"""Oct 7 (fd20): account-scoped X daily fetch (RapidAPI, Apify fallback, cheap batched extract, deterministic
beat tags), crypto sub-beats and compose routing of X units."""
import json
from datetime import datetime, timedelta, timezone

from live import beat_rules, x_daily
from live.content_store import ContentStore
from ml import budget

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def _created(hours):
    return (NOW - timedelta(hours=hours)).strftime('%a %b %d %H:%M:%S +0000 %Y')


def _post(pid, text, hours=2, **kw):
    return {'id': str(pid), 'created': _created(hours), 'text': text, 'lang': 'en', 'rt': False, 'reply': False,
            'self_thread': False, 'quote': False, **kw}


def _sub(handle, tier='B', accounts=('defi_narratives_en',), beats=(('crypto_defi', 'crypto_macro_en'),), core=True):
    return {'handle': handle, 'source_id': 'x_' + handle, 'accounts': list(accounts), 'roles': ['CORE'],
            'tier': tier, 'beats': [list(b) for b in beats], 'core': core}


PERP = 'BTC funding rates flipped negative across venues while open interest stays near the record; shorts are crowded here.'
DEFI = 'Aave deposits passed 40B in TVL this week; lending rates on stablecoins are back above 6% which pulls capital on-chain.'


def test_keep_post_filters():
    since = NOW - timedelta(hours=24)
    assert x_daily.keep_post(_post(1, PERP), since, NOW) == (True, None)
    assert x_daily.keep_post(_post(2, PERP, rt=True), since, NOW)[1] == 'repost'
    assert x_daily.keep_post(_post(3, PERP, reply=True), since, NOW)[1] == 'reply'
    assert x_daily.keep_post(_post(4, PERP, self_thread=True), since, NOW)[1] == 'thread_part'
    assert x_daily.keep_post(_post(5, PERP, hours=30), since, NOW)[1] == 'outside_window'
    assert x_daily.keep_post(_post(6, 'gm frens'), since, NOW)[1] == 'short'
    assert x_daily.keep_post(_post(7, PERP + ' Use my referral code for 20% off fees'), since, NOW)[1] == 'promo'
    assert x_daily.keep_post(_post(8, 'Short quote but long enough to pass the minimum for posts here ok', quote=True),
                             since, NOW)[1] == 'short_quote'
    zh = _post(9, '比特币资金费率转负，持仓量仍在高位，空头拥挤。')
    assert x_daily.keep_post(zh, since, NOW) == (True, None)


def test_gather_rapid_then_apify_fallback_tier_c_skipped_and_dedupe():
    subs = [_sub('alice'), _sub('bob'), _sub('newsdesk', tier='C'), _sub('carol')]
    timelines = {'alice': [_post(10 + i, f'{PERP} Note {i}.', hours=1 + i) for i in range(6)] + [_post(30, PERP, rt=True)],
                 'bob': RuntimeError('429')}
    asked = {}

    def rapid(handle, uids):
        v = timelines.get(handle, [])
        if isinstance(v, Exception):
            raise v
        return v

    def apify(handles, since):
        asked['handles'] = handles
        return {'bob': [_post(50, DEFI)], 'carol': [_post(60, DEFI.replace('this week', 'today'))]}, {'run_id': 'r1', 'billed_usd': 0.01}

    state = {'x': {'seen': ['x-11']}}
    plan = x_daily.gather(state, now=NOW, subs=subs, rapid=rapid, apify=apify, per_source_max=3)
    assert sorted(asked['handles']) == ['bob', 'carol']          # rapid failed / empty -> Apify, tier C never fetched
    rows = {r['handle']: r for r in plan['sources']}
    assert rows['newsdesk']['status'] == 'skipped_tier_C' and rows['newsdesk']['provider'] is None
    assert rows['alice']['provider'] == 'rapidapi' and rows['bob']['provider'] == 'apify'
    ids = [s['id'] for s in plan['selected']]
    assert 'x-11' not in ids and 'x-30' not in ids               # seen earlier / repost
    assert sum(i.startswith('x-1') for i in ids) <= 3             # per-source cap
    assert len([i for i in ids if i in ('x-50', 'x-60')]) == 1    # near-duplicate across handles kept once
    src = plan['selected'][0]
    assert src['adapter'].startswith('x:') and src['author_name'].startswith('@') and src['source_id'].startswith('x_')
    assert plan['apify']['run_id'] == 'r1'


class FakeLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, stage, messages, max_tokens):
        self.calls.append(stage)
        payload = json.loads(messages[-1]['content'][messages[-1]['content'].index('{'):])
        out = []
        for f in payload['flashes']:
            text = f['paragraphs'][0]['text']
            span = text.split(';')[0].split('；')[0]
            out.append({'flash_id': f['flash_id'], 'units': [{
                'kind': 'view', 'statement': f['outlet'] + ' argues positioning is crowded', 'speaker': f['outlet'].split()[0],
                'speaker_type': 'kol', 'freshness_class': 'current', 'numbers': [],
                'source_spans': [{'paragraph_id': f['paragraphs'][0]['paragraph_id'], 'exact_text': span}],
                'view': {'direction': 'bearish', 'subject': 'BTC positioning', 'conviction': 'medium',
                         'reasoning': [span[:60]], 'horizon': 'days'}}]})
        return {'text': json.dumps({'flashes': out}), 'finish_reason': 'stop',
                'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}


def test_extract_stores_units_with_handle_and_beat_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, 'STORE', tmp_path / 'ledger')
    monkeypatch.setattr(budget, 'LEDGER', tmp_path / 'ledger' / 'spend.json')
    subs = [_sub('alice', accounts=('crypto_trader_en',), beats=(('crypto_perp', 'crypto_macro_en'),)),
            _sub('dora', accounts=('zh_industry',), beats=(('zh_us_stock_commentary',),))]
    alice = x_daily.to_source(_post(70, PERP), subs[0])
    dora = x_daily.to_source(_post(71, 'Long post about nothing in particular, just thinking aloud about the week; '
                                       'markets feel quiet and I am reading more.'), subs[1])
    db = ContentStore(tmp_path / 'store')
    state = {}
    llm = FakeLLM()
    stats, pending = x_daily.extract(db, [alice, dora], client=llm, budget=budget, cost_cap_usd=5.0, x_budget_usd=1.0,
                                     batch_size=20, state=state, now=NOW, subs=subs)
    assert llm.calls == ['extract_flash'] and not pending
    assert stats['units_added'] == 2 and stats['units_by_handle'] == {'alice': 1, 'dora': 1}
    rows = {r['source']['id']: r for r in ContentStore(tmp_path / 'store').units()}
    a, d = rows['x-70'], rows['x-71']
    assert a['source']['adapter'] == 'x:alice' and a['source']['author_name'] == '@alice'
    assert 'crypto_perp' in a['tag_personas'] and 'crypto_macro_en' in a['tag_personas']
    assert 'zh_us_stock_commentary' in d['tag_personas']            # no keyword beat of the subscriber: its first beat
    assert a['persona_tags']['crypto_perp']['rule'].endswith(':keyword')
    assert a['unit']['extract_version'].endswith('+x-batch-v1')
    assert set(state['x']['seen']) == {'x-70', 'x-71'}


def test_keyword_beats_and_crypto_subbeats():
    assert {'crypto_perp', 'crypto_macro_en'} <= set(beat_rules.keyword_beats(PERP))
    assert 'crypto_onchain' in beat_rules.keyword_beats('比特币链上巨鲸地址持续流出交易所')
    # sub-beats need a crypto word: funding / leverage alone are not crypto, 产业链 / 人民币 are not crypto
    assert not set(beat_rules.keyword_beats('Bank funding costs and leverage ratios rose')) & set(beat_rules.SUB_BEAT_KEYWORDS)
    assert beat_rules.keyword_beats('产业链 人民币 杠杆') == {}
    rows = [{'unit_id': 'u1', 'unit': {'statement': 'Pump.fun memecoin volume fell 40% as Solana degens rotate'},
             'source': {}, 'persona_tags': {'crypto_macro_en': {'verdict': 'relevant', 'confidence': 0.9}},
             'tag_personas': ['crypto_macro_en']},
            {'unit_id': 'u2', 'unit': {'statement': 'Pump.fun memecoin volume fell'}, 'source': {},
             'persona_tags': {'industry_ai_capex': {'verdict': 'relevant', 'confidence': 0.9}},
             'tag_personas': ['industry_ai_capex']}]
    tags = beat_rules.crypto_subbeat_tags(rows)
    assert set(tags) == {'u1'} and 'crypto_meme' in tags['u1'] and 'crypto_macro_en' in tags['u1']


def test_sub_beats_are_not_sent_to_jev():
    from live import jev_front, persona_tags
    assert set(jev_front.SUB_BEATS) <= set(jev_front.PERSONAS)
    assert not set(jev_front.SUB_BEATS) & set(jev_front.JEV_BEATS)
    assert not set(jev_front.SUB_BEATS) & set(jev_front.ROUTE_CRITERIA)
    calls = []

    class Jev:
        def review(self, state, questions):
            calls.extend(questions)
            return {'status': 'completed', 'answers': {}}
    persona_tags.tag_units([{'unit_id': 'u', 'unit': {'statement': 'x'}}], jev=Jev())
    assert not any(json.loads(q)[1] in jev_front.SUB_BEATS for q in calls)


