from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_r0b0t_vibecad"


def test_wheel_installs_as_package_with_resources(tmp_path: Path) -> None:
    # Build without uv or a network connection, then install into a fresh venv.
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    subprocess.run(
        [sys.executable, "-c", "import hatchling.build, sys; hatchling.build.build_wheel(sys.argv[1])", str(wheel_dir)],
        cwd=ROOT, check=True,
    )
    (wheel,) = wheel_dir.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        files = set(archive.namelist())
    # Every root module and shipped resource must stay available under the package.
    for source in ROOT.glob("*.py"):
        assert f"{PACKAGE}/{source.name}" in files
    for directory in ("profiles", "scripts", "skills", "desktop"):
        for source in (ROOT / directory).rglob("*"):
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                assert f"{PACKAGE}/{source.relative_to(ROOT).as_posix()}" in files
    assert f"{PACKAGE}/plugin.yaml" in files
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in files)
    assert "__init__.py" not in files

    env = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(env)], check=True)
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], check=True, cwd=tmp_path)
    code = '''
from pathlib import Path
import hermes_r0b0t_vibecad as package
from hermes_r0b0t_vibecad.profiles import load_profile_catalog
from hermes_r0b0t_vibecad.scripts import bootstrap
from hermes_r0b0t_vibecad.config import Settings
from hermes_r0b0t_vibecad.exports import run_cad
import sys
root = Path(package.__file__).parent
assert root.is_relative_to(Path(__import__("sys").prefix))
assert "generic-fdm-220" in load_profile_catalog()
for item in ("profiles/bambu-adapters.json", "profiles/printer-profile.schema.json", "desktop/plugin.js", "skills/fdm-handoff/SKILL.md", "plugin.yaml"):
    assert (root / item).is_file(), item
assert callable(bootstrap.main)
settings = Settings(Path.cwd(), Path(sys.executable), "generic-fdm-220", None, 5)
completed = run_cad(settings, [sys.executable, "-c", "print('wheel-cad')"], cwd=Path.cwd())
assert completed.returncode == 0 and completed.stdout.strip() == "wheel-cad"
'''
    subprocess.run([str(python), "-I", "-c", code], check=True, cwd=tmp_path)
    subprocess.run([str(python), "-I", "-m", f"{PACKAGE}.scripts.init_printer_profile", "--help"], check=True, cwd=tmp_path)


def test_source_distribution_builds_wheel(tmp_path: Path) -> None:
    from hatchling.build import build_sdist

    source = tmp_path / "source"
    source.mkdir()
    archive_name = build_sdist(str(source))
    with tarfile.open(source / archive_name) as archive:
        archive.extractall(source, filter="data")
    (extracted,) = (path for path in source.iterdir() if path.is_dir())
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir()
    subprocess.run(
        [sys.executable, "-c", "import hatchling.build, sys; hatchling.build.build_wheel(sys.argv[1])", str(wheel_dir)],
        cwd=extracted, check=True,
    )
    (wheel,) = wheel_dir.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert f"{PACKAGE}/__init__.py" in archive.namelist()
        assert f"{PACKAGE}/profiles/builtin.json" in archive.namelist()
        assert f"{PACKAGE}/desktop/plugin.js" in archive.namelist()
