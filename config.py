"""Portable plugin configuration and trusted workspace resolution."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .profiles import PrinterProfile, ProfileError, resolve_printer_profile


class ConfigError(ValueError):
    """A workspace, interpreter, or printer-profile configuration error."""


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
    workspace_raw = str(ctx.get_config("workspace_root", "~/vibecad-projects") or "~/vibecad-projects")
    python_raw = str(ctx.get_config("python_executable", "") or "").strip()
    profiles_raw = str(ctx.get_config("printer_profiles_file", "") or "").strip()
    return Settings(
        workspace_root=Path(workspace_raw).expanduser().resolve(strict=False),
        python_executable=Path(python_raw).expanduser().resolve(strict=False) if python_raw else None,
        printer_profile=str(ctx.get_config("printer_profile", "") or "").strip(),
        printer_profiles_file=Path(profiles_raw).expanduser().resolve(strict=False) if profiles_raw else None,
        timeout_s=_timeout(ctx.get_config("timeout_s", 120)),
    )


def ensure_workspace(settings: Settings) -> Path:
    root = settings.workspace_root.resolve(strict=False)
    if not root.is_dir():
        raise ConfigError(
            f"vibeCAD workspace does not exist: {root}. Create it, then set "
            "plugins.entries.hermes-r0b0t-vibeCAD.settings.workspace_root."
        )
    return root


def resolve_workspace_file(
    raw_path: Any,
    settings: Settings,
    *,
    suffixes: Iterable[str] = (),
    must_exist: bool = True,
) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConfigError("a non-empty file path is required")
    root = ensure_workspace(settings)
    supplied = Path(raw_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ConfigError(f"path must remain under the vibeCAD workspace: {root}") from exc
    allowed = {suffix.lower() for suffix in suffixes}
    if allowed and candidate.suffix.lower() not in allowed:
        raise ConfigError(f"expected one of {', '.join(sorted(allowed))}, got {candidate.name!r}")
    if must_exist and (not candidate.is_file()):
        raise ConfigError(f"file does not exist: {candidate}")
    return candidate


def safe_output_stem(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("output_name is required")
    stem = Path(value.strip()).stem
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", stem):
        raise ConfigError("output_name may contain only letters, numbers, dot, underscore, and hyphen")
    return stem


def cad_python(settings: Settings) -> Path:
    executable = settings.python_executable or Path(sys.executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ConfigError(
            f"CAD Python is unavailable: {executable}. Run "
            "python scripts/bootstrap.py --venv <path> and configure python_executable."
        )
    return executable


def resolve_profile(settings: Settings, args: Mapping[str, Any]) -> PrinterProfile:
    selected = str(args.get("printer_profile") or settings.printer_profile or "").strip()
    try:
        return resolve_printer_profile(selected, settings.printer_profiles_file)
    except ProfileError as exc:
        raise ConfigError(str(exc)) from exc


def project_root_for(path: Path, workspace_root: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if parent == workspace_root:
            break
        if (parent / "README.md").is_file():
            return parent
    if path.parent.name in {"source", "exports", "build", "renders"}:
        return path.parent.parent
    return path.parent


def project_dirs(project_root: Path) -> tuple[Path, Path]:
    established = (project_root / "source").exists() or (project_root / "exports").exists()
    exports = project_root / ("exports" if established else "build")
    renders = project_root / ("renders" if established else "build")
    exports.mkdir(parents=True, exist_ok=True)
    renders.mkdir(parents=True, exist_ok=True)
    return exports, renders
