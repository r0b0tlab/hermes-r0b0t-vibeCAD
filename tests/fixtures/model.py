from __future__ import annotations

import os
from pathlib import Path

from build123d import Align, Box, Compound, Location, export_step

body = Box(42, 24, 6, align=(Align.CENTER, Align.CENTER, Align.MIN))
body.label = "body_01"
accent = Location((0, 0, 6)) * Box(12, 8, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
accent.label = "accent_01"
assembly = Compound(children=[body, accent], label="generic_fixture")
output = Path(os.environ["VIBECAD_OUTPUT_STEP"])
output.parent.mkdir(parents=True, exist_ok=True)
export_step(assembly, output)
print("fixture exported")
