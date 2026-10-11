"""Oct 8 PM P1 (fd-pm-quality): own-X support facts / data packets, evidence span bug, stance contract retry, relay
transport retry, fill rounds that skip tried sources, selection prechecks, same-language arbitration, hotspot tweaks."""
import importlib.util
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import compose, x_support
from live.distillation import ContractError

ROOT = Path(__file__).resolve().parents[1]
REF = datetime(2026, 10, 7, 23, 53, tzinfo=timezone.utc)


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def dc():
    return _script('daily_compose')


@pytest.fixture(scope='module')
def vrc():
    return _script('voice_relay_check')


def _span(text):
    return {'source_hash': 'h', 'paragraph_id': 'P1', 'start': 0, 'end': len(text), 'exact_text': text,
            'typography_normalized': False}


def _view_unit(uid, quote, subject='BTC', horizon='weeks', statement=None):
    return {'unit_id': uid, 'kind': 'view', 'usage': 'paraphrase', 'statement': statement or f'@a argues {quote}',
            'numbers': [], 'speaker': '@a', 'speaker_type': 'kol', 'source_spans': [_span(quote)],
            'view': {'direction': 'bullish', 'subject': subject, 'conviction': 'medium', 'reasoning': [quote],
                     'horizon': horizon, 'support': [{'span_index': 0, 'quote': quote}]}}


def _fact_unit(uid, text, numbers=()):
    return {'unit_id': uid, 'kind': 'fact', 'usage': 'paraphrase', 'statement': text, 'numbers': list(numbers),
            'view': None, 'speaker': 'pub', 'speaker_type': 'media', 'source_spans': [_span(text)]}


def _rec(unit, source, tier='B'):
    return {'unit_id': unit['unit_id'], 'licence_tier': tier, 'unit': unit, 'source': source, 'tag_personas': []}


def _x_source(i, title, hours_ago=3, handle='alice'):
    return {'id': f'x-{i}', 'source_id': f'x_{handle}', 'publisher': f'@{handle} (X)', 'title': title,
            'url': f'https://x.com/{handle}/status/{i}', 'source_hash': f'xh{i}', 'adapter': f'x:{handle}',
            'published_at': (REF - timedelta(hours=hours_ago)).isoformat(), 'source_language': 'en'}


def _news_source(i, title, hours_ago=5):
    return {'id': f'n-{i}', 'source_id': 'coindesk', 'publisher': 'CoinDesk', 'title': title,
            'url': f'https://coindesk.com/{i}', 'source_hash': f'nh{i}', 'adapter': 'rss',
            'published_at': (REF - timedelta(hours=hours_ago)).isoformat(), 'source_language': 'en'}


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def units(self, **_):
        return list(self.rows)


def _text(g):
    return ' '.join([str(g[0]['source'].get('title') or '')] + [str(r['unit'].get('statement') or '') for r in g])


# ------------------------------------------------------------------ evidence span bug (StopIteration)

def test_evidence_source_span_with_trailing_space_or_blank_line_maps(vrc):
    src = _news_source(1, 'Robinhood adds bitcoin')
    a = _fact_unit('u1', 'Robinhood has added approximately $25 million worth of bitcoin  to its balance sheet. ')
    b = _fact_unit('u2', 'First line.\n\n  Second paragraph of the same span.')
    source, units = vrc.evidence_source([_rec(a, src), _rec(b, src)])
    paras = {p['paragraph_id']: p['exact_text'] for p in vrc.paragraphs(source['original_text'])}
    for u in units:
        for s in u['source_spans']:
            assert s['exact_text'] in paras[s['paragraph_id']]
    assert units[0]['source_spans'][0]['exact_text'].endswith('sheet.')
    assert units[1]['source_spans'][0]['exact_text'] == 'First line.\nSecond paragraph of the same span.'


# ------------------------------------------------------------------ x_support

