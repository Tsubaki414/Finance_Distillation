"""Hotspot detection over the live store.

What counts as hot is not "a lot of people posted". Every signal here is computed against a
baseline drawn from the same data, so a busy account does not look like a breaking story:

  velocity        views per hour since posting, divided by that author's own median. An account
                  with 200k median views does not out-rank one with 5k just for being big.
  spread          how many distinct authors touched the entity inside the window
  novelty         whether the entity appears in the trailing baseline window at all
  cross_language  discussed in one language and not the other. This is a content lane, and it is
                  the one signal that is worthless without a bilingual watchlist.
  first_mention   earliest post naming the entity, so "who said it first" is ordering, not opinion

Acceleration deliberately reports as unavailable until a post has been observed twice. One poll
cannot measure a rate of change, and guessing one from a single snapshot would be inventing the
main thing the system claims to do.

Run: .venv/bin/python -B live/hotspots.py [--window=48] [--baseline=336]
"""
from pathlib import Path
import sys, json, re, statistics, datetime, collections

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'

CASHTAG = re.compile(r'\$([A-Za-z]{1,6})(?![A-Za-z0-9])')

# Macro topics do not carry a ticker, so they are matched by name in both languages and folded
# to one entity. Without this, a Fed story in Chinese and the same story in English never meet
# and the cross-language gap can never be detected.
TOPICS = {
    'fed_policy':   ['美联储', '联储', '降息', '加息', '议息', 'FOMC', 'Fed ', 'rate cut', 'rate hike',
                     'Powell', '鲍威尔'],
    'inflation':    ['通胀', 'CPI', 'PCE', 'PPI', 'inflation', '物价'],
    'jobs':         ['非农', '就业', '失业率', 'payroll', 'nonfarm', 'jobless', 'unemployment'],
    'tariffs':      ['关税', 'tariff', '贸易战', 'trade war'],
    'yen_fx':       ['日元', '日圆', '汇率', 'yen', 'JPY', '干预', 'intervention', '美元指数', 'DXY'],
    'ai_capex':     ['算力', 'AI 资本开支', 'capex', 'datacenter', '数据中心', 'GPU', 'HBM', '存储',
                     'memory'],
    'oil':          ['油价', '原油', 'WTI', 'Brent', 'OPEC', '石油'],
    'crypto':       ['比特币', 'Bitcoin', 'BTC', 'ETH', '以太', '加密'],
    'china_policy': ['政策', '刺激', '降准', 'PBOC', '央行', '国常会'],
    'earnings':     ['财报', '业绩', 'earnings', 'guidance', '指引'],
}

STOP_TICKERS = {'A', 'I', 'IT', 'ON', 'BE', 'SO', 'AT', 'GO', 'ALL', 'ANY', 'FOR', 'NOW', 'ONE',
                'OUT', 'BIG', 'CEO', 'USD', 'EPS', 'ATH'}


def load(name):
    p = STORE / name
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().split('\n') if l.strip()]


def parse(ts):
    try:
        return datetime.datetime.fromisoformat(ts)
    except Exception:
        return None


def entities(text):
    """Tickers and macro topics. Both are folded into one namespace so they rank together."""
    out = set()
    for m in CASHTAG.finditer(text or ''):
        t = m.group(1).upper()
        if t not in STOP_TICKERS:
            out.add('$' + t)
    low = (text or '').lower()
    for topic, words in TOPICS.items():
        if any((w.lower() in low) if w.isascii() else (w in (text or '')) for w in words):
            out.add('#' + topic)
    return out


def author_baseline(posts):
    """Median views per hour for each author, from their own recent posts."""
    per = collections.defaultdict(list)
    now = datetime.datetime.now(datetime.timezone.utc)
    for p in posts:
        t = parse(p.get('created_at'))
        v = (p.get('metrics_at_first_sight') or {}).get('views')
        if not t or not v:
            continue
        hrs = max((now - t).total_seconds() / 3600, 1.0)
        per[p['handle']].append(v / hrs)
    return {h: statistics.median(v) for h, v in per.items() if v}


def acceleration(snaps):
    """Views gained per hour between the first and last observation of a post.

    Reports nothing for a post seen once. A rate of change needs two points, and a system whose
    whole claim is "it notices things moving" must not fake that from a single reading.
    """
    by = collections.defaultdict(list)
    for s in snaps:
        if s.get('views') is not None and s.get('observed_at'):
            by[s['post_id']].append(s)
    out = {}
    for pid, rows in by.items():
        rows.sort(key=lambda r: r['observed_at'])
        if len(rows) < 2:
            continue
        a, b = rows[0], rows[-1]
        ta, tb = parse(a['observed_at']), parse(b['observed_at'])
        if not ta or not tb:
            continue
        dt = (tb - ta).total_seconds() / 3600
        if dt <= 0:
            continue
        out[pid] = {'views_per_hour': round((b['views'] - a['views']) / dt, 1),
                    'observations': len(rows), 'span_hours': round(dt, 2)}
    return out


