from __future__ import annotations
import hashlib
import sys
from pathlib import Path
import trimesh
from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.renders import generate_preview_renders


def test_mesh_detail_view_and_source_hash(tmp_path: Path):
    project = tmp_path / 'fig'
    (project / 'source').mkdir(parents=True)
    (project / 'README.md').write_text('# figure')
    mesh = project / 'source' / 'figure.stl'
    trimesh.creation.box(extents=(10, 8, 30)).export(mesh)
    result = generate_preview_renders(Settings(tmp_path, Path(sys.executable), 'bambu-x2d', None, 120),
        {'mesh_file': str(mesh), 'views': ['front', 'back'], 'region': {'label':'head', 'x_min':0.2, 'y_min':0.1, 'x_max':0.8, 'y_max':0.5}, 'resolution':800})
    assert result['success'], result
    assert result['source_sha256'] == hashlib.sha256(mesh.read_bytes()).hexdigest()
    assert set(result['renders']) == {'front_detail_head', 'back_detail_head'}
    for label, path in result['renders'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == result['render_sha256'][label]


def test_mesh_and_step_are_mutually_exclusive(tmp_path: Path):
    settings = Settings(tmp_path, Path(sys.executable), 'bambu-x2d', None, 120)
    result = generate_preview_renders(settings, {'mesh_file':'a.stl','step_file':'b.step'})
    assert result['success'] is False
    assert 'exactly one' in result['error']
