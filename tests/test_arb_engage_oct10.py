"""Oct 10: reply / quote drafts are exempt from cross-account claim arbitration (FD_ARB_ENGAGE=1 restores)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

import daily_compose as dc  # noqa: E402


def _res(i, mode=None, **kw):
    plan = {'engagement': {'mode': mode}} if mode else {}
    return dict({'id': f'r{i}', 'account_id': f'a{i}', 'draft_status': 'draft_ready', 'plan': plan, 'text': 'x'}, **kw)


def _row(i, mode=None, **kw):
    return dict({'id': f'i{i}', 'account_id': f'b{i}', 'text': 'x', 'draft_status': 'draft_ready', 'run_id': 'old',
                 'post_mode': mode or 'original'}, **kw)


def test_engagement_exempt_by_default():
    ok = [_res(1), _res(2, 'reply'), _res(3, 'quote'), _res(4, draft_status='needs_review')]
    rows = [_row(1), _row(2, 'reply'), _row(3, held=True), _row(4, run_id='now')]
    eligible, locked = dc.arbitration_pool(ok, rows, 'now', env={})
    assert [r['id'] for r in eligible] == ['r1']
    assert [x['id'] for x in locked] == ['i1']


def test_env_restores_old_pool():
    ok = [_res(1), _res(2, 'reply')]
    rows = [_row(1), _row(2, 'quote')]
    eligible, locked = dc.arbitration_pool(ok, rows, 'now', env={'FD_ARB_ENGAGE': '1'})
    assert [r['id'] for r in eligible] == ['r1', 'r2']
    assert [x['id'] for x in locked] == ['i1', 'i2']


def test_is_engagement_inbox_engagement_block():
    assert dc.is_engagement({'engagement': {'mode': 'reply'}})
    assert not dc.is_engagement({'post_mode': 'original', 'engagement': None})
