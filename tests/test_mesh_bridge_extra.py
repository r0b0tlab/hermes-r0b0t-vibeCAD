from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import trimesh

from vibecad_public_plugin import mesh_bridge


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / 'workspace'
    project = root / 'demo'
    (project / 'source').mkdir(parents=True)
    source = project / 'source' / 'input.stl'
    return root, project, source


def do_import(fixture, **kwargs):
    root, project, source = fixture
    return mesh_bridge.import_stl(workspace_root=root, project_root=project, source_path=source,
                                  axis='z', dimension_mm=30, envelope_mm=(100, 100, 100), **kwargs)


def test_ascii_input_negative_source_origin_is_bed_placed(fixture):
    root, project, source = fixture
    mesh = trimesh.creation.box(extents=(2, 3, 4))
    mesh.apply_translation([-100, 42, -19])
    source.write_text(mesh.export(file_type='stl_ascii'))
    result = do_import(fixture)
    out = trimesh.load(result['stl_path'], force='mesh')
    assert out.bounds[0] == pytest.approx([0, 0, 0])
    assert out.extents == pytest.approx([15, 22.5, 30])
    data = json.loads(Path(result['manifest_path']).read_text())
    assert not data['scope']['self_intersections_checked']
    assert not data['scope']['manufacturability_checked']
    assert not data['scope']['native_project']


def test_collision_does_not_overwrite_revision(fixture, monkeypatch):
    root, project, source = fixture
    source.write_bytes(trimesh.creation.box().export(file_type='stl'))
    monkeypatch.setattr(mesh_bridge.uuid, 'uuid4', lambda: SimpleNamespace(hex='fixed'))
    result = do_import(fixture)
    paths = [Path(result['stl_path']), Path(result['manifest_path'])]
    before = [p.read_bytes() for p in paths]
    with pytest.raises(FileExistsError):
        do_import(fixture)
    assert [p.read_bytes() for p in paths] == before


def test_publication_failure_removes_only_new_revision(fixture, monkeypatch):
    root, project, source = fixture
    source.write_bytes(trimesh.creation.box().export(file_type='stl'))
    good = do_import(fixture)
    before = Path(good['manifest_path']).read_bytes()
    def fail(*args, **kwargs):
        raise OSError('disk error')
    monkeypatch.setattr(mesh_bridge.json, 'dump', fail)
    with pytest.raises(OSError, match='disk error'):
        do_import(fixture)
    assert Path(good['manifest_path']).read_bytes() == before
    assert len(list((project / 'exports').iterdir())) == 1


def test_symlink_to_internal_project_is_also_rejected(fixture):
    root, project, source = fixture
    source.write_bytes(trimesh.creation.box().export(file_type='stl'))
    alias = root / 'alias'
    alias.symlink_to(project, target_is_directory=True)
    with pytest.raises(mesh_bridge.MeshImportError, match='symlink'):
        mesh_bridge.import_stl(workspace_root=root, project_root=alias,
                               source_path=source, dimension_mm=30, envelope_mm=(100, 100, 100))
