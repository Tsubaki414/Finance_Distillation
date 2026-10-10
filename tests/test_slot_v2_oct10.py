"""Oct 10 (item 4, FD_SLOT_V2): EN in 20:00-22:59 Beijing, ZH spread over the day, <= 3 of our accounts in any 10-min
window, jittered minutes (never :00 / :30); 08:00-22:59, 30-min same-account gap, not-before and engagement windows kept."""
import copy
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_ops_dashboard as ops  # noqa: E402

DAY = '2026-10-11'
T = lambda d: datetime.fromisoformat(d['time']).astimezone(ops.BJT)  # noqa: E731


def std(acct, i, lang, stored='07:00', planned='15:00'):
    return {'id': f'{acct}-{i}', 'account_id': acct, 'lang': lang, 'time': f'{DAY}T{planned}:0{i}+08:00',
            'status': 'draft_ready', 'text': 's', 'stored': f'{DAY}T{stored}:00+08:00'}


def eng(acct, planned, close, lang='en'):
    return {'id': f'{acct}-e', 'account_id': acct, 'lang': lang, 'time': f'{DAY}T{planned}:00+08:00', 'pinned': True,
            'status': 'draft_ready', 'text': 'q', 'mode': 'quote', 'engage_close': f'{DAY}T{close}:00+08:00',
            'stored': f'{DAY}T07:00:00+08:00'}


def now(hm='07:00'):
    return datetime.fromisoformat(f'{DAY}T{hm}:00+08:00')


def matrix():
    ds = []
    for k in range(18):
        ds += [std(f'en{k}', 0, 'en'), std(f'en{k}', 1, 'en', planned='18:00')]
        ds += [std(f'zh{k}', 0, 'zh'), std(f'zh{k}', 1, 'zh', planned='18:00')]
    for k in range(6):
        ds.append(eng(f'en{k}', f'1{k}:05', f'1{k + 3}:00'))
    return ds


def max_burst(ts):
    return max(len({a for u, a in ts if t <= u < t + timedelta(minutes=10)}) for t, _ in ts)


def test_en_evening_and_gap():
    out = ops.clamp_times([std('a', 0, 'en'), std('a', 1, 'en', planned='18:00')], DAY, now=now())
    ts = sorted(T(d) for d in out)
    assert all(t.hour >= 20 and t <= ts[0].replace(hour=22, minute=59) for t in ts)
    assert ts[1] - ts[0] >= timedelta(minutes=30)


def test_zh_spread_over_the_day():
    out = ops.clamp_times([std(f'z{k}', 0, 'zh') for k in range(10)], DAY, now=now())
    ts = sorted(T(d) for d in out)
    assert ts[-1] - ts[0] >= timedelta(hours=6)


def test_matrix_burst_window_minutes():
    out = ops.clamp_times(matrix(), DAY, now=now())
    live = [d for d in out if d['status'] == 'draft_ready' and not d.get('overflow')]
    ts = [(T(d), d['account_id']) for d in live]
    assert len(live) == len(out)
    assert max_burst(ts) <= 3
    assert all(8 <= t.hour <= 22 for t, _ in ts)
    assert not any(t.minute in (0, 30) for t, _ in ts)
    assert sum(t.minute % 5 == 0 for t, _ in ts) < len(ts) / 2
    by = {}
    for t, a in ts:
        by.setdefault(a, []).append(t)
    for v in by.values():
        v.sort()
        assert all(y - x >= timedelta(minutes=30) for x, y in zip(v, v[1:]))
    en = [t for (t, a) in ts if a.startswith('en')]
    assert sum(t.hour >= 20 for t in en) >= 0.6 * len(en)


def test_deterministic():
    a = [(d['id'], d['time']) for d in ops.clamp_times(matrix(), DAY, now=now())]
    b = [(d['id'], d['time']) for d in ops.clamp_times(matrix(), DAY, now=now())]
    assert a == b


def test_not_before_respected():
    out = ops.clamp_times([std('a', 0, 'zh', stored='16:00')], DAY, now=now())
    assert T(out[0]) >= datetime.fromisoformat(f'{DAY}T16:30:00+08:00')


def test_engagement_inside_window():
    out = {d['id']: d for d in ops.clamp_times(matrix(), DAY, now=now())}
    for k in range(6):
        d = out[f'en{k}-e']
        assert T(d) <= datetime.fromisoformat(d['engage_close']) - ops.ENGAGE_MARGIN


def test_flag_off_is_old_behaviour(monkeypatch):
    ds = matrix()
    monkeypatch.setenv('FD_SLOT_V2', '0')
    off = [(d['id'], d['time']) for d in ops.clamp_times(copy.deepcopy(ds), DAY, now=now())]
    monkeypatch.setattr(ops, 'SLOT_V2_FROM', '2099-01-01')
    monkeypatch.delenv('FD_SLOT_V2')
    old = [(d['id'], d['time']) for d in ops.clamp_times(copy.deepcopy(ds), DAY, now=now())]
    assert off == old


def test_published_history_counts_for_burst():
    ds = [dict(std(f'p{k}', 0, 'en'), decision='published', time=f'{DAY}T21:1{k}:00+08:00') for k in range(3)]
    ds.append(std('n', 0, 'en'))
    out = {d['id']: d for d in ops.clamp_times(ds, DAY, now=now())}
    t = T(out['n-0'])
    assert not (datetime.fromisoformat(f'{DAY}T21:01:00+08:00') <= t <= datetime.fromisoformat(f'{DAY}T21:19:00+08:00'))


def test_late_build_best_lead_stays_today():
    ds = [dict(std('a', i, 'zh', stored='14:45'), lead=float(i == 2)) for i in range(3)]
    out = {d['id']: d for d in ops.clamp_times(ds, DAY, now=now('21:50'))}
    today = [d for d in out.values() if not d.get('overflow')]
    assert len(today) == 2 and out['a-2'].get('overflow') is None
    ts = sorted(T(d) for d in today)
    assert ts[0] >= now('22:20') and ts[-1] <= now('22:59') and ts[1] - ts[0] >= timedelta(minutes=30)
    assert all(T(d).date().isoformat() == '2026-10-12' for d in out.values() if d.get('overflow'))
