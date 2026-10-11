"""Oct 10 17:30 (PM decision A): micuapi empty -> circuit-broken for the day; subrouter retries with backoff;
one draft's failure never stops the run."""
import json
import os

import httpx
import pytest

from live import stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget

ENV = {'SUBROUTER_API_KEY': 'sk-sub-x'}
QUOTA = {'error': {'message': '用户额度不足, 剩余额度: ¥-0.017640', 'type': 'new_api_error', 'code': 'insufficient_user_quota'}}


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 10.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(budget, 'RUNS', tmp_path / 'review_runs.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.setenv('GEMINI_RELAY_API_KEY', 'sk-micu-x')
    monkeypatch.setenv('SUBROUTER_API_KEY', 'sk-sub-x')
    for name in [k for k in os.environ if k.startswith('FD_')]:
        monkeypatch.delenv(name)
    monkeypatch.setenv('FD_PROVIDER_DEAD_FILE', str(tmp_path / 'dead.json'))
    monkeypatch.setenv('FD_SUBROUTER_BACKOFF', '0')
    relay.reset_quota_breaker()
    prices = budget.PRICES.copy()
    yield
    relay.reset_quota_breaker()
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def _client(tmp_path, handler):
    cfg = {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
           'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
           'stage_models': stage_models.from_env(stage_models.load(), ENV)}
    return ErisedaiClient(tmp_path / 'calls', configuration=cfg, transport=httpx.MockTransport(handler))


def ok(model):
    return httpx.Response(200, json={'id': 'x', 'model': model, 'choices': [
        {'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"body": "x"}'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})


def test_subrouter_timeout_retried_then_succeeds(tmp_path):
    hosts, n = [], {'k': 0}

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == 'subrouter.ai':
            n['k'] += 1
            if n['k'] == 1:
                return httpx.Response(524, text='<html>timeout</html>')
            return ok(json.loads(request.content)['model'])
        raise AssertionError('micuapi must not be called')
    out = _client(tmp_path, handler)('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert hosts == ['subrouter.ai', 'subrouter.ai'] and out['serving_provider'] == 'subrouter'


def test_empty_micuapi_is_circuit_broken_for_the_day_and_not_a_quota_error(tmp_path):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == 'subrouter.ai':
            raise httpx.ConnectError('down')
        return httpx.Response(403, json=QUOTA)
    c = _client(tmp_path, handler)
    with pytest.raises(relay.PrimaryFailed) as e:
        c('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    from scripts.daily_compose import QUOTA_RX
    assert not QUOTA_RX.search(str(e.value))          # a per-draft failure, never the run-wide quota stop
    assert hosts.count('www.micuapi.ai') == 1
    dead = json.loads((tmp_path / 'dead.json').read_text())
    assert any('micuapi' in k for k in dead)
    hosts.clear()
    relay.FALLBACK_DEAD.clear()                        # a new process of the same day reads the file
    with pytest.raises(relay.PrimaryFailed):
        c('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert 'www.micuapi.ai' not in hosts and hosts.count('subrouter.ai') == 1 + relay.subrouter_retries()


def test_breaker_off_switch(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_FALLBACK_BREAKER', '0')
    relay.mark_fallback_dead('https://www.micuapi.ai/v1', 'x')
    assert relay.fallback_dead('https://www.micuapi.ai/v1') is None


def test_one_quota_draft_does_not_block_the_run(monkeypatch):
    from scripts import daily_compose
    monkeypatch.delenv('FD_QUOTA_BLOCK_AFTER', raising=False)
    assert daily_compose.quota_block_after() == 3


def test_dead_mark_survives_london_midnight_for_24h(tmp_path, monkeypatch):
    import time as _t
    url = 'https://www.micuapi.ai/v1'
    (tmp_path / 'dead.json').write_text(json.dumps({url: ['2000-01-01', 'old day', _t.time() - 3600]}))
    relay.FALLBACK_DEAD.clear()
    assert relay.fallback_dead(url)                      # set 1h ago on another date: still dead
    (tmp_path / 'dead.json').write_text(json.dumps({url: ['2000-01-01', 'old', _t.time() - 25 * 3600]}))
    relay.FALLBACK_DEAD.clear()
    assert relay.fallback_dead(url) is None              # older than 24h: retried
