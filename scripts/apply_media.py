"""Attach post_mode (original / quote / reply) and fetched-data charts to a day's ready inbox drafts, in place.

Text is never rewritten. Charts go under the dashboard deploy dir (<out>/media/<day>/<id>.png + .json spec);
a draft gets no chart when no provider returns data.

  python3 scripts/apply_media.py --day 2026-10-07 [--out /workspace/x/dashboard/ops] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import draft_media  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--day', required=True)
    ap.add_argument('--out', type=Path, default=draft_media.MEDIA_OUT)
    ap.add_argument('--dry-run', action='store_true', help='decide and render, but do not write inbox rows')
    args = ap.parse_args()
    summary = draft_media.apply_day(args.day, out_dir=args.out, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
