"""Source breadth from the Sirius X source list (Oct 8): curated tier-B X sources mapped to the fd20 accounts by topic.

Config in git: live/x_breadth.json - handles and account mapping only (no tweet text, no Sirius repo content),
plus the daily call cap. Local aggregates (no text): live/store/x_breadth/ (candidates, evaluation, call log).

Curation (scripts/x_breadth.py):
1. candidates (0 calls): Sirius handles (content_source_accounts.json: handle, user_id, source_lists) that are not
   already our X sources or donors, minus handle-name org patterns; ranked by how often each account's donors
   @-mention them (all donor history) - the zero-cost topical prior.
2. evaluate (1 twitter241 /user-tweets call per handle, user id known so no /user lookup; capped): bio, followers,
   verified type, originals per day, reply / repost / promo share, language, theme mix (live/topic_div) - aggregates
   only.
3. assign: individual, active, low-promo handles -> up to 2 same-language accounts by
   0.6 x cosine(handle theme mix, account donor theme mix over 30 days) + 0.4 x normalised donor mentions;
   at most PER_ACCOUNT per account.

Daily intake (`fetch`, called from live/x_daily.gather): batched /search-v2 `(from:a OR from:b ...)` Latest, newest
first, up to PAGES pages per batch until the page is older than the window; batches rotate through the day so the
day's calls never exceed `daily_call_cap` (call log per day). Posts then go through the same x_daily filters,
dedupe and flash extraction as the CORE sources; units are account-scoped to the mapped accounts.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'live' / 'x_breadth.json'
HOST = 'twitter241.p.rapidapi.com'
USER_AGENT = 'Mozilla/5.0 (compatible; fd-x-breadth/1.0)'
PER_ACCOUNT = 8
MAX_ACCOUNTS_PER_HANDLE = 2
BATCH = 20                 # handles per search query (query stays < 512 chars)
PAGES = 4                  # pages per batch at most (20 posts a page; 4 covered 24h in the Oct 8 trial)
DAILY_CALL_CAP = 20        # default; the config value wins
ORG_HANDLE = re.compile(r'(labs?|protocol|finance|_?fi$|_io$|xyz$|dao$|exchange|wallet|official|news|network|ventures|'
                        r'_vc$|fund$|_app$|hq$|global$|swap|bot$|foundation|_zh$|zh$|cn$|chinese|research$|capital$|'
                        r'markets?$|daily$|insights?$|alerts?$|_ai$)', re.I)
ORG_BIO = re.compile(r'\bofficial\b|\bprotocol\b|\bwe (?:are|build)|\bour\b|building the|the (?:first|leading|home of)|'
                     r'\bplatform\b|\bexchange\b|\bwallet\b|\bnetwork\b|\bfoundation\b|\bnews\b|\bmedia\b|官方|官推|交易所|'
                     r'\bdao\b|\bchain\b for|layer ?[12] (?:for|built)|backed by', re.I)


def store_dir():
    return Path(os.environ.get('FD_X_BREADTH_STORE') or ROOT / 'live' / 'store' / 'x_breadth')


def load_config(path=None):
    path = Path(path or CONFIG)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def enabled(env=None, config=None):
    env = env if env is not None else os.environ
    cfg = config if config is not None else load_config()
    return env.get('FD_X_BREADTH', '1') != '0' and bool(cfg.get('handles'))


# ------------------------------------------------------------------ curation

def candidates(sirius, exclude, mentions):
    """[(handle, user_id, mention total, {account: n})] ranked by donor mentions; org-looking handles dropped."""
    out = []
    for row in sirius:
        h = str(row.get('handle') or '').lstrip('@')
        if not h or h.lower() in exclude or ORG_HANDLE.search(h):
            continue
        m = mentions.get(h.lower()) or {}
        out.append((h, str(row.get('user_id') or ''), sum(m.values()), dict(m)))
    return sorted(out, key=lambda r: (-r[2], r[0].lower()))


def mention_candidates(by_donor, exclude, uids=None, min_donors=2, extra=()):
    """Oct 8 (market_data_charts had 0 Sirius handles): [(handle, user_id, mention total, {donor: n})] from one
    account's donor @-mention graph. A handle needs >= min_donors distinct donors citing it; `extra` (e.g. unused
    verified roster donors of the account's category) needs one. Existing sources / donors and org-looking
    handles are left out, like candidates()."""
    uids = {k.lower(): v for k, v in (uids or {}).items()}
    extra = {h.lower() for h in extra}
    out = []
    for h, donors in by_donor.items():
        hl = h.lower()
        if hl in exclude or ORG_HANDLE.search(h) or len(donors) < (0 if hl in extra and not donors else 1 if hl in extra else min_donors):
            continue
        out.append((h, str(uids.get(hl) or ''), sum(donors.values()), dict(donors)))
    return sorted(out, key=lambda r: (-len(r[3]), -r[2], r[0].lower()))


def merge_assigned(handles, picked, evals, accounts):
    """Config `handles` with the picks for `accounts` added (other handles and accounts untouched)."""
    out = {h: dict(v, accounts=list(v.get('accounts') or []), scores=dict(v.get('scores') or {}))
           for h, v in (handles or {}).items()}
    low = {h.lower(): h for h in out}
    for aid in accounts:
        for h, score, _why in picked.get(aid) or []:
            key = low.get(h.lower(), h)
            e = evals[h.lower()]
            row = out.setdefault(key, {'lang': e['lang'], 'accounts': [], 'scores': {},
                                       'originals_per_day': e['originals_per_day']})
            low[h.lower()] = key
            if aid not in row['accounts']:
                row['accounts'].append(aid)
            row['scores'][aid] = score
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def user_of(page, uid):
    """The timeline owner's profile fields (legacy + verified flags) from a /user-tweets page."""
    found = {}

    def walk(o):
        if found:
            return
        if isinstance(o, dict):
            if o.get('rest_id') == uid and isinstance(o.get('legacy'), dict):
                lg = o['legacy']
                core = o.get('core') if isinstance(o.get('core'), dict) else {}
                ver = o.get('verification') if isinstance(o.get('verification'), dict) else {}
                found.update(description=lg.get('description') or '', followers=lg.get('followers_count'),
                             statuses=lg.get('statuses_count'),
                             verified_type=lg.get('verified_type') or ver.get('verified_type'),
                             name=lg.get('name') or core.get('name') or '', blue=o.get('is_blue_verified'),
                             # X shows verified organisations with a square avatar
                             shape=o.get('profile_image_shape'))
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(page)
    return found