def test_view_only_post_gets_same_story_public_fact_with_citation():
    from live.view_enrich import has_valid_view
    xs = _x_source(1, 'Hyperliquid volume hit $12.5 billion today, HYPE looks strong')
    view = _view_unit('xv1', 'HYPE looks strong', subject='Hyperliquid volume')
    assert has_valid_view(view)
    news = _news_source(2, 'Hyperliquid daily volume reaches $12.5 billion')
    fact = _fact_unit('nf1', 'Hyperliquid processed $12.5 billion in daily volume.',
                      [{'text': '$12.5 billion', 'metric': 'volume', 'period': None, 'span_ref': 0,
                        'quantity': [['12.5', 'USD']]}])
    other = _news_source(3, 'Fed minutes show hawkish consensus')
    ofact = _fact_unit('of1', 'The Fed minutes show a hawkish consensus.')
    store = FakeStore([_rec(view, xs), _rec(fact, news), _rec(ofact, other)])
    idx = x_support.Index(store, REF, _text, price=False)
    group = [_rec(view, xs)]
    assert x_support.view_only(group, has_valid_view)
    hit = idx.support(group)
    assert hit and hit['kind'] == 'public_fact' and hit['link'] in x_support.LINKS
    assert hit['source']['url'] == 'https://coindesk.com/2' and hit['source']['publisher'] == 'CoinDesk'
    rec = hit['records'][0]
    assert rec['unit_id'] == 'nf1' and rec['support']['source']['url'] == news['url']
    assert rec['unit']['support_source']['publisher'] == 'CoinDesk'
    assert fact.get('support_source') is None                                  # the store row is not mutated
    # citations: only ledger rows that use the support unit, with that unit's own source
    cites = x_support.citations({'claim_ledger': [{'claim': 'vol 12.5B', 'unit_id': 'nf1'},
                                                  {'claim': 'view', 'unit_id': 'xv1'}]}, hit)
    assert cites == [{'claim': 'vol 12.5B', 'unit_id': 'nf1', 'publisher': 'CoinDesk', 'url': news['url'],
                      'published_at': news['published_at']}]


def test_unrelated_public_news_is_not_attached_and_plain_names_do_not_link():
    from live.view_enrich import has_valid_view
    xs = _x_source(1, 'Genius platform keeps draining its best token')
    view = _view_unit('xv1', 'Genius platform keeps draining its best token', subject='Genius platform')
    news = _news_source(2, 'Wells Fargo in talks with Kraken')
    fact = _fact_unit('nf1', 'The GENIUS Act created a federal framework for payment stablecoins.')
    idx = x_support.Index(FakeStore([_rec(view, xs), _rec(fact, news)]), REF, _text, price=False)
    assert idx.support([_rec(view, xs)]) is None
    assert has_valid_view(view)


def test_price_support_only_for_a_known_ticker_the_view_names():
    rows = [[1759880000 - 3600 * i, 0, 0, 0, 80000 + i] for i in range(30)][::-1]
    fetch = {'fetch_crypto': lambda sym, iv, n: {'rows': rows, 'source': 'Binance spot', 'url': 'https://binance.com'},
             'fetch_stock': lambda *a: (_ for _ in ()).throw(AssertionError('no stock fetch'))}
    xs = _x_source(1, 'Bitcoin is just ranging, no need to guess tops')
    view = _view_unit('xv1', 'Bitcoin is just ranging', subject='BTC')
    idx = x_support.Index(FakeStore([_rec(view, xs)]), REF, _text, price=True, fetchers=fetch)
    hit = idx.support([_rec(view, xs)])
    assert hit['kind'] == 'reality_price'
    rec = hit['records'][0]
    line = rec['unit']['source_spans'][0]['exact_text']
    assert line.startswith('BTC 80,000 (Binance spot, as of') and rec['unit']['kind'] == 'fact'
    assert rec['unit']['numbers'][0]['text'] == '80,000' and rec['support']['source']['publisher'] == 'Binance spot'
    # an unknown $CASHTAG (could be an unrelated listing) and a ticker only outside the view get no price
    xs2 = _x_source(2, 'My $DRV thesis is unchanged; also watching BTC')
    view2 = _view_unit('xv2', 'thesis is unchanged', subject='$DRV thesis')
    assert idx.support([_rec(view2, xs2)]) is None


