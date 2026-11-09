"""Local STL-to-STL geometry handoff; not a slicer or a B-rep converter.

Run in vibeCAD's CAD Python (numpy and trimesh). Paths are confined to a
trusted workspace/project; callers must prevent concurrent hostile workspace
mutation. No repair, remeshing, network access or slicer invocation is done.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import uuid
from pathlib import Path
from typing import Sequence

import numpy as np
import trimesh


class MeshImportError(ValueError):
    """Unsafe path, invalid input, or a failed geometry/envelope check."""


def _absolute(value: str | Path, base: Path) -> Path:
    try:
        path = Path(value).expanduser()
        return Path(os.path.abspath(path if path.is_absolute() else base / path))
    except (TypeError, ValueError, OSError) as exc:
        raise MeshImportError('invalid path') from exc


def _beneath(path: Path, root: Path, *, allow_root: bool = False) -> None:
    if not path.is_relative_to(root) or (path == root and not allow_root):
        raise MeshImportError(f'path must be within {root}')
    # Reject even in-workspace symlinks, including dangling symlinks. All
    # subsequent access uses this normalized lexical path, not the input string.
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise MeshImportError(f'symlinks are not allowed: {current}')


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MeshImportError(f'{name} must be a finite positive number')
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise MeshImportError(f'{name} must be a finite positive number') from exc
    if not math.isfinite(number) or number <= 0:
        raise MeshImportError(f'{name} must be a finite positive number')
    return number


def _mesh(data: bytes) -> trimesh.Trimesh:
    """Load all raw STL triangles and index exact shared coordinates only.

    STL is triangle soup; indexing equal vertices is required for topology
    checks and does not weld nearby points or alter triangle coordinates.
    """
    try:
        loaded = trimesh.load(io.BytesIO(data), file_type='stl', process=False)
        if not isinstance(loaded, trimesh.Trimesh):
            raise MeshImportError('STL must contain a triangle mesh')
        triangles = np.asarray(loaded.triangles, dtype=np.float64)
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or len(triangles) == 0:
            raise MeshImportError('STL contains no triangles')
        if not np.isfinite(triangles).all():
            raise MeshImportError('STL contains nonfinite vertices')
        with np.errstate(over='ignore', invalid='ignore'):
            area2 = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                            triangles[:, 2] - triangles[:, 0]), axis=1)
        if not np.isfinite(area2).all() or np.any(area2 <= 0):
            raise MeshImportError('STL contains degenerate or invalid triangles')
        vertices, indices = np.unique(triangles.reshape(-1, 3), axis=0, return_inverse=True)
        mesh = trimesh.Trimesh(vertices=vertices, faces=indices.reshape(-1, 3), process=False)
        # Explicit edge incidence catches boundaries and non-manifold edges.
        if np.any(np.bincount(mesh.edges_unique_inverse) != 2):
            raise MeshImportError('mesh has boundary or non-manifold edges')
        if not mesh.is_watertight:
            raise MeshImportError('mesh is not watertight')
        if not mesh.is_winding_consistent:
            raise MeshImportError('mesh has inconsistent winding')
        components = trimesh.graph.connected_components(mesh.face_adjacency,
                                                         nodes=np.arange(len(mesh.faces)))
        if len(components) != 1:
            raise MeshImportError('mesh must be one connected shell')
        if not mesh.is_volume or not math.isfinite(mesh.volume) or mesh.volume <= 0:
            raise MeshImportError('mesh must enclose positive oriented volume')
        if not np.isfinite(mesh.bounds).all():
            raise MeshImportError('mesh has invalid bounds')
        return mesh
    except MeshImportError:
        raise
    except Exception as exc:
        raise MeshImportError(f'invalid STL mesh: {exc}') from exc


def import_stl(*, workspace_root: str | Path, project_root: str | Path,
               source_path: str | Path, dimension_mm: float,
               envelope_mm: Sequence[float], axis: str = 'z') -> dict:
    """Validate, uniformly size, bed-place and publish a single STL revision.

    Relative project/source paths are relative to workspace_root. The existing
    project must be strictly inside the workspace and source inside the project.
    dimension_mm is the target extent along axis (x/y/z), in millimeters;
    envelope_mm is the available rectangular (X, Y, Z) envelope after margins.
    The transformed minimum XYZ is (0,0,0); no rotation is performed. Source
    bytes are untouched. Returns absolute stl_path/manifest_path. Publication
    is a uniquely named directory under project/exports, manifest written last.

    Checks do not establish absence of self-intersections, minimum wall size,
    overhang support, bed adhesion, material suitability or successful slicing.
    """
    size = _positive(dimension_mm, 'dimension_mm')
    if axis not in ('x', 'y', 'z'):
        raise MeshImportError('axis must be x, y or z')
    try:
        if len(envelope_mm) != 3:
            raise MeshImportError('envelope_mm must contain X, Y and Z')
        envelope = np.array([_positive(v, 'envelope_mm') for v in envelope_mm])
    except (TypeError, OverflowError) as exc:
        raise MeshImportError('envelope_mm must contain X, Y and Z') from exc

    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (TypeError, OSError, ValueError) as exc:
        raise MeshImportError('workspace must exist') from exc
    if not root.is_dir():
        raise MeshImportError('workspace must be a directory')
    project = _absolute(project_root, root)
    _beneath(project, root)
    if not project.is_dir():
        raise MeshImportError('project must be an existing directory')
    source = _absolute(source_path, root)
    _beneath(source, root)
    _beneath(source, project)
    if source.suffix.lower() != '.stl' or not source.is_file():
        raise MeshImportError('source must be an existing STL file')
    exports = project / 'exports'
    _beneath(exports, root)
    if exports.exists() and not exports.is_dir():
        raise MeshImportError('exports must be a directory')

    try:
        source_bytes = source.read_bytes()
    except OSError as exc:
        raise MeshImportError(f'cannot read source: {exc}') from exc
    mesh = _mesh(source_bytes)
    extent = mesh.extents['xyz'.index(axis)]
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        scale = size / extent
        coords = (mesh.vertices - mesh.bounds[0]) * scale
    if not math.isfinite(scale) or scale <= 0 or not np.isfinite(coords).all():
        raise MeshImportError('scaled geometry is invalid')
    mesh.vertices = coords
    if np.any(mesh.extents > envelope):
        raise MeshImportError('mesh exceeds printer envelope')
    try:
        output_bytes = mesh.export(file_type='stl')
    except Exception as exc:
        raise MeshImportError(f'cannot export STL: {exc}') from exc
    # Validate actual serialized floats, not just the in-memory transform.
    try:
        output = _mesh(output_bytes)
    except MeshImportError as exc:
        raise MeshImportError(
            f'scaled STL serialization failed validation: {exc}; '
            'the source was not modified and no output was published'
        ) from exc
    bounds = output.bounds
    if np.any(bounds[0] < 0) or np.any(bounds[1] > envelope):
        raise MeshImportError('serialized mesh exceeds bed or printer envelope')
    if not math.isclose(float(output.extents['xyz'.index(axis)]), size, rel_tol=1e-6, abs_tol=1e-6):
        raise MeshImportError('serialized mesh does not retain requested dimension')

    revision = 'mesh-' + uuid.uuid4().hex
    folder = exports / revision
    stl = folder / 'model.stl'
    manifest_path = folder / 'manifest.json'
    manifest = {
        'schema_version': 1,
        'revision': revision,
        'source': {'path': str(source), 'sha256': hashlib.sha256(source_bytes).hexdigest()},
        'output': {'path': str(stl), 'sha256': hashlib.sha256(output_bytes).hexdigest(),
                   'bounds_mm': bounds.tolist(), 'extents_mm': output.extents.tolist()},
        'transform': {'axis': axis, 'dimension_mm': size, 'uniform_scale': float(scale),
                      'placement': 'minimum XYZ at origin; no rotation'},
        'checks': {'triangle_count': len(output.faces), 'watertight': True,
                   'winding_consistent': True, 'connected_components': 1,
                   'volume_mm3': float(output.volume), 'envelope_mm': envelope.tolist()},
        'scope': {'single_color': True, 'sliced': False, 'native_project': False,
                  'self_intersections_checked': False, 'manufacturability_checked': False},
    }
    created = False
    try:
        exports.mkdir(exist_ok=True)
        folder.mkdir()  # Exclusive; do not clobber any existing revision.
        created = True
        with stl.open('xb') as stream:
            stream.write(output_bytes)
        with manifest_path.open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, indent=2, allow_nan=False)
            stream.write('\n')
    except Exception:
        if created:
            shutil.rmtree(folder)
        raise
    return {'stl_path': str(stl), 'manifest_path': str(manifest_path)}
