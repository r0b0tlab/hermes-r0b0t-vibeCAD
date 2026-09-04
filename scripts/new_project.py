#!/usr/bin/env python3
"""Create a generic FDM vibeCAD project under a trusted workspace."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


MODEL_TEMPLATE = '''"""Parametric FDM model exported by hermes-r0b0t-vibeCAD."""
from __future__ import annotations
import os
from pathlib import Path
from build123d import Align, Box, Compound, export_step

PARAMS = {
    "length": 60.0,  # mm: overall X span
    "width": 40.0,   # mm: overall Y span
    "height": 8.0,   # mm: overall Z span
}

body = Box(PARAMS["length"], PARAMS["width"], PARAMS["height"], align=(Align.CENTER, Align.CENTER, Align.MIN))
body.label = "body_01"
assembly = Compound(children=[body], label="fdm_assembly")
output = Path(os.environ["VIBECAD_OUTPUT_STEP"])
output.parent.mkdir(parents=True, exist_ok=True)
export_step(assembly, output)
print(f"[SUCCESS] Exported STEP to {output}")
'''

README_TEMPLATE = '''# {name}

Generic FDM vibeCAD project.

- `source/model.py` is the parametric source of truth.
- `exports/` receives STEP, STL, 3MF, and generic slicer handoff artifacts.
- `renders/` receives deterministic previews.

Select a printer profile before exporting. The plugin validates the model envelope and bed datum but never sends a print.
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Kebab-case project name")
    parser.add_argument("--workspace-root", default=str(Path.home() / "vibecad-projects"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.name):
        raise SystemExit("project name must be kebab-case, 1–64 characters")
    root = Path(args.workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"workspace root does not exist: {root}")
    project = root / args.name
    if project.exists():
        raise SystemExit(f"project already exists: {project}")
    (project / "source").mkdir(parents=True)
    (project / "exports").mkdir()
    (project / "renders").mkdir()
    (project / "source" / "model.py").write_text(MODEL_TEMPLATE, encoding="utf-8")
    (project / "README.md").write_text(README_TEMPLATE.format(name=args.name), encoding="utf-8")
    print(project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
