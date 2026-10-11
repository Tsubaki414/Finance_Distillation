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


@pytest.fixture(autouse=True)
def legacy_compose_without_line_end(monkeypatch):
    """live/line_end.py (Oct 10) is default-on in compose; scripted compose tests pin the exact model body
    (tests/test_line_end_oct10.py turns it back on)."""
    monkeypatch.setenv('FD_LINE_END', '0')


@pytest.fixture(autouse=True)
def legacy_select_without_audit_fixes(monkeypatch, tmp_path):
    """Oct 11 account audit fixes (story dedupe / lane allowlist / post-kind mix / diary slot) are default-on in
    select() and read the real compose inbox history; scripted selection tests pin the plan from before them
    (tests/test_audit_fixes_oct11.py turns them back on)."""
    for k in ('FD_STORY_DEDUPE', 'FD_LANE_ALLOW', 'FD_POST_KIND', 'FD_DIARY_SLOT', 'FD_ARCHIVE_AUDIT_GATE'):
        monkeypatch.setenv(k, '0')
    monkeypatch.setenv('FD_STORY_STORE', str(tmp_path / 'story_labels'))
    monkeypatch.setenv('FD_STORY_LLM', '0')
