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

## Not in scope

Resin/SLA, SLS, CNC, print dispatch, live AMS binding, native Bambu process projects, and automatic material assignment.

## Disclosure

Executes trusted Python inside the configured workspace. Reads and writes that workspace's `source/`, `exports/`, and `renders/`. Spawns the configured CAD interpreter as a subprocess. No network calls, no credentials, no telemetry, and no printer connection. The Desktop half only displays image files those tools already wrote.

Export publication serializes cooperating writers and rolls back ordinary publication failures, retaining recovery backups if rollback itself fails. Existing STEP/STL/3MF paths are unchanged. They are replaced individually, so unlocked readers can observe a mixed set during publication; a process or machine crash can also interrupt the set. This is not a crash-atomic or reader-atomic transaction. The status file reports the latest completed attempt, including failures; it is not a versioned snapshot. CAD subprocesses ignore inherited Python path/home/user-site settings, and captured output is capped.

See [docs/INSTALL.md](docs/INSTALL.md), [docs/PRINTER_PROFILES.md](docs/PRINTER_PROFILES.md), [docs/BAMBU_X2D.md](docs/BAMBU_X2D.md), and [docs/BAMBU_P2S.md](docs/BAMBU_P2S.md).
