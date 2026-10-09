"""Oct 9 (Fiona approved the perf-review proposals): 1 standalone + 1 engagement slot per account and day, 回看 / 常青
only without a standalone, zh accounts lead with a hot 母题, quote / reply action column on the ops dashboard, and the
resumable nightly (ingest day_total, compose lock)."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import archive_lookback as al, compose_inbox, engagement as E

ROOT = Path(__file__).resolve().parents[1]
BJT = E.BJT
DAY = '2026-10-09'
REF = datetime(2026, 10, 8, 22, 13, tzinfo=timezone.utc)
SLOT0 = datetime(2026, 10, 9, 8, 0, tzinfo=BJT)


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def src(handle, pid, hours_before=2.0, likes=300, followers=120000):
    pub = SLOT0 - timedelta(hours=hours_before)
    return {'url': f'https://x.com/{handle}/status/{pid}', 'published_at': pub.isoformat(), 'source_language': 'zh',
            'x_metrics': {'likes': likes, 'views': 30000, 'followers': followers, 'reposts': 5, 'replies': 9}}


@pytest.fixture(autouse=True)
def slot_rule_on(monkeypatch, tmp_path):
    monkeypatch.setenv('FD_ENGAGE_FILL2', '0')   # Oct 9 night thresholds pinned off (legacy expectations)
    monkeypatch.setenv('FD_ENGAGE_PICK_GATE', '0')
    monkeypatch.setenv('FD_ENGAGE', '1')
    monkeypatch.setenv('FD_SLOT_RULE', '1')
    monkeypatch.setenv('FD_ENGAGE_LOG', str(tmp_path / 'engage_log'))
    monkeypatch.setattr(E, '_ROSTER', {})


# ------------------------------------------------------------------ 1. slot rule
def test_one_engagement_slot_per_account_any_age():
    cands = {'a': [{'key': 'k1', 'source': src('big1', '11', 1)}, {'key': 'k2', 'source': src('big2', '12', 3)}],
             'b': [{'key': 'k3', 'source': src('big3', '13', 2)}]}
    dec, log = E.plan_day(cands, day=DAY, ref=REF, langs={'a': 'zh', 'b': 'zh'}, cold={'a': False, 'b': False})
    assert sum(1 for d in dec['a'].values() if d['mode']) == 1     # one slot, not reply + quote
    assert sum(1 for d in dec['b'].values() if d['mode']) == 1     # a non-cold account gets its slot too
    dec, _ = E.plan_day(cands, day=DAY, ref=REF, langs={'a': 'zh', 'b': 'zh'})   # cold=None: everyone eligible
    assert all(any(d['mode'] for d in dec[a].values()) for a in ('a', 'b'))


def test_one_account_per_target_and_ready_rows_fill_the_slot():
    same = {'a': [{'key': 'k1', 'source': src('big1', '11', 1)}], 'b': [{'key': 'k1', 'source': src('big1', '11', 1)}]}
    dec, _ = E.plan_day(same, day=DAY, ref=REF, langs={'a': 'zh', 'b': 'zh'})
    assert sum(1 for a in 'ab' for d in dec[a].values() if d['mode']) == 1
    earlier = [{'account_id': 'a', 'draft_status': 'draft_ready', 'post_mode': 'reply',
                'engagement': {'mode': 'reply', 'url': 'https://x.com/big9/status/99'}}]
    state = E.DayState.from_rows(earlier)
    dec, _ = E.plan_day({'a': [{'key': 'k2', 'source': src('big2', '12', 1)}]}, day=DAY, ref=REF, state=state,
                        langs={'a': 'zh'})
    assert not any(d['mode'] for d in dec['a'].values())          # engage_pull later in the day: slot already used
    held = [dict(earlier[0], draft_status='needs_review', held=True,
                 engagement={'mode': 'quote', 'url': 'https://x.com/big8/status/98'})]
    dec, _ = E.plan_day({'a': [{'key': 'k2', 'source': src('big2', '12', 1)}]}, day=DAY, ref=REF,
                        state=E.DayState.from_rows(held), langs={'a': 'zh'})
    assert any(d['mode'] == 'reply' for d in dec['a'].values())   # a held quote does not fill the slot


def test_age_windows_still_hold():
    old = {'a': [{'key': 'k1', 'source': src('big1', '11', 13)}]}
    dec, _ = E.plan_day(old, day=DAY, ref=REF, langs={'a': 'zh'})
    assert not any(d['mode'] for d in dec['a'].values())


def test_slot_kinds_and_day_counts(tmp_path, monkeypatch):
    dc = _script('daily_compose')
    assert dc.slot_kind('x-2108484110075510885') == 'engage' and dc.slot_kind('ch109_theblock-1') == 'standalone'
    base = tmp_path / 'inbox'
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(base))
    rows = [{'id': 'c1', 'account_id': 'a', 'text': 'x', 'draft_status': 'draft_ready'},
            {'id': 'c2', 'account_id': 'a', 'text': 'y', 'draft_status': 'draft_ready',
             'post_format': {'engage': 'reply'}},
            {'id': 'c3', 'account_id': 'b', 'text': 'z', 'draft_status': 'needs_review', 'held': True}]
    for r in rows:
        compose_inbox.add(dict(r, day=DAY), base=base)
    real = compose_inbox.rows
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day, **kw: real(day, base=base))
    assert dc.day_slots(DAY) == {'a': {'standalone': 1, 'engage': 1}}


def test_archive_only_without_a_standalone(tmp_path, monkeypatch):
    monkeypatch.delenv('FD_ARCHIVE', raising=False)
    monkeypatch.delenv('FD_ARCHIVE_ACCOUNTS', raising=False)
    cfg = {'enabled_accounts': ['crypto_altcoin_zh'], 'per_day': 1, 'target_ready_per_day': 2}
    base = tmp_path / 'inbox'
    compose_inbox.add({'id': 'e1', 'day': DAY, 'account_id': 'crypto_altcoin_zh', 'text': 'x',
                       'draft_status': 'draft_ready', 'post_format': {'engage': 'quote'}}, base=base)
    ok, why = al.gate('crypto_altcoin_zh', DAY, config=cfg, base=base)
    assert ok and 'no standalone' in why                         # an engagement draft is not a standalone
    compose_inbox.add({'id': 's1', 'day': DAY, 'account_id': 'crypto_altcoin_zh', 'text': 'y',
                       'draft_status': 'draft_ready'}, base=base)
    ok, why = al.gate('crypto_altcoin_zh', DAY, config=cfg, base=base)
    assert not ok and 'standalone' in why                         # 1 standalone: no 回看 as a 2nd post


# ------------------------------------------------------------------ 3. zh hot-first
def test_zh_hot_rule_switch():
    dc = _script('daily_compose')
    assert dc.zh_hot_rule('zh', {}) and not dc.zh_hot_rule('en', {})
    assert not dc.zh_hot_rule('zh', {'FD_ZH_HOT_FIRST': '0'})
    assert dc.ZH_HOT_MIN == 2.5


# ------------------------------------------------------------------ 2. dashboard action column
def test_action_column_and_card_target():
    ops = _script('build_ops_dashboard')
    row = {'post_mode': 'reply', 'engagement': {'mode': 'reply', 'url': 'https://x.com/TedPillows/status/1'}}
    m = ops.media_of(row)
    assert m['action'] == '回复 https://x.com/TedPillows/status/1' and m['target'].endswith('/1')
    assert ops.media_of({'post_mode': 'quote', 'quote_target_url': 'https://x.com/a/status/2'})['action'] \
        == '引用 https://x.com/a/status/2'
    assert ops.media_of({'post_mode': 'original'})['action'] == ''
    out = ops.day_csv([{'account_id': 'a', 'time': '2026-10-10T19:40:00+08:00', 'text': 't', 'status': 'draft_ready',
                        'action': m['action']},
                       {'account_id': 'b', 'time': '2026-10-10T20:40:00+08:00', 'text': 'u', 'status': 'draft_ready',
                        'action': ''}], {'a': 'A'}).decode('utf-8-sig').splitlines()
    assert out[0] == 'account,time (北京时间),text,引用/回复'
    assert out[1] == 'A,2026-10-10 19:40,t,回复 https://x.com/TedPillows/status/1' and out[2].endswith(',u,')
    assert '用 X 的「回复」发在这条帖子下面' in Path(ROOT / 'scripts' / 'build_ops_dashboard.py').read_text()
    assert ops.lead_score({'motif_heat': 3.0}) > ops.lead_score({})


# ------------------------------------------------------------------ resumable nightly
def test_ingest_rerun_keeps_day_total(tmp_path):
    from live import daily_ingest
    p = tmp_path / '20261010.json'
    first = {'cost_usd': {'total': 1.25}}
    daily_ingest.keep_day_total(p, first)
    assert first['cost_usd']['day_total'] == 1.25
    p.write_text(json.dumps(first))
    second = {'cost_usd': {'total': 0.5}}
    daily_ingest.keep_day_total(p, second)
    assert second['cost_usd']['day_total'] == 1.75 and (tmp_path / '20261010_run1.json').exists()


def test_cron_scripts_resume_and_lock():
    ing = (ROOT / 'scripts' / 'cron' / 'daily_ingest.sh').read_text()
    comp = (ROOT / 'scripts' / 'cron' / 'daily_compose.sh').read_text()
    pull = (ROOT / 'scripts' / 'cron' / 'engage_pull.sh').read_text()
    assert 'FD_INGEST_RESUME' in ing and 'skipping to compose' in ing
    assert 'flock -n 9' in comp and "day_total" in comp
    assert 'FD_ENGAGE_PER_ACCOUNT:-2' in pull and 'FD_ENGAGE_ONLY=1' in pull
