#!/usr/bin/env python3
"""Nightly: /admin review decisions -> per-account approve rates by angle / 母题 type + edit diffs (local only).

Reads live/store/admin_decisions/<day>.json (scripts/apply_admin_decisions.py) and the inbox rows; writes
live/store/feedback/priors.json and live/store/feedback/style_examples/<account>.jsonl. No model calls, nothing is
sent anywhere. daily_compose reads priors.json next day as a soft prior (live/feedback.py). Off with FD_HOTSPOT=0.

  python3 scripts/feedback_priors.py [--pull]      # --pull: run apply_admin_decisions.py for the newest 3 days first
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import feedback  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pull', action='store_true', help='pull the newest decisions from the console API first')
    args = ap.parse_args()
    if os.environ.get('FD_HOTSPOT', '1') == '0':
        print('FD_HOTSPOT=0: feedback priors off')
        return 0
    if args.pull:
        days = sorted(p.name for p in feedback.inbox_dir().iterdir() if p.is_dir())[-3:] if feedback.inbox_dir().is_dir() else []
        for day in days:
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/apply_admin_decisions.py'), '--day', day],
                               capture_output=True, text=True, timeout=90)
            print(f'pull {day}: exit {r.returncode}')
    result = feedback.build(feedback.collect())
    priors = feedback.write(result)
    n = sum(a['overall']['n'] for a in priors['accounts'].values())
    print(f"feedback: {len(priors['accounts'])} account(s), {n} decided draft(s), {len(result['edits'])} edit example(s)"
          f" -> {feedback.store_dir()}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
