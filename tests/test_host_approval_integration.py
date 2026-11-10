"""Optional integration with a real Hermes checkout (set VIBECAD_HERMES_HOST)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_approval_security import TOOL, args, setup_plugin


@pytest.mark.parametrize("allow_final", [False, True])
def test_host_hook_modify_and_execution_middleware_rewrite(tmp_path, monkeypatch, allow_final):
    host = os.environ.get("VIBECAD_HERMES_HOST")
    if not host:
        pytest.skip("set VIBECAD_HERMES_HOST and put its dependencies on PYTHONPATH")
    monkeypatch.syspath_prepend(host)
    from hermes_cli import lifecycle, middleware, plugins
    from tools import approval

    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    original = tmp_path / "original.py"
    rewritten = tmp_path / "middleware.py"
    final = tmp_path / "hook_modified.py"
    original.write_text("raise RuntimeError('original should not run')\n")
    rewritten.write_text("raise RuntimeError('middleware path should not run')\n")
    good = (Path(__file__).parent / "fixtures" / "model.py").read_bytes()
    final.write_bytes(good)
    good_hash = hashlib.sha256(good).hexdigest()
    middleware_hash = hashlib.sha256(rewritten.read_bytes()).hexdigest()
    seen = []

    def ask(name, message, *, rule_key, **_kwargs):
        seen.append((name, message, rule_key))
        return {"approved": rule_key != f"vibecad:{good_hash}" or allow_final}

    monkeypatch.setattr(approval, "request_tool_approval", ask)
    # The real host aggregates all pre-hook directives; competing hook changes the
    # path after this plugin has requested approval for the middleware path.
    def invoke_hook(name, **kwargs):
        assert name == "pre_tool_call"
        return [ctx.hooks[name](**kwargs), {"action": "modify", "args": {"script_path": str(final)}}]
    monkeypatch.setattr(lifecycle, "invoke_hook", invoke_hook)

    def rewrite(*, args, next_call, **_kwargs):
        return next_call({**args, "script_path": str(rewritten)})
    manager = SimpleNamespace(_middleware={"tool_execution": [rewrite]})
    monkeypatch.setattr(plugins, "_delivery_manager", lambda: manager)

    def dispatch(effective):
        block, modified = plugins._dispatch_pre_tool_call_hooks(TOOL, effective)
        assert block is None
        return ctx.tools[TOOL](modified if modified is not None else effective)

    result = json.loads(middleware.run_tool_execution_middleware(TOOL, args(original), dispatch))
    assert [entry[2] for entry in seen] == [f"vibecad:{middleware_hash}", f"vibecad:{good_hash}"]
    assert str(rewritten) in seen[0][1] and str(final) in seen[1][1]
    if allow_final:
        assert result["success"], result
        assert "fixture exported" in result["stdout"]
    else:
        assert not result["success"]
        assert not (tmp_path / "build").exists()


@pytest.mark.parametrize("choice,prompts", [("once", 2), ("session", 1), ("timeout", 1)])
def test_real_host_approval_once_session_and_timeout(tmp_path, monkeypatch, choice, prompts):
    host = os.environ.get("VIBECAD_HERMES_HOST")
    if not host:
        pytest.skip("set VIBECAD_HERMES_HOST and put its dependencies on PYTHONPATH")
    monkeypatch.syspath_prepend(host)
    from hermes_cli import lifecycle, plugins
    from tools import approval, approval_context

    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    marker = tmp_path / "executed"
    model.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
    calls = []
    approved = set()
    monkeypatch.setattr(approval, "_yolo_active", lambda: False)
    monkeypatch.setattr(approval_context, "_get_approval_mode", lambda: "manual")
    monkeypatch.setattr(approval, "get_current_session_key", lambda: "test-session")
    monkeypatch.setattr(approval, "is_approved", lambda _session, key: key in approved)
    monkeypatch.setattr(approval, "approve_session", lambda _session, key: approved.add(key))
    monkeypatch.setattr(approval, "_presence", lambda callback: (None, True, False, False))
    def prompt(*_args, **_kwargs):
        calls.append(choice)
        return choice
    monkeypatch.setattr(approval, "prompt_dangerous_approval", prompt)
    def invoke_hook(name, **kwargs):
        return [ctx.hooks[name](**kwargs)] if name == "pre_tool_call" else []
    monkeypatch.setattr(lifecycle, "invoke_hook", invoke_hook)
    block, modified = plugins._dispatch_pre_tool_call_hooks(TOOL, args(model))
    if block is None:
        result = json.loads(ctx.tools[TOOL](modified or args(model)))
        assert result["return_code"] == 0 and marker.read_text() == "executed"
    else:
        assert choice == "timeout" and not marker.exists()
    assert len(calls) == prompts


def test_host_hook_dispatch_exception_still_denied_by_handler(tmp_path, monkeypatch):
    host = os.environ.get("VIBECAD_HERMES_HOST")
    if not host:
        pytest.skip("set VIBECAD_HERMES_HOST and put its dependencies on PYTHONPATH")
    monkeypatch.syspath_prepend(host)
    from agent.tool_executor import _ToolCallRef, _pre_tool_block
    from hermes_cli import plugins
    from tools import approval
    from vibecad_public_plugin import exports

    ctx, _ = setup_plugin(tmp_path, monkeypatch)
    model = tmp_path / "model.py"
    model.write_text("pass")
    invoked = []
    def broken(*_args, **_kwargs):
        invoked.append(True)
        raise RuntimeError("host hook dispatcher failed")
    monkeypatch.setattr(plugins, "_dispatch_pre_tool_call_hooks", broken)
    monkeypatch.setattr(approval, "request_tool_approval", lambda *a, **k: {"approved": False})
    monkeypatch.setattr(exports.subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess started"))
    ref = _ToolCallRef(TOOL, args(model), "", "", [])
    block, final = _pre_tool_block(SimpleNamespace(), ref)
    assert invoked == [True]
    assert block is None  # Host's outer exception handler fails open.
    assert not json.loads(ctx.tools[TOOL](final))["success"]
