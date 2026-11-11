"""Deterministic, headless STEP preview rendering."""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, cad_python, ensure_workspace, project_dirs, project_root_for, resolve_workspace_file
from .exports import ExportError, decode_json, run_cad, sha256


class RenderError(ValueError):
    """Invalid render request or failed headless renderer."""


RENDER_PROGRAM = r'''
import json
import math
import os
from pathlib import Path
from build123d import Location, export_stl, import_step
from PIL import Image
import numpy as np
import trimesh

step_path = Path(os.environ["VIBECAD_STEP_FILE"])
outputs = {name: Path(path) for name, path in json.loads(os.environ["VIBECAD_RENDER_OUTPUTS"]).items()}
requested = json.loads(os.environ.get("VIBECAD_PART_COLORS", "[]"))
render_views = json.loads(os.environ.get("VIBECAD_RENDER_VIEWS", "{}"))
region = json.loads(os.environ.get("VIBECAD_RENDER_REGION", "null"))
side = int(os.environ.get("VIBECAD_RENDER_RESOLUTION", "800"))
# Keep STEP assembly labels/colors instead of flattening away their metadata.
def collect(node, inherited=None, parent_location=None):
    if parent_location is None:
        parent_location = Location()
    paint = getattr(node, "color", None)
    if paint is None:
        paint = inherited
    if node.children:
        location = parent_location * node.location
        for child in node.children:
            yield from collect(child, paint, location)
    else:
        for solid in node.solids():
            yield parent_location * solid, paint

if step_path.suffix.lower() == ".stl":
    mesh = trimesh.load(step_path, force="mesh")
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise RuntimeError("STL contains no valid finite triangles")
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    part_faces = np.zeros(len(faces), dtype=np.int32)
    parts = [(None, None)]
else:
    shape = import_step(step_path)
    parts = list(collect(shape))
    if not parts:
        raise RuntimeError("STEP contains no solids")
    vertices_parts = []
    faces_parts = []
    part_faces = []
    offset = 0
    for index, (solid, _) in enumerate(parts):
        temporary = Path(os.environ["VIBECAD_RENDER_TEMP"]) / f"{index}.stl"
        try:
            export_stl(solid, temporary, tolerance=0.03, angular_tolerance=0.15)
            mesh = trimesh.load(temporary, force="mesh")
        finally:
            temporary.unlink(missing_ok=True)
        if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
            raise RuntimeError(f"solid {index + 1} triangulated empty")
        vertices_parts.append(np.asarray(mesh.vertices, dtype=float))
        faces_parts.append(np.asarray(mesh.faces, dtype=int) + offset)
        part_faces.append(np.full(len(mesh.faces), index, dtype=np.int32))
        offset += len(mesh.vertices)
    vertices = np.vstack(vertices_parts)
    faces = np.vstack(faces_parts)
    part_faces = np.concatenate(part_faces)

def color(value):
    text = str(value).lstrip('#')
    if len(text) != 6:
        raise ValueError("part_colors entries must be #RRGGBB")
    return tuple(int(text[i:i+2], 16) for i in (0, 2, 4))
palette = [color(v) for v in requested]

def solid_rgb(paint, index):
    if requested:
        return palette[index % len(palette)]
    if paint is not None:
        try:
            channels = tuple(paint)[:3]
            if len(channels) == 3:
                scale = 255.0 if max(channels) <= 1.0 else 1.0
                return tuple(max(0, min(255, int(round(channel * scale)))) for channel in channels)
        except Exception:
            pass
    return (180, 180, 180)

part_rgb = [solid_rgb(paint, index) for index, (_, paint) in enumerate(parts)]
light = np.array([0.25, -0.35, 0.90], dtype=float)
light /= np.linalg.norm(light)

def projection(name):
    x, y, z = vertices[:, 0], vertices[:, 1], vertices[:, 2]
    if name == "top": return np.column_stack((x, y)), z
    if name == "bottom": return np.column_stack((x, y)), -z
    if name == "front": return np.column_stack((x, z)), -y
    if name == "back": return np.column_stack((-x, z)), y
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
    # Construct exactly the historic 800px full frame first. The selected
    # rectangle is a camera viewport, never a filter on the STEP geometry.
    base, pad = 800, 40
    scale = min((base - 2 * pad) / span[0], (base - 2 * pad) / span[1])
    screen = np.empty_like(projected)
    screen[:, 0] = pad + (projected[:, 0] - low[0]) * scale
    screen[:, 1] = base - pad - (projected[:, 1] - low[1]) * scale
    bounds = (0.0, 0.0, 1.0, 1.0) if region is None else (region["x_min"], region["y_min"], region["x_max"], region["y_max"])
    x0, y0, x1, y1 = bounds
    zoom = side / (base * max(x1 - x0, y1 - y0))
    if region is not None or side != base:
        screen[:, 0] = (screen[:, 0] - base * (x0 + x1) / 2) * zoom + side / 2
        screen[:, 1] = (screen[:, 1] - base * (y0 + y1) / 2) * zoom + side / 2
    zbuf = np.full((side, side), -1e18)
    pixels = np.zeros((side, side, 3), dtype=np.uint8)
    pixels[:, :] = (247, 249, 251)
    # Bound fragment-grid allocations per chunk. Mesh and per-face arrays
    # still scale with triangle count; the scalar path handles larger triangles.
    tri_screen = screen[faces]
    mins = np.maximum(np.floor(tri_screen.min(axis=1)).astype(np.int32), 0)
    maxs = np.minimum(np.ceil(tri_screen.max(axis=1)).astype(np.int32), side - 1)
    dims = maxs - mins + 1
    small = (dims[:, 0] > 0) & (dims[:, 1] > 0) & (dims[:, 0] <= 8) & (dims[:, 1] <= 8)
    small_indices = np.flatnonzero(small)
    # Shading is constant per face, computed once in vectorized form.
    edge_a = vertices[faces[:, 1]] - vertices[faces[:, 0]]
    edge_b = vertices[faces[:, 2]] - vertices[faces[:, 0]]
    normals = np.cross(edge_a, edge_b)
    lengths = np.linalg.norm(normals, axis=1)
    shade = 0.42 + 0.58 * np.abs(normals @ light) / np.maximum(lengths, 1e-30)
    shade[lengths <= 1e-9] = 0.72
    face_rgb = np.clip(np.rint(np.asarray(part_rgb)[part_faces] * shade[:, None]), 0, 255).astype(np.uint8)
    dx = np.tile(np.arange(8), 8)
    dy = np.repeat(np.arange(8), 8)
    flat_z = zbuf.ravel()
    flat_pixels = pixels.reshape(-1, 3)
    for start in range(0, len(small_indices), 1024):
        ids = small_indices[start:start + 1024]
        pts = tri_screen[ids]
        x = mins[ids, 0, None] + dx
        y = mins[ids, 1, None] + dy
        x0, y0 = pts[:, 0, 0, None], pts[:, 0, 1, None]
        x1, y1 = pts[:, 1, 0, None], pts[:, 1, 1, None]
        x2, y2 = pts[:, 2, 0, None], pts[:, 2, 1, None]
        den = (y1-y2)*(x0-x2) + (x2-x1)*(y0-y2)
        safe_den = np.where(np.abs(den) < 1e-8, 1, den)
        w0 = ((y1-y2)*(x+0.5-x2) + (x2-x1)*(y+0.5-y2)) / safe_den
        w1 = ((y2-y0)*(x+0.5-x2) + (x0-x2)*(y+0.5-y2)) / safe_den
        w2 = 1-w0-w1
        zs = depth[faces[ids]]
        zz = w0*zs[:, 0, None] + w1*zs[:, 1, None] + w2*zs[:, 2, None]
        mask = ((x <= maxs[ids, 0, None]) & (y <= maxs[ids, 1, None]) &
                (np.abs(den) >= 1e-8) & (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4))
        pix = (y * side + x)[mask]
        zz = zz[mask]
        face_ids = np.broadcast_to(ids[:, None], mask.shape)[mask]
        if not len(pix):
            continue
        # Select closest fragment, breaking equal-depth ties by lowest face id.
        best = np.full(side * side, -1e18)
        np.maximum.at(best, pix, zz)
        eligible = (zz == best[pix]) & (zz > flat_z[pix])
        pix, face_ids = pix[eligible], face_ids[eligible]
        if len(pix):
            order = np.lexsort((face_ids, pix))
            pix, face_ids = pix[order], face_ids[order]
            first = np.r_[True, pix[1:] != pix[:-1]]
            pix, face_ids = pix[first], face_ids[first]
            flat_z[pix] = best[pix]
            flat_pixels[pix] = face_rgb[face_ids]
    for face_index in np.flatnonzero(~small):
        tri = faces[face_index]
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
        pixels[miny:maxy + 1, minx:maxx + 1][mask] = face_rgb[face_index]
    # Letterbox rectangular selections, after depth testing the entire scene.
    if region is not None:
        x0, y0, x1, y1 = bounds
        width, height = side * (x1 - x0) / max(x1 - x0, y1 - y0), side * (y1 - y0) / max(x1 - x0, y1 - y0)
        xx = np.arange(side) + 0.5
        yy = np.arange(side) + 0.5
        outside_x = (xx < (side-width)/2) | (xx >= (side+width)/2)
        outside_y = (yy < (side-height)/2) | (yy >= (side+height)/2)
        pixels[:, outside_x] = (247, 249, 251)
        pixels[outside_y, :] = (247, 249, 251)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode="RGB").save(output)

for name, output in outputs.items():
    render(render_views.get(name, name), output)
print(json.dumps({"outputs": {name: str(path) for name, path in outputs.items()}}, sort_keys=True))
'''


