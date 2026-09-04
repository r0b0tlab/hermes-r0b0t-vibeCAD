from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
WATCHER = REPO / "scripts" / "watch_project.py"
FIXTURE = REPO / "tests" / "fixtures" / "model.py"


def test_watcher_once_publishes_generic_profile_validated_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    source = workspace / "demo" / "source"
    source.mkdir(parents=True)
    (source.parent / "README.md").write_text("# demo\n", encoding="utf-8")
    (source / "model.py").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(WATCHER),
            "demo/source/model.py",
            "--workspace-root",
            str(workspace),
            "--printer-profile",
            "generic-fdm-220",
            "--output-name",
            "watch",
            "--once",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    events = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert events[-1]["success"] is True
    assert (workspace / "demo" / "exports" / "watch.step").is_file()
