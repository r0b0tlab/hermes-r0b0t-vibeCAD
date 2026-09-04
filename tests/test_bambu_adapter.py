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


def _exported_step(tmp_path: Path) -> tuple[Settings, str]:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(
        workspace_root=workspace,
        python_executable=Path(sys.executable),
        printer_profile="bambu-x2d",
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
