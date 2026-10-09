"""Post-performance review (Oct 9): metrics of published FD drafts joined to their draft metadata.

fetch:   one RapidAPI twitter241 /user (followers) + /user-tweets page per our account with a handle that has
         published drafts on the given days; raw pages cached under --out/raw (read-only API, RAPID_X_API_KEY).
join:    match each published draft (admin_decisions published flag) to our own timeline by text similarity and
         write --out/perf.jsonl: metrics (views/likes/replies/reposts, age), views per follower and draft metadata
         (account, group, lane, post_type, format, angle, 母题 heat, source type, media, engage mode, post time).
"""
import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STORE = ROOT / 'live' / 'store'
URL = re.compile(r'https?://\S+')
WS = re.compile(r'\s+')


def norm(text):
    return WS.sub('', URL.sub('', text or '')).lower()


def similarity(a, b):
    a, b = norm(a)[:220], norm(b)[:220]
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def published(days):
    out = []
    for day in days:
        f = STORE / 'admin_decisions' / f'{day}.json'
        if not f.exists():
            continue
        for did, dec in json.loads(f.read_text())['decisions'].items():
            if not dec.get('published'):
                continue
            row = None
            for p in sorted((STORE / 'compose_inbox').glob(f'*/{did}.json')):
                row = json.loads(p.read_text())
            if row:
                out.append({'decision': dec, 'draft': row, 'day': day})
    return out


def source_type(draft):
    src = draft.get('source') or {}
    sid = str(src.get('source_id') or src.get('id') or '')
    if draft.get('archive') or str(draft.get('id', '')).startswith(('arc-', 'evg-')):
        return 'archive'
    if re.match(r'^x[-_]', sid) or 'x.com/' in str(src.get('url') or ''):
        return 'x_post'
    if draft.get('packet') == 'data' or 'lane_data' in sid or re.search(r'defillama|polymarket|coingecko|binance', sid):
        return 'data'
    return 'news'


def motif_heat(days):
    """source id / key -> (motif id, heat score, source_count, type) from the hotspot files around the days."""
    out = {}
    for f in sorted((STORE / 'hotspot').glob('*.json')):
        if f.name.endswith('.merge.json'):
            continue
        try:
            h = json.loads(f.read_text())
        except Exception:
            continue
        for m in h.get('motifs') or []:
            info = (m['id'], (m.get('heat') or {}).get('score'), m.get('source_count'), m.get('type'), m.get('pool'))
            for mem in m.get('members') or []:
                for k in mem.get('key') or []:
                    out.setdefault(k, info)
    return out


def fetch(handles, out, max_requests=80):
    from live.x_daily import RapidClient
    from scripts.scrape_donor_posts import timeline_posts
    key = os.environ.get('RAPID_X_API_KEY')
    if not key:
        raise SystemExit('RAPID_X_API_KEY missing')
    client = RapidClient(key, max_requests=max_requests)
    raw = out / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    for h in handles:
        try:
            user = client.get('/user', username=h)['result']['data']['user']['result']
            legacy = user.get('legacy') or {}
            followers = legacy.get('followers_count')
            if followers is None:
                followers = (user.get('relationship_counts') or {}).get('followers')
            uid = user['rest_id']
            posts = timeline_posts(client.get('/user-tweets', user=uid, count=40))
            posts = [p for p in posts if p.get('uid') in (None, uid)]
            (raw / f'{h.lower()}.json').write_text(json.dumps(
                {'handle': h, 'uid': uid, 'followers': followers, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                 'posts': posts}, ensure_ascii=False))
            print(f'{h}: followers {followers}, {len(posts)} posts', flush=True)
        except Exception as exc:   # noqa: BLE001
            print(f'{h}: error {type(exc).__name__}: {str(exc)[:120]}', flush=True)
    print(f'rapid requests {client.made}', flush=True)


def created(p):
    try:
        return datetime.strptime(p['created'], '%a %b %d %H:%M:%S %z %Y').astimezone(timezone.utc)
    except Exception:
        return None


def join(rows, accounts, out, min_sim=0.45):
    heat = motif_heat(None)
    now = datetime.now(timezone.utc)
    res = []
    for r in rows:
        d, acc = r['draft'], accounts.get(r['draft']['account_id']) or {}
        h = acc.get('handle')
        f = out / 'raw' / f'{(h or "").lower()}.json'
        page = json.loads(f.read_text()) if h and f.exists() else None
        best, sim = None, 0.0
        for p in (page or {}).get('posts') or []:
            if p.get('rt'):
                continue
            s = similarity(r['decision'].get('text') or d.get('text'), p.get('text'))
            if s > sim:
                best, sim = p, s
        if sim < min_sim:
            best = None
        src = d.get('source') or {}
        mh = heat.get(src.get('id')) or heat.get(src.get('source_hash')) or (None, None, None, None, None)
        t = created(best) if best else None
        fmt = d.get('post_format') or {}
        media = d.get('media') or []
        res.append({
            'id': d['id'], 'day': r['day'], 'account_id': d['account_id'], 'no': d.get('no'), 'group': acc.get('group'),
            'lang': d.get('lang'), 'beat': d.get('beat'), 'handle': h, 'followers': (page or {}).get('followers'),
            'post_type': d.get('post_type'), 'format': fmt.get('type'), 'shapes': fmt.get('shapes'),
            'engage': fmt.get('engage'), 'post_mode': d.get('post_mode'),
            'angle': (d.get('angle') or {}).get('id'), 'source_type': source_type(d), 'publisher': src.get('publisher'),
            'source_title': src.get('title'), 'motif': mh[0], 'motif_heat': mh[1], 'motif_sources': mh[2],
            'motif_type': mh[3], 'motif_pool': mh[4],
            'media': bool(media) or (d.get('media_plan') or {}).get('status') == 'made',
            'suggested_london': d.get('suggested_post_time_london'), 'marked_at': r['decision'].get('at'),
            'tweet_id': best and best.get('id'), 'match_sim': round(sim, 3), 'posted_at': t and t.isoformat(),
            'age_h': t and round((now - t).total_seconds() / 3600, 1),
            'tweet_media': best and best.get('media'), 'tweet_quote': best and best.get('quote'),
            'tweet_reply': best and best.get('reply'),
            'views': best and best.get('views'), 'likes': best and best.get('likes'),
            'replies': best and best.get('replies'), 'reposts': best and best.get('reposts'),
            'text_head': (d.get('text') or '')[:80],
        })
    with open(out / 'perf.jsonl', 'w') as fh:
        for x in res:
            fh.write(json.dumps(x, ensure_ascii=False) + '\n')
    m = sum(1 for x in res if x['tweet_id'])
    print(f'joined {len(res)} published drafts, matched {m}', flush=True)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', default='2026-10-07,2026-10-08')
    ap.add_argument('--out', default='/workspace/x/perf')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--max-requests', type=int, default=80)
    a = ap.parse_args(argv)
    from live import fd_accounts
    accounts = {r['id']: r for r in fd_accounts.rows(ROOT / 'live' / 'fd20_accounts.json')}
    rows = published(a.days.split(','))
    out = Path(a.out)
    if a.fetch:
        handles = sorted({accounts[r['draft']['account_id']].get('handle') for r in rows
                          if accounts.get(r['draft']['account_id'], {}).get('handle')})
        fetch(handles, out, a.max_requests)
    join(rows, accounts, out)


if __name__ == '__main__':
    main()
