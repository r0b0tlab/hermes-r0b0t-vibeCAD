# Printer profiles

`hermes-r0b0t-vibeCAD` validates FDM parts against a selected profile before it calls an artifact print-ready. A profile is declarative metadata; it does not connect to, interrogate, or control a printer.

Create a catalog:

```bash
python scripts/init_printer_profile.py --output "$HOME/.config/vibecad/printers.json"
```

Then set both values with Hermes:

```bash
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.printer_profiles_file' "$HOME/.config/vibecad/printers.json"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.printer_profile' my-printer
```

## v1 schema

```json
{
  "schema_version": 1,
  "profiles": [
    {
      "id": "my-printer",
      "display_name": "My FDM printer",
      "technology": "fdm",
      "bed": {
        "shape": "rectangular",
        "width_mm": 220.0,
        "depth_mm": 220.0,
        "height_mm": 250.0,
        "safe_margin_mm": 2.0
      },
      "nozzle_diameter_mm": 0.4,
      "min_layer_height_mm": 0.08,
      "max_layer_height_mm": 0.32,
      "tool_count": 1
    }
  ]
}
```

v1 supports rectangular FDM beds only. The plugin checks `model width + 2 × margin`, `model depth + 2 × margin`, `model height`, and the Z=0 datum. It intentionally fails if no profile is selected.
