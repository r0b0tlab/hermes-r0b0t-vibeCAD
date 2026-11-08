from __future__ import annotations

import pytest

from vibecad_public_plugin.geometry import GeometryError, fit_to_profile
from vibecad_public_plugin.profiles import BedProfile, PrinterProfile


def profile() -> PrinterProfile:
    return PrinterProfile(
        id="test-fdm",
        display_name="Test FDM",
        technology="fdm",
        bed=BedProfile(shape="rectangular", width_mm=100.0, depth_mm=80.0, height_mm=90.0, safe_margin_mm=2.0),
        nozzle_diameter_mm=0.4,
        min_layer_height_mm=0.08,
        max_layer_height_mm=0.32,
        tool_count=1,
        source="test",
    )


def metrics(*, x: float = 80.0, y: float = 60.0, z: float = 20.0, z_min: float = 0.0) -> dict:
    return {"bbox": {"size_mm": {"x": x, "y": y, "z": z}, "min_mm": {"x": -x / 2, "y": -y / 2, "z": z_min}}}


def test_fit_to_profile_passes_when_geometry_and_margin_fit() -> None:
    result = fit_to_profile(metrics(), profile())
    assert result["fits"] is True
    assert result["z_datum_ok"] is True
    assert result["profile_id"] == "test-fdm"
    assert result["failures"] == []


def test_p2s_profile_rejects_one_tenth_over_bed() -> None:
    from vibecad_public_plugin.profiles import load_profile_catalog

    profile = load_profile_catalog()["bambu-p2s"]
    fit = fit_to_profile(
        {"bbox": {"size_mm": {"x": 256.1, "y": 10.0, "z": 10.0}, "min_mm": {"x": 0.0, "y": 0.0, "z": 0.0}}},
        profile,
    )
    assert fit["fits"] is False
    assert fit["failures"] == ["x"]
    assert fit["profile_id"] == "bambu-p2s"


def test_nozzle_warning_does_not_mean_unprintable() -> None:
    from vibecad_public_plugin.geometry import nozzle_warnings
    from vibecad_public_plugin.profiles import load_profile_catalog

    printer = load_profile_catalog()["bambu-p2s"]
    measured = {
        "bbox": {"size_mm": {"x": 20.0, "y": 20.0, "z": 0.5}, "min_mm": {"x": 0.0, "y": 0.0, "z": 0.0}},
        "solids": [{"label": "fin", "bbox": {"size_mm": {"x": 20.0, "y": 20.0, "z": 0.5}}}],
    }
    assert fit_to_profile(measured, printer)["fits"] is True
    warnings = nozzle_warnings(measured, printer)
    assert len(warnings) == 1
    assert "fin" in warnings[0]
    assert "not a measured wall thickness" in warnings[0]


def test_fit_to_profile_reports_each_failed_axis_and_bad_datum() -> None:
    result = fit_to_profile(metrics(x=97, y=77, z=95, z_min=0.02), profile())
    assert result["fits"] is False
    assert result["z_datum_ok"] is False
    assert set(result["failures"]) == {"x", "y", "z", "z_datum"}


@pytest.mark.parametrize("axis", ["x", "y", "z"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.1])
def test_invalid_bbox_dimensions_are_rejected(axis: str, value: float) -> None:
    data = metrics()
    data["bbox"]["size_mm"][axis] = value
    with pytest.raises(GeometryError):
        fit_to_profile(data, profile())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_datum_is_rejected(value: float) -> None:
    with pytest.raises(GeometryError):
        fit_to_profile(metrics(z_min=value), profile())


def test_fit_preserves_epsilon_and_allows_zero_size() -> None:
    assert fit_to_profile(metrics(x=96.005, z=0, z_min=0.005), profile())["fits"]
    assert not fit_to_profile(metrics(x=96.02), profile())["fits"]