def is_org(prof):
    return bool(ORG_BIO.search(prof.get('description') or '') or ORG_HANDLE.search(prof.get('name') or '')
                or prof.get('verified_type') in ('Business', 'Government') or prof.get('shape') == 'Square')


def evaluate_page(handle, uid, page, now, posts=None):
    """Aggregates of one handle (no text): activity, shares, language, theme mix, org signal."""
    from live import topic_div, x_daily
    if posts is None:
        import sys
        sys.path.insert(0, str(ROOT / 'scripts'))
        from scrape_donor_posts import timeline_posts
        posts = timeline_posts(page)
    prof = user_of(page, uid) if page is not None else {}
    own = [p for p in posts if p.get('uid') in (None, uid) and not p.get('pinned')]
    times = [t for t in (x_daily._parse_created(p.get('created')) for p in own) if t]
    originals = [p for p in own if not p.get('rt') and not p.get('reply') and not p.get('self_thread')]
    span_d = max(1.0, (now - min(times)).total_seconds() / 86400) if times else 7.0
    week = [p for p in originals if (x_daily._parse_created(p.get('created')) or now - timedelta(days=99)) >= now - timedelta(days=7)]
    texts = [x_daily.clean_text(p.get('text')) for p in originals]
    langs = [x_daily.lang_of(t, p.get('lang')) for t, p in zip(texts, originals)]
    themes = {}
    for t in texts:
        th = topic_div.theme_of(t)
        themes[th] = themes.get(th, 0) + 1
    promo = sum(1 for t in texts if x_daily.PROMO.search(t))
    newest = max(times).isoformat(timespec='minutes') if times else None
    org = is_org(prof)
    return {'handle': handle, 'user_id': uid, 'fetched': len(posts), 'own': len(own), 'originals': len(originals),
            'originals_7d': len(week), 'originals_per_day': round(len(originals) / span_d, 2),
            'reply_share': round(sum(1 for p in own if p.get('reply')) / len(own), 3) if own else None,
            'repost_share': round(sum(1 for p in own if p.get('rt')) / len(own), 3) if own else None,
            'promo_share': round(promo / len(originals), 3) if originals else None,
            'avg_chars': round(sum(len(t) for t in texts) / len(texts)) if texts else 0,
            'lang': max(set(langs), key=langs.count) if langs else None,
            'zh_share': round(langs.count('zh') / len(langs), 3) if langs else None,
            'themes': dict(sorted(themes.items(), key=lambda kv: -kv[1])), 'newest_at': newest,
            'followers': prof.get('followers'), 'verified_type': prof.get('verified_type'), 'org': org,
            'avatar_shape': prof.get('shape'),
            'bio_chars': len(prof.get('description') or '')}


