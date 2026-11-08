from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from vibecad_public_plugin import exports
from vibecad_public_plugin.config import Settings


def settings(root: Path, timeout: int = 5) -> Settings:
    return Settings(root, Path(sys.executable), "generic-fdm-220", None, timeout)


def metrics(**updates):
    result = {"valid_brep": True, "is_valid": True, "n_solids": 1,
              "bbox": {"size_mm": {"x": 10, "y": 10, "z": 10}, "min_mm": {"x": 0, "y": 0, "z": 0}}}
    result.update(updates)
    return result


@pytest.mark.parametrize("change", [{"valid_brep": False}, {"is_valid": False}, {"n_solids": 0},
                                   {"bbox": {"size_mm": {"x": 500, "y": 10, "z": 10}, "min_mm": {"x": 0, "y": 0, "z": 0}}}])
def test_inspect_failure_agrees_with_printer_validation(tmp_path, monkeypatch, change):
    step = tmp_path / "model.step"
    step.write_text("step")
    monkeypatch.setattr(exports, "inspect_step", lambda *args: metrics(**change))
    result = exports.inspect_metrics(settings(tmp_path), {"step_file": str(step)})
    assert result["success"] is False
    assert result["printer_validation"] == "failed"


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
@pytest.mark.parametrize("existing", [True, False])
def test_publication_rolls_back_every_failure(tmp_path, monkeypatch, fail_at, existing):
    pairs = []
    for i in range(4):
        source, target = tmp_path / f"stage{i}", tmp_path / f"final{i}"
        source.write_text(f"new{i}")
        if existing:
            target.write_text(f"old{i}")
        pairs.append((source, target))
    real_replace = os.replace
    count = 0
    def failing_replace(source, target):
        nonlocal count
        count += 1
        if count == fail_at:
            raise OSError("injected publication failure")
        real_replace(source, target)
    monkeypatch.setattr(exports.os, "replace", failing_replace)
    with pytest.raises(exports.ExportError, match="previous artifacts restored"):
        exports._publish_artifacts(pairs, tmp_path)
    for i, (_, target) in enumerate(pairs):
        assert target.read_text() == f"old{i}" if existing else not target.exists()
    assert not list(tmp_path.glob(".vibecad-backup-*"))


def test_rollback_failure_retains_backups(tmp_path, monkeypatch):
    pairs = []
    for i in range(2):
        source, target = tmp_path / f"stage{i}", tmp_path / f"final{i}"
        source.write_text("new")
        target.write_text("old")
        pairs.append((source, target))
    real_replace = os.replace
    count = 0
    def failing_replace(source, target):
        nonlocal count
        count += 1
        if count >= 2:
            raise OSError("injected")
        real_replace(source, target)
    monkeypatch.setattr(exports.os, "replace", failing_replace)
    with pytest.raises(exports.ExportError, match="rollback failed.*recovery backups retained"):
        exports._publish_artifacts(pairs, tmp_path)
    backups = list(tmp_path.glob(".vibecad-backup-*/final0"))
    assert len(backups) == 1 and backups[0].read_text() == "old"


def test_cooperating_concurrent_writers_are_serialized(tmp_path, monkeypatch):
    real_replace = os.replace
    def slow_replace(source, target):
        time.sleep(0.005)
        real_replace(source, target)
    monkeypatch.setattr(exports.os, "replace", slow_replace)
    barrier = threading.Barrier(2)
    errors = []
    def writer(revision):
        try:
            pairs = []
            for index in range(4):
                source, target = tmp_path / f"{revision}-{index}", tmp_path / f"target-{index}"
                source.write_text(revision)
                pairs.append((source, target))
            barrier.wait()
            with exports._publication_lock(tmp_path):
                exports._publish_artifacts(pairs, tmp_path)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=writer, args=(str(i),)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert len({(tmp_path / f"target-{i}").read_text() for i in range(4)}) == 1


