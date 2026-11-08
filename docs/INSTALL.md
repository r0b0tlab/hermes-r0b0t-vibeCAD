# Install

## Requirements

- Hermes Agent v0.21.0 or newer.
- Python 3.12 or 3.13 for the CAD environment (Python 3.14 is not supported by this package). Hermes may use a different Python version.
- `venv` and `pip` available for the chosen interpreter, and network access to install the CAD dependencies and build backend. `uv` is not required.
- An FDM printer profile with an accurate rectangular build volume, safe margin, nozzle diameter, layer limits, and tool count.

## Install from GitHub

```bash
git clone https://github.com/r0b0tlab/hermes-r0b0t-vibeCAD.git
mkdir -p "$HOME/.hermes/plugins"
ln -s "$(pwd)/hermes-r0b0t-vibeCAD" "$HOME/.hermes/plugins/hermes-r0b0t-vibeCAD"
hermes plugins enable hermes-r0b0t-vibeCAD
python3.12 "$HOME/.hermes/plugins/hermes-r0b0t-vibeCAD/scripts/bootstrap.py" \
  --python python3.12 --venv "$HOME/.local/share/hermes-r0b0t-vibeCAD/venv"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.python_executable' \
  "$HOME/.local/share/hermes-r0b0t-vibeCAD/venv/bin/python"
mkdir -p "$HOME/vibecad-projects"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.workspace_root' \
  "$HOME/vibecad-projects"
hermes config set 'plugins.entries.hermes-r0b0t-vibeCAD.settings.printer_profile' generic-fdm-220
```

The example uses Python 3.12; substitute `python3.13` or an absolute path to a supported interpreter as needed. Bootstrap defaults to its own interpreter if `--python` is omitted, checks its version before creating the environment, and installs using pip (without upgrading pip). It is run from a source checkout, not from an installed wheel. The example paths are POSIX; on Windows use the venv's `Scripts/python.exe`.

The wheel can also be installed into a supported Python environment with `python -m pip install '.[cad]'` from the checkout and imported as `hermes_r0b0t_vibecad`. A wheel installation alone does not register a Hermes plugin: keep the source checkout linked in the Hermes plugins directory as shown above. The wheel's source mapping copies files even for an editable install; do not rely on `pip install -e` to reflect subsequent source edits.

Use `scripts/init_printer_profile.py --output <path>` to create an editable printer profile, then set `printer_profiles_file` and `printer_profile` through `hermes config set`.

Restart the Hermes gateway or start a new Hermes session after installing or changing plugin Python code. Never hand-edit Hermes `config.yaml`.
