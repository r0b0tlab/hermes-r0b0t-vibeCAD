"""A two-part parametric demonstration for the P2S manual slicer handoff.

The body and raised accent touch at one planar face; they do not overlap.
"""

from __future__ import annotations

import os
from pathlib import Path

from build123d import Align, Box, Color, Compound, Location, export_step

PARAMS = {
    "length": 42.0,  # mm, body length
    "width": 24.0,  # mm, body width
    "height": 6.0,  # mm, body height
    "accent_height": 1.0,  # mm
}

body = Box(PARAMS["length"], PARAMS["width"], PARAMS["height"], align=(Align.CENTER, Align.CENTER, Align.MIN))
body.label = "body_01"
body.color = Color("#0086D6")
accent = Location((0, 0, PARAMS["height"])) * Box(12, 8, PARAMS["accent_height"], align=(Align.CENTER, Align.CENTER, Align.MIN))
accent.label = "accent_01"
accent.color = Color("#FFFFFF")
assembly = Compound(children=[body, accent], label="vibecad_demo")
output = Path(os.environ["VIBECAD_OUTPUT_STEP"])
output.parent.mkdir(parents=True, exist_ok=True)
export_step(assembly, output)
print(f"Exported {output}")
