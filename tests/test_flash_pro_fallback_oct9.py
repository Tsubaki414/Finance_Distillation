"""Oct 9 ~13:00 London: subrouter gemini-3-flash -> HTTP 400 'antigravity auth missing project_id'; micuapi (the
same-model fallback) has no balance. Flash stages re-run on subrouter gemini-3.1-pro-preview instead."""
import json
import os

import httpx
import pytest

from live import stage_models
from live import erisedai_distillation_client as relay
from live.erisedai_distillation_client import ErisedaiClient
from ml import budget

SUB_KEY = 'sk-subrouter-secret-abcdef123'
DEAD = {'error': {'message': 'antigravity auth missing project_id: no project_id in response'}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 10.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(budget, 'RUNS', tmp_path / 'review_runs.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.delenv('GEMINI_RELAY_API_KEY', raising=False)    # micuapi unset (no balance), as in production
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


def config():
    return {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
            'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
            'stage_models': stage_models.from_env(stage_models.load(), {'SUBROUTER_API_KEY': SUB_KEY})}


def ok(model):
    return httpx.Response(200, json={'id': 'x', 'model': model,
                                     'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 100, 'completion_tokens': 200}})


def _client(tmp_path, seen, flash_status=400, flash_body=DEAD):
    def handler(request):
        body = json.loads(request.content)
        seen.append((str(request.url), body['model']))
        if body['model'] == 'gemini-3-flash':
            return httpx.Response(flash_status, json=flash_body)
        return ok(body['model'])
    return ErisedaiClient(tmp_path / 'calls', configuration=config(), transport=httpx.MockTransport(handler))


@pytest.mark.parametrize('stage', ['stance', 'extract', 'extract_flash', 'view_enrich'])
def test_every_flash_stage_falls_back_to_pro_on_subrouter(tmp_path, stage):
    seen = []
    out = _client(tmp_path, seen)(stage, [{'role': 'user', 'content': 'hi'}], 1000)
    assert seen == [('https://subrouter.ai/v1/chat/completions', 'gemini-3-flash'),
                    ('https://subrouter.ai/v1/chat/completions', 'gemini-3.1-pro-preview')]
    assert out['model_fallback'] and not out['provider_fallback'] and out['serving_provider'] == 'subrouter'
    rec = [json.loads(p.read_text()) for p in (tmp_path / 'calls').glob('*.json')]
    pro = [r for r in rec if r['model'] == 'gemini-3.1-pro-preview']
    assert pro and 'project_id' in pro[0]['fallback_reason'] and pro[0]['cost_counts_toward_cap'] is False
    assert json.loads(budget.LEDGER.read_text())['spent_usd'] == 0.0


def test_dead_channel_is_skipped_after_the_first_error(tmp_path):
    seen = []
    client = _client(tmp_path, seen)
    for _ in range(3):
        client('stance', [{'role': 'user', 'content': 'hi'}], 1000)
    assert [m for _, m in seen] == ['gemini-3-flash'] + ['gemini-3.1-pro-preview'] * 3


def test_other_400s_and_switch_off_do_not_fall_back(tmp_path, monkeypatch):
    seen = []
    with pytest.raises(Exception):
        _client(tmp_path, seen, flash_body={'error': {'message': 'bad request: invalid json'}})(
            'stance', [{'role': 'user', 'content': 'hi'}], 1000)
    assert [m for _, m in seen] == ['gemini-3-flash']
    relay.reset_quota_breaker()
    monkeypatch.setenv('FD_FLASH_PRO_FALLBACK', '0')
    seen.clear()
    with pytest.raises(Exception):
        _client(tmp_path, seen)('stance', [{'role': 'user', 'content': 'hi'}], 1000)
    assert [m for _, m in seen] == ['gemini-3-flash']


def test_compose_on_pro_is_untouched(tmp_path):
    seen = []
    _client(tmp_path, seen)('compose', [{'role': 'user', 'content': 'hi'}], 1000)
    assert [m for _, m in seen] == ['gemini-3.1-pro-preview']
