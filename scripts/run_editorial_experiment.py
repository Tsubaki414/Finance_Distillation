"""Run frozen real sources in an isolated editorial experiment; never writes the queue."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.editorial import EditorialPipeline
from live.distillation import export
from live.distillation_source import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', help='Comma-separated case names; does not affect model input')
    parser.add_argument('--accounts', type=Path, help='Explicit experiment account file, never changes production accounts')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required for paid calls')
    args.out.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.inputs.read_text())['cases']
    if args.cases:
        cases = [c for c in cases if c['case'] in args.cases.split(',')]
    assert cases
    protected = [ROOT / n for n in ['live/store/content_queue.json', 'live/store/analysis_corpus.jsonl', 'live/accounts.json']]
    before = {str(p): digest(p.read_text()) for p in protected}
    accounts = json.loads(args.accounts.read_text())['accounts'] if args.accounts else None
    pipeline = EditorialPipeline(args.out / 'artifacts', accounts=accounts)
    summary = {'experiment': True, 'inputs_hash': digest(args.inputs.read_text()),
               'accounts_ref': str(args.accounts) if args.accounts else 'live/accounts.json',
               'human_review': 'pending', 'cases': []}
    for case in cases:
        print('Start ' + case['case'], flush=True)
        result = pipeline.run(case['source'])
        export(result, args.out / case['case'])
        row = {'case': case['case'], 'role': case['role'], 'route': result.get('route'),
               'status': result['draft_status'], 'stage_calls': result['stage_calls'],
               'attempt_ref': result['attempt_ref'], 'error_detail': result.get('error_detail'),
               'ready_text': result['text'], 'candidate_text': (result.get('localization') or {}).get('text', '')}
        summary['cases'].append(row)
        print(json.dumps({'case': case['case'], 'status': row['status'], 'error': row['error_detail']}, ensure_ascii=False), flush=True)
        (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    summary['production_data_unchanged'] = all(digest(Path(p).read_text()) == h for p, h in before.items())
    (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(not summary['production_data_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())
