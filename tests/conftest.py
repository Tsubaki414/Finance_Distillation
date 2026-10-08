"""Keep local draft history isolated across offline tests."""
import pytest
from live import anti_repeat


@pytest.fixture(autouse=True)
def isolated_draft_history(tmp_path, monkeypatch):
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path / 'history')
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path / 'fallback')


@pytest.fixture(autouse=True)
def reset_relay_quota_breaker():
    from live import erisedai_distillation_client as relay
    relay.reset_quota_breaker()
    yield
    relay.reset_quota_breaker()


@pytest.fixture(autouse=True)
def legacy_compose_without_hook_voice(monkeypatch):
    """live/hook_voice.py is default-on in the pipeline; the scripted legacy compose tests pin the payload / call
    sequence from before it (tests/test_hook_voice_oct8.py turns it back on)."""
    monkeypatch.setenv('FD_HOOK_VOICE', '0')
