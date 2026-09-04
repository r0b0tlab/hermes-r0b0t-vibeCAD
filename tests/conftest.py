from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(tempfile.gettempdir()) / "hermes-r0b0t-vibeCAD-test-pkg"
LINK = PACKAGE_ROOT / "vibecad_public_plugin"


def pytest_configure() -> None:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    if LINK.is_symlink() and LINK.resolve() != REPO:
        LINK.unlink()
    if not LINK.exists():
        os.symlink(REPO, LINK, target_is_directory=True)
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))


def load_plugin():
    sys.modules.pop("vibecad_public_plugin", None)
    return importlib.import_module("vibecad_public_plugin")
