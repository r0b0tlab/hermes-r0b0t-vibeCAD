from __future__ import annotations

import os
from pathlib import Path

import pytest

from vibecad_public_plugin.config import ConfigError, project_dirs, project_root_for, settings_from_context


class FakeContext:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get_config(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def test_settings_preserves_configured_venv_python_symlink(tmp_path: Path) -> None:
    target = tmp_path / "base-python"
    target.write_text("placeholder", encoding="utf-8")
    shim = tmp_path / "venv" / "bin" / "python"
    shim.parent.mkdir(parents=True)
    os.symlink(target, shim)

    settings = settings_from_context(
        FakeContext(
            {
                "workspace_root": str(tmp_path),
                "python_executable": str(shim),
                "printer_profile": "generic-fdm-220",
            }
        )
    )

    assert settings.python_executable == shim
    assert settings.python_executable.is_symlink()


@pytest.mark.parametrize("directory", ["exports", "renders", "build"])
@pytest.mark.parametrize("existing", [True, False])
def test_project_dirs_rejects_symlinks_leaving_project(tmp_path: Path, directory: str, existing: bool) -> None:
    project = tmp_path / "workspace" / "demo"
    project.mkdir(parents=True)
    if directory != "build":
        (project / "source").mkdir()
    outside = tmp_path / "outside"
    if existing:
        outside.mkdir()
    (project / directory).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ConfigError):
        project_dirs(project)
    assert not (outside / "renders").exists()
    if not existing:
        assert not outside.exists()


def test_project_root_for_resolves_nested_exports_without_readme(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "statue"
    mesh = project / "exports" / "mesh-abc123" / "model.stl"
    handoff_step = project / "exports" / "handoff-revisions" / "rev999" / "source.step"
    mesh.parent.mkdir(parents=True)
    handoff_step.parent.mkdir(parents=True)
    mesh.write_bytes(b"solid s\nendsolid s\n")
    handoff_step.write_bytes(b"ISO-10303-21;")

    assert project_root_for(mesh, workspace) == project
    assert project_root_for(handoff_step, workspace) == project
    exports_dir, renders_dir = project_dirs(project_root_for(mesh, workspace))
    assert exports_dir == project / "exports"
    assert renders_dir == project / "renders"
