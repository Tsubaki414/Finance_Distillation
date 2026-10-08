"""Draft images taken from the same sources the donors take theirs from (media v3, Oct 8, Fiona: 「看看他们的source都是
什么；然后去source找」).

Attribution (docs/MEDIA_SOURCES.md): 263 recent donor images across the 20 accounts' donors, each traced to the site /
app / page it came from. About a third are not charts at all (photos, memes, promos). Of the rest the big sources are
TradingView (12% of all images), the donors' own charts and tables (11%), news / flash screenshots (5%), third-party
report charts (5%), exchange apps (Binance / OKX, 4%), X post screenshots (3%), CryptoQuant + Glassnode (4%).

Only sources whose public page may be loaded by a program are captured here (robots.txt allows the path and the
site's terms do not forbid automated access, or the page is the site's official embed meant for third-party display):

  x_post      the X post the draft is built on: X's official embed (platform.twitter.com/embed/Tweet.html)
  etf_flows   Farside Investors daily ETF flow table (light) / SoSoValue US spot ETF dashboard (dark), BTC ETH SOL ZEC
  polymarket  Polymarket's official market embed (embed.polymarket.com), market found through the public gamma API
  article     flash / article page of an allow-listed Chinese crypto news site (BlockBeats, PANews, Odaily) when the
              draft's source is one; phone-width shot like the donors' (no current ingest source maps here yet)

Pages whose terms forbid bots (CoinDesk, The Block, Glassnode, CryptoQuant, DefiLlama, CoinGlass, StockCharts), that
block headless browsers (CME FedWatch, Trading Economics) or that need an app / login / subscription (Binance / OKX /
Futu apps, Bloomberg, MarketSurge, YCharts, The Daily Shot, bank research) are never loaded. When a draft matches one
of them, manual_sources() names the exact public page so a reviewer can screenshot it by hand.

Every capture: scripts/chart_capture.py in a subprocess, fresh headless context (no cookies, no login), one page
load, consent / geo banners hidden with CSS (never clicked), the page text checked for walls / errors / blanks, the
PNG cached per page and hour (data pages) or day (X posts) and shared across drafts, at most one load per host every
HOST_GAP_S seconds. Any failure returns ok False and media_real falls back to its v2 chain. FD_MEDIA_SOURCES=0 turns
this whole path off.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from live import charts

NEW_STYLES = ('x_post', 'etf_flows', 'polymarket', 'article')
HOST_GAP_S = 8
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'}
X_STATUS = re.compile(r'https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d{6,25})')
ETF_TALK = re.compile(r'ETF', re.I)
FLOW_TALK = re.compile(r'流入|流出|净流|资金流|吸金|吸走|申购|赎回|inflow|outflow|net flow|flows?\b|vacuum|AUM|资产规模', re.I)
FARSIDE = {'BTC': 'btc', 'ETH': 'eth', 'SOL': 'sol', 'ZEC': 'zec'}
SOSO = {'BTC': 'us-btc-spot', 'ETH': 'us-eth-spot', 'SOL': 'us-sol-spot'}
ETF_ASSET = [('ZEC', r'ZEC|Zcash|大零币'), ('SOL', r'\bSOL\b|Solana|索拉纳'), ('ETH', r'\bETH\b|以太坊|以太|Ether(?:eum)?\b'),
             ('BTC', r'\bBTC\b|比特币|大饼|Bitcoin|IBIT')]
ODDS_TALK = re.compile(r'Polymarket|Kalshi|预测市场|prediction market|赔率|押注|下注|概率|胜率|\bodds\b|priced in|定价', re.I)
PM_TOPICS = [
    (re.compile(r'降息|加息|议息|利率决议|FOMC|rate cut|rate hike|cut rates|Fed (?:decision|meeting)|美联储.{0,6}(?:会议|决议|降息|加息)', re.I),
     'fed decision', re.compile(r'^Fed Decision in', re.I)),
    (re.compile(r'中期选举|midterm', re.I), 'midterms', re.compile(r'midterm|win the (?:House|Senate) in', re.I)),
    (re.compile(r'衰退|recession', re.I), 'recession', re.compile(r'recession', re.I)),
    (re.compile(r'政府停摆|关门|shutdown', re.I), 'government shutdown', re.compile(r'shutdown', re.I)),
]
ARTICLE_SITES = {   # allow-listed: robots allow the path, no anti-automation clause found in the site terms
    'theblockbeats.info': 'BlockBeats', 'panewslab.com': 'PANews', 'odaily.news': 'Odaily'}
# Text that means the capture is not the content: walls, errors, geo blocks, empty embeds
WALL = re.compile(r'Access denied|403 Forbidden|Page Not Found|404 Error|could not be found|doesn.t exist|'
                  r'this (?:page|post) is unavailable|Something went wrong|Market not found|Log in to continue|'
                  r'Sign in to continue|Just a moment|Verify you are human|请先登录|页面不存在|访问被拒绝', re.I)
CONSENT = ['#onetrust-banner-sdk', '#onetrust-consent-sdk', '.cc-window', '.cookie-banner', '[id*="cookie" i]',
           '[class*="cookie" i]', '[class*="consent" i]', '[id*="consent" i]', '.fc-consent-root', '#CybotCookiebotDialog']


def enabled():
    """FD_MEDIA_SOURCES=0 turns the source captures off (media v2 behaviour exactly)."""
    return os.environ.get('FD_MEDIA_SOURCES', '1') != '0'


# ------------------------------------------------------------------ which sources fit this draft

def x_source(row):
    """(handle, status id) of the X post the draft is built on, or None."""
    src = row.get('source') or {}
    for u in (src.get('url'), (row.get('archive') or {}).get('original_url')):
        m = X_STATUS.match(u or '')
        if m:
            return m.group(1), m.group(2)
    return None


def etf_asset(text):
    """BTC / ETH / SOL / ZEC when the draft talks about ETF flows of that asset, else None."""
    if not (ETF_TALK.search(text) and FLOW_TALK.search(text)):
        return None
    for sym, pat in ETF_ASSET:
        if re.search(pat, text, re.I):
            return sym
    return None


def pm_topic(text):
    """(search query, event title pattern, explicit) when the draft is about something Polymarket prices."""
    for pat, q, title in PM_TOPICS:
        if pat.search(text):
            return q, title, bool(ODDS_TALK.search(text))
    return None


def article_source(row):
    url = (row.get('source') or {}).get('url') or ''
    m = re.match(r'https?://(?:www\.|m\.)?([^/]+)/', url + '/')
    host = (m.group(1) if m else '').lower()
    for dom, name in ARTICLE_SITES.items():
        if host == dom or host.endswith('.' + dom):
            return {'url': url, 'site': name}
    return None


def candidates(row, account, text):
    """{style: detail} for the new source styles this draft supports (no network)."""
    if not enabled():
        return {}
    out = {}
    xs = x_source(row)
    if xs and row.get('post_mode') not in ('quote', 'reply'):
        out['x_post'] = {'handle': xs[0], 'status_id': xs[1]}
    if account.get('kind') == 'crypto':
        sym = etf_asset(text)
        if sym:
            out['etf_flows'] = {'asset': sym}
    topic = pm_topic(text)
    if topic:
        out['polymarket'] = {'query': topic[0], 'explicit': topic[2]}
    art = article_source(row)
    if art:
        out['article'] = art
    return out


# ------------------------------------------------------------------ manual-only sources (named, never loaded)

MANUAL_TOPICS = [
    (re.compile(r'清算|爆仓|liquidat', re.I), 'CoinGlass liquidation heatmap',
     'https://www.coinglass.com/pro/futures/LiquidationHeatMap', 'terms forbid scraping'),
    (re.compile(r'交易所余额|交易所储备|exchange (?:reserve|balance)|exchange (?:in|out)flow', re.I), 'CryptoQuant exchange reserve',
     'https://cryptoquant.com/asset/{sym}/chart/exchange-flows/exchange-reserve', 'terms forbid scraping'),
    (re.compile(r'SOPR|MVRV|已实现(?:市值|价格|利润|盈亏)|realized (?:cap|price|profit)|LTH|STH|长期持有者|短期持有者|supply in profit|盈利供应', re.I),
     'Glassnode Studio chart', 'https://studio.glassnode.com/charts/indicators.Sopr?a={sym}', 'terms forbid bots'),
    (re.compile(r'FedWatch|降息概率|加息概率|rate[- ]cut (?:odds|probabilit)', re.I), 'CME FedWatch',
     'https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html', 'blocks headless browsers'),
    (re.compile(r'\bTVL\b|锁仓|协议收入|protocol revenue|fees? (?:revenue|30d)|holders revenue', re.I), 'DefiLlama',
     'https://defillama.com/', 'terms forbid bots (its free API feeds our rendered panel)'),
]
MANUAL_SITES = {   # draft source article on a site whose terms forbid automated access
    'coindesk.com': ('CoinDesk article', 'terms forbid robots / scrapers'),
    'theblock.co': ('The Block article', 'terms forbid automated collection; manual social screenshots allowed (≤4 / month, credit The Block)'),
    'research.glassnode.com': ('Glassnode research figure', 'terms forbid bots; donors post these figures by hand'),
    'insights.glassnode.com': ('Glassnode research figure', 'terms forbid bots'),
    'wallstreetcn.com': ('华尔街见闻 article', 'terms not verified; not captured'),
    'spotgamma.com': ('SpotGamma article', 'terms not verified; not captured'),
    'unchainedcrypto.com': ('Unchained article', 'terms not verified; not captured'),
    'eetimes.com': ('EE Times article', 'terms not verified; not captured'),
}


def manual_sources(row, text, subj=None):
    """[{source, url, why}] the donors would screenshot here but we may not load automatically."""
    out = []
    url = (row.get('source') or {}).get('url') or ''
    m = re.match(r'https?://(?:www\.)?([^/]+)/', url + '/')
    host = (m.group(1) if m else '').lower()
    for dom, (name, why) in MANUAL_SITES.items():
        if host == dom or host.endswith('.' + dom):
            out.append({'source': name, 'url': url, 'why': why})
    sym = ((subj or {}).get('symbol') or 'btc').lower() if (subj or {}).get('asset') == 'crypto' else 'btc'
    for pat, name, page, why in MANUAL_TOPICS:
        if pat.search(text):
            out.append({'source': name, 'url': page.format(sym=sym), 'why': why})
    if subj and subj.get('asset') == 'stock':
        out.append({'source': 'StockCharts SharpChart', 'url': f"https://stockcharts.com/h-sc/ui?s={subj['display']}",
                    'why': 'terms forbid programmatic access; a manual reprint needs "Chart courtesy of StockCharts.com"'})
    return out


# ------------------------------------------------------------------ capture plumbing

def _cache_dir():
    d = charts.CACHE / '_captures'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _host_wait(url):
    """At most one page load per host every HOST_GAP_S seconds (across processes)."""
    host = re.sub(r'^https?://([^/]+).*', r'\1', url)
    lock = _cache_dir() / '_hosts.lock'
    with open(lock, 'a+') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            seen = json.loads(fh.read() or '{}')
        except ValueError:
            seen = {}
        gap = HOST_GAP_S - (time.time() - seen.get(host, 0))
        if gap > 0:
            time.sleep(gap)
        seen[host] = time.time()
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(seen))


def capture_page(job, out, cache_key, ttl_s, capture):
    """Cached page capture -> (ok, info). capture = media_real._capture. The page text is checked for walls."""
    key = hashlib.sha256(cache_key.encode()).hexdigest()[:24]
    png, meta = _cache_dir() / f'{key}.png', _cache_dir() / f'{key}.json'
    if png.exists() and meta.exists() and time.time() - png.stat().st_mtime < ttl_s:
        shutil.copyfile(png, out)
        return True, {**json.loads(meta.read_text()), 'cached': True}
    _host_wait(job['url'])
    res = capture({**job, 'out': str(png), 'text_probe': True,
                   'hide': list(job.get('hide') or []) + CONSENT})
    text = ((res.get('info') or {}).get('text') or '').strip()
    if not res.get('ok'):
        return False, {'error': res.get('error') or 'capture failed'}
    wall = WALL.search(text[:600])
    if wall or len(text) < 20:
        png.unlink(missing_ok=True)
        return False, {'error': f'wall / empty page: {wall.group(0) if wall else "no text"}'}
    info = {'url': job['url'], 'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'text_sha': hashlib.sha256(re.sub(r'\s+', ' ', text).encode()).hexdigest()}
    meta.write_text(json.dumps(info))
    shutil.copyfile(png, out)
    return True, info


# ------------------------------------------------------------------ the four capturers

def x_post(detail, theme, lang, out, capture):
    url = (f"https://platform.twitter.com/embed/Tweet.html?id={detail['status_id']}&theme={theme}"
           f"&lang={'zh-cn' if lang == 'zh' else 'en'}&dnt=true&hideThread=true&conversation=none")
    job = {'url': url, 'viewport': [550, 1600], 'dpr': 2, 'wait_for': 'article', 'wait_ms': 3500,
           'timeout_ms': 45000, 'color_scheme': theme,
           'clip_js': "(() => { const a = document.querySelector('article'); if (!a) return null; "
                      "const r = a.getBoundingClientRect(); return [r.x, r.y + window.scrollY, r.width, r.height]; })()"}
    ok, info = capture_page(job, out, f"x|{detail['status_id']}|{theme}|{lang}|{_day()}", 6 * 3600, capture)
    return ok, {**info, 'page': f"https://x.com/{detail['handle']}/status/{detail['status_id']}",
                'source_name': f"X post @{detail['handle']} (official embed)"}


def etf_flows(detail, theme, lang, out, capture):
    sym = detail['asset']
    if theme == 'dark' and sym in SOSO:
        url = f'https://sosovalue.com/assets/etf/{SOSO[sym]}'
        job = {'url': url, 'viewport': [1440, 1100], 'dpr': 2, 'wait_ms': 8000, 'timeout_ms': 60000,
               'color_scheme': 'dark',
               'clip_js': "(() => { const all = [...document.querySelectorAll('div,span,p')];"
                          " const t = all.find(e => /^(Daily Total Net Inflow|每日总净流入)$/.test(e.innerText.trim()));"
                          " const m = all.find(e => /^(Market Data|市场数据)$/.test(e.innerText.trim()));"
                          " if (!t || !m) return null; let tbl = m; for (let i = 0; i < 6 && tbl; i++) { tbl = tbl.parentElement;"
                          " if (tbl && tbl.querySelectorAll('tr, [role=row]').length > 5) break; }"
                          " const a = t.getBoundingClientRect(), b = (tbl || m).getBoundingClientRect();"
                          " const x = Math.max(0, Math.min(a.x, b.x) - 16), y = a.y + window.scrollY - 60;"
                          " return [x, y, Math.min(1440 - x, Math.max(a.right, b.right) - x + 16), b.bottom + window.scrollY - y + 12]; })()"}
        name = 'SoSoValue US spot ETF dashboard'
    elif sym in FARSIDE:
        url = f'https://farside.co.uk/{FARSIDE[sym]}/'
        job = {'url': url, 'viewport': [{'BTC': 1600, 'ETH': 1400}.get(sym, 1000), 1200], 'dpr': 2, 'wait_for': 'table.etf', 'wait_ms': 1500,
               'timeout_ms': 45000,
               'clip_js': "(() => { const h = document.querySelector('h1.entry-title'), t = document.querySelector('table.etf');"
                          " if (!h || !t) return null; const a = h.getBoundingClientRect(), b = t.getBoundingClientRect();"
                          " const x = Math.min(a.x, b.x) - 24, y = a.y + window.scrollY - 24;"
                          " return [Math.max(0, x), y, Math.max(a.right, b.right) - x + 24, b.bottom + window.scrollY - y + 20]; })()"}
        name = 'Farside Investors ETF flow table'
    else:
        return False, {'error': f'no ETF flow page for {sym}'}
    ok, info = capture_page(job, out, f'etf|{url}|{_hour()}', 3600, capture)
    return ok, {**info, 'page': url, 'source_name': name}


def polymarket_market(query, ttl=None):
    """(event, market) for the most traded active event matching the topic; market = the leading outcome."""
    title = next((t for _p, q, t in PM_TOPICS if q == query), None)

    def parse(r):
        evs = [e for e in r.json().get('events') or [] if e.get('active') and not e.get('closed')
               and (not title or title.search(e.get('title') or ''))]
        evs.sort(key=lambda e: -(float(e.get('volume') or 0)))
        for e in evs:
            ms = [m for m in e.get('markets') or [] if m.get('active') and not m.get('closed')]
            best = None
            for m in ms:
                try:
                    yes = float(json.loads(m.get('outcomePrices') or '[]')[0])
                except (ValueError, IndexError, TypeError):
                    continue
                if not best or yes > best[0]:
                    best = (yes, m)
            if best and best[0] >= 0.05:   # a near-zero long shot is not what the market is pricing
                return [{'event_slug': e['slug'], 'event_title': e.get('title'), 'market_slug': best[1]['slug'],
                         'question': best[1].get('question'), 'yes': best[0]}]
        return None
    key = datetime.now(timezone.utc).strftime('%Y%m%d%H')
    rows, meta = charts._get('https://gamma-api.polymarket.com/public-search', 'polymarket', query, key, parse,
                             ttl=ttl, params={'q': query, 'limit_per_type': 10, 'events_status': 'active'})
    return (rows or [None])[0], meta


def polymarket(detail, theme, lang, out, capture, ttl=None):
    mk, _meta = polymarket_market(detail['query'], ttl=ttl)
    if not mk:
        return False, {'error': f"no active Polymarket market for {detail['query']}"}
    url = (f"https://embed.polymarket.com/market.html?market={mk['market_slug']}&features=volume,chart"
           f"&theme={theme}")
    job = {'url': url, 'viewport': [480, 640], 'dpr': 2, 'wait_ms': 5000, 'timeout_ms': 45000, 'color_scheme': theme,
           'clip_js': "(() => { const b = document.body; const kids = [...b.querySelectorAll('body > *')]"
                      ".filter(e => e.getBoundingClientRect().height > 50); const e = kids[0] || b;"
                      " const r = e.getBoundingClientRect(); return r.height > 50 ? [r.x, r.y, r.width, r.height] : null; })()"}
    ok, info = capture_page(job, out, f"pm|{mk['market_slug']}|{theme}|{_hour()}", 3600, capture)
    return ok, {**info, 'page': f"https://polymarket.com/event/{mk['event_slug']}", 'market': mk,
                'source_name': 'Polymarket (official embed)'}


def article(detail, theme, lang, out, capture):
    url = detail['url']
    job = {'url': url, 'viewport': [390, 844], 'dpr': 3, 'wait_ms': 3500, 'timeout_ms': 45000,
           'color_scheme': theme, 'hide': ['header .download', '[class*="download" i]', '[class*="openApp" i]']}
    ok, info = capture_page(job, out, f'article|{url}|{theme}', 24 * 3600, capture)
    return ok, {**info, 'page': url, 'source_name': f"{detail['site']} article"}


CAPTURERS = {'x_post': x_post, 'etf_flows': etf_flows, 'polymarket': polymarket, 'article': article}


def _hour():
    return datetime.now(timezone.utc).strftime('%Y%m%d%H')


def _day():
    return datetime.now(timezone.utc).strftime('%Y%m%d')
