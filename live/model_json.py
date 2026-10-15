"""One JSON object, optionally fenced. Never discard prose outside the object.

Models sometimes copy CJK text whose “curly” quotes they normalise to bare ASCII
quotes inside a JSON string. parse_object(repair_quotes=True) — used by EXTRACT,
whose output is re-validated span by span, and by STANCE (Oct 6: zh why_line /
zh_units quoting 「无需紧迫行动」 as bare ASCII quotes burned a full ~$0.42 stance
retry) — repairs only that case: on an
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


def parse_object(raw, *, repair_quotes=False, unwrap_singleton=False):
    """unwrap_singleton (opt-in, STANCE only): accept `[{...}]` - exactly one object in a
    one-element array, nothing else - as that object. Gemini returns this shape for stance
    deterministically at temperature 0 (Oct 5/6), so strict parsing burned all 3 retries."""
    raw = raw.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):
        raw = raw[8:-4]
    value = _loads(raw) if repair_quotes else json.loads(raw)
    if unwrap_singleton and isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        value = value[0]
    if not isinstance(value, dict):
        raise ValueError('Expected one JSON object')
    return value


def robust_extract_on():
    """FD_THIN_EXTRACT_ROBUST (default on; 0 = HEAD behaviour): tolerant EXTRACT units parsing, one stricter
    retry, a per-request timeout on the ingest extract client."""
    import os
    return os.environ.get('FD_THIN_EXTRACT_ROBUST', '1') != '0'


def _strip_fence(raw):
    raw = raw.strip()
    for head in ('```json', '```JSON', '```'):
        if raw.startswith(head) and raw.endswith('```') and len(raw) > len(head) + 3:
            return raw[len(head):-3].strip()
    return raw


def parse_units_object(raw):
    """EXTRACT output -> {"units": [...]}. Oct 15 (FD_THIN_EXTRACT_ROBUST): the realistic off-contract shapes seen
    in the 10-10..10-15 extract calls are taken as-is, never filled in:
      [{"units": [...]}]                       a list wrapper (5 calls on 10-15; 4 channels failed)
      ```json{...}```                          a fence without the newlines
      {"units": [...]}}]}                      stray closing brackets after one complete object
      {"units": [a]} {"units": [b]}            concatenated objects / a list of several {"units"} objects
    Several objects are only combined when every one of them is exactly {"units": [...]} (their units are
    concatenated in order). Anything else raises ValueError like parse_object."""
    raw = _strip_fence(raw)
    try:
        value = _loads(raw)
    except json.JSONDecodeError:
        value = None
    if value is None:
        decoder, values, pos = json.JSONDecoder(), [], 0
        while pos < len(raw):
            while pos < len(raw) and raw[pos] in ' \t\r\n,':
                pos += 1
            if pos >= len(raw):
                break
            if not values and raw[pos] not in '{[':
                raise ValueError('Expected one JSON object')
            if values and set(raw[pos:].strip()) <= set(']}'):
                break   # trailing closers after a complete value
            try:
                item, pos = decoder.raw_decode(raw, pos)
            except json.JSONDecodeError:
                raise ValueError('Expected one JSON object') from None
            values.append(item)
        if not values:
            raise ValueError('Expected one JSON object')
        value = values if len(values) > 1 else values[0]
    if isinstance(value, dict):
        return value
    items = value if isinstance(value, list) else []
    flat = []
    for item in items:
        flat.extend(item if isinstance(item, list) else [item])
    if not flat or not all(isinstance(x, dict) for x in flat):
        raise ValueError('Expected one JSON object')
    if len(flat) == 1:
        return flat[0]
    if not all(set(x) == {'units'} and isinstance(x['units'], list) for x in flat):
        raise ValueError('Expected one JSON object')
    return {'units': [u for x in flat for u in x['units']]}
