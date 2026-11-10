# hermes-r0b0t-vibeCAD

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that executes a trusted build123d model or prepares a local single-shell STL, checks the selected FDM bed, renders preview drawings, and writes slicer handoffs.

## What a skill cannot do

The tools return `success: false` for an unknown profile, a bed miss, overlapping solids, a P2S second nozzle, and a P2S slot above the AMS capacity. Those refusals are the product. A prompt can describe them. It cannot enforce them.

## Printers

- User-supplied rectangular FDM profiles.
- Bundled `generic-fdm-220`.
- Bundled `bambu-x2d`: 235.5 × 256 × 256 mm dual-tool common envelope. Not a synonym for P2S.
- Bundled `bambu-p2s`: Bambu Lab P2S AMS Combo, 256 × 256 × 256 mm, one 0.4 mm nozzle. Default AMS slots are 1–4 (one AMS 2 Pro). Pass `ams_slot_capacity` only for extra AMS units, never above 20.

The plugin does not connect to a printer.

## Desktop

After install, enable the Desktop column in Capabilities → Plugins (not Settings → Plugins), then reload desktop plugins. Preview PNGs are depth-tested. Emit each `media` line and Desktop labels the view inline. The vibeCAD pane follows the focused chat and shows views from its latest **observed** sheet, ordered by the gateway's session history. Open the transcript to mount its media cards; the pane is not a background history browser. It stays empty if it cannot verify order or identify a unique tool call; inline media still falls back to Desktop's built-in player. History is requested via the active gateway, so other connections may not be available.

Every successful preview invocation writes new `preview_<unique-id>_<view>.png` paths: use the returned `renders` map rather than deriving filenames. Previous images are not overwritten when the same STEP path changes. Uncolored parts use neutral gray; otherwise STEP assembly/instance colors are used when exposed by build123d. `part_colors` overrides those colors in imported solid traversal order. Face-specific materials, transparency and coplanar relief contrast are not guaranteed. Previews are visual aids, not geometry validation; complex rendering remains bounded by `timeout_s`.

### Visual detail review

Hermes reviews previews with the active session's vision route: a vision-capable main model may receive pixels natively; otherwise Hermes uses its configured auxiliary vision route. In Desktop, choose the profile-wide auxiliary model under **Settings → Models → Auxiliary models → Vision**. Explicit auxiliary configuration can change image routing and applies beyond vibeCAD. Visual review is not an anatomy or printability certification.

On the final trusted STEP or prepared STL, first request `views: ["iso", "front", "back", "top"]` and actually inspect the images. Front looks from −Y with +X to the right; back looks from +Y with −X to the right. View directions use model axes, not inferred anatomy. Then request targeted details appropriate to the object: for a figure inspect face, both hands and attachment/contact points from relevant front and back angles; for other objects inspect critical joints, edges, openings and contacts. If a feature is hidden or ambiguous, choose another view or inspect geometry; a view does not reveal what is occluded. Note observed defects and uncertainty before describing quality, revise the model if needed, and repeat on the new source.

Example tool input (coordinates are **illustrative**, not a detected face):

```json
{"step_file":"demo/exports/demo.step","views":["front"],"region":{"label":"face","x_min":0.35,"y_min":0.10,"x_max":0.65,"y_max":0.40},"resolution":1600}
```

The `region` is a rectangle in the selected view's normal **800 × 800 full-frame image**, including background padding: divide pixel coordinates by 800; `(0,0)` is top-left and `(1,1)` bottom-right. Each coordinate must be finite and between 0 and 1, and each extent at least 0.001. The label is 1–32 ASCII letters/digits/underscores/hyphens, starting with a letter or digit. The same rectangle is applied independently to every requested view, so use separate calls when their target locations differ. Rectangles are centered and letterboxed without distortion. `resolution` is an integer from 800 to 2048 pixels per side, defaulting to 1600 for a region or 800 for a full frame. The entire scene is depth-tested into the enlarged viewport; geometry is not cropped before occlusion. This is a fresh rasterization, not an enlarged PNG, but fixed tessellation, shading, occlusion and rendering timeout can still hide details.

The response retains `renders` and `media`, and adds `source_sha256` (`source_step_sha256` is retained for STEP compatibility), `render_sha256` (per returned label), and `render_metadata` (view, region, resolution). A detail label such as `front_detail_face` identifies both direction and selected region. The renderer reads a hash-checked temporary STEP or STL snapshot and rejects an ordinary source change during rendering. Record hashes with observations and compare the current source hash before reusing findings; unique paths prevent this tool overwriting earlier previews but do not make files immutable against outside edits. Hashes identify bytes, not quality. Rendered images cannot certify dimensions, anatomy, strength, printability, or slicer toolpaths; use geometry/measurement and printability checks and inspect the actual slice separately.

For a reproducible 500,000-triangle raster-only stress check (two views, synthetic mesh, excludes STEP import), run `python tests/benchmark_render.py`.

The JavaScript integration harness uses Node's standard library: `node --experimental-vm-modules --test tests/desktop.test.mjs`.

## Try the two-part demo

