"""Oct 15 FD_COMPOSE_PERSIST_UNITS: inbox rows keep the compose units and the source's own text fields (synthetic only)."""
import importlib.util
import json
import threading
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SLIM_KEYS = {'id', 'source_id', 'publisher', 'title', 'url', 'published_at', 'lang', 'same_language'}
UNITS = [{'unit_id': 'u1', 'kind': 'fact', 'statement': 'Widget sales rose 12% in Q3.',
          'source_spans': [{'exact_text': 'Widget sales rose 12% in Q3.', 'paragraph_id': 'p1'}],
          'numbers': [{'text': '12%'}]},
         {'unit_id': 'u2', 'kind': 'view', 'statement': 'Margins should hold because input costs fell.',
          'source_spans': [{'exact_text': 'input costs fell', 'paragraph_id': 'p2'}]}]


@pytest.fixture
def dc(monkeypatch):
    monkeypatch.delenv('FD_COMPOSE_PERSIST_UNITS', raising=False)
    spec = importlib.util.spec_from_file_location('dc_persist', ROOT / 'scripts' / 'daily_compose.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pick():
    return {'source_id': 's1', 'post_format': {'type': 'single'}, 'suggested_post_time_london': '2026-10-15T10:00:00+01:00',
            'angle': 'a', 'angle_why': '', 'shared_event_with': [], 'publisher': 'Pub', 'title': 'Widget maker Q3',
            'url': 'https://example.test/a', 'published_at': '2026-10-15T06:00:00+00:00', 'source_lang': 'en',
            'same_language': True, 'account_lang': 'en', 'unit_ids': ['u1', 'u2'], 'post_type': 'judgment_take'}


def _result(source, units=UNITS):
    return {'id': 'd1', 'body': 'b', 'text': 'b', 'post_type': 'judgment_take', 'plan': _pick(), 'source': source,
            'units': units, 'arbitration': {}, 'hard_repair': {}}


CFG = {'id': 'acct_en', 'no': 1, 'name': 'n', 'beat': 'b', 'lang': 'en'}
SRC = {'id': 'src-1', 'source_id': 's1', 'original_text': 'Widget sales rose 12% in Q3.\n\ninput costs fell',
       'summary': 'Q3 widget sales and margins.'}


def test_default_on_persists_units_and_source_text(dc):
    row = dc.inbox_row(_result(dict(SRC)), CFG, date(2026, 10, 15), 'run1')
    assert row['units'] == UNITS
    assert row['source']['original_text'] == SRC['original_text']
    assert row['source']['summary'] == SRC['summary']
    assert 'text' not in row['source']                       # absent on the source: not invented, no None
    assert SLIM_KEYS <= set(row['source'])
    assert row['source']['title'] == 'Widget maker Q3'
    json.dumps(row, ensure_ascii=False)


def test_kill_switch_matches_head_slim_shape(dc, monkeypatch):
    monkeypatch.setenv('FD_COMPOSE_PERSIST_UNITS', '0')
    row = dc.inbox_row(_result(dict(SRC, text='t')), CFG, date(2026, 10, 15), 'run1')
    assert set(row['source']) == SLIM_KEYS
    assert 'units' not in row


def test_missing_and_blank_fields_omitted(dc):
    row = dc.inbox_row(_result({'id': 'src-1', 'original_text': '  ', 'text': None}, units=None),
                       CFG, date(2026, 10, 15), 'run1')
    assert set(row['source']) == SLIM_KEYS
    assert 'units' not in row
    row = dc.inbox_row(_result({'id': 'src-1'}, units=[]), CFG, date(2026, 10, 15), 'run1')
    assert 'units' not in row


def test_units_json_safe_and_text_capped(dc):
    odd = [{'unit_id': 'u1', 'statement': 's', 'as_of': date(2026, 10, 15)}, 'not-a-dict']
    row = dc.inbox_row(_result({'text': 'x' * 20000}, units=odd), CFG, date(2026, 10, 15), 'run1')
    assert row['units'] == [{'unit_id': 'u1', 'statement': 's', 'as_of': '2026-10-15'}]
    assert len(row['source']['text']) == dc.PERSIST_TEXT_MAX


def _stub_compose(dc, monkeypatch, compose_fn):
    from live import rc_guard
    monkeypatch.setattr(rc_guard, 'event_enabled', lambda *a, **k: False)
    monkeypatch.setattr(dc, 'evidence_source', lambda group: (dict(SRC), [dict(u) for u in UNITS]))
    monkeypatch.setattr(dc.compose, 'compose_source', compose_fn)
    monkeypatch.setattr(dc, 'DraftClient', lambda client, log: type('C', (), {'paths': []})())
    monkeypatch.setattr(dc, 'call_cost', lambda paths: 0.0)
    monkeypatch.setattr(dc, 'ViewLedger', lambda account: None)
    monkeypatch.setattr(dc.angles, 'payload', lambda angle, lang: {'angle': angle})
    store = {'u1': {'source': {'id': 'src-1'}, 'unit': UNITS[0]}, 'u2': {'source': {'id': 'src-1'}, 'unit': UNITS[1]}}
    return dc.compose_one(lambda: None, 'acct_en', _pick(), date(2026, 10, 15), store, {'usd': 0.0}, threading.Lock())


def _boom(*a, **k):
    raise RuntimeError('model down')


def test_compose_one_error_path_keeps_evidence_units(dc, monkeypatch):
    r = _stub_compose(dc, monkeypatch, _boom)
    assert r['status'] == 'error' and r['units'] == UNITS
    assert r['source']['original_text'] == SRC['original_text']
    row = dc.inbox_row(r, CFG, date(2026, 10, 15), 'run1')
    assert row['units'] == UNITS and row['source']['original_text'] == SRC['original_text']


def test_compose_one_keeps_compose_chosen_units(dc, monkeypatch):
    r = _stub_compose(dc, monkeypatch, lambda *a, **k: {'status': 'ok', 'body': 'b', 'units': UNITS[:1]})
    assert r['units'] == UNITS[:1]


def test_compose_one_kill_switch_error_path_has_no_units(dc, monkeypatch):
    monkeypatch.setenv('FD_COMPOSE_PERSIST_UNITS', '0')
    r = _stub_compose(dc, monkeypatch, _boom)
    assert 'units' not in r
