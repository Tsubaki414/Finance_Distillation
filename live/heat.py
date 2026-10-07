"""Public-heat signals for topic selection: what the wider public is searching / upvoting today.

Sources (all free, unauthenticated, one request each, cached per day under live/store/heat/<day>.json):
- Google Trends daily trending searches RSS (US)            trends.google.com/trending/rss
- Reddit hot JSON, r/CryptoCurrency + r/wallstreetbets       www.reddit.com/r/<sub>/hot.json (403 from some hosts)
- Eastmoney hot-stock rank (codes) + names via push2delay     emappdata.eastmoney.com/stockrank
- Bilibili hot search words                                   s.search.bilibili.com/main/hotword
- Douyin hot list: skipped (needs a signed web API, not cheap) - recorded as skipped, never fetched.

Rules (enforced by `promote`, not by callers):
- Heat only re-ranks an account's own candidate pool (already filtered to its lanes / beat gate). It never adds a
  topic, so an off-position topic cannot enter through heat.
- At most one heat-led draft per account per day (`promote(..., already_led=True)` is a no-op), tagged heat_led.
- A cost cap (default $0.20/day, FD_HEAT_COST_CAP_USD) is charged per fetch at each source's estimated cost; the
  current sources cost $0, so the cap only matters if a paid source is added.
- Flag: FD_HEAT=1 by default; FD_HEAT=0 turns heat off (selection is then exactly the old order).
"""
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(os.environ.get('FD_HEAT_STORE', ROOT / 'live/store/heat'))
UA = {'User-Agent': 'Mozilla/5.0 (fd-heat; research)'}
TIMEOUT = 15
TTL_S = 3 * 3600
DEFAULT_CAP_USD = 0.20
MIN_SCORE = 1.0

# name -> estimated USD per fetch (all public endpoints: 0)
SOURCES = {'google_trends': 0.0, 'reddit': 0.0, 'eastmoney': 0.0, 'bilibili': 0.0}
SKIPPED = {'douyin': 'not cheap: the hot list needs a signed web API / paid scraper'}
WEIGHT = {'google_trends': 1.0, 'reddit': 0.6, 'eastmoney': 0.8, 'bilibili': 0.7}
GENERIC = {'today', 'news', 'market', 'stock market', 'price', 'live', 'update', 'weather', 'game', 'score',
           'daily discussion', 'what are your moves tomorrow', 'moves tomorrow', 'discussion thread'}


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_HEAT', '1') != '0'


def cost_cap(env=None):
    try:
        return float((env if env is not None else os.environ).get('FD_HEAT_COST_CAP_USD', DEFAULT_CAP_USD))
    except ValueError:
        return DEFAULT_CAP_USD


