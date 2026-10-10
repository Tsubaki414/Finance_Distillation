#!/usr/bin/env python3
"""Apply the per-account line-end habit (live/line_end.py, Fiona Oct 10) to one inbox day's not-yet-posted drafts.

Skips drafts marked 已发 (published) in live/store/admin_decisions/<day>.json, drafts with any admin decision carrying
edited text, superseded rows and rows a human already reviewed. The day directory is copied to
live/store/backups/compose_inbox-<day>-pre-line-end-<stamp>/ first. Seeded by draft id, so re-running is a no-op.
Prints one line per changed draft; --dry-run writes nothing.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import compose_inbox, line_end  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--day', required=True)
    ap.add_argument('--inbox', type=Path, default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    base = Path(a.inbox or compose_inbox.root())
    day_dir = base / a.day
    dec_path = ROOT / 'live/store/admin_decisions' / f'{a.day}.json'
    decisions = json.loads(dec_path.read_text()).get('decisions', {}) if dec_path.exists() else {}
    if not a.dry_run:
        dest = ROOT / 'live/store/backups' / f'compose_inbox-{a.day}-pre-line-end-{datetime.now():%Y%m%d%H%M%S}'
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(day_dir, dest)
        print('backup', dest)
    changed = skipped = 0
    for p in sorted(day_dir.glob('*.json')):
        row = json.loads(p.read_text())
        d = decisions.get(row.get('id')) or {}
        if (d.get('published') is True or d.get('action') == 'published' or d.get('text')
                or row.get('superseded') or row.get('review_status', 'pending') != 'pending' or row.get('reviews')):
            skipped += 1
            continue
        body = row.get('body') or ''
        new_body = line_end.apply(body, row.get('account_id'), row['id'])
        if new_body == body:
            continue
        new_text = row.get('text') or ''
        new_text = new_text.replace(body, new_body, 1) if body and body in new_text else line_end.apply(
            new_text, row.get('account_id'), row['id'])
        row.update(body=new_body, text=new_text, text_hash=compose_inbox.text_hash(new_text),
                   line_end={'applied_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                             'before': body, 'source': 'scripts/apply_line_end_inbox.py'})
        if isinstance(row.get('thread'), list):
            row['thread'] = line_end.apply_parts([str(x) for x in row['thread']], row.get('account_id'), row['id'])
        changed += 1
        print(row['id'], row.get('account_id'))
        if not a.dry_run:
            p.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n')
    print(f'changed {changed}, skipped (published / reviewed / superseded) {skipped}')


if __name__ == '__main__':
    main()
