"""Oct 6 P1-1: Gemini stance answered `[{...}]` three times -> 'Expected one JSON object'."""
import json

import pytest

from live import compose
from live.model_json import parse_object


def test_singleton_array_unwrapped_only_when_opted_in():
    assert parse_object('[{"decision": "adapt"}]', unwrap_singleton=True) == {'decision': 'adapt'}
    with pytest.raises(ValueError):
        parse_object('[{"decision": "adapt"}]')            # strict default unchanged
    for raw in ('[{"a": 1}, {"b": 2}]', '[1]', '[]', '[{"a": 1}] extra'):
        with pytest.raises(ValueError):
            parse_object(raw, unwrap_singleton=True)


def _client(text):
    calls = []

    def client(stage, messages, max_tokens):
        calls.append(stage)
        return {'text': text, 'finish_reason': 'stop'}
    return client, calls


def test_ask_unwraps_singleton_for_stance_first_try():
    client, calls = _client(json.dumps([{'decision': 'adapt'}]))
    value, _ = compose._ask(client, 'stance', 'system', {'x': 1}, 100, [], sleep=lambda s: None)
    assert value == {'decision': 'adapt'} and calls == ['stance']


def test_ask_keeps_strict_parse_for_other_stages():
    client, calls = _client(json.dumps([{'body': 'x'}]))
    with pytest.raises(Exception, match='Expected one JSON object'):
        compose._ask(client, 'compose', 'system', {'x': 1}, 100, [], sleep=lambda s: None)
    assert calls == ['compose'] * 3


def test_ask_repairs_bare_cjk_quotes_in_stance_first_try():
    # Oct 6 zhfix pack: a ZH why_line quoted 无需紧迫行动 with bare ASCII quotes; strict parse
    # resent the full stance call (~$0.42 reservation) and the slot sub-cap refused it.
    text = '```json\n{"decision": "take", "why_line": "威廉姆斯表示9月加息后"无需紧迫行动"，再看数据。"}\n```'
    client, calls = _client(text)
    value, _ = compose._ask(client, 'stance', 'system', {'x': 1}, 100, [], sleep=lambda s: None)
    assert value['why_line'] == '威廉姆斯表示9月加息后"无需紧迫行动"，再看数据。' and calls == ['stance']
    with pytest.raises(Exception):
        compose._ask(*_client(text)[:1], 'compose', 'system', {'x': 1}, 100, [], sleep=lambda s: None)
