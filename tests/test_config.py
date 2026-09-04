from __future__ import annotations

import os
from pathlib import Path

from vibecad_public_plugin.config import settings_from_context


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
