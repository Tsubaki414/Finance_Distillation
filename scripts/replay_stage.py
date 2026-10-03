"""Offline replay of a recorded run (plan 1.3 subset).

Usage: replay_stage.py --input input.json --calls calls.jsonl [--from-call-logs DIR]
input.json holds {"account_id", "source"}; calls.jsonl holds recorded
responses (see live/recorded_client.py). --from-call-logs converts a
ContentStages call directory into calls.jsonl first. No network, no ledger.
Prints status, stages consumed, unrecorded requests and the final draft hash.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--calls', type=Path, required=True)
    ap.add_argument('--from-call-logs', type=Path)
    args = ap.parse_args()
    from live.recorded_client import RecordedClient, from_call_logs, load_calls
    from live.account_source_adaptation import adapt_source
    from live.content_stages import ContentStages
    from live.distillation_source import digest
    if args.from_call_logs:
        rows = from_call_logs(args.from_call_logs)
        args.calls.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    data = json.loads(args.input.read_text())
    client = RecordedClient(load_calls(args.calls))
    with tempfile.TemporaryDirectory() as tmp:
        result = adapt_source(data['source'], data['account_id'], Path(tmp),
                              ContentStages(Path(tmp) / 'calls', client=client))
    print(json.dumps({'status': result.get('status'), 'draft_status': result.get('draft_status'),
                      'execution_failure': result.get('execution_failure'),
                      'stages_consumed': client.used, 'unrecorded': client.misses,
                      'final_draft_sha256': digest(result.get('final_draft') or '')},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
