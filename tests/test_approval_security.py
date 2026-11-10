from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

from .conftest import load_plugin
from .test_plugin_registration import FakeContext
from vibecad_public_plugin import exports, runtime
from vibecad_public_plugin.config import Settings

TOOL = "vibecad_execute_and_export"


def setup_plugin(tmp_path, monkeypatch):
    ctx = FakeContext()
    settings = Settings(tmp_path, Path(sys.executable), "generic-fdm-220", None, 60)
    monkeypatch.setattr(runtime, "settings_from_context", lambda _ctx: settings)
    load_plugin().register(ctx)
    return ctx, settings


def fake_gate(monkeypatch, callback):
    parent = types.ModuleType("tools")
    parent.__path__ = []
    module = types.ModuleType("tools.approval")
    module.request_tool_approval = callback
    monkeypatch.setitem(sys.modules, "tools", parent)
    monkeypatch.setitem(sys.modules, "tools.approval", module)


def args(path):
    return {"script_path": str(path), "output_name": "model"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_hook_manifest_and_unrelated_tools(tmp_path, monkeypatch):
    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    model.write_bytes(b"print('ok')\n")
    hook = ctx.hooks["pre_tool_call"]
    directive = hook(TOOL, args(model))
    assert directive["action"] == "approve"
    assert directive["rule_key"] == "vibecad:" + digest(model.read_bytes())
    assert str(model) in directive["message"] and digest(model.read_bytes()) in directive["message"]
    assert hook("vibecad_prepare_mesh", {}) is None
    assert hook(TOOL, {})["action"] == "block"
    assert "pre_tool_call" in (Path(__file__).parents[1] / "plugin.yaml").read_text()


@pytest.mark.parametrize("decision", [None, {}, {"approved": False}, {"approved": 1}, {"approved": "true"}])
def test_denial_and_malformed_results_never_start_subprocess(tmp_path, monkeypatch, decision):
    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    model.write_text("pass")
    fake_gate(monkeypatch, lambda *a, **k: decision)
    monkeypatch.setattr(exports.subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess started"))
    assert not json.loads(ctx.tools[TOOL](args(model)))["success"]


@pytest.mark.parametrize("error", [RuntimeError("failure"), TimeoutError("timeout"), ImportError("missing")])
def test_gate_exceptions_never_start_subprocess(tmp_path, monkeypatch, error):
    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    model.write_text("pass")
    def fail(*a, **k):
        raise error
    fake_gate(monkeypatch, fail)
    monkeypatch.setattr(exports.subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess started"))
    result = json.loads(ctx.tools[TOOL](args(model)))
    assert not result["success"] and "approval unavailable" in result["error"]


def test_missing_host_api_fails_closed(tmp_path, monkeypatch):
    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    model.write_text("pass")
    parent = types.ModuleType("tools")
    parent.__path__ = []
    monkeypatch.setitem(sys.modules, "tools", parent)
    monkeypatch.setitem(sys.modules, "tools.approval", None)
    monkeypatch.setattr(exports.subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess started"))
    assert not json.loads(ctx.tools[TOOL](args(model)))["success"]


def test_snapshot_survives_mutation_and_runs_real_export(tmp_path, monkeypatch):
    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    content = (Path(__file__).parent / "fixtures" / "model.py").read_bytes()
    model.write_bytes(content)
    requests = []
    def approve(name, message, *, rule_key):
        requests.append((name, message, rule_key))
        model.write_text("raise RuntimeError('unapproved replacement')\n")
        return {"approved": True}
    fake_gate(monkeypatch, approve)
    result = json.loads(ctx.tools[TOOL](args(model)))
    assert result["success"], result
    assert requests[0][0] == TOOL and requests[0][2] == "vibecad:" + digest(content)
    assert str(model) in requests[0][1] and digest(content) in requests[0][1]
    assert "fixture exported" in result["stdout"]
    assert all(Path(result["output"][ext]).is_file() for ext in ("step", "stl", "3mf"))
    assert "unapproved replacement" in model.read_text()


def test_snapshot_runner_rejects_corrupt_pipe(tmp_path):
    settings = Settings(tmp_path, Path(sys.executable), "generic-fdm-220", None, 10)
    marker = tmp_path / "marker"
    code = f"open({str(marker)!r}, 'w').write('bad')".encode()
    result = exports.run_cad(settings, [sys.executable, "-c", exports._SNAPSHOT_RUNNER, str(tmp_path / "model.py"), digest(b"different")], cwd=tmp_path, input_bytes=code)
    assert result.returncode != 0 and "corrupted" in result.stderr
    assert not marker.exists()


def test_approved_snapshot_preserves_script_imports_and_identity(tmp_path, monkeypatch):
    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "helper.py").write_text("VALUE = 'local-import'\n")
    model = source / "model.py"
    marker = tmp_path / "identity.json"
    model.write_text(
        "import json, sys\nfrom pathlib import Path\nimport helper\n"
        "assert sys.modules['__main__'].__dict__ is globals()\n"
        f"Path({str(marker)!r}).write_text(json.dumps([__name__, __file__, sys.argv[0], helper.VALUE, sys.stdin.read()]))\n"
    )
    fake_gate(monkeypatch, lambda *a, **k: {"approved": True})
    result = json.loads(ctx.tools[TOOL](args(model)))
    assert result["return_code"] == 0  # No STEP was written; execution itself succeeded.
    assert json.loads(marker.read_text()) == ["__main__", str(model), str(model), "local-import", ""]