def _get(url, method='GET', **kw):
    r = requests.request(method, url, headers={**UA, **kw.pop('headers', {})}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def fetch_google_trends(geo='US'):
    root = ET.fromstring(_get(f'https://trends.google.com/trending/rss?geo={geo}').content)
    ns = {'ht': 'https://trends.google.com/trending/rss'}
    out = []
    for i, item in enumerate(root.iter('item')):
        news = ' | '.join(t.text or '' for t in item.findall('ht:news_item/ht:news_item_title', ns))
        out.append({'term': (item.findtext('title') or '').strip(), 'rank': i + 1, 'context': news[:300],
                    'traffic': item.findtext('ht:approx_traffic', default='', namespaces=ns)})
    return out


def fetch_reddit(subs=('CryptoCurrency', 'wallstreetbets')):
    out = []
    for sub in subs:
        data = _get(f'https://www.reddit.com/r/{sub}/hot.json?limit=50&raw_json=1').json()
        for i, c in enumerate((data.get('data') or {}).get('children') or []):
            d = c.get('data') or {}
            if d.get('stickied'):
                continue
            out.append({'term': (d.get('title') or '').strip(), 'rank': i + 1, 'sub': sub, 'score': d.get('score')})
    return out


def fetch_eastmoney(n=30):
    rank = _get('https://emappdata.eastmoney.com/stockrank/getAllCurrentList', method='POST',
                json={'appId': 'appId01', 'globalId': '786e4c21-70dc-435a-93bb-38', 'marketType': '',
                      'pageNo': 1, 'pageSize': n}).json().get('data') or []
    codes = [(x['sc'], x['rk']) for x in rank if x.get('sc')]
    secids = ','.join(('1.' if sc.startswith('SH') else '0.') + sc[2:] for sc, _ in codes)
    names = {}
    if secids:
        diff = ((_get(f'https://push2delay.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f12,f14&secids={secids}')
                 .json().get('data') or {}).get('diff') or [])
        names = {d['f12']: d['f14'] for d in diff if d.get('f12')}
    return [{'term': names.get(sc[2:], sc), 'code': sc, 'rank': rk} for sc, rk in codes]


def fetch_bilibili():
    data = _get('https://s.search.bilibili.com/main/hotword').json()
    return [{'term': (x.get('keyword') or '').strip(), 'rank': i + 1} for i, x in enumerate(data.get('list') or [])]


FETCHERS = {'google_trends': fetch_google_trends, 'reddit': fetch_reddit, 'eastmoney': fetch_eastmoney,
            'bilibili': fetch_bilibili}


def load(day, store=None):
    try:
        return json.loads(((store or STORE) / f'{day}.json').read_text())
    except (OSError, ValueError):
        return None


def fetch(day, store=None, fetchers=None, cap=None, force=False):
    """Today's signals {day, fetched_at, items: [{source, term, rank, ...}], errors, skipped, cost_usd}; cached 3h.
    A failing source is recorded in `errors` and skipped; never raises."""
    store = store or STORE
    cached = load(day, store)
    if cached and not force and time.time() - cached.get('fetched_ts', 0) < TTL_S:
        return cached
    cap = cost_cap() if cap is None else cap
    spent = (cached or {}).get('cost_usd', 0.0)
    items, errors = [], {}
    for name, fn in (fetchers or FETCHERS).items():
        est = SOURCES.get(name, 0.0)
        if spent + est > cap:
            errors[name] = f'cost cap ${cap:.2f}/day reached'
            continue
        try:
            got = fn()
            spent += est
        except Exception as exc:   # noqa: BLE001 - one dead source never blocks selection
            errors[name] = f'{type(exc).__name__}: {str(exc)[:160]}'
            continue
        items += [{'source': name, **x} for x in got if x.get('term')]
    now = datetime.now(timezone.utc)
    out = {'day': day, 'fetched_at': now.isoformat(timespec='seconds'), 'fetched_ts': now.timestamp(),
           'items': items, 'errors': errors, 'skipped': SKIPPED, 'cost_usd': round(spent, 4), 'cost_cap_usd': cap}
    try:
        store.mkdir(parents=True, exist_ok=True)
        (store / f'{day}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ scoring

def _signals(items):
    """[(weight, phrase or None, subjects)] from raw items."""
    from live.charts import subjects_in
    out = []
    for it in items:
        term = str(it.get('term') or '').strip()
        w = WEIGHT.get(it.get('source'), 0.5) / (1 + (int(it.get('rank') or 1) - 1) / 10)
        low = term.lower()
        cjk = len(re.findall(r'[一-鿿]', term))
        phrase = low if (low not in GENERIC and (cjk >= 2 or len(low) >= 4)) else None
        if it.get('source') == 'reddit':
            phrase = None   # reddit titles are sentences: only the subjects they name count
        out.append((w, phrase, subjects_in(f"{term} {it.get('context') or ''}")))
    return out


def score(text, signals):
    """(score, matched terms) of one candidate text against today's signals."""
    from live.charts import subjects_in
    low = (text or '').lower()
    subs = subjects_in(text or '')
    total, hits = 0.0, []
    for w, phrase, s in signals:
        if phrase and phrase in low:
            total += w
            hits.append(phrase)
        elif s & subs:
            total += w * 0.5
            hits += sorted(s & subs)
    return round(total, 3), sorted(set(hits))


def promote(pool, text_of, signals, ok=None, already_led=False, min_score=MIN_SCORE):
    """Move the hottest acceptable candidate of an account's own pool to the front.

    pool: candidates in the current order (never extended); text_of(c) -> text; ok(c) -> bool filters candidates
    that may lead (e.g. prescreen ok and timely). Returns (new pool, info or None); info = {'index', 'score',
    'terms'} for the promoted candidate. No-op when the account already has a heat-led draft today, when nothing
    scores >= min_score, or when the hottest candidate is already first."""
    if already_led or not pool or not signals:
        return list(pool), None
    best = None
    for i, c in enumerate(pool):
        if ok and not ok(c):
            continue
        s, terms = score(text_of(c), signals)
        if s >= min_score and (best is None or s > best[1]):
            best = (i, s, terms)
    if best is None:
        return list(pool), None
    i, s, terms = best
    first_score = score(text_of(pool[0]), signals)[0]
    if i == 0 or first_score >= s:   # heat did not change the pick: not heat-led
        return list(pool), None
    return [pool[i]] + pool[:i] + pool[i + 1:], {'index': i, 'score': s, 'terms': terms}


def signals_for(day, store=None, env=None):
    """Prepared signals for `day` (fetching when stale), or [] when FD_HEAT=0."""
    if not enabled(env):
        return []
    return _signals(fetch(day, store=store).get('items') or [])
