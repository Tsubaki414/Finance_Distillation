#!/usr/bin/env python3
"""Archive drafts (回看 then-vs-now / 常青 evergreen) for fd20 accounts, standalone (live/archive_lookback.py,
live/archive_evergreen.py). Never publishes.

  python scripts/archive_lookback.py --accounts crypto_altcoin_zh,crypto_macro_en --day 2026-10-08
      [--force]          skip the material-gap check (still at most 1 archive draft per account per day, 30-day cooldown)
      [--fetch-only]     gather material + rank candidates for both variants, no model call, nothing written
      [--no-gap-plan]    gap check from the inbox only (do not simulate the normal selection)
      [--refresh]        refetch X search pages even when cached
      [--recheck]        re-run the checks on the day's stored 回看 drafts (no fetch, no model call)
      [--judge]          with --recheck: also build the claim card and run the flash fidelity judge (model calls)
      [--rapid-cap N]    twitter241 calls for this run (also bounded by rapid_max_calls_per_day)
      [--budget-usd X]   Gemini spend for this run (also bounded by model_usd_per_day)
      [--inbox-base DIR] write to / read from a scratch inbox instead of live/store/compose_inbox
      [--media-out DIR]  chart output directory (default the ops media directory)

Default accounts: live/archive_lookback.json enabled_accounts ("all"; FD_ARCHIVE=0 turns everything off,
FD_ARCHIVE_ACCOUNTS narrows it). The gap check simulates scripts/daily_compose.select for the day (no model calls).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

from live import archive_evergreen as ae, archive_lookback as al  # noqa: E402


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
    ap.add_argument('--judge', action='store_true')
    ap.add_argument('--rapid-cap', type=int)
    ap.add_argument('--budget-usd', type=float)
    ap.add_argument('--inbox-base')
    ap.add_argument('--media-out')
    args = ap.parse_args()
    config = al.load_config()
    if args.recheck:
        ask = None
        if args.judge:
            client, _table = al.make_client(al.raw_dir() / 'runs' / args.day.isoformat() / 'recheck' / 'calls')

            def ask(messages):
                return al.ask_flash(client, messages, config.get('judge_stage', 'stance'))
        print(json.dumps(al.recheck(args.day.isoformat(), base=args.inbox_base, ask=ask), ensure_ascii=False,
                         default=str))
        return 0
    ids = args.accounts.split(',') if args.accounts else al.enabled_accounts(config)
    enabled = set(al.enabled_accounts(config))
    off = [a for a in ids if a not in enabled]
    if off:
        print(f'not enabled for archive drafts (FD_ARCHIVE / FD_ARCHIVE_ACCOUNTS / config): {off}')
        ids = [a for a in ids if a in enabled]
    if not ids:
        return 0
    if args.fetch_only:
        accounts = {a['id']: a for a in json.loads(al.ACCOUNTS.read_text())['accounts']}
        key = os.environ.get('RAPID_X_API_KEY')
        cap = min(args.rapid_cap if args.rapid_cap is not None else config.get('rapid_max_calls', 40),
                  max(0, config.get('rapid_max_calls_per_day', 40) - al.calls_on(args.day)))
        rapid = al.SearchClient(key, cap, al.store_dir() / 'fetch_log.jsonl', day=args.day) if key and cap else None
        for aid in ids:
            handles = al.handles_for(aid, limit=config.get('max_handles_per_account', 10))
            posts, calls = al.gather(aid, handles, args.day, config=config, client=rapid,
                                     allowance=config.get('rapid_max_calls_per_account_day', 4), refresh=args.refresh)
            used = al.used_recently(aid, args.day, config.get('event_cooldown_days', 30))
            tvn = al.candidates({('all', 'all'): posts}, accounts[aid], args.day, config=config, used=used)
            evg = ae.candidates(posts, accounts[aid], args.day, config=config, used=used,
                                past=ae.history(aid, args.day, base=args.inbox_base))
            print(f'[{aid}] handles={len(handles)} posts={len(posts)} calls={calls} then_vs_now={len(tvn)} '
                  f'evergreen_rules={len(evg)}')
            for c in evg[:5]:
                print(f"   EVG {c['date']} @{c['handle']} eng={c.get('engagement')} rel={c['engagement_rel']} "
                      f"rule={c['rule_score']} {c['url']}\n      {c['text'][:120]!r}")
            for c in tvn[:3]:
                print(f"   TVN {c['date']} @{c['handle']} {c['subject']['key']} {c['url']}\n      {c['text'][:120]!r}")
        print('rapid calls this run:', rapid.made if rapid else 0)
        return 0
    timely = {} if args.force or args.no_gap_plan else al.timely_planned_for(args.day, set(ids))
    summary = al.run(ids, args.day, timely_planned=timely, force=args.force, config=config, refresh=args.refresh,
                     inbox_base=args.inbox_base, media_out=args.media_out, rapid_cap=args.rapid_cap,
                     budget_usd=args.budget_usd)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
