"""Fixed fixture matrix for P0-2 prompt-assembly equivalence (test helper, not a test).

Each case runs the real account adaptation pipeline with the real ContentStages
layer over a recording transport, so the messages captured are exactly what a
provider would receive. Volatile timestamps are dropped before comparison.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from live.account_source_adaptation import adapt_source
from live.content_stages import ContentStages
from test_account_source_adaptation import FakeClient, source, ZH, EN

VOLATILE = {'snapshot_at', 'created_at', 'finished_at', 'recorded_at', 'as_of'}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


class Recorder:
    def __init__(self, inner):
        self.inner, self.sent = inner, []

    def __call__(self, stage, messages, max_tokens):
        self.sent.append({'stage': stage, 'messages': copy.deepcopy(messages), 'max_tokens': max_tokens,
                          'sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False,
                                                              sort_keys=True).encode()).hexdigest()})
        return self.inner(stage, messages, max_tokens)


def _media_row():
    row = source("Paragraph one sets context for the chart. " * 3 + "\n\n" + EN, "industry_writer", "en")
    row["media_dependencies"] = [{"kind": "chart", "required": None, "status": "uncertain_dependency",
                                  "selection_review_required": True, "url": "https://example.test/chart.png"}]
    return row


def _long_row():
    first = "Industry supply needs gradual verification, and technology paths need real demand. " * 75
    return source(first + "\n\n" + EN, "industry_writer", "en")


CASES = {
    'industry_long_selection': dict(row=_long_row, account='zh_industry', fake=lambda: FakeClient(
        'zh_industry', ZH, overrides={'selection': lambda v, p: {**v, 'paragraph_ids': ['P2']}}),
        item={'selection_reason': 'fixture', 'proposed_passages': ['P2']}, baseline={'summary': {'median_chars': 300}}),
    'morris_plain': dict(row=source, account='en_morris_archive', fake=lambda: FakeClient('en_morris_archive')),
    'morris_style_exception': dict(row=source, account='en_morris_archive', item={'style_exception': True,
                                   'selection_reason': 'fixture', 'proposed_passages': ['P1']},
                                   fake=lambda: FakeClient('en_morris_archive')),
    'industry_media_hygiene': dict(row=_media_row, account='zh_industry', fake=lambda: FakeClient('zh_industry', ZH),
                                   baseline={'summary': {'median_chars': 300}}),
    'industry_repairs': dict(row=_media_row, account='zh_industry', fake=lambda: FakeClient('zh_industry', ZH),
                             repairs=[{'name': 'hygiene_contract'}, {'name': 'translation_json_contract'}]),
}


def run_case(name):
    spec = CASES[name]
    with tempfile.TemporaryDirectory() as tmp:
        recorder = Recorder(spec['fake']())
        stages = ContentStages(Path(tmp) / 'calls', item=spec.get('item'), baseline=spec.get('baseline'),
                               client=recorder, execution_repairs=spec.get('repairs'))
        result = adapt_source(spec['row'](), spec['account'], tmp, stages)
    calls = [{'stage': c['stage'], 'max_tokens': c['max_tokens'],
              'system': c['messages'][0]['content'],
              'user': _strip(json.loads(c['messages'][1]['content'])),
              'roles': [m['role'] for m in c['messages']]} for c in recorder.sent]
    return {'status': result['status'], 'calls': calls}, result, recorder


def capture():
    return {name: run_case(name)[0] for name in CASES}


if __name__ == '__main__':
    import sys
    out = Path(__file__).resolve().parent / 'fixtures' / 'p0_prompt_golden.json'
    out.write_text(json.dumps(capture(), ensure_ascii=False, indent=1, sort_keys=True))
    print('wrote', out)
