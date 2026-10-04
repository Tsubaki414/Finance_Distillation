#!/usr/bin/env python3
"""Enrich legacy store views through the budgeted relay; never rewrite units."""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live.content_store import ContentStore
from live.view_enrich import enrich_views
from ml import budget


def enrich_store(store, run, *, cap_usd=3.0, max_calls=None, client=None):
    if not math.isfinite(cap_usd) or cap_usd <= 0:
        raise ValueError('cap_usd must be positive and finite')
    if max_calls is not None and (type(max_calls) is not int or max_calls < 0):
        raise ValueError('max_calls must be a nonnegative integer or None')
    run = Path(run)
    run.mkdir(parents=True, exist_ok=True)
    budget.STORE = run / 'ledger'
    budget.LEDGER = budget.STORE / 'spend.json'
    budget.DISTILLATION_RUNS = budget.STORE / 'distillation_spend.jsonl'
    budget.RUNS = budget.STORE / 'review_runs.jsonl'
    prior = json.loads(budget.LEDGER.read_text()).get('spent_usd', 0.0) if budget.LEDGER.exists() else 0.0
    budget.set_cap(float(prior) + cap_usd)
    store = store if isinstance(store, ContentStore) else ContentStore(store)
    records = store.units()
    # Persist each completed batch before another paid call; reruns skip successes.
    from live.view_enrich import BATCH_SIZE, has_valid_view, VERSION
    candidates = [r for r in records if r['unit'].get('kind') == 'view' and not has_valid_view(r['unit'])]
    report = dict(version=VERSION, enriched=[], invalid=[], calls=0, deferred=len(candidates), by_adapter={})
    by_uid = {r['unit_id']: r for r in records}
    journal = run / 'view_enrich_report.json'
    def save():
        journal.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    save()
    for start in range(0, len(candidates), BATCH_SIZE):
        if max_calls is not None and report['calls'] >= max_calls:
            break
        try:
            if client is None:
                from live.erisedai_distillation_client import ErisedaiClient
                client = ErisedaiClient(run / 'view_enrich_calls')
            result = enrich_views(candidates[start:start + BATCH_SIZE], client, max_calls=1)
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            save()
            raise
        store.set_view_enrichments(result['enriched'])
        report['calls'] += result['calls']
        report['deferred'] -= len(candidates[start:start + BATCH_SIZE])
        for status in ('enriched', 'invalid'):
            report[status].extend(result[status])
            for entry in result[status]:
                adapter = by_uid[entry['unit_id']]['source'].get('adapter') or 'unknown'
                counts = report['by_adapter'].setdefault(adapter, dict(enriched=0, invalid=0))
                counts[status] += 1
        save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--cap-usd', type=float, default=3.0)
    parser.add_argument('--max-calls', type=int)
    args = parser.parse_args(argv)
    report = enrich_store(args.store, args.run, cap_usd=args.cap_usd, max_calls=args.max_calls)
    print(json.dumps({'enriched': len(report['enriched']), 'invalid': len(report['invalid']),
                      'calls': report['calls'], 'deferred': report['deferred'],
                      'by_adapter': report['by_adapter']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
