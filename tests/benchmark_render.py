"""Opt-in raster stress benchmark: python tests/benchmark_render.py [grid_cells].

Renders a two-part, wavy triangulated surface, not a STEP import benchmark.
The default 500x500 grid is exactly 500,000 triangles per view. This exercises
actual renderer code without making an expensive, artificial STEP fixture.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vibecad_public_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from vibecad_public_plugin.renders import RENDER_PROGRAM

n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
if not 1 <= n <= 1000:
    raise SystemExit("grid_cells must be between 1 and 1000")
# Replace only STEP ingestion; run the production projection and rasterizer.
start = RENDER_PROGRAM.index('shape = import_step(step_path)')
end = RENDER_PROGRAM.index('def color(value):')
mesh = '''
n = int(os.environ["GRID_CELLS"])
grid_x, grid_y = np.meshgrid(np.linspace(-50, 50, n+1), np.linspace(-50, 50, n+1))
z = 4*np.sin(grid_x/9)*np.cos(grid_y/11)
vertices = np.column_stack((grid_x.ravel(), grid_y.ravel(), z.ravel()))
rows, cols = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
a = (rows*(n+1) + cols).ravel()
faces = np.vstack((np.column_stack((a, a+1, a+n+1)), np.column_stack((a+1, a+n+2, a+n+1))))
part_faces = np.concatenate(((cols.ravel() >= n//2).astype(np.int32), (cols.ravel() >= n//2).astype(np.int32)))
parts = [(None, (1., 0., 0.)), (None, (0., 0., 1.))]
'''
program = RENDER_PROGRAM[:start] + mesh + RENDER_PROGRAM[end:]
with tempfile.TemporaryDirectory(prefix="vibecad-render-benchmark-") as directory:
    output = {name: str(Path(directory) / (name + ".png")) for name in ("iso", "top")}
    env = os.environ | {"VIBECAD_STEP_FILE": "unused.step", "VIBECAD_RENDER_OUTPUTS": json.dumps(output), "VIBECAD_PART_COLORS": "[]", "GRID_CELLS": str(n)}
    before = time.monotonic()
    result = subprocess.run([sys.executable, "-c", program], env=env, capture_output=True, text=True, timeout=120)
    elapsed = time.monotonic() - before
    print(f"triangles={2*n*n} views=2 elapsed_s={elapsed:.2f} exit={result.returncode}")
    print(result.stdout, result.stderr)
    if result.returncode or not all(Path(path).stat().st_size > 100 for path in output.values()):
        raise SystemExit(1)
    from PIL import Image
    import numpy as np
    for name, path in output.items():
        pixels = np.asarray(Image.open(path).convert("RGB"))
        red = ((pixels[:, :, 0] > 80) & (pixels[:, :, 1] == 0) & (pixels[:, :, 2] == 0)).sum()
        blue = ((pixels[:, :, 2] > 80) & (pixels[:, :, 0] == 0) & (pixels[:, :, 1] == 0)).sum()
        print(f"{name}: red_pixels={red} blue_pixels={blue}")
        if red < 1000 or blue < 1000:
            raise SystemExit("missing rendered part color")
