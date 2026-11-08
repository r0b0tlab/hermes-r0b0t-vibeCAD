# Optional Bambu Studio X2D workflow

`hermes-r0b0t-vibeCAD` remains usable with any rectangular FDM printer profile. `vibecad_stage_for_bambu` dispatches on the selected profile id. `bambu-x2d` is the dual-tool adapter. `bambu-p2s` is the single-nozzle AMS Combo adapter documented in [BAMBU_P2S.md](BAMBU_P2S.md).

## What the adapter validates and creates

1. It validates slots and roles, then checks the STEP B-rep, non-overlap, exact named-node-to-solid identity, the selected profile, and the adapter's physical common dual-nozzle envelope.
2. It writes `bambu-assemble-list.json`, an X2D-aligned Bambu Studio CLI assembly recipe using the requested 1-based Bambu filament slots.
3. It writes `bambu-handoff.json` with the part-to-slot/nozzle map, geometry constraints, and manual Studio steps.

Each successful call returns paths under a new `exports/handoff-revisions/<revision>/` directory (or `build/handoff-revisions/` for build-layout projects). Previously returned paths are not overwritten. The generic manifest hashes the STEP snapshot, 3MF and each STL; the Bambu manifest hashes the generic manifest and assembly recipe. Check hashes before use, particularly if files can be edited externally. A failed call does not replace a previous revision. `support` and `support_interface` roles are refused by the Bambu adapter because their recipe subtype conversion is not verified. User profile overrides cannot enlarge the adapter's physical envelope.

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
