"""Small, explicit live regression run. Never collects sources or writes the live queue."""
from pathlib import Path
import argparse
import json
import sys
import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.distillation import Pipeline, export
from live.distillation_source import digest

FIXTURES = ROOT / 'docs/audits/2026-09-29-distillation/regression_cases.json'


def fixture_source(case):
    text = '\n\n'.join(p['text'] for p in case['paragraphs'])
    # Case names and expected routing are NOT passed to any model.
    return {'id': digest(text)[:16], 'source_id': 'synthetic_fixture', 'text': text,
            'source_type': 'fixture', 'source_language': case['source_language'],
            'author': case['source_author'], 'url': case['source_url'],
            'title': 'Arbor Systems quarterly update' if len(case['paragraphs']) > 1 else '',
            'content_complete': True, 'extraction_status': 'complete_synthetic_fixture',
            'extractor_version': 'fixture-v1', 'synthetic': True,
            'entity_glossary': case['expected'].get('entity_glossary', {})}


def assertions(case, result):
    exp = case['expected']
    errors = []
    route = result.get('route') or {}
    for key in ('decision', 'account_id', 'target_language'):
        if route.get(key) != exp[key]:
            errors.append(f'{key}: {route.get(key)!r} != {exp[key]!r}')
    if exp['decision'] == 'SKIP':
        if result['draft_id'] or result['text'] or result['draft_status'] != 'skipped':
            errors.append('SKIP emitted a draft or did not terminate')
        if any(result['stage_calls'].get(s) for s in ('selection', 'translation', 'localization', 'qa')):
            errors.append('SKIP called downstream model stages')
    else:
        ids = [p['paragraph_id'] for p in (result.get('selection') or {}).get('passages', [])]
        selection = exp['selection']
        if not set(selection['required_paragraph_ids']).issubset(ids):
            errors.append('Required source paragraphs omitted')
        if set(selection.get('excluded_paragraph_ids', [])) & set(ids):
            errors.append('Unrelated paragraphs selected')
        if result['draft_status'] != 'draft_ready':
            errors.append(f"No ready draft: {result['why']} {result.get('error_detail') or ''}")
        if result['review_status'] != 'pending' or result.get('human_review') is not None:
            errors.append('Human approval fabricated')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly make the small paid relay run')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live for model execution; offline contract tests use unittest')
    out = args.out or ROOT / 'runs/localization_v1' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    queue_path = ROOT / 'live/store/content_queue.json'
    queue_before = digest(queue_path.read_text())
    corpus_path = ROOT / 'live/store/analysis_corpus.jsonl'
    corpus_before = digest(corpus_path.read_text())
    cases = json.loads(FIXTURES.read_text())['cases']
    pipeline = Pipeline(out / 'artifacts')
    summary = {'fixture_file_hash': digest(FIXTURES.read_text()), 'synthetic': True,
               'model_execution': 'live', 'human_review': 'pending', 'cases': []}
    for case in cases:
        result = pipeline.run(fixture_source(case))
        export(result, out / case['id'])
        errors = assertions(case, result)
        summary['cases'].append({'id': case['id'], 'status': result['draft_status'],
                                 'account_id': result.get('account_id'), 'target_language': result.get('target_language'),
                                 'stage_calls': result['stage_calls'], 'errors': errors,
                                 'exact_output': result['text'], 'attempt_ref': result['attempt_ref']})
        print(json.dumps({'case': case['id'], 'status': result['draft_status'], 'errors': errors}, ensure_ascii=False), flush=True)
        (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    summary['live_queue_unchanged'] = queue_before == digest(queue_path.read_text())
    summary['corpus_unchanged'] = corpus_before == digest(corpus_path.read_text())
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print('Artifacts: ' + str(out), flush=True)
    return 1 if any(c['errors'] for c in summary['cases']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
