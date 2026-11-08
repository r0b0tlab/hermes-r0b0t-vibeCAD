from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import trimesh

from .conftest import load_plugin
from .test_plugin_registration import FakeContext
from vibecad_public_plugin.config import Settings


def test_registered_mesh_bridge_sizes_and_hashes_source(tmp_path, monkeypatch):
    from vibecad_public_plugin import runtime
    project = tmp_path / 'model'
    (project / 'source').mkdir(parents=True)
    (project / 'README.md').write_text('# Mesh project\n')
    source = project / 'source' / 'generated.stl'
    trimesh.creation.box(extents=[10, 10, 20]).export(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    ctx = FakeContext()
    settings = Settings(tmp_path, Path(sys.executable), 'bambu-x2d', None, 120)
    monkeypatch.setattr(runtime, 'settings_from_context', lambda _ctx: settings)
    load_plugin().register(ctx)
    handler = ctx.tools['vibecad_prepare_mesh']
    payload = json.loads(handler({'mesh_file': str(source), 'height_mm': 152.4}))
    assert payload['success'], payload
    manifest = json.loads(Path(payload['manifest_path']).read_text())
    assert manifest['source']['sha256'] == before
    assert manifest['output']['sha256'] == hashlib.sha256(Path(payload['stl_path']).read_bytes()).hexdigest()
    assert abs(manifest['output']['extents_mm'][2] - 152.4) < 1e-4
    assert payload['printer_profile'] == 'bambu-x2d'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert manifest['scope']['sliced'] is False and manifest['scope']['manufacturability_checked'] is False
    repeated = json.loads(handler({'mesh_file': str(source), 'height_mm': 152.4}))
    assert repeated['success'] and repeated['stl_path'] != payload['stl_path']


def test_registered_mesh_bridge_refuses_bad_fit_and_open_mesh(tmp_path, monkeypatch):
    from vibecad_public_plugin import runtime
    project = tmp_path / 'model'
    (project / 'source').mkdir(parents=True)
    (project / 'README.md').write_text('# Mesh project\n')
    source = project / 'source' / 'shape.stl'
    trimesh.creation.box(extents=[10, 10, 1]).export(source)
    ctx = FakeContext()
    settings = Settings(tmp_path, Path(sys.executable), 'bambu-p2s', None, 120)
    monkeypatch.setattr(runtime, 'settings_from_context', lambda _ctx: settings)
    load_plugin().register(ctx)
    handler = ctx.tools['vibecad_prepare_mesh']
    too_wide = json.loads(handler({'mesh_file': str(source), 'height_mm': 50}))
    assert too_wide['success'] is False
    assert 'envelope' in too_wide['error']
    mesh = trimesh.creation.box()
    mesh.update_faces(range(len(mesh.faces)-1))
    mesh.export(source)
    invalid = json.loads(handler({'mesh_file': str(source), 'height_mm': 10}))
    assert invalid['success'] is False
    assert 'boundary' in invalid['error'] or 'watertight' in invalid['error']


def test_physical_p2s_limit_beats_oversized_custom_profile(tmp_path):
    from vibecad_public_plugin.runtime import prepare_mesh
    project = tmp_path / 'model'
    (project / 'source').mkdir(parents=True)
    (project / 'README.md').write_text('# Mesh project\n')
    source = project / 'source' / 'shape.stl'
    trimesh.creation.box(extents=[6, 1, 1]).export(source)
    profiles = json.loads((Path(__file__).parents[1] / 'profiles' / 'builtin.json').read_text())
    entry = next(p for p in profiles['profiles'] if p['id'] == 'bambu-p2s')
    entry['bed'].update(width_mm=500, depth_mm=500, height_mm=500, safe_margin_mm=0)
    override = tmp_path / 'profiles.json'
    override.write_text(json.dumps({'schema_version': 1, 'profiles': [entry]}))
    settings = Settings(tmp_path, Path(sys.executable), 'bambu-p2s', override, 120)
    result = prepare_mesh(settings, {'mesh_file': str(source), 'height_mm': 50})
    assert result['success'] is False and 'envelope' in result['error']
