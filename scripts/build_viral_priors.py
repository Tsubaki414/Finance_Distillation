#!/usr/bin/env python3
"""Build live/viral_priors.json from our own donor corpus (live/donors/posts, local; no model calls).

Writes aggregates only: per language and structure, the median within-donor engagement lift, n_donors and the number
of posts that have the structure. No post text, handle or id is written. See live/viral_priors.py for the method.

  python3 scripts/build_viral_priors.py [--posts live/donors/posts] [--out live/viral_priors.json]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import viral_priors as vp  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--posts', type=Path, default=ROOT / 'live/donors/posts')
    ap.add_argument('--out', type=Path, default=vp.PATH)
    args = ap.parse_args()
    donors = {}
    for p in sorted(args.posts.glob('*.jsonl')):
        rows = []
        for line in p.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        donors[p.stem] = rows
    priors = vp.compute(donors)
    out = {'version': 'viral-priors-v1', 'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'method': ('engagement = views (likes if no views) / the donor\'s own median; lift = median over donors of '
                      'median(engagement | structure) / median(engagement | not structure); originals only; donors with '
                      f'>= {vp.MIN_POSTS} posts in the language and >= {vp.MIN_SIDE} posts on each side. Association in '
                      'donor data, not a causal effect. Used only as a soft angle-ranking signal (+-15% max).'),
           'donors_read': len(donors), 'priors': priors}
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    for lang, feats in priors.items():
        print(lang, {f: (v['lift'], v['n_donors']) for f, v in feats.items()})
    print('->', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
