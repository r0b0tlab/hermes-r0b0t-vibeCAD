from __future__ import annotations

from vibecad_public_plugin.geometry import fit_to_profile
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


def test_fit_to_profile_reports_each_failed_axis_and_bad_datum() -> None:
    result = fit_to_profile(metrics(x=97, y=77, z=95, z_min=0.02), profile())
    assert result["fits"] is False
    assert result["z_datum_ok"] is False
    assert set(result["failures"]) == {"x", "y", "z", "z_datum"}
