#!/usr/bin/env python3
"""Write an editable generic FDM printer-profile catalog."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New JSON profile-catalog path")
    parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"output already exists: {output}; pass --force to replace it")
    template = Path(__file__).resolve().parents[1] / "examples" / "printer-profiles.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
