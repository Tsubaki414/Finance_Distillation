"""Oct 9 afternoon: a late build (Beijing evening) used to crash clamp_times ("3 slots do not fit 08:00-22:59 at
30-minute spacing"). Now the drafts that fit keep the last valid slots; the rest go to 明天 with a note."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_ops_dashboard as ops  # noqa: E402

STAMPS = ['2026-10-09T03:00:00+01:00', '2026-10-09T09:10:00+01:00', '2026-10-09T20:40:00+01:00']


def _drafts(acct, n=3, stored='2026-10-09T07:45:00+01:00'):
    return [{'id': f'{acct}-{i}', 'account_id': acct, 'time': ops.to_bjt(s), 'stored': ops.to_bjt(stored)}
            for i, s in enumerate(STAMPS[:n])]


def _late(now_bjt):
    return datetime.fromisoformat(f'2026-10-09T{now_bjt}:00+08:00')


def test_late_build_never_crashes_and_overflows_to_tomorrow(capsys):
    out = ops.clamp_times(_drafts('a') + _drafts('b', 1), '2026-10-09', now=_late('21:50'))
    a = sorted((d for d in out if d['account_id'] == 'a'), key=lambda d: d['time'])
    today = [d for d in a if not d.get('overflow')]
    over = [d for d in a if d.get('overflow')]
    assert len(today) == 2 and len(over) == 1          # lo = 21:50 + 30 min lead = 22:20: 22:29 and 22:59 fit
    t = [datetime.fromisoformat(d['time']) for d in today]
    assert [x.strftime('%H:%M') for x in t] == ['22:29', '22:59']
    assert all(d['time'].startswith('2026-10-10T08') for d in over)
    assert all(d['note'].startswith('明天') for d in over)
    b = [d for d in out if d['account_id'] == 'b']
    assert len(b) == 1 and not b[0].get('overflow') and b[0]['time'].startswith('2026-10-09T22')
    assert 'moved to 明天' in capsys.readouterr().err


def test_two_of_three_fit_at_2130():
    out = ops.clamp_times(_drafts('a'), '2026-10-09', now=_late('21:50'))
    today = sorted(datetime.fromisoformat(d['time']) for d in out if not d.get('overflow'))
    assert len(today) == 2 and today[-1].strftime('%H:%M') <= '22:59'
    assert (today[1] - today[0]).total_seconds() >= 1800
    assert sum(1 for d in out if d.get('overflow')) == 1


def test_best_lead_keeps_today():
    ds = _drafts('a')
    ds[2]['lead'] = 5.0   # the hot one stays today
    out = {d['id']: d for d in ops.clamp_times(ds, '2026-10-09', now=_late('22:20'))}   # lo 22:50: one fits
    assert not out['a-2'].get('overflow') and out['a-0'].get('overflow') and out['a-1'].get('overflow')
    assert out['a-0']['time'] < out['a-1']['time'] and out['a-2']['time'].startswith('2026-10-09T22:59')


def test_after_2259_everything_moves_to_tomorrow_but_past_days_keep_times():
    out = ops.clamp_times(_drafts('a'), '2026-10-09', now=_late('23:05'))
    assert all(d.get('overflow') and d['time'].startswith('2026-10-10T') for d in out)
    nxt = datetime.fromisoformat('2026-10-10T09:00:00+08:00')
    out = ops.clamp_times(_drafts('a'), '2026-10-09', now=nxt)   # 10-09 file rendered on 10-10: unchanged rule
    assert not any(d.get('overflow') for d in out)


def test_early_build_unchanged():
    out = ops.clamp_times(_drafts('a'), '2026-10-09', now=_late('10:00'))
    assert not any(d.get('overflow') for d in out)


def test_main_build_with_frozen_late_clock(tmp_path, monkeypatch):
    """The whole render path (clamp + CSV) survives the late clock."""
    out = ops.clamp_times(_drafts('a'), '2026-10-09', now=datetime(2026, 10, 9, 14, 40, tzinfo=timezone.utc))
    for d in out:
        d.update(text='t', status='draft_ready', action='')
    csv = ops.day_csv(out, {'a': 'A'}).decode('utf-8-sig').splitlines()
    assert len(csv) == 4 and sum(',2026-10-10 ' in r for r in csv) == 3   # 22:40 BJT + lead > 22:59
