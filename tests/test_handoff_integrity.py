from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from vibecad_public_plugin.bambu import stage_for_bambu
from vibecad_public_plugin.handoff import stage_for_slicer
from tests.test_bambu_adapter import _exported_step, _solids_map


@pytest.mark.parametrize("stage", [stage_for_slicer, stage_for_bambu])
def test_revision_parent_symlink_cannot_escape_workspace(tmp_path, stage):
    settings, step = _exported_step(tmp_path)
    outside = tmp_path / "outside-workspace"
    outside.mkdir()
    revision_parent = Path(step).parent / "handoff-revisions"
    try:
        revision_parent.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    result = stage(settings, args(step))
    assert result["success"] is False, result
    assert not list(outside.iterdir())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def args(step):
    return {"step_file": step, "solids_map": _solids_map(), "bambu_slots": {"body_01": 1, "accent_01": 2}}


@pytest.mark.parametrize("value", [True, False, 1.9, 1.0, "1"])
def test_index_and_slots_require_exact_integers(value):
    from vibecad_public_plugin.bambu import BambuError, _slots
    from vibecad_public_plugin.handoff import HandoffError, _normalize_map
    with pytest.raises(BambuError, match="integer"):
        _slots({"body": value}, {"body"})
    with pytest.raises(HandoffError, match="integer"):
        _normalize_map({"body": {"solid_index": value}}, solids=1, tool_count=1)
    assert _slots({"body": 1}, {"body"}) == {"body": 1}
    assert _normalize_map({"body": {"solid_index": 1}}, solids=1, tool_count=1)[0]["solid_index"] == 1


def test_swapped_indexes_are_rejected(tmp_path):
    settings, step = _exported_step(tmp_path)
    request = args(step)
    request["solids_map"]["body_01"]["solid_index"] = 2
    request["solids_map"]["accent_01"]["solid_index"] = 1
    result = stage_for_slicer(settings, request)
    assert not result["success"], result
    assert "identity" in result["error"].lower()


def test_assembly_product_name_is_not_a_solid_identity(tmp_path):
    settings, step = _exported_step(tmp_path)
    request = args(step)
    request["solids_map"]["generic_fixture"] = request["solids_map"].pop("body_01")
    result = stage_for_slicer(settings, request)
    assert not result["success"], result
    assert "identity" in result["error"].lower()


@pytest.mark.parametrize("role", ["support", "support_interface"])
def test_bambu_refuses_unverified_support_roles(tmp_path, role):
    settings, step = _exported_step(tmp_path)
    request = args(step)
    request["solids_map"]["accent_01"]["role"] = role
    result = stage_for_bambu(settings, request)
    assert not result["success"], result
    assert "support" in result["error"].lower()


def test_failed_bambu_request_preserves_previous_artifacts(tmp_path):
    settings, step = _exported_step(tmp_path)
    request = args(step)
    first = stage_for_bambu(settings, request)
    assert first["success"], first
    paths = [first["staged_3mf"], first["handoff_manifest"], first["bambu_handoff_manifest"], first["bambu_assemble_list"], *(x["path"] for x in first["individual_stls"])]
    before = {p: digest(p) for p in paths}
    request["solids_map"]["body_01"]["color"] = "#FF0000"
    request["bambu_slots"].pop("accent_01")
    result = stage_for_bambu(settings, request)
    assert not result["success"]
    assert {p: digest(p) for p in paths} == before


def test_revision_hashes_and_independent_successive_stages(tmp_path):
    settings, step = _exported_step(tmp_path)
    request = args(step)
    first = stage_for_bambu(settings, request)
    assert first["success"], first
    manifest = json.loads(Path(first["bambu_handoff_manifest"]).read_text())
    generic = json.loads(Path(first["handoff_manifest"]).read_text())
    assert generic["source_step_sha256"] == digest(generic["source_step_snapshot"])
    assert generic["staged_3mf_sha256"] == digest(first["staged_3mf"])
    assert all(x["sha256"] == digest(x["path"]) for x in generic["individual_stls"])
    assert manifest["generic_handoff_sha256"] == digest(first["handoff_manifest"])
    assert manifest["bambu_assemble_list_sha256"] == digest(first["bambu_assemble_list"])
    old = {p: digest(p) for p in [first["staged_3mf"], first["handoff_manifest"], first["bambu_handoff_manifest"], first["bambu_assemble_list"], *(x["path"] for x in first["individual_stls"])]}
    request["solids_map"]["body_01"]["color"] = "#FF0000"
    second = stage_for_bambu(settings, request)
    assert second["success"], second
    assert second["bambu_handoff_manifest"] != first["bambu_handoff_manifest"]
    assert {p: digest(p) for p in old} == old


