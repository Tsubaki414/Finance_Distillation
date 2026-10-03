"""Content Habit and Visual Profile for one donor, from their own timeline.

CLAUDE.md requires five axes per donor — Knowledge, Reasoning, Style, Content Habit, Visual —
each with 「样本量、计算方法、支持 post IDs、版本和可观察范围」. Style and Knowledge had artefacts.
These two did not, so two of the five axes were simply absent while the pipeline went on writing.

Everything here is counted, not inferred. Where the collection cannot support a claim the field
says `unknown` and why, because the acceptance contract is explicit about that: 「不完整时间序列下
不可观测项明确 unknown」.

What the collection genuinely cannot see, stated once rather than papered over per field:

  reaction latency   How long after an event the author posted needs event times. The collector
                     stores post times, not the events they respond to, so latency to a named
                     event is unknown here.
  deletions          A deleted post is invisible to polling. Silence and deletion look identical.
  edits              Only the text as first seen is stored, so revisions are not observable.
  true burst shape   Polling is periodic, so two posts an hour apart are visible but two posts a
                     minute apart may arrive in the same poll. Intervals below the poll period
                     are not resolvable.

Run: .venv/bin/python -B live/habit.py [--donor=qinbafrank]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime, statistics as st, collections

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
OUT = STORE / 'habit_profiles.json'
MIN_POSTS = 60

CHART_WORD = re.compile(r'chart|figure|table|graph|图|表|走势|曲线', re.I)


def _dt(stamp):
    try:
        d = datetime.datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except Exception:
        return None
    return d.astimezone(datetime.timezone.utc) if d.tzinfo else d.replace(
        tzinfo=datetime.timezone.utc)


def _load(handle=None):
    rows = collections.defaultdict(list)
    for line in (STORE / 'posts.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if handle and r.get('handle') != handle:
            continue
        d = _dt(r.get('created_at'))
        if d is None:
            continue
        r['_dt'] = d
        rows[r['handle']].append(r)
    for h in rows:
        rows[h].sort(key=lambda r: r['_dt'])
    return rows


def _pct(v, q):
    v = sorted(v)
    return round(v[max(0, min(len(v) - 1, int(q * len(v))))], 3) if v else None


def profile(handle, posts):
    """Habit and visual counts for one author. Every figure carries its own denominator."""
    if len(posts) < MIN_POSTS:
        return {'donor': handle, 'usable': False, 'n': len(posts),
                'why': f'{len(posts)} posts; {MIN_POSTS} needed'}

    own = [p for p in posts if not p.get('is_retweet')]
    gaps = [round((b['_dt'] - a['_dt']).total_seconds() / 3600, 2)
            for a, b in zip(posts, posts[1:])]
    hours = collections.Counter(p['_dt'].hour for p in posts)
    weekend = sum(1 for p in posts if p['_dt'].weekday() >= 5)
    days = collections.Counter(p['_dt'].date() for p in posts)
    span = (posts[-1]['_dt'].date() - posts[0]['_dt'].date()).days + 1
    silent = span - len(days)

    with_media = [p for p in own if p.get('media')]
    kinds = collections.Counter(m for p in own for m in (p.get('media') or []))
    with_link = [p for p in own if p.get('urls')]
    chart_words = [p for p in own if CHART_WORD.search(p.get('text') or '')]

    return {
        'donor': handle, 'usable': True, 'n': len(posts), 'own_posts': len(own),
        'observed_from': posts[0]['_dt'].date().isoformat(),
        'observed_to': posts[-1]['_dt'].date().isoformat(),
        'span_days': span,
        'method': ('counted from the collected timeline; every rate names its own denominator '
                   'and nothing is inferred from a post the collector did not see'),
        'habit': {
            'posts_per_active_day': round(len(posts) / max(len(days), 1), 2),
            'active_days': len(days), 'silent_days': silent,
            'silent_day_share': round(silent / max(span, 1), 3),
            'longest_silence_hours': max(gaps) if gaps else None,
            'gap_hours_p10': _pct(gaps, .10), 'gap_hours_p50': _pct(gaps, .50),
            'gap_hours_p90': _pct(gaps, .90),
            'burst_share_under_1h': (round(sum(1 for g in gaps if g < 1) / len(gaps), 3)
                                     if gaps else None),
            'weekend_share': round(weekend / len(posts), 3),
            'busiest_utc_hours': [h for h, _ in hours.most_common(3)],
            'retweet_share': round(1 - len(own) / len(posts), 3),
        },
        'visual': {
            'media_share_of_own_posts': round(len(with_media) / max(len(own), 1), 3),
            'media_kinds': dict(kinds),
            'link_share_of_own_posts': round(len(with_link) / max(len(own), 1), 3),
            'chart_word_share': round(len(chart_words) / max(len(own), 1), 3),
            'note': ('the collector records that media exists and its type, not what the image '
                     'contains. Whether a photo is a chart, a screenshot or a portrait is not '
                     'observable here, so chart_word_share counts the text saying so instead — '
                     'a proxy, and named as one'),
        },
        'unknown': {
            'reaction_latency': 'event times are not collected, so latency to an event is unknown',
            'deletions': 'a deleted post is invisible to polling; silence and deletion look alike',
            'edits': 'only the text as first seen is stored',
            'sub_poll_intervals': 'intervals shorter than the polling period are not resolvable',
            'reply_and_quote_relations': ('the live collector does not store reply/quote parents, '
                                          'so conversational habit is unknown for live rows'),
        },
        'supporting_post_ids': [p['post_id'] for p in posts[:40]],
        'version': 'habit-v1',
    }


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    rows = _load(args.get('donor') if isinstance(args.get('donor'), str) else None)
    out = {h: profile(h, ps) for h, ps in rows.items()}
    usable = {h: v for h, v in out.items() if v.get('usable')}
    prev = json.loads(OUT.read_text()) if OUT.is_file() else {}
    prev.update(out)
    OUT.write_text(json.dumps(prev, ensure_ascii=False, indent=2))
    print(f'{len(usable)} 位 donor 可建 Habit/Visual 画像，写入 {OUT}')
    for h, v in sorted(usable.items(), key=lambda x: -x[1]['n'])[:8]:
        hb, vs = v['habit'], v['visual']
        print(f"  {h:18} n={v['n']:<4} 活跃{hb['active_days']}天/沉默{hb['silent_days']}天  "
              f"周末{hb['weekend_share']}  中位间隔{hb['gap_hours_p50']}h  "
              f"配图率{vs['media_share_of_own_posts']}  带链接{vs['link_share_of_own_posts']}")


if __name__ == '__main__':
    main()
