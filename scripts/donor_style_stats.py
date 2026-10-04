"""Tag deep-scraped donor posts (Jev post_type + hook; deterministic structure /
numbers) and build per-persona style stats -> live/donors/style_stats.json.

  python scripts/donor_style_stats.py --jev --run /workspace/x/donor_tags
Tags are cached per donor in live/donors/tags/<handle>.json (untracked).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import donor_style, jev_front  # noqa: E402

POSTS = ROOT / 'live/donors/posts'
TAGS = ROOT / 'live/donors/tags'


def load_posts(handle):
    path = POSTS / f'{handle.lower()}.jsonl'
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def tag_donor(handle, jev, cap):
    out = TAGS / f'{handle.lower()}.json'
    if out.exists():
        return handle, json.loads(out.read_text())
    seen, posts = set(), []
    for p in donor_style.originals(load_posts(handle)):
        key = ' '.join((p.get('text') or '').split())[:200]
        if key and key not in seen:  # repeated promo / boilerplate posts would skew the mix
            seen.add(key)
            posts.append(p)
    posts = posts[:cap]
    if not posts:
        return handle, {}
    tags = jev_front.tag_posts(posts, jev=jev)
    TAGS.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tags, ensure_ascii=False))
    return handle, tags


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--jev', action='store_true')
    ap.add_argument('--cap', type=int, default=250, help='max original posts tagged per donor')
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()
    roster = json.loads((ROOT / 'live/donors/roster.json').read_text())
    from ml import budget as spend
    spend.STORE = args.run / 'ledger'
    spend.LEDGER = spend.STORE / 'spend.json'
    jev = None
    if args.jev:
        from live.jev_review_client import JevReviewClient
        jev = JevReviewClient(args.run / 'jev_calls')
    handles = sorted({d['handle'] for c in roster['persona_clusters'].values() for d in c['donors']} |
                     {h for c in roster['persona_clusters'].values() for h in c['bench']})
    handles = [h for h in handles if (POSTS / f'{h.lower()}.jsonl').exists()]
    with ThreadPoolExecutor(args.workers) as ex:
        tagged = dict(ex.map(lambda h: tag_donor(h, jev, args.cap), handles))
    per_donor = {h: donor_style.aggregate(t.values()) for h, t in tagged.items() if t}
    clusters = {}
    for name, c in roster['persona_clusters'].items():
        weights = {d['handle']: d['weight'] for d in c['donors']}
        core = {h: per_donor[h] for h in weights if h in per_donor}
        clusters[name] = {'lang': c['lang'], 'core_with_posts': len(core), 'core': len(weights),
                          'core_stats': donor_style.cluster(core, weights),
                          'all_stats': donor_style.cluster({h: per_donor[h] for h in list(weights) + c['bench'] if h in per_donor},
                                                           {h: weights.get(h, min(weights.values()) / 2) for h in list(weights) + c['bench']})}
    out = {'version': '1', 'method': 'originals (no RT / replies to others / pinned) from live/donors/posts; post_type + hook by '
                                      'TypeSafe Jev choice questions (rule fallback flagged); structure + numbers deterministic',
           'use': 'voice and structure only; never facts or numbers', 'donors_tagged': len(per_donor),
           'posts_tagged': sum(s['posts'] for s in per_donor.values()), 'clusters': clusters, 'donors': per_donor}
    (ROOT / 'live/donors/style_stats.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'donors_tagged': out['donors_tagged'], 'posts_tagged': out['posts_tagged'],
                      'jev_calls': len(jev.calls) if jev else 0,
                      'jev_failed': sum(1 for c in (jev.calls if jev else []) if c['status'] != 'completed')}, indent=1))


if __name__ == '__main__':
    main()
