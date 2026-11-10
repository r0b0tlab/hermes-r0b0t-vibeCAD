"""Hermes plugin entry point for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping


def _payload(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)


_EXECUTE_TOOL = "vibecad_execute_and_export"


def _script_snapshot(settings: Any, args: Mapping[str, Any]) -> tuple[Path, bytes, str]:
    from .config import resolve_workspace_file

    path = resolve_workspace_file(args.get("script_path"), settings, suffixes={".py"})
    content = path.read_bytes()
    return path, content, hashlib.sha256(content).hexdigest()


def _approval_message(path: Path, digest: str) -> str:
    return (f"Execute trusted Python model {path} (SHA-256: {digest}). "
            "Python has host filesystem and network access; this is not a sandbox.")


def register(ctx: Any) -> None:
    from . import runtime
    from .schemas import TOOL_DEFINITIONS

    def pre_tool_call(tool_name: str, args: dict[str, Any], **_kwargs: Any) -> dict[str, str] | None:
        if tool_name != _EXECUTE_TOOL:
            return None
        try:
            path, _content, digest = _script_snapshot(runtime.settings_from_context(ctx), args)
            return {"action": "approve", "message": _approval_message(path, digest), "rule_key": f"vibecad:{digest}"}
        except Exception as exc:
            return {"action": "block", "message": f"vibeCAD cannot prepare script approval: {exc}"}

    ctx.register_hook("pre_tool_call", pre_tool_call)

    for name, schema, operation_name, emoji in TOOL_DEFINITIONS:
        operation = getattr(runtime, operation_name)

        def handler(
            args: dict[str, Any],
            _operation: Callable[..., Mapping[str, Any]] = operation,
            _name: str = name,
            **_kwargs: Any,
        ) -> str:
            try:
                settings = runtime.settings_from_context(ctx)
                args = args if isinstance(args, dict) else {}
                if _name == _EXECUTE_TOOL:
                    # This is the authority: hooks and middleware may rewrite args.
                    path, content, digest = _script_snapshot(settings, args)
                    try:
                        from tools.approval import request_tool_approval
                        decision = request_tool_approval(_EXECUTE_TOOL, _approval_message(path, digest), rule_key=f"vibecad:{digest}")
                    except Exception as exc:
                        return _payload({"success": False, "error": f"vibeCAD approval unavailable: {type(exc).__name__}: {exc}"})
                    if not isinstance(decision, dict) or decision.get("approved") is not True:
                        return _payload({"success": False, "error": "vibeCAD script approval denied or unavailable"})
                    return _payload(_operation(settings, args, _approved_script=(path, content)))
                return _payload(_operation(settings, args))
            except runtime.CadError as exc:
                return _payload({"success": False, "error": str(exc)})
            except Exception as exc:
                return _payload({"success": False, "error": f"vibeCAD internal error: {type(exc).__name__}: {exc}"})

        ctx.register_tool(name=name, toolset="vibecad", schema=schema, handler=handler, emoji=emoji)

    skill_md = Path(__file__).resolve().parent / "skills" / "fdm-handoff" / "SKILL.md"
    register_skill = getattr(ctx, "register_skill", None)
    if register_skill is not None and skill_md.is_file():
        try:
            register_skill("fdm-handoff", skill_md)
        except Exception:
            # A skill registration failure must not drop the CAD tools.
            pass