def test_data_packet_needs_a_money_or_percent_number():
    from live.view_enrich import has_valid_view
    xs = _x_source(1, '13 years ago, OKX started as a crypto exchange.')
    years = _fact_unit('f1', 'OKX started 13 years ago.', [{'text': '13 years', 'quantity': [['13', 'number']]}])
    assert not x_support.data_only([_rec(years, xs)], has_valid_view)
    fees = _fact_unit('f2', 'Virtuals earned $2.86M in fees.', [{'text': '$2.86M', 'quantity': [['2.86', 'USD']]}])
    assert x_support.data_only([_rec(fees, xs)], has_valid_view)
    view = _view_unit('v1', 'fees will keep rising')
    assert not x_support.data_only([_rec(fees, xs), _rec(view, xs)], has_valid_view)


def test_own_x_packets_and_plan_fields(dc):
    from live.view_enrich import has_valid_view
    xs = _x_source(1, 'BTC is ranging')
    view = _view_unit('xv1', 'BTC is ranging')
    fs = _x_source(2, 'Virtuals fees')
    fees = _fact_unit('f2', 'Virtuals earned $2.86M in fees.', [{'text': '$2.86M', 'quantity': [['2.86', 'USD']]}])
    ns = _news_source(3, 'Some news')
    news_view = [_rec(_view_unit('nv', 'x'), ns)]                              # not X: never touched

    class Sup:
        def support(self, g):
            return {'kind': 'reality_price', 'link': 'ticker', 'source': {'publisher': 'Binance spot'},
                    'records': [dict(x_support.price_record({'symbol': 'BTC', 'last': 80000.0, 'last_text': '80,000',
                                                             'change_pct': -1.0, 'change_window': '24h',
                                                             'as_of': '2026-10-08T07:00+00:00', 'source': 'Binance spot',
                                                             'url': 'u'}))]}
    out = dc.own_x_packets([[_rec(view, xs)], [_rec(fees, fs)], news_view], Sup())
    assert len(out) == 2
    sup, data = out
    assert dc.packet_kind(sup) == 'supported' and dc.packet_kind(data) == 'data'
    assert dc.support_of(sup)['kind'] == 'reality_price' and dc.support_of(data) is None
    assert has_valid_view(sup[0]['unit']) and sup[1]['unit']['kind'] == 'fact'


def test_compose_one_passes_post_type_and_support_records(dc, monkeypatch):
    seen = {}

    def fake_compose(source, account, client, **kw):
        seen.update(source=source, units=kw['extracted_units'], post_type=kw['post_type'])
        return {'status': 'ok', 'draft_status': 'draft_ready', 'text': 't', 'body': 't',
                'claim_ledger': [{'claim': 'price', 'unit_id': 'price-x'}]}
    monkeypatch.setattr(dc.compose, 'compose_source', fake_compose)

    class C:
        stage_models = {}
        calls = []
    xs = _x_source(1, 'BTC is ranging')
    view = _view_unit('xv1', 'BTC is ranging')
    price = x_support.price_record({'symbol': 'BTC', 'last': 80000.0, 'last_text': '80,000', 'change_pct': None,
                                    'change_window': '24h', 'as_of': '2026-10-08T07:00+00:00',
                                    'source': 'Binance spot', 'url': 'u'})
    price['unit_id'] = price['unit']['unit_id'] = 'price-x'
    pick = {'account_lang': 'en', 'unit_ids': ['xv1'], 'suggested_post_time_london': '2026-10-08T10:00:00+01:00',
            'angle': 'price_structure', 'post_format': {'type': 'quick_take'}, 'support': {'kind': 'reality_price'},
            'support_records': [price], 'post_type': None}
    import threading
    r = dc.compose_one(lambda: C(), 'crypto_macro_en', pick, date(2026, 10, 8), {'xv1': _rec(view, xs)},
                       {'usd': 0.0}, threading.Lock())
    assert [u['unit_id'] for u in seen['units']] == ['xv1', 'price-x']
    assert 'BTC 80,000' in seen['source']['original_text'] and seen['source']['id'] == 'x-1'
    assert seen['post_type'] == 'judgment_take'
    assert r['support_citations'][0]['publisher'] == 'Binance spot'
    pick2 = dict(pick, post_type='data_take', support=None, support_records=[])
    dc.compose_one(lambda: C(), 'crypto_macro_en', pick2, date(2026, 10, 8), {'xv1': _rec(view, xs)},
                   {'usd': 0.0}, threading.Lock())
    assert seen['post_type'] == 'data_take'