def test_publication_error_preserves_old_revision(tmp_path, monkeypatch):
    import vibecad_public_plugin.bambu as bambu
    settings, step = _exported_step(tmp_path)
    first = stage_for_bambu(settings, args(step))
    assert first["success"], first
    old = digest(first["bambu_handoff_manifest"])
    revision_root = Path(first["bambu_handoff_manifest"]).parent.parent
    revisions_before = {p.name for p in revision_root.iterdir()}
    original = bambu.atomic_json
    def failing(path, value):
        if path.name == "bambu-handoff.json":
            raise OSError("injected publication failure")
        return original(path, value)
    monkeypatch.setattr(bambu, "atomic_json", failing)
    result = stage_for_bambu(settings, args(step))
    assert not result["success"]
    assert digest(first["bambu_handoff_manifest"]) == old
    assert {p.name for p in revision_root.iterdir()} == revisions_before


def test_generic_publication_error_preserves_previous_revision(tmp_path, monkeypatch):
    import vibecad_public_plugin.handoff as handoff
    settings, step = _exported_step(tmp_path)
    first = stage_for_slicer(settings, args(step))
    assert first["success"], first
    manifest = Path(first["handoff_manifest"])
    before = digest(manifest)
    revisions_before = {p.name for p in manifest.parent.parent.iterdir()}
    def failing(path, value):
        raise OSError("injected generic publication failure")
    monkeypatch.setattr(handoff, "atomic_json", failing)
    result = stage_for_slicer(settings, args(step))
    assert not result["success"]
    assert digest(manifest) == before
    assert {p.name for p in manifest.parent.parent.iterdir()} == revisions_before


def test_revision_collision_does_not_delete_previous_revision(tmp_path, monkeypatch):
    import vibecad_public_plugin.handoff as handoff
    from types import SimpleNamespace
    settings, step = _exported_step(tmp_path)
    first = stage_for_bambu(settings, args(step))
    assert first["success"], first
    manifest = Path(first["bambu_handoff_manifest"])
    old = digest(manifest)
    monkeypatch.setattr(handoff.uuid, "uuid4", lambda: SimpleNamespace(hex=manifest.parent.name))
    result = stage_for_bambu(settings, args(step))
    assert not result["success"]
    assert digest(manifest) == old


def test_source_mutation_during_staging_is_refused(tmp_path, monkeypatch):
    import vibecad_public_plugin.handoff as handoff
    settings, step = _exported_step(tmp_path)
    first = stage_for_bambu(settings, args(step))
    assert first["success"], first
    old = digest(first["bambu_handoff_manifest"])
    original = handoff.run_cad
    def changing(settings, argv, **kwargs):
        completed = original(settings, argv, **kwargs)
        if handoff.STAGE_PROGRAM in argv:
            with Path(step).open("ab") as file:
                file.write(b"\n/* changed */\n")
        return completed
    monkeypatch.setattr(handoff, "run_cad", changing)
    result = stage_for_bambu(settings, args(step))
    assert not result["success"] and "changed" in result["error"]
    assert digest(first["bambu_handoff_manifest"]) == old
    saved = json.loads(Path(first["bambu_handoff_manifest"]).read_text())
    assert digest(saved["source_step_snapshot"]) == saved["source_step_sha256"]
    assert digest(step) != saved["source_step_sha256"]


def test_custom_p2s_profile_cannot_enlarge_adapter_envelope(tmp_path):
    settings, step = _exported_step(tmp_path, "bambu-p2s")
    profile = json.loads((Path(__file__).parents[1] / "profiles" / "builtin.json").read_text())["profiles"][2]
    profile["bed"]["width_mm"] = 500
    profile["bed"]["depth_mm"] = 500
    profile["bed"]["height_mm"] = 500
    catalog = tmp_path / "profiles.json"
    catalog.write_text(json.dumps({"schema_version": 1, "profiles": [profile]}))
    settings = replace(settings, printer_profiles_file=catalog)
    # Real, valid 300 mm STEP, exported by the CAD interpreter.
    import subprocess, sys
    subprocess.run([sys.executable, "-c", "from build123d import *; import sys; s=Box(300,10,10,align=(Align.CENTER,Align.CENTER,Align.MIN)); s.label='body_01'; export_step(Compound(children=[s],label='assembly'),sys.argv[1])", step], check=True)
    request = {"step_file": step, "solids_map": {"body_01": {"solid_index": 1}}, "bambu_slots": {"body_01": 1}}
    result = stage_for_bambu(settings, request)
    assert not result["success"], result
    assert "fit" in result["error"].lower() or "envelope" in result["error"].lower()
