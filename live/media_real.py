"""Draft images that look like what each account's donors post (Oct 8, Fiona: our charts looked fake).

Evidence (docs/MEDIA_REAL.md): donors attach an image to 21-59% of their posts, and only about half of those are
charts. Among the charts the mix is TradingView screenshots (light about as often as dark, hand-drawn levels /
boxes), phone exchange or broker app screenshots (zh accounts), on-chain / research data panels and funding / OI
tables. Ours were one dark matplotlib template (MA20/MA50, 16:9, a "fetched ... UTC" footer) on every eligible
draft of every account.

Per account (live/media_profiles.json, built by scripts/build_media_profiles.py from the donors' image habits):
  p_image      = donor image rate x share of donor images that are charts - how often a draft gets one at all
  styles       = weights of tv_drawn / tv_widget / mobile / table / panel
  light_share, tall_share

decide(row, account) is deterministic per draft id (apply_media and the hourly refresh agree):
  - chart_caption drafts always get an image when there is a subject (their text was written for one);
    quote_comment drafts never (the quoted card is the visual); other drafts with probability p_image.
  - the subject must be what the draft is about: a ticker named and a price / market word, or a data series.
  - style drawn from the profile among the styles the subject supports; levels the draft names force a style that
    can draw them (tv_widget cannot).

Rendering, best first, never raising into the draft:
  tv_widget  -> screenshot of TradingView's public embed widget (s.tradingview.com/widgetembed) for the ticker
  fred panel -> screenshot of the public FRED graph page (fred.stlouisfed.org/graph/?id=...)
  tv_drawn / mobile / panel / table -> local HTML page with TradingView Lightweight Charts (Apache-2.0) and our
                 fetched numbers, screenshotted offline
  then the old matplotlib render (live/charts.py), then no image.
Captures run in a subprocess (scripts/chart_capture.py) with a fresh headless browser context: no cookies, no
login, no profile; one page load per image. FD_MEDIA_CAPTURE=0 disables public-page captures (renders only).

Numbers: candles / series / funding come from the fetchers in live/charts.py (Binance, Yahoo, FRED, DefiLlama)
and Hyperliquid's public info API. Drawn lines are only the levels the draft names (charts.draft_levels).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from live import charts, media_sources

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / 'live/media_profiles.json'
TEMPLATE_JS = ROOT / 'live/media_templates/chart_page.js'
CAPTURE_SCRIPT = ROOT / 'scripts/chart_capture.py'
LWC_VERSION = '4.2.0'
LWC_SHA256 = '46fc69534ec098f095bbcd1d9a26d693d39a8b9eeff7343536765b3dd28c2bdf'
LWC_URLS = (f'https://unpkg.com/lightweight-charts@{LWC_VERSION}/dist/lightweight-charts.standalone.production.js',
            f'https://cdn.jsdelivr.net/npm/lightweight-charts@{LWC_VERSION}/dist/lightweight-charts.standalone.production.js')
CAPTURE_TIMEOUT_S = 90
STYLES = ('tv_drawn', 'tv_widget', 'mobile', 'table', 'panel')
# media v3 (live/media_sources.py): when a draft's subject matches one of these sources, that source gets this share
# of the style draw and the v2 styles share the rest by profile weight: ETF flow talk -> the flow table 75%, odds
# talk naming a prediction market / odds -> Polymarket 75% (35% when only the topic matches), built on an X post ->
# that post 50%, an allow-listed article source -> the article 50%. (Donors post these rarely overall, but when the
# post is about exactly that, the source is what they screenshot.)
SOURCE_SHARE = {'x_post': 0.5, 'etf_flows': 0.75, 'polymarket': 0.75, 'polymarket_topic': 0.35, 'article': 0.5}


def style_weights(old, src, prof):
    """Draw weights for the v2 styles (profile) plus the matched source styles (SOURCE_SHARE of the draw)."""
    w_old = [max(prof['styles'].get(s, 0), 0.02) for s in old]
    shares = [SOURCE_SHARE['polymarket_topic' if s == 'polymarket' and not src[s].get('explicit') else s] for s in src]
    if not old:
        return w_old + shares
    tot = sum(shares)
    if tot >= 0.95:
        shares, tot = [x * 0.95 / tot for x in shares], 0.95
    k = sum(w_old) / (1 - tot)
    return w_old + [x * k for x in shares]
DEFAULT_PROFILE = {'p_image': 0.2, 'chart_share': 0.55, 'light_share': 0.55, 'tall_share': 0.1,
                   'styles': {'tv_drawn': 0.3, 'tv_widget': 0.1, 'mobile': 0.15, 'table': 0.05, 'panel': 0.4}}
PRICE_TALK = re.compile(
    r'价格|币价|股价|涨|跌|回调|反弹|突破|支撑|阻力|压力位|新高|新低|K线|走势|点位|横盘|震荡|拉升|砸盘|抄底|顶部|底部|仓位|'
    r'\bprice\b|rall(?:y|ied)|dump|pump|breakout|break(?:s|ing)? (?:above|below)|support|resistance|\bATH\b|bounce|'
    r'sell-?off|chart|range|trend|reclaim|\blevels?\b|downside|upside|[+-]\d+(?:\.\d+)?%|\d+(?:\.\d+)?%', re.I)
DERIV_TALK = re.compile(r'资金费率|费率|持仓量|未平仓|合约|永续|杠杆|爆仓|清算|多空|funding|open interest|\bOI\b|perps?\b|'
                        r'leverage|liquidat|long/short|basis', re.I)
TV_DRAW = ('#2962ff', '#f23645', '#089981', '#ff9800', '#9c27b0', '#00bcd4', '#e91e63')
COIN_NAME = {'ZEC': 'Zcash', 'ONDO': 'Ondo', 'TAO': 'Bittensor', 'WLD': 'Worldcoin', 'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana', 'BNB': 'BNB', 'XRP': 'XRP', 'DOGE': 'Dogecoin',
             'ADA': 'Cardano', 'AVAX': 'Avalanche', 'LINK': 'ChainLink', 'SUI': 'Sui', 'TON': 'Toncoin',
             'HYPE': 'Hyperliquid', 'ENA': 'Ethena', 'AAVE': 'Aave', 'UNI': 'Uniswap', 'LTC': 'Litecoin', 'TRX': 'TRON',
             'NEAR': 'NEAR Protocol', 'APT': 'Aptos', 'ARB': 'Arbitrum', 'PEPE': 'Pepe'}
COIN_DOT = {'BTC': '#f7931a', 'ETH': '#627eea', 'SOL': '#14f195', 'BNB': '#f3ba2f', 'XRP': '#23292f', 'DOGE': '#c2a633',
            'TRX': '#ff060a', 'HYPE': '#97fce4', 'LINK': '#2a5ada', 'ADA': '#0033ad'}
# display -> (TradingView symbol, legend name, venue)
STOCK_TV = {'SPX': ('SP:SPX', 'S&P 500 Index', 'SP'), 'NDX': ('NASDAQ:NDX', 'Nasdaq 100 Index', 'NASDAQ'),
            'IXIC': ('NASDAQ:IXIC', 'Nasdaq Composite Index', 'NASDAQ'), 'DJI': ('DJ:DJI', 'Dow Jones Industrial Average', 'DJ'),
            'SPY': ('AMEX:SPY', 'SPDR S&P 500 ETF', 'NYSE Arca'), 'QQQ': ('NASDAQ:QQQ', 'Invesco QQQ Trust', 'NASDAQ'),
            'NVDA': ('NASDAQ:NVDA', 'NVIDIA Corporation', 'NASDAQ'), 'TSLA': ('NASDAQ:TSLA', 'Tesla, Inc.', 'NASDAQ'),
            'AAPL': ('NASDAQ:AAPL', 'Apple Inc.', 'NASDAQ'), 'MSFT': ('NASDAQ:MSFT', 'Microsoft Corporation', 'NASDAQ'),
            'AMZN': ('NASDAQ:AMZN', 'Amazon.com, Inc.', 'NASDAQ'), 'GOOGL': ('NASDAQ:GOOGL', 'Alphabet Inc.', 'NASDAQ'),
            'META': ('NASDAQ:META', 'Meta Platforms, Inc.', 'NASDAQ'), 'AMD': ('NASDAQ:AMD', 'Advanced Micro Devices', 'NASDAQ'),
            'AVGO': ('NASDAQ:AVGO', 'Broadcom Inc.', 'NASDAQ'), 'TSM': ('NYSE:TSM', 'Taiwan Semiconductor', 'NYSE'),
            'MU': ('NASDAQ:MU', 'Micron Technology', 'NASDAQ'), 'ORCL': ('NYSE:ORCL', 'Oracle Corporation', 'NYSE'),
            'PLTR': ('NASDAQ:PLTR', 'Palantir Technologies', 'NASDAQ'), 'COIN': ('NASDAQ:COIN', 'Coinbase Global', 'NASDAQ'),
            'MSTR': ('NASDAQ:MSTR', 'Strategy', 'NASDAQ'), 'NFLX': ('NASDAQ:NFLX', 'Netflix, Inc.', 'NASDAQ'),
            'INTC': ('NASDAQ:INTC', 'Intel Corporation', 'NASDAQ'), 'ASML': ('NASDAQ:ASML', 'ASML Holding', 'NASDAQ'),
            'ARM': ('NASDAQ:ARM', 'Arm Holdings', 'NASDAQ'), 'SMCI': ('NASDAQ:SMCI', 'Super Micro Computer', 'NASDAQ'),
            'CRWV': ('NASDAQ:CRWV', 'CoreWeave', 'NASDAQ')}
STOCK_ZH = {'NVDA': '英伟达', 'TSLA': '特斯拉', 'AAPL': '苹果', 'MSFT': '微软', 'AMZN': '亚马逊', 'GOOGL': '谷歌-A',
            'META': 'Meta', 'AMD': '超威半导体', 'AVGO': '博通', 'TSM': '台积电', 'MU': '美光科技', 'ORCL': '甲骨文',
            'PLTR': 'Palantir', 'COIN': 'Coinbase', 'MSTR': 'Strategy', 'NFLX': '奈飞', 'INTC': '英特尔', 'ASML': '阿斯麦',
            'SPX': '标普500', 'NDX': '纳斯达克100', 'IXIC': '纳斯达克综合指数', 'DJI': '道琼斯指数'}
INTERVAL_LABEL = {'1h': '1h', '4h': '4h', '1d': '1D', '1w': '1W'}
TV_WIDGET_INTERVAL = {'1h': '60', '4h': '240', '1d': 'D', '1w': 'W'}


def enabled():
    """FD_MEDIA_V2=0 restores the Oct 7 chart path (live/charts.attach) exactly."""
    return os.environ.get('FD_MEDIA_V2', '1') != '0'


def captures_enabled():
    return os.environ.get('FD_MEDIA_CAPTURE', '1') != '0'


# ------------------------------------------------------------------ profile + decision

def load_profiles(path=None):
    try:
        return json.loads(Path(path or PROFILES).read_text())
    except (OSError, ValueError):
        return {'accounts': {}}


def profile_for(account_id, profiles=None):
    prof = (profiles or load_profiles()).get('accounts', {}).get(account_id)
    if not prof:
        return dict(DEFAULT_PROFILE, source='default')
    if not media_sources.enabled() and prof.get('v2'):   # FD_MEDIA_SOURCES=0: the Oct 8 (v2) numbers exactly
        prof = {**prof, **prof['v2']}
    return {**DEFAULT_PROFILE, **prof, 'styles': {**DEFAULT_PROFILE['styles'], **(prof.get('styles') or {})},
            'source': 'profile'}


def _rng(draft_id, salt=''):
    return random.Random(int(hashlib.sha256(f'media-v2|{draft_id}|{salt}'.encode()).hexdigest()[:16], 16))


def _post_type(row):
    pf = row.get('post_format') or {}
    return (pf.get('type') if isinstance(pf, dict) else None) or row.get('post_type')


def subject_mentions(text, subj):
    if subj['asset'] == 'crypto':
        en, zh, _cg = charts.CRYPTO.get(subj['symbol'], ([], [], None))
    else:
        _d, en, zh = charts.STOCKS.get(subj['symbol'], (subj['display'], [], []))
    return charts._hits(text, subj['display'], en, zh)[0]


def feasible_styles(subj, series, levels, account, derivs=False):
    """Styles this draft's subject can be drawn in."""
    out = []
    if subj:
        out += ['tv_drawn', 'mobile', 'panel']
        if not levels:
            out.append('tv_widget')
        if subj['asset'] == 'crypto' and account.get('kind') == 'crypto' and derivs:
            out.append('table')
    elif series:
        out.append('panel')
    return out


