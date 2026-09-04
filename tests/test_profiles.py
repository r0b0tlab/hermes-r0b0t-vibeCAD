from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibecad_public_plugin.profiles import ProfileError, load_profile_catalog, resolve_printer_profile


def test_bundled_catalog_exposes_generic_and_legacy_example() -> None:
    catalog = load_profile_catalog()
    assert set(catalog) >= {"generic-fdm-220", "bambu-x2d"}
    profile = catalog["generic-fdm-220"]
    assert profile.technology == "fdm"
    assert profile.bed.width_mm == 220.0
    assert profile.nozzle_diameter_mm == 0.4
    assert profile.tool_count == 1
    assert profile.source == "bundled"


def test_user_catalog_overrides_a_bundled_profile(tmp_path: Path) -> None:
    profile_file = tmp_path / "profiles.json"
    profile_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [
                    {
                        "id": "generic-fdm-220",
                        "display_name": "My calibrated printer",
                        "technology": "fdm",
                        "bed": {
                            "shape": "rectangular",
                            "width_mm": 300,
                            "depth_mm": 300,
                            "height_mm": 300,
                            "safe_margin_mm": 3,
                        },
                        "nozzle_diameter_mm": 0.6,
                        "min_layer_height_mm": 0.12,
                        "max_layer_height_mm": 0.48,
                        "tool_count": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    profile = resolve_printer_profile("generic-fdm-220", profile_file)
    assert profile.display_name == "My calibrated printer"
    assert profile.bed.width_mm == 300.0
    assert profile.tool_count == 2
    assert profile.source == str(profile_file)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda item: item.update({"technology": "sla"}), "technology"),
        (lambda item: item.update({"nozzle_diameter_mm": -0.4}), "nozzle_diameter_mm"),
        (lambda item: item["bed"].update({"safe_margin_mm": 120}), "safe_margin_mm"),
        (lambda item: item.update({"tool_count": 1.5}), "tool_count"),
        (lambda item: item["bed"].update({"shape": "circular"}), "bed.shape"),
    ],
)
def test_invalid_profile_fields_fail_with_the_field_name(tmp_path: Path, mutate, field: str) -> None:
    item = {
        "id": "bad-printer",
        "display_name": "Bad Printer",
        "technology": "fdm",
        "bed": {"shape": "rectangular", "width_mm": 220, "depth_mm": 220, "height_mm": 250, "safe_margin_mm": 2},
        "nozzle_diameter_mm": 0.4,
        "min_layer_height_mm": 0.08,
        "max_layer_height_mm": 0.32,
        "tool_count": 1,
    }
    mutate(item)
    profile_file = tmp_path / "profiles.json"
    profile_file.write_text(json.dumps({"schema_version": 1, "profiles": [item]}), encoding="utf-8")

    with pytest.raises(ProfileError, match=field):
        load_profile_catalog(profile_file)


def test_duplicate_profile_ids_fail(tmp_path: Path) -> None:
    item = {
        "id": "same",
        "display_name": "Same",
        "technology": "fdm",
        "bed": {"shape": "rectangular", "width_mm": 220, "depth_mm": 220, "height_mm": 250, "safe_margin_mm": 2},
        "nozzle_diameter_mm": 0.4,
        "min_layer_height_mm": 0.08,
        "max_layer_height_mm": 0.32,
        "tool_count": 1,
    }
    profile_file = tmp_path / "profiles.json"
    profile_file.write_text(json.dumps({"schema_version": 1, "profiles": [item, item]}), encoding="utf-8")

    with pytest.raises(ProfileError, match="duplicate profile id"):
        load_profile_catalog(profile_file)


def test_unknown_profile_lists_available_profile_ids() -> None:
    with pytest.raises(ProfileError, match="generic-fdm-220"):
        resolve_printer_profile("missing-printer")