@pytest.mark.skipif(os.name != "posix", reason="process-lock test requires POSIX")
def test_cooperating_processes_are_serialized(tmp_path):
    program = '''
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from vibecad_public_plugin import exports
root, revision = Path(sys.argv[2]), sys.argv[3]
pairs = []
for i in range(4):
    source, target = root / f"stage-{revision}-{i}", root / f"target-{i}"
    source.write_text(revision)
    pairs.append((source, target))
(root / f"ready-{revision}").touch()
while not (root / "start").exists():
    time.sleep(.005)
original = os.replace
def slow(source, target):
    time.sleep(.02)
    original(source, target)
exports.os.replace = slow
with exports._publication_lock(root):
    exports._publish_artifacts(pairs, root)
'''
    package_root = str(Path(exports.__file__).parent.parent)
    children = [subprocess.Popen([sys.executable, "-c", program, package_root, str(tmp_path), str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
    try:
        deadline = time.monotonic() + 10
        while not all((tmp_path / f"ready-{i}").exists() for i in range(2)):
            assert time.monotonic() < deadline, "writers did not become ready"
            time.sleep(.01)
        (tmp_path / "start").touch()
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0, (stdout, stderr)
        assert len({(tmp_path / f"target-{i}").read_text() for i in range(4)}) == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_execute_reports_publication_failure_and_preserves_set(tmp_path, monkeypatch):
    source = tmp_path / "demo" / "source"
    source.mkdir(parents=True)
    model = source / "model.py"
    model.write_text("pass")
    out = source.parent / "exports"
    out.mkdir()
    for ext in ("step", "stl", "3mf"):
        (out / f"model.{ext}").write_text("old")
    def fake_run(_settings, argv, *, cwd, env_updates):
        for key in ("VIBECAD_OUTPUT_STEP", "VIBECAD_STL_FILE", "VIBECAD_3MF_FILE"):
            if key in env_updates:
                Path(env_updates[key]).write_text("new")
        return subprocess.CompletedProcess(argv, 0, '{}\n', '')
    monkeypatch.setattr(exports, "run_cad", fake_run)
    monkeypatch.setattr(exports, "inspect_step", lambda *args: metrics())
    real_replace = os.replace
    failed = False
    def fail_once(source, target):
        nonlocal failed
        if str(target).endswith("model.stl") and not failed:
            failed = True
            raise OSError("injected")
        real_replace(source, target)
    monkeypatch.setattr(exports.os, "replace", fail_once)
    result = exports.execute_and_export(settings(tmp_path), {"script_path": str(model), "output_name": "model"})
    assert result["success"] is False
    assert "publication failed" in result["error"]
    assert all((out / f"model.{ext}").read_text() == "old" for ext in ("step", "stl", "3mf"))
    assert json.loads((out / ".vibecad-status.json").read_text())["success"] is False


def test_subprocess_sanitizes_environment_and_bounds_output(tmp_path, monkeypatch):
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
        monkeypatch.setenv(key, "/poison")
    code = "import os,sys,json; print('x'*2000000); print(json.dumps({k:os.environ.get(k) for k in ('PYTHONPATH','PYTHONHOME','PYTHONUSERBASE','PYTHONNOUSERSITE')})); print('y'*2000000,file=sys.stderr)"
    result = exports.run_cad(settings(tmp_path), [sys.executable, "-c", code], cwd=tmp_path)
    assert result.returncode == 0
    assert len(result.stdout) < exports.MAX_CAPTURE_BYTES + 100
    assert len(result.stderr) < exports.MAX_CAPTURE_BYTES + 100
    assert "capture truncated" in result.stdout and "capture truncated" in result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"PYTHONPATH": None, "PYTHONHOME": None, "PYTHONUSERBASE": None, "PYTHONNOUSERSITE": "1"}


def test_subprocess_timeout_reports_output(tmp_path):
    with pytest.raises(exports.ExportError, match="exceeded 1s") as exc:
        exports.run_cad(settings(tmp_path, 1), [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(10)"], cwd=tmp_path)
    assert "started" in str(exc.value)
