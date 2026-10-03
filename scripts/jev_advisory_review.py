#!/usr/bin/env python3
"""Preview Jev advisory requests, or explicitly review existing records with --live.

No source, draft, machine QA, human review or publishing state is changed. The
default is a local request packet with no provider calls. Each live record keeps
its original run identity; failed records require an explicit --retry.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live.account_intelligence import DEFAULT, Store


def packet_run_ids(path):
    """Read the frozen human-review packet, keeping identity/order and no repeats."""
    packet = json.loads(Path(path).read_text(encoding='utf-8'))
    accounts = packet.get('accounts') if isinstance(packet, dict) else None
    if not isinstance(accounts, list):
        raise ValueError('Expected a review packet with an accounts list')
    ids = []
    for account in accounts:
        drafts = account.get('drafts') if isinstance(account, dict) else None
        if not isinstance(drafts, list):
            raise ValueError('Expected drafts in each review-packet account')
        for draft in drafts:
            rid = draft.get('run_id') if isinstance(draft, dict) else None
            if not isinstance(rid, str) or not rid.strip():
                raise ValueError('Every draft must preserve its original run_id')
            if rid not in ids:
                ids.append(rid)
    if not ids:
        raise ValueError('The review packet has no drafts')
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true',
                        help='Make paid Jev requests; omitted means preview only')
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument('--run-id', action='append', help='Original run ID; repeat for several runs')
    targets.add_argument('--packet', type=Path, help='Frozen human-review packet containing run IDs')
    targets.add_argument('--pending-limit', type=int, default=None,
                         help='Read the next 1–3 eligible records (default: 3)')
    parser.add_argument('--retry', action='store_true',
                        help='Explicitly retry failed/blocked/interrupted advice for named runs; requires --live')
    parser.add_argument('--store', type=Path, default=DEFAULT)
    parser.add_argument('--output-dir', type=Path, help='New directory for preview/collection receipts')
    args = parser.parse_args(argv)
    if args.pending_limit is not None and not 1 <= args.pending_limit <= 3:
        parser.error('--pending-limit must be between 1 and 3')
    if args.retry and (not args.live or not (args.run_id or args.packet)):
        parser.error('--retry requires --live and explicit --run-id or --packet targets')

    from live.jev_advisory import packet_for_run, pending_runs, review_run

    store = Store(args.store)
    try:
        if args.packet:
            run_ids = packet_run_ids(args.packet)
        elif args.run_id:
            run_ids = list(dict.fromkeys(args.run_id))
        else:
            run_ids = [row['id'] for row in pending_runs(store, limit=args.pending_limit or 3)]
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'stage': 'select_records',
                          'error_type': type(exc).__name__, 'live_call_made': False}))
        return 2

    out = args.output_dir or ROOT / 'runs/jev_advisory_review' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    entries = []
    packets = []
    for run_id in run_ids:
        try:
            if args.live:
                result = review_run(store, run_id, retry=args.retry)
                entries.append({'run_id': run_id, 'result': result})
            else:
                packet = packet_for_run(store, store.get('runs', run_id))
                packets.append(packet)
                requests = packet.get('requests', [])
                gaps = [{'request_id': request['id'], 'blocked_reason': request['blocked_reason'],
                         'coverage': request.get('coverage')}
                        for request in requests if request.get('blocked_reason')]
                entries.append({'run_id': run_id, 'status': 'prepared_with_gaps' if gaps else 'prepared',
                                'live_call_made': False, 'request_count': len(requests),
                                'blocked_request_count': len(gaps), 'coverage_gaps': gaps})
        except Exception as exc:
            entries.append({'run_id': run_id, 'status': 'failed',
                            'error_type': type(exc).__name__})
    if not args.live:
        (out / 'review_packets.json').write_text(
            json.dumps(packets, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    statuses = [row.get('status', row.get('result', {}).get('status')) for row in entries]
    successes = {'completed', 'not_applicable'} if args.live else {'prepared'}
    errors = sum(status not in successes for status in statuses)
    unfinished = any(status in {'running', 'interrupted', 'pending'} for status in statuses)
    status = ('incomplete' if unfinished else 'completed_with_issues' if errors else 'completed') if args.live else (
        'prepared_with_gaps' if errors else 'prepared')
    summary = {'status': status,
               'mode': 'live' if args.live else 'preview', 'advisory_only': True,
               'human_review_required': True, 'production_changes': False,
               'record_count': len(entries), 'issue_count': errors,
               'output_dir': str(out), 'records': entries}
    if not args.live:
        summary.update(request_count=sum(row.get('request_count', 0) for row in entries),
                       blocked_request_count=sum(row.get('blocked_request_count', 0) for row in entries),
                       coverage_gaps=[{'run_id': row['run_id'], **gap}
                                      for row in entries for gap in row.get('coverage_gaps', [])])
    (out / 'result.json').write_text(
        json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
    # Output only stable result metadata. Detailed source-bearing requests and
    # responses remain in their persisted files for the human reviewer.
    print(json.dumps({key: value for key, value in summary.items() if key != 'records'},
                     ensure_ascii=False))
    return 2 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
