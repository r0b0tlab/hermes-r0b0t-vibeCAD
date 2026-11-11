from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
from build123d import Align, Box, Color, Compound, Location, Sphere, export_step
from PIL import Image

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.runtime import execute_and_export, generate_preview_renders


FIXTURE = Path(__file__).parent / "fixtures" / "model.py"
BACKGROUND = (247, 249, 251)


def settings_for(workspace: Path, timeout: int = 120) -> Settings:
    workspace.mkdir(parents=True, exist_ok=True)
    return Settings(workspace_root=workspace, python_executable=Path(sys.executable), printer_profile="generic-fdm-220", printer_profiles_file=None, timeout_s=timeout)


def image(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def colored_box(size, position, color):
    solid = Location(position) * Box(*size, align=(Align.CENTER, Align.CENTER, Align.MIN))
    if color:
        solid.color = Color(color)
    return solid


def test_generates_requested_deterministic_png_views(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = settings_for(workspace)
    exported = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert exported["success"] is True, exported
    args = {"step_file": exported["output"]["step"], "views": ["iso", "top", "bottom"], "part_colors": ["#00AA00", "#FFFFFF"]}
    rendered = generate_preview_renders(settings, args)
    repeated = generate_preview_renders(settings, args)
    assert rendered["success"] and repeated["success"], (rendered, repeated)
    assert set(rendered["renders"]) == {"iso", "top", "bottom"}
    assert rendered["media"] == [f"MEDIA:{path}" for path in rendered["renders"].values()]
    for view in args["views"]:
        first, second = rendered["renders"][view], repeated["renders"][view]
        assert first != second
        assert digest(first) == digest(second)
    top = image(rendered["renders"]["top"])
    foreground = np.any(top != BACKGROUND, axis=2)
    green = foreground & (top[:, :, 1] > top[:, :, 0] + 20) & (top[:, :, 1] > top[:, :, 2])
    white = foreground & (top[:, :, 0] > 200) & (top[:, :, 1] > 200) & (top[:, :, 2] > 200)
    assert green.sum() > 500, "top view lost the lower part color"
    assert white.sum() > 200, "top view lost the raised part (excluding background)"


def test_step_child_colors_and_occlusion_in_opposite_views(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    lower = colored_box((40, 40, 2), (0, 0, 0), "red")
    upper = colored_box((16, 16, 2), (0, 0, 2), "blue")
    path = tmp_path / "assembly.step"
    export_step(Compound(children=[Compound(children=[lower, upper])]), path)
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["top", "bottom"]})
    assert result["success"], result
    top, bottom = (image(result["renders"][view]) for view in ("top", "bottom"))
    assert top[400, 400, 2] > 150 and top[400, 400, 0] == 0  # blue upper face
    assert top[400, 120, 0] > 150 and top[400, 120, 2] == 0  # red lower face
    assert bottom[400, 400, 0] > 150 and bottom[400, 400, 2] == 0  # red occludes blue


def test_single_red_step_and_uncolored_fallback(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    red_path, gray_path = tmp_path / "red.step", tmp_path / "gray.step"
    export_step(colored_box((10, 10, 2), (0, 0, 0), "red"), red_path)
    export_step(colored_box((10, 10, 2), (0, 0, 0), None), gray_path)
    red = generate_preview_renders(settings, {"step_file": str(red_path), "views": ["top"]})
    gray = generate_preview_renders(settings, {"step_file": str(gray_path), "views": ["top"]})
    assert red["success"] and gray["success"], (red, gray)
    red_pixel = image(red["renders"]["top"])[400, 400]
    assert red_pixel[0] > 200 and red_pixel[1] == red_pixel[2] == 0
    pixel = image(gray["renders"]["top"])[400, 400]
    assert pixel[0] == pixel[1] == pixel[2] and pixel[0] < 200


def test_changed_step_keeps_previous_render(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = tmp_path / "part.step"
    export_step(colored_box((10, 10, 2), (0, 0, 0), "red"), path)
    first = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"]})
    assert first["success"], first
    old_path = first["renders"]["top"]
    old_hash = digest(old_path)
    export_step(colored_box((10, 10, 2), (0, 0, 0), "blue"), path)
    second = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"]})
    assert second["success"], second
    assert second["renders"]["top"] != old_path
    assert digest(old_path) == old_hash != digest(second["renders"]["top"])


def test_curved_small_triangles_occlude_large_base(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    base = colored_box((40, 40, 2), (0, 0, 0), "blue")
    curved = Location((0, 0, 9)) * Sphere(8)
    curved.color = Color("red")
    path = tmp_path / "curved.step"
    export_step(Compound(children=[base, curved]), path)
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["top", "bottom"]})
    assert result["success"], result
    top, bottom = (image(result["renders"][v]) for v in ("top", "bottom"))
    assert top[400, 400, 0] > 100 and top[400, 400, 2] == 0
    assert top[400, 120, 2] > 100 and top[400, 120, 0] == 0
    assert bottom[400, 400, 2] > 100 and bottom[400, 400, 0] == 0


def test_translated_nested_assembly_positions(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    red = colored_box((4, 4, 2), (0, 0, 0), "red")
    nested = Compound(children=[red])
    nested.location = Location((30, 0, 0))
    blue = colored_box((4, 4, 2), (0, 0, 0), "blue")
    path = tmp_path / "translated.step"
    export_step(Compound(children=[nested, blue]), path)
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"]})
    assert result["success"], result
    pixels = image(result["renders"]["top"])
    red_x = np.where((pixels[:, :, 0] > 200) & (pixels[:, :, 1] == 0) & (pixels[:, :, 2] == 0))[1]
    blue_x = np.where((pixels[:, :, 2] > 200) & (pixels[:, :, 0] == 0) & (pixels[:, :, 1] == 0))[1]
    assert red_x.size > 1000 and blue_x.size > 1000
    assert red_x.min() > blue_x.max() + 400


def test_render_refuses_changed_step_and_removes_partial_previews(tmp_path: Path, monkeypatch) -> None:
    import json
    import subprocess
    from vibecad_public_plugin import renders

    step = tmp_path / "part.step"
    step.write_bytes(b"before")

    def fake_render(settings, argv, *, cwd, env_updates):
        outputs = json.loads(env_updates["VIBECAD_RENDER_OUTPUTS"])
        for output in outputs.values():
            Path(output).write_bytes(b"fake image")
        step.write_bytes(b"after")
        return subprocess.CompletedProcess(argv, 0, json.dumps({"outputs": outputs}), "")

    monkeypatch.setattr(renders, "run_cad", fake_render)
    result = renders.generate_preview_renders(settings_for(tmp_path), {"step_file": str(step), "views": ["top"]})
    assert result["success"] is False
    assert "changed" in result["error"]
    assert not list((tmp_path / "build").glob("preview_*.png"))


def test_timeout_cleans_partial_outputs_and_temporaries(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, timeout=1)
    path = tmp_path / "part.step"
    export_step(colored_box((10, 10, 2), (0, 0, 0), "red"), path)
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"]})
    assert not result["success"] and "exceeded 1s" in result["error"]
    assert not list((tmp_path / "build").glob("*.png"))
    assert not list((tmp_path / "build").glob(".vibecad-render-*"))


def test_detail_regions_render_full_scene_at_high_resolution_and_hashes(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    # Both faces extend beyond the crop: an object outside the crop must still
    # occlude one behind it; cropping geometry or vertices would lose the face.
    front = colored_box((40, 2, 40), (0, -4, 0), "red")
    back = colored_box((40, 2, 40), (0, 4, 0), "blue")
    path = tmp_path / "occlusion.step"
    export_step(Compound(children=[front, back]), path)
    region = {"label": "contact", "x_min": 0.4, "y_min": 0.4, "x_max": 0.6, "y_max": 0.6}
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["front", "back"], "region": region, "resolution": 1200})
    assert result["success"], result
    assert result["source_step_sha256"] == digest(str(path))
    assert set(result["renders"]) == {"front_detail_contact", "back_detail_contact"}
    for view, color in (("front", 0), ("back", 2)):
        key = f"{view}_detail_contact"
        png = result["renders"][key]
        pixels = image(png)
        assert pixels.shape == (1200, 1200, 3)
        assert pixels[600, 600, color] > 100
        assert pixels[600, 600, 2 - color] == 0
        assert result["render_sha256"][key] == digest(png)
        assert result["render_metadata"][key] == {"view": view, "region": region, "resolution": 1200}


def test_full_frame_regression_and_pixel_region_mapping(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = tmp_path / "part.step"
    export_step(colored_box((10, 10, 2), (0, 0, 0), "red"), path)
    default = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"]})
    whole = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"], "resolution": 800,
        "region": {"label": "whole", "x_min": 0, "y_min": 0, "x_max": 1, "y_max": 1}})
    assert default["success"] and whole["success"], (default, whole)
    assert digest(default["renders"]["top"]) == digest(whole["renders"]["top_detail_whole"])
    assert image(default["renders"]["top"]).shape == (800, 800, 3)
    assert default["render_sha256"]["top"] == digest(default["renders"]["top"])


def test_offcenter_rectangular_viewport_and_back_orientation(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    base = colored_box((40, 40, 2), (0, 0, 0), "blue")
    mark = colored_box((2, 2, 2), (10, 0, 2), "red")
    path = tmp_path / "mark.step"
    export_step(Compound(children=[base, mark]), path)
    # +X=10 projects at x=0.725 in the top full frame; retain the same
    # full-scene geometry and frame the off-center mark, with letterboxing.
    region = {"label": "mark", "x_min": 0.625, "y_min": 0.45, "x_max": 0.825, "y_max": 0.55}
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"], "region": region, "resolution": 1200})
    assert result["success"], result
    pixels = image(result["renders"]["top_detail_mark"])
    assert pixels[600, 600, 0] > 150 and pixels[600, 600, 2] == 0
    assert tuple(pixels[100, 600]) == BACKGROUND and pixels[400, 600, 2] > 150
    red = (pixels[:, :, 0] > 150) & (pixels[:, :, 2] == 0)
    assert np.ptp(np.where(red)[1]) > 240

    # Distinct colored objects show the expected horizontal flip on opposite
    # views (the rear camera's right is -X, rather than a mirrored front).
    left = colored_box((4, 4, 4), (-10, 0, 0), "red")
    right = colored_box((4, 4, 4), (10, 0, 0), "blue")
    export_step(Compound(children=[left, right]), path)
    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["front", "back"]})
    assert result["success"], result
    for view, reverse in (("front", False), ("back", True)):
        img = image(result["renders"][view])
        red_x = np.where((img[:, :, 0] > 100) & (img[:, :, 2] == 0))[1].mean()
        blue_x = np.where((img[:, :, 2] > 100) & (img[:, :, 0] == 0))[1].mean()
        assert (red_x > blue_x) == reverse


