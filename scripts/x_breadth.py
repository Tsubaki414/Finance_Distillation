#!/usr/bin/env python3
"""Curate tier-B X sources from the Sirius source list and map them to the fd20 accounts (live/x_breadth.py).

  python scripts/x_breadth.py candidates [--sirius PATH]            # 0 calls: ranked by our donors' @-mentions
  python scripts/x_breadth.py evaluate --max-calls 250              # twitter241 /user-tweets, aggregates only
  python scripts/x_breadth.py assign [--per-account 8] [--daily-call-cap 30]   # writes live/x_breadth.json
  python scripts/x_breadth.py recheck --max-calls 90                # /user org check of the mapped handles

Local files (gitignored, no tweet text): live/store/x_breadth/{candidates,eval}.json, evaluate_calls.jsonl.
live/x_breadth.json (git) holds handles, mapped accounts, scores and the intake caps only.
The RAPID_X_API_KEY value is read from the environment and never printed or logged.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

from live import topic_div, x_breadth  # noqa: E402

SIRIUS = Path('/workspace/x/sirius_repo/configs/content_source_accounts.json')
ACCOUNTS = ROOT / 'live' / 'fd20_accounts.json'
UNIVERSES = ROOT / 'live' / 'store' / 'fd20' / 'universes.json'


def _accounts():
    return json.loads(ACCOUNTS.read_text())['accounts']


def mentions(accounts):
    """{handle_lower: {account: n}}: @-mentions in each account's donor posts (all history; counts only)."""
    out = defaultdict(Counter)
    for a in accounts:
        for h in topic_div.donor_handles(a['id']):
            path = topic_div.POSTS / f'{h.lower()}.jsonl'
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                try:
                    text = json.loads(line).get('text') or ''
                except ValueError:
                    continue
                for m in {x.lower() for x in re.findall(r'@(\w{2,15})', text)}:
                    out[m][a['id']] += 1
    return out


def existing_handles():
    uni = json.loads(UNIVERSES.read_text())
    ours = {x['handle'].lower() for u in uni.values() for x in u.get('x_sources') or []}
    roster = json.loads(topic_div.ROSTER.read_text())
    donors = {d['handle'].lower() for c in roster['persona_clusters'].values() for d in c.get('donors') or []}
    return ours, donors, {a: [x['handle'] for x in u.get('x_sources') or [] if x.get('enabled', True)] for a, u in uni.items()}


def cmd_candidates(args):
    accounts = _accounts()
    sirius = json.loads(Path(args.sirius).read_text())
    ours, donors, _ = existing_handles()
    men = mentions(accounts)
    cands = x_breadth.candidates(sirius, ours | donors, men)
    out = x_breadth.store_dir() / 'candidates.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'sirius_total': len(sirius),
                               'excluded_existing': len({r['handle'].lower() for r in sirius} & (ours | donors)),
                               'candidates': [{'handle': h, 'user_id': u, 'mentions': n, 'by_account': m}
                                              for h, u, n, m in cands]}, ensure_ascii=False, indent=1) + '\n')
    print(f'sirius {len(sirius)}; already ours/donors {len({r["handle"].lower() for r in sirius} & (ours | donors))}; '
          f'candidates {len(cands)} (mentioned by our donors: {sum(1 for c in cands if c[2])}) -> {out}')
    return 0


def cmd_evaluate(args):
    key = os.environ.get('RAPID_X_API_KEY')
    if not key:
        raise SystemExit('RAPID_X_API_KEY missing')
    cands = json.loads((x_breadth.store_dir() / 'candidates.json').read_text())['candidates']
    path = x_breadth.store_dir() / 'eval.json'
    evals = json.loads(path.read_text()) if path.exists() else {}
    log = x_breadth.store_dir() / 'evaluate_calls.jsonl'
    client = x_breadth.Client(key, args.max_calls, log)
    from scrape_donor_posts import timeline_posts
    now = datetime.now(timezone.utc)
    todo = [c for c in cands if c['handle'].lower() not in evals and c['user_id'] and c['mentions'] >= args.min_mentions]
    for c in todo[:args.max_calls]:
        try:
            page = client.get('/user-tweets', user=c['user_id'], count=20)
        except Exception as exc:   # noqa: BLE001
            evals[c['handle'].lower()] = {'handle': c['handle'], 'user_id': c['user_id'], 'error': str(exc)[:120]}
            if 'call cap' in str(exc):
                break
            continue
        ev = x_breadth.evaluate_page(c['handle'], c['user_id'], page, now, posts=timeline_posts(page))
        ev['evaluated_at'] = now.isoformat(timespec='seconds')
        evals[c['handle'].lower()] = ev
    path.write_text(json.dumps(evals, ensure_ascii=False, indent=1) + '\n')
    why = Counter((x_breadth.usable(e, now)[1] or 'usable') if 'error' not in e else 'error' for e in evals.values())
    print(f'evaluated {len(evals)} (calls this run {client.made}); {dict(why)} -> {path}')
    return 0


