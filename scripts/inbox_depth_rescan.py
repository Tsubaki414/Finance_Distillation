#!/usr/bin/env python3
"""Re-run the calibrated depth check on already-written inbox rows (Oct 15, after FD_DEPTH_HOLD_CAL).

FD_DEPTH_HOLD_CAL only changes compose-time checks; rows written before it are still held 'hard: depth'. This script
re-runs live/depth_check.findings on the stored body with what the row itself carries (post_type, post_kind, source
title / original_text / text / summary, units - a field the row lacks is passed as None, never guessed) and flips a
row back to draft_ready only when ALL hold:
  - held, draft_status needs_review, review_status pending, not superseded, no arbitration HOLD / lane_fit /
    stale_frame / audit / triage mark;
  - hold_reason is 'hard: <codes>' or 'model_error: <codes>' and the hard codes (hold_reason + findings level hard)
    are exactly {'depth'};
  - the calibrated check now returns [] (FD_DEPTH_CHECK and FD_DEPTH_HOLD_CAL both on, else nothing flips).
On a flip: held=False, draft_status=draft_ready, hold_reason=None, the depth findings are dropped, publishable is left
as stored, the old state goes under depth_rescan. The original file is copied to <backup>/<day>/<id>.json first.

Default is a dry run (no writes). Writes need APPLY=1 (or --apply); FD_INBOX_DEPTH_RESCAN=0 forces a dry run.
  python scripts/inbox_depth_rescan.py 2026-10-15                # dry run tally
  APPLY=1 python scripts/inbox_depth_rescan.py 2026-10-15        # write flips (+ backup)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import compose_inbox, depth_check  # noqa: E402

BACKUP = Path('/workspace/x/depth_hold_cal/rescan_backup')
SOURCE_KEYS = ('title', 'original_text', 'text', 'summary')   # as daily_compose passes source_text
_REASON = re.compile(r'^(hard|model_error):\s*(.*)$')


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_INBOX_DEPTH_RESCAN', '1') != '0'


def apply_requested(env=None, flag=False):
    return bool(flag) or (env if env is not None else os.environ).get('APPLY') == '1'


def _hard_codes(row):
    m = _REASON.match(str(row.get('hold_reason') or ''))
    codes = {c.strip() for c in m.group(2).split(',') if c.strip()} if m else set()
    codes |= {f.get('code') for f in row.get('findings') or [] if isinstance(f, dict) and f.get('level') == 'hard'}
    return m, codes


def classify(row, env=None):
    """(verdict, detail): flip / stay_held / other_hard / not_candidate."""
    m, codes = _hard_codes(row)
    if 'depth' not in codes:
        return 'not_candidate', 'no hard depth'
    if row.get('superseded'):
        return 'not_candidate', 'superseded'
    if (not row.get('held') or row.get('draft_status') != 'needs_review'
            or (row.get('review_status') or 'pending') != 'pending' or not (row.get('body') or '').strip()):
        return 'not_candidate', 'not a pending held needs_review row'
    if ((row.get('arbitration') or {}).get('status') == 'HOLD' or row.get('lane_fit') or row.get('stale_frame')
            or row.get('audit') or row.get('triage') or not m):
        return 'other_hard', 'non-check hold: ' + str(row.get('hold_reason'))[:60]
    if codes != {'depth'}:
        return 'other_hard', ','.join(sorted(codes - {'depth'}))
    src = row.get('source') if isinstance(row.get('source'), dict) else {}
    now = depth_check.findings(row.get('body') or '', row.get('lang'), row.get('post_kind'), env=env,
                               source_text=' '.join(str(src.get(k) or '') for k in SOURCE_KEYS).strip() or None,
                               post_type=row.get('post_type'), units=row.get('units'))
    return ('stay_held', 'depth still holds') if now else ('flip', m.group(1))


def flipped(row, at, backup_path):
    out = dict(row)
    out['depth_rescan'] = {'at': at, 'old_held': row.get('held'), 'old_draft_status': row.get('draft_status'),
                           'old_hold_reason': row.get('hold_reason'),
                           'removed_findings': [f for f in row.get('findings') or []
                                                if isinstance(f, dict) and f.get('code') == 'depth'],
                           'check': 'live/depth_check.findings FD_DEPTH_HOLD_CAL', 'backup': str(backup_path)}
    out['findings'] = [f for f in row.get('findings') or [] if not (isinstance(f, dict) and f.get('code') == 'depth')]
    out.update(held=False, draft_status='draft_ready', hold_reason=None)   # publishable left as stored
    return out


def run(day, base=None, backup=None, env=None, apply=False):
    env = env if env is not None else os.environ
    write = apply and enabled(env)
    if not (depth_check.enabled(env) and depth_check.cal_enabled(env)):
        raise SystemExit('FD_DEPTH_CHECK / FD_DEPTH_HOLD_CAL is off: a rescan would flip every depth row; refusing')
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    out = []
    for path in sorted((Path(base or compose_inbox.root()) / day).glob('*.json')):
        row = json.loads(path.read_text())
        verdict, detail = classify(row, env)
        if verdict == 'not_candidate' and detail == 'no hard depth':
            continue
        item = {'id': row.get('id'), 'account_id': row.get('account_id'), 'post_type': row.get('post_type'),
                'verdict': verdict, 'detail': detail, 'written': False}
        if verdict == 'flip' and write:
            bpath = Path(backup or BACKUP) / day / path.name
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if not bpath.exists():   # keep the first original if the rescan is re-run
                shutil.copy2(path, bpath)
            path.write_text(json.dumps(flipped(row, at, bpath), ensure_ascii=False, indent=2, default=str) + '\n')
            item['written'] = True
        out.append(item)
    return {'day': day, 'mode': 'apply' if write else 'dry_run', 'at': at,
            'tally': dict(Counter(i['verdict'] for i in out)), 'rows': out}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('days', nargs='+')
    ap.add_argument('--apply', action='store_true', help='write flips (same as APPLY=1)')
    ap.add_argument('--base', help='inbox root (default compose_inbox.root())')
    ap.add_argument('--backup', help=f'backup root (default {BACKUP})')
    ap.add_argument('--json', help='write the full result to this file')
    a = ap.parse_args(argv)
    want = apply_requested(flag=a.apply)
    if want and not enabled():
        print('FD_INBOX_DEPTH_RESCAN=0: dry run only')
    res = [run(d, a.base, a.backup, apply=want) for d in a.days]
    for r in res:
        print(r['day'], r['mode'], r['tally'], 'written', sum(i['written'] for i in r['rows']))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2) + '\n')
    return res


if __name__ == '__main__':
    main()
