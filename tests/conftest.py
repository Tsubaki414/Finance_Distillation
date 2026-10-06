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
