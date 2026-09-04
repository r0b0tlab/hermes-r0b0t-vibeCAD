from __future__ import annotations

from .conftest import load_plugin


EXPECTED_TOOLS = {
    "vibecad_list_printer_profiles",
    "vibecad_execute_and_export",
    "vibecad_inspect_metrics",
    "vibecad_generate_preview_renders",
    "vibecad_modify_parameter",
    "vibecad_stage_for_slicer",
}


class FakeContext:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def get_config(self, key: str, default: object = None) -> object:
        return default

    def register_tool(self, *, name: str, handler: object, **_kwargs: object) -> None:
        self.tools[name] = handler


def test_registers_the_public_namespaced_toolset() -> None:
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)
    assert set(ctx.tools) == EXPECTED_TOOLS
