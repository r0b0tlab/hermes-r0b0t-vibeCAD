from __future__ import annotations

from pathlib import Path

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.parameters import modify_parameter


def settings(workspace: Path) -> Settings:
    return Settings(workspace_root=workspace, python_executable=None, printer_profile="generic-fdm-220", printer_profiles_file=None, timeout_s=120)


def test_modify_parameter_updates_only_the_target_numeric_literal(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    model = source / "model.py"
    model.write_text('PARAMS = {\n    "length": 42.0,  # mm: main span\n    "width": 10.0,  # mm: short span\n}\n', encoding="utf-8")

    result = modify_parameter(settings(workspace), {"script_path": str(model), "param_name": "length", "new_val": 45.0})

    assert result["success"] is True
    text = model.read_text(encoding="utf-8")
    assert '"length": 45.0,  # mm: main span' in text
    assert '"width": 10.0,  # mm: short span' in text


def test_modify_parameter_rejects_nonliteral_values(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    model = source / "model.py"
    model.write_text('PARAMS = {"length": 20 + 2}\n', encoding="utf-8")

    result = modify_parameter(settings(workspace), {"script_path": str(model), "param_name": "length", "new_val": 45.0})

    assert result["success"] is False
    assert "numeric literals" in result["error"]
