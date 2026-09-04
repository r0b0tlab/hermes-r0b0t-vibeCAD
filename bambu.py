"""Optional Bambu Studio X2D handoff layered on the generic FDM workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, ensure_workspace, project_dirs, project_root_for, resolve_profile
from .exports import atomic_json
from .handoff import stage_for_slicer


BAMBU_X2D_PROFILE_ID = "bambu-x2d"
BAMBU_X2D_PLATE_CENTER_MM = (138.25, 128.0, 0.0)
BAMBU_X2D_COMMON_DUAL_VOLUME_MM = (235.5, 256.0, 256.0)
BAMBU_X2D_MAIN_VOLUME_MM = (256.0, 256.0, 260.0)
BAMBU_X2D_SAFE_RECTANGLE_MM = {"x_min": 20.5, "x_max": 256.0, "y_min": 0.0, "y_max": 256.0, "z_max": 256.0}
BAMBU_X2D_AUXILIARY_LIMITS = {"max_print_speed_mm_s": 200, "max_acceleration_mm_s2": 1000}


class BambuError(ValueError):
    """An X2D-specific handoff error."""


def _slots(raw: Any, labels: set[str]) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise BambuError("bambu_slots must map every part label to a positive Bambu filament slot")
    normalized: dict[str, int] = {}
    for label in labels:
        value = raw.get(label)
        if isinstance(value, bool):
            raise BambuError(f"bambu slot for {label!r} must be a positive integer")
        try:
            slot = int(value)
        except (TypeError, ValueError) as exc:
            raise BambuError(f"bambu slot for {label!r} must be a positive integer") from exc
        if slot < 1:
            raise BambuError(f"bambu slot for {label!r} must be >= 1")
        normalized[label] = slot
    extras = sorted(set(raw) - labels)
    if extras:
        raise BambuError(f"bambu_slots names parts not in solids_map: {extras}")
    return normalized


def _nozzle_for_tool(value: Any) -> str:
    if value == 0:
        return "main"
    if value == 1:
        return "auxiliary"
    return "unspecified"


def _plate_name(raw: Any) -> str:
    if raw is None:
        return "vibeCAD X2D plate"
    value = str(raw).strip()
    if not value:
        raise BambuError("plate_name must be non-empty when provided")
    return value


def stage_for_bambu(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    """Create an X2D-safe UI/CLI assembly recipe without claiming a native project."""
    try:
        profile = resolve_profile(settings, args)
        if profile.id != BAMBU_X2D_PROFILE_ID:
            raise BambuError(
                f"vibecad_stage_for_bambu requires printer_profile {BAMBU_X2D_PROFILE_ID!r}, got {profile.id!r}"
            )
        generic = stage_for_slicer(settings, args)
        if not generic.get("success"):
            return generic

        parts = list(generic["parts"])
        labels = {str(part["label"]) for part in parts}
        slots = _slots(args.get("bambu_slots"), labels)
        stls_by_label = {str(entry["label"]): entry for entry in generic["individual_stls"]}
        if set(stls_by_label) != labels:
            raise BambuError("generic staging did not produce one named STL fallback for every Bambu part")

        step_file = Path(str(generic["step_file"]))
        workspace = ensure_workspace(settings)
        project = project_root_for(step_file, workspace)
        exports_dir, _renders_dir = project_dirs(project)
        assemble_list = exports_dir / "bambu-assemble-list.json"
        handoff_manifest = exports_dir / "bambu-handoff.json"
        plate_name = _plate_name(args.get("plate_name"))

        objects = []
        bambu_parts = []
        for part in parts:
            label = str(part["label"])
            stl = stls_by_label[label]
            slot = slots[label]
            nozzle = _nozzle_for_tool(part.get("tool"))
            objects.append(
                {
                    "path": str(stl["path"]),
                    "count": 1,
                    "filaments": [slot],
                    "subtype": "normal_part",
                    "assemble_index": [1],
                    "pos_x": [BAMBU_X2D_PLATE_CENTER_MM[0]],
                    "pos_y": [BAMBU_X2D_PLATE_CENTER_MM[1]],
                    "pos_z": [BAMBU_X2D_PLATE_CENTER_MM[2]],
                }
            )
            bambu_parts.append(
                {
                    "label": label,
                    "solid_index": part["solid_index"],
                    "stl_file": str(stl["path"]),
                    "bambu_slot": slot,
                    "requested_nozzle": nozzle,
                    "requested_material": part.get("material", ""),
                    "requested_color": part.get("color", ""),
                    "role": part.get("role", "model"),
                }
            )

        assemble_payload = {
            "plates": [{"plate_name": plate_name, "need_arrange": False, "objects": objects}]
        }
        atomic_json(assemble_list, assemble_payload)
        manual_steps = [
            "For Bambu Studio UI import, select all listed individual STL files together and retain them as one multi-part object or assembly when prompted.",
            "Bind every Bambu slot in this manifest to the actual loaded printer material source; slot numbers are saved metadata, not live AMS bindings.",
            "Use the Bambu Lab X2D 0.4 mm process selected for the final slice, then inspect the complete Preview before printing.",
            "If any part uses the auxiliary hotend, keep its process at or below 200 mm/s print speed and 1000 mm/s² acceleration, and verify material/quality compatibility.",
            "The generated bambu-assemble-list.json is a CLI assembly recipe only. Use it with full, version-pinned Bambu machine/process/filament configuration and accept a native project only after Bambu Studio --info succeeds.",
        ]
        limitations = [
            "slicer-handoff.3mf remains a vendor-neutral interchange file; it is not asserted to be a Bambu-native project.",
            "This adapter deliberately does not auto-export a native Bambu 3MF: direct CLI assembly without full current Bambu configuration was observed to produce an archive that can fail Bambu Studio --info.",
            "No print is dispatched and no live AMS, material, nozzle, firmware, or process state is inferred.",
        ]
        manifest = {
            "schema_version": 2,
            "printer_profile": profile.id,
            "source_step": str(step_file),
            "generic_handoff": generic["handoff_manifest"],
            "bambu_assemble_list": str(assemble_list),
            "bambu_slots": slots,
            "parts": bambu_parts,
            "x2d_contract": {
                "shared_xy_toolhead": "main left direct-drive hotend plus right remote-fed auxiliary hotend; the heads do not move independently",
                "main_only_build_volume_mm": BAMBU_X2D_MAIN_VOLUME_MM,
                "common_dual_or_auxiliary_build_volume_mm": BAMBU_X2D_COMMON_DUAL_VOLUME_MM,
                "common_dual_safe_rectangle_mm": BAMBU_X2D_SAFE_RECTANGLE_MM,
                "plate_center_mm": BAMBU_X2D_PLATE_CENTER_MM,
                "auxiliary_hotend_limits": BAMBU_X2D_AUXILIARY_LIMITS,
            },
            "manual_bambu_steps": manual_steps,
            "limitations": limitations,
            "status": "ready_for_manual_bambu_import",
        }
        atomic_json(handoff_manifest, manifest)
        return {
            "success": True,
            **generic,
            "status": manifest["status"],
            "bambu_assemble_list": str(assemble_list),
            "bambu_handoff_manifest": str(handoff_manifest),
            "bambu_slots": slots,
            "bambu_parts": bambu_parts,
            "x2d_contract": manifest["x2d_contract"],
            "manual_bambu_steps": manual_steps,
            "limitations": limitations,
        }
    except (ConfigError, BambuError) as exc:
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