def test_compose_eligible_for_supported_and_data_packets(vrc):
    xs = _x_source(1, 'BTC is ranging')
    view = _view_unit('xv1', 'BTC is ranging')
    price = x_support.price_record({'symbol': 'BTC', 'last': 80000.0, 'last_text': '80,000', 'change_pct': -1.2,
                                    'change_window': '24h', 'as_of': '2026-10-08T07:00+00:00',
                                    'source': 'Binance spot', 'url': 'u'})
    _source, units = vrc.evidence_source([_rec(view, xs), price])
    assert not compose.eligible('judgment_take', units[:1])
    assert compose.eligible('judgment_take', units)[0]['unit_id'] == 'xv1'
    fees = _fact_unit('f2', 'Virtuals earned $2.86M in fees.', [{'text': '$2.86M', 'metric': 'fees', 'period': None,
                                                                 'span_ref': 0, 'quantity': [['2.86', 'USD']]}])
    _s, dunits = vrc.evidence_source([_rec(fees, _x_source(2, 'fees'))])
    assert compose.eligible('data_take', dunits)


# ------------------------------------------------------------------ selection prechecks

def test_precheck_drops_horizon_misfit_and_ungated_sources(dc, monkeypatch):
    xs = _x_source(1, 'BTC view')
    ok = [_rec(_view_unit('v1', 'BTC is ranging', horizon='weeks'), xs), _rec(_fact_unit('f1', 'fact'), xs)]
    far = [_rec(_view_unit('v2', 'BTC in ten years', horizon='years'), xs), _rec(_fact_unit('f2', 'fact'), xs)]
    legacy = [_rec(dict(_view_unit('v3', 'x'), view=None), xs), _rec(_fact_unit('f3', 'fact'), xs)]
    monkeypatch.setattr(dc, 'source_gate_ok', lambda a, g: True)
    diag = {}
    kept = dc.precheck('crypto_trader_zh', [ok, far, legacy], diag)          # persona horizon: days
    assert kept == [ok] and diag == {'no_stance_ready_view': 2}
    monkeypatch.setattr(dc, 'source_gate_ok', lambda a, g: False)
    diag = {}
    assert dc.precheck('crypto_trader_zh', [ok], diag) == [] and diag == {'source_gate': 1}
    data = [_rec(_fact_unit('f9', 'fees $2.86M', [{'text': '$2.86M', 'quantity': [['2.86', 'USD']]}]), xs)]
    monkeypatch.setattr(dc, 'source_gate_ok', lambda a, g: True)
    assert dc.precheck('crypto_trader_zh', [data]) == [data]                 # a data packet needs no view


