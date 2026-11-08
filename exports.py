"""Subprocess-based generic CAD export pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_profile, resolve_workspace_file, safe_output_stem
from .geometry import GeometryError, METRICS_PROGRAM, fit_to_profile, nozzle_warnings


MAX_TOOL_TEXT = 12000
MAX_CAPTURE_BYTES = 1024 * 1024


class ExportError(ValueError):
    """A model execution, CAD validation, or artifact publication error."""


def bounded(text: str | None, limit: int = MAX_TOOL_TEXT) -> str:
    value = text or ""
    return value if len(value) <= limit else value[: limit // 2] + "\n… [truncated] …\n" + value[-limit // 2 :]


def run_cad(settings: Settings, argv: list[str], *, cwd: Path, env_updates: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"PYTHONUNBUFFERED": "1", "MPLBACKEND": "Agg"})
    if env_updates:
        environment.update({key: str(value) for key, value in env_updates.items()})
    environment["PYTHONNOUSERSITE"] = "1"
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
        environment.pop(key, None)

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

    try:
        process = subprocess.Popen(argv, cwd=str(cwd), env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=(os.name == "posix"))
    except OSError as exc:
        raise ExportError(f"could not start CAD subprocess: {exc}") from exc
    threads = [threading.Thread(target=drain, args=(pipe, index), daemon=True) for index, pipe in enumerate((process.stdout, process.stderr))]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=settings.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
    for thread in threads:
        thread.join(timeout=1)
    stdout, stderr = captured(0), captured(1)
    if timed_out:
        raise ExportError(f"CAD subprocess exceeded {settings.timeout_s}s\nstdout:\n{bounded(stdout)}\nstderr:\n{bounded(stderr)}")
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


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
            handle.seek(0)
            # LK_LOCK retries internally, then fails rather than hanging forever.
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
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
            os.replace(source, target)
            replaced.append(target)
    except OSError as exc:
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
        raise ExportError(f"publication failed; previous artifacts restored: {exc}") from exc
    finally:
        if not preserve_backup:
            shutil.rmtree(backup_dir, ignore_errors=True)


def execute_and_export(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False}
    staged: list[Path] = []
    try:
        script = resolve_workspace_file(args.get("script_path"), settings, suffixes={".py"})
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
        execution = run_cad(settings, [str(cad_python(settings)), str(script)], cwd=project, env_updates={"VIBECAD_OUTPUT_STEP": str(staged_step), "VIBECAD_OUTPUT_DIR": str(exports_dir), "VIBECAD_PROJECT_ROOT": str(project)})
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
        meshed = decode_json(run_cad(settings, [str(cad_python(settings)), "-c", MESH_EXPORT_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(staged_step), "VIBECAD_STL_FILE": str(staged_stl), "VIBECAD_3MF_FILE": str(staged_3mf)}), "mesh export")
        if not all(path.is_file() and path.stat().st_size > 0 for path in staged):
            raise ExportError("validated build did not produce every staged artifact")
        result.update({"success": True, "metrics": metrics, "bed_fit": bed_fit, "fdm_warnings": warnings, "mesh_export": meshed, "printer_validation": "passed"})
        staged_status = exports_dir / f".vibecad-status.{nonce}.tmp"
        staged.append(staged_status)
        staged_status.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with _publication_lock(exports_dir):
            _publish_artifacts(list(zip(staged[:3], [final_step, final_stl, final_3mf])) + [(staged_status, _status_path(exports_dir))], exports_dir)
    except (ConfigError, GeometryError, ExportError, OSError) as exc:
        result["success"] = False
        result["error"] = str(exc)
        result["printer_validation"] = "failed"
        exports = Path(result["output"]["step"]).parent if isinstance(result.get("output"), Mapping) else None
        if exports and exports.is_dir():
            try:
                with _publication_lock(exports):
                    atomic_json(_status_path(exports), result)
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
        valid = bool(metrics.get("valid_brep")) and bool(metrics.get("is_valid")) and int(metrics.get("n_solids", 0)) > 0 and bed_fit["fits"]
        return {"success": valid, "step_file": str(step_file), "metrics": metrics, "bed_fit": bed_fit, "fdm_warnings": nozzle_warnings(metrics, profile), "printer_validation": "passed" if valid else "failed"}
    except (ConfigError, GeometryError, ExportError) as exc:
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
