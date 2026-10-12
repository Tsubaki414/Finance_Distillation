#!/usr/bin/env python3
"""Replay the Oct 11 auto_published match log after the Vercel Blob store is reactivated.

The 2026-10-11 auto_published.py run matched 113 tweet URLs successfully but all POSTs to
/api/decisions returned HTTP 500 because the Blob store was suspended. Once reactivated:

  python3 scripts/replay_decisions_1011.py [--dry-run]

This will:
  1. Read live/store/auto_published/2026-10-11.json (the match log)
  2. Re-POST each matched entry to /api/decisions (same payload format as auto_published.py)
  3. Overwrite the error field with the result in the log
  4. Then run perf_review.py --fetch --days 2026-10-11 to collect engagement metrics

PREREQUISITE: Blob store must be reactivated first. Test with:
  curl -s -X POST https://fd-ops-dashboard.vercel.app/api/decisions \\
    -H 'Content-Type: application/json' \\
    -d '{"day":"2026-10-11","id":"test-probe","account_id":"test","action":"approve"}' | grep -v suspended
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DECISIONS_API = 'https://fd-ops-dashboard.vercel.app/api/decisions'
LOG = ROOT / 'live' / 'store' / 'auto_published' / '2026-10-11.json'


def probe_blob(api_url):
    """Return True when the Blob store is accessible (no 'suspended' error)."""
    try:
        data = json.dumps({'day': '2026-10-11', 'id': '_probe_replay', 'account_id': 'test',
                           'action': 'approve'}, ensure_ascii=False).encode()
        req = urllib.request.Request(api_url, data=data, method='POST',
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode())
        if 'Blob' in str(resp.get('error', '')):
            print(f'Blob still suspended: {resp["error"]}', file=sys.stderr)
            return False
        return True
    except Exception as exc:
        print(f'Probe failed: {exc}', file=sys.stderr)
        return False


def post_decision(api_url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(api_url, data=data, method='POST',
                                 headers={'Content-Type': 'application/json', 'Cache-Control': 'no-store'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true', help='print what would be sent, no POSTs')
    ap.add_argument('--api', default=DECISIONS_API)
    ap.add_argument('--skip-perf', action='store_true', help='skip perf_review fetch after replay')
    args = ap.parse_args(argv)

    if not LOG.exists():
        print(f'No match log at {LOG}', file=sys.stderr)
        return 1

    log = json.loads(LOG.read_text())
    to_replay = [e for e in log if e.get('tweet_url') and e.get('error')]
    already_marked = [e for e in log if e.get('marked')]
    print(f'Match log: {len(log)} entries, {len(to_replay)} with errors to replay, '
          f'{len(already_marked)} already marked')

    if not to_replay:
        print('Nothing to replay.')
        return 0

    if not args.dry_run:
        print('Probing Blob store...', end=' ', flush=True)
        if not probe_blob(args.api):
            print('\nAbort: Blob store still suspended. Reactivate in Vercel dashboard first.', file=sys.stderr)
            return 1
        print('OK')

    n_ok, n_err = 0, 0
    for entry in to_replay:
        payload = {'day': entry['day'], 'id': entry['draft_id'],
                   'account_id': entry['account_id'], 'action': 'published'}
        if args.dry_run:
            print(f'[dry-run] {entry["account_id"]} {entry["draft_id"][:20]}… -> {entry["tweet_url"][-40:]}')
            n_ok += 1
            continue
        try:
            post_decision(args.api, payload)
            entry['marked'] = True
            entry.pop('error', None)
            print(f'marked: {entry["account_id"]} {entry["draft_id"][:20]}… ({entry["tweet_url"][-40:]})')
            n_ok += 1
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f'FAIL {entry["draft_id"][:20]}: {exc}', file=sys.stderr)
            entry['error'] = str(exc)
            n_err += 1

    if not args.dry_run:
        LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + '\n')
        print(f'Updated {LOG}: {n_ok} marked, {n_err} errors')

    if not args.dry_run and not args.skip_perf and n_ok > 0:
        print('\nRunning perf_review --fetch for 2026-10-11...')
        perf_out = '/workspace/x/perf/daily'
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'perf_review.py'),
             '--fetch', '--days', '2026-10-11', '--max-requests', '45', '--out', perf_out],
            check=False
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
