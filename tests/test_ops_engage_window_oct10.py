"""Oct 10: the dashboard slotter enforces the engagement window at the slotted time - an engagement draft goes to the
earliest slot when its target's window closes soon, and expires (out of the CSV) when even that is too late."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_ops_dashboard as ops  # noqa: E402

DAY = '2026-10-10'


def eng(close_bjt, planned_bjt='12:00', acct='a'):
    return {'id': f'{acct}-e', 'account_id': acct, 'time': f'{DAY}T{planned_bjt}:00+08:00', 'pinned': True,
            'status': 'draft_ready', 'text': 'q', 'mode': 'quote',
            'engage_close': f'{DAY}T{close_bjt}:00+08:00', 'stored': f'{DAY}T07:20:00+08:00'}


def std(acct='a'):
    return {'id': f'{acct}-s', 'account_id': acct, 'time': f'{DAY}T15:00:00+08:00', 'status': 'draft_ready',
            'text': 's', 'stored': f'{DAY}T07:20:00+08:00'}


def now(hm):
    return datetime.fromisoformat(f'{DAY}T{hm}:00+08:00')


def test_closing_window_moves_to_earliest_slot():
    out = {d['id']: d for d in ops.clamp_times([eng('10:00'), std()], DAY, now=now('08:10'))}
    t = datetime.fromisoformat(out['a-e']['time'])
    assert out['a-e']['status'] == 'draft_ready' and t.strftime('%H:%M') <= '09:40'
    assert abs((datetime.fromisoformat(out['a-s']['time']) - t).total_seconds()) >= 1800


def test_open_window_keeps_planned_slot():
    out = {d['id']: d for d in ops.clamp_times([eng('20:00', '12:00')], DAY, now=now('08:10'))}
    assert out['a-e']['time'].startswith(f'{DAY}T12:00') and out['a-e']['status'] == 'draft_ready'


def test_window_closed_by_earliest_slot_expires_and_leaves_csv():
    drafts = ops.clamp_times([eng('09:00'), std()], DAY, now=now('08:44'))
    e = next(d for d in drafts if d['id'] == 'a-e')
    assert e['status'] == 'expired' and e['note'].startswith('已过期')
    csv = ops.day_csv(drafts, {}).decode('utf-8-sig')
    assert 'q' not in [line.split(',')[2] for line in csv.splitlines()[1:]]


def test_past_day_never_expires():
    drafts = ops.clamp_times([eng('09:00')], DAY, now=datetime.fromisoformat('2026-10-11T10:00:00+08:00'))
    assert drafts[0]['status'] == 'draft_ready'
