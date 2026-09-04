# Install

## Requirements

- Hermes Agent v0.21.0 or newer.
- Python 3.12 or 3.13 for the CAD environment.
- An FDM printer profile with an accurate rectangular build volume, safe margin, nozzle diameter, layer limits, and tool count.

## Install from GitHub

```bash
git clone https://github.com/r0b0tlab/hermes-r0b0t-vibeCAD.git
mkdir -p "$HOME/.hermes/plugins"
ln -s "$(pwd)/hermes-r0b0t-vibeCAD" "$HOME/.hermes/plugins/hermes-r0b0t-vibeCAD"
hermes plugins enable hermes-r0b0t-vibeCAD
python "$HOME/.hermes/plugins/hermes-r0b0t-vibeCAD/scripts/bootstrap.py" \
  --venv "$HOME/.local/share/hermes-r0b0t-vibeCAD/venv"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.python_executable' \
  "$HOME/.local/share/hermes-r0b0t-vibeCAD/venv/bin/python"
mkdir -p "$HOME/vibecad-projects"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.workspace_root' \
  "$HOME/vibecad-projects"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.printer_profile' generic-fdm-220
```

Use `scripts/init_printer_profile.py --output <path>` to create an editable printer profile, then set `printer_profiles_file` and `printer_profile` through `hermes config set`.

Restart the Hermes gateway or start a new Hermes session after installing or changing plugin Python code. Never hand-edit Hermes `config.yaml`.
