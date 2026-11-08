"""Public runtime facade for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Mapping

from .adapters import load_adapters
from .config import ConfigError, Settings, cad_python, ensure_workspace, project_root_for, resolve_profile, resolve_workspace_file, settings_from_context
from .exports import ExportError, decode_json, execute_and_export, inspect_metrics, run_cad
from .handoff import stage_for_slicer
from .bambu import stage_for_bambu
from .parameters import modify_parameter
from .profiles import load_profile_catalog
from .renders import generate_preview_renders

CadError = ConfigError


def list_printer_profiles(settings: Settings, _args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        catalog = load_profile_catalog(settings.printer_profiles_file)
        return {
            "success": True,
            "profiles": [
                {
                    "id": profile.id,
                    "display_name": profile.display_name,
                    "technology": profile.technology,
                    "build_volume_mm": {"x": profile.bed.width_mm, "y": profile.bed.depth_mm, "z": profile.bed.height_mm},
                    "safe_margin_mm": profile.bed.safe_margin_mm,
                    "nozzle_diameter_mm": profile.nozzle_diameter_mm,
                    "tool_count": profile.tool_count,
                    "source": profile.source,
                }
                for profile in sorted(catalog.values(), key=lambda item: item.id)
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

_MESH_PROGRAM = r'''
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("vibecad_mesh_bridge", os.environ["VIBECAD_MESH_MODULE"])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
try:
    result = module.import_stl(**json.loads(os.environ["VIBECAD_MESH_ARGS"]))
    print(json.dumps({"success": True, **result}))
except (module.MeshImportError, OSError) as exc:
    print(json.dumps({"success": False, "error": str(exc)}))
'''


def prepare_mesh(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and size a trusted local single-shell STL in the CAD sidecar."""
    try:
        root = ensure_workspace(settings)
        source = resolve_workspace_file(args.get("mesh_file"), settings, suffixes={".stl"})
        project = project_root_for(source, root)
        profile = resolve_profile(settings, args)
        margin = profile.bed.safe_margin_mm
        envelope = [profile.bed.width_mm - 2 * margin, profile.bed.depth_mm - 2 * margin, profile.bed.height_mm]
        adapter = load_adapters().get(profile.id)
        if adapter:
            physical = adapter.build_volume_mm
            envelope = [min(envelope[0], physical[0] - 2 * margin), min(envelope[1], physical[1] - 2 * margin), min(envelope[2], physical[2])]
        options = {"workspace_root": str(root), "project_root": str(project), "source_path": args["mesh_file"],
                   "dimension_mm": args.get("height_mm"), "axis": "z", "envelope_mm": envelope}
        completed = run_cad(settings, [str(cad_python(settings)), "-c", _MESH_PROGRAM], cwd=project,
                            env_updates={"VIBECAD_MESH_MODULE": str(Path(__file__).parent / "mesh_bridge.py"),
                                         "VIBECAD_MESH_ARGS": json.dumps(options)})
        result = decode_json(completed, "mesh preparation")
        if result.get("success"):
            result.update({"printer_profile": profile.id, "envelope_mm": envelope,
                           "note": "Geometry only: not sliced, not a native printer project, and not proof of printability or anatomy."})
        return result
    except (ConfigError, ExportError, OSError, ValueError) as exc:
        return {"success": False, "error": str(exc)}


__all__ = [
    "CadError",
    "Settings",
    "settings_from_context",
    "list_printer_profiles",
    "execute_and_export",
    "inspect_metrics",
    "prepare_mesh",
    "generate_preview_renders",
    "modify_parameter",
    "stage_for_slicer",
    "stage_for_bambu",
]
