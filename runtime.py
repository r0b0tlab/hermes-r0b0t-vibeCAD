"""Public runtime facade for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

from typing import Any, Mapping

from .config import ConfigError, Settings, settings_from_context
from .exports import execute_and_export, inspect_metrics
from .handoff import stage_for_slicer
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

__all__ = [
    "CadError",
    "Settings",
    "settings_from_context",
    "list_printer_profiles",
    "execute_and_export",
    "inspect_metrics",
    "generate_preview_renders",
    "modify_parameter",
    "stage_for_slicer",
]
