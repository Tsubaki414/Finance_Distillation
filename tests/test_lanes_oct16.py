"""Oct 16 (Fiona: independent lanes): synthetic, offline tests - no network, no live store, tmp dirs only."""
import json
import multiprocessing as mp
import os
import threading
import time

import httpx
import pytest

from live import compose_inbox, lanes, stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget


# ---------------------------------------------------------------- lane locks
def test_lanes_hold_independent_locks_same_lane_excluded():
    with lanes.lane_lock('main') as main, lanes.lane_lock('engage') as eng, lanes.lane_lock('midday', 'zh') as mid, \
            lanes.lane_lock('fill') as fill, lanes.lane_lock('mindmap') as mm:
        assert main and eng and mid and fill and mm            # five lanes at once
        with lanes.lane_lock('engage') as again:
            assert again is False                                # a second engage run is excluded
        with lanes.lane_lock('midday', 'en') as other_lang:
            assert other_lang is True                            # midday zh and en are separate
    with lanes.lane_lock('engage') as after:
        assert after is True                                     # released


def test_main_lane_keeps_the_historic_lock_file(tmp_path):
    assert lanes.lane_lock_path('main').name == '.daily_compose.lock'
    assert lanes.lane_lock_path('engage').name == '.lane_engage.lock'
    assert lanes.lane_lock_path('midday', 'zh').name == '.lane_midday_zh.lock'


def test_lane_name_from_existing_cron_env():
    assert lanes.lane_name({}) == 'main'
    assert lanes.lane_name({'FD_ENGAGE_ONLY': '1'}) == 'engage'
    assert lanes.lane_name({'FD_MIDDAY': '1'}) == 'midday'
    assert lanes.lane_name({'FD_LANE': 'fill', 'FD_ENGAGE_ONLY': '1'}) == 'fill'


# ---------------------------------------------------------------- atomic writes
def test_atomic_write_never_exposes_a_partial_file(tmp_path):
    p = tmp_path / 'a.json'
    lanes.atomic_write_text(p, json.dumps({'n': 0}))
    stop, bad = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                json.loads(p.read_text())
            except ValueError:
                bad.append(1)

    def writer(k):
        for i in range(150):
            lanes.atomic_write_text(p, json.dumps({'n': k * 1000 + i, 'pad': 'x' * 20000}))
    rt = threading.Thread(target=reader)
    rt.start()
    ws = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    [w.start() for w in ws]
    [w.join() for w in ws]
    stop.set()
    rt.join()
    assert not bad
    assert not [x for x in tmp_path.iterdir() if x.name.endswith('.tmp')]   # no leftover temp files


