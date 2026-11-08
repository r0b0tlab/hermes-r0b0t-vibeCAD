# Generic slicer handoff

`vibecad_stage_for_slicer` emits:

- `slicer-handoff.3mf` — standard multipart geometry.
- `component-XX-<label>.stl` — one fallback mesh per named solid.
- `slicer-handoff.json` — source hash, selected printer profile, geometry metrics, material/color/tool mapping metadata, and manual steps.
- `source.step` — snapshot of the exact STEP used for the geometry checks and meshes.

Each successful call returns a new `exports/handoff-revisions/<revision>/` directory (or `build/handoff-revisions/` for build-layout projects); use the returned paths rather than fixed filenames. Older revisions are not overwritten. The manifest records SHA-256 for the snapshot, 3MF and every STL: verify these before use if files may have been modified. Its original `source_step` path is provenance and can later change; the snapshot is the revision's source of truth. Each supplied label must uniquely identify one STEP assembly node containing exactly one solid, and its index must match that exact imported topology. Ambiguous or absent node labels are refused.

The handoff does **not** create a vendor-native Cura, PrusaSlicer, OrcaSlicer, or Bambu Studio project. Material/color/tool fields are metadata for a human to review and bind after import.

1. Import the multipart 3MF, or all component STLs as one assembly.
2. Assign materials and tools according to `slicer-handoff.json`.
3. Apply your own printer/process profile.
4. Inspect all layers in slicer preview.
5. Send the print only after the preview is correct.

The plugin never sends a print.
