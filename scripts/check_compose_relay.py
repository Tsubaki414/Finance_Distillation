"""P0-4e relay behaviour check: COMPOSE on stored sources (isolated).

EXTRACT responses are replayed from --extract-calls/<run>/calls when present
(no new extract call); COMPOSE goes to the relay. Call logs and the local
ledger stay under --output. Reports post_type, frame, body length, post-check
codes and the draft text. Drafts are never publishable (persona voice D2).
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml import budget  # noqa: E402


class Hybrid:
    def __init__(self, recorded, live):
        self.recorded, self.live, self.sources = recorded, live, []

    def __call__(self, stage, messages, max_tokens):
        from live.recorded_client import UnrecordedCall
        if self.recorded is not None:
            try:
                out = self.recorded(stage, messages, max_tokens)
                self.sources.append((stage, 'recorded'))
                return out
            except UnrecordedCall:
                pass
        self.sources.append((stage, 'relay'))
        return self.live(stage, messages, max_tokens)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--extract-calls', type=Path)
    ap.add_argument('pairs', nargs='+', help='run_id=account_id')
    args = ap.parse_args()
    if os.environ.get('ACCOUNT_CONTENT_PROVIDER') != 'erisedai_relay':
        raise SystemExit('Set ACCOUNT_CONTENT_PROVIDER=erisedai_relay explicitly')
    args.output.mkdir(parents=True, exist_ok=True)
    budget.STORE = args.output / 'ledger'
    budget.LEDGER = budget.STORE / 'spend.json'
    from live import compose
    from live.erisedai_distillation_client import ErisedaiClient
    from live.recorded_client import RecordedClient, from_call_logs
    report = []
    for pair in args.pairs:
        rid, account = pair.split('=')
        run = json.loads(next((args.store / 'runs').glob(rid + '*.json')).read_text())
        source = run['source_adaptation']['source']
        recorded = None
        if args.extract_calls and (args.extract_calls / rid / 'calls').exists():
            recorded = RecordedClient(from_call_logs(args.extract_calls / rid / 'calls'))
        client = Hybrid(recorded, ErisedaiClient(args.output / rid / 'calls'))
        row = {'run': rid, 'account': account, 'source_id': source['source_id']}
        try:
            result = compose.compose_source(source, account, client)
            row.update(post_type=result.get('post_type'), draft_status=result['draft_status'],
                       frame=(result.get('attribution_frame') or {}).get('text'), length=result.get('length'),
                       post_check_codes=sorted({f['code'] for f in result.get('post_checks', [])}),
                       post_checks=result.get('post_checks'), units_used=len(result.get('units', [])),
                       claim_ledger=len(result.get('claim_ledger', [])), persona=result.get('persona'),
                       publishable=result['publishable'], calls=client.sources, text=result.get('text'))
            (args.output / rid / 'compose.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
        except Exception as exc:  # recorded, not hidden
            row.update(status='FAIL', error_type=type(exc).__name__, error=str(exc)[:300], calls=client.sources)
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
