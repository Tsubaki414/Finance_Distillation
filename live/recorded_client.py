"""Recorded-response client for offline stage replay (plan 1.3 subset).

Responses are keyed by (stage, replay key). The replay key is the digest of
the exact messages after removing wall-clock stamps (VOLATILE) from JSON
payloads; every other byte must match. There is no network: a request that
was not recorded raises UnrecordedCall, which surfaces prompt drift.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from live.distillation_source import digest


VOLATILE = frozenset({'snapshot_at', 'as_of'})


class UnrecordedCall(RuntimeError):
    pass


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def replay_key(messages):
    out = []
    for message in messages:
        message = dict(message)
        try:
            payload = json.loads(message.get('content', ''))
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, (dict, list)):
            message['content'] = _strip(payload)
        out.append(message)
    return digest(out)


def load_calls(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    for row in rows:
        if not {'stage', 'replay_key', 'response'} <= set(row):
            raise ValueError('recorded call needs stage, replay_key and response')
    return rows


def from_call_logs(directory):
    """Convert a ContentStages call directory (one JSON per call) to recorded rows."""
    rows = []
    for path in sorted(Path(directory).glob('*.json')):
        record = json.loads(path.read_text())
        if record.get('status') == 'completed' and record.get('response'):
            rows.append({'stage': record['stage'], 'replay_key': replay_key(record['messages']),
                         'prompt_hash': record['prompt_hash'],
                         'max_tokens': record.get('max_tokens'), 'response': record['response']})
    return rows


class RecordedClient:
    def __init__(self, calls):
        self._calls = {}
        for row in calls:
            self._calls.setdefault((row['stage'], row['replay_key']), []).append(row)
        self.used, self.misses = [], []

    def __call__(self, stage, messages, max_tokens):
        key = (stage, replay_key(messages))
        queue = self._calls.get(key)
        if not queue:
            self.misses.append({'stage': stage, 'replay_key': key[1]})
            raise UnrecordedCall(f'no recorded response for stage {stage} with this prompt')
        row = queue.pop(0)
        self.used.append(stage)
        return copy.deepcopy(row['response'])

