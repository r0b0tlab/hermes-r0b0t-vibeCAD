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
    "description": "Generate depth-tested PNG previews or detail views from a trusted STEP or STL; these do not prove printability. To show reviewed model views in the Desktop drawings sidebar, call this tool in the same session, inspect its returned images, then emit each selected returned MEDIA: string on a separate line in your assistant reply without backticks or a code fence. Use returned paths and hashes; never invent paths or claim the pane populated without confirmation.",
    "parameters": {
        "type": "object",
        "properties": {
            "step_file": {"type": "string", "description": "Absolute or workspace-relative STEP/STP file path. Supply exactly one of step_file or mesh_file."},
            "mesh_file": {"type": "string", "description": "Absolute or workspace-relative STL file path. Supply exactly one of mesh_file or step_file."},
            "views": {"type": "array", "minItems": 1, "description": "Orthographic views. Front looks from -Y with +X right; back looks from +Y with -X right. Default remains iso, top, bottom, front, right.", "items": {"type": "string", "enum": ["iso", "top", "bottom", "front", "back", "right"]}},
            "region": {
                "type": "object",
                "description": "Optional detail viewport in normalized coordinates of each selected view's ordinary 800x800 full-frame preview, including its padding: (0,0) top-left, (1,1) bottom-right. Each extent must be >=0.001; rectangular selections are centered and letterboxed. Choose one view per call when regions differ.",
                "properties": {
                    "label": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$", "description": "Human-readable region identifier, e.g. face or contact_left; appears in result labels."},
                    **{key: {"type": "number", "minimum": 0, "maximum": 1} for key in ("x_min", "y_min", "x_max", "y_max")},
                },
                "required": ["label", "x_min", "y_min", "x_max", "y_max"],
                "additionalProperties": False,
            },
            "resolution": {"type": "integer", "minimum": 800, "maximum": 2048, "description": "Square output pixels per side; default 800 for full-frame, 1600 for detail. Scene is rasterized at this resolution, not upscaled."},
            "part_colors": {"type": "array", "description": "Optional solid-color overrides in imported solid traversal order; repeated cyclically if shorter. Without overrides, use available STEP colors or neutral gray.", "items": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}},
        },
        "anyOf": [{"required": ["step_file"]}, {"required": ["mesh_file"]}],
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

VIBECAD_PREPARE_MESH_SCHEMA: dict[str, Any] = {
    "name": "vibecad_prepare_mesh",
    "description": "Validate and uniformly size a local single-shell STL (for example a Meshy export) in the configured CAD sidecar. Returns a hash-bound STL revision and manifest; not a STEP solid, slicer project, repair, anatomy review, or proof of manufacturability.",
    "parameters": {"type": "object", "properties": {
        "mesh_file": {"type": "string", "description": "Existing STL under the configured project workspace; no symlinks."},
        "height_mm": {"type": "number", "exclusiveMinimum": 0, "description": "Desired Z height in millimeters, preserving the existing pose and uniform proportions."},
        "printer_profile": _PROFILE_ARG,
    }, "required": ["mesh_file", "height_mm"], "additionalProperties": False},
}

TOOL_DEFINITIONS = (
    ("vibecad_list_printer_profiles", VIBECAD_LIST_PRINTER_PROFILES_SCHEMA, "list_printer_profiles", "🖨️"),
    ("vibecad_execute_and_export", VIBECAD_EXECUTE_AND_EXPORT_SCHEMA, "execute_and_export", "⚙️"),
    ("vibecad_inspect_metrics", VIBECAD_INSPECT_METRICS_SCHEMA, "inspect_metrics", "📐"),
    ("vibecad_generate_preview_renders", VIBECAD_GENERATE_PREVIEW_RENDERS_SCHEMA, "generate_preview_renders", "🖼️"),
    ("vibecad_modify_parameter", VIBECAD_MODIFY_PARAMETER_SCHEMA, "modify_parameter", "✏️"),
    ("vibecad_stage_for_slicer", VIBECAD_STAGE_FOR_SLICER_SCHEMA, "stage_for_slicer", "🧰"),
    ("vibecad_prepare_mesh", VIBECAD_PREPARE_MESH_SCHEMA, "prepare_mesh", "🧩"),
    ("vibecad_stage_for_bambu", VIBECAD_STAGE_FOR_BAMBU_SCHEMA, "stage_for_bambu", "🛠️"),
)
