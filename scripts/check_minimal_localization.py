"""Focused live localization/QA probes; upstream routing/translation are frozen fixtures.

This is not a new end-to-end model run. No source collection or production queue writes.
"""
from pathlib import Path
import argparse
import copy
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.distillation import Pipeline, export
from live.distillation_client import RelayClient
from live.distillation_source import digest


class FrozenUpstreamClient:
    def __init__(self, baseline, baseline_ref, relay, translation=None, injected_edit=None):
        self.baseline, self.baseline_ref, self.relay = baseline, baseline_ref, relay
        self.translation, self.injected_edit = translation, injected_edit

    def __call__(self, stage, messages, max_tokens):
        if stage == 'routing':
            value = self.baseline['route']
        elif stage == 'translation':
            rows = copy.deepcopy(self.baseline['translation']['segments'])
            if self.translation is not None:
                assert len(rows) == 1
                rows[0]['text'] = self.translation
            value = {'segments': rows}
        elif stage == 'localization' and self.injected_edit:
            value = {'edits': [self.injected_edit], 'added_background': []}
        else:
            assert stage in ('localization', 'qa'), stage
            return self.relay(stage, messages, max_tokens)
        return {'text': json.dumps(value, ensure_ascii=False), 'finish_reason': 'stop',
                'model': 'FROZEN_TEST_INPUT', 'provider': 'fixture_replay',
                'baseline_ref': str(self.baseline_ref), 'usage': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only', choices=('natural_zh_unchanged', 'natural_en_unchanged',
                                         'one_grammar_fix', 'editorial_commentary_blocked'))
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required for up to seven paid localization/QA calls')
    args.out.mkdir(parents=True, exist_ok=False)
    protected = [ROOT / 'live/store/content_queue.json', ROOT / 'live/store/analysis_corpus.jsonl']
    before = {str(p): digest(p.read_text()) for p in protected}
    macro_ref = args.fixtures / 'EN_SHORT_TO_ZH_MACRO/metadata.json'
    industry_ref = args.fixtures / 'ZH_SHORT_TO_EN_INDUSTRY/metadata.json'
    macro, industry = [json.loads(p.read_text()) for p in (macro_ref, industry_ref)]
    natural_en = industry['translation']['text']
    awkward_en = natural_en.replace('costs on new contracts are front-loaded',
                                    'costs on new contracts is front-loaded')
    assert awkward_en != natural_en
    last_sentence = '但这并不能说明信贷需求已经回升。'
    assert last_sentence in macro['translation']['text']
    injected_edit = {'paragraph_id': 'P1', 'before': last_sentence,
                     'after': last_sentence + '这是一个有条件的判断，不能视为原文提供了复苏预测。',
                     'reason': 'Clarify the scope of the statement for readers',
                     'source_support': 'may ease if banks pass the cut through'}
    probes = [
        ('natural_zh_unchanged', macro, macro_ref, None, None, macro['translation']['text']),
        ('natural_en_unchanged', industry, industry_ref, None, None, natural_en),
        ('one_grammar_fix', industry, industry_ref, awkward_en, None, natural_en),
        ('editorial_commentary_blocked', macro, macro_ref, None, injected_edit, ''),
    ]
    if args.only:
        probes = [p for p in probes if p[0] == args.only]
    summary = {'scope': 'Frozen upstream fixtures; only localization/QA are live',
               'human_review': 'pending', 'probes': []}
    for name, baseline, ref, translation, injection, expected in probes:
        out = args.out / name
        relay = RelayClient(out / 'calls')
        client = FrozenUpstreamClient(baseline, ref, relay, translation, injection)
        result = Pipeline(out / 'artifacts', client=client).run(baseline['source'])
        export(result, out)
        expected_status = 'needs_review' if injection else 'draft_ready'
        checks = ((result.get('qa') or {}).get('semantic') or {}).get('checks', [])
        errors = []
        if result['draft_status'] != expected_status or result['text'] != expected:
            errors.append('Unexpected status or text; inspect untouched response logs')
        if injection and not any(c.get('no_editorial_commentary') is False for c in checks):
            errors.append('QA did not identify the editorial commentary')
        if name.startswith('natural_') and (result.get('localization') or {}).get('edits') != []:
            errors.append('Natural translation unnecessarily edited')
        if name == 'one_grammar_fix':
            edits = (result.get('localization') or {}).get('edits', [])
            if len(edits) != 1:
                errors.append('Expected a single local grammar correction')
        row = {'probe': name, 'status': result['draft_status'], 'errors': errors,
               'real_calls': relay.calls, 'exact_output': result['text'], 'attempt_ref': result['attempt_ref']}
        summary['probes'].append(row)
        print(json.dumps({'probe': name, 'status': row['status'], 'errors': errors}, ensure_ascii=False), flush=True)
        (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    summary['protected_data_unchanged'] = all(digest(Path(p).read_text()) == h for p, h in before.items())
    (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(not summary['protected_data_unchanged'] or any(p['errors'] for p in summary['probes']))


if __name__ == '__main__':
    raise SystemExit(main())
