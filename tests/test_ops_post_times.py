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


def _stored(acct, stamps, stored):
    return [dict(d, stored=ops.to_bjt(stored)) for d in _drafts(acct, stamps)]


def test_late_run_never_slots_before_the_draft_exists():
    # Oct 9: the nightly died, compose re-ran at 14:45 Beijing (07:45 London) -> slots only after 15:15, >= 30 min apart
    stamps = ['2026-10-09T03:00:00+01:00', '2026-10-09T09:10:00+01:00', '2026-10-09T20:40:00+01:00']
    out = ops.clamp_times(_stored('a', stamps, '2026-10-09T07:45:10+01:00')
                          + _stored('b', stamps[:2], '2026-10-09T07:50:00+01:00'), '2026-10-09')
    for acct, first in (('a', '15:20'), ('b', '15:20')):
        t = sorted(datetime.fromisoformat(d['time']) for d in out if d['account_id'] == acct)
        assert all(first <= x.strftime('%H:%M') <= '22:59' for x in t)
        assert all((y - x).total_seconds() >= 1800 for x, y in zip(t, t[1:]))


def test_late_fill_takes_later_slots_and_night_run_keeps_full_window():
    early = _stored('a', ['2026-10-09T09:00:00+01:00'], '2026-10-08T23:40:00+01:00')
    fill = [dict(d, id='a-fill') for d in _stored('a', ['2026-10-09T03:00:00+01:00'], '2026-10-09T13:00:00+01:00')]
    out = {d['id']: datetime.fromisoformat(d['time']) for d in ops.clamp_times(early + fill, '2026-10-09')}
    assert out['a-fill'].strftime('%H:%M') >= '20:30' and out['a-0'] < out['a-fill']
    assert out['a-0'].strftime('%H:%M') >= '08:00'


def test_not_before_rule_skips_older_days_and_can_be_turned_off(monkeypatch):
    stamps = ['2026-10-08T03:00:00+01:00', '2026-10-08T09:00:00+01:00']
    out = ops.clamp_times(_stored('a', stamps, '2026-10-08T14:00:00+01:00'), '2026-10-08')
    assert min(d['time'][11:16] for d in out) < '21:00'      # published history keeps its full-window spread
    monkeypatch.setenv('FD_POST_NOT_BEFORE', '0')
    out = ops.clamp_times(_stored('a', [s.replace('10-08', '10-09') for s in stamps], '2026-10-09T14:00:00+01:00'),
                          '2026-10-09')
    assert min(d['time'][11:16] for d in out) < '21:00'
