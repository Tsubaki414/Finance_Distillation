"""Data-derived donor style stats: per-donor aggregates of post tags
(live/jev_front.tag_posts: Jev post_type / hook + deterministic structure and
number counts) and weight-averaged per-persona-cluster stats. Voice only:
these numbers describe how donors write, never what they claim."""
from __future__ import annotations

import collections
import statistics


def originals(posts):
    return [p for p in posts if not p.get('rt') and not p.get('reply') and not p.get('pinned')]


def _mix(values):
    c = collections.Counter(v for v in values if v)
    n = sum(c.values())
    return {k: round(v / n, 3) for k, v in c.most_common()} if n else {}


def aggregate(tags):
    tags = list(tags)
    if not tags:
        return {'posts': 0}
    chars = sorted(t['structure'].get('chars', 0) for t in tags)
    nums = [t.get('numbers', 0) for t in tags]
    share = lambda key: round(sum(1 for t in tags if t['structure'].get(key)) / len(tags), 3)
    return {'posts': len(tags), 'post_type_mix': _mix(t.get('post_type') for t in tags),
            'hook_mix': _mix(t.get('hook') for t in tags),
            'median_chars': int(statistics.median(chars)), 'p25_chars': chars[len(chars) // 4],
            'p75_chars': chars[(3 * len(chars)) // 4 if len(chars) > 1 else 0],
            'numbers_per_post': round(statistics.mean(nums), 2),
            'share_3plus_numbers': round(sum(1 for n in nums if n >= 3) / len(nums), 3),
            'list_share': share('list'), 'thread_marker_share': share('thread_marker'),
            'question_open_share': share('question_open'), 'link_share': share('has_link'),
            'jev_tagged_share': round(sum(1 for t in tags if not t.get('jev_fallback')) / len(tags), 3)}


def cluster(per_donor, weights):
    total = sum(weights.get(h, 0) for h in per_donor if per_donor[h].get('posts'))
    out = {'donors': len(per_donor), 'posts': sum(s.get('posts', 0) for s in per_donor.values())}
    if not total:
        return out
    def wmix(key):
        acc = collections.defaultdict(float)
        for h, s in per_donor.items():
            for k, v in (s.get(key) or {}).items():
                acc[k] += weights.get(h, 0) / total * v
        return {k: round(v, 3) for k, v in sorted(acc.items(), key=lambda kv: -kv[1])}
    def wmean(key):
        return round(sum(weights.get(h, 0) / total * s[key] for h, s in per_donor.items() if s.get('posts')), 3)
    out.update(post_type_mix=wmix('post_type_mix'), hook_mix=wmix('hook_mix'),
               **{k: wmean(k) for k in ('median_chars', 'numbers_per_post', 'share_3plus_numbers', 'list_share',
                                        'thread_marker_share', 'question_open_share', 'link_share', 'jev_tagged_share')})
    return out