def generate_preview_renders(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        has_step, has_mesh = args.get("step_file") is not None, args.get("mesh_file") is not None
        if has_step == has_mesh:
            raise RenderError("provide exactly one of step_file or mesh_file")
        step_file = resolve_workspace_file(args.get("step_file") if has_step else args.get("mesh_file"), settings,
                                           suffixes={".step", ".stp"} if has_step else {".stl"})
        requested = args.get("views", ["iso", "top", "bottom", "front", "right"])
        if isinstance(requested, str) and requested.strip():
            stripped = requested.strip()
            if stripped.startswith("["):
                try:
                    requested = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise RenderError("views must be a non-empty array") from exc
            else:
                requested = [part.strip() for part in stripped.split(",") if part.strip()]
        if not isinstance(requested, list) or not requested:
            raise RenderError("views must be a non-empty array")
        allowed = {"iso", "top", "bottom", "front", "back", "right"}
        views: list[str] = []
        for raw in requested:
            view = str(raw).lower().strip()
            if view not in allowed:
                raise RenderError(f"unsupported view {raw!r}")
            if view not in views:
                views.append(view)
        project = project_root_for(step_file, ensure_workspace(settings))
        _exports, render_dir = project_dirs(project)
        colors = args.get("part_colors", [])
        if not isinstance(colors, list) or any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors):
            raise RenderError("part_colors must be an array of #RRGGBB strings")
        region = args.get("region")
        if "region" in args:
            fields = {"label", "x_min", "y_min", "x_max", "y_max"}
            if not isinstance(region, dict) or set(region) != fields:
                raise RenderError("region must contain label, x_min, y_min, x_max, y_max")
            if not isinstance(region["label"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", region["label"]):
                raise RenderError("region label must be 1-32 letters, digits, underscores or hyphens, starting with a letter or digit")
            for field in ("x_min", "y_min", "x_max", "y_max"):
                value = region[field]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise RenderError("region coordinates must be finite numbers between 0 and 1")
            if region["x_max"] - region["x_min"] < 0.001 or region["y_max"] - region["y_min"] < 0.001:
                raise RenderError("region width and height must each be at least 0.001")
        resolution = args.get("resolution", 1600 if region is not None else 800)
        if isinstance(resolution, bool) or not isinstance(resolution, int) or not 800 <= resolution <= 2048:
            raise RenderError("resolution must be an integer from 800 to 2048")
        # A new invocation always gets fresh paths, so older MEDIA references
        # remain immutable even when the input STEP is replaced in place.
        source_hash = sha256(step_file)
        render_id = uuid.uuid4().hex
        named_views = {(f"{view}_detail_{region['label']}" if region is not None else view): view for view in views}
        outputs = {name: str(render_dir / f"preview_{render_id}_{name}.png") for name in named_views}
        try:
            with tempfile.TemporaryDirectory(prefix=".vibecad-render-", dir=render_dir) as temporary:
                snapshot = Path(temporary) / ("source.step" if has_step else "source.stl")
                shutil.copyfile(step_file, snapshot)
                if sha256(snapshot) != source_hash:
                    raise RenderError(f"source {'STEP' if has_step else 'STL'} changed during preview snapshot")
                completed = run_cad(settings, [str(cad_python(settings)), "-c", RENDER_PROGRAM], cwd=project, env_updates={"VIBECAD_STEP_FILE": str(snapshot), "VIBECAD_RENDER_OUTPUTS": json.dumps(outputs), "VIBECAD_RENDER_VIEWS": json.dumps(named_views), "VIBECAD_RENDER_REGION": json.dumps(region), "VIBECAD_RENDER_RESOLUTION": str(resolution), "VIBECAD_PART_COLORS": json.dumps(colors), "VIBECAD_RENDER_TEMP": temporary})
                rendered = decode_json(completed, "preview rendering")
                if sha256(step_file) != source_hash:
                    raise RenderError(f"source {'STEP' if has_step else 'STL'} changed during preview rendering")
                if rendered.get("outputs") != outputs:
                    raise RenderError("renderer returned unexpected output paths")
                missing = [path for path in outputs.values() if not Path(path).is_file() or Path(path).stat().st_size == 0]
                if missing:
                    raise RenderError(f"renderer did not create: {missing}")
                render_hashes = {name: sha256(Path(path)) for name, path in outputs.items()}
        except (ExportError, RenderError, OSError):
            for path in outputs.values():
                Path(path).unlink(missing_ok=True)
            raise
        result = {"success": True, "source_sha256": source_hash, "renders": outputs,
                  "render_sha256": render_hashes,
                  "render_metadata": {name: {"view": view, "region": region, "resolution": resolution} for name, view in named_views.items()},
                  "media": [f"MEDIA:{path}" for path in outputs.values()]}
        if has_step:
            result.update({"step_file": str(step_file), "source_step_sha256": source_hash})
        else:
            result["mesh_file"] = str(step_file)
        return result
    except (ConfigError, ExportError, RenderError, OSError) as exc:
        return {"success": False, "error": str(exc)}
