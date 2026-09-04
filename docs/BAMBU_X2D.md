# Optional Bambu Studio X2D workflow

`hermes-r0b0t-vibeCAD` remains usable with any rectangular FDM printer profile. The `bambu-x2d` profile and `vibecad_stage_for_bambu` are an optional, locally tested adapter for Bambu Studio X2D handoff.

## What the adapter validates and creates

1. It runs the generic STEP/STL/3MF staging gates first: valid B-rep, non-overlapping named solids, fit to the X2D common dual-nozzle envelope, and individual named STL fallbacks.
2. It writes `exports/bambu-assemble-list.json`, an X2D-aligned Bambu Studio CLI assembly recipe using the requested 1-based Bambu filament slots.
3. It writes `exports/bambu-handoff.json` with the part-to-slot/nozzle map, exact geometry constraints, and manual Studio steps.

It does **not** send a print, infer live AMS routes, bind a live material source, or claim that a generic 3MF carries Bambu process or nozzle assignments.

## X2D contract encoded by the adapter

| Mode | Usable envelope |
|---|---:|
| Main hotend only | 256 × 256 × 260 mm |
| Auxiliary hotend only | 235.5 × 256 × 256 mm |
| Common dual-hotend workflow | 235.5 × 256 × 256 mm |

The X2D uses a shared XY toolhead: left direct-drive main hotend and right remote-fed auxiliary hotend. They are not independently moving heads. The adapter centers a dual-tool assembly at `X=138.25`, `Y=128`, `Z=0`, respecting the common safe X range `20.5..256 mm`.

With an auxiliary-hotend assignment, keep the selected Bambu process at or below **200 mm/s** print speed and **1000 mm/s²** acceleration, then verify material and quality compatibility in the exact Studio/firmware pair.

## Bambu Studio import

1. In Bambu Studio, select all individual STL fallback files together.
2. Keep them as a multi-part object/assembly if Studio prompts.
3. Choose the X2D 0.4 mm process intended for the final slice.
4. Bind every listed Bambu slot to the actual loaded source and inspect the whole Preview before printing.

Use the named STEP assembly for fresh geometry revisions. The generic `slicer-handoff.3mf` is vendor-neutral interchange; do not treat it as a native Bambu project.

## CLI boundary

Bambu Studio’s `--load-assemble-list` accepts the generated recipe, but a native project only becomes trustworthy when paired with full, version-pinned Bambu machine/process/filament configuration and passes that Bambu Studio build’s `--info` gate. The plugin does not automatically export a native Bambu 3MF because unconfigured CLI assembly has been observed to produce an archive that fails `--info`.