def test_pick_units_prefers_structured_compatible_view_over_legacy():
    legacy = dict(_view_unit('v_legacy', 'x'), view=None)
    good = _view_unit('v_good', 'BTC is ranging', horizon='days')
    fact = _fact_unit('f', 'BTC fell 2%.', [{'text': '2%', 'quantity': [['2', 'percent']]}])
    chosen = compose.pick_units('judgment_take', [legacy, good, fact], account_id='crypto_trader_zh')
    assert compose.eligible('judgment_take', chosen)[0]['unit_id'] == 'v_good'


def test_source_gate_precheck_matches_compose_gate(dc):
    g = [_rec(_fact_unit('f', 'x'), {'id': 's', 'source_id': 'ch142_wscn_global', 'publisher': '华尔街见闻',
                                    'title': '10年期美债拍卖认购倍数2.77倍', 'source_language': 'zh'})]
    assert dc.source_gate_ok('investing_philosophy', g) is False


# ------------------------------------------------------------------ stance contract retry / relay transport retry

class _Persona:
    def __init__(self):
        self.raw = {'stance': {'horizon': 'weeks', 'prior': 'x', 'risk_appetite': 'high', 'beliefs': [], 'rejects': []},
                    'lang': 'en'}


def _stance_answer(view, text):
    return {'text': json.dumps({'decision': 'take', 'account_view': text, 'supporting_unit_ids': [view['unit_id']],
                                'rationale': 'r', 'confidence': 0.7}), 'finish_reason': 'stop'}


def test_stance_contract_error_gets_one_targeted_retry():
    from live.stance import stance_step
    view = _view_unit('v1', 'BTC is ranging')
    answers = [_stance_answer(view, 'BTC is ranging. It will break out.'), _stance_answer(view, 'BTC is ranging.')]
    sent = []

    def client(stage, messages, max_tokens):
        sent.append(json.dumps(messages, ensure_ascii=False))
        return answers.pop(0)
    value = stance_step(view, _Persona(), client, sleep=lambda s: None)
    assert value['account_view'] == 'BTC is ranging.' and len(sent) == 2
    assert 'one judgment sentence required' in value['stance_contract_retry']['first_error']
    assert '[stance_contract]' in sent[1]


def test_stance_contract_error_twice_is_reported():
    from live.stance import stance_step
    view = _view_unit('v1', 'BTC is ranging')
    answers = [_stance_answer(view, 'A. B.'), _stance_answer(view, 'C. D.')]
    with pytest.raises(ContractError, match='one judgment sentence'):
        stance_step(view, _Persona(), lambda *a: answers.pop(0), sleep=lambda s: None)


def test_relay_transport_failure_retries_once_with_backoff():
    sleeps, n = [], {'calls': 0}

    def flaky(stage, messages, max_tokens):
        n['calls'] += 1
        if n['calls'] == 1:
            raise RuntimeError('Relay transport failed: ReadTimeout')
        return {'text': '{"ok": true}', 'finish_reason': 'stop'}
    calls = []
    value, _ = compose._ask(flaky, 'compose', 'sys', {'a': 1}, 100, calls, sleep=sleeps.append)
    assert value == {'ok': True} and n['calls'] == 2 and sleeps == [compose.TRANSPORT_BACKOFF_S]
    assert calls[0]['transport_retries']

    def dead(*a):
        raise RuntimeError('Relay transport failed: ReadTimeout')
    with pytest.raises(RuntimeError, match='ReadTimeout'):
        compose._ask(dead, 'compose', 'sys', {'a': 1}, 100, [], sleep=lambda s: None)


def test_quota_regex_covers_relay_balance_and_official_402(dc):
    assert dc.QUOTA_RX.search("ProviderQuotaError: Relay HTTP 403: {'message': '用户额度不足, 剩余额度: ¥-0.0005'}")
    assert dc.QUOTA_RX.search('insufficient_user_quota')
    assert dc.QUOTA_RX.search('Your prepayment credits are depleted')
    assert not dc.QUOTA_RX.search('ContractError: stance: one judgment sentence required')


# ------------------------------------------------------------------ arbitration

