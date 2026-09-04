from __future__ import annotations

from pathlib import Path

from vibecad_public_plugin.scripts.bootstrap import venv_python_path


def test_venv_python_path_is_portable(tmp_path: Path) -> None:
    assert venv_python_path(tmp_path / "cad", windows=False) == tmp_path / "cad" / "bin" / "python"
    assert venv_python_path(tmp_path / "cad", windows=True) == tmp_path / "cad" / "Scripts" / "python.exe"