def usable(ev, now):
    """Individual, active (>= 2 originals in the last 7 days, newest <= 3 days), <= 25% promo, readable posts."""
    if not ev or ev.get('org') or ev.get('lang') is None:
        return False, 'org' if ev and ev.get('org') else 'no_posts'
    if (ev.get('followers') or 0) > 3_000_000:
        return False, 'celebrity'
    newest = ev.get('newest_at')
    if not newest or now - datetime.fromisoformat(newest) > timedelta(days=3) or ev['originals_7d'] < 2:
        return False, 'inactive'
    if (ev.get('promo_share') or 0) > 0.25:
        return False, 'promo'
    if ev.get('avg_chars', 0) < (40 if ev['lang'] == 'zh' else 80):
        return False, 'short_posts'
    return True, None


def _crypto_share(mix):
    total = sum(mix.values())
    return sum(v for k, v in mix.items() if k.startswith('c_')) / total if total else 0.0


def _cos(a, b):
    keys = set(a) | set(b)
    num = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    da = math.sqrt(sum(v * v for v in a.values()))
    db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


def assign(evals, account_mix, account_lang, mentions, now, per_account=PER_ACCOUNT,
           per_handle=MAX_ACCOUNTS_PER_HANDLE, existing=None):
    """{account: [(handle, score, why)]} - same language only; 'other' left out of the cosine (chatter)."""
    existing = existing or {}
    scored = []
    for ev in evals:
        ok, _ = usable(ev, now)
        if not ok:
            continue
        mix = {k: v for k, v in ev['themes'].items() if k != 'other'}
        m = mentions.get(ev['handle'].lower()) or {}
        mmax = max(m.values()) if m else 0
        for aid, lang in account_lang.items():
            if ev['lang'] != lang:
                continue
            amix = {k: v for k, v in (account_mix.get(aid) or {}).items() if k != 'other'}
            # a mostly-crypto handle is no source for a mostly-non-crypto account (the beat gate would drop its posts)
            if _crypto_share(amix) < 0.3 and _crypto_share(mix) > 0.5:
                continue
            cos = _cos(mix, amix)
            men = (m.get(aid, 0) / mmax) if mmax else 0.0
            score = round(0.6 * cos + 0.4 * men, 4)
            if score >= 0.35:
                scored.append((score, aid, ev['handle'], round(cos, 3), m.get(aid, 0)))
    scored.sort(key=lambda r: (-r[0], r[2].lower(), r[1]))
    out, per_h = {}, {}
    # accounts with the fewest own X sources fill first inside each score band of 0.05
    for score, aid, h, cos, men in sorted(scored, key=lambda r: (-round(r[0] / 0.05), len(existing.get(r[1]) or ()), -r[0])):
        if len(out.get(aid, [])) >= per_account or per_h.get(h, 0) >= per_handle:
            continue
        out.setdefault(aid, []).append((h, score, {'theme_cos': cos, 'donor_mentions': men}))
        per_h[h] = per_h.get(h, 0) + 1
    return out


# ------------------------------------------------------------------ daily intake

class Client:
    """twitter241 GET with a call cap and a per-day call log (never logs the key or any text)."""

    def __init__(self, key, cap, log_path, timeout=40):
        self.key, self.left, self.made, self.timeout, self.log = key, max(0, int(cap)), 0, timeout, Path(log_path)

    def get(self, path, **params):
        if self.left <= 0:
            raise RuntimeError('x_breadth: call cap reached')
        self.left -= 1
        self.made += 1
        url = f'https://{HOST}{path}?{urllib.parse.urlencode(params)}'
        req = urllib.request.Request(url, headers={'x-rapidapi-key': self.key, 'x-rapidapi-host': HOST,
                                                   'User-Agent': USER_AGENT})
        entry = {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'endpoint': path,
                 'n_handles': str(params.get('query', '')).count('from:') or None, 'user': params.get('user')}
        try:
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as r:
                        entry['status'] = r.status
                        return json.load(r)
                except Exception:
                    if attempt == 1:
                        raise
                    time.sleep(2)
        except Exception as exc:
            entry.update(status='error', error=f'{type(exc).__name__}: {str(exc)[:120]}')
            raise
        finally:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with self.log.open('a') as f:
                f.write(json.dumps(entry) + '\n')


def calls_made(log_path):
    try:
        return len(Path(log_path).read_text().splitlines())
    except OSError:
        return 0


