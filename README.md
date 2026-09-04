# hermes-r0b0t-vibeCAD

A standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for profile-driven **FDM** CAD workflows. It executes trusted build123d models, validates them against a selected printer profile, renders previews, and creates vendor-neutral STEP/STL/3MF slicer handoffs.

## Scope

- Supports user-supplied FDM printer profiles.
- Produces generic artifacts; it does not send prints or claim automatic slicer material assignments.
- Does not support resin/SLA, SLS, CNC, or vendor-native project generation in v0.1.0.

See `docs/INSTALL.md` and `docs/PRINTER_PROFILES.md` after installation.
