from __future__ import annotations

import json
import sys
from pathlib import Path

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.handoff import stage_for_slicer
from vibecad_public_plugin.runtime import execute_and_export


FIXTURE = Path(__file__).parent / "fixtures" / "model.py"


def settings(workspace: Path) -> Settings:
    return Settings(workspace_root=workspace, python_executable=Path(sys.executable), printer_profile="bambu-x2d", printer_profiles_file=None, timeout_s=120)


def test_stage_for_slicer_writes_generic_3mf_stls_and_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    configured = settings(workspace)
    exported = execute_and_export(configured, {"script_path": str(model), "output_name": "demo"})
    assert exported["success"] is True

    staged = stage_for_slicer(
        configured,
        {
            "step_file": exported["output"]["step"],
            "solids_map": {
                "body_01": {"solid_index": 1, "material": "PLA", "color": "#00AA00", "tool": 0, "role": "model"},
                "accent_01": {"solid_index": 2, "material": "PLA", "color": "#FFFFFF", "tool": 1, "role": "accent"},
            },
        },
    )

    assert staged["success"] is True, json.dumps(staged, indent=2, default=str)
    assert Path(staged["staged_3mf"]).is_file()
    manifest = json.loads(Path(staged["handoff_manifest"]).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["printer_profile"] == "bambu-x2d"
    assert {part["label"] for part in manifest["parts"]} == {"body_01", "accent_01"}
    assert all(Path(item["path"]).is_file() for item in staged["individual_stls"])
    serialized = json.dumps(manifest)
    for forbidden in ("target_plate", "main", "aux", "nozzle"):
        assert forbidden not in serialized


def test_stage_for_slicer_rejects_tool_outside_profile_range(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    configured = Settings(workspace_root=workspace, python_executable=Path(sys.executable), printer_profile="generic-fdm-220", printer_profiles_file=None, timeout_s=120)
    exported = execute_and_export(configured, {"script_path": str(model), "output_name": "demo"})
    assert exported["success"] is True

    result = stage_for_slicer(
        configured,
        {
            "step_file": exported["output"]["step"],
            "solids_map": {
                "body_01": {"solid_index": 1, "tool": 1},
                "accent_01": {"solid_index": 2},
            },
        },
    )

    assert result["success"] is False
    assert "tool" in result["error"]
