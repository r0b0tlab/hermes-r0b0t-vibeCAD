"""Minimal generic FDM example for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

import os
from pathlib import Path

from build123d import Align, Box, Compound, export_step

PARAMS = {
    "length": 60.0,  # mm: overall X span
    "width": 40.0,  # mm: overall Y span
    "height": 8.0,  # mm: overall Z span
}

body = Box(PARAMS["length"], PARAMS["width"], PARAMS["height"], align=(Align.CENTER, Align.CENTER, Align.MIN))
body.label = "body_01"
assembly = Compound(children=[body], label="example_fdm_part")
output = Path(os.environ["VIBECAD_OUTPUT_STEP"])
output.parent.mkdir(parents=True, exist_ok=True)
export_step(assembly, output)
print(f"[SUCCESS] Exported STEP to {output}")
