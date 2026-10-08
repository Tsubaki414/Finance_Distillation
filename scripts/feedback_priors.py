#!/usr/bin/env python3
"""Nightly: /admin review decisions -> soft per-account priors + feedback stats + edit diffs (local only).

Reads live/store/admin_decisions/<day>.json (scripts/apply_admin_decisions.py) and the inbox rows; writes
live/store/feedback/priors.json, stats.json (counts and rates only, shown on /admin) and
style_examples/<account>.jsonl (edit diffs, never committed). No model calls, nothing is sent anywhere.
daily_compose reads priors.json next day as a soft prior (live/feedback.py; it only acts while FD_HOTSPOT is on).

FD_FEEDBACK_V2=1 (default): outcomes published as-is / published after edit / approved not published / unpicked /
held / rejected (live/feedback.py). FD_FEEDBACK_V2=0: the Oct 8 v1 rule (approve|published vs hold|rewrite), no
stats.json. FD_FEEDBACK=0 skips the step.

  python3 scripts/feedback_priors.py [--pull [--pull-days N]]   # --pull: apply_admin_decisions.py for the newest N
                                                                #  inbox days first (default 3)
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import feedback  # noqa: E402


def pull(days):
    for day in days:
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/apply_admin_decisions.py'), '--day', day,
                            '--store', str(feedback.decisions_dir())], capture_output=True, text=True, timeout=90)
        last = (r.stdout.strip().splitlines() or [''])[-1]
        print(f'pull {day}: exit {r.returncode} {last}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pull', action='store_true', help='pull the newest decisions from the console API first')
    ap.add_argument('--pull-days', type=int, default=3, help='newest N inbox days to pull (default 3)')
    args = ap.parse_args()
    if os.environ.get('FD_FEEDBACK', '1') == '0':
        print('FD_FEEDBACK=0: feedback priors off')
        return 0
    if args.pull:
        inbox = feedback.inbox_dir()
        pull(sorted(p.name for p in inbox.iterdir() if p.is_dir())[-args.pull_days:] if inbox.is_dir() else [])
    if not feedback.v2():
        result = feedback.build(feedback.collect())
        priors = feedback.write(result)
        (feedback.store_dir() / 'stats.json').unlink(missing_ok=True)   # no stale v2 panel on /admin
        n = sum(a['overall']['n'] for a in priors['accounts'].values())
        print(f"feedback v1: {len(priors['accounts'])} account(s), {n} decided draft(s), {len(result['edits'])} edit "
              f"example(s) -> {feedback.store_dir()}")
        return 0
    result = feedback.build_v2(feedback.classify(feedback.collect_days()))
    priors, stats = feedback.write_v2(result)
    t = stats['totals']
    moving = sum(len(k) for d in stats['active_multipliers'].values() for k in d.values())
    print(f"feedback v2: {len(stats['days'])} reviewed day(s), {len(priors['accounts'])} account(s), {t['drafts']} "
          f"draft(s): published {t['published']} (edited {t.get('published_edited', 0)}), approved "
          f"{t.get('approved', 0)}, held {t.get('held', 0)}, rejected {t.get('rejected', 0)}, unpicked "
          f"{t.get('unpicked', 0)}; {moving} prior key(s) past the minimum sample; {len(result['edits'])} edit "
          f"example(s) -> {feedback.store_dir()}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
