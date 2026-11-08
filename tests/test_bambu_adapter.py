from __future__ import annotations

import json
import sys
from pathlib import Path

from vibecad_public_plugin.bambu import (
    BAMBU_X2D_AUXILIARY_LIMITS,
    BAMBU_X2D_COMMON_DUAL_VOLUME_MM,
    stage_for_bambu,
)
from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.runtime import execute_and_export


FIXTURE = Path(__file__).parent / "fixtures" / "model.py"


def _exported_step(tmp_path: Path, printer_profile: str = "bambu-x2d") -> tuple[Settings, str]:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(
        workspace_root=workspace,
        python_executable=Path(sys.executable),
        printer_profile=printer_profile,
        printer_profiles_file=None,
        timeout_s=120,
    )
    exported = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert exported["success"] is True
    return settings, exported["output"]["step"]


def _solids_map() -> dict[str, dict[str, object]]:
    return {
        "body_01": {"solid_index": 1, "material": "PLA", "color": "#00AA00", "tool": 0},
        "accent_01": {"solid_index": 2, "material": "PLA", "color": "#FFFFFF", "tool": 1},
    }


def test_stage_for_bambu_writes_x2d_safe_manual_handoff(tmp_path: Path) -> None:
    settings, step_file = _exported_step(tmp_path)

    staged = stage_for_bambu(
        settings,
        {
            "step_file": step_file,
            "plate_name": "test X2D assembly",
            "bambu_slots": {"body_01": 3, "accent_01": 4},
            "solids_map": _solids_map(),
        },
    )

    assert staged["success"] is True, json.dumps(staged, indent=2, default=str)
    assert staged["status"] == "ready_for_manual_bambu_import"
    assert "bambu_project" not in staged
    assemble = json.loads(Path(staged["bambu_assemble_list"]).read_text(encoding="utf-8"))
    assert assemble["plates"][0]["plate_name"] == "test X2D assembly"
    assert {entry["filaments"][0] for entry in assemble["plates"][0]["objects"]} == {3, 4}
    assert {tuple(entry["pos_x"] + entry["pos_y"] + entry["pos_z"]) for entry in assemble["plates"][0]["objects"]} == {(138.25, 128.0, 0.0)}

    manifest = json.loads(Path(staged["bambu_handoff_manifest"]).read_text(encoding="utf-8"))
    assert manifest["x2d_contract"]["common_dual_or_auxiliary_build_volume_mm"] == list(BAMBU_X2D_COMMON_DUAL_VOLUME_MM)
    assert manifest["x2d_contract"]["auxiliary_hotend_limits"] == BAMBU_X2D_AUXILIARY_LIMITS
    assert {part["requested_nozzle"] for part in manifest["parts"]} == {"main", "auxiliary"}
    assert any("not auto-export" in item for item in manifest["limitations"])


def test_stage_for_bambu_requires_a_slot_for_every_part(tmp_path: Path) -> None:
    settings, step_file = _exported_step(tmp_path)
    result = stage_for_bambu(settings, {"step_file": step_file, "bambu_slots": {"body_01": 3}, "solids_map": _solids_map()})
    assert result["success"] is False
    assert "accent_01" in result["error"]


def test_stage_for_p2s_centers_on_128_and_rejects_second_nozzle(tmp_path: Path) -> None:
    settings, step_file = _exported_step(tmp_path, printer_profile="bambu-p2s")
    solids = {
        "body_01": {"solid_index": 1, "material": "PLA", "color": "#00AA00", "tool": 0},
        "accent_01": {"solid_index": 2, "material": "PLA", "color": "#FFFFFF", "tool": 0},
    }
    staged = stage_for_bambu(
        settings,
        {
            "step_file": step_file,
            "plate_name": "P2S combo",
            "bambu_slots": {"body_01": 1, "accent_01": 2},
            "solids_map": solids,
        },
    )
    assert staged["success"] is True, staged
    assemble = json.loads(Path(staged["bambu_assemble_list"]).read_text(encoding="utf-8"))
    assert {tuple(entry["pos_x"] + entry["pos_y"] + entry["pos_z"]) for entry in assemble["plates"][0]["objects"]} == {(128.0, 128.0, 0.0)}
    manifest = json.loads(Path(staged["bambu_handoff_manifest"]).read_text(encoding="utf-8"))
    assert manifest["bambu_contract"]["machine_name"] == "Bambu Lab P2S 0.4 nozzle"
    assert manifest["bambu_contract"]["slot_capacity"] == 4
    import hashlib
    assert manifest["generic_handoff_sha256"] == hashlib.sha256(Path(staged["handoff_manifest"]).read_bytes()).hexdigest()
    assert manifest["bambu_assemble_list_sha256"] == hashlib.sha256(Path(staged["bambu_assemble_list"]).read_bytes()).hexdigest()
    assert "x2d_contract" not in manifest
    assert "auxiliary hotend" not in " ".join(manifest["manual_bambu_steps"]).lower()
    assert any("not auto-export" in item for item in manifest["limitations"])

    denied = stage_for_bambu(
        settings,
        {
            "step_file": step_file,
            "bambu_slots": {"body_01": 1, "accent_01": 2},
            "solids_map": {
                "body_01": {"solid_index": 1, "tool": 0},
                "accent_01": {"solid_index": 2, "tool": 1},
            },
        },
    )
    assert denied["success"] is False
    assert "one nozzle" in denied["error"]


def test_p2s_slot_5_needs_an_explicit_capacity_and_21_is_rejected(tmp_path: Path) -> None:
    settings, step_file = _exported_step(tmp_path, printer_profile="bambu-p2s")
    solids = {
        "body_01": {"solid_index": 1, "tool": 0},
        "accent_01": {"solid_index": 2, "tool": 0},
    }
    over = stage_for_bambu(
        settings,
        {"step_file": step_file, "bambu_slots": {"body_01": 1, "accent_01": 5}, "solids_map": solids},
    )
    assert over["success"] is False
    assert "4" in over["error"]

    raised = stage_for_bambu(
        settings,
        {
            "step_file": step_file,
            "ams_slot_capacity": 8,
            "bambu_slots": {"body_01": 1, "accent_01": 5},
            "solids_map": solids,
        },
    )
    assert raised["success"] is True, raised
    assert json.loads(Path(raised["bambu_handoff_manifest"]).read_text(encoding="utf-8"))["bambu_contract"]["slot_capacity"] == 8

    absurd = stage_for_bambu(
        settings,
        {
            "step_file": step_file,
            "ams_slot_capacity": 21,
            "bambu_slots": {"body_01": 1, "accent_01": 2},
            "solids_map": solids,
        },
    )
    assert absurd["success"] is False
    assert "20" in absurd["error"]


def test_generic_profile_is_not_a_bambu_adapter(tmp_path: Path) -> None:
    settings, step_file = _exported_step(tmp_path, printer_profile="generic-fdm-220")
    result = stage_for_bambu(
        settings,
        {
            "step_file": step_file,
            "bambu_slots": {"body_01": 1, "accent_01": 2},
            "solids_map": _solids_map(),
        },
    )
    assert result["success"] is False
    assert "bambu-p2s" in result["error"]
    assert "bambu-x2d" in result["error"]
