#!/usr/bin/env python3
"""Fail a release check when generated/private artifacts enter the public tree."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIRS = {"__pycache__", ".venv", "venv", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".gcode", ".step", ".stp", ".stl", ".3mf", ".pdf"}
FORBIDDEN_FILENAMES = {"result.json"}
FORBIDDEN_TEXT = ("/Users" + "/am", "gh" + "p_", "BEGIN PRIVATE" + " KEY")


def tracked_files() -> list[Path]:
    completed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, stdout=subprocess.PIPE)
    return [ROOT / item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT)
        if not path.is_file():
            failures.append(f"missing tracked file: {relative}")
            continue
        if any(part in FORBIDDEN_DIRS for part in relative.parts):
            failures.append(f"forbidden directory: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden generated artifact: {relative}")
        if relative.name in FORBIDDEN_FILENAMES:
            failures.append(f"forbidden generated artifact: {relative}")
        if path.suffix.lower() in {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".ini"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in FORBIDDEN_TEXT:
                if token in text:
                    failures.append(f"forbidden text {token!r}: {relative}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("release tree is clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