def test_same_language_arbitration_keeps_one_per_language():
    from live import claim_arbitration as ca

    def cand(aid, view):
        return {'key': aid, 'account_id': aid, 'subject': 'wells fargo kraken liquidity', 'direction': 'bullish',
                'account_view': view, 'source_id': 's1', 'day': '2026-10-08'}
    cands = [cand('btc_cycles_en', 'Banks are coming for crypto liquidity.'),
             cand('crypto_research_zh', '银行开始抢加密流动性。'), cand('crypto_onchain_zh', '银行入场加密流动性。')]
    old = {d['account_id']: d['status'] for d in ca.arbitrate(cands)}
    assert list(old.values()).count('WRITE') == 1                              # cross-language: one keeper in all
    new = {d['account_id']: d['status'] for d in ca.arbitrate(cands, same_language=True)}
    assert new['btc_cycles_en'] == 'WRITE'
    assert sorted([new['crypto_research_zh'], new['crypto_onchain_zh']]) == ['HOLD', 'WRITE']


# ------------------------------------------------------------------ fill rounds

def test_tried_sources_skip_everything_but_budget_and_quota_stops(dc, tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'RUNS', tmp_path)
    d = tmp_path / '2026-10-08' / 'r1' / 'drafts'
    d.mkdir(parents=True)
    rows = [('a', 's_ns', {'draft_status': 'not_suitable', 'status': 'skipped'}),
            ('a', 's_budget', {'error': 'budget: distillation call would exceed configured spending cap'}),
            ('a', 's_quota', {'error': "ProviderQuotaError: Relay HTTP 403: 用户额度不足"}),
            ('a', 's_err', {'error': 'StopIteration: '}),
            ('b', 's_ready', {'draft_status': 'draft_ready'})]
    for i, (acct, sid, extra) in enumerate(rows):
        (d / f'{i}.json').write_text(json.dumps({'account_id': acct, 'plan': {'source_id': sid, 'title': sid + 't',
                                                                              'source_key': [sid + 'h', sid]},
                                                 'source': {'id': sid}, **extra}))
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day: [{'account_id': 'b', 'source': {'id': 's_held'}}])
    out = dc.tried_sources(date(2026, 10, 8), keep={'a': {'s_err'}})
    assert out['a'] == {'s_ns', 's_nst', 's_nsh'}                              # s_err kept: a rewrite target
    assert {'s_ready', 's_held'} <= out['b']


def test_main_loops_fill_rounds_until_targets_or_no_candidates(dc, monkeypatch, tmp_path):
    monkeypatch.setattr(dc, 'RUNS', tmp_path)
    monkeypatch.setattr(dc, 'DASHBOARD', tmp_path / 'dash')
    monkeypatch.setenv('FD_DAILY_COMPOSE', '1')
    monkeypatch.setenv('SUBROUTER_API_KEY', 'test-key')   # Oct 11 guard: no key = refuse to start
    monkeypatch.setenv('FD_ARCHIVE', '0')
    monkeypatch.setenv('FD_FILL_ROUNDS', '3')
    accts = [{'id': 'a', 'lang': 'en'}, {'id': 'b', 'lang': 'en'}]
    monkeypatch.setattr(dc, 'load_json', lambda p: {'accounts': accts} if 'fd20' in str(p) else {'a': {}, 'b': {}})
    monkeypatch.setattr(dc.fd_accounts, 'rows', lambda path=None, env=None: list(accts))   # Oct 8: roster reader
    monkeypatch.setattr(dc, 'UNIVERSES', tmp_path / 'u.json')
    (tmp_path / 'u.json').write_text('{}')
    ready = {'a': 0, 'b': 0}
    monkeypatch.setattr(dc, 'drafted_today', lambda day, ready_only=False: dict(ready))
    seen = []

    def fake_round(args, accts_r, all_accounts, universes, per_account, fill, rnd, state):
        seen.append(([a['id'] for a in accts_r], fill))
        planned = 0
        for a in accts_r:
            if a['id'] == 'a' or rnd == 0:            # 'b' runs out of candidates after the first round
                ready[a['id']] += 1
                planned += 1
                state['tally'][a['id']]['ready'] += 1
            state['last'][a['id']] = {'round': rnd, 'picks': 1 if (a['id'] == 'a' or rnd == 0) else 0, 'pool': 0,
                                      'skipped_tried': 3}
        state['run_ids'].append(f'r{rnd}')
        out = tmp_path / f'r{rnd}'
        out.mkdir(exist_ok=True)
        return out, {'day': '2026-10-08'}, planned
    monkeypatch.setattr(dc, 'run_round', fake_round)
    monkeypatch.setattr(sys, 'argv', ['daily_compose.py', '--day', '2026-10-08', '--per-account', '2'])
    import backend.compose_inbox as bci
    monkeypatch.setattr(bci, 'render', lambda *a, **k: '')
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day: [])
    assert dc.main() == 0
    assert seen[0] == (['a', 'b'], False) and seen[1] == (['a', 'b'], True)
    status = json.loads((tmp_path / 'r2' / 'fill_status.json').read_text())
    assert status['accounts']['a']['stopped'] == 'reached'
    assert status['accounts']['b']['stopped'].startswith('no_candidates')
    assert seen[2] == (['b'], True) and len(seen) == 3                        # 'b' alone, no picks -> stop


