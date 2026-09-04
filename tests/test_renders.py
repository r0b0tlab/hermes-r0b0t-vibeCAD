from __future__ import annotations

import sys
from pathlib import Path

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.runtime import execute_and_export, generate_preview_renders


FIXTURE = Path(__file__).parent / "fixtures" / "model.py"


def test_generates_requested_deterministic_png_views(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(workspace_root=workspace, python_executable=Path(sys.executable), printer_profile="generic-fdm-220", printer_profiles_file=None, timeout_s=120)
    exported = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert exported["success"] is True

    rendered = generate_preview_renders(
        settings,
        {"step_file": exported["output"]["step"], "views": ["iso", "top", "bottom"], "part_colors": ["#00AA00", "#FFFFFF"]},
    )

    assert rendered["success"] is True
    assert set(rendered["renders"]) == {"iso", "top", "bottom"}
    for image in rendered["renders"].values():
        path = Path(image)
        assert path.is_file() and path.stat().st_size > 100