def test_locked_append_lines_never_interleave(tmp_path):
    p = tmp_path / 'ledger.jsonl'

    def w(k):
        for i in range(60):
            lanes.locked_append(p, json.dumps({'k': k, 'i': i, 'pad': 'y' * 9000}))
    ts = [threading.Thread(target=w, args=(k,)) for k in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    assert len(rows) == 360


# ---------------------------------------------------------------- claims (cross-lane anti-repeat)
def _pick(sid, title='t'):
    return {'source_id': sid, 'title': title}


def test_claim_blocks_other_lane_not_same_lane():
    a = {'acct1': [_pick('s1')], 'acct2': [_pick('s1')]}
    assert lanes.claim_plan('2026-10-16', a, 'main', 'r1') == []
    b = {'acct1': [_pick('s1'), _pick('s2')]}
    dropped = lanes.claim_plan('2026-10-16', b, 'midday', 'r2')
    assert [d[:3] for d in dropped] == [('acct1', 't', 'acct:acct1:s1')] and dropped[0][3] == 'main'
    assert [p['source_id'] for p in b['acct1']] == ['s2']
    c = {'acct1': [_pick('s1')]}                                  # same lane, later round / rewrite: allowed
    assert lanes.claim_plan('2026-10-16', c, 'main', 'r3') == [] and c['acct1']
    d = {'acct3': [_pick('s1')]}                                  # a different account may take the same story
    assert lanes.claim_plan('2026-10-16', d, 'engage', 'r4') == [] and d['acct3']


def test_engage_target_is_one_account_across_lanes():
    first = {'acct1': [_pick('x-1999')]}
    assert lanes.claim_plan('2026-10-16', first, 'engage', 'r1') == []
    second = {'acct2': [_pick('x-1999')]}
    assert lanes.claim_plan('2026-10-16', second, 'main', 'r2')[0][2] == 'target:x-1999'
    assert second['acct2'] == []


def test_claims_expire(monkeypatch):
    plan = {'a': [_pick('s9')]}
    lanes.claim_plan('2026-10-16', plan, 'main', 'r1', now=1000.0)
    again = {'a': [_pick('s9')]}
    assert lanes.claim_plan('2026-10-16', again, 'engage', 'r2', now=1000.0 + lanes.CLAIM_TTL_S + 1) == []


def _claim_proc(args):
    d, i, q = args
    os.environ['FD_LANE_LOCK_DIR'] = d
    plan = {'acct': [_pick('story-race')]}
    lanes.claim_plan('2026-10-16', plan, f'lane{i}', f'r{i}')
    q.put((i, len(plan['acct'])))


def test_claim_race_between_processes_has_one_winner(tmp_path):
    q = mp.Queue()
    ps = [mp.Process(target=_claim_proc, args=((str(tmp_path / 'lane_locks'), i, q),)) for i in range(8)]
    [p.start() for p in ps]
    [p.join(30) for p in ps]
    got = [q.get(timeout=5) for _ in ps]
    assert sum(n for _, n in got) == 1                            # exactly one lane keeps the (account, story)


# ---------------------------------------------------------------- shared day spend ledger
def _spend_proc(args):
    d, n = args
    os.environ['FD_LANE_LOCK_DIR'] = d
    for _ in range(n):
        lanes.spend_add('2026-10-16', 'engage', 0.01)


def test_day_spend_ledger_is_exact_across_processes_and_caps(tmp_path):
    d = str(tmp_path / 'lane_locks')
    ps = [mp.Process(target=_spend_proc, args=((d, 25),)) for _ in range(6)]
    [p.start() for p in ps]
    [p.join(30) for p in ps]
    assert lanes.spend_total('2026-10-16') == pytest.approx(1.5)   # no lost update
    lanes.spend_add('2026-10-16', 'main', 23.0)
    assert lanes.day_has_room('2026-10-16', 0.4) and not lanes.day_has_room('2026-10-16', 0.6)   # $25/day total
    assert json.loads(lanes._spend_path('2026-10-16').read_text())['lanes'] == {'engage': 1.5, 'main': 23.0}


# ---------------------------------------------------------------- inbox: no lost update, atomic
def _row(i, **kw):
    return {'id': f'compose-{i:03d}', 'day': '2026-10-16', 'account_id': 'acct', 'text': f'body {i}', **kw}


def test_inbox_supersede_and_review_do_not_lose_each_other(tmp_path):
    base = tmp_path / 'inbox'
    for i in range(20):
        compose_inbox.add(_row(i), base=base)
    errors = []

    def sup():
        for i in range(20):
            try:
                compose_inbox.supersede(f'compose-{i:03d}', by='new', reason='rerun', base=base)
            except Exception as e:   # noqa: BLE001
                errors.append(e)

    def rev():
        for i in range(20):
            try:
                r = compose_inbox.get(f'compose-{i:03d}', base=base)
                compose_inbox.review(f'compose-{i:03d}', decision='approve', reviewer='f', reason='ok',
                                     text=r['text'], expected_hash=r['text_hash'], base=base)
            except ValueError:
                pass   # 'stale version' / superseded interplay is a legal outcome
            except Exception as e:   # noqa: BLE001
                errors.append(e)
    ts = [threading.Thread(target=sup), threading.Thread(target=rev)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    for i in range(20):                                           # every file is valid JSON; a recorded review survives
        r = json.loads((base / '2026-10-16' / f'compose-{i:03d}.json').read_text())
        assert r['id'] == f'compose-{i:03d}'
        if r.get('review_status') == 'approved':
            assert r['reviews'], 'approved without its review entry = lost update'


def test_inbox_add_is_atomic_for_readers(tmp_path):
    base = tmp_path / 'inbox'
    stop, bad = threading.Event(), []

    def rd():
        while not stop.is_set():
            for r in compose_inbox.rows('2026-10-16', base=base):   # rows() skips torn files silently; count via direct read
                pass
            for p in (base / '2026-10-16').glob('*.json') if (base / '2026-10-16').exists() else []:
                try:
                    json.loads(p.read_text())
                except FileNotFoundError:
                    pass
                except ValueError:
                    bad.append(p.name)
    t = threading.Thread(target=rd)
    t.start()
    for i in range(120):
        compose_inbox.add(_row(i, pad='z' * 30000), base=base)
        compose_inbox.add(_row(i, pad='q' * 30000, extra=i), base=base)   # overwrite of an existing row
    stop.set()
    t.join()
    assert not bad


# ---------------------------------------------------------------- deadlines
def test_run_with_deadline_returns_raises_and_propagates():
    assert lanes.run_with_deadline(lambda: 7, 2) == 7
    with pytest.raises(ValueError):
        lanes.run_with_deadline(lambda: (_ for _ in ()).throw(ValueError('x')), 2)
    t0 = time.monotonic()
    with pytest.raises(lanes.DeadlineExceeded):
        lanes.run_with_deadline(lambda: time.sleep(5), 0.3)
    assert time.monotonic() - t0 < 2


def test_call_budget_shrinks_to_account_deadline(monkeypatch):
    monkeypatch.setenv('FD_CALL_TIMEOUT_S', '100')
    assert lanes.call_budget_s() == 100
    lanes.set_context(deadline=time.monotonic() + 5)
    try:
        assert 1 <= lanes.call_budget_s() <= 5
        lanes.set_context(deadline=time.monotonic() - 1)
        with pytest.raises(lanes.DeadlineExceeded):
            lanes.call_budget_s()
    finally:
        lanes.clear_context()


SUB_KEY = 'sk-subrouter-secret-abcdef123'


@pytest.fixture
def relay_env(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 10.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(budget, 'RUNS', tmp_path / 'review_runs.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.delenv('GEMINI_RELAY_API_KEY', raising=False)
    monkeypatch.setenv('SUBROUTER_API_KEY', SUB_KEY)
    monkeypatch.setenv('FD_SUBROUTER_RETRIES', '1')
    monkeypatch.setenv('FD_SUBROUTER_BACKOFF', '0')
    prices = budget.PRICES.copy()
    yield
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def _config():
    return {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
            'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
            'stage_models': stage_models.from_env(stage_models.load(), {'SUBROUTER_API_KEY': SUB_KEY})}


def _ok(model):
    return httpx.Response(200, json={'id': 'x', 'model': model,
                                     'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 10, 'completion_tokens': 20}})


def test_one_stuck_model_call_is_cut_and_logged(tmp_path, relay_env, monkeypatch, capsys):
    monkeypatch.setenv('FD_CALL_TIMEOUT_S', '0.4')
    monkeypatch.setenv('FD_LATENCY_JSONL', str(tmp_path / 'lat.jsonl'))
    calls = []

    def handler(request):
        calls.append(1)
        time.sleep(3 if len(calls) <= 2 else 0)   # first call and its retry hang, the next ones answer
        return _ok(json.loads(request.content)['model'])
    c = ErisedaiClient(tmp_path / 'calls', configuration=_config(), transport=httpx.MockTransport(handler))
    lanes.set_context(account='crypto_macro_zh')
    t0 = time.monotonic()
    try:
        with pytest.raises(Exception) as ei:
            c('compose', [{'role': 'user', 'content': 'hi'}], 500)
    finally:
        lanes.clear_context()
    assert time.monotonic() - t0 < 3, 'must not wait for the 3 s hang'
    out = capsys.readouterr().out
    assert '[latency] account=crypto_macro_zh stage=compose seconds=0.4 status=failed:ReadTimeout' in out
    rows = [json.loads(x) for x in (tmp_path / 'lat.jsonl').read_text().splitlines()]
    assert rows and rows[0]['account'] == 'crypto_macro_zh' and rows[0]['stage'] == 'compose' and rows[0]['seconds'] >= 0.4
    assert 'Relay transport failed' in str(ei.value) or 'subrouter' in str(ei.value) or ei.value


def test_account_deadline_stops_further_calls(tmp_path, relay_env, monkeypatch):
    monkeypatch.setenv('FD_CALL_TIMEOUT_S', '50')
    c = ErisedaiClient(tmp_path / 'calls', configuration=_config(),
                       transport=httpx.MockTransport(lambda r: _ok(json.loads(r.content)['model'])))
    lanes.set_context(account='a', deadline=time.monotonic() - 1)
    try:
        with pytest.raises(lanes.DeadlineExceeded):
            c('compose', [{'role': 'user', 'content': 'hi'}], 500)
    finally:
        lanes.clear_context()


def test_fast_call_logs_completed_latency(tmp_path, relay_env, capsys):
    c = ErisedaiClient(tmp_path / 'calls', configuration=_config(),
                       transport=httpx.MockTransport(lambda r: _ok(json.loads(r.content)['model'])))
    c('stance', [{'role': 'user', 'content': 'hi'}], 500)
    out = capsys.readouterr().out
    assert 'stage=stance' in out and 'status=completed' in out
    line = lanes.latency_line('acct', 'stance', 1.234, 'completed')
    assert line == '[latency] account=acct stage=stance seconds=1.2 status=completed'


def test_rollback_flag_restores_old_behaviour(tmp_path, relay_env, monkeypatch, capsys):
    monkeypatch.setenv('FD_LANES', '0')
    assert not lanes.enabled()
    with lanes.day_lock('2026-10-16', 'x') as got:
        assert got is False                                       # no lock taken
    monkeypatch.setenv('FD_CALL_TIMEOUT_S', '0.2')
    c = ErisedaiClient(tmp_path / 'calls', configuration=_config(),
                       transport=httpx.MockTransport(lambda r: (time.sleep(0.6), _ok(json.loads(r.content)['model']))[1]))
    c('stance', [{'role': 'user', 'content': 'hi'}], 500)         # slower than the cap but FD_LANES=0: not cut
    assert '[latency]' not in capsys.readouterr().out


# ---------------------------------------------------------------- compose_one account timeout
def test_compose_one_account_timeout_returns_error_row_quickly(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, 'scripts')
    import daily_compose as dc
    monkeypatch.setenv('FD_ACCOUNT_TIMEOUT_S', '0.4')
    monkeypatch.setenv('FD_ACCOUNT_GRACE_S', '0.2')
    monkeypatch.setattr(dc, 'evidence_source', lambda group: ({'id': 's'}, []))
    monkeypatch.setattr(dc.compose, 'compose_source', lambda *a, **k: time.sleep(5))
    monkeypatch.setattr(dc, 'DraftClient', lambda client, log: type('D', (), {'paths': []})())
    monkeypatch.setattr(dc, 'ViewLedger', lambda a: None)
    monkeypatch.setattr(dc.angles, 'payload', lambda a, l: {})
    pick = {'account_lang': 'zh', 'unit_ids': ['u'], 'suggested_post_time_london': '2026-10-16T12:00:00+01:00',
            'angle': 'x', 'post_format': {}, 'source_id': 's'}
    spend, lock = {'usd': 0.0}, threading.Lock()
    t0 = time.monotonic()
    acct = dc.fd_accounts.rows(dc.CONFIG)[0]['id']
    r = dc.compose_one(lambda: None, acct, pick, __import__('datetime').date(2026, 10, 16),
                       {'u': {'source': {'id': 's'}}}, spend, lock)
    assert time.monotonic() - t0 < 3
    assert r['status'] == 'error' and r['error'].startswith('account_timeout')
    assert r['account_id'] == acct


# ---------------------------------------------------------------- shared ledgers
def test_content_store_tolerates_torn_line_and_writes_in_one_batch(tmp_path):
    from live.content_store import ContentStore
    s = ContentStore(tmp_path / 'cs')
    (tmp_path / 'cs' / 'units.jsonl').write_text('{"unit_id": "u1", "unit": {}, "licence_tier": "A"}\n{"unit_id": "u2", "uni')
    s2 = ContentStore(tmp_path / 'cs')                             # a torn last line must not crash a starting lane
    assert 'u1' in s2._rows and 'u2' not in s2._rows


def test_anti_repeat_history_loses_no_row_under_concurrency(tmp_path, monkeypatch):
    from live import anti_repeat
    monkeypatch.setattr(anti_repeat, 'HISTORY_DIR', tmp_path / 'h')
    monkeypatch.setattr(anti_repeat, 'FALLBACK_DIR', tmp_path / 'f')

    def w(k):
        for i in range(5):
            anti_repeat.record_draft('acct', f'draft {k}-{i} BTC', meta={'draft_id': f'{k}-{i}'})
    ts = [threading.Thread(target=w, args=(k,)) for k in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ids = {r.get('draft_id') for r in anti_repeat.load_recent('acct', 29)}
    assert len(ids) == 20   # 4 lanes x 5 drafts, none lost (unlocked read-modify-write loses some)
