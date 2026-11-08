"""Exercise the documented two-part demonstration with the real CAD runner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.runtime import execute_and_export, modify_parameter, stage_for_bambu


@pytest.mark.parametrize("optional_meshy_key", [None, "dummy-not-a-real-key"])
def test_two_part_demo_export_edit_and_bambu_handoff(tmp_path: Path, monkeypatch, optional_meshy_key) -> None:
    # Installing optional Meshy credentials must not change the local CAD path.
    if optional_meshy_key is None:
        monkeypatch.delenv("MESHY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MESHY_API_KEY", optional_meshy_key)
    example = Path(__file__).resolve().parents[1] / "examples" / "two_part_demo.py"
    project = tmp_path / "demo"
    source = project / "source"
    source.mkdir(parents=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    settings = Settings(tmp_path, Path(sys.executable), "bambu-p2s", None, 120)
    edited = modify_parameter(settings, {"script_path": str(model), "param_name": "length", "new_val": 48})
    assert edited["success"], edited
    exported = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert exported["success"], exported
    assert abs(exported["metrics"]["bbox"]["size_mm"]["x"] - 48) < 0.01
    result = stage_for_bambu(settings, {
        "step_file": exported["output"]["step"],
        "solids_map": {
            "body_01": {"solid_index": 1, "material": "PLA", "color": "#0086D6", "tool": 0},
            "accent_01": {"solid_index": 2, "material": "PLA", "color": "#FFFFFF", "tool": 0},
        },
        "bambu_slots": {"body_01": 1, "accent_01": 2},
    })
    assert result["success"], result
    assert result["bambu_contract"]["machine_name"] == "Bambu Lab P2S 0.4 nozzle"