def test_detail_rasterization_reveals_subpixel_feature(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = tmp_path / "fine.step"
    base = colored_box((40, 40, 2), (0, 0, 0), "blue")
    mark = colored_box((0.02, 0.02, 0.1), (0, 0, 2), "red")
    export_step(Compound(children=[base, mark]), path)
    full = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"]})
    region = {"label": "fine", "x_min": 0.4, "y_min": 0.4, "x_max": 0.6, "y_max": 0.6}
    detail = generate_preview_renders(settings, {"step_file": str(path), "views": ["top"], "region": region, "resolution": 1200})
    assert full["success"] and detail["success"], (full, detail)
    full_pixels = image(full["renders"]["top"])
    detail_pixels = image(detail["renders"]["top_detail_fine"])
    red = lambda a: (a[:, :, 0] > 100) & (a[:, :, 2] == 0)
    assert red(full_pixels).sum() == 0
    assert red(detail_pixels).sum() >= 4


@pytest.mark.parametrize("region", [None, {}, {"label": "face", "x_min": 0.5, "y_min": 0, "x_max": 0.4, "y_max": 1},
    {"label": "face", "x_min": -0.1, "y_min": 0, "x_max": 1, "y_max": 1},
    {"label": "face", "x_min": 0, "y_min": 0, "x_max": float("nan"), "y_max": 1},
    {"label": "face", "x_min": True, "y_min": 0, "x_max": 1, "y_max": 1},
    {"label": "../bad", "x_min": 0, "y_min": 0, "x_max": 1, "y_max": 1},
    {"label": "tiny", "x_min": 0, "y_min": 0, "x_max": 0.00001, "y_max": 1}])
def test_invalid_region_is_rejected_before_renderer(tmp_path: Path, region) -> None:
    path = tmp_path / "empty.step"
    path.touch()
    result = generate_preview_renders(settings_for(tmp_path), {"step_file": str(path), "region": region})
    assert not result["success"] and "region" in result["error"], result


@pytest.mark.parametrize("resolution", [True, 799, 2049, 1000.5, "1200"])
def test_invalid_resolution_is_rejected_before_renderer(tmp_path: Path, resolution) -> None:
    path = tmp_path / "empty.step"
    path.touch()
    result = generate_preview_renders(settings_for(tmp_path), {"step_file": str(path), "resolution": resolution})
    assert not result["success"] and "resolution" in result["error"], result


@pytest.mark.parametrize("colors", [["red"], ["#GG0000"], "#ff0000", [1]])
def test_invalid_color_requests_fail_before_render(tmp_path: Path, colors) -> None:
    settings = settings_for(tmp_path)
    path = tmp_path / "empty.step"
    path.touch()
    result = generate_preview_renders(settings, {"step_file": str(path), "part_colors": colors})
    assert not result["success"] and "part_colors" in result["error"]


def test_stringified_views_transport_tolerance_and_rejection(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    path = tmp_path / "part.step"
    export_step(colored_box((10, 10, 2), (0, 0, 0), "red"), path)
    json_str = generate_preview_renders(settings, {"step_file": str(path), "views": '["top"]'})
    csv_str = generate_preview_renders(settings, {"step_file": str(path), "views": "iso, front"})
    assert json_str["success"] and set(json_str["renders"]) == {"top"}
    assert csv_str["success"] and set(csv_str["renders"]) == {"iso", "front"}
    for bad in ("", "   ", "[invalid", 123):
        rejected = generate_preview_renders(settings, {"step_file": str(path), "views": bad})
        assert not rejected["success"] and "views" in rejected["error"]


def test_left_view_orientation_and_geometry_summary(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    # Looking from -X toward +X ("left"): -Y is to the viewer's right, +Y is to the viewer's left.
    neg_y = colored_box((4, 4, 6), (0, -10, 0), "red")
    pos_y = colored_box((4, 4, 6), (0, 10, 0), "blue")
    path = tmp_path / "sides.step"
    export_step(Compound(children=[neg_y, pos_y]), path)

    result = generate_preview_renders(settings, {"step_file": str(path), "views": ["left", "right"]})
    assert result["success"] is True, result

    left_img = image(result["renders"]["left"])
    right_img = image(result["renders"]["right"])
    left_red_x = np.where((left_img[:, :, 0] > 100) & (left_img[:, :, 2] == 0))[1].mean()
    left_blue_x = np.where((left_img[:, :, 2] > 100) & (left_img[:, :, 0] == 0))[1].mean()
    right_red_x = np.where((right_img[:, :, 0] > 100) & (right_img[:, :, 2] == 0))[1].mean()
    right_blue_x = np.where((right_img[:, :, 2] > 100) & (right_img[:, :, 0] == 0))[1].mean()
    # In right (+X) view, +Y is right (blue_x > red_x); in left (-X) view, -Y is right (red_x > blue_x).
    assert right_blue_x > right_red_x
    assert left_red_x > left_blue_x

    summary = result["geometry_summary"]
    assert summary["part_count"] == 2
    assert summary["triangle_count"] >= 24
    assert summary["z_min_mm"] == pytest.approx(0.0, abs=1e-3)
    assert summary["bbox_size_mm"]["x"] == pytest.approx(4.0, abs=0.1)
    assert summary["bbox_size_mm"]["y"] == pytest.approx(24.0, abs=0.1)
    assert summary["bbox_size_mm"]["z"] == pytest.approx(6.0, abs=0.1)
