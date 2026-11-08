"""Bambu handoff contracts. Geometric beds stay in profiles/builtin.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class AdapterError(ValueError):
    """Malformed or unknown Bambu adapter."""


@dataclass(frozen=True)
class BambuAdapter:
    profile_id: str
    machine_name: str
    plate_center_mm: tuple[float, float, float]
    build_volume_mm: tuple[float, float, float]
    tool_model: str
    default_slot_capacity: int | None
    max_slot_capacity: int | None
    studio_process_hint: str
    extras: Mapping[str, Any]


def adapters_path() -> Path:
    return Path(__file__).resolve().parent / "profiles" / "bambu-adapters.json"


def _triple(raw: Any, field: str) -> tuple[float, float, float]:
    if not isinstance(raw, list) or len(raw) != 3:
        raise AdapterError(f"{field} must be a 3-number array")
    try:
        values = tuple(float(item) for item in raw)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"{field} must be a 3-number array") from exc
    return values  # type: ignore[return-value]


def load_adapters() -> dict[str, BambuAdapter]:
    path = adapters_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"cannot read Bambu adapters: {exc}") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise AdapterError("bambu adapter schema_version must equal 1")
    items = raw.get("adapters")
    if not isinstance(items, list) or not items:
        raise AdapterError("adapters must be a non-empty array")
    parsed: dict[str, BambuAdapter] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise AdapterError("adapter entries must be objects")
        profile_id = item.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise AdapterError("profile_id is required")
        tool_model = item.get("tool_model")
        if tool_model not in {"single", "dual_shared_xy"}:
            raise AdapterError(f"unsupported tool_model for {profile_id}")
        default_cap = item.get("default_slot_capacity")
        max_cap = item.get("max_slot_capacity")
        if (default_cap is None) != (max_cap is None):
            raise AdapterError(f"{profile_id} slot capacities must both be set or both be null")
        if default_cap is not None and (
            isinstance(default_cap, bool)
            or not isinstance(default_cap, int)
            or default_cap < 1
            or isinstance(max_cap, bool)
            or not isinstance(max_cap, int)
            or max_cap < default_cap
        ):
            raise AdapterError(f"{profile_id} slot capacities are invalid")
        extras = {
            key: value
            for key, value in item.items()
            if key
            not in {
                "profile_id",
                "machine_name",
                "plate_center_mm",
                "build_volume_mm",
                "tool_model",
                "default_slot_capacity",
                "max_slot_capacity",
                "studio_process_hint",
            }
        }
        adapter = BambuAdapter(
            profile_id=profile_id,
            machine_name=str(item.get("machine_name") or "").strip(),
            plate_center_mm=_triple(item.get("plate_center_mm"), "plate_center_mm"),
            build_volume_mm=_triple(item.get("build_volume_mm"), "build_volume_mm"),
            tool_model=tool_model,
            default_slot_capacity=default_cap,
            max_slot_capacity=max_cap,
            studio_process_hint=str(item.get("studio_process_hint") or "").strip(),
            extras=extras,
        )
        if not adapter.machine_name or not adapter.studio_process_hint:
            raise AdapterError(f"{profile_id} needs machine_name and studio_process_hint")
        if profile_id in parsed:
            raise AdapterError(f"duplicate adapter: {profile_id}")
        parsed[profile_id] = adapter
    return parsed


def require_adapter(profile_id: str) -> BambuAdapter:
    catalog = load_adapters()
    try:
        return catalog[profile_id]
    except KeyError as exc:
        available = ", ".join(sorted(catalog))
        raise AdapterError(
            f"vibecad_stage_for_bambu has no adapter for {profile_id!r}; available: {available}"
        ) from exc
