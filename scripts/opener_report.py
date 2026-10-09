#!/usr/bin/env python3
"""Measure weak-opener and cross-account opener-repeat in compose inbox drafts.

Usage (default: three Beijing day dirs):
  python scripts/opener_report.py [--days 2026-10-07,2026-10-08,2026-10-09] [--out /path/to/out.json]

Output:
  /workspace/x/cc_jobs/hook1009_measure.json  (default)
  Prints a summary table to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from live import hook_voice as hv, compose_inbox

INBOX_ROOT = compose_inbox.root()

# ------------ opener normalisation (same rule as batch_opener_findings) --

def _normalize_opener(first_line_text: str, lang: str) -> str:
    s = str(first_line_text or '').strip()
    if not s:
        return ''
    s = re.sub(r'^[\W@$#]+', '', s).strip()
    if lang == 'zh':
        cjk = re.sub(r'[^一-鿿㐀-䶿 0-⩭f]', '', s)
        return cjk[:6]
    else:
        words = re.findall(r'\w+', s)
        return ' '.join(words[:4]).lower()


def _first_line(body: str) -> str:
    return next((ln.strip() for ln in str(body or '').splitlines() if ln.strip()), '')


def _load_day(day: str) -> list[dict]:
    """Load all non-error inbox rows for one Beijing day."""
    d = INBOX_ROOT / day
    rows = []
    if not d.is_dir():
        return rows
    for f in sorted(d.iterdir()):
        if not f.suffix == '.json':
            continue
        try:
            row = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not row.get('body') and not row.get('text'):
            continue
        rows.append(row)
    return rows


def analyse_day(day: str) -> dict:
    rows = _load_day(day)
    weak_hits = []
    opener_clusters = []  # list of {opener, accounts, draft_ids}
    seen_openers: dict[str, dict] = {}  # key -> {accounts, draft_ids, first_line}
    phrase_counts: dict[str, list] = {}  # weak phrase -> [(draft_id, account_id)]

    for row in rows:
        body = str(row.get('body') or '')
        lang = str(row.get('lang') or 'zh')
        account_id = str(row.get('account_id') or '')
        draft_id = str(row.get('id') or '')
        fl = _first_line(body)

        # weak-opener detection
        findings = hv.hook_findings(body, lang)
        if findings:
            phrase = findings[0].get('detail', '')
            weak_hits.append({'draft_id': draft_id, 'account_id': account_id, 'lang': lang,
                               'first_line': fl[:120], 'finding': phrase})

        # track phrases for cluster rule
        explicit = hv._explicit_weak_opener(fl, lang)
        if explicit:
            phrase_counts.setdefault(explicit, []).append((draft_id, account_id))

        # opener-repeat tracking
        key = _normalize_opener(fl, lang)
        if key:
            if key not in seen_openers:
                seen_openers[key] = {'accounts': [account_id], 'draft_ids': [draft_id],
                                     'first_line': fl[:80]}
            else:
                seen_openers[key]['accounts'].append(account_id)
                seen_openers[key]['draft_ids'].append(draft_id)

    for key, info in seen_openers.items():
        if len(info['accounts']) >= 2:
            opener_clusters.append({'opener': key, 'first_line': info['first_line'],
                                    'accounts': info['accounts'], 'draft_ids': info['draft_ids']})

    # phrase-cluster findings (>= 3 accounts)
    phrase_clusters = []
    for phrase, hits in phrase_counts.items():
        if len(hits) >= 3:
            phrase_clusters.append({'phrase': phrase, 'accounts': [a for _, a in hits],
                                    'draft_ids': [d for d, _ in hits]})

    # top weak phrases
    phrase_freq: dict[str, int] = {}
    for h in weak_hits:
        phrase_freq[h['finding']] = phrase_freq.get(h['finding'], 0) + 1
    top_phrases = sorted(phrase_freq.items(), key=lambda x: -x[1])[:10]

    return {
        'day': day,
        'drafts_total': len(rows),
        'weak_opener_count': len(weak_hits),
        'weak_opener_hits': weak_hits,
        'top_phrases': [{'phrase': p, 'count': c} for p, c in top_phrases],
        'repeat_clusters': opener_clusters,
        'phrase_clusters': phrase_clusters,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', default='2026-10-07,2026-10-08,2026-10-09')
    ap.add_argument('--out', default='/workspace/x/cc_jobs/hook1009_measure.json')
    args = ap.parse_args()

    days = [d.strip() for d in args.days.split(',') if d.strip()]
    results = [analyse_day(d) for d in days]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({'days': results}, indent=2, ensure_ascii=False))
    print(f'Saved → {out_path}')

    # summary table
    print(f'\n{"Day":<14} {"Drafts":>6} {"Weak":>5} {"Top phrase":<60} {"RepeatClusters":>14}')
    print('-' * 100)
    for r in results:
        top = r['top_phrases'][0]['phrase'][:58] if r['top_phrases'] else '—'
        print(f"{r['day']:<14} {r['drafts_total']:>6} {r['weak_opener_count']:>5}  {top:<60} {len(r['repeat_clusters']):>14}")

    # repeat cluster examples (first line of each draft, not donor text)
    all_clusters = [(r['day'], c) for r in results for c in r['repeat_clusters']]
    if all_clusters:
        print('\nRepeat-opener clusters (first line of our drafts only):')
        for day, c in all_clusters[:6]:
            print(f"  [{day}] opener={c['opener']!r}  accounts={c['accounts']}  first_line={c['first_line']!r}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
