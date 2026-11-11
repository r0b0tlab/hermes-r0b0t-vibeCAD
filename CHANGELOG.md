# Changelog

## 0.4.1 — Hermes session discovery & Desktop CAD workstation

- Pass bundled `fdm-handoff` skill frontmatter/description and per-tool descriptions at registration so Hermes lists trigger guidance in `<available_skills>` and tool metadata surfaces; add human-readable labels to `config_schema`.
- Return `workspace` (`root`, `exists`), `selected_printer_profile`, and `cad_runtime` readiness in `vibecad_list_printer_profiles` to eliminate cold-start workspace path guessing; drop provider-fragile top-level `anyOf` from the preview schema and tolerate stringified `views` transport payloads.
- Resolve `project_root_for` across nested `exports/mesh-<uuid>` and `exports/handoff-revisions/<uuid>` paths even when `README.md` is absent; return actionable `error` strings on `inspect_metrics` fit/datum failures; clean up temporary files on `modify_parameter` I/O errors; verify CAD imports in `scripts/bootstrap.py` with sanitized `PYTHONPATH`.
- Add `left` (`-X`) orthographic previews and zero-extra-subprocess `geometry_summary` (`bbox_size_mm`, `z_min_mm`, `part_count`, `triangle_count`) to `vibecad_generate_preview_renders`.
- Upgrade `desktop/plugin.js` (strictly within `@hermes/plugin-sdk`): fuse full-frame and detail calls sharing a verified 64-hex `source_sha256` into one sheet, display Title-Block dimensions and bed-datum warnings, add `Compare prev` revision A/B toggling, `4×` zoom, `[` / `]` keyboard view navigation, `Reveal file` / `Copy SHA-256` actions, interactive drag-to-crop `Select region` → Composer prompt insertion, unmount resilience, and bounded session/candidate LRU caches.
- Run `hermes plugins validate .` alongside `hermes plugins doctor . --ci` in GitHub Actions CI.

## 0.4.0 — reliability and Desktop audit

- Keep local build123d as the default workflow; Meshy remains a separate opt-in provider with its own API key and paid-call approvals. Do not silently switch when either path is unavailable.
- Make pytest's console entry point collect consistently regardless of checkout directory name; cover both identifier and hyphenated layouts.
- Add true high-resolution front/back detail viewports and source/image hashes for close visual review; do not treat images as anatomy or printability certification.
- Accept a local single-shell STL from a generator such as the optional Meshy plugin, validate basic mesh topology and printer envelope in the CAD sidecar, and publish a uniquely hash-bound, uniformly scaled geometry revision. Preview STEP and STL with the same renderer; native slicing and Meshy API calls remain separate.
- Bind handoff labels to exact STEP solids and refuse invalid mappings, unknown support conversion, and Bambu profile overrides exceeding physical bed limits.
- Create revision-specific handoff artifacts and manifests bound to source, assembly and component hashes; fail without overwriting older ready handoffs.
- Correct Unicode parameter editing, finite fit validation, disconnected overlap measurement and output directory confinement.
- Use immutable preview paths, preserve assembly colors where available, refuse source changes during rendering, and scope the Desktop pane to the focused chat and observed result.
- Add an importable wheel, tested bootstrap, explicit external CAD-runtime declaration, two-part demo, real CAD integration tests and a JavaScript Desktop harness.
- Serialize cooperating export writers and roll back ordinary publication failures; stable-path exports remain neither reader-atomic nor crash-atomic.
- Match the Desktop pane's own preview tool when the gateway stores a deferred call under the `tool_call` bridge, so the pane recognises its own sheet instead of reporting none; a batch that ran several tools is not claimed.
- Require the same Hermes floor as the catalog entry (`>=0.21.6`), so the installed manifest and the catalog declare one compatibility floor.

## 0.3.0

- Depth-test preview drawings and color them from the part, so an iso view is the model rather than overlapping slabs.
- Desktop drawing cards read a JSON tool result, label the view, and keep the built-in player until the image URL resolves.
- A bundled-skill registration failure no longer drops the CAD tools.

## 0.2.0

- Add a Bambu Lab P2S AMS Combo adapter: 256 mm cube, one 0.4 mm nozzle, default slots 1–4, explicit capacity up to 20.
- Show preview PNGs as labeled Desktop drawings when the Desktop half is enabled.
- Warn when a solid bounding-box axis is below two nozzle diameters, without failing an export that fits the bed.

## 0.1.2 — Unreleased

- Preserve a configured virtual-environment Python shim instead of resolving it to its dependency-free base interpreter.

## 0.1.1

- Add an optional Bambu Studio X2D adapter that emits an aligned CLI/UI assembly recipe, named STL fallbacks, and explicit native-project verification boundaries.
- Preserve generic FDM tools and vendor-neutral slicer handoffs unchanged.

## 0.1.0

- Initial public release of `hermes-r0b0t-vibeCAD`.
