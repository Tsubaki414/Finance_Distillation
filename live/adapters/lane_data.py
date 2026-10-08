"""Structured lane material for the 10 niche accounts (Oct 8 evening, PM_PLAN item 4 / pm_sources).

Public, key-free, read-only JSON endpoints turned into dated, numbered fact lines (no model call). One source per
(fetcher, Beijing day): each source is one data packet for the accounts its live/source_registry.json row routes it to
(route_accounts / route_beats), so live/lane_fit.py sees lane words in every line. Aggregates, protocol / market
names and numbers only: never a contract address, wallet, ticker shill or reproduced text.

Sources (terms checked Oct 8, recorded in live/source_licence.json, tier B = cite the publisher, paraphrase numbers):
  DefiLlama   free open API (api.llama.fi / yields.llama.fi / stablecoins.llama.fi; no key; pro-only endpoints such as
              /overview/derivatives and /emissions return 402 and are not used)
  Hyperliquid public info API (POST api.hyperliquid.xyz/info, documented, no key)
  Polymarket  public Gamma API (gamma-api.polymarket.com, documented read API, no key)
  CoinGecko   public API categories endpoint (no key, attribution "CoinGecko")

Rate limits / caching: every URL is fetched at most once per CACHE_TTL_S (disk cache under live/store/lane_cache,
shared by all fetchers in a run: the yields / protocols / fees bodies feed several sources), >= MIN_GAP_S between
requests to the same host, honest bot UA. Tests pass `transport` (no network, no disk cache).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from live.adapters import common

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.environ.get('FD_LANE_CACHE', ROOT / 'live/store/lane_cache'))
CACHE_TTL_S = 3 * 3600
MIN_GAP_S = 1.2
BJT = timezone(timedelta(hours=8))
_LAST = {}

LLAMA = 'https://api.llama.fi'
YIELDS = 'https://yields.llama.fi/pools'
STABLE_ALL = 'https://stablecoins.llama.fi/stablecoincharts/all'
STABLE_CHAINS = 'https://stablecoins.llama.fi/stablecoinchains'
OI = LLAMA + '/overview/open-interest?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true'
FEES = LLAMA + '/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true'
DEXS = LLAMA + '/overview/dexs/{chain}?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true'
CHAINS = LLAMA + '/v2/chains'
CHAIN_HIST = LLAMA + '/v2/historicalChainTvl/{chain}'
PROTOCOLS = LLAMA + '/protocols'
HL_INFO = 'https://api.hyperliquid.xyz/info'
PM_MARKETS = 'https://gamma-api.polymarket.com/markets?order=volume24hr&ascending=false&closed=false&limit=200'
PM_CRYPTO = 'https://gamma-api.polymarket.com/events?tag_slug=crypto&order=volume24hr&ascending=false&closed=false&limit=40'
CG_CATEGORIES = 'https://api.coingecko.com/api/v3/coins/categories'


# ---------------------------------------------------------------- transport + cache

def _wait(url):
    host = urlparse(url).netloc
    gap = time.monotonic() - _LAST.get(host, 0)
    if gap < MIN_GAP_S:
        time.sleep(MIN_GAP_S - gap)
    _LAST[host] = time.monotonic()


def get_json(url, *, transport=None, body=None, timeout=60, ttl=CACHE_TTL_S):
    """(status, parsed JSON or None). body (dict) makes it a POST (Hyperliquid info). Disk-cached for ttl seconds
    unless a test transport is given; a failed fetch falls back to a cached body younger than 4 x ttl."""
    key = hashlib.sha1((url + json.dumps(body or {}, sort_keys=True)).encode()).hexdigest()[:20]
    path = CACHE_DIR / f'{key}.json'
    if transport is not None:
        st, text = transport(url, {'User-Agent': common.DEFAULT_UA, 'body': body})
        try:
            return st, json.loads(text) if st == 200 else None
        except ValueError:
            return 0, None
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        try:
            return 200, json.loads(path.read_text())
        except ValueError:
            pass
    _wait(url)
    try:
        import httpx
        headers = {'User-Agent': common.DEFAULT_UA, 'Accept': 'application/json'}
        r = (httpx.post(url, json=body, headers=headers, timeout=timeout) if body is not None
             else httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True))
        st, text = r.status_code, r.text
    except Exception:   # noqa: BLE001 - network error: stale cache or nothing
        st, text = 0, ''
    if st == 200:
        try:
            data = json.loads(text)
        except ValueError:
            return 0, None
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(text)
            tmp.replace(path)
        except OSError:
            pass
        return 200, data
    if path.exists() and time.time() - path.stat().st_mtime < 4 * ttl:
        try:
            return 200, json.loads(path.read_text())
        except ValueError:
            pass
    return st, None


# ---------------------------------------------------------------- formatting

def money(x):
    x = float(x or 0)
    a = abs(x)
    if a >= 1e9:
        return f'${x / 1e9:.2f}bn'
    if a >= 1e6:
        return f'${x / 1e6:.1f}m'
    if a >= 1e3:
        return f'${x / 1e3:.0f}k'
    return f'${x:.0f}'


def pct(x, digits=1, sign=True):
    x = float(x or 0)
    return f'{x:+.{digits}f}%' if sign else f'{x:.{digits}f}%'


def _now(now):
    return now or datetime.now(timezone.utc)


def snapshot(now):
    """(period, day_bjt, stamp): period = UTC date stated in the lines; id day = Beijing date (one snapshot per
    drafting day: the 23:13 London run writes the next Beijing day's); stamp = ISO UTC published_at."""
    now = _now(now)
    return now.date().isoformat(), now.astimezone(BJT).date().isoformat(), now.replace(microsecond=0).isoformat()


def row(line, numbers, period):
    """A structured row: numbers = [(text, metric), ...] all literally inside line."""
    nums = [{'text': t, 'metric': m, 'period': period, 'span_ref': 0} for t, m in numbers if t and t in line]
    return {'line': line, 'number': nums[0]['text'], 'metric': nums[0]['metric'], 'period': period, 'numbers': nums}


def result(rows, *, sid, publisher, title, url, now, requests=1):
    period, day, stamp = snapshot(now)
    rows = [r for r in rows if r and r.get('numbers')]
    # url carries the snapshot day: the ingest skips a source whose URL is already in the store (filter_known)
    out = common.structured_result(rows, id=f'{sid}-{day}', source_id=sid, publisher=publisher, title=title,
                                   url=f'{url}#{day}',
                                   published_at=stamp, adapter='lane_data:' + sid, requests=requests)
    out['rows'] = len(rows)
    return out


def _fail(st, requests=1):
    return {'status': f'http_{st}', 'requests': requests, 'sources': [], 'units': []}


# ---------------------------------------------------------------- stablecoin yield lane

def _stable_pools(data, min_tvl):
    return [p for p in (data or {}).get('data') or []
            if p.get('stablecoin') and (p.get('tvlUsd') or 0) >= min_tvl and p.get('apy') is not None]


def yield_movers(*, transport=None, now=None, top=6, min_tvl=50e6):
    """Stablecoin pools (TVL >= $50m) with the biggest 7-day APY change (DefiLlama apyPct7D), up and down."""
    st, data = get_json(YIELDS, transport=transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    # a pool whose 7-day change equals its whole APY is new (no 7-day history), not a mover
    pools = [p for p in _stable_pools(data, min_tvl) if p.get('apyPct7D') is not None and abs(p['apyPct7D']) >= 0.3
             and abs(p['apyPct7D'] - p['apy']) > 0.05]
    picked, seen = [], set()
    for side in (sorted(pools, key=lambda p: -p['apyPct7D']), sorted(pools, key=lambda p: p['apyPct7D'])):
        n = 0
        for p in side:
            k = (p['project'], p['symbol'])
            if k in seen or n >= top // 2:
                continue
            seen.add(k); picked.append(p); n += 1
    rows = []
    for p in picked:
        apy, ch, tvl = pct(p['apy'], 2, False), f"{p['apyPct7D']:+.2f} pp", money(p['tvlUsd'])
        rows.append(row(f"DefiLlama stablecoin yield mover {p['project']} {p['symbol']} on {p['chain']}, {period}: "
                        f"APY {apy}, 7-day APY change {ch}, TVL {tvl}.",
                        [(apy, f"{p['project']} {p['symbol']} APY"), (tvl, f"{p['project']} {p['symbol']} TVL")], period))
    return result(rows, sid='defillama_yield_movers', publisher='DefiLlama', now=now,
                  title='Stablecoin pools with the biggest 7-day APY moves', url='https://defillama.com/yields?attribute=stablecoins')


def pendle_stable(*, transport=None, now=None, top=6, min_tvl=10e6):
    """Pendle fixed-yield (PT) stablecoin pools and the yield-bearing stablecoin pools (sUSDe / sUSDS / USDY style)."""
    st, data = get_json(YIELDS, transport=transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    pools = _stable_pools(data, min_tvl)
    pendle = sorted([p for p in pools if str(p.get('project')).startswith('pendle')
                     and str(p.get('poolMeta') or '').startswith('For buying PT')], key=lambda p: -p['tvlUsd'])[:top // 2 + 1]
    rows = []
    for p in pendle:
        apy, tvl = pct(p['apy'], 2, False), money(p['tvlUsd'])
        pt = str(p['poolMeta']).replace('For buying ', '').strip()
        rows.append(row(f"Pendle fixed-rate stablecoin {pt} on {p['chain']}, {period}: fixed APY {apy} for buying the PT, "
                        f"pool TVL {tvl} (DefiLlama).", [(apy, f"Pendle {p['symbol']} PT fixed APY"), (tvl, f"Pendle {p['symbol']} TVL")], period))
    ybs = ('ethena-usde', 'sky-lending', 'maker-dsr', 'spark-savings', 'usual-usd0', 'maple', 'resolv', 'elixir',
           'falcon-finance', 'level', 'cap', 'usd-ai')
    rwa = ('blackrock-buidl', 'ondo-yield-assets', 'circle-usyc', 'invesco-ustb', 'franklin-templeton', 'superstate-ustb')
    for group, label, cap in ((ybs, 'Yield-bearing stablecoin', 3), (rwa, 'Tokenized treasury (RWA) fund', 3)):
        seen = set()
        for p in sorted([p for p in pools if p.get('project') in group and p.get('exposure') == 'single'], key=lambda p: -p['tvlUsd']):
            if p['project'] in seen or len(seen) >= cap:
                continue
            seen.add(p['project'])
            apy, tvl = pct(p['apy'], 2, False), money(p['tvlUsd'])
            rows.append(row(f"{label} {p['symbol']} ({p['project']}) on {p['chain']}, {period}: "
                            f"APY {apy}, TVL {tvl} (DefiLlama stablecoin yields).",
                            [(apy, f"{p['symbol']} APY"), (tvl, f"{p['symbol']} TVL")], period))
    return result(rows, sid='defillama_pendle_stable', publisher='DefiLlama', now=now,
                  title='Pendle fixed-rate PTs, yield-bearing stablecoins and tokenized treasuries', url='https://defillama.com/yields?project=pendle')


# ---------------------------------------------------------------- perp DEX lane

def perp_oi(*, transport=None, now=None, top=6):
    """Perp DEX open interest (DefiLlama open-interest overview, category Derivatives)."""
    st, data = get_json(OI, transport=transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    ps = [p for p in data.get('protocols') or [] if p.get('category') == 'Derivatives' and (p.get('total24h') or 0) > 0]
    ps.sort(key=lambda p: -p['total24h'])
    rows = []
    tot = sum(p['total24h'] for p in ps)
    if tot:
        rows.append(row(f'Perp DEX open interest tracked by DefiLlama, {period}: {money(tot)} across {len(ps)} '
                        f'perpetuals venues.', [(money(tot), 'perp DEX open interest')], period))
    for p in ps[:top]:
        oi, d1, d7 = money(p['total24h']), pct(p.get('change_1d')), pct(p.get('change_7d'))
        share = pct(100 * p['total24h'] / tot, 1, False) if tot else None
        line = f"Perp DEX {p.get('displayName') or p['name']} open interest, {period}: {oi} ({d1} 1d, {d7} 7d"
        line += f', {share} share of tracked perp OI).' if share else ').'
        rows.append(row(line, [(oi, f"{p['name']} open interest"), (d1, f"{p['name']} OI 1-day change")], period))
    return result(rows, sid='defillama_perp_oi', publisher='DefiLlama', now=now,
                  title='Perp DEX open interest by venue', url='https://defillama.com/open-interest')


def _hl_rows(data):
    meta, ctxs = data
    out = []
    for u, c in zip(meta.get('universe') or [], ctxs):
        if u.get('isDelisted'):
            continue
        try:
            px, prev = float(c.get('markPx') or 0), float(c.get('prevDayPx') or 0)
            oi = float(c.get('openInterest') or 0) * px
            out.append({'name': u['name'], 'funding': float(c.get('funding') or 0), 'oi': oi, 'px': px,
                        'vol': float(c.get('dayNtlVlm') or 0), 'chg': (px / prev - 1) * 100 if prev else 0.0})
        except (TypeError, ValueError):
            continue
    return out


def _funding(f):
    """Hyperliquid funding is hourly; annualised = hourly x 24 x 365."""
    return pct(f * 24 * 365 * 100, 1)


def hyperliquid_perps(*, transport=None, now=None, min_oi=20e6):
    """Hyperliquid perps: top open interest, most extreme funding (annualised) and biggest 24h movers."""
    st, data = get_json(HL_INFO, transport=transport, body={'type': 'metaAndAssetCtxs'}, ttl=1800)
    if st != 200 or not isinstance(data, list) or len(data) != 2:
        return _fail(st)
    period = snapshot(now)[0]
    rs = _hl_rows(data)
    big = [r for r in rs if r['oi'] >= min_oi]
    rows = []
    tot = sum(r['oi'] for r in rs)
    vol = sum(r['vol'] for r in rs)
    rows.append(row(f'Hyperliquid perps, {period}: total open interest {money(tot)}, 24h notional volume {money(vol)}.',
                    [(money(tot), 'Hyperliquid open interest'), (money(vol), 'Hyperliquid 24h perp volume')], period))
    for r in sorted(rs, key=lambda r: -r['oi'])[:4]:
        oi, fr = money(r['oi']), _funding(r['funding'])
        rows.append(row(f"Hyperliquid {r['name']} perp, {period}: open interest {oi}, funding rate {fr} annualised, "
                        f"24h price change {pct(r['chg'])}.", [(oi, f"{r['name']} open interest"), (fr, f"{r['name']} funding rate")], period))
    for r in sorted(big, key=lambda r: -abs(r['funding']))[:3]:
        fr, oi = _funding(r['funding']), money(r['oi'])
        side = 'longs pay shorts' if r['funding'] > 0 else 'shorts pay longs'
        rows.append(row(f"Hyperliquid funding extreme {r['name']} perp, {period}: funding rate {fr} annualised ({side}), "
                        f"open interest {oi}.", [(fr, f"{r['name']} funding rate"), (oi, f"{r['name']} open interest")], period))
    for r in sorted(big, key=lambda r: -abs(r['chg']))[:3]:
        ch, oi = pct(r['chg']), money(r['oi'])
        rows.append(row(f"Hyperliquid 24h mover {r['name']} perp, {period}: price {ch} in 24h, open interest {oi}, "
                        f"funding rate {_funding(r['funding'])} annualised.", [(ch, f"{r['name']} 24h price change"), (oi, f"{r['name']} open interest")], period))
    return result(rows, sid='hyperliquid_perps', publisher='Hyperliquid', now=now,
                  title='Hyperliquid perps: open interest, funding, movers', url='https://app.hyperliquid.xyz/trade')


MEME_PERPS = {'DOGE', 'kPEPE', 'kBONK', 'kSHIB', 'kFLOKI', 'kNEIRO', 'WIF', 'POPCAT', 'FARTCOIN', 'PUMP', 'PENGU',
              'TRUMP', 'MEW', 'BOME', 'MOODENG', 'SPX', 'GOAT', 'PNUT', 'BRETT', 'TURBO', 'MEME', 'CHILLGUY',
              'MELANIA', 'VINE', 'USELESS', 'kDOGS', 'TST', 'BABY', 'GRIFFAIN', 'AI16Z', 'FWOG', 'MYRO', 'NEIROETH',
              'BANANA', 'HMSTR', 'DOGS', 'WLFI', 'kLUNC', 'YZY'}


def hyperliquid_meme(*, transport=None, now=None, min_oi=1e6, top=6):
    """Memecoin perps on Hyperliquid: open interest, 24h move, funding (shared cached body with hyperliquid_perps)."""
    st, data = get_json(HL_INFO, transport=transport, body={'type': 'metaAndAssetCtxs'}, ttl=1800)
    if st != 200 or not isinstance(data, list) or len(data) != 2:
        return _fail(st)
    period = snapshot(now)[0]
    rs = [r for r in _hl_rows(data) if r['name'] in MEME_PERPS and r['oi'] >= min_oi]
    if not rs:
        return result([], sid='hyperliquid_meme_perps', publisher='Hyperliquid', now=now, title='', url=HL_INFO)
    tot = sum(r['oi'] for r in rs)
    rows = [row(f'Memecoin perps on Hyperliquid, {period}: {len(rs)} meme perps with combined open interest {money(tot)}.',
                [(money(tot), 'Hyperliquid memecoin perp open interest')], period)]
    for r in sorted(rs, key=lambda r: -r['oi'])[:top // 2] + sorted(rs, key=lambda r: -abs(r['chg']))[:top // 2]:
        ch, oi = pct(r['chg']), money(r['oi'])
        line = (f"Memecoin {r['name']} perp on Hyperliquid, {period}: 24h price change {ch}, open interest {oi}, "
                f"funding rate {_funding(r['funding'])} annualised.")
        if not any(x['line'] == line for x in rows):
            rows.append(row(line, [(ch, f"{r['name']} 24h price change"), (oi, f"{r['name']} open interest")], period))
    return result(rows, sid='hyperliquid_meme_perps', publisher='Hyperliquid', now=now,
                  title='Memecoin perps on Hyperliquid', url=HL_INFO)


# ---------------------------------------------------------------- memecoin lane

def launchpads(*, transport=None, now=None, top=6):
    """Memecoin launchpads (DefiLlama fees overview, category Launchpad): 24h fees and 1d / 7d change."""
    st, data = get_json(FEES, transport=transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    ps = [p for p in data.get('protocols') or [] if p.get('category') == 'Launchpad' and (p.get('total24h') or 0) > 0]
    ps.sort(key=lambda p: -p['total24h'])
    rows = []
    tot = sum(p['total24h'] for p in ps)
    if tot:
        lead = ps[0]
        share = pct(100 * lead['total24h'] / tot, 0, False)
        rows.append(row(f"Memecoin launchpad fees tracked by DefiLlama, {period}: {money(tot)} in 24h across {len(ps)} "
                        f"launchpads; {lead.get('displayName') or lead['name']} took {share}.",
                        [(money(tot), 'launchpad 24h fees'), (share, 'launchpad fee share')], period))
    for p in ps[:top]:
        fee, d1, d7 = money(p['total24h']), pct(p.get('change_1d')), pct(p.get('change_7d'))
        chains = '/'.join((p.get('chains') or [])[:2])
        rows.append(row(f"Memecoin launchpad {p.get('displayName') or p['name']} ({chains}), {period}: 24h fees {fee} "
                        f"({d1} 1d, {d7} 7d).", [(fee, f"{p['name']} 24h fees"), (d1, f"{p['name']} fees 1-day change")], period))
    return result(rows, sid='defillama_launchpads', publisher='DefiLlama', now=now,
                  title='Memecoin launchpads: 24h fees', url='https://defillama.com/fees?category=Launchpad')


MEME_CATEGORIES = ('meme-token', 'solana-meme-coins', 'pump-fun', 'base-meme-coins', 'four-meme-ecosystem',
                   'ai-meme-coins', 'chinese-meme')


def meme_sectors(*, transport=None, now=None):
    """Memecoin sector market caps (CoinGecko public categories endpoint)."""
    st, data = get_json(CG_CATEGORIES, transport=transport)
    if st != 200 or not isinstance(data, list):
        return _fail(st)
    period = snapshot(now)[0]
    by = {c.get('id'): c for c in data if isinstance(c, dict)}
    rows = []
    for cid in MEME_CATEGORIES:
        c = by.get(cid)
        if not c or not c.get('market_cap'):
            continue
        cap, ch, vol = money(c['market_cap']), pct(c.get('market_cap_change_24h')), money(c.get('volume_24h'))
        name = c['name'] if 'meme' in c['name'].lower() else c['name'] + ' memecoins'
        rows.append(row(f'CoinGecko {name} sector, {period}: market cap {cap} ({ch} 24h), 24h volume {vol}.',
                        [(cap, f'{name} market cap'), (ch, f'{name} 24h market cap change')], period))
    return result(rows, sid='coingecko_meme_sectors', publisher='CoinGecko', now=now,
                  title='Memecoin sector market caps', url='https://www.coingecko.com/en/categories/meme-token')


# ---------------------------------------------------------------- prediction-market lane

def _sporty(m):
    if m.get('gameId') or m.get('sportsMarketType') or m.get('gameStartTime'):
        return True
    ev = (m.get('events') or [{}])[0] or {}
    if ev.get('gameId') or ev.get('seriesSlug') or ev.get('score'):
        return True
    q = str(m.get('question') or '').lower()
    return any(w in q for w in (' vs. ', ' vs ', 'o/u', 'spread:', 'tweets', 'up or down'))


def _yes_price(m):
    try:
        outcomes, prices = json.loads(m.get('outcomes') or '[]'), [float(p) for p in json.loads(m.get('outcomePrices') or '[]')]
    except (TypeError, ValueError):
        return None
    if outcomes[:2] == ['Yes', 'No'] and prices:
        return prices[0]
    return None


def polymarket_movers(*, transport=None, now=None, top=6, min_vol=25e3):
    """Polymarket Yes/No markets with the biggest 24h odds moves (Gamma oneDayPriceChange), sports / tweet-count
    / 'up or down' intraday markets excluded."""
    st, data = get_json(PM_MARKETS, transport=transport, ttl=1800)
    if st != 200 or not isinstance(data, list):
        return _fail(st)
    period = snapshot(now)[0]
    cands = []
    for m in data:
        if m.get('closed') or _sporty(m) or float(m.get('volume24hr') or 0) < min_vol:
            continue
        p, ch = _yes_price(m), m.get('oneDayPriceChange')
        if p is None or ch is None or not 0.02 <= p <= 0.98 or abs(float(ch)) < 0.03:
            continue
        cands.append((abs(float(ch)), m, p, float(ch)))
    cands.sort(key=lambda x: -x[0])
    rows = []
    for _, m, p, ch in cands[:top]:
        q = ' '.join(str(m.get('question') or '').split())[:150]
        now_p, move, vol = f'{p * 100:.0f}%', f'{ch * 100:+.0f} pts', money(m.get('volume24hr'))
        rows.append(row(f'Polymarket odds move, {period}: "{q}" Yes at {now_p}, {move} in 24h; 24h volume {vol}.',
                        [(now_p, 'Polymarket implied probability'), (vol, 'Polymarket 24h volume')], period))
    return result(rows, sid='polymarket_movers', publisher='Polymarket', now=now,
                  title='Polymarket: biggest 24h odds moves', url='https://polymarket.com/markets')


def polymarket_crypto(*, transport=None, now=None, top=6):
    """Crypto-tagged Polymarket events by 24h volume (BTC / ETH price ladders, token launches, ETF decisions)."""
    from live.adapters import polymarket
    st, data = get_json(PM_CRYPTO, transport=transport, ttl=1800)
    if st != 200 or not isinstance(data, list):
        return _fail(st)
    period = snapshot(now)[0]
    rows = []
    for e in data:
        title = ' '.join(str(e.get('title') or '').split())[:140]
        if not title or 'up or down' in title.lower() or not e.get('volume24hr'):
            continue
        lead = polymarket.leading(e)
        if not lead:
            continue
        q, outcome, price = lead
        if not 0.03 <= price <= 0.97:   # an all-but-settled rung ('above 74,000 on October 8?' at 99.9%) says nothing
            continue
        p, vol = f'{price * 100:.0f}%', money(e['volume24hr'])
        q = ' '.join(str(q).split())[:120]
        what = f'"{outcome}" on "{q}"' if q and q != title else f'"{outcome}"'
        rows.append(row(f'Polymarket crypto market "{title}", {period}: {what} at {p}; 24h volume {vol}.',
                        [(p, 'Polymarket implied probability'), (vol, 'Polymarket 24h volume')], period))
        if len(rows) >= top:
            break
    return result(rows, sid='polymarket_crypto', publisher='Polymarket', now=now,
                  title='Polymarket: most-traded crypto markets', url=PM_CRYPTO)


def prediction_oi(*, transport=None, now=None):
    """Prediction-market venues (Kalshi, Polymarket, ...) open interest and notional volume (DefiLlama)."""
    st, oi = get_json(OI, transport=transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    ps = [p for p in oi.get('protocols') or [] if p.get('category') == 'Prediction Market' and (p.get('total24h') or 0) > 0]
    ps.sort(key=lambda p: -p['total24h'])
    rows = []
    tot = sum(p['total24h'] for p in ps)
    if tot:
        rows.append(row(f'Prediction markets open interest tracked by DefiLlama, {period}: {money(tot)} across {len(ps)} venues.',
                        [(money(tot), 'prediction market open interest')], period))
    for p in ps[:5]:
        v, d1, d7 = money(p['total24h']), pct(p.get('change_1d')), pct(p.get('change_7d'))
        rows.append(row(f"Prediction market {p.get('displayName') or p['name']} open interest, {period}: {v} "
                        f"({d1} 1d, {d7} 7d).", [(v, f"{p['name']} open interest"), (d1, f"{p['name']} OI 1-day change")], period))
    return result(rows, sid='defillama_prediction_oi', publisher='DefiLlama', now=now,
                  title='Prediction markets: open interest by venue', url='https://defillama.com/protocols/prediction-market')


# ---------------------------------------------------------------- Solana / Base lane

SOL_BASE = (('Solana', 'Solana', 'solana'), ('Base', 'Base chain', 'base'))


def chain_snapshot(name, *, transport=None, now=None, top=3):
    """One chain (Solana or Base): DeFi total value locked with 1d / 7d change, stablecoin supply, decentralised-exchange
    volume (24h, 1d / 7d) and its top venues. One source per chain, so the two chains are two stories (the hotspot
    linker clusters by shared rare names)."""
    label, slug = {'Solana': ('Solana', 'solana'), 'Base': ('Base chain', 'base')}[name]
    where = 'on Solana' if name == 'Solana' else 'on Base'
    period = snapshot(now)[0]
    rows, reqs = [], 0
    st, hist = get_json(CHAIN_HIST.format(chain=name), transport=transport)
    reqs += 1
    if st == 200 and isinstance(hist, list) and len(hist) >= 8:
        hist = sorted(hist, key=lambda d: d['date'])
        last, d1, d7 = hist[-1]['tvl'], hist[-2]['tvl'], hist[-8]['tvl']
        tvl, c1, c7 = money(last), pct((last / d1 - 1) * 100), pct((last / d7 - 1) * 100)
        rows.append(row(f'{label} DeFi total value locked per DefiLlama, {period}: {tvl} ({c1} 1d, {c7} 7d).',
                        [(tvl, f'{name} DeFi TVL'), (c7, f'{name} TVL 7-day change')], period))
    st_s, stables = get_json(STABLE_CHAINS, transport=transport)
    reqs += 1
    if st_s == 200:
        sup = next(((c.get('totalCirculatingUSD') or {}).get('peggedUSD') for c in stables or [] if c.get('name') == name), None)
        if sup:
            rows.append(row(f'Stablecoin supply {where}, {period}: {money(sup)}.', [(money(sup), f'{name} stablecoin supply')], period))
    st_d, d = get_json(DEXS.format(chain=slug), transport=transport)
    reqs += 1
    if st_d == 200 and d and d.get('total24h'):
        v, c1, c7 = money(d.get('total24h')), pct(d.get('change_1d')), pct(d.get('change_7d'))
        rows.append(row(f'Decentralised-exchange volume {where}, {period}: {v} in 24h ({c1} 1d, {c7} 7d).',
                        [(v, f'{name} DEX 24h volume'), (c1, f'{name} DEX volume 1-day change')], period))
        ps = sorted([p for p in d.get('protocols') or [] if (p.get('total24h') or 0) > 0], key=lambda p: -p['total24h'])
        for p in ps[:top]:
            pv, share = money(p['total24h']), pct(100 * p['total24h'] / d['total24h'], 0, False)
            rows.append(row(f"{p.get('displayName') or p['name']} {where}, {period}: 24h trading volume {pv}, {share} of "
                            f"the chain's exchange volume ({pct(p.get('change_1d'))} 1d).", [(pv, f"{p['name']} 24h volume")], period))
    if not rows:
        return _fail(0, reqs)
    sid = 'defillama_' + slug
    return result(rows, sid=sid, publisher='DefiLlama', now=now, requests=reqs,
                  title=f'{name} chain snapshot: value locked, stablecoins, exchange volume',
                  url=f'https://defillama.com/chain/{name}')


def solana_chain(*, transport=None, now=None):
    return chain_snapshot('Solana', transport=transport, now=now)


def base_chain(*, transport=None, now=None):
    return chain_snapshot('Base', transport=transport, now=now)


def _protocols(transport):
    st, data = get_json(PROTOCOLS, transport=transport)
    return st, data if isinstance(data, list) else []


def sol_base_movers(*, transport=None, now=None, top=6, min_tvl=20e6):
    """Solana / Base protocols with the biggest 7-day TVL change (chain-level TVL of that protocol >= $20m)."""
    st, ps = _protocols(transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    rows = []
    for name, label, _ in SOL_BASE:
        where = 'on Solana' if name == 'Solana' else 'on Base'
        cands = [p for p in ps if (p.get('chainTvls') or {}).get(name, 0) >= min_tvl and p.get('change_7d') is not None
                 and p.get('category') not in ('CEX', 'Chain', 'Bridge', 'Canonical Bridge')]
        cands.sort(key=lambda p: -abs(p['change_7d']))
        for p in cands[:top // 2]:
            tvl, c7 = money(p['chainTvls'][name]), pct(p['change_7d'])
            rows.append(row(f"{p['name']} ({p.get('category')}) {where}, {period}: TVL {tvl} {where}, total TVL "
                            f"{c7} over 7 days (DefiLlama).", [(tvl, f"{p['name']} {name} TVL"), (c7, f"{p['name']} TVL 7-day change")], period))
    return result(rows, sid='defillama_sol_base_movers', publisher='DefiLlama', now=now,
                  title='Solana and Base protocols: biggest 7-day TVL moves', url='https://api.llama.fi/protocols')


# ---------------------------------------------------------------- airdrop lane

FARM_CATEGORIES = {'Dexs', 'Lending', 'Yield', 'Yield Aggregator', 'Prediction Market', 'Restaking',
                   'Liquid Restaking', 'Collateral Markets', 'Launchpad', 'SoFi',
                   'Basis Trading', 'DEX Aggregator', 'Leveraged Farming', 'Synthetics', 'Gaming', 'Trading App'}


# exchange / regulated venues without a token are not airdrop candidates
NOT_FARMABLE = re.compile(r'binance|coinbase|bybit|okx|kraken|robinhood|kalshi|bitget|gemini|crypto\.com', re.I)


def _tokenless(p):
    return (not p.get('gecko_id') and str(p.get('symbol') or '-').strip() in ('', '-') and not p.get('parentProtocol')
            and not NOT_FARMABLE.search(str(p.get('name') or '')))


def tokenless_tvl(*, transport=None, now=None, top=8, min_tvl=50e6):
    """Tokenless DeFi protocols (no token listed on DefiLlama) by TVL and 7-day change: the pool airdrop / points
    farmers track. Bridges, curators and CEXs excluded."""
    st, ps = _protocols(transport)
    if st != 200:
        return _fail(st)
    period = snapshot(now)[0]
    cands = [p for p in ps if _tokenless(p) and (p.get('tvl') or 0) >= min_tvl and p.get('category') in FARM_CATEGORIES]
    cands.sort(key=lambda p: -p['tvl'])
    rows = []
    if cands:
        tot = money(sum(p['tvl'] for p in cands))
        rows.append(row(f'Airdrop watchlist: DeFi protocols above $50m locked with no token yet (DefiLlama), '
                        f'{period}: {len(cands)} protocols holding {tot}.', [(tot, 'tokenless protocol TVL')], period))
    for p in cands[:top]:
        tvl, c7 = money(p['tvl']), pct(p.get('change_7d'))
        chains = '/'.join((p.get('chains') or [])[:2])
        rows.append(row(f"Airdrop watchlist {p['name']} ({p.get('category')}, {chains}), {period}: {tvl} locked "
                        f"({c7} 7d); no token yet per DefiLlama, so any airdrop / TGE is still ahead.",
                        [(tvl, f"{p['name']} TVL"), (c7, f"{p['name']} TVL 7-day change")], period))
    return result(rows, sid='defillama_tokenless', publisher='DefiLlama', now=now,
                  title='Tokenless DeFi protocols (airdrop / points watchlist)', url='https://defillama.com/airdrops')


def tokenless_activity(*, transport=None, now=None, top=8):
    """Tokenless perp / prediction venues by open interest (DefiLlama OI overview joined to /protocols)."""
    st, ps = _protocols(transport)
    st2, oi = get_json(OI, transport=transport)
    if st != 200 or st2 != 200:
        return _fail(st if st != 200 else st2, 2)
    period = snapshot(now)[0]
    # perp-style venues only (the TVL watchlist covers lending / yield / DEX), so the two airdrop sources do not overlap
    tokenless = {str(p.get('id')): p for p in ps if _tokenless(p)}
    names = {p['name'].lower() for p in tokenless.values()}
    rows = []
    for p in sorted(oi.get('protocols') or [], key=lambda p: -(p.get('total24h') or 0)):
        if p.get('category') not in ('Derivatives', 'Interface', 'Options'):
            continue
        pid = str(p.get('defillamaId') or p.get('id') or '')
        if (pid in tokenless or str(p.get('name') or '').lower() in names) and not p.get('parentProtocol') \
                and not NOT_FARMABLE.search(str(p.get('name') or '')) \
                and (p.get('total24h') or 0) >= 10e6:
            v, d7 = money(p['total24h']), pct(p.get('change_7d'))
            rows.append(row(f"Points-season perp venue {p.get('displayName') or p['name']}, {period}: "
                            f"open interest {v} ({d7} 7d); it has no token yet, so a TGE / airdrop is still ahead "
                            f"(per DefiLlama listings).", [(v, f"{p['name']} open interest"), (d7, f"{p['name']} OI 7-day change")], period))
        if len(rows) >= top:
            break
    return result(rows, sid='defillama_tokenless_activity', publisher='DefiLlama', now=now, requests=2,
                  title='Perp venues with no token yet, by open interest (points / TGE watch)',
                  url='https://defillama.com/derivatives')


TGE_RX = re.compile(r'airdrop|launch (?:a |its )?token|token launch|\bFDV\b|\bTGE\b|public sale|\bICO\b|points', re.I)
PM_TGE = 'https://gamma-api.polymarket.com/events?tag_slug=crypto&order=volume24hr&ascending=false&closed=false&limit=100'


def _tge_rung(event):
    """For a ladder event (FDV above $X / launch by date) the Yes rung closest to 50% - the live line, not the
    settled 99% bottom rung. None when the event has no open Yes/No markets."""
    best = None
    for m in event.get('markets') or []:
        if m.get('closed') or not m.get('active', True):
            continue
        try:
            outcomes, prices = json.loads(m.get('outcomes') or '[]'), [float(x) for x in json.loads(m.get('outcomePrices') or '[]')]
        except (TypeError, ValueError):
            continue
        if outcomes[:2] != ['Yes', 'No'] or len(prices) < 2 or not 0.03 <= prices[0] <= 0.97:
            continue
        cand = (m.get('groupItemTitle') or m.get('question') or '', 'Yes', prices[0])
        if best is None or abs(cand[2] - 0.5) < abs(best[2] - 0.5):
            best = cand
    return best


def polymarket_tge(*, transport=None, now=None, top=6):
    """Polymarket TGE / airdrop markets ('X FDV above ___ one day after launch?', 'Will X launch a token by ___?',
    'X airdrop by ...?') by 24h volume: the market's read on upcoming token launches."""
    from live.adapters import polymarket
    st, data = get_json(PM_TGE, transport=transport, ttl=1800)
    if st != 200 or not isinstance(data, list):
        return _fail(st)
    period = snapshot(now)[0]
    rows = []
    for e in data:
        title = ' '.join(str(e.get('title') or '').split())[:140]
        if not TGE_RX.search(title) or not e.get('volume24hr'):
            continue
        lead = _tge_rung(e) or polymarket.leading(e)
        if not lead:
            continue
        q, outcome, price = lead
        if not 0.03 <= price <= 0.97:
            continue
        p, vol = f'{price * 100:.0f}%', money(e['volume24hr'])
        q = ' '.join(str(q).split())[:120]
        what = f'"{outcome}" on "{q}"' if q and q != title else f'"{outcome}"'
        rows.append(row(f'Polymarket TGE / airdrop market "{title}", {period}: {what} at {p}; 24h volume {vol}.',
                        [(p, 'Polymarket implied probability'), (vol, 'Polymarket 24h volume')], period))
        if len(rows) >= top:
            break
    return result(rows, sid='polymarket_tge', publisher='Polymarket', now=now,
                  title='Polymarket token-launch odds (FDV, airdrop, TGE timing)', url=PM_TGE)


# ---------------------------------------------------------------- registry of fetchers

FETCHERS = {
    'defillama_yield_movers': yield_movers,
    'defillama_pendle_stable': pendle_stable,
    'defillama_perp_oi': perp_oi,
    'hyperliquid_perps': hyperliquid_perps,
    'hyperliquid_meme_perps': hyperliquid_meme,
    'defillama_launchpads': launchpads,
    'coingecko_meme_sectors': meme_sectors,
    'polymarket_movers': polymarket_movers,
    'polymarket_crypto': polymarket_crypto,
    'defillama_prediction_oi': prediction_oi,
    'defillama_solana': solana_chain,
    'defillama_base': base_chain,
    'defillama_sol_base_movers': sol_base_movers,
    'defillama_tokenless': tokenless_tvl,
    'defillama_tokenless_activity': tokenless_activity,
    'polymarket_tge': polymarket_tge,
}
