from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from vibecad_public_plugin.mesh_bridge import MeshImportError, import_stl


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def context(tmp_path):
    root = tmp_path / 'workspace'
    project = root / 'project'
    (project / 'source').mkdir(parents=True)
    return root, project


def put(project, mesh, name='model.stl'):
    path = project / 'source' / name
    path.write_bytes(mesh.export(file_type='stl'))
    return path


def run(context, source, **overrides):
    root, project = context
    options = dict(workspace_root=root, project_root=project, source_path=source,
                   dimension_mm=152.4, axis='z', envelope_mm=(235.5, 256, 256))
    options.update(overrides)
    return import_stl(**options)


def test_real_roundtrip_scale_bed_hashes_and_unique_revisions(context):
    root, project = context
    source = put(project, trimesh.creation.box(extents=(2, 3, 4)))
    before = source.read_bytes()
    a, b = run(context, source), run(context, source)
    assert source.read_bytes() == before
    assert a['stl_path'] != b['stl_path']
    out, manifest = Path(a['stl_path']), Path(a['manifest_path'])
    assert out.is_relative_to(project / 'exports') and manifest.parent == out.parent
    data = json.loads(manifest.read_text())
    assert data['source']['sha256'] == digest(before)
    assert data['output']['sha256'] == digest(out.read_bytes())
    assert data['source']['path'] == str(source)
    assert data['output']['path'] == str(out)
    mesh = trimesh.load(out, force='mesh')
    assert np.allclose(mesh.extents, (76.2, 114.3, 152.4), atol=1e-4)
    assert np.allclose(mesh.bounds[0], 0, atol=1e-6)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.is_volume
    assert data['checks']['connected_components'] == 1
    assert data['checks']['watertight'] and data['checks']['winding_consistent']
    assert data['output']['bounds_mm'][0] == pytest.approx([0, 0, 0], abs=1e-6)
    assert data['scope']['sliced'] is False


def test_generic_axis_and_relative_paths(context):
    root, project = context
    source = put(project, trimesh.creation.box(extents=(2, 3, 4)))
    result = run(context, source.relative_to(root), project_root=project.relative_to(root),
                 dimension_mm=25, axis='x', envelope_mm=(30, 40, 60))
    mesh = trimesh.load(result['stl_path'], force='mesh')
    assert mesh.extents == pytest.approx([25, 37.5, 50])


@pytest.mark.parametrize('dimension', [0, -1, float('nan'), float('inf'), True, '5'])
def test_invalid_dimension(context, dimension):
    source = put(context[1], trimesh.creation.box())
    with pytest.raises(MeshImportError):
        run(context, source, dimension_mm=dimension)


@pytest.mark.parametrize('envelope', [(0, 2, 3), (1, float('nan'), 3), (1, 2), (1, 2, float('inf')), (True, 2, 3)])
def test_invalid_envelope(context, envelope):
    source = put(context[1], trimesh.creation.box())
    with pytest.raises(MeshImportError):
        run(context, source, envelope_mm=envelope)


@pytest.mark.parametrize('axis', ['X', 'height', '', 2])
def test_invalid_axis(context, axis):
    source = put(context[1], trimesh.creation.box())
    with pytest.raises(MeshImportError):
        run(context, source, axis=axis)


def test_out_of_envelope_on_xy_and_height(context):
    source = put(context[1], trimesh.creation.box(extents=(4, 3, 2)))
    for envelope in [(300, 256, 256), (400, 200, 256), (400, 300, 100)]:
        with pytest.raises(MeshImportError, match='envelope'):
            run(context, source, envelope_mm=envelope)
    assert not (context[1] / 'exports').exists()


def test_open_winding_disconnected_and_nonmanifold_rejected(context):
    box = trimesh.creation.box()
    open_mesh = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-1], process=False)
    winding = box.copy()
    winding.faces[0] = winding.faces[0][::-1]
    other = box.copy()
    other.apply_translation([3, 0, 0])
    disconnected = trimesh.util.concatenate([box, other])
    # Three faces on one edge, rather than two.
    nonmanifold = trimesh.Trimesh(vertices=box.vertices, faces=np.vstack([box.faces, box.faces[0]]), process=False)
    inverted = box.copy()
    inverted.invert()
    for i, mesh in enumerate([open_mesh, winding, disconnected, nonmanifold, inverted]):
        source = put(context[1], mesh, f'bad-{i}.stl')
        with pytest.raises(MeshImportError):
            run(context, source)
    assert not (context[1] / 'exports').exists()


def test_empty_invalid_nonfinite_and_degenerate_triangles(context):
    project = context[1]
    for i, raw in enumerate([b'', b'garbage', b'solid a\nendsolid a\n']):
        p = project / 'source' / f'bad{i}.stl'
        p.write_bytes(raw)
        with pytest.raises(MeshImportError):
            run(context, p)
    box = trimesh.creation.box()
    for i, vertices in enumerate([[[0,0,0],[0,0,0],[0,0,0]], [[float('nan'),0,0],[1,0,0],[0,1,0]]]):
        raw = bytearray(box.export(file_type='stl'))
        import struct
        raw[96:132] = struct.pack('<9f', *(v for row in vertices for v in row))
        p = project / 'source' / f'badtri{i}.stl'
        p.write_bytes(raw)
        with pytest.raises(MeshImportError):
            run(context, p)


def test_workspace_project_and_symlink_escape_rejected(context, tmp_path):
    root, project = context
    outside = tmp_path / 'outside'
    outside.mkdir()
    external = outside / 'evil.stl'
    external.write_bytes(trimesh.creation.box().export(file_type='stl'))
    good = put(project, trimesh.creation.box())
    link = project / 'source' / 'link.stl'
    link.symlink_to(external)
    (project / 'source' / 'escape').symlink_to(outside, target_is_directory=True)
    for bad in [external, link, project / 'source' / 'escape' / 'evil.stl', root / '..' / 'outside' / 'evil.stl']:
        with pytest.raises(MeshImportError):
            run(context, bad)
    with pytest.raises(MeshImportError):
        run(context, good, project_root=outside)
    (project / 'exports').symlink_to(outside, target_is_directory=True)
    with pytest.raises(MeshImportError):
        run(context, good)
    assert not list(outside.glob('mesh-*'))


def test_source_must_be_regular_stl_inside_project(context, tmp_path):
    root, project = context
    source = put(project, trimesh.creation.box())
    sibling = root / 'sibling'
    (sibling / 'source').mkdir(parents=True)
    sibling_source = put(sibling, trimesh.creation.box())
    for bad in [sibling_source, source.with_name('missing.stl'), project / 'source', source.with_suffix('.obj')]:
        with pytest.raises(MeshImportError):
            run(context, bad)
    with pytest.raises(MeshImportError):
        run(context, source, project_root=root)


def test_quantization_collapse_reports_scaled_output_and_does_not_publish(context):
    vertices = np.array([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0], [-1.0, -1.0, 1.0],
        [1e-10, 1e-10, 0.0],
    ])
    faces = np.array([
        [3, 1, 2], [0, 1, 3], [3, 2, 0],
        [0, 2, 4], [2, 1, 4], [1, 0, 4],
    ])
    original = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    assert original.is_watertight and original.is_volume
    source = put(context[1], original, 'quantization.stl')
    before = source.read_bytes()
    with pytest.raises(MeshImportError, match='scaled STL serialization'):
        run(context, source, dimension_mm=240.0,
            envelope_mm=(1000.0, 1000.0, 1000.0))
    assert source.read_bytes() == before
    assert not (context[1] / 'exports').exists()
