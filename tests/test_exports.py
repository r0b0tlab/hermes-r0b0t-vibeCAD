from __future__ import annotations

import json
import sys
from pathlib import Path

from vibecad_public_plugin.config import Settings
from vibecad_public_plugin.runtime import execute_and_export, inspect_metrics


FIXTURE = Path(__file__).parent / "fixtures" / "model.py"


def make_settings(workspace: Path) -> Settings:
    return Settings(
        workspace_root=workspace,
        python_executable=Path(sys.executable),
        printer_profile="generic-fdm-220",
        printer_profiles_file=None,
        timeout_s=120,
    )


def test_execute_export_inspect_and_preserve_last_good_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    project = workspace / "demo"
    source = project / "source"
    source.mkdir(parents=True)
    (project / "README.md").write_text("# demo\n", encoding="utf-8")
    model = source / "model.py"
    model.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    settings = make_settings(workspace)

    first = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert first["success"] is True, json.dumps(first, indent=2, default=str)
    assert first["printer_validation"] == "passed"
    assert first["metrics"]["n_solids"] == 2
    for path in first["output"].values():
        assert Path(path).is_file() and Path(path).stat().st_size > 0

    inspected = inspect_metrics(settings, {"step_file": first["output"]["step"]})
    assert inspected["success"] is True
    assert inspected["bed_fit"]["profile_id"] == "generic-fdm-220"

    step = Path(first["output"]["step"])
    baseline = step.read_bytes()
    model.write_text("this is not Python\n", encoding="utf-8")
    failed = execute_and_export(settings, {"script_path": str(model), "output_name": "demo"})
    assert failed["success"] is False
    assert step.read_bytes() == baseline
