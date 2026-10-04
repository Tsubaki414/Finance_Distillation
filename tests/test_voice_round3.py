import pytest
from live import compose
from live.distillation import ContractError


class Seq:
    def __init__(self, items): self.items = list(items)
    def __call__(self, stage, messages, max_tokens):
        x = self.items.pop(0)
        if isinstance(x, Exception): raise x
        return x


def test_http_429_is_retried_with_backoff():
    sleeps = []
    client = Seq([RuntimeError("Relay HTTP 429: {'code': 'user_concurrency_queue'}"), {'text': '{"a": 1}', 'finish_reason': 'stop'}])
    value, _ = compose._ask(client, 'compose', 'sys', {'x': 1}, 100, [], sleep=sleeps.append)
    assert value == {'a': 1} and sleeps and sleeps[0] >= 2


def test_other_runtime_errors_not_retried():
    client = Seq([RuntimeError('Relay HTTP 400: bad request')])
    with pytest.raises(RuntimeError):
        compose._ask(client, 'compose', 'sys', {'x': 1}, 100, [], sleep=lambda s: None)


def test_format_hint_from_line_break_habits():
    hint = compose.format_hint({'paragraphs': {'line_break_rate': 0.74, 'median': 3}}, 'en')
    assert 'line' in hint and '74%' in hint
    assert compose.format_hint({'paragraphs': {'line_break_rate': 0.2, 'median': 1}}, 'en').lower().startswith('mostly single')
    assert compose.format_hint(None, 'en') == ''


def test_opinion_markers_allowed_but_not_positions():
    assert '我觉得' in compose.COMPOSE and 'I think' in compose.COMPOSE
