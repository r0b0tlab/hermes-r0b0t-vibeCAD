#!/usr/bin/env python3
"""Create a portable CAD virtual environment for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def venv_python_path(venv_dir: Path, *, windows: bool) -> Path:
    return venv_dir / ("Scripts/python.exe" if windows else "bin/python")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", required=True, help="Target virtual-environment directory")
    parser.add_argument("--python", default=sys.executable, help="Python 3.12+ interpreter used to create the venv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    venv_dir = Path(args.venv).expanduser().resolve()
    creator = Path(args.python).expanduser()
    if not creator.is_file() or not os.access(creator, os.X_OK):
        raise SystemExit(f"Python interpreter is unavailable: {creator}")
    subprocess.run([str(creator), "-m", "venv", str(venv_dir)], check=True)
    cad_python = venv_python_path(venv_dir, windows=os.name == "nt")
    subprocess.run([str(cad_python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(cad_python), "-m", "pip", "install", "--upgrade", f"{REPO_ROOT}[cad]"], check=True)
    print(cad_python)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
