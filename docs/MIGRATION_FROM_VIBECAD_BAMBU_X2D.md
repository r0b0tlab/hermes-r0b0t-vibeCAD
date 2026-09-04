# Migration from vibecad-bambu-x2d

`hermes-r0b0t-vibeCAD` replaces the old local Bambu-only plugin with namespaced tools and a portable FDM core. The optional X2D adapter preserves the verified Bambu constraints without making them defaults for users of other printers.

| Former private tool | Replacement |
|---|---|
| `cad_execute_and_export` | `vibecad_execute_and_export` |
| `cad_inspect_metrics` | `vibecad_inspect_metrics` |
| `cad_generate_preview_renders` | `vibecad_generate_preview_renders` |
| `cad_modify_parameter` | `vibecad_modify_parameter` |
| `cad_stage_for_bambu` | `vibecad_stage_for_bambu` for X2D, or `vibecad_stage_for_slicer` for another FDM slicer |

## Local X2D configuration

```bash
hermes config set plugins.entries.hermes-r0b0t-vibeCAD.settings.workspace_root ~/3d-printing/projects
hermes config set plugins.entries.hermes-r0b0t-vibeCAD.settings.python_executable ~/hermes-r0b0t-vibeCAD/.venv/bin/python
hermes config set plugins.entries.hermes-r0b0t-vibeCAD.settings.printer_profile bambu-x2d
```

For an X2D multi-material model, call `vibecad_stage_for_bambu` with one named `solids_map` entry and one positive `bambu_slots` entry for every solid. It produces a Bambu Studio import/CLI recipe and named STL fallbacks, not a print dispatch or claimed native process project.

See [BAMBU_X2D.md](BAMBU_X2D.md) for the exact envelope, toolhead, and Bambu Studio verification boundary.
