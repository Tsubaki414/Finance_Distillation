#!/usr/bin/env python3
"""回看 (archive / look-back) drafts for fd20 accounts, standalone (live/archive_lookback.py). Never publishes.

  python scripts/archive_lookback.py --accounts crypto_altcoin_zh,crypto_macro_en --day 2026-10-08
      [--force]          skip the material-gap check (still at most 1 回看 per account per day, 30-day event cooldown)
      [--fetch-only]     fetch + rank candidates, no model call, nothing written to the inbox
      [--no-gap-plan]    gap check from the inbox only (do not simulate the normal selection)
      [--refresh]        refetch X search pages even when cached
      [--recheck]        re-run the checks on the day's stored 回看 drafts (no fetch, no model call)

Default accounts: live/archive_lookback.json enabled_accounts (FD_ARCHIVE=0 turns everything off). The gap check
simulates scripts/daily_compose.select for the day (no model calls) and runs only for accounts whose ready drafts
plus timely planned packets stay below target_ready_per_day.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

from live import archive_lookback as al  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--accounts')
    ap.add_argument('--day', type=date.fromisoformat, default=datetime.now(ZoneInfo('Asia/Shanghai')).date(),
                    help='Beijing day (inbox day directory)')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--fetch-only', action='store_true')
    ap.add_argument('--no-gap-plan', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--recheck', action='store_true')
    args = ap.parse_args()
    config = al.load_config()
    if args.recheck:
        print(json.dumps(al.recheck(args.day.isoformat()), ensure_ascii=False, default=str))
        return 0
    ids = args.accounts.split(',') if args.accounts else al.enabled_accounts(config)
    enabled = set(al.enabled_accounts(config))
    off = [a for a in ids if a not in enabled]
    if off:
        print(f'not enabled for 回看 (FD_ARCHIVE / live/archive_lookback.json): {off}')
        ids = [a for a in ids if a in enabled]
    if not ids:
        return 0
    if args.fetch_only:
        import os
        accounts = {a['id']: a for a in json.loads(al.ACCOUNTS.read_text())['accounts']}
        key = os.environ.get('RAPID_X_API_KEY')
        rapid = al.SearchClient(key, config.get('rapid_max_calls', 150), al.store_dir() / 'fetch_log.jsonl') if key else None
        for aid in ids:
            handles = al.handles_for(aid, limit=config.get('max_handles_per_account', 10))
            fetched = al.fetch_posts(aid, handles, args.day, config=config, client=rapid, refresh=args.refresh)
            cands = al.candidates(fetched, accounts[aid], args.day, config=config,
                                  used=al.used_recently(aid, args.day, config.get('event_cooldown_days', 30)))
            print(f'[{aid}] handles={[h for h, _ in handles]} posts={sum(len(v) for v in fetched.values())} '
                  f'eligible={len(cands)}')
            for c in cands[:8]:
                print(f"   {c['window']} {c['date']} @{c['handle']} {c['subject']['key']} {c['url']}\n      "
                      f"{c['text'][:160]!r}")
        print('rapid calls this run:', rapid.made if rapid else 0)
        return 0
    timely = {} if args.force or args.no_gap_plan else al.timely_planned_for(args.day, set(ids))
    summary = al.run(ids, args.day, timely_planned=timely, force=args.force, config=config, refresh=args.refresh)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
