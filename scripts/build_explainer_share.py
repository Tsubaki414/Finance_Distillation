"""Oct 12 (Fiona, explainer post type): per-account donor share of explainer / tutorial / checklist posts.

Writes live/personas/posting_habits/explainer_share.json: {account: {lang, donor_posts, explainer_posts, share}}.
live/explainer_mix.py lets en accounts post explainers only when their donors do (share >= EN_MIN_SHARE); zh accounts
get ~1 a day regardless (Fiona's rule). Deterministic regex classifier over the donor archive (live/donors/posts).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import explainer_mix, topic_div  # noqa: E402

import os
POSTS = Path(os.environ.get('FD_DONOR_POSTS') or ROOT / 'live' / 'donors' / 'posts')
OUT = ROOT / 'live' / 'personas' / 'posting_habits' / 'explainer_share.json'


def main():
    roster = json.loads((ROOT / 'live' / 'donors' / 'roster.json').read_text())
    out = {}
    for cid, cl in sorted((roster.get('persona_clusters') or {}).items()):
        if not cid.startswith('acct_'):
            continue
        acct, lang = cid[5:], (cl.get('lang') or 'en')[:2]
        n = e = 0
        for h in topic_div.donor_handles(acct, roster):
            p = POSTS / f'{h.lower()}.jsonl'
            if not p.exists():
                continue
            for line in p.read_text().splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get('rt') or r.get('reply') or not str(r.get('text') or '').strip():
                    continue
                n += 1
                e += explainer_mix.is_explainer_text(r['text'], lang)
        out[acct] = {'lang': lang, 'donor_posts': n, 'explainer_posts': e, 'share': round(e / n, 4) if n else 0.0}
    OUT.write_text(json.dumps({'version': 1, 'built_by': 'scripts/build_explainer_share.py', 'accounts': out},
                              ensure_ascii=False, indent=1) + '\n')
    for a, v in out.items():
        print(f"{a:32s} {v['lang']} {v['explainer_posts']:4d}/{v['donor_posts']:5d} {v['share']:.3f}")


if __name__ == '__main__':
    main()
