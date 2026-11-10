---
name: fdm-handoff
description: "Use when a vibeCAD FDM model must fit a printer and show drawings. Run the plugin tools, do not approximate them."
version: 1.0.0
---

# vibeCAD FDM handoff

The plugin tools are the gate. A prose claim that a part fits, or a guessed AMS slot, is not a result.

## Desktop drawings sidebar: tool → assistant attachment

When presenting a model in Hermes Desktop, use the vibeCAD drawings sidebar for reviewed views. Call `vibecad_generate_preview_renders` in the **same session** as the user-facing reply; use the returned `renders` map and `media` list, not guessed paths. Inspect the actual pixels first and exclude misleading or blank views. In the assistant reply, emit each selected returned `MEDIA:/absolute/path.png` on a separate line, exactly as returned, with no backticks, quotes or code fence. Include concise context unless the user explicitly asks for paths only.

The `media` array inside a tool result does not itself populate the sidebar: the assistant's standalone `MEDIA:` attachment mounts the corresponding inline tool-media card, which supplies the sidebar. A plain file path, arbitrary CAD render, or direct Python/CLI rendering fallback can appear in chat but is not equivalent to a plugin-linked tool result. Use a fresh tool call and emit its returned media after every relevant revision; keep views tied to the current source hashes and session. Never claim the sidebar populated until the user or a live UI check confirms it. If it stays empty, check that the Desktop plugin is enabled under Capabilities → Plugins, the correct session/transcript is open, and the current process has loaded the plugin; do not change the user's toggles or restart their app without permission. If the tool-call transport corrupts array arguments, omit optional `views` and inspect the default results; disclose any fallback that cannot populate the sidebar.

## Generation provider routing

- **Default to the local build123d workflow**: author trusted local parametric geometry and run the vibeCAD tools. This path does not require Meshy or an API key. A pre-existing local STL can also be inspected with the mesh workflow below; that is not a cloud generation call.
- Meshy is a **separate optional plugin**, not a replacement or automatic fallback. Use it only when the user explicitly chooses Meshy and its official plugin and API key are available. The mere presence of an API key or the Meshy plugin does not change the default. Before every paid Meshy task, state the cost and obtain the user's approval through its existing workflow; do not bypass the plugin's approval or spending guard.
- Never silently switch providers. If the local workflow cannot faithfully model a requested organic shape or image, say so and offer Meshy or a user-supplied mesh; do not describe local build123d as an image-to-3D generator. If the user chooses Meshy but it is missing, unconfigured, out of credits, declined or fails, explain the blocker and preserve the local option. Do not ask for API keys in chat or retry an uncertain paid creation.

1. `vibecad_list_printer_profiles` and use the selected id. `bambu-p2s` is the 256 × 256 × 256 mm single-nozzle P2S AMS Combo. `bambu-x2d` is the narrower dual-tool common envelope, not a synonym for P2S.
2. For trusted build123d models, after every geometry change run `vibecad_execute_and_export`. Require `success`, a valid STEP, and `printer_validation: passed` before using files. For an externally generated local STL (including Meshy output), call `vibecad_prepare_mesh` with the workspace file, desired `height_mm` and selected profile; use its new revision, not a stale source, and inspect its manifest. This checks basic topology and envelope only; it does not repair, prove printability, or produce STEP/native 3MF. Meshy is a separate optional plugin and its paid calls need their own authorization.
3. `vibecad_generate_preview_renders` for `iso`, `front`, `back`, and `top`, then actually inspect the pixels. For an STL pass `mesh_file`; for STEP pass `step_file`, never both. Emit each `media` string as its own line. On figures, additionally inspect face, both hands and contact points from relevant angles; on other parts inspect critical details and joints. Use separate region calls for each target/view. A region is `{"label":"face","x_min":0.35,"y_min":0.10,"x_max":0.65,"y_max":0.40}`: coordinates are normalized from the 800px full-frame view, including padding, top-left origin; these numbers are illustrative, not detection. `resolution` defaults to 1600 for details. Note what was visible, defects and unresolved occlusion; change the model and repeat as needed before describing quality.
   - Use Hermes's current vision route when inspecting preview pixels. The user can change the profile-wide auxiliary vision model in Desktop Settings → Models → Auxiliary models → Vision; never silently override it. A vision model cannot certify anatomy, manufacturability, or hardware behavior.
   - Record `source_sha256` (or the STEP-compatible `source_step_sha256`), each `render_sha256` and `render_metadata` with observations. Compare against the current source after changes; old images cannot review a new revision. Fresh paths and hashes are not protection against external edits.
   - Depth-tested images are visual aids only, not anatomy, dimensional, strength or printability certification. Shadows, triangulation and occlusion can conceal defects. Verify geometry and measurements separately, run printability checks as available, and inspect the actual slicer preview.
4. For STEP exports, read `fdm_warnings`. They do not fail the export. Do not call a warning a measured wall thickness. Mesh preparation does not calculate these warnings.
5. For multi-material STEP assemblies, Bambu handoff is `vibecad_stage_for_bambu` with an exact `solids_map` and one positive `bambu_slots` entry per label. For an STL revision, import the STL into the slicer and select the printer/material there; the Bambu multipart STEP adapter does not accept a mesh.
   - P2S: every `tool` is `0` or omitted. Default slots are 1–4. Pass `ams_slot_capacity` only when the user has more than one AMS unit, and never above 20.
   - X2D: tool `0` is main, tool `1` is auxiliary. Do not reuse P2S slot caps on X2D.
6. Slot numbers are not live AMS bindings. Do not dispatch a print. Do not claim `slicer-handoff.3mf` is a Bambu-native project. `bambu-assemble-list.json` is a recipe; a native archive is trustworthy only after that Studio build's `--info` succeeds, which this plugin does not run.
7. Place the bed face at Z=0. P2S usable envelope is 256 × 256 × 256 mm. A 256.1 mm axis does not fit.