def build(window_hours=48, baseline_hours=336):
    posts = load('posts.jsonl')
    snaps = load('engagement.jsonl')
    now = datetime.datetime.now(datetime.timezone.utc)
    base_med = author_baseline(posts)
    accel = acceleration(snaps)

    recent, older = [], []
    for p in posts:
        t = parse(p.get('created_at'))
        if not t:
            continue
        age = (now - t).total_seconds() / 3600
        p['_age_h'] = age
        (recent if age <= window_hours else older).append(p)

    baseline_entities = collections.Counter()
    for p in older:
        if p['_age_h'] <= baseline_hours:
            for e in entities(p['text']):
                baseline_entities[e] += 1

    hits = collections.defaultdict(list)
    for p in recent:
        for e in entities(p['text']):
            hits[e].append(p)

    rows = []
    for ent, ps in hits.items():
        authors = {p['handle'] for p in ps}
        langs = collections.Counter(p['lang_reported'] for p in ps)
        vel = []
        for p in ps:
            v = (p.get('metrics_at_first_sight') or {}).get('views')
            if not v:
                continue
            hrs = max(p['_age_h'], 1.0)
            med = base_med.get(p['handle']) or 1
            vel.append((v / hrs) / med)
        earliest = min(ps, key=lambda p: p['created_at'])
        accels = [accel[p['post_id']]['views_per_hour'] for p in ps if p['post_id'] in accel]
        zh, en = langs.get('zh', 0), langs.get('en', 0)
        rows.append({
            'entity': ent,
            'kind': 'ticker' if ent.startswith('$') else 'topic',
            'mentions': len(ps),
            'distinct_authors': len(authors),
            'authors': sorted(authors),
            'velocity_vs_author_median': round(statistics.median(vel), 2) if vel else None,
            'new_this_window': baseline_entities.get(ent, 0) == 0,
            'baseline_mentions': baseline_entities.get(ent, 0),
            'languages': dict(langs),
            'cross_language_gap': ('zh_only' if zh and not en else
                                   'en_only' if en and not zh else
                                   'both' if zh and en else 'unclear'),
            'first_mention': {'handle': earliest['handle'], 'at': earliest['created_at'],
                              'post_id': earliest['post_id'],
                              'text': earliest['text'][:160]},
            'acceleration_views_per_hour': (round(statistics.median(accels), 1)
                                            if accels else None),
            'acceleration_available': bool(accels),
            'post_ids': [p['post_id'] for p in ps],
        })

    for r in rows:
        # Spread across authors is the strongest signal that something is a story rather than one
        # person's hobby horse, so it is weighted hardest.
        r['score'] = round(
            2.2 * (r['distinct_authors'] - 1)
            + 1.0 * min(r['mentions'], 6) / 2
            + 1.4 * min(r['velocity_vs_author_median'] or 0, 4)
            + (1.6 if r['new_this_window'] else 0)
            + (1.2 if r['cross_language_gap'] in ('zh_only', 'en_only') and r['distinct_authors'] > 1
               else 0), 2)
    rows.sort(key=lambda r: -r['score'])

    return {
        'run_id': 'hot-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S'),
        'computed_at': now.isoformat(),
        'window_hours': window_hours, 'baseline_hours': baseline_hours,
        'posts_in_window': len(recent), 'posts_in_baseline': len(older),
        'store_posts': len(posts), 'engagement_snapshots': len(snaps),
        'acceleration_available_for': len(accel),
        'acceleration_note': ('a post observed once has no rate of change; run the collector '
                              'again and it becomes measurable'),
        'method': {
            'velocity': "views/hour divided by that author's own median views/hour",
            'spread': 'distinct authors naming the entity inside the window',
            'novelty': 'absent from the trailing baseline window',
            'cross_language': 'named in one watchlist language and not the other',
        },
        'entities': rows,
    }


def main():
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    out = build(int(args.get('window', 48)), int(args.get('baseline', 336)))
    (STORE / 'hotspots.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"window {out['window_hours']}h · {out['posts_in_window']} posts · "
          f"acceleration available for {out['acceleration_available_for']} posts")
    print(f"{'score':>6}  {'entity':14} {'auth':>4} {'ment':>4} {'vel':>5} {'new':>4}  lang")
    for r in out['entities'][:14]:
        print(f"{r['score']:>6}  {r['entity']:14} {r['distinct_authors']:>4} {r['mentions']:>4} "
              f"{str(r['velocity_vs_author_median'] or '—'):>5} {'Y' if r['new_this_window'] else '·':>4}  "
              f"{r['cross_language_gap']}")
    return out


if __name__ == '__main__':
    main()