def test_fill_status_reasons(dc, monkeypatch):
    state = {'quota': {}, 'tally': {'a': Counter({'skipped:budget': 1}), 'b': Counter(), 'c': Counter()},
             'last': {'a': {'round': 1, 'picks': 1}, 'b': {'round': 3, 'picks': 1}, 'c': {'round': 0, 'picks': 2}},
             'run_ids': ['r'], 'spend': {'usd': 1.0}}
    monkeypatch.setattr(dc, 'drafted_today', lambda day, ready_only=False: {'c': 2})
    st = dc.fill_status(date(2026, 10, 8), [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}], 2, state, 4)
    assert st['accounts']['a']['stopped'] == 'budget'
    assert st['accounts']['b']['stopped'] == 'max_rounds'
    assert st['accounts']['c']['stopped'] == 'reached' and st['short'] == ['a', 'b']
    state['quota'] = {'reason': 'Gemini quota / balance exhausted: 用户额度不足'}
    st = dc.fill_status(date(2026, 10, 8), [{'id': 'a'}], 2, state, 4)
    assert st['accounts']['a']['stopped'].startswith('quota')


# ------------------------------------------------------------------ flags off

def test_flags_off_leave_candidates_unchanged(dc, monkeypatch):
    monkeypatch.setenv('FD_X_SUPPORT', '0')
    monkeypatch.setenv('FD_X_DATA', '0')
    assert dc.support_index(None, REF) is None


def test_review_page_shows_the_support_citation():
    from backend.compose_inbox import render
    row = {'id': 'd1', 'account_id': 'a', 'text': 'body', 'source': {'publisher': '@x', 'title': 't'},
           'support': {'kind': 'reality_price', 'source': {'publisher': 'Binance spot', 'title': 'BTC 80,000 (...)',
                                                            'published_at': '2026-10-08T07:00+00:00', 'url': 'u'}},
           'support_citations': [{'unit_id': 'p'}]}
    page = render([row], '2026-10-08')
    assert '补充事实（实时价格，正文引用了）' in page and 'Binance spot' in page


def test_chain_and_token_names_are_not_jargon():
    from live.draft_qa import readability_findings
    assert readability_findings('Shoving TRON liquidity onto Polygon; STG and HYPE rallied.') == []
    found = readability_findings('CVD is falling while QXZT pumps.')
    assert found and 'CVD' in found[0]['detail'] and 'QXZT' in found[0]['detail']
