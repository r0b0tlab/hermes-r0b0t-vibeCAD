"""Public runtime facade for hermes-r0b0t-vibeCAD.

Heavy CAD imports stay in child interpreters. This module is safe to import in
Hermes' gateway interpreter on any supported platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class CadError(ValueError):
    """A user-actionable CAD workflow error."""


@dataclass(frozen=True)
class Settings:
    workspace_root: Path
    python_executable: Path | None
    printer_profile: str
    printer_profiles_file: Path | None
    timeout_s: int


def _timeout(value: Any, default: int = 120) -> int:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(300, candidate))


def settings_from_context(ctx: Any) -> Settings:
    workspace = Path(str(ctx.get_config("workspace_root", "~/vibecad-projects"))).expanduser()
    raw_python = str(ctx.get_config("python_executable", "") or "").strip()
    raw_profiles = str(ctx.get_config("printer_profiles_file", "") or "").strip()
    return Settings(
        workspace_root=workspace.resolve(strict=False),
        python_executable=Path(raw_python).expanduser().resolve(strict=False) if raw_python else None,
        printer_profile=str(ctx.get_config("printer_profile", "") or "").strip(),
        printer_profiles_file=Path(raw_profiles).expanduser().resolve(strict=False) if raw_profiles else None,
        timeout_s=_timeout(ctx.get_config("timeout_s", 120)),
    )


def _not_ready(_settings: Settings, _args: Mapping[str, Any]) -> dict[str, Any]:
    return {"success": False, "error": "vibeCAD runtime is not initialized."}


list_printer_profiles = _not_ready
execute_and_export = _not_ready
inspect_metrics = _not_ready
generate_preview_renders = _not_ready
modify_parameter = _not_ready
stage_for_slicer = _not_ready