def test_crypto_accounts_have_own_lanes():
    from live.jev_front import JEV_BEATS, SUB_BEATS, jev_persona_for
    accounts = json.loads(open('live/fd20_accounts.json').read())['accounts']
    crypto = [a for a in accounts if a['kind'] == 'crypto']
    lanes = {a['id']: [b for b in a['retrieval_beats'] if b in SUB_BEATS] for a in crypto}
    assert sum(bool(v) for v in lanes.values()) >= 10
    assert lanes['defi_narratives_en'][0] == 'crypto_defi' and lanes['crypto_trader_zh'][0] == 'crypto_perp'
    for a in accounts:
        assert jev_persona_for(a['id']) in JEV_BEATS        # Jev-facing beat of an account is never a sub-beat


def test_compose_candidates_scope_x_units_to_subscribers(tmp_path, monkeypatch):
    import scripts.daily_compose as dc
    rec = lambda uid, adapter, beats: {'unit_id': uid, 'licence_tier': 'B', 'tag_personas': beats,   # noqa: E731
                                       'unit': {'statement': uid}, 'source': {'id': uid, 'source_hash': uid, 'title': uid,
                                                                              'adapter': adapter, 'published_at': NOW.isoformat()}}
    pool = [rec('x-own', 'x:alice', ['crypto_perp']), rec('x-other', 'x:mallory', ['crypto_perp']),
            rec('doc', 'rss', ['crypto_macro_en'])]
    monkeypatch.setattr(dc, 'units_for_persona', lambda store, beat, **kw: pool)
    monkeypatch.setattr(dc, 'used_sources', lambda a: set())
    monkeypatch.setattr(dc.anti_repeat, 'load_recent', lambda a: [])
    monkeypatch.setattr(dc.demo, 'ranked_balanced', lambda groups, now=None: groups)
    for name, value in (('in_shelf', True), ('group_freshness', 1.0), ('group_hook_repeat', False),
                        ('group_theme_repeat', False)):
        monkeypatch.setattr(dc.demo, name, lambda *a, value=value, **k: value)
    monkeypatch.setattr(dc.prescreen, 'prescreen', lambda account, g: {'ok': True})
    out = dc.candidates(None, 'crypto_trader_en', ['crypto_perp', 'crypto_macro_en'], {}, NOW, x_handles=['Alice'])
    ids = [g[0]['unit_id'] for g in out]
    assert 'x-other' not in ids and set(ids) == {'x-own', 'doc'}
    assert ids[0] == 'x-own'                                      # own X post first (both timely)


def test_daily_ingest_only_x(tmp_path, monkeypatch):
    from live.daily_ingest import run
    subs = [_sub('alice', accounts=('crypto_trader_en',), beats=(('crypto_perp', 'crypto_macro_en'),))]
    llm = FakeLLM()
    r = run(store=tmp_path / 'store', runs_dir=tmp_path / 'runs', inbox=tmp_path / 'inbox',
            state_path=tmp_path / 'state.json', no_dashboard=True, only=['x'], fetchers={}, extract=lambda s: [],
            backup=lambda: None, refresh=lambda: None, x_subs=subs, x_llm=llm,
            x_rapid=lambda handle, uids: [_post(80, PERP), _post(81, PERP + ' More detail here.', hours=3)],
            x_apify=lambda handles, since: ({}, {}))
    assert r['status'] == 'ok', r['steps']
    x = r['x']
    assert x['selected'] >= 1 and x['units_added'] >= 1 and x['by_provider'] == {'rapidapi': 1}
    assert {s['id']: s['status'] for s in r['steps']}.get('crypto_subbeats') == 'ok'
    st = json.loads((tmp_path / 'state.json').read_text())
    assert st['x']['seen']


def test_drafted_today_counts_earlier_runs(monkeypatch):
    import scripts.daily_compose as dc
    from datetime import date
    rows = [{'account_id': 'a', 'day': '2026-10-07', 'text': 'x'}, {'account_id': 'a', 'day': '2026-10-07', 'text': ''},
            {'account_id': 'b', 'day': '2026-10-07', 'text': 'y'}]
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day: rows)
    assert dc.drafted_today(date(2026, 10, 7)) == {'a': 1, 'b': 1}


def test_compose_one_survives_bad_packet(monkeypatch):
    import threading
    import scripts.daily_compose as dc

    def boom(group):
        raise StopIteration
    monkeypatch.setattr(dc, 'evidence_source', boom)
    pick = {'account_lang': 'en', 'unit_ids': ['u'], 'suggested_post_time_london': '2026-10-07T12:00:00+01:00',
            'angle': 'price_structure', 'post_format': {}}
    rec = {'u': {'unit_id': 'u', 'source': {'id': 's'}, 'unit': {}}}
    inner = type('C', (), {'stage_models': {}, 'calls': []})()
    r = dc.compose_one(lambda: inner, 'crypto_trader_en', pick, None, rec, {'usd': 0.0}, threading.Lock())
    assert r['status'] == 'error' and 'StopIteration' in r['error'] and r['source']['id'] == 's'
