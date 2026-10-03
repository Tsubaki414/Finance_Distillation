"""One JSON object, optionally fenced. Never discard prose outside the object."""
import json


def parse_object(raw):
    raw=raw.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):
        raw=raw[8:-4]
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('Expected one JSON object')
    return value
