import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from vibecad_public_plugin import exports
from vibecad_public_plugin.config import Settings


def settings(root):
    return Settings(root, Path(sys.executable), "generic-fdm-220", None, 3)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_host_without_waitid_runs_and_returns_real_status(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "waitid", raising=False)
    result = exports.run_cad(settings(tmp_path), [sys.executable, "-c", "import sys; print('cad'); sys.exit(7)"], cwd=tmp_path)
    assert (result.returncode, result.stdout.strip()) == (7, "cad")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_concurrent_global_reaper_does_not_leak_cad_descendant(tmp_path, monkeypatch):
    # Stress the actual waitpid(-1, WNOHANG) used by Kanban, while keeping the
    # competition local to this isolated interpreter's children.
    ready = tmp_path / 'ready'
    sentinel = tmp_path / 'sentinel'
    child = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(1); pathlib.Path(sys.argv[2]).touch()"
    parent = "import subprocess,sys,time,pathlib; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(.001)"
    stop = threading.Event()
    reaped = []
    def reap():
        while not stop.is_set():
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid:
                    reaped.append(pid)
            except ChildProcessError: pass
            time.sleep(.0001)
    real_select = exports._wait_readable
    def let_reaper_win(*args):
        result = real_select(*args)
        if result:
            time.sleep(.1)
        return result
    monkeypatch.setattr(exports, '_wait_readable', let_reaper_win)
    thread = threading.Thread(target=reap)
    thread.start()
    try:
        result = exports.run_cad(settings(tmp_path), [sys.executable, '-c', parent, child, str(ready), str(sentinel)], cwd=tmp_path)
        assert result.returncode == 0
        assert reaped, "the competing reaper must actually reap the supervisor"
        time.sleep(1.2)
        assert ready.exists() and not sentinel.exists()
    finally:
        stop.set()
        thread.join()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_host_crash_closes_control_pipe_and_kills_descendant(tmp_path):
    ready, sentinel = tmp_path / "ready", tmp_path / "sentinel"
    child_code = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(1.5); pathlib.Path(sys.argv[2]).touch()"
    package_root = str(Path(exports.__file__).parent.parent)
    host_code = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from vibecad_public_plugin import exports
from vibecad_public_plugin.config import Settings
root = Path(sys.argv[2])
s = Settings(root, Path(sys.executable), "generic-fdm-220", None, 20)
exports.run_cad(s, [sys.executable, "-c", sys.argv[3], sys.argv[4], sys.argv[5]], cwd=root)
'''
    host = subprocess.Popen([sys.executable, "-c", host_code, package_root, str(tmp_path), child_code, str(ready), str(sentinel)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert host.poll() is None and time.monotonic() < deadline
            time.sleep(.01)
        host.kill()
        host.wait(timeout=5)
        time.sleep(2)
        assert not sentinel.exists()
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=5)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor duplication")
def test_high_numbered_control_and_report_descriptors(tmp_path, monkeypatch):
    import fcntl
    import resource
    if resource.getrlimit(resource.RLIMIT_NOFILE)[0] < 1200:
        pytest.skip("descriptor limit too low")
    original_pipe = os.pipe
    def high_pipe():
        a, b = original_pipe()
        try:
            high_a = fcntl.fcntl(a, fcntl.F_DUPFD, 1100)
            high_b = fcntl.fcntl(b, fcntl.F_DUPFD, 1100)
            return high_a, high_b
        finally:
            os.close(a)
            os.close(b)
    monkeypatch.setattr(os, "pipe", high_pipe)
    completed = exports.run_cad(settings(tmp_path), [sys.executable, "-c", "print('high-fd')"], cwd=tmp_path)
    assert completed.returncode == 0 and completed.stdout.strip() == "high-fd"


def test_missing_executable_is_reported(tmp_path):
    with pytest.raises(exports.ExportError, match="could not start CAD subprocess"):
        exports.run_cad(settings(tmp_path), [str(tmp_path / "missing")], cwd=tmp_path)


@pytest.mark.skipif(not os.environ.get("VIBECAD_TEST_SIDECAR"), reason="set VIBECAD_TEST_SIDECAR to a CAD environment")
def test_actual_sidecar_export_from_host(tmp_path):
    sidecar = Path(os.environ["VIBECAD_TEST_SIDECAR"])
    root = tmp_path / "projects"
    source = root / "demo" / "source"
    source.mkdir(parents=True)
    model = source / "model.py"
    model.write_text((Path(__file__).parent / "fixtures" / "model.py").read_text())
    configured = Settings(root, sidecar, "generic-fdm-220", None, 120)
    result = exports.execute_and_export(configured, {"script_path": str(model), "output_name": "actual"})
    assert result["success"], result
    assert result["metrics"]["n_solids"] == 2
    assert all(Path(path).is_file() and Path(path).stat().st_size > 0 for path in result["output"].values())
