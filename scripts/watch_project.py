#!/usr/bin/env python3
"""Launch the generic persistent watcher in the configured CAD interpreter."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--python", dest="python_executable", default=sys.executable)
    known, _unknown = parser.parse_known_args()
    return known


def main() -> int:
    args = parse_args()
    executable = Path(args.python_executable).expanduser()
    worker = Path(__file__).resolve().with_name("watch_worker.py")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise SystemExit(f"CAD Python is unavailable: {executable}")
    os.execv(str(executable), [str(executable), str(worker), *sys.argv[1:]])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
