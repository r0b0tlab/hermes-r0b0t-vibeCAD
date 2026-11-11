"""Subprocess-based generic CAD export pipeline."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_profile, resolve_workspace_file, safe_output_stem
from .geometry import GeometryError, METRICS_PROGRAM, fit_to_profile, nozzle_warnings, overlapping_solids


MAX_TOOL_TEXT = 12000
MAX_CAPTURE_BYTES = 1024 * 1024


class ExportError(ValueError):
    """A model execution, CAD validation, or artifact publication error."""


class CadCancelled(ExportError):
    """The host requested cooperative cancellation on this tool thread."""


def _check_cancelled() -> None:
    # Hermes has no documented plugin cancellation API as of this integration.
    # This host-internal hook is optional only when the module is absent, so
    # standalone Python still works. Other import/API failures must not silently
    # claim that cancellation is supported.
    try:
        from tools.interrupt import is_interrupted
    except ModuleNotFoundError as exc:
        if exc.name not in ("tools", "tools.interrupt"):
            raise
        return
    if is_interrupted():
        raise CadCancelled("CAD operation cancelled by host")


def bounded(text: str | None, limit: int = MAX_TOOL_TEXT) -> str:
    value = text or ""
    return value if len(value) <= limit else value[: limit // 2] + "\n… [truncated] …\n" + value[-limit // 2 :]


def _wait_readable(fd: int, timeout: float) -> bool:
    # Avoid select(2)'s FD_SETSIZE limit in long-lived Hermes processes.
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        return bool(selector.select(timeout))


def run_cad(settings: Settings, argv: list[str], *, cwd: Path, env_updates: Mapping[str, str] | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[str]:
    """Run CAD and clean up its owned process group where POSIX permits it.

    This is not a sandbox: descendants can leave the group or become
    unsignalable. Windows cleanup covers only the direct child, not its tree.
    POSIX uses an isolated supervisor so host-wide child reapers cannot steal
    the CAD group anchor or its exit status.
    """
    _check_cancelled()
    # Do not pass provider credentials, Python injection settings or inherited
    # VIBECAD_* values to the CAD child. This is not a filesystem sandbox.
    permitted = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR",
                 "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
    environment = {key: os.environ[key] for key in permitted if key in os.environ}
    environment.update({"PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "MPLBACKEND": "Agg"})
    if env_updates:
        if any(not isinstance(key, str) or not key.startswith("VIBECAD_") for key in env_updates):
            raise ExportError("invalid CAD subprocess environment key")
        environment.update({key: str(value) for key, value in env_updates.items()})

    # Drain both pipes continuously while retaining only their beginning and end.
    # This bounds memory even when trusted model code emits unlimited diagnostics.
    captures: list[bytearray] = [bytearray(), bytearray()]
    totals = [0, 0]

    def drain(pipe: Any, index: int) -> None:
        half = MAX_CAPTURE_BYTES // 2
        while chunk := pipe.read(65536):
            totals[index] += len(chunk)
            captures[index].extend(chunk)
            if len(captures[index]) > MAX_CAPTURE_BYTES:
                captures[index][:] = captures[index][:half] + captures[index][-half:]
        pipe.close()

    def captured(index: int) -> str:
        value = bytes(captures[index])
        if totals[index] > MAX_CAPTURE_BYTES:
            half = MAX_CAPTURE_BYTES // 2
            value = value[:half] + b"\n... [capture truncated] ...\n" + value[-half:]
        return value.decode("utf-8", errors="replace")

    control_read = control_write = report_read = report_write = None
    try:
        if os.name == "posix":
            control_read, control_write = os.pipe()
            report_read, report_write = os.pipe()
            helper = str(Path(__file__).with_name("_cad_supervisor.py"))
            command = [sys.executable, helper, "supervise", str(control_read), str(report_write), str(settings.timeout_s), *argv]
            process = subprocess.Popen(command, cwd=str(cwd), env=environment, stdin=subprocess.PIPE if input_bytes is not None else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(control_read, report_write))
        else:
            process = subprocess.Popen(argv, cwd=str(cwd), env=environment, stdin=subprocess.PIPE if input_bytes is not None else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        for fd in (control_read, control_write, report_read, report_write):
            if fd is not None:
                os.close(fd)
        raise ExportError(f"could not start CAD subprocess: {exc}") from exc
    if os.name == "posix":
        os.close(control_read)
        os.close(report_write)
    threads = []
    writer = None
    timed_out = False
    returncode = None
    reported = False
    try:
        for index, pipe in enumerate((process.stdout, process.stderr)):
            thread = threading.Thread(target=drain, args=(pipe, index), daemon=True)
            thread.start()
            threads.append(thread)
        if input_bytes is not None:
            def feed_snapshot() -> None:
                try:
                    pipe = process.stdin
                    assert pipe is not None
                    with pipe:
                        pipe.write(input_bytes)
                except (BrokenPipeError, OSError):
                    pass
            writer = threading.Thread(target=feed_snapshot, daemon=True)
            writer.start()
        if os.name == "posix":
            # The helper reports only after it has waited for its anchor's
            # SIGKILL. This dedicated pipe is independent of host waitpid.
            deadline = time.monotonic() + settings.timeout_s + 10
            while True:
                _check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExportError("CAD supervision did not report cleanup")
                if _wait_readable(report_read, min(remaining, 0.1)):
                    break
            _check_cancelled()
            raw = os.read(report_read, 65536)
            reported = True
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ExportError("CAD supervisor exited without a valid cleanup report") from exc
            if result.get("error"):
                raise ExportError(result["error"])
            timed_out = bool(result.get("timeout"))
            if not timed_out:
                returncode = result.get("returncode")
                if not isinstance(returncode, int):
                    raise ExportError("CAD supervisor returned no process status")
        else:
            deadline = time.monotonic() + settings.timeout_s
            while True:
                _check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    returncode = process.wait(timeout=min(remaining, 0.1))
                    break
                except subprocess.TimeoutExpired:
                    continue
            _check_cancelled()
    finally:
        if os.name == "posix":
            # EOF requests cleanup even if the calling thread is cancelled or
            # the host exits. Never signal the helper by a recyclable PID.
            os.close(control_write)
            if not reported:
                ready = _wait_readable(report_read, 5)
                if not ready:
                    os.close(report_read)
                    raise ExportError("CAD supervisor did not confirm cleanup")
                try:
                    cleanup = json.loads(os.read(report_read, 65536))
                    if cleanup.get("error"):
                        raise ExportError(cleanup["error"])
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ExportError("CAD supervisor did not confirm cleanup") from exc
            os.close(report_read)
        elif process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise ExportError("CAD supervisor did not exit after cleanup request") from exc
        finally:
            for thread in threads:
                thread.join(timeout=1)
            if writer is not None:
                writer.join(timeout=1)
    _check_cancelled()
    stdout, stderr = captured(0), captured(1)
    if timed_out:
        raise ExportError(f"CAD subprocess exceeded {settings.timeout_s}s\nstdout:\n{bounded(stdout)}\nstderr:\n{bounded(stderr)}")
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def decode_json(completed: subprocess.CompletedProcess[str], operation: str) -> dict[str, Any]:
    if completed.returncode != 0:
        raise ExportError(f"{operation} failed with exit code {completed.returncode}\nstdout:\n{bounded(completed.stdout)}\nstderr:\n{bounded(completed.stderr)}")
    for line in reversed((completed.stdout or "").splitlines()):
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    raise ExportError(f"{operation} produced no JSON payload\nstdout:\n{bounded(completed.stdout)}\nstderr:\n{bounded(completed.stderr)}")


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def step_product_names(step_file: Path) -> list[str]:
    text = step_file.read_text(encoding="latin1", errors="replace")
    names: list[str] = []
    for raw in re.findall(r"\bPRODUCT\('((?:''|[^'])*)'", text):
        name = raw.replace("''", "'").strip()
        if name and name not in names:
            names.append(name)
    return names


def inspect_step(step_file: Path, settings: Settings) -> dict[str, Any]:
    completed = run_cad(settings, [str(cad_python(settings)), "-c", METRICS_PROGRAM], cwd=step_file.parent, env_updates={"VIBECAD_STEP_FILE": str(step_file)})
    metrics = decode_json(completed, "STEP inspection")
    metrics["step_product_names"] = step_product_names(step_file)
    return metrics


MESH_EXPORT_PROGRAM = r'''
import json
import os
from build123d import Mesher, export_stl, import_step

shape = import_step(os.environ["VIBECAD_STEP_FILE"])
stl_path = os.environ["VIBECAD_STL_FILE"]
three_mf_path = os.environ["VIBECAD_3MF_FILE"]
export_stl(shape, stl_path, tolerance=0.02, angular_tolerance=0.1)
mesher = Mesher()
mesher.add_shape(shape, linear_deflection=0.02, angular_deflection=0.1)
mesher.write(three_mf_path)
print(json.dumps({
    "stl_bytes": os.path.getsize(stl_path),
    "three_mf_bytes": os.path.getsize(three_mf_path),
    "mesh_count": mesher.mesh_count,
    "triangle_counts": mesher.triangle_counts,
    "roundtrip_skipped": True,
    "roundtrip_skip_reason": "not_performed",
}, sort_keys=True))
'''


def _status_path(exports_dir: Path) -> Path:
    return exports_dir / ".vibecad-status.json"


@contextmanager
def _publication_lock(exports_dir: Path):
    """Serialize cooperating writers, including status, across processes."""
    with (exports_dir / ".vibecad-publication.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b"0")
                handle.flush()
        else:
            import fcntl
        # The host may clear its thread-scoped interrupt after abandoning a
        # worker. Never sit in a blocking lock call throughout that window.
        while True:
            _check_cancelled()
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                contention = (errno.EACCES, errno.EAGAIN)
                if os.name == "nt":
                    contention += (errno.EDEADLK,)
                if exc.errno not in contention:
                    raise
                time.sleep(0.1)
        try:
            _check_cancelled()
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _publish_artifacts(pairs: list[tuple[Path, Path]], exports_dir: Path) -> None:
    """Replace a set with rollback on ordinary I/O errors; caller holds lock.

    Stable individual paths cannot provide an atomic snapshot to unlocked readers
    or recover automatically from a process/machine crash during publication.
    """
    backup_dir = Path(tempfile.mkdtemp(prefix=".vibecad-backup-", dir=exports_dir))
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    preserve_backup = False
    try:
        for _source, target in pairs:
            if target.exists():
                backup = backup_dir / target.name
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None
        for source, target in pairs:
            _check_cancelled()
            os.replace(source, target)
            replaced.append(target)
        _check_cancelled()
    except (OSError, CadCancelled) as exc:
        failures = []
        for target in reversed(replaced):
            try:
                backup = backups[target]
                if backup is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(backup, target)
            except OSError as rollback_exc:
                failures.append(f"{target}: {rollback_exc}")
        if failures:
            preserve_backup = True
            raise ExportError(f"publication failed: {exc}; rollback failed: {'; '.join(failures)}; recovery backups retained at {backup_dir}") from exc
        if isinstance(exc, CadCancelled):
            raise
        raise ExportError(f"publication failed; previous artifacts restored: {exc}") from exc
    finally:
        if not preserve_backup:
            shutil.rmtree(backup_dir, ignore_errors=True)


_SNAPSHOT_RUNNER = '''
import hashlib, sys
from pathlib import Path
source = sys.stdin.buffer.read()
script = sys.argv[1]
if hashlib.sha256(source).hexdigest() != sys.argv[2]:
    raise RuntimeError("approved script snapshot was truncated or corrupted")
sys.argv = [script]
sys.path[0] = str(Path(script).parent)
__file__ = script
code = compile(source, script, "exec")
del source, script
exec(code, globals())
'''


def execute_and_export(settings: Settings, args: Mapping[str, Any], *, _approved_script: tuple[Path, bytes] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False}
    staged: list[Path] = []
    try:
        script = _approved_script[0] if _approved_script is not None else resolve_workspace_file(args.get("script_path"), settings, suffixes={".py"})
        profile = resolve_profile(settings, args)
        stem = safe_output_stem(args.get("output_name"))
        workspace = ensure_workspace(settings)
        project = project_root_for(script, workspace)
        exports_dir, _renders_dir = project_dirs(project)
        final_step = exports_dir / f"{stem}.step"
        final_stl = exports_dir / f"{stem}.stl"
        final_3mf = exports_dir / f"{stem}.3mf"
        nonce = f"{os.getpid()}.{time.time_ns()}"
        staged_step = exports_dir / f"{stem}.staging.{nonce}.step"
        staged_stl = exports_dir / f"{stem}.staging.{nonce}.stl"
        staged_3mf = exports_dir / f"{stem}.staging.{nonce}.3mf"
        staged = [staged_step, staged_stl, staged_3mf]
        for artifact in staged:
            artifact.unlink(missing_ok=True)
        env_updates = {"VIBECAD_OUTPUT_STEP": str(staged_step), "VIBECAD_OUTPUT_DIR": str(exports_dir), "VIBECAD_PROJECT_ROOT": str(project)}
        if _approved_script is None:
            execution = run_cad(settings, [str(cad_python(settings)), str(script)], cwd=project, env_updates=env_updates)
        else:
            execution = run_cad(settings, [str(cad_python(settings)), "-c", _SNAPSHOT_RUNNER, str(script), hashlib.sha256(_approved_script[1]).hexdigest()], cwd=project, env_updates=env_updates, input_bytes=_approved_script[1])
        result.update({"script_path": str(script), "project_root": str(project), "output": {"step": str(final_step), "stl": str(final_stl), "3mf": str(final_3mf)}, "return_code": execution.returncode, "stdout": bounded(execution.stdout), "stderr": bounded(execution.stderr), "printer_profile": profile.id})
        if execution.returncode != 0:
            raise ExportError("model execution failed")
        if not staged_step.is_file() or staged_step.stat().st_size <= 0:
            raise ExportError("model exited without writing VIBECAD_OUTPUT_STEP")
        metrics = inspect_step(staged_step, settings)
        bed_fit = fit_to_profile(metrics, profile)
        warnings = nozzle_warnings(metrics, profile)
        if not metrics.get("valid_brep") or not metrics.get("is_valid"):
            raise ExportError("STEP B-rep validity failed")
        if int(metrics.get("n_solids", 0)) < 1:
            raise ExportError("STEP contains no solids")
        if not bed_fit["fits"]:
            raise ExportError(f"model does not fit printer profile {profile.id}: {bed_fit['failures']}")
        overlaps = overlapping_solids(metrics)
        if overlaps:
            raise ExportError(f"STEP solids overlap in volume: {overlaps}")
        meshed = decode_json(run_cad(settings, [str(cad_python(settings)), "-c", MESH_EXPORT_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(staged_step), "VIBECAD_STL_FILE": str(staged_stl), "VIBECAD_3MF_FILE": str(staged_3mf)}), "mesh export")
        if not all(path.is_file() and path.stat().st_size > 0 for path in staged):
            raise ExportError("validated build did not produce every staged artifact")
        result.update({"success": True, "metrics": metrics, "bed_fit": bed_fit, "fdm_warnings": warnings, "mesh_export": meshed, "printer_validation": "passed"})
        staged_status = exports_dir / f".vibecad-status.{nonce}.tmp"
        staged.append(staged_status)
        staged_status.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with _publication_lock(exports_dir):
            _check_cancelled()
            _publish_artifacts(list(zip(staged[:3], [final_step, final_stl, final_3mf])) + [(staged_status, _status_path(exports_dir))], exports_dir)
    except (ConfigError, GeometryError, ExportError, OSError) as exc:
        result["success"] = False
        result["error"] = str(exc)
        result["printer_validation"] = "failed"
        exports = Path(result["output"]["step"]).parent if isinstance(result.get("output"), Mapping) else None
        if exports and exports.is_dir() and not isinstance(exc, CadCancelled):
            try:
                with _publication_lock(exports):
                    _check_cancelled()
                    atomic_json(_status_path(exports), result)
            except CadCancelled as cancel_exc:
                result["error"] = str(cancel_exc)
            except OSError as status_exc:
                result["status_error"] = str(status_exc)
    finally:
        for artifact in staged:
            try:
                artifact.unlink(missing_ok=True)
            except OSError:
                pass
    return result


def inspect_metrics(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        step_file = resolve_workspace_file(args.get("step_file"), settings, suffixes={".step", ".stp"})
        profile = resolve_profile(settings, args)
        metrics = inspect_step(step_file, settings)
        bed_fit = fit_to_profile(metrics, profile)
        overlaps = overlapping_solids(metrics)
        reasons: list[str] = []
        if not metrics.get("valid_brep") or not metrics.get("is_valid"):
            reasons.append("STEP B-rep validity failed")
        if int(metrics.get("n_solids", 0)) < 1:
            reasons.append("STEP contains no solids")
        if not bed_fit["fits"]:
            reasons.append(f"model does not fit printer profile {profile.id}: {bed_fit['failures']}")
        if overlaps:
            reasons.append(f"STEP solids overlap in volume: {overlaps}")
        valid = not reasons
        result: dict[str, Any] = {
            "success": valid,
            "step_file": str(step_file),
            "metrics": metrics,
            "bed_fit": bed_fit,
            "fdm_warnings": nozzle_warnings(metrics, profile),
            "printer_validation": "passed" if valid else "failed",
        }
        if reasons:
            result["error"] = "; ".join(reasons)
        return result
    except (ConfigError, GeometryError, ExportError, OSError) as exc:
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
