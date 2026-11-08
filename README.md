# hermes-r0b0t-vibeCAD

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that executes a trusted build123d model, refuses geometry that misses the selected FDM bed, renders preview drawings, and writes a vendor-neutral slicer handoff.

## What a skill cannot do

The tools return `success: false` for an unknown profile, a bed miss, overlapping solids, a P2S second nozzle, and a P2S slot above the AMS capacity. Those refusals are the product. A prompt can describe them. It cannot enforce them.

## Printers

- User-supplied rectangular FDM profiles.
- Bundled `generic-fdm-220`.
- Bundled `bambu-x2d`: 235.5 × 256 × 256 mm dual-tool common envelope. Not a synonym for P2S.
- Bundled `bambu-p2s`: Bambu Lab P2S AMS Combo, 256 × 256 × 256 mm, one 0.4 mm nozzle. Default AMS slots are 1–4 (one AMS 2 Pro). Pass `ams_slot_capacity` only for extra AMS units, never above 20.

The plugin does not connect to a printer.

## Desktop

After install, enable the Desktop column in Capabilities → Plugins (not Settings → Plugins), then reload desktop plugins. Preview PNGs are depth-tested. Emit each `media` line and Desktop labels the view inline. The vibeCAD pane repeats the latest sheet for this app session.

## 90-second demo

1. `vibecad_list_printer_profiles` — `bambu-p2s` is present.
2. `vibecad_execute_and_export` on `examples/model.py` with `printer_profile: bambu-p2s`. Require `printer_validation: passed`.
3. `vibecad_inspect_metrics` on the STEP.
4. `vibecad_generate_preview_renders` for `iso`, `front`, and `top`. Emit every `media` line.
5. `vibecad_stage_for_bambu` with slots 1 and 2 and `tool: 0`.
6. Call it again with slot 5 and no `ams_slot_capacity`. `success` is false. That refusal is the plugin, not the narrator.

## Not in scope

Resin/SLA, SLS, CNC, print dispatch, live AMS binding, native Bambu process projects, and automatic material assignment.

## Disclosure

Executes trusted Python inside the configured workspace. Reads and writes that workspace's `source/`, `exports/`, and `renders/`. Spawns the configured CAD interpreter as a subprocess. No network calls, no credentials, no telemetry, and no printer connection. The Desktop half only displays image files those tools already wrote.

See [docs/INSTALL.md](docs/INSTALL.md), [docs/PRINTER_PROFILES.md](docs/PRINTER_PROFILES.md), [docs/BAMBU_X2D.md](docs/BAMBU_X2D.md), and [docs/BAMBU_P2S.md](docs/BAMBU_P2S.md).