def cmd_recheck(args):
    """Profile re-check (/user, 1 call per handle) of the handles in live/x_breadth.json: org flag from the avatar
    shape / verified type (an evaluation before Oct 8 18:00 did not read them). Updates eval.json; run assign after."""
    key = os.environ.get('RAPID_X_API_KEY')
    if not key:
        raise SystemExit('RAPID_X_API_KEY missing')
    path = x_breadth.store_dir() / 'eval.json'
    evals = json.loads(path.read_text())
    cfg = x_breadth.load_config()
    client = x_breadth.Client(key, args.max_calls, x_breadth.store_dir() / 'evaluate_calls.jsonl')
    todo = [h for h in cfg.get('handles') or {} if 'avatar_shape' not in evals.get(h.lower(), {})]
    for h in todo[:args.max_calls]:
        ev = evals[h.lower()]
        try:
            page = client.get('/user', username=h)
        except Exception as exc:   # noqa: BLE001
            print(f'{h}: {str(exc)[:80]}')
            continue
        prof = x_breadth.user_of(page, ev['user_id'])
        ev.update(avatar_shape=prof.get('shape'), verified_type=prof.get('verified_type'),
                  org=bool(ev.get('org')) or x_breadth.is_org(prof))
    path.write_text(json.dumps(evals, ensure_ascii=False, indent=1) + '\n')
    print(f'rechecked {client.made}; orgs now {sum(1 for h in cfg.get("handles") or {} if evals[h.lower()].get("org"))}'
          f' of {len(cfg.get("handles") or {})}')
    return 0


def cmd_assign(args):
    accounts = _accounts()
    evals = json.loads((x_breadth.store_dir() / 'eval.json').read_text())
    _, _, existing = existing_handles()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    ref = max((datetime.fromisoformat(e['evaluated_at']) for e in evals.values() if e.get('evaluated_at')), default=now)
    roster = json.loads(topic_div.ROSTER.read_text())
    mix = {a['id']: topic_div.donor_profile(a['id'], ref, roster, days=30)['mix'] for a in accounts}
    men = mentions(accounts)
    cfg = x_breadth.load_config()
    exclude = {h.lower() for h in cfg.get('exclude') or {}}
    # only handles whose profile was re-checked for the org avatar / verified type (recheck) are mapped
    picked = x_breadth.assign([e for e in evals.values() if 'error' not in e and e['handle'].lower() not in exclude
                               and 'avatar_shape' in e], mix, {a['id']: a['lang'] for a in accounts},
                              men, ref, per_account=args.per_account, existing=existing)
    handles = {}
    for aid, rows in picked.items():
        for h, score, why in rows:
            e = evals[h.lower()]
            row = handles.setdefault(h, {'lang': e['lang'], 'accounts': [], 'scores': {},
                                         'originals_per_day': e['originals_per_day']})
            row['accounts'].append(aid)
            row['scores'][aid] = score
    out = {'version': 'x-breadth-v1',
           'note': 'Tier-B X sources curated from the Sirius X source list (handles only) and mapped to fd20 '
                   'accounts by donor theme mix + donor @-mentions (scripts/x_breadth.py). No tweet text here.',
           'daily_call_cap': args.daily_call_cap or cfg.get('daily_call_cap', x_breadth.DAILY_CALL_CAP),
           'batch_size': cfg.get('batch_size', x_breadth.BATCH), 'pages_per_batch': cfg.get('pages_per_batch', x_breadth.PAGES),
           'per_account': args.per_account, 'built_at': ref.isoformat(timespec='seconds'),
           'exclude': cfg.get('exclude') or {},
           'handles': dict(sorted(handles.items(), key=lambda kv: kv[0].lower()))}
    x_breadth.CONFIG.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    per = Counter(a for h in handles.values() for a in h['accounts'])
    print(f'{len(handles)} handles -> {x_breadth.CONFIG}; per account {dict(sorted(per.items()))}; '
          f'expected originals/day {sum(h["originals_per_day"] for h in handles.values()):.0f}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('candidates')
    c.add_argument('--sirius', default=str(SIRIUS))
    e = sub.add_parser('evaluate')
    e.add_argument('--max-calls', type=int, required=True)
    e.add_argument('--min-mentions', type=int, default=1)
    r = sub.add_parser('recheck')
    r.add_argument('--max-calls', type=int, required=True)
    a = sub.add_parser('assign')
    a.add_argument('--per-account', type=int, default=x_breadth.PER_ACCOUNT)
    a.add_argument('--daily-call-cap', type=int)
    a.add_argument('--now')
    args = ap.parse_args()
    return {'candidates': cmd_candidates, 'evaluate': cmd_evaluate, 'recheck': cmd_recheck,
            'assign': cmd_assign}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
