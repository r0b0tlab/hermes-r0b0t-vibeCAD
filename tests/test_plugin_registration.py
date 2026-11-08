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
    "vibecad_prepare_mesh",
    "vibecad_stage_for_bambu",
}


class FakeContext:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}
        self.skills: dict[str, object] = {}
        self.schemas: dict[str, object] = {}

    def get_config(self, key: str, default: object = None) -> object:
        return default

    def register_tool(self, *, name: str, handler: object, schema: object, **_kwargs: object) -> None:
        self.tools[name] = handler
        self.schemas[name] = schema

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


def test_registered_preview_tool_real_detail_payload(tmp_path, monkeypatch) -> None:
    import hashlib
    import sys
    from build123d import Box, export_step
    from vibecad_public_plugin import runtime
    from vibecad_public_plugin.config import Settings

    plugin = load_plugin()
    ctx = FakeContext()
    settings = Settings(workspace_root=tmp_path, python_executable=Path(sys.executable), printer_profile="generic-fdm-220", printer_profiles_file=None, timeout_s=120)
    monkeypatch.setattr(runtime, "settings_from_context", lambda ctx: settings)
    plugin.register(ctx)
    step = tmp_path / "box.step"
    export_step(Box(10, 10, 10), step)
    region = {"label": "joint", "x_min": 0.25, "y_min": 0.25, "x_max": 0.75, "y_max": 0.75}
    schema = ctx.schemas["vibecad_generate_preview_renders"]["parameters"]["properties"]
    assert "back" in schema["views"]["items"]["enum"] and set(schema["region"]["required"]) == set(region)
    payload = json.loads(ctx.tools["vibecad_generate_preview_renders"]({"step_file": str(step), "views": ["back"], "region": region}))
    assert payload["success"], payload
    key = "back_detail_joint"
    assert payload["render_metadata"][key]["resolution"] == 1600
    assert payload["source_step_sha256"] == hashlib.sha256(step.read_bytes()).hexdigest()
    assert payload["render_sha256"][key] == hashlib.sha256(Path(payload["renders"][key]).read_bytes()).hexdigest()
    assert payload["media"] == [f"MEDIA:{payload['renders'][key]}"]
