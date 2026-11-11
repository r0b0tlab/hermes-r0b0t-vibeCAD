from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.runtime import execute_and_export, inspect_metrics


FIXTURE = Path(__file__).parent / "fixtures" / "model.py"


def make_settings(workspace: Path) -> Settings:
    return Settings(
        workspace_root=workspace,
        python_executable=Path(sys.executable),
        printer_profile="generic-fdm-220",
        printer_profiles_file=None,
        timeout_s=120,
    )


def test_execute_export_inspect_and_preserve_last_good_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    project = workspace / "demo"
    source = project / "source"
    source.mkdir(parents=True)
    (project / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = make_settings(workspace)

    first = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert first["success"] is True, json.dumps(first, indent=2, default=str)
    assert first["printer_validation"] == "passed"
    assert first["metrics"]["n_solids"] == 2
    # A nonempty archive is not an independently reimported/verified mesh.
    assert first["mesh_export"]["roundtrip_skipped"] is True
    assert first["mesh_export"]["roundtrip_skip_reason"] == "not_performed"
    for path in first["output"].values():
        assert Path(path).is_file() and Path(path).stat().st_size > 0

    inspected = inspect_metrics(settings, {"step_file": first["output"]["step"]})
    assert inspected["success"] is True
    assert inspected["bed_fit"]["profile_id"] == "generic-fdm-220"

    step = Path(first["output"]["step"])
    baseline = step.read_bytes()
    model.write_text("this is not Python\n", encoding="utf-8")
    failed = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert failed["success"] is False
    assert step.read_bytes() == baseline


def test_inspection_sums_disconnected_overlap_regions(tmp_path: Path) -> None:
    from build123d import Box, Compound, Pos, export_step

    # A single U-shaped solid intersecting a bar at two disconnected regions.
    left = Pos(-3, 0, 0) * Box(2, 2, 2)
    right = Pos(3, 0, 0) * Box(2, 2, 2)
    bridge = Pos(0, 2, 0) * Box(8, 2, 2)
    u_shape = left.fuse(right, bridge)
    bar = Box(10, 1, 1)
    step = tmp_path / "overlap.step"
    export_step(Compound(children=[u_shape, bar]), step)
    inspected = inspect_metrics(make_settings(tmp_path), {"step_file": str(step)})
    # The bar extends below the bed datum; inspection still returns metrics,
    # but the integrated fit gate correctly reports failure.
    assert inspected["success"] is False, inspected
    assert inspected["printer_validation"] == "failed"
    assert inspected["metrics"]["n_solids"] == 2
    assert inspected["metrics"]["intersections"][0]["overlap_volume_mm3"] == pytest.approx(4.0)


def _two_box_model(distance: float) -> str:
    return f'''\
import os
from build123d import Align, Box, Compound, Pos, export_step
left = Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
right = Pos({distance}, 0, 0) * Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
export_step(Compound(children=[left, right]), os.environ["VIBECAD_OUTPUT_STEP"])
'''


def test_overlap_tolerance_is_shared_and_strict() -> None:
    from vibecad_public_plugin.geometry import overlapping_solids

    pairs = [{"overlap_volume_mm3": volume} for volume in (0.0, 1e-6, 1.0001e-6)]
    assert overlapping_solids({"intersections": pairs}) == [pairs[2]]


def test_inspect_rejects_bed_aligned_overlapping_solids(tmp_path: Path) -> None:
    from build123d import Align, Box, Compound, Pos, export_step

    box = Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    step = tmp_path / "overlap.step"
    export_step(Compound(children=[box, Pos(5, 0, 0) * box]), step)
    result = inspect_metrics(make_settings(tmp_path), {"step_file": str(step)})
    assert result["success"] is False, result
    assert result["printer_validation"] == "failed"
    assert result["metrics"]["intersections"][0]["overlap_volume_mm3"] == pytest.approx(500)
    assert "overlap" in result["error"].lower()


def test_export_rejects_overlap_preserves_touching_export(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    model = source / "model.py"
    model.write_text(_two_box_model(10), encoding="utf-8")
    settings = make_settings(workspace)
    request = {"script_path": str(model), "output_name": "demo"}
    first = execute_and_export(settings, request)
    assert first["success"] is True, first
    assert first["printer_validation"] == "passed"
    inspected = inspect_metrics(settings, {"step_file": first["output"]["step"]})
    assert inspected["success"] is True, inspected
    assert inspected["metrics"]["intersections"][0]["overlap_volume_mm3"] == pytest.approx(0)
    before = {path: Path(path).read_bytes() for path in first["output"].values()}

    model.write_text(_two_box_model(5), encoding="utf-8")
    result = execute_and_export(settings, request)
    assert result["success"] is False, result
    assert result["printer_validation"] == "failed"
    assert "overlap" in result["error"].lower()
    assert {path: Path(path).read_bytes() for path in before} == before


def test_export_rejects_output_directory_symlink_before_running_model(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (source.parent / "exports").symlink_to(outside, target_is_directory=True)
    model = source / "model.py"
    model.write_text("raise RuntimeError('model must not run')\n", encoding="utf-8")
    result = execute_and_export(make_settings(workspace), {"script_path": str(model), "output_name": "demo"})
    assert result["success"] is False
    assert "output directory" in result["error"]
    assert list(outside.iterdir()) == []


def test_inspect_metrics_reports_actionable_error_on_bed_or_datum_failure(tmp_path: Path) -> None:
    from build123d import Box, export_step

    floating = tmp_path / "floating.step"
    # Centered Box(10, 10, 10) sits at z_min = -5.0 mm (violates Z=0 bed datum).
    export_step(Box(10, 10, 10), floating)
    result = inspect_metrics(make_settings(tmp_path), {"step_file": str(floating)})
    assert result["success"] is False
    assert result["printer_validation"] == "failed"
    assert "z_datum" in result.get("error", "")
