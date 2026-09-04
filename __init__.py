"""Hermes plugin entry point for hermes-r0b0t-vibeCAD."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping


def _payload(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)


def register(ctx: Any) -> None:
    from . import runtime
    from .schemas import TOOL_DEFINITIONS

    for name, schema, operation_name, emoji in TOOL_DEFINITIONS:
        operation = getattr(runtime, operation_name)

        def handler(
            args: dict[str, Any],
            _operation: Callable[..., Mapping[str, Any]] = operation,
            **_kwargs: Any,
        ) -> str:
            try:
                return _payload(_operation(runtime.settings_from_context(ctx), args if isinstance(args, dict) else {}))
            except runtime.CadError as exc:
                return _payload({"success": False, "error": str(exc)})
            except Exception as exc:
                return _payload({"success": False, "error": f"vibeCAD internal error: {type(exc).__name__}: {exc}"})

        ctx.register_tool(name=name, toolset="vibecad", schema=schema, handler=handler, emoji=emoji)
