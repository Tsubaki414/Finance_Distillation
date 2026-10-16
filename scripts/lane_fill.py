#!/usr/bin/env python
"""Oct 16 (lanes): stand-alone fill lanes that do not wait for (or block) the main compose.

  python scripts/lane_fill.py --lane fill    [--day YYYY-MM-DD] [--accounts a,b]   # 回看 / 常青 / archive fill
  python scripts/lane_fill.py --lane mindmap [--day YYYY-MM-DD] [--accounts a,b]   # mind-map last tier (needs FD_MINDMAP_FILL=1)

Each lane takes its own flock (.lane_<lane>.lock) and exits 0 with "lane busy" when a run of the SAME lane is active; it
never looks at the main compose lock. Rows go through live/compose_inbox (atomic, unique ids: arc- / evg- / mm- prefixes
come from the generators), ledgers through live/lanes locks. FD_LANES=0 refuses to run (the old in-process hooks of
daily_compose.py remain the only path). No publishing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from live import fd_accounts, lanes  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--lane', choices=('fill', 'mindmap'), required=True)
    ap.add_argument('--day')
    ap.add_argument('--accounts')
    args = ap.parse_args(argv)
    if not lanes.enabled():
        print('FD_LANES=0: lane runner off (use the daily_compose.py hooks)')
        return 0
    os.environ['FD_LANE'] = args.lane
    day = args.day or datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with lanes.lane_lock(args.lane) as got:
        if not got:
            print(f'lane {args.lane} busy: another run of this lane is active; skip')
            return 0
        ids = args.accounts.split(',') if args.accounts else [a['id'] for a in fd_accounts.rows(ROOT / 'live' / 'fd20_accounts.json')]
        if args.lane == 'fill':
            from live import archive_lookback
            out = archive_lookback.fill_gaps(day, accounts=ids)
        else:
            from live.mindmap import fill as mm
            out = mm.fill_gaps(day, accounts=ids)
    print(json.dumps({'lane': args.lane, 'day': day, 'result': out}, ensure_ascii=False, default=str)[:4000])
    return 0


if __name__ == '__main__':
    sys.exit(main())