def subscriptions(config=None):
    """x_daily-shaped rows for the breadth handles: role BREADTH, tier B (individual analysts)."""
    cfg = config if config is not None else load_config()
    rows = []
    for h, meta in sorted((cfg.get('handles') or {}).items(), key=lambda kv: kv[0].lower()):
        rows.append({'handle': h, 'source_id': 'x_' + h, 'accounts': list(meta.get('accounts') or []),
                     'roles': ['BREADTH'], 'tier': 'B', 'core': False, 'breadth': True})
    return rows


def batches(subs, size=BATCH):
    """Handles grouped by their first account (so a batch's posts share a topic), then chunked."""
    subs = sorted(subs, key=lambda s: ((s['accounts'] or [''])[0], s['handle'].lower()))
    return [subs[i:i + size] for i in range(0, len(subs), size)]


def rotation(n_batches, day, calls_left, pages=PAGES):
    """Which batches run today when the cap cannot cover all of them: a day-of-year offset round robin."""
    if n_batches == 0 or calls_left <= 0:
        return []
    k = max(1, min(n_batches, calls_left // max(1, pages) or 1))
    start = (datetime.fromisoformat(str(day)).timetuple().tm_yday * k) % n_batches
    return [(start + i) % n_batches for i in range(k)]


def fetch(subs, *, now, day, window_hours, key=None, config=None, client=None, search=None, pages=None):
    """{handle_lower: [normalised posts]} for today's batches + info. search(query, cursor) -> page is injectable."""
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from scrape_donor_posts import timeline_posts
    from live import x_daily
    cfg = config if config is not None else load_config()
    cap = int(cfg.get('daily_call_cap', DAILY_CALL_CAP))
    pages = int(pages or cfg.get('pages_per_batch', PAGES))
    log = store_dir() / f'{day}.calls.jsonl'
    left = cap - calls_made(log)
    if search is None:
        key = key or os.environ.get('RAPID_X_API_KEY')
        if not key:
            return {}, {'skipped': 'no RAPID_X_API_KEY'}
        client = client or Client(key, left, log)
        search = lambda q, cursor=None: client.get('/search-v2', type='Latest', count=20, query=q,  # noqa: E731
                                                   **({'cursor': cursor} if cursor else {}))
    groups = batches(subs, int(cfg.get('batch_size', BATCH)))
    todo = rotation(len(groups), day, left, pages)
    since = now - timedelta(hours=window_hours)
    uid_handle = {str(s.get('user_id')): s['handle'].lower() for s in subs if s.get('user_id')}
    wanted = {s['handle'].lower() for s in subs}
    out, info = {}, {'batches': len(groups), 'run_batches': todo, 'calls': 0, 'errors': [], 'cap': cap,
                     'calls_before': cap - left}
    info['run_handles'] = [s['handle'].lower() for bi in todo for s in groups[bi]]
    for bi in todo:
        names = [s['handle'] for s in groups[bi]]
        query = '(' + ' OR '.join('from:' + h for h in names) + ') -filter:replies -filter:retweets'
        cursor = None
        for _ in range(pages):
            try:
                page = search(query, cursor)
            except Exception as exc:   # noqa: BLE001 - cap reached / transport: stop this batch
                info['errors'].append(f'{type(exc).__name__}: {str(exc)[:100]}')
                break
            info['calls'] += 1
            posts = timeline_posts(page)
            uid_handle.update(screen_names(page, wanted))
            oldest = None
            for p in posts:
                h = uid_handle.get(str(p.get('uid')))
                if h:
                    p['handle'] = h
                    out.setdefault(h, []).append(p)
                t = x_daily._parse_created(p.get('created'))
                oldest = t if oldest is None or (t and t < oldest) else oldest
            cursor = _bottom_cursor(page)
            if not posts or not cursor or (oldest and oldest < since):
                break
    return out, info


def screen_names(page, wanted):
    """{user id: handle_lower} for the authors on a search page whose screen name is one of `wanted` (the git
    config keeps handles only; ids come from the page)."""
    out = {}

    def walk(o):
        if isinstance(o, dict):
            rid = o.get('rest_id')
            if rid:
                names = [(o.get('legacy') or {}).get('screen_name'), (o.get('core') or {}).get('screen_name')
                         if isinstance(o.get('core'), dict) else None]
                for n in names:
                    if n and n.lower() in wanted:
                        out[str(rid)] = n.lower()
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(page)
    return out


def _bottom_cursor(page):
    found = []

    def walk(o):
        if isinstance(o, dict):
            if o.get('cursorType') == 'Bottom' and o.get('value'):
                found.append(o['value'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(page)
    if not found and isinstance(page, dict):
        c = page.get('cursor') or {}
        if isinstance(c, dict) and c.get('bottom'):
            found.append(c['bottom'])
    return found[0] if found else None
