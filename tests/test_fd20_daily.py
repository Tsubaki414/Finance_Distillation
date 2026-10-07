"""fd20 (Oct 7): 20 main accounts, angles, review inbox, daily compose gate."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from live import angles, compose_inbox, registry
from live.jev_front import PERSONAS, jev_persona_for

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'live' / 'fd20_accounts.json').read_text())['accounts']


def test_twenty_main_accounts_resolve_to_personas_with_clusters():
    assert len(CONFIG) == 20 and len({a['id'] for a in CONFIG}) == 20
    personas = registry.load_personas()
    emotion = json.loads((ROOT / 'live' / 'emotion_tiers.json').read_text())['personas']
    for a in CONFIG:
        p = registry.persona_for_account(a['id'], personas)
        assert p.lang == a['lang']
        assert len(p.donor_weights) >= 3, a['id']
        assert set(p.raw['banned']) >= {'claimed_positions', 'claimed_returns', 'source_author_experience'}
        assert a['id'] in emotion
        assert jev_persona_for(a['id']) in PERSONAS, a['id']       # units_for_persona never raises
        assert all(b in PERSONAS for b in a['retrieval_beats'])


def test_restrained_and_emotional_tiers():
    emotion = json.loads((ROOT / 'live' / 'emotion_tiers.json').read_text())['personas']
    assert emotion['zh_industry'] == 'low' and emotion['zh_macro'] == 'low'
    assert emotion['crypto_trader_zh'] == 'high' and emotion['crypto_macro_en'] == 'high'


def test_arbitration_knows_new_accounts():
    from live.claim_arbitration import _load_beats
    beats = _load_beats()
    assert all(a['id'] in beats for a in CONFIG)


def test_angles_detect_and_assign_without_collision():
    assert 'onchain_holders' in angles.angles_of('长期持有者的成本价在 6 万附近')
    assert 'flows_etf' in angles.angles_of('Spot ETF net inflows hit $1.2bn')
    mix = {'flows_etf': 0.5, 'onchain_holders': 0.3, 'macro_liquidity': 0.2}
    a1, why1 = angles.assign(mix, 'ETF inflows and holder cost basis', taken=())
    a2, why2 = angles.assign(mix, 'ETF inflows and holder cost basis', taken={a1})
    assert a1 == 'flows_etf' and why1 == 'source_fit'
    assert a2 == 'onchain_holders' and a2 != a1
    p = angles.payload(a2, 'zh')
    assert p['id'] == a2 and '筹码' in p['lens']
    assert 'invent' in p['rule']


def test_distinctive_prefers_own_lenses():
    mixes = {'a': {'macro_liquidity': 0.6, 'retail_lesson': 0.4}, 'b': {'macro_liquidity': 0.9, 'cycle_position': 0.1},
             'c': {'macro_liquidity': 0.9, 'flows_etf': 0.1}}
    lead = angles.distinctive(mixes)
    assert angles.top_angles(lead['a'], 1) == ['retail_lesson']


def test_inbox_review_guard(tmp_path):
    row = compose_inbox.add({'id': 'compose-x1', 'day': '2026-10-07', 'account_id': 'crypto_diary_zh', 'text': '原稿'},
                            base=tmp_path)
    assert row['review_status'] == 'pending' and row['publishable'] is False
    h = row['text_hash']
    with pytest.raises(ValueError):
        compose_inbox.review('compose-x1', decision='approve', reviewer='r', reason='ok', text='改了', expected_hash=h, base=tmp_path)
    with pytest.raises(ValueError):
        compose_inbox.review('compose-x1', decision='minor_edit', reviewer='r', reason='ok', text='原稿', expected_hash=h, base=tmp_path)
    with pytest.raises(ValueError):
        compose_inbox.review('compose-x1', decision='approve', reviewer='', reason='ok', text='原稿', expected_hash=h, base=tmp_path)
    compose_inbox.review('compose-x1', decision='minor_edit', reviewer='r', reason='语气', text='改稿', expected_hash=h, base=tmp_path)
    with pytest.raises(ValueError, match='stale'):
        compose_inbox.review('compose-x1', decision='approve', reviewer='r', reason='ok', text='改稿', expected_hash=h, base=tmp_path)
    stored = compose_inbox.get('compose-x1', base=tmp_path)
    assert stored['reviewed_text'] == '改稿' and stored['review_status'] == 'edited' and stored['publishable'] is False
    assert compose_inbox.rows('2026-10-07', base=tmp_path)[0]['id'] == 'compose-x1'


def test_inbox_page_and_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import backend.content_dashboard as dash
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path))
    row = compose_inbox.add({'id': 'compose-y1', 'day': '2026-10-07', 'account_id': 'btc_cycles_en', 'name': 'Elias',
                             'text': 'Draft body', 'angle': {'lens': 'cycle position'}})
    client = TestClient(dash.app)
    page = client.get('/compose-inbox?day=2026-10-07')
    assert page.status_code == 200 and 'Draft body' in page.text and '<script src="/compose-inbox.js">' in page.text
    assert client.get('/compose-inbox.js').status_code == 200
    r = client.post('/api/compose-inbox/compose-y1/review', json={'decision': 'reject', 'reviewer': 'r', 'reason': 'off beat',
                                                                  'text': 'Draft body', 'expected_hash': row['text_hash']})
    assert r.status_code == 200
    assert client.get('/api/compose-inbox?day=2026-10-07').json()['rows'][0]['review_status'] == 'rejected'
    assert not any('publish' in getattr(route, 'path', '') for route in dash.app.routes if 'compose' in getattr(route, 'path', ''))


def test_daily_compose_is_off_without_flag(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != 'FD_DAILY_COMPOSE'}
    env['FD_COMPOSE_RUNS'] = str(tmp_path)
    out = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'daily_compose.py')], env=env, cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and 'compose is off' in out.stdout
    assert not any(tmp_path.iterdir())


def test_route_allows_same_language_for_compose_accounts(monkeypatch):
    from live.account_source_adaptation import AccountSourcePipeline, _account
    from live.distillation_source import source_record
    monkeypatch.setenv('ACCOUNT_COMPOSE_PIPELINE', '1')
    acc = _account('zh_industry'); acc['lang'] = acc.get('lang') or acc['language']
    acc.setdefault('profile_version', 'test')
    pipe = AccountSourcePipeline.__new__(AccountSourcePipeline)
    pipe.accounts = [acc]
    calls = []
    pipe.ask = lambda *a, **k: calls.append(a) or {'decision': 'NONE'}
    pipe.account_context = {}
    src = source_record({'id': 'zh1', 'source_id': 'x_test', 'source_language': 'zh', 'url': 'https://example.test/a',
                         'title': '英伟达', 'original_text': '英伟达数据中心收入同比增长，AI 芯片需求仍强。',
                         'author_name': 'a', 'published_at': '2026-10-07T00:00:00Z'})
    try:
        AccountSourcePipeline.route(pipe, src, {})
    except Exception:
        pass
    assert calls, 'same-language source should reach the routing model for a compose account'
    monkeypatch.delenv('ACCOUNT_COMPOSE_PIPELINE')
    calls.clear()
    route, _ = AccountSourcePipeline.route(pipe, src, {})
    assert route['decision'] == 'NONE' and calls == []