def decide(row, account, profiles=None, force=False):
    """{'want': bool, 'why': str, ...plan} for one draft; no network. force skips the donor-rate roll only
    (sample sheets); every other rule still applies."""
    text = (row.get('text') or row.get('body') or '').strip()
    prof = profile_for(account['id'], profiles)
    from live import cold_start   # Oct 8 evening: image-heavy donors -> p_image raised toward their image rate
    prof = {**prof, 'p_image': cold_start.boosted_p_image(account['id'], prof['p_image'])}
    ptype = _post_type(row)
    base = {'want': False, 'post_type': ptype, 'p_image': prof['p_image'], 'profile_source': prof['source']}
    if not text:
        return {**base, 'why': 'empty text'}
    if ptype == 'quote_comment' or row.get('post_mode') in ('quote', 'reply'):
        return {**base, 'why': 'quote / reply post: the quoted card or thread is the visual'}
    rng = _rng(row['id'])
    roll = rng.random()
    forced = ptype == 'chart_caption'
    if not (forced or force) and roll >= prof['p_image']:
        return {**base, 'why': f'no image by donor rate (roll {roll:.2f} >= p {prof["p_image"]:.2f})', 'roll': round(roll, 3)}
    src = media_sources.candidates(row, account, text)
    subj = charts.pick_subject(text)
    if subj and subj['asset'] == 'crypto' and account.get('kind') != 'crypto':
        subj = None   # beat gate: no crypto price charts on stock / investing accounts
    series = charts.pick_series(text)
    if subj and not (forced or PRICE_TALK.search(text) or subject_mentions(text, subj) >= 2):
        subj = None   # the ticker is named in passing; a price chart of it would be off-topic
    manual = media_sources.manual_sources(row, text, subj) if media_sources.enabled() else []
    if not subj and not series and not src:
        return {**base, 'why': 'no chartable subject in the text', 'roll': round(roll, 3),
                **({'manual_sources': manual} if manual else {})}
    if subj and series and not PRICE_TALK.search(text):
        subj = None   # the draft is about the data series, not the price
    interval = charts.pick_interval(text)
    levels_named = bool(subj) and bool(charts._price_numbers(text))
    old = feasible_styles(subj, series, levels_named, account, derivs=bool(DERIV_TALK.search(text)))
    styles = old + list(src)
    weights = style_weights(old, src, prof)
    style = rng.choices(styles, weights)[0]
    theme = 'light' if rng.random() < prof['light_share'] else 'dark'
    # the v2 style this draft falls back to when the source capture fails (same draw among the v2 styles only)
    # (drawn only when a source matched, so drafts without one keep their v2 seed and image exactly)
    fallback = (rng.choices(old, [max(prof['styles'].get(s, 0), 0.02) for s in old])[0] if src and old else None)
    return {**base, 'want': True, 'why': ('chart_caption' if forced else 'forced (sample)' if roll >= prof['p_image']
                                          else f'donor rate (roll {roll:.2f} < p {prof["p_image"]:.2f})'),
            'style': style, 'theme': theme, 'subject': subj, 'series': series if not subj or style == 'panel' else None,
            'interval': interval, 'candidates': styles, 'seed': rng.randrange(1 << 30),
            **({'sources': src, 'fallback_style': fallback} if src else {}),
            **({'manual_sources': manual} if manual else {})}


