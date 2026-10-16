"""Oct 16: subrouter serves gemini-3.1-pro-preview as SSE backed by gemini-3.8-flash-n. Fix: send gemini-3.1-pro with
stream:false, detect SSE as a distinct non-retried error, refuse gemini-3.8-* response models."""
import json
import os

import httpx
import pytest

from live import stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient, RelaySSEError
from ml import budget

SUB_KEY = 'sk-subrouter-secret-abcdef123'
MSG = [{'role': 'user', 'content': 'hi'}]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 10.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(budget, 'RUNS', tmp_path / 'review_runs.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.delenv('GEMINI_RELAY_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('SUBROUTER_API_KEY', SUB_KEY)
    for name in [k for k in os.environ if k.startswith('FD_')]:
        monkeypatch.delenv(name)
    monkeypatch.setattr(relay.time, 'sleep', lambda s: None)
    relay.reset_quota_breaker()
    prices = budget.PRICES.copy()
    yield
    relay.reset_quota_breaker()
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def config():
    return {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
            'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
            'stage_models': stage_models.from_env(stage_models.load(), {'SUBROUTER_API_KEY': SUB_KEY})}


def ok(model):
    return httpx.Response(200, json={'id': 'x', 'model': model,
                                     'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 10, 'completion_tokens': 20}})


def sse():
    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                          content=b'data: {"model":"gemini-3.8-flash-n"}\n\ndata: [DONE]\n\n')


def test_model_mapping():
    assert stage_models.subrouter_model('gemini-3.1-pro-preview', {}) == 'gemini-3.1-pro'
    assert stage_models.subrouter_model('gemini-3-flash-preview', {}) == 'gemini-3-flash'
    assert stage_models.subrouter_model('gemini-3.1-pro-preview', {'FD_SUBROUTER_PRO_ID': 'preview'}) \
        == 'gemini-3.1-pro-preview'


def test_table_maps_pro_stages_to_ga_id_and_leaves_flash():
    table = stage_models.apply_gemini_provider(stage_models.load(), {'SUBROUTER_API_KEY': SUB_KEY,
                                                                      'FD_GEMINI_PROVIDER': 'subrouter'})
    for stage, entry in table['stages'].items():
        if entry['base_url'] == stage_models.SUBROUTER_BASE:
            assert entry['model'] != 'gemini-3.1-pro-preview'
            assert entry['model'] in ('gemini-3.1-pro', 'gemini-3-flash')
    assert any(e['model'] == 'gemini-3.1-pro' for e in table['stages'].values())
    assert 'gemini-3.1-pro' in table['accepted_response_models']


def test_accepted_model_path_sends_stream_false(tmp_path):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return ok(body['model'])
    client = ErisedaiClient(tmp_path / 'c', configuration=config(), transport=httpx.MockTransport(handler))
    out = client('compose', MSG, 1000)
    assert seen[0]['model'] == 'gemini-3.1-pro' and seen[0]['stream'] is False
    assert out['response_model'] == 'gemini-3.1-pro' and out['serving_provider'] == 'subrouter'


def test_sse_is_distinct_error_and_not_retried(tmp_path):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return sse()
    client = ErisedaiClient(tmp_path / 'c', configuration=config(), transport=httpx.MockTransport(handler))
    with pytest.raises(RelaySSEError):
        client('compose', MSG, 1000)
    assert hosts == ['subrouter.ai']   # one call; no same-model retry, micuapi key unset so no provider fallback


def test_sse_detected_by_data_prefix_without_content_type(tmp_path):
    n = []

    def handler(request):
        n.append(1)
        return httpx.Response(200, content=b'data: {"x":1}\n\n')
    client = ErisedaiClient(tmp_path / 'c', configuration=config(), transport=httpx.MockTransport(handler))
    with pytest.raises(RelaySSEError):
        client('compose', MSG, 1000)
    assert len(n) == 1


def test_gemini_38_response_model_refused_without_retry(tmp_path):
    n = []

    def handler(request):
        n.append(1)
        return ok('gemini-3.8-flash-n')
    client = ErisedaiClient(tmp_path / 'c', configuration=config(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match='Unexpected relay response model'):
        client('compose', MSG, 1000)
    assert len(n) <= 2   # existing guard: at most the one documented free same-provider retry for a wrong channel


def test_rollback_flag_restores_preview_id(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_SUBROUTER_PRO_ID', 'preview')
    t = stage_models.apply_gemini_provider(stage_models.load(), {'SUBROUTER_API_KEY': SUB_KEY,
                                                                  'FD_GEMINI_PROVIDER': 'subrouter'})
    assert any(e['model'] == 'gemini-3.1-pro-preview' for e in t['stages'].values())
