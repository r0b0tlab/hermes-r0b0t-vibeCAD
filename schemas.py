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
    "description": "Run a trusted workspace build123d model, export STEP/STL/generic 3MF with rollback on publication errors, and validate against a selected FDM printer profile.",
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
    "description": "Generate deterministic PNG previews from a verified STEP file without a slicer or printer dependency. Every call returns fresh unique paths in renders; use that view-to-path map rather than constructing filenames. On success, emit each string in media as its own line so Desktop and messaging can show the drawings.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path."},
            "views": {"type": "array", "items": {"type": "string", "enum": ["iso", "top", "bottom", "front", "right"]}},
            "part_colors": {"type": "array", "description": "Optional solid-color overrides in imported solid traversal order; repeated cyclically if shorter. Without overrides, use available STEP colors or neutral gray.", "items": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}},
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
                "description": "Every STEP assembly node label must uniquely identify exactly one solid, and its solid_index must match that exact imported solid; ambiguous or unlabeled nodes are refused.",
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
    "description": "Optional Bambu Studio adapter for a profile that has a bundled adapter (bambu-x2d or bambu-p2s). Writes an assembly recipe and named STL fallbacks after generic staging. Support and support_interface roles are refused because Bambu subtype conversion is unverified. It does not export a native process project, bind a live AMS, or dispatch a print. P2S is single-nozzle; slots default to 1..4 unless ams_slot_capacity is set from 1 to 20.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path."},
            "printer_profile": _PROFILE_ARG,
            "plate_name": {"type": "string", "description": "Optional Bambu Studio plate label for the generated assembly recipe."},
            "ams_slot_capacity": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Optional AMS slot ceiling. P2S Combo defaults to 4 and rejects values above 20."},
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
