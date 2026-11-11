"""Vendor-neutral multipart 3MF/STL slicer handoff."""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_profile, resolve_workspace_file
from .exports import ExportError, WRITE_3MF_SNIPPET, atomic_json, decode_json, inspect_step, run_cad, sha256
from .geometry import GeometryError, fit_to_profile, overlapping_solids


class HandoffError(ValueError):
    """Invalid material mapping or generic slicer handoff request."""


STAGE_PROGRAM = WRITE_3MF_SNIPPET + r'''
import json
import os
from build123d import Color, export_stl, import_step

shape = import_step(os.environ["VIBECAD_STEP_FILE"])
parts = json.loads(os.environ["VIBECAD_PART_MAP"])
out_path = os.environ["VIBECAD_SLICER_3MF"]
solids = list(shape.solids())
# Labels belong to assembly nodes, not to shape.solids() wrappers.  Associate
# the exact imported topology, never PRODUCT text, order, volume or bounds.
nodes = []
def visit(node):
    nodes.append(node)
    for child in node.children:
        visit(child)
visit(shape)
for entry in parts:
    matches = [node for node in nodes if node.label == entry["label"]]
    if len(matches) != 1:
        raise ValueError("STEP identity: label %r is absent or ambiguous" % entry["label"])
    named_solids = list(matches[0].solids())
    if len(named_solids) != 1 or not named_solids[0].wrapped.IsSame(solids[entry["solid_index"] - 1].wrapped):
        raise ValueError("STEP identity: label %r does not identify solid_index %s" % (entry["label"], entry["solid_index"]))
files = []
for entry in parts:
    solid = solids[entry["solid_index"] - 1]
    solid.label = entry["label"]
    if entry.get("color"):
        solid.color = Color(entry["color"])
    export_stl(solid, entry["stl_file"], tolerance=0.02, angular_tolerance=0.1)
    files.append({"label": entry["label"], "path": entry["stl_file"], "bytes": os.path.getsize(entry["stl_file"])})
mesh_count, triangle_counts = write_assembly_3mf(out_path, parts)
print(json.dumps({"bytes": os.path.getsize(out_path), "mesh_count": mesh_count, "triangle_counts": triangle_counts, "individual_stls": files}, sort_keys=True))
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
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise HandoffError(f"solid_index for {label!r} must be an integer")
        index = raw_index
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
        normalized.append({"label": label, "solid_index": index, "material": str(details.get("material") or "").strip(), "color": color, "tool": tool, "role": role})
        used.add(index)
    expected = set(range(1, solids + 1))
    if used != expected:
        raise HandoffError(f"solids_map must cover every solid exactly once; missing {sorted(expected - used)}")
    return sorted(normalized, key=lambda item: item["solid_index"])


def stage_for_slicer(settings: Settings, args: Mapping[str, Any], *, physical_volume: tuple[float, float, float] | None = None, physical_tools: int | None = None) -> dict[str, Any]:
    # Every invocation gets immutable, uniquely named artifacts. Existing ready
    # manifests and the files they reference are never overwritten.
    revision: Path | None = None
    success = False
    try:
        step_file = resolve_workspace_file(args.get("step_file"), settings, suffixes={".step", ".stp"})
        profile = resolve_profile(settings, args)
        workspace = ensure_workspace(settings)
        project = project_root_for(step_file, workspace)
        exports_dir, _renders_dir = project_dirs(project)
        revision_parent = exports_dir / "handoff-revisions"
        if revision_parent.is_symlink():
            raise HandoffError("handoff revision directory must not be a symlink")
        revision_parent.mkdir(exist_ok=True)
        if (revision_parent.is_symlink() or not revision_parent.is_dir()
                or revision_parent.resolve().parent != exports_dir.resolve()):
            raise HandoffError("handoff revision directory must stay in exports")
        candidate = revision_parent / uuid.uuid4().hex
        candidate.mkdir(exist_ok=False)
        revision = candidate
        source_hash = sha256(step_file)
        snapshot = revision / "source.step"
        shutil.copyfile(step_file, snapshot)
        if sha256(snapshot) != source_hash or sha256(step_file) != source_hash:
            raise HandoffError("source STEP changed during snapshot")
        metrics = inspect_step(snapshot, settings)
        solids = int(metrics.get("n_solids", 0))
        if solids < 1 or not metrics.get("valid_brep") or not metrics.get("is_valid"):
            raise HandoffError("STEP must contain valid printable solids")
        fit = fit_to_profile(metrics, profile)
        if not fit["fits"]:
            raise HandoffError(f"model does not fit printer profile {profile.id}: {fit['failures']}")
        if physical_volume is not None:
            bed = replace(profile.bed, width_mm=physical_volume[0], depth_mm=physical_volume[1], height_mm=physical_volume[2], safe_margin_mm=0.0)
            physical_fit = fit_to_profile(metrics, replace(profile, bed=bed))
            if not physical_fit["fits"]:
                raise HandoffError(f"model does not fit adapter physical envelope: {physical_fit['failures']}")
        overlaps = overlapping_solids(metrics)
        if overlaps:
            raise HandoffError(f"STEP solids overlap in volume: {overlaps}")
        parts = _normalize_map(args.get("solids_map"), solids=solids, tool_count=min(profile.tool_count, physical_tools) if physical_tools else profile.tool_count)
        multipart = revision / "slicer-handoff.3mf"
        manifest_path = revision / "slicer-handoff.json"
        for part in parts:
            part["stl_file"] = str(revision / _component_filename(part["label"], part["solid_index"]))
        result = decode_json(run_cad(settings, [str(cad_python(settings)), "-c", STAGE_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(snapshot), "VIBECAD_SLICER_3MF": str(multipart), "VIBECAD_PART_MAP": json.dumps(parts)}), "generic slicer staging")
        individual = result.get("individual_stls") or []
        if not multipart.is_file() or multipart.stat().st_size <= 0 or len(individual) != solids:
            raise HandoffError("generic multipart export did not produce every expected artifact")
        if [(x.get("label"), x.get("path")) for x in individual] != [(p["label"], p["stl_file"]) for p in parts]:
            raise HandoffError("generic staging returned unexpected STL paths")
        for entry in individual:
            artifact = Path(entry["path"])
            if not artifact.is_file() or artifact.stat().st_size <= 0:
                raise HandoffError("generic staging produced a missing or empty STL")
            entry["sha256"] = sha256(artifact)
        if sha256(snapshot) != source_hash or sha256(step_file) != source_hash:
            raise HandoffError("source STEP changed during staging")
        manifest = {
            "schema_version": 1,
            "generated_at_epoch_s": time.time(),
            "printer_profile": profile.id,
            "source_step": str(step_file),
            "source_step_sha256": source_hash,
            "source_step_snapshot": str(snapshot),
            "metrics": metrics,
            "bed_fit": fit,
            "staged_3mf": str(multipart),
            "staged_3mf_sha256": sha256(multipart),
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
                "Generic 3MF encodes both support and support_interface roles as SUPPORT; interface-specific behavior must be set and verified in the slicer.",
            ],
        }
        atomic_json(manifest_path, manifest)
        success = True
        return {"success": True, "step_file": str(step_file), "staged_3mf": str(multipart), "handoff_manifest": str(manifest_path), "individual_stls": individual, "parts": manifest["parts"], "bed_fit": fit, "printer_validation": "passed"}
    except (ConfigError, GeometryError, ExportError, HandoffError, OSError) as exc:
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
    finally:
        if revision is not None and not success:
            shutil.rmtree(revision, ignore_errors=True)
