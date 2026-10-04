from live import compose


def test_incomplete_finish_retries_with_bigger_budget():
    seen = []

    def client(stage, messages, max_tokens):
        seen.append(max_tokens)
        if len(seen) == 1:
            return {'text': '', 'finish_reason': 'length'}
        return {'text': '{"ok": true}', 'finish_reason': 'stop'}
    value, _ = compose._ask(client, 'compose', 'sys', {'a': 1}, 4000, [], sleep=lambda s: None)
    assert value == {'ok': True} and seen == [4000, 8000]
