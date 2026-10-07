"""Review feedback -> soft priors for the next day (Oct 8, Sirius borrow: hotspot item 5).

Input (local, no model calls): the /admin decisions pulled by scripts/apply_admin_decisions.py
(live/store/admin_decisions/<day>.json, one latest decision per draft: approve / published / hold / rewrite / edit)
joined with that day's inbox rows (live/store/compose_inbox/<day>/) for the account, angle and 母题 type.

Output (live/store/feedback/, gitignored):
- priors.json: per account, approve rate by angle id and by 母题 type (hotspot topic, or 'regular' for non-hotspot
  drafts), Beta(1, 1)-smoothed, with n. approve / published = approved; hold / rewrite = not approved; edit alone
  (text changed, no verdict) is not counted in the rate.
- style_examples/<account>.jsonl: one row per edited draft (before, after, unified diff), as a local style example.
  Never committed (live/store is gitignored); nothing here is sent anywhere.

Use next day: `angle_multiplier` / `motif_multiplier` give a soft multiplier in [1-MAX_SHIFT, 1+MAX_SHIFT] when an
(account, key) has at least MIN_N decided drafts; otherwise 1.0. A multiplier only reorders; it never adds a topic.
"""
from __future__ import annotations

import difflib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED = {'approve', 'published'}
REJECTED = {'hold', 'rewrite'}
MIN_N = 3
MAX_SHIFT = 0.15


def store_dir():
    return Path(os.environ.get('FD_FEEDBACK_STORE') or ROOT / 'live' / 'store' / 'feedback')


def decisions_dir():
    return Path(os.environ.get('FD_ADMIN_DECISIONS') or ROOT / 'live' / 'store' / 'admin_decisions')


def inbox_dir():
    return Path(os.environ.get('FD_COMPOSE_INBOX') or ROOT / 'live' / 'store' / 'compose_inbox')


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def motif_type(row):
    hot = row.get('hotspot') or {}
    return f"hot:{hot.get('type') or 'other'}" if hot else 'regular'


def angle_of(row):
    a = row.get('angle')
    return (a or {}).get('id') if isinstance(a, dict) else a


def collect(decisions_root=None, inbox_root=None):
    """[(day, row, decision)] for every decided draft found in both stores."""
    out = []
    root = Path(decisions_root or decisions_dir())
    for f in sorted(root.glob('????-??-??.json')):
        data = _read(f) or {}
        day = data.get('day') or f.stem
        rows = {}
        for p in sorted((Path(inbox_root or inbox_dir()) / day).glob('*.json')):
            r = _read(p)
            if isinstance(r, dict) and r.get('id'):
                rows[r['id']] = r
        for did, d in (data.get('decisions') or {}).items():
            if did in rows and isinstance(d, dict):
                out.append((day, rows[did], d))
    return out


def _rate(a, n):
    return round((a + 1) / (n + 2), 4)


def build(decided):
    """{'accounts': {acct: {'overall', 'angle': {id: {...}}, 'motif': {type: {...}}}}, 'edits': [...]}"""
    acc, edits = {}, []
    for day, row, d in decided:
        action = d.get('action')
        a = row.get('account_id')
        if not a:
            continue
        body = (row.get('body') or row.get('text') or '').strip()
        text = (d.get('text') or '').strip()
        if text and text != body:
            edits.append({'day': day, 'account_id': a, 'draft_id': row.get('id'), 'action': action,
                          'angle': angle_of(row), 'motif_type': motif_type(row), 'before': body, 'after': text,
                          'diff': '\n'.join(difflib.unified_diff(body.splitlines(), text.splitlines(), 'draft', 'edited',
                                                                 lineterm='')),
                          'note': d.get('note') or '', 'at': d.get('at') or ''})
        if action not in APPROVED | REJECTED:
            continue
        ok = action in APPROVED
        e = acc.setdefault(a, {'overall': [0, 0], 'angle': {}, 'motif': {}})
        e['overall'][0] += ok
        e['overall'][1] += 1
        for kind, key in (('angle', angle_of(row) or 'none'), ('motif', motif_type(row))):
            c = e[kind].setdefault(key, [0, 0])
            c[0] += ok
            c[1] += 1
    out = {}
    for a, e in acc.items():
        out[a] = {'overall': {'approve_rate': _rate(*e['overall']), 'n': e['overall'][1]},
                  **{kind: {k: {'approve_rate': _rate(*v), 'n': v[1]} for k, v in sorted(e[kind].items())}
                     for kind in ('angle', 'motif')}}
    return {'accounts': out, 'edits': edits}


def write(result, store=None):
    store = Path(store or store_dir())
    store.mkdir(parents=True, exist_ok=True)
    priors = {'version': 'feedback-v1', 'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'rule': 'approve|published = approved; hold|rewrite = not; Beta(1,1) smoothing; soft prior only',
              'accounts': result['accounts']}
    (store / 'priors.json').write_text(json.dumps(priors, ensure_ascii=False, indent=2) + '\n')
    ex = store / 'style_examples'
    ex.mkdir(exist_ok=True)
    by_acct = {}
    for e in result['edits']:
        by_acct.setdefault(e['account_id'], []).append(e)
    for a, rows in by_acct.items():   # rewritten whole each night: the newest decision per draft wins
        (ex / f'{a}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    return priors


def load(store=None):
    return (_read(Path(store or store_dir()) / 'priors.json') or {}).get('accounts') or {}


def _mult(entry, overall):
    if not entry or entry.get('n', 0) < MIN_N or not overall:
        return 1.0
    shift = entry['approve_rate'] - overall['approve_rate']
    return round(1 + max(-MAX_SHIFT, min(MAX_SHIFT, shift)), 4)


def angle_multiplier(priors, account, angle):
    p = (priors or {}).get(account) or {}
    return _mult((p.get('angle') or {}).get(angle), p.get('overall'))


def motif_multiplier(priors, account, mtype):
    p = (priors or {}).get(account) or {}
    return _mult((p.get('motif') or {}).get(f'hot:{mtype}'), p.get('overall'))
