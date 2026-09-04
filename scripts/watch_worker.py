#!/usr/bin/env python3
"""Persistent, debounced profile-aware vibeCAD watcher."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from _plugin_loader import load_module


runtime = load_module("runtime")
config = load_module("config")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script_path")
    parser.add_argument("--workspace-root", default=str(Path.home() / "vibecad-projects"))
    parser.add_argument("--printer-profile", required=True)
    parser.add_argument("--printer-profiles-file", default="")
    parser.add_argument("--python", default="", help="Accepted by the launcher; the worker runs in that interpreter")
    parser.add_argument("--output-name", default="output")
    parser.add_argument("--debounce-s", type=float, default=0.05)
    parser.add_argument("--interval-s", type=float, default=0.05)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def settings(args: argparse.Namespace):
    return config.Settings(
        workspace_root=Path(args.workspace_root).expanduser().resolve(),
        python_executable=Path(sys.executable),
        printer_profile=args.printer_profile,
        printer_profiles_file=Path(args.printer_profiles_file).expanduser().resolve() if args.printer_profiles_file else None,
        timeout_s=120,
    )


def emit(current, args: argparse.Namespace, event: str, queued_at: float) -> dict:
    current["watcher"] = {
        "event": event,
        "mode": "persistent_worker",
        "debounce_ms": max(0.0, args.debounce_s) * 1000.0,
        "save_to_publish_ms": round((time.perf_counter() - queued_at) * 1000.0, 1),
    }
    print(json.dumps(current, sort_keys=True, default=str), flush=True)
    return current


def build(current_settings, args: argparse.Namespace, event: str, queued_at: float) -> dict:
    return emit(runtime.execute_and_export(current_settings, {"script_path": args.script_path, "output_name": args.output_name, "printer_profile": args.printer_profile}), args, event, queued_at)


def main() -> int:
    args = parse_args()
    current_settings = settings(args)
    if not current_settings.workspace_root.is_dir():
        raise SystemExit(f"workspace root does not exist: {current_settings.workspace_root}")
    if args.once:
        return 0 if build(current_settings, args, "once", time.perf_counter()).get("success") else 1
    raw = Path(args.script_path).expanduser()
    script = raw if raw.is_absolute() else current_settings.workspace_root / raw
    script = script.resolve()
    print(json.dumps({"watching": str(script), "output_name": args.output_name, "printer_profile": args.printer_profile}), flush=True)
    previous_mtime: int | None = None
    queued_at: float | None = None
    while True:
        try:
            mtime = script.stat().st_mtime_ns
        except FileNotFoundError:
            print(json.dumps({"success": False, "error": f"model disappeared: {script}"}), flush=True)
            time.sleep(max(0.01, args.interval_s))
            continue
        if previous_mtime is None or mtime != previous_mtime:
            previous_mtime = mtime
            queued_at = time.perf_counter()
        if queued_at is not None and time.perf_counter() - queued_at >= max(0.0, args.debounce_s):
            build(current_settings, args, "saved_revision", queued_at)
            queued_at = None
        time.sleep(max(0.01, args.interval_s))


if __name__ == "__main__":
    raise SystemExit(main())
