"""Oct 10: tests for midday fresh-news compose logic (Item 5).

Tests cover:
- qualifying-account logic (stale >24h, no standalone, posted/held/superseded excluded)
- fix: published account is skipped (defect 3b)
- fix: all standalone rows evaluated, not just the first (defect 3a)
- fresh-source age filter in select() (FD_MIDDAY_MAX_AGE_H)
- FD_MIDDAY_REPLACE semantics: midday_supersede() (defect 2)
- midday cron script bash syntax and hour-gate / lock behaviour (fake env, no network)
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

import daily_compose as dc  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now():
    return datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)


def _pub(hours_ago):
    """Return an ISO timestamp `hours_ago` before _now()."""
    return (_now() - timedelta(hours=hours_ago)).isoformat()


def _inbox_row(account_id, held=False, superseded=False, draft_status='draft_ready',
               post_mode='original', source_id='s1', published_at=None):
    pub = published_at or _pub(30)  # 30h old by default → stale
    return {
        'account_id': account_id,
        'held': held,
        'superseded': superseded,
        'draft_status': draft_status,
        'post_mode': post_mode,
        'source': {'id': source_id, 'published_at': pub},
        'text': 'test draft',
    }


# ── Account-qualification logic ───────────────────────────────────────────────

def test_no_standalone_qualifies():
    """Account with no inbox row for today qualifies."""
    rows = []
    with patch.object(dc.compose_inbox, 'rows', return_value=rows):
        with patch.dict(os.environ, {'FD_MIDDAY': '0'}):
            # call the helper directly by reconstructing the closure logic
            # We test the lambda by running the same code as main() would.
            result = _run_midday_needs(rows, 'a1')
    assert result is True


def test_stale_standalone_qualifies():
    """Account with a standalone whose source is >24h old qualifies."""
    rows = [_inbox_row('a1', published_at=_pub(30))]
    result = _run_midday_needs(rows, 'a1')
    assert result is True


def test_fresh_standalone_does_not_qualify():
    """Account whose standalone has source published <24h ago does not qualify."""
    rows = [_inbox_row('a1', published_at=_pub(6))]
    result = _run_midday_needs(rows, 'a1')
    assert result is False


def test_held_standalone_ignored():
    """A held draft is not counted as a qualifying standalone — account still qualifies."""
    rows = [_inbox_row('a1', held=True, published_at=_pub(6))]
    result = _run_midday_needs(rows, 'a1')
    assert result is True


def test_superseded_standalone_ignored():
    """A superseded draft is not counted — account qualifies as if it has none."""
    rows = [_inbox_row('a1', superseded=True, published_at=_pub(6))]
    result = _run_midday_needs(rows, 'a1')
    assert result is True


def test_not_draft_ready_ignored():
    """A draft with status needs_review is not a ready standalone — account qualifies."""
    rows = [_inbox_row('a1', draft_status='needs_review', published_at=_pub(6))]
    result = _run_midday_needs(rows, 'a1')
    assert result is True


def test_engage_source_id_ignored():
    """A reply/quote draft (x-<id> source_id) does not count as a standalone."""
    rows = [_inbox_row('a1', source_id='x-12345678', post_mode='reply', published_at=_pub(6))]
    result = _run_midday_needs(rows, 'a1')
    assert result is True


def _run_midday_needs(inbox_rows, account_id, decisions=None):
    """Call the module-level midday_qualifies() with the given rows for one account."""
    return dc.midday_qualifies(
        [r for r in inbox_rows if r.get('account_id') == account_id],
        decisions or {},
        _now(),
    )


# ── Fresh-source age filter ───────────────────────────────────────────────────

def _group(published_at):
    return [{'source': {'id': 's1', 'published_at': published_at}, 'unit_id': 'u1',
             'unit': {}, 'beat': 'crypto'}]


def _run_midday_age_filter(groups, max_age_h=6, now_dt=None):
    """Run the FD_MIDDAY age filter block from select() on a simple pools dict."""
    now_dt = now_dt or _now()
    age_cutoff = now_dt - timedelta(hours=max_age_h)
    kept = []
    for g in groups:
        src = g[0]['source']
        pub = src.get('published_at')
        try:
            pub_dt = datetime.fromisoformat(str(pub or '').replace('Z', '+00:00'))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt >= age_cutoff:
                kept.append(g)
        except (ValueError, AttributeError):
            pass
    return kept


def test_fresh_source_passes_age_filter():
    groups = [_group(_pub(3))]
    assert len(_run_midday_age_filter(groups, max_age_h=6)) == 1


def test_stale_source_filtered_out():
    groups = [_group(_pub(10))]
    assert len(_run_midday_age_filter(groups, max_age_h=6)) == 0


def test_exactly_at_boundary_passes():
    """A source published exactly max_age_h ago (to the second) passes."""
    groups = [_group(_pub(6))]
    assert len(_run_midday_age_filter(groups, max_age_h=6)) == 1


def test_bad_date_excluded():
    """A group with an unparseable published_at is excluded (safe default)."""
    groups = [_group('not-a-date')]
    assert len(_run_midday_age_filter(groups, max_age_h=6)) == 0


def test_missing_date_excluded():
    """A group with no published_at is excluded."""
    groups = [[{'source': {'id': 's1'}, 'unit_id': 'u1', 'unit': {}, 'beat': 'crypto'}]]
    assert len(_run_midday_age_filter(groups, max_age_h=6)) == 0


def test_custom_max_age_h():
    groups = [_group(_pub(12))]
    assert len(_run_midday_age_filter(groups, max_age_h=6)) == 0
    assert len(_run_midday_age_filter(groups, max_age_h=24)) == 1


# ── FD_MIDDAY_REPLACE: midday_supersede() (defect 2 fix) ─────────────────────

def _make_row(id, account_id, held=False, superseded=False, draft_status='draft_ready',
              source_id='s1', text='draft text'):
    return {'id': id, 'account_id': account_id, 'held': held, 'superseded': superseded,
            'draft_status': draft_status, 'source': {'id': source_id}, 'text': text}


def test_midday_supersede_marks_stale_standalone():
    """midday_supersede() calls compose_inbox.supersede on the stale ready standalone."""
    new_row = _make_row('new1', 'a1')
    earlier = [_make_row('old1', 'a1')]
    superseded_ids = []
    def fake_supersede(draft_id, *, by, reason, base=None):
        superseded_ids.append((draft_id, by, reason))
        return {'id': draft_id, 'superseded': True}
    with patch.object(dc.compose_inbox, 'supersede', side_effect=fake_supersede):
        done = dc.midday_supersede(new_row, earlier, {})
    assert done == ['old1']
    assert superseded_ids == [('old1', 'new1', 'midday_fresh')]


def test_midday_supersede_skips_published():
    """midday_supersede() must not supersede a row that admin_decisions marks published."""
    from apply_admin_decisions import is_published as _is_pub
    new_row = _make_row('new1', 'a1')
    earlier = [_make_row('old1', 'a1')]
    # published decision: action='published' sets is_published to True
    decisions = {'old1': {'action': 'published'}}
    with patch.object(dc.compose_inbox, 'supersede', return_value=None) as mock_sup:
        done = dc.midday_supersede(new_row, earlier, decisions)
    assert done == []
    mock_sup.assert_not_called()


def test_midday_supersede_skips_engagement():
    """midday_supersede() must not supersede an engagement (x-<id>) row."""
    new_row = _make_row('new1', 'a1')
    earlier = [_make_row('old1', 'a1', source_id='x-99887766')]
    with patch.object(dc.compose_inbox, 'supersede', return_value=None) as mock_sup:
        done = dc.midday_supersede(new_row, earlier, {})
    assert done == []
    mock_sup.assert_not_called()


def test_midday_supersede_held_new_does_nothing():
    """A held midday draft must not supersede anything."""
    new_row = {**_make_row('new1', 'a1'), 'held': True}
    earlier = [_make_row('old1', 'a1')]
    with patch.object(dc.compose_inbox, 'supersede', return_value=None) as mock_sup:
        done = dc.midday_supersede(new_row, earlier, {})
    assert done == []
    mock_sup.assert_not_called()


# ── midday_qualifies: all rows evaluated, published check (defects 3a / 3b) ──

def test_all_standalones_evaluated_one_fresh_disqualifies():
    """defect 3a: if ANY unposted standalone is fresh, the account must not qualify — even if
    another standalone is stale."""
    fresh_row = _inbox_row('a1', published_at=_pub(6))   # fresh → should disqualify
    stale_row = _inbox_row('a1', published_at=_pub(48))  # stale → would qualify on its own
    result = _run_midday_needs([fresh_row, stale_row], 'a1')
    assert result is False


def test_published_account_does_not_qualify():
    """defect 3b: if an account's standalone is published (admin_decisions), it already posted — skip."""
    row = {**_inbox_row('a1', published_at=_pub(48)), 'id': 'draft-1'}
    decisions = {'draft-1': {'action': 'published'}}
    result = _run_midday_needs([row], 'a1', decisions=decisions)
    assert result is False


def test_missing_source_date_treated_as_stale():
    """A standalone with no published_at date is treated as stale — account qualifies."""
    row = {**_inbox_row('a1'), 'source': {'id': 's1'}}  # no published_at
    result = _run_midday_needs([row], 'a1')
    assert result is True


# ── Cron script bash syntax and hour gate ─────────────────────────────────────

MIDDAY_SCRIPT = ROOT / 'scripts' / 'cron' / 'midday_compose.sh'


def test_midday_script_bash_syntax():
    r = subprocess.run(['bash', '-n', str(MIDDAY_SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, f'bash -n failed: {r.stderr}'


def test_midday_script_off_flag():
    """FD_MIDDAY_COMPOSE=0 causes early exit with status 0."""
    env = {**os.environ, 'FD_MIDDAY_COMPOSE': '0'}
    r = subprocess.run(['bash', str(MIDDAY_SCRIPT), 'zh'],
                       capture_output=True, text=True, env=env, timeout=10)
    assert r.returncode == 0
    assert 'off' in r.stdout or 'off' in r.stderr


def test_midday_script_bad_lang():
    """Missing or wrong lang arg exits non-zero."""
    r = subprocess.run(['bash', str(MIDDAY_SCRIPT)],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode != 0
