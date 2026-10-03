"""P0-4d relay behaviour check: run EXTRACT on stored sources through the relay.

Isolated: call logs and the local ledger go under --output only. For each
run: licence tier, units count by kind, numbers count, and either PASS (the
code-enforced contract accepted every unit) or the contract error. Call logs
can be reused as recorded fixtures (live/recorded_client.py). Never publishes.
"""
import argparse
import collections
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
    from live import content_units, registry, attribution_frame
    from live.erisedai_distillation_client import ErisedaiClient
    report = []
    for rid in args.runs:
        run = json.loads(next((args.store / 'runs').glob(rid + '*.json')).read_text())
        source = run['source_adaptation']['source']
        tier = registry.source_licence_tier(source['source_id'])
        client = ErisedaiClient(args.output / rid / 'calls')
        row = {'run': rid, 'source_id': source['source_id'], 'licence_tier': tier,
               'chars': len(source['original_text'])}
        try:
            result = content_units.extract(source, client, licence_tier=tier,
                                           publisher=attribution_frame.publisher_name(source['source_id']))
            units = result['units']
            row.update(status='PASS', units=len(units),
                       kinds=dict(collections.Counter(u['kind'] for u in units)),
                       numbers=sum(len(u['numbers']) for u in units),
                       span_match_rate=result['span_match_rate'], response=result['response'])
            (args.output / rid / 'units.json').write_text(json.dumps(units, ensure_ascii=False, indent=1))
        except Exception as exc:  # recorded, not hidden
            row.update(status='FAIL', error_type=type(exc).__name__, error=str(exc)[:300])
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
