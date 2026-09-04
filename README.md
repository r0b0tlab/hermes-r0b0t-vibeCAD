# hermes-r0b0t-vibeCAD

A standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for profile-driven **FDM** CAD workflows. It executes trusted build123d models, validates them against a selected printer profile, renders previews, and creates vendor-neutral STEP/STL/3MF slicer handoffs.

## Scope

- Supports user-supplied rectangular FDM printer profiles.
- Produces generic artifacts and never sends a print or claims automatic slicer material assignments.
- Includes an optional **Bambu Studio X2D** handoff adapter: named component STLs, an X2D-aligned `bambu-assemble-list.json`, and a reviewable manual mapping manifest.
- Does not support resin/SLA, SLS, CNC, printer dispatch, or automatic Bambu-native process-project generation.

See [docs/INSTALL.md](docs/INSTALL.md), [docs/PRINTER_PROFILES.md](docs/PRINTER_PROFILES.md), and [docs/BAMBU_X2D.md](docs/BAMBU_X2D.md) after installation.
