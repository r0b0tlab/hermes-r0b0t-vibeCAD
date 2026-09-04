# Migration from vibecad-bambu-x2d

The original private `vibecad-bambu-x2d` plugin remains independent. It is not modified or uninstalled by this plugin.

| Private tool | Public replacement |
|---|---|
| `cad_execute_and_export` | `vibecad_execute_and_export` |
| `cad_inspect_metrics` | `vibecad_inspect_metrics` |
| `cad_generate_preview_renders` | `vibecad_generate_preview_renders` |
| `cad_modify_parameter` | `vibecad_modify_parameter` |
| `cad_stage_for_bambu` | `vibecad_stage_for_slicer` |

The public plugin does not accept X2D `print_mode`, `main`/`aux` nozzle fields, or Bambu plate fields. Select a generic FDM profile and use `material`, `color`, and optional zero-based `tool` mappings instead.

Both plugins can coexist because their tools are namespaced differently.
