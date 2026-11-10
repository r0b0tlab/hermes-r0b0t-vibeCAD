import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from vibecad_public_plugin import exports
from vibecad_public_plugin.config import Settings


def host_interrupt():
    try:
        return importlib.import_module("tools.interrupt")
    except ModuleNotFoundError as exc:
        if exc.name not in ("tools", "tools.interrupt"):
            raise
        pytest.skip("requires Hermes host interrupt module")


def wait_for(path, thread):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert thread.is_alive() and time.monotonic() < deadline, "CAD did not reach the gate"
        time.sleep(.01)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descendant cleanup")
def test_host_interrupt_cleans_children_and_never_publishes(tmp_path):
    interrupt = host_interrupt()
    source = tmp_path / "demo" / "source"
    source.mkdir(parents=True)
    output = source.parent / "exports"
    output.mkdir()
    for name in ("model.step", "model.stl", "model.3mf", ".vibecad-status.json"):
        (output / name).write_text("previous")
    model = source / "model.py"
    model.write_text('''\nimport os, pathlib, subprocess, sys, time\nroot = pathlib.Path(__file__).parent\nchild = "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); (p/'ready').touch();\\nwhile not (p/'release').exists(): time.sleep(.005)\\n(p/'marker').touch()"\nsubprocess.Popen([sys.executable, '-c', child, str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\nwhile not (root / 'ready').exists(): time.sleep(.005)\npathlib.Path(os.environ['VIBECAD_OUTPUT_STEP']).write_text('new')\nwhile not (root / 'release').exists(): time.sleep(.005)\n''')
    result = []
    settings = Settings(tmp_path, Path(sys.executable), "generic-fdm-220", None, 30)
    worker = threading.Thread(target=lambda: result.append(exports.execute_and_export(settings, {"script_path": str(model), "output_name": "model"})))
    worker.start()
    try:
        wait_for(source / "ready", worker)
        interrupt.set_interrupt(True, thread_id=worker.ident)
        worker.join(timeout=3)
        assert not worker.is_alive(), "cooperative cancellation did not stop CAD promptly"
        assert result and result[0]["success"] is False and "cancel" in result[0]["error"].lower()
        (source / "release").touch()
        time.sleep(.3)
        assert not (source / "marker").exists()
        for name in ("model.step", "model.stl", "model.3mf", ".vibecad-status.json"):
            assert (output / name).read_text() == "previous"
        assert not list(output.glob("*.staging.*"))
    finally:
        (source / "release").touch()
        worker.join(timeout=10)
        interrupt.set_interrupt(False, thread_id=worker.ident)


def test_preexisting_host_interrupt_does_not_spawn(tmp_path):
    interrupt = host_interrupt()
    marker = tmp_path / "spawned"
    interrupt.set_interrupt(True)
    try:
        with pytest.raises(exports.ExportError, match="cancel"):
            exports.run_cad(Settings(tmp_path, Path(sys.executable), "generic-fdm-220", None, 5),
                            [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).touch()", str(marker)], cwd=tmp_path)
        assert not marker.exists()
    finally:
        interrupt.set_interrupt(False)


def test_interrupt_before_publication_preserves_all_outputs(tmp_path, monkeypatch):
    interrupt = host_interrupt()
    source = tmp_path / "demo" / "source"
    source.mkdir(parents=True)
    model = source / "model.py"
    model.write_text("pass")
    output = source.parent / "exports"
    output.mkdir()
    for name in ("model.step", "model.stl", "model.3mf", ".vibecad-status.json"):
        (output / name).write_text("previous")
    def fake_run(_settings, argv, *, cwd, env_updates):
        for key in ("VIBECAD_OUTPUT_STEP", "VIBECAD_STL_FILE", "VIBECAD_3MF_FILE"):
            if key in env_updates:
                Path(env_updates[key]).write_text("new")
        if "VIBECAD_3MF_FILE" in env_updates:
            interrupt.set_interrupt(True)
        return subprocess.CompletedProcess(argv, 0, '{}\n', '')
    monkeypatch.setattr(exports, "run_cad", fake_run)
    monkeypatch.setattr(exports, "inspect_step", lambda *args: {"valid_brep": True, "is_valid": True, "n_solids": 1, "bbox": {"size_mm": {"x": 10, "y": 10, "z": 10}, "min_mm": {"x": 0, "y": 0, "z": 0}}})
    try:
        result = exports.execute_and_export(Settings(tmp_path, Path(sys.executable), "generic-fdm-220", None, 5), {"script_path": str(model), "output_name": "model"})
        assert result["success"] is False and "cancel" in result["error"].lower()
        for name in ("model.step", "model.stl", "model.3mf", ".vibecad-status.json"):
            assert (output / name).read_text() == "previous"
    finally:
        interrupt.set_interrupt(False)


def test_interrupt_during_publication_rolls_back(tmp_path, monkeypatch):
    interrupt = host_interrupt()
    pairs = []
    for number in range(4):
        source, target = tmp_path / f"stage{number}", tmp_path / f"target{number}"
        source.write_text("new")
        target.write_text("old")
        pairs.append((source, target))
    real_replace = os.replace
    def interrupt_after_first_replace(source, target):
        real_replace(source, target)
        if target == pairs[0][1]:
            interrupt.set_interrupt(True)
    monkeypatch.setattr(exports.os, "replace", interrupt_after_first_replace)
    try:
        with pytest.raises(exports.CadCancelled):
            exports._publish_artifacts(pairs, tmp_path)
        assert all(target.read_text() == "old" for _, target in pairs)
    finally:
        interrupt.set_interrupt(False)


def test_other_thread_interrupt_does_not_cancel_worker(tmp_path):
    interrupt = host_interrupt()
    interrupt.set_interrupt(True)
    results = []
    worker = threading.Thread(target=lambda: results.append(exports.run_cad(
        Settings(tmp_path, Path(sys.executable), "generic-fdm-220", None, 5),
        [sys.executable, "-c", "print('ok')"], cwd=tmp_path)))
    try:
        worker.start()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert results[0].stdout.strip() == "ok"
    finally:
        interrupt.set_interrupt(False)
        worker.join(timeout=10)
