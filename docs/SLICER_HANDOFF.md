# Generic slicer handoff

`vibecad_stage_for_slicer` emits:

- `slicer-handoff.3mf` — standard multipart geometry.
- `component-XX-<label>.stl` — one fallback mesh per named solid.
- `slicer-handoff.json` — source hash, selected printer profile, geometry metrics, material/color/tool mapping metadata, and manual steps.

The handoff does **not** create a vendor-native Cura, PrusaSlicer, OrcaSlicer, or Bambu Studio project. Material/color/tool fields are metadata for a human to review and bind after import.

1. Import the multipart 3MF, or all component STLs as one assembly.
2. Assign materials and tools according to `slicer-handoff.json`.
3. Apply your own printer/process profile.
4. Inspect all layers in slicer preview.
5. Send the print only after the preview is correct.

The plugin never sends a print.
