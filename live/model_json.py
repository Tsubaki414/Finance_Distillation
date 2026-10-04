"""One JSON object, optionally fenced. Never discard prose outside the object.

Models sometimes copy CJK text whose “curly” quotes they normalise to bare ASCII
quotes inside a JSON string. parse_object repairs only that case: on an
"Expecting ',' delimiter" error it escapes the last unescaped quote before the
error and retries (bounded). The repaired value still goes through every
downstream contract check (exact spans, numbers), so nothing is relaxed.
"""
import json

MAX_REPAIRS = 40


def _last_unescaped_quote(raw, before):
    i = raw.rfind('"', 0, before)
    while i > 0:
        backslashes = 0
        j = i - 1
        while j >= 0 and raw[j] == '\\':
            backslashes += 1
            j -= 1
        if backslashes % 2 == 0:
            return i
        i = raw.rfind('"', 0, i)
    return -1


def _loads(raw):
    original = raw
    for _ in range(MAX_REPAIRS + 1):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if not exc.msg.startswith("Expecting ',' delimiter"):
                raise
            at = _last_unescaped_quote(raw, exc.pos)
            if at <= 0:
                raise
            raw = raw[:at] + '\\' + raw[at:]
    return json.loads(original)


def parse_object(raw):
    raw = raw.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):
        raw = raw[8:-4]
    value = _loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Expected one JSON object')
    return value
