"""Oct 15 (FD_THIN_EXTRACT_ROBUST): the 10-14 -> 10-15 nightly lost 4 thin_* channels to
(a) EXTRACT answers wrapped as [{"units": [...]}] -> "ContractError: extract: Expected one JSON object" and
(b) extract requests that hung on subrouter until the 240 s task alarm (the relay's own 300 s read timeout never
fired, so its retry never ran). Fixtures only: no network, no model."""
import json
import os

import httpx
import pytest

from live import content_units as cu
from live import erisedai_distillation_client as relay
from live import stage_models
from live.distillation import ContractError
from live.model_json import parse_units_object
from tests.test_extract_contract import SOURCE, unit
from ml import budget


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ('FD_THIN_EXTRACT_ROBUST', 'FD_EXTRACT_CALL_TIMEOUT_S', 'FD_INGEST_TASK_TIMEOUT'):
        monkeypatch.delenv(name, raising=False)


class Seq:
    """Fake relay client answering the given texts in order."""
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []

    def __call__(self, stage, messages, max_tokens):
        self.calls.append(messages)
        return {'text': self.texts[len(self.calls) - 1], 'finish_reason': 'stop', 'model': 'fake'}


A, B = unit(), unit(kind='view', statement='Makers avoid overbuilding.',
                    source_spans=[{'paragraph_id': 'P3', 'exact_text': 'none of them wants to build a glut'}],
                    numbers=[], speaker='Timothy Prickett Morgan', speaker_type='media')
OBJ = json.dumps({'units': [A, B]}, indent=2)


# ---------------- JSON shapes seen in 10-10..10-15 extract calls ----------------
@pytest.mark.parametrize('raw', [
    OBJ,
    '```json\n' + OBJ + '\n```',
    '```json' + OBJ + '```',                                    # fence without newlines (10-12)
    '[\n' + OBJ + '\n]',                                        # list wrapper (5 calls on 10-15)
    '```json\n[' + OBJ + ']\n```',
    OBJ + '}]}',                                                # stray closers after a complete object (10-12)
    json.dumps({'units': [A]}) + '\n' + json.dumps({'units': [B]}),   # concatenated objects
    json.dumps([{'units': [A]}, {'units': [B]}]),               # list of several {"units"} objects
])
def test_realistic_shapes_parse_to_the_same_units(raw):
    assert parse_units_object(raw) == {'units': [A, B]}


@pytest.mark.parametrize('raw', [
    json.dumps([A, B]),                                         # bare unit list: no wrapper is invented
    json.dumps([{'units': [A]}, {'units': [B], 'note': 'x'}]),  # extra keys: objects are not merged
    json.dumps({'units': [A]}) + ' trailing prose',
    'Here you go: ' + OBJ,
    '{"units": [{"kind": "fact", _subject: "x"}]}',             # unquoted key (10-12): not repaired
    '',
    '[]',
])
def test_unsafe_shapes_still_fail(raw):
    with pytest.raises(ValueError):
        parse_units_object(raw)


def test_list_wrapper_is_extracted_without_retry():
    fake = Seq('[' + OBJ + ']')
    out = cu.extract(SOURCE, fake, licence_tier='B')
    assert len(fake.calls) == 1 and len(out['units']) == 2


def test_unparseable_answer_gets_one_stricter_retry():
    fake = Seq('{"units": [{"kind": "fact", _subject: "x"}]}', OBJ)
    out = cu.extract(SOURCE, fake, licence_tier='B')
    assert len(fake.calls) == 2 and len(out['units']) == 2
    assert fake.calls[1][:-1] == fake.calls[0]                  # same prompt + one stricter user turn
    assert fake.calls[1][-1]['role'] == 'user' and 'exactly one JSON object' in fake.calls[1][-1]['content']


def test_at_most_one_retry_then_contract_error():
    fake = Seq('not json', 'still not json', OBJ)
    with pytest.raises(ContractError, match='extract: Expected one JSON object'):
        cu.extract(SOURCE, fake, licence_tier='B')
    assert len(fake.calls) == 2


def test_single_unit_without_wrapper_retries_once():
    fake = Seq(json.dumps([A]), OBJ)                            # [unit] unwraps to a unit, not {"units"}
    out = cu.extract(SOURCE, fake, licence_tier='B')
    assert len(fake.calls) == 2 and len(out['units']) == 2


def test_switch_off_restores_head_parsing(monkeypatch):
    monkeypatch.setenv('FD_THIN_EXTRACT_ROBUST', '0')
    fake = Seq('[' + OBJ + ']', OBJ)
    with pytest.raises(ContractError, match='^extract: Expected one JSON object$'):
        cu.extract(SOURCE, fake, licence_tier='B')
    assert len(fake.calls) == 1                                 # no retry
    fake = Seq('```json\n' + OBJ + '\n```')
    assert len(cu.extract(SOURCE, fake, licence_tier='B')['units']) == 2


def test_switch_off_identical_result_on_well_formed_answer(monkeypatch):
    on = cu.extract(SOURCE, Seq(OBJ), licence_tier='B')
    monkeypatch.setenv('FD_THIN_EXTRACT_ROBUST', '0')
    off = cu.extract(SOURCE, Seq(OBJ), licence_tier='B')
    assert on == off


