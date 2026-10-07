import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_ops_dashboard as ops  # noqa: E402


def _drafts(acct, stamps):
    return [{'id': f'{acct}-{i}', 'account_id': acct, 'time': ops.to_bjt(s)} for i, s in enumerate(stamps)]


def test_late_london_slots_spread_over_the_day():
    # London evening habit slots fall in the Beijing night; they used to pile up at 22:29 / 22:59
    stamps = ['2026-10-07T19:30:00+01:00', '2026-10-07T21:10:00+01:00', '2026-10-07T23:40:00+01:00']
    out = ops.clamp_times(_drafts('a', stamps) + _drafts('b', stamps), '2026-10-07')
    for acct in 'ab':
        t = sorted(datetime.fromisoformat(d['time']) for d in out if d['account_id'] == acct)
        assert all(x.strftime('%H:%M') >= '08:00' and x.strftime('%H:%M') <= '22:59' for x in t)
        assert all((y - x).total_seconds() >= 1800 for x, y in zip(t, t[1:]))
        assert t[0].hour < 13 and t[-1].hour >= 17       # one per segment of the window, not stacked at the end
    assert {d['time'] for d in out if d['account_id'] == 'a'} != {d['time'] for d in out if d['account_id'] == 'b'}


def test_shared_slot_stays_shared_and_order_kept():
    stamps = ['2026-10-07T03:00:00+01:00', '2026-10-07T03:00:00+01:00', '2026-10-07T10:00:00+01:00']
    out = {d['id']: d['time'] for d in ops.clamp_times(_drafts('a', stamps), '2026-10-07')}
    assert out['a-0'] == out['a-1'] < out['a-2']
