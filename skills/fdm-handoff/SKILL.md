---
name: fdm-handoff
description: "Use when a vibeCAD FDM model must fit a printer and show drawings. Run the plugin tools, do not approximate them."
version: 1.0.0
---

# vibeCAD FDM handoff

The plugin tools are the gate. A prose claim that a part fits, or a guessed AMS slot, is not a result.

1. `vibecad_list_printer_profiles` and use the selected id. `bambu-p2s` is the 256 × 256 × 256 mm single-nozzle P2S AMS Combo. `bambu-x2d` is the narrower dual-tool common envelope, not a synonym for P2S.
2. After every geometry change, `vibecad_execute_and_export`. Require `success`, a valid STEP, and `printer_validation: passed` before using files.
3. `vibecad_generate_preview_renders` for `iso`, `front`, and `top` at minimum. The PNGs are depth-tested drawings, not a triangle painter. Emit every string in that result's `media` array as its own line. Desktop labels them inline.
4. Read `fdm_warnings`. They do not fail the export. Do not call a warning a measured wall thickness.
5. Multi-material Bambu handoff is `vibecad_stage_for_bambu` with an exact `solids_map` and one positive `bambu_slots` entry per label.
   - P2S: every `tool` is `0` or omitted. Default slots are 1–4. Pass `ams_slot_capacity` only when the user has more than one AMS unit, and never above 20.
   - X2D: tool `0` is main, tool `1` is auxiliary. Do not reuse P2S slot caps on X2D.
6. Slot numbers are not live AMS bindings. Do not dispatch a print. Do not claim `slicer-handoff.3mf` is a Bambu-native project. `bambu-assemble-list.json` is a recipe; a native archive is trustworthy only after that Studio build's `--info` succeeds, which this plugin does not run.
7. Place the bed face at Z=0. P2S usable envelope is 256 × 256 × 256 mm. A 256.1 mm axis does not fit.
