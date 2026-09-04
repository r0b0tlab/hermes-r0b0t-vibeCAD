"""Vendor-neutral multipart 3MF/STL slicer handoff."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_profile, resolve_workspace_file
from .exports import ExportError, atomic_json, decode_json, inspect_step, run_cad, sha256
from .geometry import GeometryError, fit_to_profile


class HandoffError(ValueError):
    """Invalid material mapping or generic slicer handoff request."""


STAGE_PROGRAM = r'''
import json
import os
from build123d import Color, MeshType, Mesher, export_stl, import_step

shape = import_step(os.environ["VIBECAD_STEP_FILE"])
parts = json.loads(os.environ["VIBECAD_PART_MAP"])
out_path = os.environ["VIBECAD_SLICER_3MF"]
solids = list(shape.solids())
mesher = Mesher()
files = []
for entry in parts:
    solid = solids[entry["solid_index"] - 1]
    solid.label = entry["label"]
    if entry.get("color"):
        solid.color = Color(entry["color"])
    export_stl(solid, entry["stl_file"], tolerance=0.02, angular_tolerance=0.1)
    files.append({"label": entry["label"], "path": entry["stl_file"], "bytes": os.path.getsize(entry["stl_file"])})
    mesh_type = MeshType.SUPPORT if entry["role"] in {"support", "support_interface"} else MeshType.MODEL
    mesher.add_shape(solid, linear_deflection=0.02, angular_deflection=0.1, mesh_type=mesh_type)
mesher.write(out_path)
print(json.dumps({"bytes": os.path.getsize(out_path), "mesh_count": mesher.mesh_count, "triangle_counts": mesher.triangle_counts, "individual_stls": files}, sort_keys=True))
'''


def _component_filename(label: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip(".-") or f"solid-{index}"
    return f"component-{index:02d}-{slug}.stl"


def _normalize_map(raw: Any, *, solids: int, tool_count: int) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping) or not raw:
        raise HandoffError("solids_map must map every labeled STEP solid exactly once")
    used: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for label, details in raw.items():
        if not isinstance(label, str) or not label.strip() or not isinstance(details, Mapping):
            raise HandoffError("each solids_map entry needs a non-empty label and object value")
        raw_index = details.get("solid_index")
        if isinstance(raw_index, bool):
            raise HandoffError(f"solid_index for {label!r} must be an integer")
        try:
            index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise HandoffError(f"solid_index for {label!r} must be an integer") from exc
        if index < 1 or index > solids or index in used:
            raise HandoffError(f"solid_index for {label!r} must uniquely identify one of 1..{solids}")
        role = str(details.get("role") or "model").strip().lower()
        if role not in {"model", "accent", "support", "support_interface"}:
            raise HandoffError(f"role for {label!r} is unsupported: {role!r}")
        tool = details.get("tool")
        if tool is not None:
            if isinstance(tool, bool) or not isinstance(tool, int) or tool < 0 or tool >= tool_count:
                raise HandoffError(f"tool for {label!r} must be an integer in 0..{tool_count - 1}")
        color = str(details.get("color") or "").strip()
        if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise HandoffError(f"color for {label!r} must match #RRGGBB")
        normalized.append({"label": label.strip(), "solid_index": index, "material": str(details.get("material") or "").strip(), "color": color, "tool": tool, "role": role})
        used.add(index)
    expected = set(range(1, solids + 1))
    if used != expected:
        raise HandoffError(f"solids_map must cover every solid exactly once; missing {sorted(expected - used)}")
    return sorted(normalized, key=lambda item: item["solid_index"])


def stage_for_slicer(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    staged_files: list[Path] = []
    try:
        step_file = resolve_workspace_file(args.get("step_file"), settings, suffixes={".step", ".stp"})
        profile = resolve_profile(settings, args)
        metrics = inspect_step(step_file, settings)
        solids = int(metrics.get("n_solids", 0))
        if solids < 1 or not metrics.get("valid_brep") or not metrics.get("is_valid"):
            raise HandoffError("STEP must contain valid printable solids")
        fit = fit_to_profile(metrics, profile)
        if not fit["fits"]:
            raise HandoffError(f"model does not fit printer profile {profile.id}: {fit['failures']}")
        overlaps = [entry for entry in metrics.get("intersections", []) if float(entry.get("overlap_volume_mm3", 0)) > 1e-6]
        if overlaps:
            raise HandoffError(f"STEP solids overlap in volume: {overlaps}")
        parts = _normalize_map(args.get("solids_map"), solids=solids, tool_count=profile.tool_count)
        known_names = set(metrics.get("step_product_names") or [])
        missing_names = [entry["label"] for entry in parts if entry["label"] not in known_names]
        if missing_names:
            raise HandoffError(f"STEP is missing stable component labels: {missing_names}")
        workspace = ensure_workspace(settings)
        project = project_root_for(step_file, workspace)
        exports_dir, _renders_dir = project_dirs(project)
        multipart = exports_dir / "slicer-handoff.3mf"
        manifest_path = exports_dir / "slicer-handoff.json"
        for part in parts:
            stl = exports_dir / _component_filename(part["label"], part["solid_index"])
            stl.unlink(missing_ok=True)
            part["stl_file"] = str(stl)
            staged_files.append(stl)
        multipart.unlink(missing_ok=True)
        staged_files.append(multipart)
        result = decode_json(run_cad(settings, [str(cad_python(settings)), "-c", STAGE_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(step_file), "VIBECAD_SLICER_3MF": str(multipart), "VIBECAD_PART_MAP": json.dumps(parts)}), "generic slicer staging")
        individual = result.get("individual_stls") or []
        if not multipart.is_file() or multipart.stat().st_size <= 0 or len(individual) != solids:
            raise HandoffError("generic multipart export did not produce every expected artifact")
        manifest = {
            "schema_version": 1,
            "generated_at_epoch_s": time.time(),
            "printer_profile": profile.id,
            "source_step": str(step_file),
            "source_step_sha256": sha256(step_file),
            "metrics": metrics,
            "bed_fit": fit,
            "staged_3mf": str(multipart),
            "individual_stls": individual,
            "parts": [{key: value for key, value in entry.items() if key != "stl_file"} | {"stl_file": entry["stl_file"]} for entry in parts],
            "manual_slicer_steps": [
                "Import the multipart 3MF or all component STL files into your slicer as one assembly.",
                "Assign each part's material/color/tool metadata manually after checking the slicer's own profile and loaded materials.",
                "Inspect the slicer preview before printing; this plugin never sends a print or claims automatic assignment.",
            ],
            "limitations": [
                "Material, color, and tool fields are reviewable mapping metadata, not automatic slicer commands.",
                "No vendor-specific project file or printer dispatch is generated.",
            ],
        }
        atomic_json(manifest_path, manifest)
        return {"success": True, "step_file": str(step_file), "staged_3mf": str(multipart), "handoff_manifest": str(manifest_path), "individual_stls": individual, "parts": manifest["parts"], "bed_fit": fit, "printer_validation": "passed"}
    except (ConfigError, GeometryError, ExportError, HandoffError) as exc:
        for path in staged_files:
            path.unlink(missing_ok=True)
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
