"""Load the root plugin as a real package when a script runs directly."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "_hermes_r0b0t_vibecad_script"


def load_module(name: str):
    if PACKAGE_NAME not in sys.modules:
        spec = importlib.util.spec_from_file_location(PACKAGE_NAME, PLUGIN_ROOT / "__init__.py", submodule_search_locations=[str(PLUGIN_ROOT)])
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not load plugin package from {PLUGIN_ROOT}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{PACKAGE_NAME}.{name}")
