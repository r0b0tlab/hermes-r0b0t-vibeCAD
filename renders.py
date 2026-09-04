"""Deterministic, headless STEP preview rendering."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_workspace_file
from .exports import ExportError, decode_json, run_cad


class RenderError(ValueError):
    """Invalid render request or failed headless renderer."""


RENDER_PROGRAM = r'''
import json
import math
import os
from pathlib import Path
from build123d import export_stl, import_step
from PIL import Image, ImageDraw
import numpy as np
import trimesh

step_path = Path(os.environ["VIBECAD_STEP_FILE"])
outputs = {name: Path(path) for name, path in json.loads(os.environ["VIBECAD_RENDER_OUTPUTS"]).items()}
requested = json.loads(os.environ.get("VIBECAD_PART_COLORS", "[]"))
shape = import_step(step_path)
solids = list(shape.solids())
if not solids:
    raise RuntimeError("STEP contains no solids")
vertices_parts = []
faces_parts = []
part_faces = []
offset = 0
for index, solid in enumerate(solids):
    temporary = step_path.parent / f".vibecad-render-{os.getpid()}-{index}.stl"
    export_stl(solid, temporary, tolerance=0.03, angular_tolerance=0.15)
    mesh = trimesh.load(temporary, force="mesh")
    temporary.unlink(missing_ok=True)
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise RuntimeError(f"solid {index + 1} triangulated empty")
    vertices_parts.append(np.asarray(mesh.vertices, dtype=float))
    faces_parts.append(np.asarray(mesh.faces, dtype=int) + offset)
    part_faces.extend([index] * len(mesh.faces))
    offset += len(mesh.vertices)
vertices = np.vstack(vertices_parts)
faces = np.vstack(faces_parts)
part_faces = np.asarray(part_faces, dtype=int)

def color(value):
    text = str(value).lstrip('#')
    if len(text) != 6:
        raise ValueError("part_colors entries must be #RRGGBB")
    return tuple(int(text[i:i+2], 16) for i in (0, 2, 4))
palette = [color(v) for v in requested] if requested else [(0, 132, 88), (235, 155, 60), (110, 150, 200), (180, 130, 190)]

def projection(name):
    x, y, z = vertices[:, 0], vertices[:, 1], vertices[:, 2]
    if name == "top": return np.column_stack((x, y)), z
    if name == "bottom": return np.column_stack((x, y)), -z
    if name == "front": return np.column_stack((x, z)), -y
    if name == "right": return np.column_stack((y, z)), x
    elevation = math.radians(30)
    screen_x = (x - y) / math.sqrt(2)
    screen_y = (x + y) * math.sin(elevation) / math.sqrt(2) + z * math.cos(elevation)
    depth = -(x + y) * math.cos(elevation) / math.sqrt(2) + z * math.sin(elevation)
    return np.column_stack((screen_x, screen_y)), depth

def render(name, output):
    projected, depth = projection(name)
    low, high = projected.min(axis=0), projected.max(axis=0)
    span = np.maximum(high - low, 1e-9)
    side, pad = 800, 40
    scale = min((side - 2 * pad) / span[0], (side - 2 * pad) / span[1])
    screen = np.empty_like(projected)
    screen[:, 0] = pad + (projected[:, 0] - low[0]) * scale
    screen[:, 1] = side - pad - (projected[:, 1] - low[1]) * scale
    image = Image.new("RGB", (side, side), (247, 249, 251))
    draw = ImageDraw.Draw(image)
    order = np.argsort(depth[faces].mean(axis=1))
    depth_low = float(depth.min())
    depth_span = max(float(depth.max()) - depth_low, 1e-9)
    for face_index in order:
        points = [(float(screen[v, 0]), float(screen[v, 1])) for v in faces[face_index]]
        base = palette[int(part_faces[face_index]) % len(palette)]
        local_depth = float(depth[faces[face_index]].mean())
        shade = 0.45 + 0.55 * max(0.0, min(1.0, (local_depth - depth_low) / depth_span))
        draw.polygon(points, fill=tuple(round(channel * shade) for channel in base))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)

for name, output in outputs.items():
    render(name, output)
print(json.dumps({"outputs": {name: str(path) for name, path in outputs.items()}}, sort_keys=True))
'''


def generate_preview_renders(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        step_file = resolve_workspace_file(args.get("step_file"), settings, suffixes={".step", ".stp"})
        requested = args.get("views") or ["iso", "top", "bottom", "front", "right"]
        if not isinstance(requested, list) or not requested:
            raise RenderError("views must be a non-empty array")
        allowed = {"iso", "top", "bottom", "front", "right"}
        views: list[str] = []
        for raw in requested:
            view = str(raw).lower().strip()
            if view not in allowed:
                raise RenderError(f"unsupported view {raw!r}")
            if view not in views:
                views.append(view)
        project = project_root_for(step_file, ensure_workspace(settings))
        _exports, render_dir = project_dirs(project)
        outputs = {view: str(render_dir / f"preview_{view}.png") for view in views}
        completed = run_cad(settings, [str(cad_python(settings)), "-c", RENDER_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(step_file), "VIBECAD_RENDER_OUTPUTS": json.dumps(outputs), "VIBECAD_PART_COLORS": json.dumps(args.get("part_colors") or [])})
        rendered = decode_json(completed, "preview rendering")
        missing = [path for path in outputs.values() if not Path(path).is_file() or Path(path).stat().st_size == 0]
        if missing:
            raise RenderError(f"renderer did not create: {missing}")
        return {"success": True, "step_file": str(step_file), "renders": rendered["outputs"]}
    except (ConfigError, ExportError, RenderError) as exc:
        return {"success": False, "error": str(exc)}