# ------------------------------------------------------------------ capture plumbing

def _capture_python():
    env = os.environ.get('FD_CAPTURE_PYTHON')
    if env:
        return env
    if importlib.util.find_spec('playwright'):
        return sys.executable
    return shutil.which('python3') or '/usr/bin/python3'


def _capture(job, timeout=CAPTURE_TIMEOUT_S):
    """Run scripts/chart_capture.py on one job; returns its result dict (ok False on any failure)."""
    try:
        r = subprocess.run([_capture_python(), str(CAPTURE_SCRIPT)], input=json.dumps(job), capture_output=True,
                           text=True, timeout=timeout)
        line = (r.stdout.strip().splitlines() or ['{}'])[-1]
        res = json.loads(line)
        if not res.get('ok'):
            res.setdefault('error', (r.stderr or 'capture failed')[-300:])
        return res
    except Exception as exc:   # noqa: BLE001 - timeout, missing python, bad output: fall back
        return {'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'}


def _png_ok(path, min_std=6.0):
    """A real picture, not a blank / error page."""
    try:
        from PIL import Image, ImageStat
        im = Image.open(path).convert('L')
        return im.width >= 300 and im.height >= 200 and ImageStat.Stat(im).stddev[0] >= min_std
    except Exception:   # noqa: BLE001
        return False


def lwc_js():
    """TradingView Lightweight Charts standalone build, cached under the chart cache, sha256-pinned."""
    path = charts.CACHE / '_vendor' / f'lightweight-charts-{LWC_VERSION}.js'
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == LWC_SHA256:
        return path.read_text()
    for url in LWC_URLS:
        try:
            r = requests.get(url, headers=charts.UA, timeout=charts.TIMEOUT)
            r.raise_for_status()
        except Exception:   # noqa: BLE001
            continue
        if hashlib.sha256(r.content).hexdigest() == LWC_SHA256:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.text
    raise RuntimeError('lightweight-charts unavailable')


