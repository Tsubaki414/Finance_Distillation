"""Tag deep-scraped donor posts (Jev post_type + hook; deterministic structure /
numbers) and build per-persona style stats -> live/donors/style_stats.json.

  python scripts/donor_style_stats.py --jev --run /workspace/x/donor_tags
Tags are cached per donor in live/donors/tags/<handle>.json (untracked).
Use --only-fallback live/donors/tags to retry only previously failed posts.
Use --questions-per-call 8 to ask post_type and hook separately.
Use --flash to answer with the extract_flash Gemini stage (subrouter) instead of TypeSafe Jev.
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
    return [json.loads(l) for l in path.read_text(encoding='utf-8').split('\n') if l.strip()]


def tag_donor(handle, jev, cap, *, only_fallback=None, stats=None, questions_per_call=16):
    out = TAGS / f'{handle.lower()}.json'
    previous_path = None
    if only_fallback is not None:
        previous_path = Path(only_fallback)
        if previous_path.is_dir():
            previous_path = previous_path / out.name
        elif previous_path.stem.lower() != handle.lower():
            # A single per-donor JSON only selects that donor.
            return handle, json.loads(out.read_text()) if out.exists() else {}
    if previous_path is not None:
        if not previous_path.exists():
            return handle, json.loads(out.read_text()) if out.exists() else {}
        previous = json.loads(previous_path.read_text())
        # Preserve successful cached tags if using an older selection snapshot.
        merged = dict(previous)
        if out.exists():
            merged.update(json.loads(out.read_text()))
        selected = {key for key, tag in previous.items() if tag.get('jev_fallback') is True}
        # Retag all selected IDs, regardless of the original cap/dedup policy.
        posts = [p for p in load_posts(handle) if str(p['id']) in selected]
    else:
        if out.exists():
            return handle, json.loads(out.read_text())
        merged = {}
        seen, posts = set(), []
        for p in donor_style.originals(load_posts(handle)):
            key = ' '.join((p.get('text') or '').split())[:200]
            if key and key not in seen:
                seen.add(key)
                posts.append(p)
        posts = posts[:cap]
    if not posts:
        return handle, merged
    if stats is not None:
        stats['posts'] = stats.get('posts', 0) + len(posts)
    tags = jev_front.tag_posts(posts, jev=jev, stats=stats, questions_per_call=questions_per_call)
    merged.update(tags)
    TAGS.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False))
    return handle, merged


def main():
    global POSTS, TAGS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--jev', action='store_true')
    ap.add_argument('--flash', action='store_true',
                    help='answer the Jev choice questions with the extract_flash Gemini stage (subrouter first, '
                         'live/jev_flash.py) instead of TypeSafe Jev; implies --jev')
    ap.add_argument('--cap-usd', type=float, default=None,
                    help='spend cap of this run ledger (paid relay fallback only; subrouter calls are flat-rate)')
    ap.add_argument('--cap', type=int, default=250, help='max original posts tagged per donor')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--only-fallback', type=Path, metavar='PREV_TAGS',
                    help='retag only fallback IDs from a per-donor JSON or directory of tag JSONs; merge into cache')
    ap.add_argument('--questions-per-call', type=int, choices=range(1, 17), default=16,
                    help='default 16; use 8 to ask post_type and hook separately')
    ap.add_argument('--posts-dir', type=Path, default=POSTS)
    ap.add_argument('--tags-dir', type=Path, default=TAGS)
    args = ap.parse_args()
    if args.flash:
        args.jev = True
    if args.only_fallback is not None and not args.only_fallback.exists():
        ap.error('--only-fallback must name an existing tag JSON or directory')
    if args.only_fallback is not None and not args.jev:
        ap.error('--only-fallback requires --jev')
    POSTS, TAGS = args.posts_dir, args.tags_dir
    roster = json.loads((ROOT / 'live/donors/roster.json').read_text())
    from ml import budget as spend
    spend.STORE = args.run / 'ledger'
    spend.LEDGER = spend.STORE / 'spend.json'
    spend.DISTILLATION_RUNS = spend.STORE / 'distillation_spend.jsonl'
    if args.cap_usd is not None:
        spend.set_cap(args.cap_usd)
    jev = None
    if args.flash:
        from live.jev_flash import FlashJev
        jev = FlashJev(args.run / 'flash_calls')
    elif args.jev:
        from live.jev_review_client import JevReviewClient
        jev = JevReviewClient(args.run / 'jev_calls')
    handles = sorted({d['handle'] for c in roster['persona_clusters'].values() for d in c['donors']} |
                     {h for c in roster['persona_clusters'].values() for h in c.get('bench', [])})
    handles = [h for h in handles if (POSTS / f'{h.lower()}.jsonl').exists()]
    def tag_handle(handle):
        stats = {}
        result = tag_donor(handle, jev, args.cap, only_fallback=args.only_fallback,
                           stats=stats, questions_per_call=args.questions_per_call)
        return result, stats

    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(tag_handle, handles))
    tagged = dict(result for result, stats in results)
    totals = {key: sum(stats.get(key, 0) for result, stats in results)
              for key in ('calls', 'failed_calls', 'retried', 'split', 'fallback_posts', 'posts')}
    per_donor = {h: donor_style.aggregate(t.values()) for h, t in tagged.items() if t}
    clusters = {}
    for name, c in roster['persona_clusters'].items():
        weights = {d['handle']: d['weight'] for d in c['donors']}
        core = {h: per_donor[h] for h in weights if h in per_donor}
        clusters[name] = {'lang': c['lang'], 'core_with_posts': len(core), 'core': len(weights),
                          'core_stats': donor_style.cluster(core, weights),
                          'all_stats': donor_style.cluster({h: per_donor[h] for h in list(weights) + c.get('bench', []) if h in per_donor},
                                                           {h: weights.get(h, min(weights.values()) / 2) for h in list(weights) + c.get('bench', [])})}
    out = {'version': '1', 'method': 'originals (no RT / replies to others / pinned) from live/donors/posts; post_type + hook by '
                                      'TypeSafe Jev choice questions (rule fallback flagged); structure + numbers deterministic',
           'use': 'voice and structure only; never facts or numbers', 'donors_tagged': len(per_donor),
           'posts_tagged': sum(s['posts'] for s in per_donor.values()), 'clusters': clusters, 'donors': per_donor}
    (ROOT / 'live/donors/style_stats.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'donors_tagged': out['donors_tagged'], 'posts_tagged': out['posts_tagged'],
                      'posts_retagged' if args.only_fallback else 'new_posts_tagged': totals['posts'],
                      'jev_calls': totals['calls'], 'jev_failed': totals['failed_calls'],
                      'retried': totals['retried'], 'split': totals['split'],
                      'fallback_posts': totals['fallback_posts'],
                      'failed_calls_rate': totals['failed_calls'] / totals['calls'] if totals['calls'] else 0,
                      'fallback_posts_rate': totals['fallback_posts'] / totals['posts'] if totals['posts'] else 0}, indent=1))


if __name__ == '__main__':
    main()