Create a project in the configured workspace, then copy the bundled example into it. The plugin deliberately refuses model paths outside that workspace:

```bash
mkdir -p "$HOME/vibecad-projects"
python scripts/new_project.py demo --workspace-root "$HOME/vibecad-projects"
cp examples/two_part_demo.py "$HOME/vibecad-projects/demo/source/model.py"
```

Set the plugin's workspace to `~/vibecad-projects` as described in [the install guide](docs/INSTALL.md), and ask Hermes:

> Use vibeCAD to export `demo/source/model.py` as `demo` for `bambu-p2s`. Show ISO, front and top previews. Stage a Bambu handoff with `body_01` on slot 1 and `accent_01` on slot 2; both use tool 0.

The example is tested against the real CAD runner and handoff. A handoff is geometry and reviewable metadata, **not** a sliced native Bambu project or a live AMS binding. In Studio, select the actual machine, process, colors and material sources; slice and inspect before printing. For a refusal demonstration, request slot 5 without increasing `ams_slot_capacity`—it must fail.

## Generation: default local, optional Meshy

The default local workflow uses trusted build123d scripts and works without Meshy, an API key or a cloud service. The user can also supply a local STL. The local CAD tools are not an image-to-3D generator; if a requested organic shape cannot be modeled faithfully, say so rather than silently changing providers or inventing a result. Meshy is an **optional separate Hermes plugin**, used only when the user explicitly chooses it, its key is configured and the user approves any paid operations. Having the Meshy plugin or key installed does not change vibeCAD's default. If Meshy is unavailable, fails or approval is declined, report that and preserve the local workflow.

## Meshy and other generated meshes

Meshy runs as a separate, optional Hermes plugin and handles its own account, credit approvals and image-to-3D generation; vibeCAD does not bundle Meshy or call its API. Download a single-color **STL** into a project's `source/`, then call `vibecad_prepare_mesh` with `mesh_file`, `height_mm` and `printer_profile`. The CAD sidecar checks finite triangles, watertightness, winding, one connected shell, positive volume and profile envelope, and writes a hash-bound STL revision and manifest without modifying the source. Use `vibecad_generate_preview_renders` with `mesh_file` to inspect full front/back/iso views and magnified regions from that exact STL. Results do not prove anatomy, thin features, self-intersection absence, supports, adhesion or slicer settings; review them visually, slice and inspect in the actual slicer before printing. Meshes are not converted into editable STEP or sent through the multipart Bambu adapter.

## Not in scope

Resin/SLA, SLS, CNC, print dispatch, live AMS binding, native Bambu process projects, and automatic material assignment.

## Disclosure

The agent's `vibecad_execute_and_export` requires Hermes approval for the resolved script path and SHA-256. A pre-tool hook requests approval early; the handler independently approves the final script after argument rewrites, and executes the exact bytes it read for that approval. Selecting **once** can therefore prompt twice; session/always approval uses the same content key and normally suppresses the second prompt if the bytes have not changed. An approval failure, denial, timeout or unavailable host approval API prevents execution. Hermes approval configuration (including explicit automatic approval modes) still applies.

This binds only the top-level script bytes, not imported modules, data files, interpreter, working directory or subsequent filesystem changes. Approved Python is **not sandboxed**: it can read or write outside the workspace, access credentials on disk, and use the network. The plugin does not itself initiate network calls, telemetry or printer connections; model code can. The subprocess environment is minimized, not a security boundary. Direct Python calls to `runtime.execute_and_export` are a separate trusted-caller API and do not invoke the agent approval gate. The approved agent snapshot is supplied on stdin (which is then at EOF). The Desktop half only displays image files those tools already wrote.

Export publication serializes cooperating writers and rolls back ordinary publication failures, retaining recovery backups if rollback itself fails. Existing STEP/STL/3MF paths are unchanged. They are replaced individually, so unlocked readers can observe a mixed set during publication; a process or machine crash can also interrupt the set. This is not a crash-atomic or reader-atomic transaction. The status file reports the latest completed attempt, including failures; it is not a versioned snapshot. CAD subprocesses ignore inherited Python path/home/user-site settings, and captured output is capped.

On POSIX, a separate supervisor starts a live session/group anchor that runs CAD and kills its own group on exit, timeout, cancellation, or host control-pipe closure. The host never signals a numeric group ID, and a host-wide `waitpid(-1)` reaper cannot reap the anchor. The supervisor reports CAD status only after it observes the anchor's SIGKILL. This works without `os.waitid`; no ctypes or sidecar-interpreter fallback is needed. Windows cleanup remains direct-child only. This is not a sandbox: descendants can escape the group or change credentials; external termination/failure of the supervisor or anchor, uninterruptible tasks, OS failure, or hostile model code can defeat cleanup. Never run untrusted CAD code.

See [docs/INSTALL.md](docs/INSTALL.md), [docs/PRINTER_PROFILES.md](docs/PRINTER_PROFILES.md), [docs/BAMBU_X2D.md](docs/BAMBU_X2D.md), and [docs/BAMBU_P2S.md](docs/BAMBU_P2S.md).
