"""Oct 8: subrouter (flat-rate) is the primary Gemini provider when SUBROUTER_API_KEY is set; micuapi is the automatic
same-model fallback; subrouter calls are ledgered (provider=subrouter, nominal cost) but never count toward a cap."""
import json
import os

import httpx
import pytest

from live import stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget

SUB_KEY = 'sk-subrouter-secret-abcdef123'
MICU_KEY = 'sk-micu-secret-654321'
ENV = {'SUBROUTER_API_KEY': SUB_KEY}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 0.001, 'spent_usd': 0.0, 'calls': 0}))   # cap already "exhausted"
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(budget, 'RUNS', tmp_path / 'review_runs.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.setenv('GEMINI_RELAY_API_KEY', MICU_KEY)
    monkeypatch.setenv('SUBROUTER_API_KEY', SUB_KEY)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    for name in [k for k in os.environ if k.startswith('FD_')]:
        monkeypatch.delenv(name)
    relay.reset_quota_breaker()
    prices = budget.PRICES.copy()
    yield
    relay.reset_quota_breaker()
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def config(env=ENV):
    return {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
            'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
            'stage_models': stage_models.from_env(stage_models.load(), env)}


def ok(model):
    return httpx.Response(200, json={'id': 'x', 'model': model,
                                     'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 1000, 'completion_tokens': 2000}})


def test_provider_selection():
    sub = stage_models.from_env(stage_models.load(), ENV)
    for stage in ('compose', 'stance', 'extract', 'extract_flash', 'view_enrich'):
        assert stage_models.route(sub, stage) == {'base_url': 'https://subrouter.ai/v1', 'api_key_env': 'SUBROUTER_API_KEY'}
        fb = stage_models.fallback(sub, stage)
        assert fb['provider_fallback'] and fb['base_url'] == stage_models.GEMINI_RELAY_BASE
        assert stage_models.model_fallback(sub, stage) is None
    assert stage_models.for_stage(sub, 'compose')['model'] == 'gemini-3.1-pro-preview'
    assert stage_models.fallback(sub, 'compose')['model'] == 'gemini-3.1-pro-preview'
    # subrouter has no gemini-3-flash-preview id: GA gemini-3-flash on subrouter, the preview id on micuapi
    assert stage_models.for_stage(sub, 'stance')['model'] == 'gemini-3-flash'
    assert stage_models.fallback(sub, 'stance')['model'] == 'gemini-3-flash-preview'
    assert stage_models.max_tokens(sub, 'extract') == 24000 and stage_models.fallback(sub, 'extract')['max_tokens'] == 24000
    # no key -> micuapi only (unchanged); explicit relay wins over the key
    for env in ({}, {**ENV, 'FD_GEMINI_PROVIDER': 'relay'}):
        t = stage_models.from_env(stage_models.load(), env)
        assert stage_models.route(t, 'compose')['base_url'] == stage_models.GEMINI_RELAY_BASE
        assert stage_models.fallback(t, 'compose') is None


def test_subrouter_serves_and_does_not_count_toward_cap(tmp_path):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((str(request.url), request.headers.get('authorization'), body['model'], body.get('reasoning_effort')))
        return ok(body['model'])
    client = ErisedaiClient(tmp_path / 'calls', configuration=config(), transport=httpx.MockTransport(handler))
    out = client('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert seen == [('https://subrouter.ai/v1/chat/completions', 'Bearer ' + SUB_KEY, 'gemini-3.1-pro-preview', 'medium')]
    assert out['serving_provider'] == 'subrouter' and not out['model_fallback'] and not out['provider_fallback']
    rec = json.loads(next((tmp_path / 'calls').glob('*.json')).read_text())
    assert rec['provider'] == 'subrouter' and rec['cost_counts_toward_cap'] is False
    assert rec['estimated_cost_usd'] == 0.0 and rec['nominal_cost_usd'] > 0
    d = json.loads(budget.LEDGER.read_text())
    assert d['spent_usd'] == 0.0 and d['flat_rate_nominal_usd'] == pytest.approx(rec['nominal_cost_usd'])
    assert d['by_provider']['subrouter']['calls'] == 1 and d['by_provider']['subrouter']['completion_tokens'] == 2000
    line = json.loads(budget.DISTILLATION_RUNS.read_text().splitlines()[0])
    assert line['provider'] == 'subrouter' and line['counts_toward_cap'] is False
    for p in list((tmp_path / 'calls').glob('*.json')) + [budget.LEDGER, budget.DISTILLATION_RUNS]:
        assert SUB_KEY not in p.read_text() and MICU_KEY not in p.read_text()
    budget.recost()
    assert json.loads(budget.LEDGER.read_text())['spent_usd'] == 0.0


@pytest.mark.parametrize('status', [429, 503, 500, 401, 403])
def test_errors_fall_back_to_micuapi_same_model_and_count(tmp_path, status):
    budget.set_cap(10.0)
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == 'subrouter.ai':
            return httpx.Response(status, json={'error': {'message': 'nope'}})
        return ok(json.loads(request.content)['model'])
    client = ErisedaiClient(tmp_path / 'calls', configuration=config(), transport=httpx.MockTransport(handler))
    out = client('stance', [{'role': 'user', 'content': 'hi'}], 1000)
    assert hosts == ['subrouter.ai', 'www.micuapi.ai']
    assert out['response_model'] == 'gemini-3-flash-preview' and out['serving_provider'] == 'micuapi'
    assert out['provider_fallback'] and not out['model_fallback']   # DraftClient accepts it (same Gemini model)
    d = json.loads(budget.LEDGER.read_text())
    assert d['spent_usd'] > 0   # the paid micuapi fallback counts
    recs = [json.loads(p.read_text()) for p in (tmp_path / 'calls').glob('*.json')]
    fb = [r for r in recs if r['host'] == 'www.micuapi.ai'][0]
    assert fb['cost_counts_toward_cap'] is True and fb['estimated_cost_usd'] > 0


def test_transport_error_falls_back_and_breaker_opens(tmp_path):
    budget.set_cap(10.0)
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == 'subrouter.ai':
            raise httpx.ConnectError('down')
        return ok(json.loads(request.content)['model'])
    client = ErisedaiClient(tmp_path / 'calls', configuration=config(), transport=httpx.MockTransport(handler))
    for _ in range(relay.PROVIDER_BREAKER_FAILS + 1):
        client('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert hosts.count('subrouter.ai') == relay.PROVIDER_BREAKER_FAILS   # last call skipped subrouter
    assert hosts.count('www.micuapi.ai') == relay.PROVIDER_BREAKER_FAILS + 1


def test_missing_micuapi_key_runs_subrouter_alone(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_RELAY_API_KEY')
    client = ErisedaiClient(tmp_path / 'calls', configuration=config(),
                            transport=httpx.MockTransport(lambda r: httpx.Response(503, json={'error': {'message': 'x'}})))
    with pytest.raises(RuntimeError, match='Relay HTTP 503'):
        client('compose', [{'role': 'user', 'content': 'hi'}], 1000)


def test_daily_compose_client_guard_accepts_provider_fallback(monkeypatch, tmp_path):
    from scripts import daily_compose
    _, table = daily_compose.make_client(tmp_path / 'calls')
    assert stage_models.route(table, 'compose')['base_url'] == 'https://subrouter.ai/v1'
    assert stage_models.is_flat_rate(stage_models.route(table, 'compose')['base_url'])


def test_draft_client_rejects_only_model_fallback():
    from scripts.daily_compose import DraftClient

    class Inner:
        stage_models = {}
        calls = []

        def __init__(self, r):
            self.r = r

        def __call__(self, *a):
            return self.r
    ok_r = {'response_model': 'gemini-3-flash-preview', 'model_fallback': False, 'provider_fallback': True}
    assert DraftClient(Inner(ok_r), [])('stance', [{'role': 'user', 'content': 'x'}], 10) is ok_r
    with pytest.raises(RuntimeError):
        DraftClient(Inner({'response_model': 'claude-opus-5', 'model_fallback': True}), [])('stance', [{'role': 'user', 'content': 'x'}], 10)


def test_wrong_response_model_retries_subrouter_once_then_falls_back(tmp_path):
    budget.set_cap(10.0)
    hosts = []
    answers = iter(['gemini-pro-agent', 'gemini-3.1-pro-preview'])

    def handler(request):
        hosts.append(request.url.host)
        return ok(next(answers) if request.url.host == 'subrouter.ai' else 'gemini-3.1-pro-preview')
    client = ErisedaiClient(tmp_path / 'calls', configuration=config(), transport=httpx.MockTransport(handler))
    out = client('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert hosts == ['subrouter.ai', 'subrouter.ai'] and out['serving_provider'] == 'subrouter'
    hosts.clear()
    answers = iter(['gemini-pro-agent', 'gemini-pro-agent'])
    out = client('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert hosts == ['subrouter.ai', 'subrouter.ai', 'www.micuapi.ai'] and out['provider_fallback']


def test_subrouter_stages_limit():
    t = stage_models.from_env(stage_models.load(), {**ENV, 'FD_SUBROUTER_STAGES': 'stance,extract'})
    assert stage_models.route(t, 'compose')['base_url'] == stage_models.GEMINI_RELAY_BASE
    assert stage_models.fallback(t, 'compose') is None
    assert stage_models.route(t, 'stance')['base_url'] == stage_models.SUBROUTER_BASE
