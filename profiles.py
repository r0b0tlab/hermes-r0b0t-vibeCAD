"""Strict, vendor-neutral FDM printer-profile loading."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROFILE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SCHEMA_VERSION = 1


class ProfileError(ValueError):
    """A malformed, missing, or unsupported printer profile."""


@dataclass(frozen=True)
class BedProfile:
    shape: str
    width_mm: float
    depth_mm: float
    height_mm: float
    safe_margin_mm: float


@dataclass(frozen=True)
class PrinterProfile:
    id: str
    display_name: str
    technology: str
    bed: BedProfile
    nozzle_diameter_mm: float
    min_layer_height_mm: float
    max_layer_height_mm: float
    tool_count: int
    source: str


def bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "profiles" / "builtin.json"


def _number(raw: Any, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(raw, bool):
        raise ProfileError(f"{field} must be a finite number")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"{field} must be a finite number") from exc
    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        comparator = "non-negative" if allow_zero else "positive"
        raise ProfileError(f"{field} must be a finite {comparator} number")
    return value


def _tool_count(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ProfileError("tool_count must be an integer >= 1")
    return raw


def _parse_profile(raw: Any, *, source: str) -> PrinterProfile:
    if not isinstance(raw, Mapping):
        raise ProfileError("profiles entries must be objects")
    profile_id = raw.get("id")
    if not isinstance(profile_id, str) or not PROFILE_ID_RE.fullmatch(profile_id):
        raise ProfileError("id must match [a-z0-9][a-z0-9_-]{0,63}")
    display_name = raw.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ProfileError("display_name must be a non-empty string")
    technology = raw.get("technology")
    if technology != "fdm":
        raise ProfileError("technology must be 'fdm' in schema_version 1")
    bed_raw = raw.get("bed")
    if not isinstance(bed_raw, Mapping):
        raise ProfileError("bed must be an object")
    shape = bed_raw.get("shape")
    if shape != "rectangular":
        raise ProfileError("bed.shape must be 'rectangular' in schema_version 1")
    width = _number(bed_raw.get("width_mm"), "bed.width_mm")
    depth = _number(bed_raw.get("depth_mm"), "bed.depth_mm")
    height = _number(bed_raw.get("height_mm"), "bed.height_mm")
    margin = _number(bed_raw.get("safe_margin_mm"), "bed.safe_margin_mm", allow_zero=True)
    if margin * 2 >= width or margin * 2 >= depth:
        raise ProfileError("bed.safe_margin_mm leaves no printable rectangular area")
    min_layer = _number(raw.get("min_layer_height_mm"), "min_layer_height_mm")
    max_layer = _number(raw.get("max_layer_height_mm"), "max_layer_height_mm")
    if min_layer > max_layer:
        raise ProfileError("min_layer_height_mm must be <= max_layer_height_mm")
    return PrinterProfile(
        id=profile_id,
        display_name=display_name.strip(),
        technology=technology,
        bed=BedProfile(shape=shape, width_mm=width, depth_mm=depth, height_mm=height, safe_margin_mm=margin),
        nozzle_diameter_mm=_number(raw.get("nozzle_diameter_mm"), "nozzle_diameter_mm"),
        min_layer_height_mm=min_layer,
        max_layer_height_mm=max_layer,
        tool_count=_tool_count(raw.get("tool_count")),
        source=source,
    )


def _read_catalog(path: Path, *, source: str) -> dict[str, PrinterProfile]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"printer profile catalog does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"printer profile catalog is invalid JSON: {path}: {exc.msg}") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ProfileError(f"schema_version must equal {SCHEMA_VERSION}")
    profiles = raw.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ProfileError("profiles must be a non-empty array")
    parsed: dict[str, PrinterProfile] = {}
    for item in profiles:
        profile = _parse_profile(item, source=source)
        if profile.id in parsed:
            raise ProfileError(f"duplicate profile id: {profile.id}")
        parsed[profile.id] = profile
    return parsed


def load_profile_catalog(user_catalog: str | Path | None = None) -> dict[str, PrinterProfile]:
    """Load bundled profiles and explicitly configured user overrides."""
    catalog = _read_catalog(bundled_catalog_path(), source="bundled")
    if user_catalog is None or not str(user_catalog).strip():
        return catalog
    user_path = Path(user_catalog).expanduser().resolve(strict=False)
    catalog.update(_read_catalog(user_path, source=str(user_path)))
    return catalog


def resolve_printer_profile(profile_id: str, user_catalog: str | Path | None = None) -> PrinterProfile:
    catalog = load_profile_catalog(user_catalog)
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ProfileError("printer_profile is required; choose one with vibecad_list_printer_profiles")
    clean = profile_id.strip()
    try:
        return catalog[clean]
    except KeyError as exc:
        available = ", ".join(sorted(catalog))
        raise ProfileError(f"unknown printer_profile {clean!r}; available: {available}") from exc
