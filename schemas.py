"""OpenAI-function schemas for the public generic-FDM vibeCAD toolset."""

from __future__ import annotations

from typing import Any

_PROFILE_ARG: dict[str, Any] = {
    "type": "string",
    "description": "Optional FDM printer profile id. Overrides the plugin setting for this call.",
}

VIBECAD_LIST_PRINTER_PROFILES_SCHEMA: dict[str, Any] = {
    "name": "vibecad_list_printer_profiles",
    "description": "List available FDM printer profiles from bundled and configured catalogs. Does not inspect live printer hardware.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

VIBECAD_EXECUTE_AND_EXPORT_SCHEMA: dict[str, Any] = {
    "name": "vibecad_execute_and_export",
    "description": "Run a trusted workspace build123d model, atomically export STEP/STL/generic 3MF, and validate the result against a selected FDM printer profile.",
    "parameters": {
        "type": "object",
        "properties": {
            "script_path": {"type": "string", "description": "Absolute or workspace-relative trusted model.py path."},
            "output_name": {"type": "string", "description": "Artifact filename stem, without a path."},
            "printer_profile": _PROFILE_ARG,
        },
        "required": ["script_path", "output_name"],
        "additionalProperties": False,
    },
}

VIBECAD_INSPECT_METRICS_SCHEMA: dict[str, Any] = {
    "name": "vibecad_inspect_metrics",
    "description": "Inspect STEP validity, dimensions, mass properties, labeled solids, intersections, and selected FDM printer-profile fit.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path."},
            "printer_profile": _PROFILE_ARG,
        },
        "required": ["step_file"],
        "additionalProperties": False,
    },
}

VIBECAD_GENERATE_PREVIEW_RENDERS_SCHEMA: dict[str, Any] = {
    "name": "vibecad_generate_preview_renders",
    "description": "Generate deterministic PNG previews from a verified STEP file without a slicer or printer dependency.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path."},
            "views": {"type": "array", "items": {"type": "string", "enum": ["iso", "top", "bottom", "front", "right"]}},
            "part_colors": {"type": "array", "items": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}},
        },
        "required": ["step_file"],
        "additionalProperties": False,
    },
}

VIBECAD_MODIFY_PARAMETER_SCHEMA: dict[str, Any] = {
    "name": "vibecad_modify_parameter",
    "description": "AST-validate and replace one finite numeric literal in a top-level PARAMS dictionary.",
    "parameters": {
        "type": "object",
        "properties": {
            "script_path": {"type": "string", "description": "Absolute or workspace-relative trusted model.py path."},
            "param_name": {"type": "string", "description": "Existing PARAMS key."},
            "new_val": {"type": "number", "description": "Finite replacement numeric value."},
        },
        "required": ["script_path", "param_name", "new_val"],
        "additionalProperties": False,
    },
}

VIBECAD_STAGE_FOR_SLICER_SCHEMA: dict[str, Any] = {
    "name": "vibecad_stage_for_slicer",
    "description": "Create a vendor-neutral multipart 3MF, component STL fallback files, and a manual generic slicer handoff manifest for a selected FDM printer profile.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path."},
            "printer_profile": _PROFILE_ARG,
            "solids_map": {
                "type": "object",
                "description": "Every labeled STEP solid mapped exactly once to material/color/tool metadata.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "solid_index": {"type": "integer", "minimum": 1},
                        "material": {"type": "string"},
                        "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                        "tool": {"type": "integer", "minimum": 0},
                        "role": {"type": "string", "enum": ["model", "accent", "support", "support_interface"]},
                    },
                    "required": ["solid_index"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["step_file", "solids_map"],
        "additionalProperties": False,
    },
}

VIBECAD_STAGE_FOR_BAMBU_SCHEMA: dict[str, Any] = {
    "name": "vibecad_stage_for_bambu",
    "description": "Optional Bambu Studio X2D adapter. Produces an X2D-aligned CLI/UI assembly recipe and named STL fallbacks after generic staging; it does not claim a native process project or live material binding.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path."},
            "printer_profile": _PROFILE_ARG,
            "plate_name": {"type": "string", "description": "Optional Bambu Studio plate label for the generated assembly recipe."},
            "bambu_slots": {
                "type": "object",
                "description": "Every part label mapped to its positive Bambu filament slot number.",
                "additionalProperties": {"type": "integer", "minimum": 1},
            },
            "solids_map": VIBECAD_STAGE_FOR_SLICER_SCHEMA["parameters"]["properties"]["solids_map"],
        },
        "required": ["step_file", "bambu_slots", "solids_map"],
        "additionalProperties": False,
    },
}

TOOL_DEFINITIONS = (
    ("vibecad_list_printer_profiles", VIBECAD_LIST_PRINTER_PROFILES_SCHEMA, "list_printer_profiles", "🖨️"),
    ("vibecad_execute_and_export", VIBECAD_EXECUTE_AND_EXPORT_SCHEMA, "execute_and_export", "⚙️"),
    ("vibecad_inspect_metrics", VIBECAD_INSPECT_METRICS_SCHEMA, "inspect_metrics", "📐"),
    ("vibecad_generate_preview_renders", VIBECAD_GENERATE_PREVIEW_RENDERS_SCHEMA, "generate_preview_renders", "🖼️"),
    ("vibecad_modify_parameter", VIBECAD_MODIFY_PARAMETER_SCHEMA, "modify_parameter", "✏️"),
    ("vibecad_stage_for_slicer", VIBECAD_STAGE_FOR_SLICER_SCHEMA, "stage_for_slicer", "🧰"),
    ("vibecad_stage_for_bambu", VIBECAD_STAGE_FOR_BAMBU_SCHEMA, "stage_for_bambu", "🛠️"),
)
