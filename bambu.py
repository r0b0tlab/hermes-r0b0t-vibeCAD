"""Optional Bambu Studio handoff layered on the generic FDM workflow."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .adapters import AdapterError, BambuAdapter, load_adapters, require_adapter
from .config import ConfigError, Settings, resolve_profile
from .exports import atomic_json, sha256
from .handoff import stage_for_slicer

_X2D = load_adapters()["bambu-x2d"]
BAMBU_X2D_PROFILE_ID = _X2D.profile_id
BAMBU_X2D_PLATE_CENTER_MM = _X2D.plate_center_mm
BAMBU_X2D_COMMON_DUAL_VOLUME_MM = _X2D.build_volume_mm
BAMBU_X2D_MAIN_VOLUME_MM = tuple(float(value) for value in _X2D.extras["main_only_build_volume_mm"])
BAMBU_X2D_SAFE_RECTANGLE_MM = {key: float(value) for key, value in _X2D.extras["safe_rectangle_mm"].items()}
BAMBU_X2D_AUXILIARY_LIMITS = {key: int(value) for key, value in _X2D.extras["auxiliary_limits"].items()}


class BambuError(ValueError):
    """A Bambu-specific handoff error."""


def _slots(raw: Any, labels: set[str]) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise BambuError("bambu_slots must map every part label to a positive Bambu filament slot")
    normalized: dict[str, int] = {}
    for label in labels:
        value = raw.get(label)
        if isinstance(value, bool) or not isinstance(value, int):
            raise BambuError(f"bambu slot for {label!r} must be a positive integer")
        slot = value
        if slot < 1:
            raise BambuError(f"bambu slot for {label!r} must be >= 1")
        normalized[label] = slot
    extras = sorted(set(raw) - labels)
    if extras:
        raise BambuError(f"bambu_slots names parts not in solids_map: {extras}")
    return normalized


def _nozzle_for_tool(value: Any, tool_model: str) -> str:
    if tool_model == "single":
        return "main"
    if value == 0:
        return "main"
    if value == 1:
        return "auxiliary"
    return "unspecified"


def _plate_name(raw: Any, fallback: str) -> str:
    if raw is None:
        return fallback
    value = str(raw).strip()
    if not value:
        raise BambuError("plate_name must be non-empty when provided")
    return value


def _capacity(adapter: BambuAdapter, raw: Any) -> int | None:
    if adapter.default_slot_capacity is None or adapter.max_slot_capacity is None:
        return None
    if raw is None:
        return adapter.default_slot_capacity
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise BambuError("ams_slot_capacity must be an integer")
    if raw < 1 or raw > adapter.max_slot_capacity:
        raise BambuError(f"ams_slot_capacity must be 1..{adapter.max_slot_capacity} for {adapter.profile_id}")
    return raw


def _reject_single_nozzle_tools(adapter: BambuAdapter, solids_map: Any) -> None:
    if adapter.tool_model != "single" or not isinstance(solids_map, Mapping):
        return
    for label, details in solids_map.items():
        if isinstance(details, Mapping) and details.get("tool") not in (None, 0):
            raise BambuError(f"P2S has one nozzle; tool must be 0 or omitted ({label!r})")


def _manual_steps(adapter: BambuAdapter) -> list[str]:
    if adapter.tool_model == "dual_shared_xy":
        return [
            "For Bambu Studio UI import, select all listed individual STL files together and retain them as one multi-part object or assembly when prompted.",
            "Bind every Bambu slot in this manifest to the actual loaded printer material source; slot numbers are saved metadata, not live AMS bindings.",
            "Use the Bambu Lab X2D 0.4 mm process selected for the final slice, then inspect the complete Preview before printing.",
            "If any part uses the auxiliary hotend, keep its process at or below 200 mm/s print speed and 1000 mm/s² acceleration, and verify material/quality compatibility.",
            "The generated bambu-assemble-list.json is a CLI assembly recipe only. Use it with full, version-pinned Bambu machine/process/filament configuration and accept a native project only after Bambu Studio --info succeeds.",
        ]
    return [
        "For Bambu Studio UI import, select all listed individual STL files together and retain them as one multi-part object or assembly when prompted.",
        "Bind every Bambu slot in this manifest to the actual loaded AMS or external spool. Slot numbers are saved metadata, not live AMS bindings.",
        f"Select the Bambu Lab P2S 0.4 mm process ({adapter.studio_process_hint} unless a different installed 0.4 mm P2S process is intended), then inspect the complete Preview before printing.",
        "P2S Combo default is one AMS 2 Pro: slots 1 through 4. Raise ams_slot_capacity only when more AMS units are actually connected, never above 20.",
        "TPU 85A and TPU 90A on P2S are external-spool materials. An AMS slot number does not mean the AMS can feed them.",
        "The generated bambu-assemble-list.json is a CLI assembly recipe only. A native project is acceptable only after that Studio build's --info succeeds. This plugin does not export one.",
    ]


def _limitations() -> list[str]:
    return [
        "slicer-handoff.3mf remains a vendor-neutral interchange file; it is not asserted to be a Bambu-native project.",
        "This adapter deliberately does not auto-export a native Bambu 3MF: direct CLI assembly without full current Bambu configuration was observed to produce an archive that can fail Bambu Studio --info.",
        "No print is dispatched and no live AMS, material, nozzle, firmware, or process state is inferred.",
    ]


def _x2d_contract(adapter: BambuAdapter) -> dict[str, Any]:
    return {
        "shared_xy_toolhead": "main left direct-drive hotend plus right remote-fed auxiliary hotend; the heads do not move independently",
        "main_only_build_volume_mm": list(BAMBU_X2D_MAIN_VOLUME_MM),
        "common_dual_or_auxiliary_build_volume_mm": list(adapter.build_volume_mm),
        "common_dual_safe_rectangle_mm": dict(BAMBU_X2D_SAFE_RECTANGLE_MM),
        "plate_center_mm": list(adapter.plate_center_mm),
        "auxiliary_hotend_limits": dict(BAMBU_X2D_AUXILIARY_LIMITS),
    }


def stage_for_bambu(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    """Create a Bambu-safe UI/CLI assembly recipe without claiming a native project."""
    revision: Path | None = None
    success = False
    try:
        profile = resolve_profile(settings, args)
        adapter = require_adapter(profile.id)
        raw_map = args.get("solids_map")
        _reject_single_nozzle_tools(adapter, raw_map)
        if isinstance(raw_map, Mapping):
            for label, details in raw_map.items():
                if isinstance(details, Mapping) and str(details.get("role") or "model").strip().lower() in {"support", "support_interface"}:
                    raise BambuError(f"Bambu support role for {label!r} is not verified; refusing normal_part conversion")
        capacity = _capacity(adapter, args.get("ams_slot_capacity"))
        fallback_plate = "vibeCAD X2D plate" if adapter.tool_model == "dual_shared_xy" else "vibeCAD P2S plate"
        plate_name = _plate_name(args.get("plate_name"), fallback_plate)
        if isinstance(raw_map, Mapping) and all(isinstance(label, str) for label in raw_map):
            labels = set(raw_map)
            slots = _slots(args.get("bambu_slots"), labels)
            if capacity is not None:
                for label, slot in slots.items():
                    if slot > capacity:
                        raise BambuError(f"bambu slot for {label!r} is {slot}, above slot capacity {capacity}")
        generic = stage_for_slicer(settings, args, physical_volume=adapter.build_volume_mm, physical_tools=1 if adapter.tool_model == "single" else 2)
        if not generic.get("success"):
            return generic
        revision = Path(generic["handoff_manifest"]).parent

        parts = list(generic["parts"])
        labels = {str(part["label"]) for part in parts}
        slots = _slots(args.get("bambu_slots"), labels)
        if capacity is not None:
            for label, slot in slots.items():
                if slot > capacity:
                    raise BambuError(f"bambu slot for {label!r} is {slot}, above slot capacity {capacity}")
        stls_by_label = {str(entry["label"]): entry for entry in generic["individual_stls"]}
        if set(stls_by_label) != labels:
            raise BambuError("generic staging did not produce one named STL fallback for every Bambu part")

        step_file = Path(str(generic["step_file"]))
        assemble_list = revision / "bambu-assemble-list.json"
        handoff_manifest = revision / "bambu-handoff.json"
        center = adapter.plate_center_mm

        objects = []
        bambu_parts = []
        for part in parts:
            label = str(part["label"])
            stl = stls_by_label[label]
            slot = slots[label]
            nozzle = _nozzle_for_tool(part.get("tool"), adapter.tool_model)
            objects.append(
                {
                    "path": str(stl["path"]),
                    "count": 1,
                    "filaments": [slot],
                    "subtype": "normal_part",
                    "assemble_index": [1],
                    "pos_x": [center[0]],
                    "pos_y": [center[1]],
                    "pos_z": [center[2]],
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

        atomic_json(assemble_list, {"plates": [{"plate_name": plate_name, "need_arrange": False, "objects": objects}]})
        generic_manifest_path = Path(generic["handoff_manifest"])
        generic_manifest = json.loads(generic_manifest_path.read_text(encoding="utf-8"))
        if (sha256(step_file) != generic_manifest["source_step_sha256"]
                or sha256(Path(generic_manifest["source_step_snapshot"])) != generic_manifest["source_step_sha256"]
                or sha256(Path(generic_manifest["staged_3mf"])) != generic_manifest["staged_3mf_sha256"]
                or any(sha256(Path(item["path"])) != item["sha256"] for item in generic_manifest["individual_stls"])):
            raise BambuError("source or generic artifacts changed during Bambu staging")
        manual_steps = _manual_steps(adapter)
        limitations = _limitations()
        bambu_contract = {
            "machine_name": adapter.machine_name,
            "plate_center_mm": list(center),
            "build_volume_mm": list(adapter.build_volume_mm),
            "tool_model": adapter.tool_model,
            "studio_process_hint": adapter.studio_process_hint,
            "slot_capacity": capacity,
        }
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "printer_profile": profile.id,
            "source_step": str(step_file),
            "source_step_sha256": generic_manifest["source_step_sha256"],
            "source_step_snapshot": generic_manifest["source_step_snapshot"],
            "generic_handoff": generic["handoff_manifest"],
            "generic_handoff_sha256": sha256(generic_manifest_path),
            "bambu_assemble_list": str(assemble_list),
            "bambu_assemble_list_sha256": sha256(assemble_list),
            "bambu_slots": slots,
            "parts": bambu_parts,
            "bambu_contract": bambu_contract,
            "manual_bambu_steps": manual_steps,
            "limitations": limitations,
            "status": "ready_for_manual_bambu_import",
        }
        if adapter.tool_model == "dual_shared_xy":
            manifest["x2d_contract"] = _x2d_contract(adapter)
        else:
            manifest["p2s_contract"] = {
                "machine_name": adapter.machine_name,
                "slot_capacity": capacity,
                "max_slot_capacity": adapter.max_slot_capacity,
                "supported_nozzle_diameters_mm": list(adapter.extras.get("supported_nozzle_diameters_mm") or []),
                "max_nozzle_temperature_c": adapter.extras.get("max_nozzle_temperature_c"),
                "max_bed_temperature_c": adapter.extras.get("max_bed_temperature_c"),
            }
        atomic_json(handoff_manifest, manifest)
        result = {
            "success": True,
            **generic,
            "status": manifest["status"],
            "bambu_assemble_list": str(assemble_list),
            "bambu_handoff_manifest": str(handoff_manifest),
            "bambu_slots": slots,
            "bambu_parts": bambu_parts,
            "bambu_contract": bambu_contract,
            "manual_bambu_steps": manual_steps,
            "limitations": limitations,
        }
        if "x2d_contract" in manifest:
            result["x2d_contract"] = manifest["x2d_contract"]
        if "p2s_contract" in manifest:
            result["p2s_contract"] = manifest["p2s_contract"]
        success = True
        return result
    except (ConfigError, BambuError, AdapterError, OSError, json.JSONDecodeError) as exc:
        return {"success": False, "error": str(exc), "printer_validation": "failed"}
    finally:
        if revision is not None and not success:
            shutil.rmtree(revision, ignore_errors=True)
