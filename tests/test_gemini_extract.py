"""EXTRACT routing. Shipped (Oct 7, v3): gemini-3-flash-preview on the official Gemini API, no fallback.
The Oct 6 fallback machinery (gemini-3.1-pro-preview on micuapi -> claude-opus-5 at its full 12000 max_tokens)
runs against the frozen v2 table in tests/fixtures. Also placeholder-speaker normalization, persona_minimum slots in the budget window, and the
fit estimate in daily_ingest / ingest_order_preview. No network: MockTransport and injected fakes only."""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from live import stage_models
from ml import budget

MSG = [{'role': 'user', 'content': 'x'}]
V2 = Path(__file__).parent / 'fixtures' / 'stage_models_v2_micuapi.json'
GEMINI = 'https://generativelanguage.googleapis.com/v1beta'
FAKE_GEMINI_ENV = 'prefix-AQ.fakeTOKEN123'
RELAY = {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'default-key', 'model': 'claude-opus-5',
         'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv('GEMINI_RELAY_API_KEY', 'gem-key')
    monkeypatch.setenv('GEMINI_API_KEY', FAKE_GEMINI_ENV)
    for k in [k for k in os.environ if k.startswith(('FD_EXTRACT_', 'FD_COMPOSE_', 'FD_STANCE_', 'FD_GEMINI_',
                                                     'FD_VIEW_ENRICH_'))]:
        monkeypatch.delenv(k)
    prices = budget.PRICES.copy()
    yield
    budget.PRICES.clear(); budget.PRICES.update(prices)


# --- stage_models -----------------------------------------------------------------------------------

def test_shipped_extract_is_flash_on_official_gemini_without_fallback():
    table = stage_models.load()
    assert stage_models.for_stage(table, 'extract')['model'] == 'gemini-3-flash-preview'
    assert stage_models.route(table, 'extract') == {'base_url': GEMINI, 'api_key_env': 'GEMINI_API_KEY'}
    assert stage_models.fallback(table, 'extract') is None
    assert stage_models.fallback(table, 'compose') is None
    assert stage_models.max_tokens(table, 'extract') == 24000


def test_extract_stage_loads_with_fallback_max_tokens():
    table = stage_models.load(V2)
    assert stage_models.for_stage(table, 'extract')['model'] == 'gemini-3.1-pro-preview'
    assert stage_models.route(table, 'extract')['api_key_env'] == 'GEMINI_RELAY_API_KEY'
    fb = stage_models.fallback(table, 'extract')
    assert fb['model'] == 'claude-opus-5' and fb['max_tokens'] == 12000
    assert stage_models.fallback(table, 'compose')['max_tokens'] is None


@pytest.mark.parametrize('bad', [0, -1, True, '5'])
def test_invalid_fallback_max_tokens_rejected(bad):
    table = stage_models.load(V2)
    table['stages']['extract']['fallback']['max_tokens'] = bad
    with pytest.raises(ValueError, match='max_tokens'):
        stage_models.validate(table)


def test_env_reverts_extract_to_opus():
    table = stage_models.from_env(stage_models.load(), {'FD_EXTRACT_MODEL': 'claude-opus-5'})
    assert stage_models.for_stage(table, 'extract')['model'] == 'claude-opus-5'
    assert stage_models.route(table, 'extract') is None
    assert stage_models.fallback(table, 'extract') is None


# --- relay client fallback --------------------------------------------------------------------------

def _ok(model):
    return httpx.Response(200, json={'id': 'r', 'model': model,
                                     'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})


@pytest.fixture
def relay_client(tmp_path, monkeypatch):
    from live.erisedai_distillation_client import ErisedaiClient
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 2.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append((request.url.host, body['model'], body.get('max_tokens')))
        if request.url.host == 'www.micuapi.ai':
            return httpx.Response(503, json={'error': {'message': 'busy'}})
        return _ok(body['model'])
    with patch('live.erisedai_distillation_client._dotenv', return_value={}):
        client = ErisedaiClient(tmp_path / 'calls', configuration=dict(RELAY, stage_models=stage_models.load(V2)),
                                transport=httpx.MockTransport(handle))
    return client, seen


def test_extract_503_falls_back_to_opus_with_full_max_tokens(relay_client):
    from live import erisedai_distillation_client as relay
    from live.daily_ingest import extract_fallbacks
    client, seen = relay_client
    out = client('extract', MSG, 12000)
    # Gemini primary gets the stage's own ceiling (reasoning tokens count toward it); opus fallback keeps 12000
    assert seen[0] == ('www.micuapi.ai', 'gemini-3.1-pro-preview', 24000)
    assert seen[1] == ('api.erisedai.com', 'claude-opus-5', 12000)
    assert 12000 != relay.FALLBACK_MAX_TOKENS
    assert out['model_fallback'] and '503' in out['fallback_reason']
    stats = extract_fallbacks(client)
    assert stats['fallback'] == 1 and stats['calls'] >= 1


@pytest.mark.parametrize('bad', [0, -5, True, '24000'])
def test_invalid_stage_max_tokens_rejected(bad):
    table = copy.deepcopy(stage_models.load())
    table['stages']['extract']['max_tokens'] = bad
    with pytest.raises(ValueError, match='max_tokens'):
        stage_models.validate(table)


def test_stage_max_tokens_only_where_configured():
    table = stage_models.load(V2)
    assert stage_models.max_tokens(table, 'extract') == 24000
    assert stage_models.max_tokens(table, 'compose') is None and stage_models.max_tokens(table, 'stance') is None
    shipped = stage_models.load()
    assert stage_models.max_tokens(shipped, 'extract') == 24000 and stage_models.max_tokens(shipped, 'extract_flash') == 24000
    assert stage_models.max_tokens(shipped, 'compose') == 16000 and stage_models.max_tokens(shipped, 'stance') == 16000
    assert stage_models.max_tokens(shipped, 'qa') is None


def test_compose_fallback_still_clamped(relay_client):
    from live import erisedai_distillation_client as relay
    client, seen = relay_client
    client('compose', MSG, 12000)
    assert seen[-1][1] == 'claude-opus-5-5' and seen[-1][2] == relay.FALLBACK_MAX_TOKENS


# --- extract_client ---------------------------------------------------------------------------------

def test_extract_client_models(tmp_path, monkeypatch):
    from live import daily_ingest
    monkeypatch.setattr(daily_ingest, '_relay_config', lambda: dict(RELAY))
    c = daily_ingest.extract_client(tmp_path / 'a')
    assert stage_models.for_stage(c.stage_models, 'extract')['model'] == 'gemini-3-flash-preview'
    assert stage_models.route(c.stage_models, 'extract')['api_key_env'] == 'GEMINI_API_KEY'
    opus = daily_ingest.extract_client(tmp_path / 'b', model='claude-opus-5')
    assert stage_models.for_stage(opus.stage_models, 'extract')['model'] == 'claude-opus-5'
    assert stage_models.route(opus.stage_models, 'extract') is None
    with pytest.raises(ValueError, match='allow'):
        daily_ingest.extract_client(tmp_path / 'c', model='claude-sonnet-5')
    daily_ingest.extract_client(tmp_path / 'd', model='claude-sonnet-5', allow_nondefault=True)


def test_extract_fallbacks_counts_records(tmp_path):
    from types import SimpleNamespace
    from live.daily_ingest import extract_fallbacks
    paths = []
    for i, rec in enumerate([{'model_fallback': True, 'fallback_reason': 'HTTP 503'}, {}, {'model_fallback': True,
                                                                                          'fallback_reason': 'HTTP 503'}]):
        p = tmp_path / f'{i}.json'; p.write_text(json.dumps(rec)); paths.append(p)
    calls = [dict(stage='extract', path=str(p)) for p in paths] + [dict(stage='compose', path=str(paths[0]))]
    out = extract_fallbacks(SimpleNamespace(calls=calls))
    assert out['calls'] == 3 and out['fallback'] == 2 and out['reasons'] == {'HTTP 503': 2}


# --- speaker normalization --------------------------------------------------------------------------

@pytest.mark.parametrize('speaker,publisher,author,expected,normalized', [
    ('media', '华尔街见闻', None, '华尔街见闻', True),
    ('Unknown', '华尔街见闻', 'Jane Doe', '华尔街见闻', True),
    ('the author', None, 'Jane Doe', 'Jane Doe', True),
    ('Jerome Powell', '华尔街见闻', None, 'Jerome Powell', False),
    ('media', None, None, 'media', False),
])
def test_placeholder_speaker_normalized(speaker, publisher, author, expected, normalized):
    from live import content_units as cu
    from live.adapters.common import make_source
    text = '美联储维持利率不变，市场预期年内降息两次。'
    src = make_source(id='s1', source_id='test_speaker_src', text=text, publisher=publisher or '',
                      title='t', url='https://example.test/s1', published_at='2026-10-06', adapter='test')
    src['author_name'] = author
    pid = cu.paragraphs(text)[0]['paragraph_id']
    unit = {'kind': 'fact', 'statement': text, 'source_spans': [{'paragraph_id': pid, 'exact_text': text}],
            'numbers': [], 'speaker': speaker, 'speaker_type': 'media', 'freshness_class': 'current'}

    def client(stage, messages, max_tokens):
        return {'text': json.dumps({'units': [unit]}, ensure_ascii=False), 'finish_reason': 'stop', 'model': 'm'}
    out = cu.extract(src, client, licence_tier='B', publisher=publisher)['units'][0]
    assert out['speaker'] == expected
    assert out.get('speaker_normalized', False) is normalized


# --- persona_minimum ordering -----------------------------------------------------------------------

def _task(channel, sid, rank=0, units=None):
    return ({'id': channel}, {'id': sid, 'source_id': channel}, units, channel, [sid], rank)


@pytest.fixture
def ip(monkeypatch):
    from live import ingest_priority
    hints = {'chA': ['macro_rates_en'], 'chB': ['crypto_macro_en'], 'chC': ['crypto_macro_zh'], 'chD': ['equity_zh']}
    monkeypatch.setattr(ingest_priority, 'channel_personas', lambda cid, s=None: hints.get(cid, [ingest_priority.UNKNOWN]))
    monkeypatch.setattr(ingest_priority, 'timeliness', lambda cid, s=None: 'standard')
    return ingest_priority


FRESH = {'macro_rates_en': 10, 'crypto_macro_en': 20, 'crypto_macro_zh': 30, 'equity_zh': 40}


def _ids(order):
    return [t[1]['id'] for t in order]


def test_persona_minimum_gets_one_slot_window_stays_fit(ip):
    tasks = [_task('chA', f'a{i}', i) for i in range(4)] + [_task('chB', 'b0'), _task('chC', 'c0'),
                                                            _task('chX', 'x0', units=[{'u': 1}])]
    base, _ = ip.order_tasks(tasks, FRESH, floor=0, legacy_priority=lambda c, s: 3)
    assert _ids(base) == ['x0', 'a0', 'a1', 'a2', 'a3', 'b0', 'c0']
    order, plan = ip.order_tasks(tasks, FRESH, floor=0, legacy_priority=lambda c, s: 3, fit=3)
    ids = _ids(order)
    assert ids[0] == 'x0' and plan[0]['phase'] == 'pre_extracted'
    # window still 3 (a2 then a1 pushed out); minimums (fewest-fresh first) sit ahead of the non-timely a0
    assert ids[1:4] == ['b0', 'c0', 'a0']
    assert ids[4:] == ['a1', 'a2', 'a3']                   # pushed-out keep their order, right after the window
    assert [r['phase'] for r in plan[1:3]] == ['persona_minimum', 'persona_minimum']
    assert sorted(ids) == sorted(_ids(tasks))


def test_persona_minimum_never_pushes_last_item_of_a_persona(ip):
    tasks = [_task('chA', 'a0'), _task('chB', 'b0'), _task('chC', 'c0'), _task('chD', 'd0')]
    base, _ = ip.order_tasks(tasks, FRESH, floor=1, legacy_priority=lambda c, s: 3)
    assert _ids(base) == ['a0', 'b0', 'c0', 'd0']
    order, plan = ip.order_tasks(tasks, FRESH, floor=1, legacy_priority=lambda c, s: 3, fit=2)
    assert _ids(order) == ['a0', 'b0', 'c0', 'd0']       # every window item is its persona's only one
    assert not [r for r in plan if r['phase'] == 'persona_minimum']
    # two missing personas, one free slot: the fewest-fresh persona (crypto_macro_zh) wins
    tasks = [_task('chA', 'a0', 0), _task('chA', 'a1', 1), _task('chB', 'b0'), _task('chD', 'd0'), _task('chC', 'c0')]
    order, plan = ip.order_tasks(tasks, FRESH, floor=0, legacy_priority=lambda c, s: 3, fit=3)
    assert _ids(order)[:3] == ['c0', 'a0', 'b0']
    assert [r['persona'] for r in plan if r['phase'] == 'persona_minimum'] == ['crypto_macro_zh']


def test_persona_minimum_stays_behind_timely_items(ip, monkeypatch):
    monkeypatch.setattr(ip, 'timeliness', lambda cid, s=None: 'timely' if cid == 'chA' else 'standard')
    tasks = [_task('chA', f'a{i}', i) for i in range(3)] + [_task('chB', 'b0')]
    order, plan = ip.order_tasks(tasks, FRESH, floor=0, legacy_priority=lambda c, s: 3, fit=3)
    assert _ids(order) == ['a0', 'a1', 'b0', 'a2']
    assert [r['phase'] for r in plan] == ['timely', 'timely', 'persona_minimum', 'timely']


def test_persona_minimum_fit_none_or_large_unchanged(ip):
    tasks = [_task('chA', f'a{i}', i) for i in range(4)] + [_task('chB', 'b0'), _task('chC', 'c0')]
    base, base_plan = ip.order_tasks(tasks, FRESH, floor=2, legacy_priority=lambda c, s: 3)
    for fit in (None, 6, 10, 0):
        order, plan = ip.order_tasks(tasks, FRESH, floor=2, legacy_priority=lambda c, s: 3, fit=fit)
        assert _ids(order) == _ids(base) and plan == base_plan


# --- preview ----------------------------------------------------------------------------------------

def test_preview_uses_per_extract_and_max_extract(tmp_path, monkeypatch):
    from scripts import ingest_order_preview as iop
    monkeypatch.setattr(iop.ingest_priority, 'timeliness', lambda cid, s=None: 'standard')
    summary = {'cost_usd': {'cap': 8.0, 'relay': 7.5}, 'steps': [{'id': 'extract', 'extracted': 9}],
               'fresh_by_persona_after': {}, 'deferred': [{'id': f'd{i}', 'channel': f'chz{i % 3}'} for i in range(20)]}
    path = tmp_path / 's.json'; path.write_text(json.dumps(summary))
    p = iop.preview(path, per_extract=0.5, max_extract=40)
    assert p['usd_per_extract'] == 0.5 and p['budget_fit'] == int((8.0 - 1.75) // 0.5)
    assert p['extracts_within_cap'] == min(40, p['budget_fit'])
    p = iop.preview(path, per_extract=0.1, max_extract=5)
    assert p['budget_fit'] == 62 and p['extracts_within_cap'] == 5
    assert sum(r['within_cap'] for r in p['plan']) == 5
    assert p['extract_model'] == 'gemini-3-flash-preview' and 'persona_minimum' in p
    default = iop.preview(path)
    assert default['usd_per_extract'] == 0.03       # stage_models.json est, not 7.5 / 9
    assert 'budget fits' in iop.to_md(p)


# --- daily_ingest.run -------------------------------------------------------------------------------

def _run_args(tmp_path, **kw):
    return dict(store=tmp_path / 'store', runs_dir=tmp_path / 'runs', inbox=tmp_path / 'inbox',
                state_path=tmp_path / 'state.json', no_dashboard=True, **kw)


def _extract(s):
    return [{'unit_id': s['id'], 'source_hash': s['source_hash'], 'statement': s['original_text'], 'kind': 'fact',
             'numbers': [], 'licence_tier': 'A', 'usage': 'quote', 'speaker': s['publisher']}]


def _fetchers():
    from live.adapters.common import make_source
    src = make_source(id='g1', source_id='sec_edgar', text='g1 distinct evidence', publisher='g1', title='g1',
                      url='https://example.test/g1', published_at='2026-10-04', adapter='edgar')
    return {'good': lambda: {'sources': [src]}}


def test_run_records_fit_estimate(tmp_path):
    import inspect
    from live.daily_ingest import run, DEFAULT_EST_USD_PER_DOC
    cap = inspect.signature(run).parameters['cost_cap_usd'].default   # the run() default daily cap
    r = run(**_run_args(tmp_path), fetchers=_fetchers(), extract=_extract, backup=lambda: None, refresh=lambda: None)
    fe = r['ordering']['fit_estimate']
    # flashes keep their ring-fenced $1.75 inside the default cap.
    assert fe['est_usd_per_doc'] == DEFAULT_EST_USD_PER_DOC and fe['docs_budget_usd'] == round(cap - 1.75, 4)
    assert fe['fit'] == min(40, int((cap - 1.75) // DEFAULT_EST_USD_PER_DOC))
    assert r['ordering']['persona_minimum'] == []
    r = run(**_run_args(tmp_path / 'b', est_usd_per_doc=0.1, flashes=False, max_extract=30), fetchers=_fetchers(),
            extract=_extract, backup=lambda: None, refresh=lambda: None)
    fe = r['ordering']['fit_estimate']
    assert fe['docs_budget_usd'] == cap and fe['fit'] == 30


def test_run_persona_minimum_off(tmp_path):
    from live.daily_ingest import run
    r = run(**_run_args(tmp_path, persona_minimum=False), fetchers=_fetchers(), extract=_extract,
            backup=lambda: None, refresh=lambda: None)
    assert r['ordering']['fit_estimate'] is None and r['ordering']['persona_minimum'] == []


def test_cli_flag():
    import scripts.daily_ingest as cli
    import inspect
    assert '--no-persona-minimum' in inspect.getsource(cli)


def test_preflight_reports_extract_route(monkeypatch):
    from scripts import daily_ingest_preflight as preflight
    with patch('live.writer_backend._dotenv', return_value={}):
        out = preflight.extract_route()
        assert out['extract_model'] == 'gemini-3-flash-preview' and out['extract_key'] == 'set'
        assert out['extract_fallback'] is None and out['extract_host'] == 'generativelanguage.googleapis.com'
        assert 'fakeTOKEN' not in json.dumps(out)
        monkeypatch.setenv('GEMINI_API_KEY', 'no-token-here')     # value without an AQ. token is unusable
        assert 'missing' in preflight.extract_route()['extract_key']
        monkeypatch.delenv('GEMINI_API_KEY')
        assert preflight.extract_route()['extract_key'] == 'GEMINI_API_KEY missing'
