from __future__ import annotations

import json
from pathlib import Path

from .conftest import load_plugin


EXPECTED_TOOLS = {
    "vibecad_list_printer_profiles",
    "vibecad_execute_and_export",
    "vibecad_inspect_metrics",
    "vibecad_generate_preview_renders",
    "vibecad_modify_parameter",
    "vibecad_stage_for_slicer",
    "vibecad_stage_for_bambu",
}


class FakeContext:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}
        self.skills: dict[str, object] = {}

    def get_config(self, key: str, default: object = None) -> object:
        return default

    def register_tool(self, *, name: str, handler: object, **_kwargs: object) -> None:
        self.tools[name] = handler

    def register_skill(self, name: str, path: object, **_kwargs: object) -> None:
        self.skills[name] = path


def test_registers_the_public_namespaced_toolset() -> None:
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)
    assert set(ctx.tools) == EXPECTED_TOOLS
    profile_payload = json.loads(ctx.tools["vibecad_list_printer_profiles"]({}))
    assert profile_payload["success"] is True
    assert {profile["id"] for profile in profile_payload["profiles"]} >= {"generic-fdm-220", "bambu-x2d", "bambu-p2s"}
    assert "fdm-handoff" in ctx.skills
    assert Path(str(ctx.skills["fdm-handoff"])).is_file()
