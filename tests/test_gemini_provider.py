"""FD_GEMINI_PROVIDER=relay|official (Oct 7): default relay (micuapi, GEMINI_RELAY_API_KEY, OpenAI-compatible),
same Gemini model names, no fallback, key never in records."""
import json
import os

import httpx
import pytest

from live import stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget

FAKE_KEY = 'sk-relay-secret-123456'


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 2.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.setenv('GEMINI_RELAY_API_KEY', FAKE_KEY)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    for name in [k for k in os.environ if k.startswith('FD_')]:
        monkeypatch.delenv(name)
    prices = budget.PRICES.copy()
    yield
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def config():
    return {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
            'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True}


def test_default_provider_is_relay_for_every_gemini_stage():
    table = stage_models.from_env(stage_models.load(), {})
    for stage in ('compose', 'stance', 'extract', 'extract_flash', 'view_enrich'):
        route = stage_models.route(table, stage)
        assert route == {'base_url': stage_models.GEMINI_RELAY_BASE, 'api_key_env': 'GEMINI_RELAY_API_KEY'}
        assert stage_models.fallback(table, stage) is None
    assert stage_models.for_stage(table, 'compose')['model'] == 'gemini-3.1-pro-preview'
    assert stage_models.max_tokens(table, 'extract') == 24000
    assert stage_models.thinking_level(table, 'compose', {}) == 'medium'


def test_official_provider_keeps_native_route_and_model_switch_follows_relay():
    official = stage_models.from_env(stage_models.load(), {'FD_GEMINI_PROVIDER': 'official'})
    assert stage_models.is_gemini_native(stage_models.route(official, 'stance')['base_url'])
    pro = stage_models.from_env(stage_models.load(), {'FD_GEMINI_MODEL': 'gemini-3.1-pro-preview'})
    assert stage_models.for_stage(pro, 'stance')['model'] == 'gemini-3.1-pro-preview'
    assert stage_models.is_gemini_relay(stage_models.route(pro, 'stance')['base_url'])
    with pytest.raises(ValueError):
        stage_models.from_env(stage_models.load(), {'FD_GEMINI_PROVIDER': 'opus'})


def test_relay_request_shape_and_no_key_in_record(tmp_path):
    seen = {}

    def handler(request):
        seen['url'] = str(request.url)
        seen['auth'] = request.headers.get('authorization')
        seen['body'] = json.loads(request.content)
        return httpx.Response(200, json={'id': 'x', 'model': 'gemini-3.1-pro-preview',
                                         'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}],
                                         'usage': {'prompt_tokens': 10, 'completion_tokens': 20}})
    client = ErisedaiClient(tmp_path, configuration={**config(), 'stage_models': stage_models.from_env(stage_models.load(), {})},
                            transport=httpx.MockTransport(handler))
    out = client('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert out['response_model'] == 'gemini-3.1-pro-preview'
    assert seen['url'] == 'https://www.micuapi.ai/v1/chat/completions'
    assert seen['auth'] == 'Bearer ' + FAKE_KEY
    assert seen['body']['model'] == 'gemini-3.1-pro-preview' and seen['body']['reasoning_effort'] == 'medium'
    for p in tmp_path.glob('*.json'):
        assert FAKE_KEY not in p.read_text()


def test_relay_error_raises_without_fallback(tmp_path):
    client = ErisedaiClient(tmp_path, configuration={**config(), 'stage_models': stage_models.from_env(stage_models.load(), {})},
                            transport=httpx.MockTransport(lambda r: httpx.Response(503, json={'error': {'message': 'no channel'}})))
    with pytest.raises(RuntimeError):
        client('stance', [{'role': 'user', 'content': 'hi'}], 1000)


def test_missing_relay_key_raises_at_construction(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_RELAY_API_KEY')
    with pytest.raises(ValueError, match='GEMINI_RELAY_API_KEY'):
        ErisedaiClient(tmp_path, configuration={**config(), 'stage_models': stage_models.from_env(stage_models.load(), {})})
