#!/usr/bin/env python3
"""Create a portable CAD virtual environment for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def venv_python_path(venv_dir: Path, *, windows: bool) -> Path:
    return venv_dir / ("Scripts/python.exe" if windows else "bin/python")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", required=True, help="Target virtual-environment directory")
    parser.add_argument("--python", default=sys.executable, help="Python 3.12 or 3.13 interpreter used to create the venv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    venv_dir = Path(args.venv).expanduser().resolve()
    if not (REPO_ROOT / "pyproject.toml").is_file():
        raise SystemExit("Run bootstrap.py from a source checkout, not an installed wheel")
    requested = os.path.expanduser(args.python)
    resolved = shutil.which(requested)
    if resolved is None:
        raise SystemExit(f"Python interpreter is unavailable: {requested}")
    creator = Path(resolved).resolve()
    version_check = subprocess.run(
        [str(creator), "-c", "import sys; sys.exit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)"],
        check=False,
    )
    if version_check.returncode:
        raise SystemExit(f"CAD Python must be 3.12 or 3.13: {creator}")
    clean_env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    clean_env["PYTHONNOUSERSITE"] = "1"
    subprocess.run([str(creator), "-m", "venv", str(venv_dir)], check=True, env=clean_env)
    cad_python = venv_python_path(venv_dir, windows=os.name == "nt")
    subprocess.run([str(cad_python), "-m", "pip", "install", f"{REPO_ROOT}[cad]"], check=True, env=clean_env)
    smoke = subprocess.run(
        [str(cad_python), "-c", "import build123d, OCP, trimesh, numpy, PIL"],
        check=False,
        env=clean_env,
    )
    if smoke.returncode:
        raise SystemExit(f"CAD dependency verification failed in {cad_python}")
    print(cad_python)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
