from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
NEW_PROJECT = REPO / "scripts" / "new_project.py"
INIT_PROFILE = REPO / "scripts" / "init_printer_profile.py"


def test_new_project_uses_generic_layout_and_language(tmp_path: Path) -> None:
    workspace = tmp_path / "projects"
    workspace.mkdir()
    completed = subprocess.run([sys.executable, str(NEW_PROJECT), "demo", "--workspace-root", str(workspace)], capture_output=True, text=True, check=True)
    project = Path(completed.stdout.strip())
    assert project == workspace / "demo"
    assert (project / "source" / "model.py").is_file()
    assert (project / "exports").is_dir()
    assert (project / "renders").is_dir()
    readme = (project / "README.md").read_text(encoding="utf-8")
    assert "FDM" in readme
    assert "Bambu" not in readme


def test_init_printer_profile_copies_a_valid_editable_template(tmp_path: Path) -> None:
    output = tmp_path / "my-printer.json"
    subprocess.run([sys.executable, str(INIT_PROFILE), "--output", str(output)], capture_output=True, text=True, check=True)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["profiles"][0]["id"] == "my-printer"
