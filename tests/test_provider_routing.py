from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_workflow_is_default_and_meshy_is_explicitly_optional():
    skill = (ROOT / 'skills/fdm-handoff/SKILL.md').read_text(encoding='utf-8')
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    manifest = (ROOT / 'plugin.yaml').read_text(encoding='utf-8')
    assert 'Default to the local build123d workflow' in skill
    assert 'Never silently switch' in skill
    assert 'separate optional plugin' in skill
    assert 'paid' in skill and 'approval' in skill
    assert 'default local' in readme.lower()
    assert 'MESHY_API_KEY' not in manifest
