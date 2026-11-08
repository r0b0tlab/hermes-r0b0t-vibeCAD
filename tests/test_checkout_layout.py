from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize('checkout_name', ['repo', 'repo-with-dash'])
def test_handoff_tests_collect_in_clean_checkout_with_any_directory_name(tmp_path: Path, checkout_name: str) -> None:
    source = Path(__file__).resolve().parents[1]
    checkout = tmp_path / checkout_name
    shutil.copytree(source, checkout, ignore=shutil.ignore_patterns('.git', '.venv', '.pytest_cache', '__pycache__', '*.pyc', 'result.json'))
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    pytest_executable = shutil.which('pytest', path=str(Path(sys.executable).parent))
    assert pytest_executable is not None, 'pytest executable is required'
    completed = subprocess.run(
        [pytest_executable, '-p', 'no:cacheprovider', '--collect-only', '-q', 'tests/test_handoff_integrity.py'],
        cwd=checkout, env=env, text=True, capture_output=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + '\n' + completed.stderr
    assert 'tests/test_handoff_integrity.py::test_' in completed.stdout, completed.stdout