def render_html(cfg, out, dpr=2, timeout=CAPTURE_TIMEOUT_S):
    """Write cfg into the chart page, screenshot #root offline. Returns the capture result."""
    lib = lwc_js()
    page = ('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0}'
            '#root{overflow:hidden}</style></head><body><div id="root"></div>'
            f'<script>{lib}</script><script>window.C={json.dumps(cfg, ensure_ascii=False)};</script>'
            f'<script>{TEMPLATE_JS.read_text()}</script></body></html>')
    with tempfile.TemporaryDirectory(prefix='fd_media_') as tmp:
        html = Path(tmp) / 'chart.html'
        html.write_text(page)
        return _capture({'html': str(html), 'out': str(out), 'viewport': [cfg['w'], cfg.get('h') or 1400],
                         'dpr': dpr, 'selector': '#root', 'ready_flag': 'window.__ready === true', 'wait_ms': 150,
                         'locale': 'zh-CN' if cfg.get('lang') == 'zh' else 'en-US'}, timeout=timeout)


# ------------------------------------------------------------------ data helpers

def _precision(v):
    return 2 if v >= 10 else 3 if v >= 1 else 4 if v >= 0.1 else 6


def _bars(rows):
    return [{'time': int(t), 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v} for t, o, h, l, c, v in rows]


def _ma_series(rows, n, color, name):
    closes = [r[4] for r in rows]
    vals = charts._ma(closes, n)
    return {'name': name, 'color': color, 'data': [{'time': int(rows[i][0]), 'value': v} for i, v in enumerate(vals) if v is not None]}


def _fetch_candles(subj, interval, bars=200, ttl=None):
    """Crypto always asks Binance for 1000 bars (one cache entry per interval and hour), then keeps `bars`."""
    if subj['asset'] == 'crypto':
        data = charts.fetch_crypto(subj['symbol'], interval, bars=1000, ttl=ttl)
        return {**data, 'rows': data['rows'][-bars:]} if data.get('rows') else data
    return charts.fetch_stock(subj['symbol'], interval, bars=bars, ttl=ttl)


