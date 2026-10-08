#!/usr/bin/env python3
"""Pull review-console decisions into the local store (no model calls, no publishing, the inbox is not modified).

Sources (merged, the newer `at` wins per draft):
  default      GET https://fd-ops-dashboard.vercel.app/api/decisions?day=<day> (no auth; the site is unlisted)
  --file F     a "导出决定 JSON" export from /admin (the localStorage fallback); repeatable
  --no-api     skip the API (file only)

Writes live/store/admin_decisions/<day>.json ({day, updated_at, decisions: {draft id: decision}}), which
scripts/build_ops_dashboard.py overlays on the next rebuild: approve -> ready (with the edited text if any),
hold / rewrite -> HOLD, edit -> edited text only, published (marked
after a human posted it) -> ready. scripts/feedback_priors.py turns the decisions into next-day soft priors. Rewrite requests also go to
live/store/admin_decisions/<day>.rewrite_notes.json ({draft id: note}) for
`daily_compose.py --fill --rewrite-notes <that file>`.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store/admin_decisions'
API = 'https://fd-ops-dashboard.vercel.app/api/decisions'
ACTIONS = {'approve', 'published', 'hold', 'rewrite', 'edit', 'clear'}   # published: a human posted it


def fetch_api(url, day):
    req = urllib.request.Request(f'{url}?day={day}', headers={'Cache-Control': 'no-store'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get('decisions') or {}


def clean(d):
    if not isinstance(d, dict) or not d.get('id') or d.get('action') not in ACTIONS:
        return None
    text = d.get('text')
    # published (bool, the shared 已发 flag) and before_publish (the verdict under it) are kept: an approve / edit
    # after 已发 keeps the flag, so `action` alone under-counts what was posted (live/feedback.py reads both).
    # Older blobs have no flag: None, and action 'published' alone then means posted (decisions.js isPublished).
    pub = d.get('published')
    before = d.get('before_publish')
    return {'id': str(d['id']), 'account_id': d.get('account_id') or '', 'action': d['action'],
            'text': text.strip() if isinstance(text, str) and text.strip() else None,
            'note': d.get('note') or '', 'at': d.get('at') or '', 'history': d.get('history') or [],
            'published': pub if isinstance(pub, bool) else None,
            'before_publish': before if before in ACTIONS - {'published', 'clear'} else None}


def is_published(d):
    """decisions.js isPublished: the flag on newer blobs, action 'published' on blobs written before it."""
    return bool(d) and (d.get('published') is True or (d.get('published') is not False and d.get('action') == 'published'))


def merge(into, decisions):
    n = 0
    for d in (decisions or {}).values():
        d = clean(d)
        if d and (d['id'] not in into or d['at'] >= into[d['id']]['at']):
            into[d['id']] = d
            n += 1
    return n


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--day', type=date.fromisoformat, default=None, help='inbox day (default: newest inbox day)')
    ap.add_argument('--file', type=Path, action='append', default=[], help='exported decisions JSON (repeatable)')
    ap.add_argument('--no-api', action='store_true')
    ap.add_argument('--api', default=API)
    ap.add_argument('--store', type=Path, default=STORE)
    args = ap.parse_args()
    exports = [json.loads(f.read_text()) for f in args.file]
    day = args.day.isoformat() if args.day else next((e.get('day') for e in exports if e.get('day')), None)
    if not day:
        inbox = ROOT / 'live/store/compose_inbox'
        days = sorted(p.name for p in inbox.iterdir() if p.is_dir()) if inbox.is_dir() else []
        day = days[-1] if days else datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()   # inbox day = Beijing date
    path = args.store / f'{day}.json'
    try:
        decisions = json.loads(path.read_text()).get('decisions') or {}
    except (OSError, ValueError):
        decisions = {}
    before = dict(decisions)
    for e in exports:
        if e.get('day') and e['day'] != day:
            print(f"skip export for {e['day']} (day is {day})", file=sys.stderr)
            continue
        print(f'file: {merge(decisions, e.get("decisions"))} decision(s)')
    if not args.no_api:
        try:
            print(f'api: {merge(decisions, fetch_api(args.api, day))} decision(s)')
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f'api failed: {exc}', file=sys.stderr)
            if not exports:
                return 1
    if decisions != before or not path.exists():
        write_json(path, {'day': day, 'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                          'decisions': decisions})
    notes = {i: d['note'] for i, d in sorted(decisions.items()) if d['action'] == 'rewrite' and d['note']}
    notes_path = args.store / f'{day}.rewrite_notes.json'
    if notes:
        write_json(notes_path, notes)
    elif notes_path.exists():
        notes_path.unlink()
    count = {a: sum(d['action'] == a for d in decisions.values()) for a in sorted(ACTIONS)}
    print(f'{day}: {len(decisions)} decision(s) {count}, published flag {sum(is_published(d) for d in decisions.values())},'
          f' edited text {sum(bool(d["text"]) for d in decisions.values())} -> {path}')
    if notes:
        print(f'rewrite requests: {len(notes)} -> FD_DAILY_COMPOSE=1 python3 scripts/daily_compose.py --day {day} '
              f'--fill --rewrite-notes {notes_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
