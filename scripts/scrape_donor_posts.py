"""Scrape donor posts into live/donors/posts/<handle>.jsonl (voice exemplars only).

Provider: RapidAPI twitter241 (/user, /user-tweets with cursor paging), key in
RAPID_X_API_KEY. Read-only: never posts, likes or follows. Each run merges with
the existing file (dedup by post id) and stops a donor once it has --target
non-repost posts, the timeline ends, or --max-pages is reached; --max-requests
caps the whole run. Apify (APIFY_TOKEN) is the documented fallback provider
for donors the RapidAPI timeline cannot page deep enough (not wired here).

Usage:
  python scripts/scrape_donor_posts.py --cluster macro_zh --limit 5 --target 200
  python scripts/scrape_donor_posts.py qinbafrank PhyrexNi --target 200
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOST = 'twitter241.p.rapidapi.com'


def _unwrap(t):
    if t and t.get('__typename') == 'TweetWithVisibilityResults':
        t = t.get('tweet')
    return t


def normalise(t, pinned=False):
    t = _unwrap(t)
    if not t or 'legacy' not in t:
        return None
    legacy = t['legacy']
    note = (((t.get('note_tweet') or {}).get('note_tweet_results') or {}).get('result') or {}).get('text')
    text = note or legacy.get('full_text', '')
    media = (legacy.get('extended_entities') or {}).get('media') or (legacy.get('entities') or {}).get('media') or []
    reply_to = legacy.get('in_reply_to_status_id_str')
    return {'id': t.get('rest_id'), 'uid': legacy.get('user_id_str'), 'created': legacy.get('created_at'),
            'text': text, 'lang': legacy.get('lang'), 'is_note': bool(note),
            'rt': 'retweeted_status_result' in legacy,
            'quote': bool(legacy.get('is_quote_status')) and 'retweeted_status_result' not in legacy,
            'reply': bool(reply_to) and legacy.get('in_reply_to_user_id_str') != legacy.get('user_id_str'),
            'self_thread': bool(reply_to) and legacy.get('in_reply_to_user_id_str') == legacy.get('user_id_str'),
            'pinned': pinned, 'media': [m.get('type') for m in media],
            'likes': legacy.get('favorite_count', 0), 'views': int((t.get('views') or {}).get('count') or 0)}


def timeline_posts(obj):
    out = []
    for ins in ((obj.get('result') or {}).get('timeline') or {}).get('instructions') or []:
        entries = ins.get('entries') or ([ins['entry']] if 'entry' in ins else [])
        for e in entries:
            c = e.get('content') or {}
            pinned = ins.get('type') == 'TimelinePinEntry'
            tr = ((c.get('itemContent') or {}).get('tweet_results') or {}).get('result')
            if tr:
                n = normalise(tr, pinned)
                if n:
                    out.append(n)
            for it in c.get('items') or []:
                tr = (((it.get('item') or {}).get('itemContent') or {}).get('tweet_results') or {}).get('result')
                n = normalise(tr) if tr else None
                if n:
                    out.append(n)
    return out


def bottom_cursor(obj):
    c = obj.get('cursor')
    if isinstance(c, dict) and c.get('bottom'):
        return c['bottom']
    for ins in ((obj.get('result') or {}).get('timeline') or {}).get('instructions') or []:
        for e in ins.get('entries') or []:
            content = e.get('content') or {}
            if content.get('cursorType') == 'Bottom':
                return content.get('value')
    return None


def merge(existing, new, uid=None):
    seen = {p['id']: p for p in existing}
    for p in new:
        if p.get('id') and (uid is None or p.get('uid') == uid or p.get('rt')):
            seen.setdefault(p['id'], p)
    return sorted(seen.values(), key=lambda p: -int(p['id']))


class Client:
    def __init__(self, key, max_requests):
        self.key, self.left, self.made = key, max_requests, 0

    def get(self, path, **params):
        if self.left <= 0:
            raise RuntimeError('request budget exhausted')
        self.left -= 1
        self.made += 1
        url = f'https://{HOST}{path}?{urllib.parse.urlencode(params)}'
        req = urllib.request.Request(url, headers={'x-rapidapi-key': self.key, 'x-rapidapi-host': HOST})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.load(r)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 + 3 * attempt)


def scrape(client, handle, out_dir, target, max_pages):
    path = out_dir / f'{handle.lower()}.jsonl'
    existing = [json.loads(l) for l in path.read_text().split('\n') if l.strip()] if path.exists() else []
    user = client.get('/user', username=handle)['result']['data']['user']['result']
    uid = user['rest_id']
    posts, cursor, pages = existing, None, 0
    while pages < max_pages and sum(not p['rt'] for p in posts) < target:
        params = {'user': uid, 'count': 40}
        if cursor:
            params['cursor'] = cursor
        obj = client.get('/user-tweets', **params)
        pages += 1
        new = timeline_posts(obj)
        before = len(posts)
        posts = merge(posts, new, uid)
        cursor = bottom_cursor(obj)
        if not cursor or len(posts) == before:
            break
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(p, ensure_ascii=False) + '\n' for p in posts))
    originals = [p for p in posts if not p['rt']]
    return {'handle': handle, 'pages': pages, 'posts': len(posts), 'non_repost': len(originals),
            'original_no_reply': sum(not p['reply'] for p in originals),
            'oldest': min((p['created'] for p in posts), default=None, key=lambda s: time.strptime(s, '%a %b %d %H:%M:%S +0000 %Y')),
            'reached_target': len(originals) >= target}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('handles', nargs='*')
    ap.add_argument('--cluster', action='append', default=[])
    ap.add_argument('--limit', type=int)
    ap.add_argument('--target', type=int, default=200)
    ap.add_argument('--max-pages', type=int, default=12)
    ap.add_argument('--max-requests', type=int, default=200)
    ap.add_argument('--out', type=Path, default=ROOT / 'live' / 'donors' / 'posts')
    ap.add_argument('--report', type=Path)
    args = ap.parse_args()
    key = os.environ.get('RAPID_X_API_KEY')
    if not key:
        raise SystemExit('RAPID_X_API_KEY is missing')
    from live import registry
    handles = list(args.handles)
    roster = registry.load_donor_roster()
    for name in args.cluster:
        handles += [d['handle'] for d in roster['persona_clusters'][name]['donors']]
    handles = list(dict.fromkeys(handles))[:args.limit]
    client = Client(key, args.max_requests)
    rows = []
    for h in handles:
        try:
            row = scrape(client, h, args.out, args.target, args.max_pages)
        except Exception as exc:
            row = {'handle': h, 'error': f'{type(exc).__name__}: {str(exc)[:120]}'}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {'requests': client.made, 'donors': len(rows),
               'reached_target': sum(bool(r.get('reached_target')) for r in rows), 'rows': rows}
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}))
    if args.report:
        args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