def _levels(text, rows, rng, lang):
    """Drawn levels: only the prices the draft names, each anchored at the bar where price last touched it."""
    lo, hi = min(r[3] for r in rows), max(r[2] for r in rows)
    named = charts.draft_levels(text, lo, hi, last=rows[-1][4])
    colors = rng.sample(TV_DRAW, k=len(TV_DRAW))
    out = []
    for i, v in enumerate(named):
        back = rows[:-max(12, len(rows) // 6)] or rows   # rays start some way back, as people draw them
        touch = next((r[0] for r in reversed(back) if r[3] <= v <= r[2]), None)
        if touch is None:
            touch = min(back, key=lambda r: min(abs(r[2] - v), abs(r[3] - v)))[0]
        out.append({'price': v, 'color': colors[i % len(colors)], 'width': rng.choice((1, 1, 2)), 'dash': rng.random() < 0.3,
                    'from_time': int(touch), 'label': charts._fmt_price(v), 'anchor_dot': rng.random() < 0.4})
    zone = None
    if len(out) >= 2:
        last = rows[-1][4]
        a, b = sorted(sorted(out, key=lambda l: abs(l['price'] - last))[:2], key=lambda l: l['price'])
        if (b['price'] - a['price']) / last < 0.08 and rng.random() < 0.6:
            zone = {'top': b['price'], 'bottom': a['price'], 'color': rng.choice(('#2962ff', '#ff9800', '#089981')),
                    'from_time': int(rows[max(0, len(rows) - rng.randint(18, 40))][0])}
            out = [l for l in out if l not in (a, b)]
    return out, zone, named


def hyperliquid_ctx(ttl=None):
    """[(coin, mark, prev_day_px, funding_1h, oi_usd, day_ntl_vlm)] from Hyperliquid's public info API."""
    def parse(r):
        meta, ctxs = r.json()
        rows = []
        for u, c in zip(meta['universe'], ctxs):
            if u.get('isDelisted'):
                continue
            try:
                mark = float(c['markPx'])
                rows.append([u['name'], mark, float(c.get('prevDayPx') or mark), float(c.get('funding') or 0),
                             float(c.get('openInterest') or 0) * mark, float(c.get('dayNtlVlm') or 0)])
            except (TypeError, ValueError, KeyError):
                continue
        return rows
    key = datetime.now(timezone.utc).strftime('%Y%m%d%H')
    return charts._get('https://api.hyperliquid.xyz/info', 'hyperliquid', 'metaAndAssetCtxs', key, parse, method='POST',
                       ttl=ttl, json={'type': 'metaAndAssetCtxs'})


def okx_ctx(ttl=None):
    """Same row shape from OKX public USDT swaps (funding = current 8h-period rate). Three public GETs."""
    key = datetime.now(timezone.utc).strftime('%Y%m%d%H')
    base = 'https://www.okx.com/api/v5'
    tick, meta = charts._get(f'{base}/market/tickers?instType=SWAP', 'okx', 'tickers', key,
                             lambda r: [[x['instId'], float(x['last']), float(x['sodUtc0'] or x['open24h']),
                                         float(x.get('volCcy24h') or 0)] for x in r.json()['data']
                                        if x['instId'].endswith('-USDT-SWAP')], ttl=ttl)
    if not tick:
        return None, meta
    oi, _m = charts._get(f'{base}/public/open-interest?instType=SWAP', 'okx', 'open-interest', key,
                         lambda r: [[x['instId'], float(x.get('oiUsd') or 0)] for x in r.json()['data']], ttl=ttl)
    fund, _m = charts._get(f'{base}/public/funding-rate?instId=ANY', 'okx', 'funding', key,
                           lambda r: [[x['instId'], float(x.get('fundingRate') or 0)] for x in r.json()['data']], ttl=ttl)
    oi, fund = dict(oi or []), dict(fund or [])
    rows = [[i.split('-')[0], last, open_, fund.get(i, 0.0), oi.get(i, 0.0), vol * last]
            for i, last, open_, vol in tick if i in oi]
    return rows or None, meta


# ------------------------------------------------------------------ style builders (each returns cfg, data, meta)

def _now_local(lang):
    return datetime.now(ZoneInfo('Asia/Shanghai' if lang == 'zh' else 'Europe/London'))


def build_tv(plan, text, lang, ttl=None):
    rng = random.Random(plan['seed'])
    subj, interval = plan['subject'], plan['interval']
    data = _fetch_candles(subj, interval, bars=300, ttl=ttl)
    rows = data.get('rows')
    if not rows or len(rows) < 30:
        return None, data
    show = rng.randint(70, 170)
    full = rows
    rows = rows[-show:]
    levels, zone, named = _levels(text, rows, rng, lang)
    crypto = subj['asset'] == 'crypto'
    tvsym, name, venue = STOCK_TV.get(subj['display'], (subj['display'], subj['display'], 'NASDAQ'))
    w = rng.choice((1200, 1280, 1366, 1440, 1100))
    h = int(w / rng.choice((16 / 9, 1.6, 1.5, 1.85, 1.7)))
    ma = []
    if rng.random() < 0.35:   # most donor TradingView shots carry no moving averages; some an EMA or two
        n = rng.choice((20, 50, 200))
        ma.append(_ma_series(full, n, rng.choice(('#2962ff', '#ff9800', '#f23645')), f'EMA {n}' if rng.random() < .5 else f'MA {n}'))
        ma[0]['data'] = [p for p in ma[0]['data'] if p['time'] >= rows[0][0]]
    cfg = {'style': 'tv', 'theme': plan['theme'], 'lang': lang, 'w': w, 'h': h, 'candles': _bars(rows),
           'precision': _precision(rows[-1][4]), 'levels': levels, 'zone': zone, 'ma': ma,
           'volume': rng.random() < 0.7, 'intraday': interval in ('1h', '4h'),
           'title': f"{COIN_NAME.get(subj['symbol'], subj['symbol'])} / TetherUS" if crypto else name,
           'ticker': f"{subj['symbol']}USDT" if crypto else subj['display'], 'base': subj['symbol'] if crypto else '',
           'venue': 'Binance' if crypto else venue, 'coin_dot': COIN_DOT.get(subj['symbol']) if crypto else None,
           'interval_label': INTERVAL_LABEL[interval], 'intervals': ['1h', '4h', '1D', '1W'],
           'bar_spacing': max(3.0, min(12.0, (w - 120) / (show + 8))), 'right_offset': rng.randint(3, 12),
           'legend_size': 14, 'chrome': {'top': rng.random() < 0.55, 'left': rng.random() < 0.35, 'symbol_box': rng.random() < 0.5},
           'dark_bg': rng.choice(('#131722', '#0f0f0f', '#161a25')), 'dark_grid': rng.choice(('#1e222d', '#1a1a1a', '#232632'))}
    return cfg, {**data, 'rows': rows}, {'levels': [l['price'] for l in levels] + ([zone['bottom'], zone['top']] if zone else []),
                                          'named_levels': named}


def build_mobile(plan, text, lang, ttl=None):
    rng = random.Random(plan['seed'])
    subj = plan['subject']
    crypto = subj['asset'] == 'crypto'
    interval = plan['interval'] if plan['interval'] != '1d' or rng.random() < 0.5 else rng.choice(('1h', '4h'))
    if not crypto:
        interval = '1d'
    data = _fetch_candles(subj, interval, bars=220, ttl=ttl)
    rows = data.get('rows')
    if not rows or len(rows) < 30:
        return None, data
    full = rows
    show = rng.randint(45, 80)
    rows = rows[-show:]
    levels, zone, named = _levels(text, rows, rng, lang)
    zh = lang == 'zh'
    last = rows[-1]
    if crypto:
        day = charts.fetch_crypto(subj['symbol'], '1h', bars=24, ttl=ttl).get('rows') or rows[-1:]
        hi24, lo24 = max(r[2] for r in day), min(r[3] for r in day)
        vol24 = sum(r[5] for r in day)
        quote = sum(r[5] * r[4] for r in day)
        ref = day[0][1]
        okx = rng.random() < 0.35
        mob = {'font': '"IBM Plex Sans", "Noto Sans CJK SC", Roboto, sans-serif', 'accent': '#ffffff' if okx and plan['theme'] == 'dark' else ('#000000' if okx else '#f0b90b'),
               'pair': f"{subj['symbol']}/USDT", 'pair_sub': '现货' if zh else 'Spot', 'tag': None,
               'tabs': ['价格', '信息', '交易数据', '广场'] if zh else ['Price', 'Info', 'Trading Data', 'Square'],
               'fiat_prefix': '≈$', 'ref_close': ref,
               'stats': [('24h最高价' if zh else '24h High', charts._fmt_price(hi24)), ('24h最低价' if zh else '24h Low', charts._fmt_price(lo24)),
                         (f"24h成交量({subj['symbol']})" if zh else f"24h Vol({subj['symbol']})", _big(vol24)),
                         ('24h成交额(USDT)' if zh else '24h Vol(USDT)', _big(quote))],
               'intervals': ['15m', '1h', '4h', '1D', '更多 ▾' if zh else 'More ▾'], 'active': INTERVAL_LABEL[interval],
               'buttons': ['买入', '卖出'] if zh else ['Buy', 'Sell'], 'active_bg': okx}
        ma = [_ma_series(full, 7, '#f0b90b', 'MA(7)'), _ma_series(full, 25, '#e94da3', 'MA(25)'), _ma_series(full, 99, '#8c5ad8', 'MA(99)')]
        palette = {'up': '#2ebd85', 'down': '#f6465d'} if not okx else {}
    else:
        prev = rows[-2]
        cn = STOCK_ZH.get(subj['display'], '')
        mob = {'font': 'Roboto, "Noto Sans CJK SC", sans-serif', 'accent': '#ff7d00', 'pair': subj['display'],
               'pair_sub': cn if zh else STOCK_TV.get(subj['display'], (0, subj['display']))[1], 'tag': None,
               'tabs': ['报价', '资讯', '评论', '财务'] if zh else ['Quote', 'News', 'Comments', 'Financials'],
               'fiat_prefix': 'USD ' if not zh else '收盘价 ', 'ref_close': prev[4],
               'stats': [('最高' if zh else 'High', charts._fmt_price(last[2])), ('最低' if zh else 'Low', charts._fmt_price(last[3])),
                         ('今开' if zh else 'Open', charts._fmt_price(last[1])), ('昨收' if zh else 'Prev Close', charts._fmt_price(prev[4])),
                         ('成交量' if zh else 'Volume', _big(last[5]))],
               'intervals': ['分时', '五日', '日K', '周K', '月K'] if zh else ['1D', '5D', 'Daily', 'Weekly', 'Monthly'],
               'active': '日K' if zh else 'Daily', 'buttons': None, 'active_bg': True}
        ma = [_ma_series(full, 5, '#f5a623', 'MA5'), _ma_series(full, 10, '#e94da3', 'MA10'), _ma_series(full, 20, '#2f80ed', 'MA20')]
        # Futu / moomoo style colour: zh readers expect red up / green down
        palette = {'up': '#f23645', 'down': '#089981'} if zh else {}
    for m in ma:
        m['data'] = [p for p in m['data'] if p['time'] >= rows[0][0]]
    mob['clock'] = _now_local(lang).strftime('%H:%M')
    mob['battery'] = round(rng.uniform(0.25, 0.95), 2)
    cfg = {'style': 'mobile', 'theme': plan['theme'], 'lang': lang, 'w': 390, 'h': rng.choice((780, 820, 844)),
           'candles': _bars(rows), 'precision': _precision(last[4]), 'levels': levels, 'zone': zone, 'ma': ma,
           'intraday': interval in ('1h', '4h'), 'bar_spacing': max(3.0, (390 - 70) / (show + 3)), 'mobile': mob,
           'palette': palette, 'dark_bg': '#0b0e11' if not crypto or mob['accent'] == '#f0b90b' else '#000000',
           'dark_grid': '#1c2127'}
    return cfg, {**data, 'rows': rows, 'interval': interval}, {'levels': [l['price'] for l in levels] + ([zone['bottom'], zone['top']] if zone else []),
                                                               'named_levels': named}


def _big(v):
    for d, s in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if abs(v) >= d:
            return f'{v / d:,.2f}{s}'
    return f'{v:,.2f}'


def build_panel(plan, text, lang, ttl=None):
    rng = random.Random(plan['seed'])
    zh = lang == 'zh'
    light = plan['theme'] == 'light'
    if plan.get('series'):
        spec = plan['series']
        data = charts.fetch_series(spec, ttl=ttl)
        rows = data.get('rows')
        if not rows:
            return None, data
        pct = spec['unit'] == '%'
        series = [{'name': spec['title'], 'color': rng.choice(('#2962ff', '#1f77b4', '#f7931a' if not pct else '#e4572e')),
                   'type': rng.choice(('line', 'area')), 'width': 2, 'format': 'percent' if pct else 'big' if spec['unit'] == 'USD' else None,
                   'precision': 2, 'data': [{'time': int(t), 'value': v} for t, v in rows]}]
        title = spec['title']
        sub = f"{datetime.fromtimestamp(rows[0][0], timezone.utc):%b %Y} – {datetime.fromtimestamp(rows[-1][0], timezone.utc):%b %Y}"
        src = data['source']
    else:
        subj = plan['subject']
        crypto = subj['asset'] == 'crypto'
        data = _fetch_candles(subj, '1d', bars=1000, ttl=ttl)
        rows = data.get('rows')
        n = rng.choice((200, 111, 50)) if crypto else 50   # Yahoo daily reaches back one year
        if not rows or len(rows) < n + 100:
            return None, data
        ma = _ma_series(rows, n, '#f7931a', '')
        keep = rows[-rng.randint(min(365, len(rows) - n), len(rows) - n + 1):]
        price_name = (COIN_NAME.get(subj['symbol'], subj['symbol']) if subj['asset'] == 'crypto' else subj['display'])
        pp = 0 if keep[-1][4] >= 1000 else 2
        series = [{'name': ('价格' if zh else 'Price') + (' (USD)' if not zh else ''), 'color': '#1d1d1d' if light else '#e0e0e0', 'type': 'line', 'width': 1.6,
                   'precision': pp, 'data': [{'time': int(r[0]), 'value': r[4]} for r in keep]},
                  {'name': f'{n}{"日均线" if zh else "D SMA"}', 'color': rng.choice(('#f7931a', '#e4572e', '#2962ff')), 'type': 'line', 'width': 2,
                   'precision': pp, 'last': False, 'data': [p for p in ma['data'] if p['time'] >= keep[0][0]]}]
        title = (f'{price_name}：价格与{n}日均线' if zh else f'{price_name}: Price vs {n}-day SMA')
        sub = ('日线收盘' if zh else 'Daily close') + f" · {datetime.fromtimestamp(keep[0][0], timezone.utc):%Y-%m} – {datetime.fromtimestamp(keep[-1][0], timezone.utc):%Y-%m}"
        src = data['source']
        rows = keep
    w = rng.choice((1200, 1280, 1100, 1400))
    cfg = {'style': 'panel', 'theme': plan['theme'], 'lang': lang, 'w': w, 'h': int(w / rng.choice((1.75, 1.6, 2.0, 1.5))),
           'series': series,
           'panel': {'font': rng.choice(('Inter, "Noto Sans CJK SC", sans-serif', '"IBM Plex Sans", "Noto Sans CJK SC", sans-serif', 'Roboto, "Noto Sans CJK SC", sans-serif')),
                     'title': title, 'subtitle': sub, 'title_size': rng.choice((20, 22, 24)), 'pad': rng.choice((18, 24, 28)),
                     'vgrid': rng.random() < 0.4, 'footer': f'<span>{"数据来源" if zh else "Source"}: {src.split(" (")[0]}</span><span></span>'},
           'dark_bg': rng.choice(('#111217', '#0e1117', '#181a20')), 'dark_grid': '#24262d'}
    return cfg, {**data, 'rows': rows}, {'levels': []}


def build_table(plan, text, lang, ttl=None):
    rng = random.Random(plan['seed'])
    zh = lang == 'zh'
    venue = 'Hyperliquid'
    rows, meta = hyperliquid_ctx(ttl=ttl)
    if not rows or not any(r[0] == plan['subject']['symbol'] for r in rows):
        venue, first = 'OKX', meta
        rows, meta = okx_ctx(ttl=ttl)
        if not rows:
            return None, {'rows': None, 'attempts': [first, meta]}
    sym = plan['subject']['symbol']
    rows = sorted(rows, key=lambda r: -r[4])
    top = [r for r in rows if r[0] != sym][:rng.choice((7, 8, 9))]
    mine = [r for r in rows if r[0] == sym]
    if not mine:
        return None, {'rows': None, 'attempts': [{'error': f'{sym} not listed on {venue}'}]}
    pick = sorted(mine + top, key=lambda r: -r[4])
    trs = []
    for coin, mark, prev, fund, oi, vlm in pick:
        chg = (mark / prev - 1) * 100 if prev else 0
        trs.append({'hl': coin == sym, 'cells': [{'v': coin}, {'v': charts._fmt_price(mark)},
                                                 {'v': f'{chg:+.2f}%', 'sign': chg},
                                                 {'v': f'{fund * 100:+.4f}%', 'sign': fund},
                                                 {'v': '$' + _big(oi)}, {'v': '$' + _big(vlm)}]})
    stamp = _now_local(lang).strftime('%Y-%m-%d %H:%M')
    per = '1h' if venue == 'Hyperliquid' else '8h'
    cfg = {'style': 'table', 'theme': plan['theme'], 'lang': lang, 'w': rng.choice((760, 820, 900)), 'h': 0,
           'table': {'font': '"IBM Plex Sans", "Noto Sans CJK SC", Roboto, sans-serif',
                     'title': (f'{venue} 永续合约 · 资金费率 / 持仓量' if zh else f'{venue} perps · funding / open interest'),
                     'subtitle': (f'按持仓量排序 · 资金费率为当前{per}费率 · {stamp} {"北京时间"}' if zh else
                                  f'Sorted by OI · funding = current {per} rate · {stamp} London'),
                     'columns': ['币种', '价格', '24h涨跌', f'资金费率({per})', '持仓量', '24h成交额'] if zh else
                                ['Coin', 'Mark', '24h', f'Funding ({per})', 'Open interest', '24h volume'],
                     'rows': trs, 'footer': None}}
    return cfg, {'rows': pick, 'source': f'{venue} public API', **meta}, {'levels': []}


BUILDERS = {'tv_drawn': build_tv, 'mobile': build_mobile, 'panel': build_panel, 'table': build_table}


def capture_widget(plan, out, lang):
    subj = plan['subject']
    sym = f"BINANCE:{subj['symbol']}USDT" if subj['asset'] == 'crypto' else STOCK_TV.get(subj['display'], (subj['display'],))[0]
    rng = random.Random(plan['seed'])
    url = ('https://s.tradingview.com/widgetembed/?symbol=' + requests.utils.quote(sym) +
           f"&interval={TV_WIDGET_INTERVAL[plan['interval']]}&theme={plan['theme']}&style=1"
           f"&locale={'zh_CN' if lang == 'zh' else 'en'}&hidesidetoolbar={0 if rng.random() < 0.5 else 1}"
           '&withdateranges=0&hide_volume=0&timezone=Etc%2FUTC')
    w = rng.choice((1200, 1280, 1366))
    res = _capture({'url': url, 'out': str(out), 'viewport': [w, int(w / rng.choice((16 / 9, 1.6, 1.7)))], 'dpr': 2,
                    'wait_for': 'canvas', 'wait_ms': 3500, 'timeout_ms': 45000})
    return res, url


FRED_SELECTOR = '#zoom-and-share'


def capture_fred(spec, out):
    url = f"https://fred.stlouisfed.org/graph/?id={spec['series']}"
    res = _capture({'url': url, 'out': str(out), 'viewport': [1200, 900], 'dpr': 2, 'selector': FRED_SELECTOR,
                    'wait_for': '.highcharts-root', 'wait_ms': 2500, 'timeout_ms': 45000})
    return res, url


# ------------------------------------------------------------------ per draft

def _old_attach(row, account, out_dir, rel_prefix, ttl, why):
    """Last resort: the Oct 7 matplotlib render (only when the account was chart-eligible there)."""
    media, plan = charts.attach_v1(row, account, out_dir, rel_prefix=rel_prefix, ttl=ttl)
    if media:
        media.update(style='matplotlib', capture=False, fallback_from=why)
    return media, plan


def attach(row, account, out_dir, rel_prefix='media', ttl=None, profiles=None, force=False, style=None):
    """Same contract as charts.attach: (media dict | None, plan). Never raises for data / browser failures."""
    plan = decide(row, account, profiles, force=force)
    if not plan['want']:
        return None, {**plan, 'kind': None}
    if style and style in plan['candidates']:   # sample sheets: another style the draft supports
        plan = {**plan, 'style': style, 'why': plan['why'] + f' / style override {style}'}
    text = row.get('text') or row.get('body') or ''
    lang = account.get('lang') or row.get('lang') or 'en'
    day = row.get('day') or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    rel = Path(rel_prefix) / day / f"{row['id']}.png"
    path = Path(out_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tried = []
    first = plan['style']
    chain = []
    if first in media_sources.NEW_STYLES:   # source capture first, then the v2 style this draft would have had
        chain.append(first)
        first = plan.get('fallback_style')
    if first:
        chain.append(first)
        if first in ('tv_widget', 'table') or (first == 'panel' and plan.get('subject')):
            chain.append('tv_drawn')
    made = None
    for style in chain:
        try:
            if style in media_sources.NEW_STYLES:
                if not captures_enabled():
                    tried.append({'style': style, 'error': 'captures disabled'})
                    continue
                ok, info = media_sources.CAPTURERS[style](plan['sources'][style], plan['theme'], lang, path, _capture)
                if ok and _png_ok(path):
                    made = {'style': style, 'capture': True, 'page': info.get('page'), 'source_info': info,
                            'data': {'source': info.get('source_name'), 'url': info.get('page'),
                                     'fetched_at': info.get('captured_at'), 'rows': info.get('text_sha')},
                            'extra': {}}
                    break
                tried.append({'style': style, 'error': info.get('error') or 'blank capture'})
                continue
            fred = style == 'panel' and (plan.get('series') or {}).get('provider') == 'fred'
            if style == 'tv_widget' or (fred and captures_enabled()):
                if not captures_enabled():
                    tried.append({'style': style, 'error': 'captures disabled'})
                    continue
                if style == 'tv_widget':
                    res, url = capture_widget(plan, path, lang)
                    data = _fetch_candles(plan['subject'], plan['interval'], bars=200, ttl=ttl)   # data_sha / refresh
                else:
                    res, url = capture_fred(plan['series'], path)
                    data = charts.fetch_series(plan['series'], ttl=ttl)
                if res.get('ok') and _png_ok(path):
                    made = {'style': style, 'capture': True, 'page': url, 'data': data, 'extra': {}}
                    break
                tried.append({'style': style, 'error': res.get('error') or 'blank capture'})
                if style == 'tv_widget':
                    continue
                # FRED page failed: draw the same series locally below
            cfg, data, *extra = BUILDERS[style]({**plan, 'style': style}, text, lang, ttl=ttl)
            if not cfg:
                tried.append({'style': style, 'error': 'no data', 'detail': (data or {}).get('attempts')})
                continue
            res = render_html(cfg, path, dpr=3 if style == 'mobile' else 2)
            if res.get('ok') and _png_ok(path):
                made = {'style': style, 'capture': False, 'data': data, 'extra': extra[0] if extra else {}}
                break
            tried.append({'style': style, 'error': res.get('error') or 'blank render'})
        except Exception as exc:   # noqa: BLE001 - any failure: next style
            tried.append({'style': style, 'error': f'{type(exc).__name__}: {str(exc)[:160]}'})
    if not made:
        media, old_plan = _old_attach(row, account, out_dir, rel_prefix, ttl, tried)
        if media:
            return media, {**plan, 'kind': media['chart_type'], 'tried': tried}
        path.unlink(missing_ok=True)
        return None, {**plan, 'kind': None, 'failed': tried}
    data = made['data']
    subj, series = plan.get('subject'), plan.get('series')
    # source captures are data images: the hourly refresh rechecks them at most every 6 h (scripts/refresh_charts.py)
    kind = 'data' if (made['style'] == 'panel' and series) or made['style'] in media_sources.NEW_STYLES else 'candle'
    label = (subj or {}).get('display') or (series or {}).get('title')
    info = made.get('source_info') or {}
    src = plan.get('sources') or {}
    alt = {'tv_widget': f'{label} {INTERVAL_LABEL.get(plan["interval"], "")} chart (TradingView widget)',
           'tv_drawn': f'{label} {INTERVAL_LABEL.get(plan["interval"], "")} candlestick chart',
           'mobile': f'{label} price screen', 'panel': f'{label} chart', 'table': 'Perp funding / open interest table',
           'x_post': f"Screenshot of the source post by @{src.get('x_post', {}).get('handle')}",
           'etf_flows': f"{src.get('etf_flows', {}).get('asset')} spot ETF daily flows ({info.get('source_name')})",
           'polymarket': f"Polymarket: {(info.get('market') or {}).get('question')}",
           'article': f"Screenshot of the source article ({info.get('source_name')})"}[made['style']]
    levels = made['extra'].get('levels') or []
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    data_sha = hashlib.sha256(json.dumps([made['style'], alt, data.get('rows'), levels], default=str).encode()).hexdigest()
    rendered = datetime.now(timezone.utc).isoformat(timespec='seconds')
    sources = [{'name': data.get('source'), 'url': data.get('url'), 'fetched_at': data.get('fetched_at')}]
    if made['style'] in media_sources.NEW_STYLES:
        sources = [{'name': info.get('source_name'), 'url': made['page'], 'fetched_at': info.get('captured_at') or rendered}]
    elif made.get('page'):
        sources.insert(0, {'name': 'TradingView widget' if made['style'] == 'tv_widget' else 'FRED graph page',
                           'url': made['page'], 'fetched_at': rendered})
    spec = {'draft_id': row['id'], 'kind': kind, 'style': made['style'], 'capture': made['capture'],
            'theme': plan['theme'], 'subject': subj, 'series': series, 'interval': plan['interval'],
            'decision': {k: plan.get(k) for k in ('why', 'p_image', 'post_type', 'candidates', 'profile_source',
                                                  'sources', 'fallback_style')},
            'tried': tried, 'data_sources': sources, 'levels': levels, 'sha256': sha, 'data_sha': data_sha,
            'refreshed_at': rendered, 'version': 'media-v3' if made['style'] in media_sources.NEW_STYLES else 'media-v2',
            **({'manual_sources': plan['manual_sources']} if plan.get('manual_sources') else {})}
    path.with_suffix('.json').write_text(json.dumps(spec, ensure_ascii=False, indent=1, default=str))
    media = {'kind': 'chart', 'chart_type': kind, 'style': made['style'], 'capture': made['capture'],
             'path': rel.as_posix(), 'alt': alt, 'data_sources': sources, 'levels': levels, 'sha256': sha,
             'data_sha': data_sha, 'refreshed_at': rendered}
    if made['style'] == 'x_post':   # a screenshot of someone's post: credit them wherever the image is shown
        media['credit'] = '@' + src['x_post']['handle'] + ' on X'
    return media, {**plan, 'kind': kind, 'profile': {'why': plan['why']}, 'tried': tried}
