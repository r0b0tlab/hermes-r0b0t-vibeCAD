"""Pure geometry/profile checks plus child-process STEP inspection programs."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from .profiles import PrinterProfile


EPSILON_MM = 0.01


class GeometryError(ValueError):
    """Malformed geometry metrics or unsupported FDM fit check."""


def _number(mapping: Mapping[str, Any], key: str, context: str) -> float:
    try:
        value = float(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryError(f"missing or invalid {context}.{key}") from exc
    if not math.isfinite(value):
        raise GeometryError(f"missing or invalid {context}.{key}")
    return value


def fit_to_profile(metrics: Mapping[str, Any], profile: PrinterProfile) -> dict[str, Any]:
    """Conservatively fit a rectangular FDM part into a rectangular profile."""
    bbox = metrics.get("bbox")
    if not isinstance(bbox, Mapping):
        raise GeometryError("missing bbox")
    size = bbox.get("size_mm")
    minimum = bbox.get("min_mm")
    if not isinstance(size, Mapping) or not isinstance(minimum, Mapping):
        raise GeometryError("missing bbox.size_mm or bbox.min_mm")
    x = _number(size, "x", "bbox.size_mm")
    y = _number(size, "y", "bbox.size_mm")
    z = _number(size, "z", "bbox.size_mm")
    z_min = _number(minimum, "z", "bbox.min_mm")
    if any(value < 0 for value in (x, y, z)):
        raise GeometryError("bbox.size_mm dimensions must be non-negative")
    margin = profile.bed.safe_margin_mm
    failures: list[str] = []
    if x + 2 * margin > profile.bed.width_mm + EPSILON_MM:
        failures.append("x")
    if y + 2 * margin > profile.bed.depth_mm + EPSILON_MM:
        failures.append("y")
    if z > profile.bed.height_mm + EPSILON_MM:
        failures.append("z")
    z_datum_ok = abs(z_min) <= EPSILON_MM
    if not z_datum_ok:
        failures.append("z_datum")
    return {
        "fits": not failures,
        "z_datum_ok": z_datum_ok,
        "profile_id": profile.id,
        "build_volume_mm": {
            "x": profile.bed.width_mm,
            "y": profile.bed.depth_mm,
            "z": profile.bed.height_mm,
        },
        "safe_margin_mm": margin,
        "failures": failures,
        "bbox_size_mm": {"x": x, "y": y, "z": z},
        "z_min_mm": z_min,
    }


def nozzle_warnings(metrics: Mapping[str, Any], profile: PrinterProfile) -> list[str]:
    """Warn when a solid bbox axis is below two nozzle diameters.

    This is a lower bound, not a wall-thickness measurement. Callers must not
    fail an export on it.
    """
    floor = 2 * profile.nozzle_diameter_mm
    warnings: list[str] = []
    for solid in metrics.get("solids") or []:
        if not isinstance(solid, Mapping):
            continue
        bbox = solid.get("bbox")
        size = bbox.get("size_mm") if isinstance(bbox, Mapping) else None
        if not isinstance(size, Mapping):
            continue
        label = str(solid.get("label") or solid.get("solid_index") or "solid")
        for axis in ("x", "y", "z"):
            try:
                value = float(size[axis])
            except (KeyError, TypeError, ValueError):
                continue
            if value + 1e-9 < floor:
                warnings.append(
                    f"{label} bbox {axis} is {value:.3f} mm, below 2× nozzle ({floor:.3f} mm); not a measured wall thickness"
                )
    return warnings


METRICS_PROGRAM = r'''
import json
import os
from build123d import CenterOf, import_step
from OCP.BRepCheck import BRepCheck_Analyzer

path = os.environ["VIBECAD_STEP_FILE"]
shape = import_step(path)
solids = list(shape.solids())

def vector(value):
    return {"x": float(value.X), "y": float(value.Y), "z": float(value.Z)}

def bbox(value):
    return {"min_mm": vector(value.min), "max_mm": vector(value.max), "size_mm": vector(value.size)}

pairs = []
for left_index, left in enumerate(solids):
    for right_index in range(left_index + 1, len(solids)):
        overlap = left.intersect(solids[right_index])
        pairs.append({
            "left_solid": left_index + 1,
            "right_solid": right_index + 1,
            "overlap_volume_mm3": sum(float(part.volume) for part in overlap) if isinstance(overlap, list) else float(overlap.volume) if overlap else 0.0,
        })

print(json.dumps({
    "bbox": bbox(shape.bounding_box()),
    "volume_mm3": float(shape.volume),
    "center_of_mass_mm": vector(shape.center(CenterOf.MASS)),
    "n_solids": len(solids),
    "valid_brep": bool(BRepCheck_Analyzer(shape.wrapped).IsValid()),
    "is_valid": bool(shape.is_valid),
    "solids": [{
        "solid_index": index + 1,
        "label": str(solid.label or f"solid_{index + 1}"),
        "bbox": bbox(solid.bounding_box()),
        "volume_mm3": float(solid.volume),
        "is_valid": bool(solid.is_valid),
    } for index, solid in enumerate(solids)],
    "intersections": pairs,
}, sort_keys=True))
'''
