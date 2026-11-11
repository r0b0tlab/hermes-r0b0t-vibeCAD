from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest
from vibecad_public_plugin.scripts import bootstrap
from vibecad_public_plugin.scripts.bootstrap import venv_python_path


def test_manifest_declares_external_cad_runtime() -> None:
    # CAD runs in a user-configured sidecar, not the Hermes host interpreter.
    manifest = (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text(encoding="utf-8")
    assert "python_runtime: external" in manifest
    assert "python_dependencies:" not in manifest


def test_venv_python_path_is_portable(tmp_path: Path) -> None:
    assert venv_python_path(tmp_path / "cad", windows=False) == tmp_path / "cad" / "bin" / "python"
    assert venv_python_path(tmp_path / "cad", windows=True) == tmp_path / "cad" / "Scripts" / "python.exe"


def test_bootstrap_uses_supported_path_interpreter_without_upgrading_pip(tmp_path: Path, monkeypatch, capsys) -> None:
    creator = tmp_path / "python3.13"
    creator.touch()
    commands = []
    monkeypatch.setattr(bootstrap, "parse_args", lambda: argparse.Namespace(venv=str(tmp_path / "cad"), python="python3.13"))
    monkeypatch.setattr(bootstrap.shutil, "which", lambda requested: str(creator) if requested == "python3.13" else None)
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main() == 0
    assert commands[0][0:2] == [str(creator), "-c"]
    assert commands[1] == [str(creator), "-m", "venv", str(tmp_path / "cad")]
    assert commands[2] == [str(venv_python_path(tmp_path / "cad", windows=bootstrap.os.name == "nt")), "-m", "pip", "install", f"{bootstrap.REPO_ROOT}[cad]"]
    assert str(venv_python_path(tmp_path / "cad", windows=bootstrap.os.name == "nt")) in capsys.readouterr().out


def test_bootstrap_rejects_unsupported_python_before_creating_venv(tmp_path: Path, monkeypatch) -> None:
    creator = tmp_path / "python3.14"
    creator.touch()
    monkeypatch.setattr(bootstrap, "parse_args", lambda: argparse.Namespace(venv=str(tmp_path / "cad"), python=str(creator)))
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: str(creator))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)
    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    with pytest.raises(SystemExit, match="3.12 or 3.13"):
        bootstrap.main()
    assert len(calls) == 1
    assert not (tmp_path / "cad").exists()


def test_bootstrap_rejects_missing_interpreter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "parse_args", lambda: argparse.Namespace(venv=str(tmp_path / "cad"), python="missing-python"))
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit, match="unavailable"):
        bootstrap.main()
    assert not (tmp_path / "cad").exists()


def test_bootstrap_verifies_cad_imports_with_sanitized_env(tmp_path: Path, monkeypatch) -> None:
    creator = tmp_path / "python3.12"
    creator.touch()
    monkeypatch.setenv("PYTHONPATH", "/polluted/host/site-packages")
    monkeypatch.setattr(bootstrap, "parse_args", lambda: argparse.Namespace(venv=str(tmp_path / "cad"), python="python3.12"))
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: str(creator))
    seen = []

    def run(command, **kwargs):
        seen.append((command, kwargs.get("env")))
        if len(seen) == 4:
            return subprocess.CompletedProcess(command, 1)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    with pytest.raises(SystemExit, match="CAD dependency verification failed"):
        bootstrap.main()
    assert len(seen) == 4
    assert "import build123d" in seen[3][0][2]
    assert seen[2][1] is not None and "PYTHONPATH" not in seen[2][1]
