"""AST-safe targeted edits for top-level model PARAMS dictionaries."""

from __future__ import annotations

import ast
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .config import ConfigError, Settings, resolve_workspace_file


def _params_assignment(tree: ast.Module) -> ast.Dict:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PARAMS" for target in node.targets):
            if isinstance(node.value, ast.Dict):
                return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "PARAMS" and isinstance(node.value, ast.Dict):
            return node.value
    raise ConfigError("model must define a top-level PARAMS dictionary literal")


def _literal(node: ast.AST) -> float | int:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise ConfigError("PARAMS values must be finite numeric literals for AST-safe editing") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ConfigError("PARAMS values must be finite numeric literals for AST-safe editing")
    return value


def _offset(lines: list[str], lineno: int, column: int) -> int:
    return sum(len(item) for item in lines[: lineno - 1]) + column


def modify_parameter(settings: Settings, args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        script = resolve_workspace_file(args.get("script_path"), settings, suffixes={".py"})
        name = str(args.get("param_name") or "").strip()
        if not name.isidentifier():
            raise ConfigError("param_name must be a valid PARAMS key")
        raw_value = args.get("new_val")
        if isinstance(raw_value, bool):
            raise ConfigError("new_val must be a finite number")
        new_value = float(raw_value)
        if not math.isfinite(new_value):
            raise ConfigError("new_val must be a finite number")
        source = script.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(script))
        params = _params_assignment(tree)
        target: ast.AST | None = None
        for key, value in zip(params.keys, params.values):
            if isinstance(key, ast.Constant) and key.value == name:
                target = value
                break
        if target is None:
            raise ConfigError(f"PARAMS has no key {name!r}")
        old_value = _literal(target)
        lines = source.splitlines(keepends=True)
        start = _offset(lines, target.lineno, target.col_offset)
        end = _offset(lines, target.end_lineno, target.end_col_offset)
        updated = source[:start] + repr(new_value) + source[end:]
        ast.parse(updated, filename=str(script))
        temporary = script.with_name(f".{script.name}.{os.getpid()}.tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, script)
        return {"success": True, "script_path": str(script), "param_name": name, "old_value": old_value, "new_value": new_value, "changed_bytes": [start, end], "next_step": "Run vibecad_execute_and_export before relying on this edit."}
    except (ConfigError, SyntaxError, TypeError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
