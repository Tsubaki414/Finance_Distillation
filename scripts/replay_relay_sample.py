"""Small real replay of stored runs through the erisedai relay (isolated).

Re-runs the saved source of each named run through the current account
adaptation pipeline with real relay calls. Writes only under --output; the
local call ledger is redirected to --output/ledger so no project ledger is
touched. Prints per-run status, failure code and per-stage assembly records.
Never publishes.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml import budget  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('runs', nargs='+')
    args = ap.parse_args()
    if os.environ.get('ACCOUNT_CONTENT_PROVIDER') != 'erisedai_relay':
        raise SystemExit('Set ACCOUNT_CONTENT_PROVIDER=erisedai_relay explicitly')
    args.output.mkdir(parents=True, exist_ok=True)
    budget.STORE = args.output / 'ledger'
    budget.LEDGER = budget.STORE / 'spend.json'
    from live.account_source_adaptation import adapt_source
    from live.content_stages import ContentStages
    report = []
    for rid in args.runs:
        path = next((args.store / 'runs').glob(rid + '*.json'))
        run = json.loads(path.read_text())
        adaptation = run.get('source_adaptation') or {}
        source = adaptation['source']
        out = args.output / run['id']
        stages = ContentStages(out / 'calls')
        try:
            result = adapt_source(source, run['account_id'], out, stages)
            attempt = result.get('attempt') or {}
            row = {'run': run['id'], 'account': run['account_id'], 'source_id': source.get('source_id'),
                   'historical_failure': (adaptation.get('execution_failure') or {}).get('code')
                   or adaptation.get('draft_status'),
                   'status': result.get('status'), 'draft_status': result.get('draft_status'),
                   'execution_failure': result.get('execution_failure'),
                   'stages': [(r['stage'], r['effective_template_id'], r['messages_sha256'][:12])
                              for r in attempt.get('prompt_assembly', [])],
                   'models': sorted({m.get('model') for m in attempt.get('model_responses', []) if m.get('model')}),
                   'final_draft_chars': len(result.get('final_draft') or '')}
        except Exception as exc:  # recorded, not hidden
            row = {'run': run['id'], 'account': run['account_id'], 'error_type': type(exc).__name__,
                   'error': str(exc)[:300]}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