# ---------------- per-request timeout of the ingest extract client ----------------
def test_extract_request_timeout_defaults(monkeypatch):
    from live.daily_ingest import extract_request_timeout
    assert extract_request_timeout() == 110.0                  # task limit 240: 110 + 10 s backoff + 110 < 240
    assert extract_request_timeout(120) == 50.0
    assert extract_request_timeout(0) == 110.0                  # task alarm off
    monkeypatch.setenv('FD_EXTRACT_CALL_TIMEOUT_S', '90')
    assert extract_request_timeout() == 90.0
    monkeypatch.setenv('FD_EXTRACT_CALL_TIMEOUT_S', '0')
    assert extract_request_timeout() is None
    monkeypatch.setenv('FD_THIN_EXTRACT_ROBUST', '0')
    monkeypatch.delenv('FD_EXTRACT_CALL_TIMEOUT_S')
    assert extract_request_timeout() is None


@pytest.fixture
def relay_iso(tmp_path, monkeypatch):
    ledger = tmp_path / 'spend.json'
    ledger.write_text(json.dumps({'cap_usd': 10.0, 'spent_usd': 0.0, 'calls': 0}))
    monkeypatch.setattr(budget, 'LEDGER', ledger)
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'DISTILLATION_RUNS', tmp_path / 'r.jsonl')
    monkeypatch.setattr(budget, 'RUNS', tmp_path / 'review_runs.jsonl')
    monkeypatch.setattr(relay, '_dotenv', lambda: {})
    monkeypatch.setenv('SUBROUTER_API_KEY', 'sk-sub-x')
    for name in [k for k in os.environ if k.startswith('FD_')]:
        monkeypatch.delenv(name)
    monkeypatch.setenv('FD_PROVIDER_DEAD_FILE', str(tmp_path / 'dead.json'))
    monkeypatch.setenv('FD_SUBROUTER_BACKOFF', '0')
    relay.reset_quota_breaker()
    prices = budget.PRICES.copy()
    seen = []
    real = httpx.Client

    def spy(*a, **k):
        seen.append(k.get('timeout'))
        return real(*a, **k)
    monkeypatch.setattr(relay.httpx, 'Client', spy)
    yield seen
    relay.reset_quota_breaker()
    budget.PRICES.clear()
    budget.PRICES.update(prices)


def _client(tmp_path, handler):
    cfg = {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused', 'model': 'claude-opus-5',
           'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
           'stage_models': stage_models.from_env(stage_models.load(), {'SUBROUTER_API_KEY': 'sk-sub-x'})}
    return relay.ErisedaiClient(tmp_path / 'calls', configuration=cfg, transport=httpx.MockTransport(handler))


def _ok(request):
    return httpx.Response(200, json={'id': 'x', 'model': json.loads(request.content)['model'], 'choices': [
        {'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': OBJ}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})


def test_hung_extract_request_is_cut_and_retried_inside_the_task(tmp_path, relay_iso):
    from live.daily_ingest import set_extract_request_timeout
    n = {'k': 0}

    def handler(request):
        n['k'] += 1
        if n['k'] == 1:
            raise httpx.ReadTimeout('no response headers', request=request)   # the 10-15 hang
        return _ok(request)
    c = _client(tmp_path, handler)
    assert set_extract_request_timeout(c) == 110.0
    out = cu.extract(SOURCE, c, licence_tier='B')
    assert n['k'] == 2 and len(out['units']) == 2
    assert [t.read for t in relay_iso] == [110.0, 110.0] and relay_iso[0].connect == 15.0


def test_switch_off_keeps_relay_timeout(tmp_path, relay_iso, monkeypatch):
    from live.daily_ingest import set_extract_request_timeout
    monkeypatch.setenv('FD_THIN_EXTRACT_ROBUST', '0')
    c = _client(tmp_path, _ok)
    assert set_extract_request_timeout(c) is None and not hasattr(c, 'request_timeout')
    cu.extract(SOURCE, c, licence_tier='B')
    assert relay_iso == [relay.TIMEOUT]


# ---------------- a failed item does not discard the channel's other items ----------------
def test_timed_out_item_keeps_units_of_the_channels_other_items(tmp_path, monkeypatch):
    from live.adapters.common import make_source
    from live.content_store import ContentStore
    from live.daily_ingest import run
    monkeypatch.setenv('FD_INGEST_TASK_TIMEOUT', '1')

    def source(sid):
        return make_source(id=sid, source_id='cboe', text=sid + ' distinct evidence', publisher=sid,
                           title=sid, url='https://example.test/' + sid, published_at='2026-10-14', adapter='edgar')

    def extract(s):
        if s['id'] == 'hang':
            while True:
                sum(range(1000))
        return [{'unit_id': s['id'], 'source_hash': s['source_hash'], 'statement': s['original_text'], 'kind': 'fact',
                 'numbers': [], 'licence_tier': 'A', 'usage': 'quote', 'speaker': s['publisher']}]
    fs = {'cboe': lambda: {'sources': [source('first'), source('hang'), source('third')]}}
    r = run(store=tmp_path / 'store', runs_dir=tmp_path / 'runs', inbox=tmp_path / 'inbox',
            state_path=tmp_path / 'state.json', no_dashboard=True, fetchers=fs, extract=extract,
            backup=lambda: None, refresh=lambda: None, per_channel_max=3)
    ch = {c['id']: c for c in r['channels']}['cboe']
    assert ch['status'] == 'failed' and ch['units'] == 2
    assert {u['unit_id'] for u in ContentStore(tmp_path / 'store').units()} == {'first', 'third'}
