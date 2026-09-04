"""Subprocess-based generic CAD export pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_profile, resolve_workspace_file, safe_output_stem
from .geometry import GeometryError, METRICS_PROGRAM, fit_to_profile


MAX_TOOL_TEXT = 12000


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
    try:
        return subprocess.run(argv, cwd=str(cwd), env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=settings.timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"CAD subprocess exceeded {settings.timeout_s}s\nstdout:\n{bounded(exc.stdout if isinstance(exc.stdout, str) else '')}\nstderr:\n{bounded(exc.stderr if isinstance(exc.stderr, str) else '')}") from exc
    except OSError as exc:
        raise ExportError(f"could not start CAD subprocess: {exc}") from exc


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
triangles = sum(mesher.triangle_counts)
print(json.dumps({
    "stl_bytes": os.path.getsize(stl_path),
    "three_mf_bytes": os.path.getsize(three_mf_path),
    "mesh_count": mesher.mesh_count,
    "triangle_counts": mesher.triangle_counts,
    "roundtrip_skipped": triangles > 100000,
    "roundtrip_skip_reason": "dense_mesh" if triangles > 100000 else None,
}, sort_keys=True))
'''


def _status_path(exports_dir: Path) -> Path:
    return exports_dir / ".vibecad-status.json"


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
        if not metrics.get("valid_brep") or not metrics.get("is_valid"):
            raise ExportError("STEP B-rep validity failed")
        if int(metrics.get("n_solids", 0)) < 1:
            raise ExportError("STEP contains no solids")
        if not bed_fit["fits"]:
            raise ExportError(f"model does not fit printer profile {profile.id}: {bed_fit['failures']}")
        meshed = decode_json(run_cad(settings, [str(cad_python(settings)), "-c", MESH_EXPORT_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(staged_step), "VIBECAD_STL_FILE": str(staged_stl), "VIBECAD_3MF_FILE": str(staged_3mf)}), "mesh export")
        if not all(path.is_file() and path.stat().st_size > 0 for path in staged):
            raise ExportError("validated build did not produce every staged artifact")
        os.replace(staged_step, final_step)
        os.replace(staged_stl, final_stl)
        os.replace(staged_3mf, final_3mf)
        result.update({"success": True, "metrics": metrics, "bed_fit": bed_fit, "mesh_export": meshed, "printer_validation": "passed"})
    except (ConfigError, GeometryError, ExportError) as exc:
        result["error"] = str(exc)
        result["printer_validation"] = "failed"
        for artifact in staged:
            artifact.unlink(missing_ok=True)
    finally:
        exports = Path(result.get("output", {}).get("step", ".")).parent if isinstance(result.get("output"), Mapping) else None
        if exports and exports.is_dir():
            atomic_json(_status_path(exports), result)
    return result


def inspect_metrics(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        step_file = resolve_workspace_file(args.get("step_file"), settings, suffixes={".step", ".stp"})
        profile = resolve_profile(settings, args)
        metrics = inspect_step(step_file, settings)
        bed_fit = fit_to_profile(metrics, profile)
        return {"success": bool(metrics.get("valid_brep")) and bool(metrics.get("is_valid")) and int(metrics.get("n_solids", 0)) > 0, "step_file": str(step_file), "metrics": metrics, "bed_fit": bed_fit, "printer_validation": "passed" if bed_fit["fits"] else "failed"}
    except (ConfigError, GeometryError, ExportError) as exc:
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
