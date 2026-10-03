"""P0-3b: recover inbox rows blocked only on body completeness.

For each needs_source inbox row whose only body gap is "completeness
unverified": re-verify the stored source with the P0-3a/3c capture rule; if
verified, re-ingest (a new inbox row; the old row stays, append-only) and, when
a monitor DB exists, reset the monitor item through the existing revision path
(State.enqueue -> _revision_allowed). Scheduling is unchanged. Recovered rows
older than the account's freshness window are counted as stale, not unblocked.
Default is a dry run; --apply writes.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.account_intelligence import Store, DEFAULT, time, now  # noqa: E402
from live.account_monitor import State  # noqa: E402
from live.account_sources import admission, ingest, universe  # noqa: E402
from live.archive_verification import verify_archive_row  # noqa: E402

BODY_GAP = 'Original text completeness unverified'
MAX_AGE_HOURS = json.loads((ROOT / 'live/account_monitor.json').read_text())['max_source_age_hours']


def recover(store, *, as_of=None, apply=False):
    as_of = as_of or now()
    rows = store.rows('inbox')
    done = {(r['account_id'], store.get('sources', r['source_id'])['url']) for r in rows
            if r['status'] != 'needs_source'}
    report = Counter()
    details = []
    state = State(store.root) if (Path(store.root) / 'monitor.sqlite3').exists() else None
    for r in rows:
        if r['status'] != 'needs_source' or BODY_GAP not in r.get('blocking_gaps', []):
            continue
        source = store.get('sources', r['source_id'])
        if (r['account_id'], source.get('url')) in done:
            continue  # already recovered earlier
        report['candidates'] += 1
        verified = verify_archive_row({**source, 'content_complete': False})
        if not verified.get('content_complete'):
            report['still_unverified'] += 1
            details.append({'inbox': r['id'], 'result': 'unverified',
                            'reason': verified['archive_verification'].get('reason')})
            continue
        if [g for g in r['blocking_gaps'] if g != BODY_GAP]:
            report['still_blocked_other_gaps'] += 1
            details.append({'inbox': r['id'], 'result': 'other_gaps'})
            continue
        stale = (universe(r['account_id'])['mode'] != 'evergreen' and source.get('published_at')
                 and (time(as_of) - time(source['published_at'])).total_seconds() > MAX_AGE_HOURS * 3600)
        if not apply:
            verdict = admission(r['account_id'], verified)
            report[('would_recover_stale' if stale else 'would_recover') if verdict['admitted']
                   else 'would_not_admit:' + str(verdict.get('code') or 'other')] += 1
            continue
        row = {k: v for k, v in verified.items() if k not in ('id', 'source_hash', 'snapshot_at', 'source_version')}
        result = ingest(store, r['account_id'], row, batch_id='p0-recover-needs-source')
        if not result['admitted']:
            report['not_admitted:' + str(result.get('code') or 'other')] += 1
            continue
        cand = result['candidate']
        if cand['status'] != 'pending_selection':
            report['reingested_still_blocked'] += 1
            continue
        if state is not None:
            state.enqueue(r['account_id'], r['canonical_source_id'], {**row, 'content_complete': True}, as_of)
        report['recovered_stale' if stale else 'recovered'] += 1
        report['recovered_by_account:' + r['account_id']] += 1
        details.append({'inbox': r['id'], 'result': 'recovered', 'new_inbox': cand['id'], 'stale': bool(stale),
                        'account': r['account_id'], 'source': r['canonical_source_id']})
    for key in ('recovered', 'recovered_stale', 'would_recover', 'still_unverified', 'still_blocked_other_gaps'):
        report.setdefault(key, 0)
    return {**report, 'apply': apply, 'as_of': as_of, 'monitor_db': state is not None, 'details': details}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--store', type=Path, default=DEFAULT)
    ap.add_argument('--as-of')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    out = recover(Store(args.store), as_of=args.as_of, apply=args.apply)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
