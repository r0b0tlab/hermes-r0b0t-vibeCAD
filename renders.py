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
from PIL import Image
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
palette = [color(v) for v in requested] if requested else [(0, 122, 61), (236, 236, 232)]

def solid_rgb(solid, index):
    if requested:
        return palette[index % len(palette)]
    paint = getattr(solid, "color", None)
    if paint is not None:
        try:
            channels = tuple(paint)[:3]
            if len(channels) == 3:
                scale = 255.0 if max(channels) <= 1.0 else 1.0
                return tuple(max(0, min(255, int(round(channel * scale)))) for channel in channels)
        except Exception:
            pass
    return palette[index % len(palette)]

part_rgb = [solid_rgb(solid, index) for index, solid in enumerate(solids)]
light = np.array([0.25, -0.35, 0.90], dtype=float)
light /= np.linalg.norm(light)

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
    zbuf = np.full((side, side), -1e18)
    pixels = np.zeros((side, side, 3), dtype=np.uint8)
    pixels[:, :] = (247, 249, 251)
    for face_index, tri in enumerate(faces):
        pts = screen[tri]
        zs = depth[tri]
        minx = max(int(np.floor(pts[:, 0].min())), 0)
        maxx = min(int(np.ceil(pts[:, 0].max())), side - 1)
        miny = max(int(np.floor(pts[:, 1].min())), 0)
        maxy = min(int(np.ceil(pts[:, 1].max())), side - 1)
        if minx > maxx or miny > maxy:
            continue
        x0, y0 = pts[0]
        x1, y1 = pts[1]
        x2, y2 = pts[2]
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-8:
            continue
        xs = np.arange(minx, maxx + 1) + 0.5
        ys = np.arange(miny, maxy + 1) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        w0 = ((y1 - y2) * (grid_x - x2) + (x2 - x1) * (grid_y - y2)) / den
        w1 = ((y2 - y0) * (grid_x - x2) + (x0 - x2) * (grid_y - y2)) / den
        w2 = 1.0 - w0 - w1
        zz = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
        window = zbuf[miny:maxy + 1, minx:maxx + 1]
        mask = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4) & (zz > window)
        if not np.any(mask):
            continue
        window[mask] = zz[mask]
        zbuf[miny:maxy + 1, minx:maxx + 1] = window
        edge_a = vertices[tri[1]] - vertices[tri[0]]
        edge_b = vertices[tri[2]] - vertices[tri[0]]
        normal = np.cross(edge_a, edge_b)
        norm = float(np.linalg.norm(normal))
        shade = 0.72
        if norm > 1e-9:
            shade = 0.42 + 0.58 * abs(float(np.dot(normal / norm, light)))
        base = part_rgb[int(part_faces[face_index])]
        pixels[miny:maxy + 1, minx:maxx + 1][mask] = tuple(max(0, min(255, int(round(channel * shade)))) for channel in base)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode="RGB").save(output)

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
        return {"success": True, "step_file": str(step_file), "renders": rendered["outputs"], "media": [f"MEDIA:{path}" for path in rendered["outputs"].values()]}
    except (ConfigError, ExportError, RenderError) as exc:
        return {"success": False, "error": str(exc)}
