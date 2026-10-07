"""Oct 7 (stage-models-v3-gemini-official): Gemini stages call the official Gemini API natively.

compose / stance / extract / extract_flash / view_enrich -> POST {base}/models/<model>:generateContent with the
x-goog-api-key header (the AQ. token extracted from GEMINI_API_KEY), no Authorization header, no fallback.
Offline: httpx.MockTransport only; the budget ledger is patched to a temp file; env via monkeypatch.
"""
import json
import os
from pathlib import Path

import httpx
import pytest

from live import stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget

GEMINI = 'https://generativelanguage.googleapis.com/v1beta'
GEMINI_STAGES = ('compose', 'stance', 'extract', 'extract_flash', 'view_enrich')
FAKE_ENV = 'prefix-AQ.fakeTOKEN123'
TOKEN = 'AQ.fakeTOKEN123'
RELAY = {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'default-relay-key', 'model': 'claude-opus-5',
         'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0}
MSGS = [{'role': 'system', 'content': 'Return JSON only.'},
        {'role': 'user', 'content': '{"source": "s"}'}]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 2.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.setenv('GEMINI_API_KEY', FAKE_ENV)
    for name in [k for k in os.environ if k.startswith('FD_')]:
        monkeypatch.delenv(name)
    monkeypatch.setenv('FD_GEMINI_PROVIDER', 'official')   # these tests cover the official native API
    prices = budget.PRICES.copy()
    yield
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def gemini_ok(model='gemini-3-flash-preview', finish='STOP', text='{"ok": true}'):
    return httpx.Response(200, json={
        'responseId': 'resp-1', 'modelVersion': model,
        'candidates': [{'content': {'role': 'model', 'parts': [
            {'text': 'internal reasoning that must not leak', 'thought': True},
            {'text': text}]}, 'finishReason': finish}],
        'usageMetadata': {'promptTokenCount': 11, 'candidatesTokenCount': 7, 'thoughtsTokenCount': 30}})


def make_client(tmp_path, handler, seen, table=None):
    def handle(request):
        seen.append(request)
        return handler(request)
    config = dict(RELAY)
    if table is not None:
        config['stage_models'] = table
    return ErisedaiClient(tmp_path / 'calls', configuration=config, transport=httpx.MockTransport(handle))


def records(tmp_path):
    return [json.loads(p.read_text()) for p in sorted((tmp_path / 'calls').glob('*.json'))]


# (a) native transport --------------------------------------------------------------------------------

def test_native_request_shape_and_headers(tmp_path):
    seen = []
    out = make_client(tmp_path, lambda r: gemini_ok(), seen)('stance', MSGS, 500)   # flash stage (compose is pro)
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == GEMINI + '/models/gemini-3-flash-preview:generateContent'
    assert req.headers['x-goog-api-key'] == TOKEN
    assert 'authorization' not in req.headers
    body = json.loads(req.content)
    assert body['systemInstruction'] == {'parts': [{'text': 'Return JSON only.'}]}
    assert body['contents'] == [{'role': 'user', 'parts': [{'text': '{"source": "s"}'}]}]
    gen = body['generationConfig']
    assert gen['responseMimeType'] == 'application/json'
    assert gen['temperature'] == 1.0                 # Gemini 3: temperature 0 loops in thinking
    assert gen['thinkingConfig'] == {'thinkingLevel': 'medium'}
    assert gen['maxOutputTokens'] == 16000          # the stage's own ceiling (thinking tokens count)
    assert 'model' not in body and 'messages' not in body
    assert out['text'] == '{"ok": true}'
    assert out['model'] == 'gemini-3-flash-preview' and out['model_fallback'] is False


def test_response_mapping_excludes_thoughts_and_counts_thought_tokens(tmp_path):
    out = make_client(tmp_path, lambda r: gemini_ok(), [])('extract', MSGS, 500)
    assert 'internal reasoning' not in out['text']
    assert out['finish_reason'] == 'stop'
    assert out['usage']['prompt_tokens'] == 11
    assert out['usage']['completion_tokens'] == 7 + 30
    assert out['usage']['thoughts_tokens'] == 30


def test_max_tokens_finish_maps_to_length(tmp_path):
    out = make_client(tmp_path, lambda r: gemini_ok(finish='MAX_TOKENS'), [])('stance', MSGS, 500)
    assert out['finish_reason'] == 'length'


def test_gemini_to_chat_mapping_directly():
    data = relay.gemini_to_chat({'candidates': [{'content': {'parts': [{'text': 'a', 'thought': True}, {'text': 'b'}]},
                                                 'finishReason': 'MAX_TOKENS'}],
                                 'usageMetadata': {'promptTokenCount': 3, 'candidatesTokenCount': 4,
                                                   'thoughtsTokenCount': 5}}, 'gemini-3-flash-preview')
    assert data['choices'][0]['message']['content'] == 'b'
    assert data['choices'][0]['finish_reason'] == 'length'
    assert data['usage'] == {'prompt_tokens': 3, 'completion_tokens': 9, 'total_tokens': 12, 'thoughts_tokens': 5}
    assert data['model'] == 'gemini-3-flash-preview'
    stop = relay.gemini_to_chat({'candidates': [{'content': {'parts': [{'text': 'x'}]}, 'finishReason': 'STOP'}]}, 'm')
    assert stop['choices'][0]['finish_reason'] == 'stop'


def test_call_record_never_contains_the_token(tmp_path):
    def echo_token(request):
        # Even a provider echoing the key must not leak it into saved records.
        return httpx.Response(400, json={'error': {'message': f'API key {TOKEN} not valid',
                                                   'details': {'x-goog-api-key': TOKEN}}})
    client = make_client(tmp_path, lambda r: gemini_ok('gemini-3.1-pro-preview'), [])
    client('compose', MSGS, 500)
    with pytest.raises(Exception) as err:
        make_client(tmp_path, echo_token, [])('compose', MSGS, 500)
    assert TOKEN not in str(err.value) and 'fakeTOKEN' not in str(err.value)
    recs = records(tmp_path)
    assert len(recs) == 2
    dump = json.dumps(recs)
    assert 'fakeTOKEN' not in dump and FAKE_ENV not in dump
    ok = [r for r in recs if r['status'] == 'completed'][0]
    assert ok['provider'] == relay.GEMINI_PROVIDER and ok['host'] == 'generativelanguage.googleapis.com'
    assert ok['routed_key_env'] == 'GEMINI_API_KEY'


# (b) failures raise, no fallback -----------------------------------------------------------------------

@pytest.mark.parametrize('response', [
    httpx.Response(429, json={'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'message': 'quota exceeded'}}),
    httpx.Response(500, json={'error': {'code': 500, 'status': 'INTERNAL', 'message': 'boom'}}),
    httpx.Response(503, json={'error': {'code': 503, 'status': 'UNAVAILABLE', 'message': 'overloaded'}}),
])
def test_gemini_errors_raise_without_fallback(tmp_path, response):
    seen = []
    with pytest.raises(Exception, match=str(response.status_code)):
        make_client(tmp_path, lambda r: response, seen)('compose', MSGS, 500)
    assert len(seen) == 1 and seen[0].url.host == 'generativelanguage.googleapis.com'
    recs = records(tmp_path)
    assert len(recs) == 1 and recs[0]['status'] == 'failed'
    assert not any(r.get('model_fallback') for r in recs)
    assert relay.quota_tripped() == {}


def test_gemini_timeout_raises_without_fallback(tmp_path):
    seen = []

    def slow(request):
        raise httpx.ReadTimeout('slow')
    with pytest.raises(RuntimeError, match='transport failed'):
        make_client(tmp_path, slow, seen)('extract', MSGS, 500)
    assert len(seen) == 1
    assert not any(r.get('model_fallback') for r in records(tmp_path))


# (c) missing key fails at construction -------------------------------------------------------------------

def test_missing_gemini_key_raises_at_construction(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY')
    seen = []
    with pytest.raises(ValueError, match='GEMINI_API_KEY'):
        make_client(tmp_path, lambda r: gemini_ok(), seen)
    assert seen == []


def test_key_without_aq_token_raises_at_construction(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'no-usable-token')
    with pytest.raises(ValueError, match='AQ'):
        make_client(tmp_path, lambda r: gemini_ok(), [])


def test_gemini_token_extraction():
    assert stage_models.gemini_token('prefix-AQ.fakeTOKEN123') == 'AQ.fakeTOKEN123'
    assert stage_models.gemini_token('AQ.abc_DEF-1') == 'AQ.abc_DEF-1'
    with pytest.raises(ValueError):
        stage_models.gemini_token('sk-nothing')


# (d) FD_GEMINI_MODEL / FD_<STAGE>_MODEL switch models, keep the route ----------------------------------

def test_fd_gemini_model_switches_every_gemini_stage_and_keeps_route():
    shipped = stage_models.load()
    table = stage_models.from_env(shipped, {'FD_GEMINI_MODEL': 'gemini-3.1-pro-preview', 'FD_GEMINI_PROVIDER': 'official'})
    for stage in GEMINI_STAGES:
        assert stage_models.for_stage(table, stage)['model'] == 'gemini-3.1-pro-preview'
        assert stage_models.route(table, stage) == {'base_url': GEMINI, 'api_key_env': 'GEMINI_API_KEY'}
        assert stage_models.max_tokens(table, stage) == stage_models.max_tokens(shipped, stage)
        assert stage_models.rates(table, stage) == (2.0, 12.0)
        assert stage_models.fallback(table, stage) is None
    assert stage_models.for_stage(table, 'qa')['model'] == 'claude-opus-5'
    assert stage_models.route(table, 'qa') is None


def test_fd_stage_model_switches_one_stage_and_keeps_route():
    table = stage_models.from_env(stage_models.load(), {'FD_COMPOSE_MODEL': 'gemini-3.1-pro-preview', 'FD_GEMINI_PROVIDER': 'official'})
    assert stage_models.for_stage(table, 'compose')['model'] == 'gemini-3.1-pro-preview'
    assert stage_models.route(table, 'compose') == {'base_url': GEMINI, 'api_key_env': 'GEMINI_API_KEY'}
    assert stage_models.max_tokens(table, 'compose') == 16000
    assert stage_models.for_stage(table, 'stance')['model'] == 'gemini-3-flash-preview'


def test_fd_gemini_model_reaches_the_request_url(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_GEMINI_MODEL', 'gemini-3.1-pro-preview')
    seen = []
    out = make_client(tmp_path, lambda r: gemini_ok(model='gemini-3.1-pro-preview'), seen)('stance', MSGS, 500)
    assert str(seen[0].url) == GEMINI + '/models/gemini-3.1-pro-preview:generateContent'
    assert seen[0].headers['x-goog-api-key'] == TOKEN
    assert json.loads(seen[0].content)['generationConfig']['maxOutputTokens'] == 16000
    assert out['model'] == 'gemini-3.1-pro-preview'


# (e) FD_GEMINI_ONLY ----------------------------------------------------------------------------------------

def test_gemini_only_rejects_stage_not_routed_to_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_GEMINI_ONLY', '1')
    seen = []
    client = make_client(tmp_path, lambda r: gemini_ok('gemini-3.1-pro-preview'), seen)
    with pytest.raises(RuntimeError, match='FD_GEMINI_ONLY'):
        client('qa', MSGS, 500)
    assert seen == []
    client('compose', MSGS, 500)                 # Gemini-routed stages still run
    assert len(seen) == 1 and seen[0].url.host == 'generativelanguage.googleapis.com'


def test_gemini_only_rejects_stage_overridden_off_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv('FD_GEMINI_ONLY', '1')
    monkeypatch.setenv('FD_COMPOSE_MODEL', 'claude-opus-5')
    seen = []
    with pytest.raises(RuntimeError, match='FD_GEMINI_ONLY'):
        make_client(tmp_path, lambda r: gemini_ok(), seen)('compose', MSGS, 500)
    assert seen == []


def test_gemini_error_is_not_billed(tmp_path, monkeypatch):
    import httpx as _h
    client = make_client(tmp_path, lambda r: _h.Response(503, json={'error': {'code': 503, 'message': 'high demand'}}), [])
    with pytest.raises(RuntimeError):
        client('compose', MSGS, 500)
    rec = json.loads(Path(client.calls[0]['path']).read_text())
    assert rec['estimated_cost_usd'] == 0


def test_thinking_env_override(monkeypatch):
    table = stage_models.load()
    assert stage_models.thinking_level(table, 'compose', {'FD_GEMINI_THINKING': 'low'}) == 'low'
    with pytest.raises(ValueError):
        stage_models.thinking_level(table, 'compose', {'FD_GEMINI_THINKING': 'huge'})
