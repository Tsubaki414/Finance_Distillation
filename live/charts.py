"""Chart images for drafts: candlesticks from fetched market data, line charts from FRED / DefiLlama series.

Rule zero: every plotted value comes from a fetch made here (cached under live/store/chart_data with the request
URL and fetch time). If no provider returns data, there is no chart; nothing is ever drawn from the draft text
except the horizontal "levels" the draft itself names, and those are only drawn when they sit inside the fetched
price range.

- Candles: crypto from Binance spot klines (data-api.binance.vision mirror first: api.binance.com answers 451 from
  some regions), falling back to CoinGecko OHLC; US stocks / indices from Yahoo's chart API (what yfinance wraps),
  falling back to Stooq daily CSV. MA20 / MA50 overlay, volume, a TradingView-like dark look, small source + time.
- Data: FRED series (rates, CPI, unemployment, M2, Fed balance sheet, dollar) for macro drafts; DefiLlama total /
  per-chain TVL and stablecoin supply for DeFi drafts.
- Which accounts get which kind: `chart_profile(account)`, from the fd20 beat text and the donors' chart_caption
  share in the posting-habit card. Which ticker / series: `pick_subject(text)` / `pick_series(text)`.

`attach(row, out_dir)` renders one draft's chart and returns the media dict (or None); the text is never touched.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get('FD_CHART_CACHE', ROOT / 'live/store/chart_data'))
HABITS = ROOT / 'live/personas/posting_habits'
UA = {'User-Agent': 'Mozilla/5.0 (fd-charts; +research)'}
TIMEOUT = 20
CACHE_TTL_S = 3 * 3600

# ------------------------------------------------------------------ subjects

# symbol -> (EN name patterns, ZH literals, CoinGecko id). Short uppercase symbols match case-sensitively only.
CRYPTO = {
    'BTC': ([r'bitcoin'], ['比特币', '大饼'], 'bitcoin'),
    'ETH': ([r'ethereum', r'ether'], ['以太坊', '二饼'], 'ethereum'),
    'SOL': ([r'solana'], ['索拉纳'], 'solana'),
    'BNB': ([], [], 'binancecoin'),
    'XRP': ([r'ripple'], ['瑞波'], 'ripple'),
    'DOGE': ([r'dogecoin'], ['狗狗币'], 'dogecoin'),
    'ADA': ([r'cardano'], [], 'cardano'),
    'AVAX': ([r'avalanche'], [], 'avalanche-2'),
    'LINK': ([r'chainlink'], [], 'chainlink'),
    'SUI': ([], [], 'sui'),
    'TON': ([r'toncoin'], [], 'the-open-network'),
    'HYPE': ([r'hyperliquid'], [], 'hyperliquid'),
    'ENA': ([r'ethena'], [], 'ethena'),
    'AAVE': ([], [], 'aave'),
    'UNI': ([r'uniswap'], [], 'uniswap'),
    'LTC': ([r'litecoin'], ['莱特币'], 'litecoin'),
    'TRX': ([r'tron'], ['波场'], 'tron'),
    'NEAR': ([], [], 'near'),
    'APT': ([r'aptos'], [], 'aptos'),
    'ARB': ([r'arbitrum'], [], 'arbitrum'),
    'PEPE': ([], [], 'pepe'),
    'ZEC': ([r'zcash'], ['大零币'], 'zcash'),
    'ONDO': ([r'ondo finance'], [], 'ondo-finance'),
    'TAO': ([r'bittensor'], [], 'bittensor'),
    'WLD': ([r'worldcoin'], [], 'worldcoin-wld'),
}
# Yahoo symbol -> (display, EN patterns, ZH literals)
STOCKS = {
    'NVDA': ('NVDA', [r'nvidia'], ['英伟达']), 'TSLA': ('TSLA', [r'tesla'], ['特斯拉']),
    'AAPL': ('AAPL', [r'apple'], ['苹果公司']), 'MSFT': ('MSFT', [r'microsoft'], ['微软']),
    'AMZN': ('AMZN', [r'amazon'], ['亚马逊']), 'GOOGL': ('GOOGL', [r'alphabet', r'google'], ['谷歌']),
    'META': ('META', [r'meta platforms'], []), 'AMD': ('AMD', [], ['超威']),
    'AVGO': ('AVGO', [r'broadcom'], ['博通']), 'TSM': ('TSM', [r'tsmc'], ['台积电']),
    'MU': ('MU', [r'micron'], ['美光']), 'ORCL': ('ORCL', [r'oracle'], ['甲骨文']),
    'PLTR': ('PLTR', [r'palantir'], []), 'COIN': ('COIN', [r'coinbase'], []),
    'MSTR': ('MSTR', [r'microstrategy', r'strategy inc'], ['微策略']), 'NFLX': ('NFLX', [r'netflix'], ['奈飞']),
    'INTC': ('INTC', [r'intel'], ['英特尔']), 'ASML': ('ASML', [], ['阿斯麦']), 'ARM': ('ARM', [], []),
    'SMCI': ('SMCI', [r'supermicro'], ['超微电脑']), 'CRWV': ('CRWV', [r'coreweave'], []),
    'SPY': ('SPY', [], []), 'QQQ': ('QQQ', [], []),
    '^GSPC': ('SPX', [r's&p ?500', r'spx'], ['标普500', '标普']), '^IXIC': ('IXIC', [r'nasdaq composite'], ['纳斯达克', '纳指']),
    '^NDX': ('NDX', [r'nasdaq ?100', r'ndx'], ['纳斯达克100']), '^DJI': ('DJI', [r'dow jones'], ['道琼斯', '道指']),
}
NOT_TICKERS = {'AI', 'US', 'USD', 'ETF', 'CEO', 'CFO', 'GDP', 'CPI', 'PCE', 'FED', 'FOMC', 'IPO', 'ATH', 'TVL', 'SEC',
               'CFTC', 'API', 'DEX', 'CEX', 'L1', 'L2', 'RWA', 'DCA', 'PE', 'EPS', 'YOY', 'QOQ', 'UTC', 'BJT', 'OK'}


def _hits(text, sym, en, zh):
    """(mentions, first position) of one subject: the symbol (case-sensitive, optional $), EN names, ZH names."""
    pats = [(rf'(?<![A-Za-z0-9])\$?{re.escape(sym)}(?![A-Za-z0-9])', 0)] + \
        [(rf'(?<![A-Za-z]){p}(?![A-Za-z])', re.I) for p in en] + [(re.escape(z), 0) for z in zh]
    starts = [m.start() for p, flags in pats for m in re.finditer(p, text, flags)]
    return len(starts), min(starts, default=10 ** 9)


def pick_subject(text):
    """The draft's main ticker: {'asset': 'crypto'|'stock', 'symbol', 'display'} or None. Most mentions wins,
    ties go to the first mentioned. Unknown $CASHTAGS count as stocks (Yahoo decides whether they exist)."""
    text = text or ''
    found = []
    for sym, (en, zh, _cg) in CRYPTO.items():
        n, first = _hits(text, sym, en, zh)
        if n:
            found.append((n, -first, 'crypto', sym, sym))
    for ysym, (disp, en, zh) in STOCKS.items():
        n, first = _hits(text, disp, en, zh)
        if n:
            found.append((n, -first, 'stock', ysym, disp))
    known = {f[4] for f in found}
    for m in re.finditer(r'\$([A-Z]{1,5})(?![A-Za-z])', text):
        sym = m.group(1)
        if sym not in known and sym not in NOT_TICKERS and sym not in CRYPTO:
            known.add(sym)
            found.append((len(re.findall(rf'\${sym}(?![A-Za-z])', text)), -m.start(), 'stock', sym, sym))
    if not found:
        return None
    _n, _neg, asset, sym, disp = max(found)
    return {'asset': asset, 'symbol': sym, 'display': disp}


def subjects_in(text):
    """Every known crypto / stock symbol the text mentions (by symbol, $cashtag or name) - used by live/heat.py."""
    text = text or ''
    out = {sym for sym, (en, zh, _cg) in CRYPTO.items() if _hits(text, sym, en, zh)[0]}
    out |= {disp for disp, en, zh in STOCKS.values() if _hits(text, disp, en, zh)[0]}
    return out


# FRED series: id -> (EN patterns, ZH literals, title, unit, start)
FRED = {
    'DGS10': ([r'10[- ]?y(ea)?r?\b.{0,12}yield', r'10y', r'ten[- ]year', r'treasury yields?'],
              ['10年期美债', '十年期美债', '10年美债', '美债收益率', '10年期国债'], 'US 10Y Treasury yield', '%', 730),
    'DFF': ([r'fed funds', r'federal funds rate', r'policy rate', r'rate cuts?', r'rate hikes?'],
            ['联邦基金利率', '降息', '加息', '政策利率'], 'Effective Fed funds rate', '%', 1095),
    'CPIAUCSL': ([r'\bcpi\b', r'inflation'], ['CPI', '通胀'], 'US CPI (index, SA)', 'index', 1825),
    'UNRATE': ([r'unemployment', r'jobless rate', r'payrolls', r'\bnfp\b'], ['失业率', '非农'], 'US unemployment rate', '%', 1825),
    'M2SL': ([r'\bm2\b', r'money supply'], ['M2', '货币供应'], 'US M2 money stock', 'bn USD', 1825),
    'WALCL': ([r'balance sheet', r'\bqt\b', r'\bqe\b'], ['缩表', '扩表', '资产负债表'], 'Fed total assets', 'mn USD', 1095),
    'DFII10': ([r'real yields?', r'\btips\b'], ['实际利率', '实际收益率'], 'US 10Y real yield (TIPS)', '%', 730),
    'DTWEXBGS': ([r'\bdxy\b', r'dollar index', r'broad dollar'], ['美元指数'], 'Broad US dollar index', 'index', 730),
}
LLAMA_CHAINS = {'Ethereum': ['ethereum', '以太坊'], 'Solana': ['solana', '索拉纳'], 'Base': ['base chain', 'on base'],
                'Arbitrum': ['arbitrum'], 'Hyperliquid L1': ['hyperliquid'], 'BSC': ['bnb chain', 'bsc'],
                'Tron': ['tron', '波场'], 'Sui': ['sui']}


def pick_series(text):
    """Data series the draft is about: {'provider': 'fred'|'defillama', 'series', 'title', 'unit'} or None."""
    text = text or ''
    best = None
    for sid, (en, zh, title, unit, start) in FRED.items():
        n = sum(len(re.findall(p, text, re.I)) for p in en) + sum(text.count(z) for z in zh)
        if sid == 'DFII10' and n:
            n += 10   # "real yield" / TIPS is the specific series; "10y yield" alone also hits DGS10
        if n and (best is None or n > best[0]):
            best = (n, {'provider': 'fred', 'series': sid, 'title': title, 'unit': unit, 'days': start})
    low = text.lower()
    if re.search(r'stablecoin|稳定币', low):
        n = len(re.findall(r'stablecoin|稳定币', low))
        if best is None or n >= best[0]:
            best = (n, {'provider': 'defillama', 'series': 'stablecoins', 'title': 'Stablecoin supply (USD)',
                        'unit': 'USD', 'days': 730})
    if re.search(r'\btvl\b|total value locked|锁仓', low):
        chain = next((c for c, keys in LLAMA_CHAINS.items() if any(k in low for k in keys)), None)
        n = len(re.findall(r'\btvl\b|total value locked|锁仓', low)) + 1
        if best is None or n >= best[0]:
            best = (n, {'provider': 'defillama', 'series': f'tvl:{chain or "all"}',
                        'title': f'{chain + " " if chain else "DeFi "}TVL (USD)', 'unit': 'USD', 'days': 730})
    return best[1] if best else None


# ------------------------------------------------------------------ account eligibility

CANDLE_BEAT = re.compile(r'K线|点位|周期|交易|levels|cycles?|charts?|trading', re.I)
DATA_BEAT = re.compile(r'宏观|macro|DeFi|链上|on-chain|资金流|flows|RWA|market data|组合', re.I)
CHART_SHARE_MIN = 0.25


def chart_share(account_id, habits_dir=None):
    try:
        card = json.loads(((habits_dir or HABITS) / f'{account_id}.json').read_text())
        return float((card.get('post_type_mix') or {}).get('chart_caption') or 0)
    except (OSError, ValueError):
        return 0.0


def chart_profile(account, habits_dir=None):
    """{'candle': bool, 'data': bool, 'chart_share': float, 'why': str} for one fd20 account row.

    candle: the beat is technical / cycle / price-structure (K线, 点位, 周期, levels, cycles, charts, trading) or the
    donors attach a chart to >= 25% of posts on a crypto account (screenshots of price are their default image).
    data: the beat is macro / on-chain / DeFi / flows / market-data, or donors chart >= 25% on a non-crypto account."""
    beat = str(account.get('beat') or '')
    share = chart_share(account['id'], habits_dir)
    candle = bool(CANDLE_BEAT.search(beat)) or (share >= CHART_SHARE_MIN and account.get('kind') == 'crypto'
                                                 and not DATA_BEAT.search(beat))
    data = bool(DATA_BEAT.search(beat)) or (share >= CHART_SHARE_MIN and account.get('kind') != 'crypto')
    why = [w for w, ok in ((f'beat "{beat}"', CANDLE_BEAT.search(beat) or DATA_BEAT.search(beat)),
                           (f'donor chart_caption share {share:.2f}', share >= CHART_SHARE_MIN)) if ok]
    return {'candle': candle, 'data': data, 'chart_share': round(share, 3), 'why': '; '.join(why) or 'no chart habit'}


# ------------------------------------------------------------------ fetch (cached)

def _cache_path(provider, series, key):
    safe = re.sub(r'[^A-Za-z0-9_.:-]+', '_', series).replace(':', '_')
    return CACHE / provider / safe / f'{key}.json'


def _get(url, provider, series, key, parse, method='GET', ttl=None, **kw):
    """Fetch + parse with an on-disk cache (3h, or `ttl` seconds; 0 = always refetch); returns (payload, meta) or
    (None, error-meta). Never raises."""
    path = _cache_path(provider, series, key)
    try:
        hit = json.loads(path.read_text())
        if time.time() - hit['fetched_ts'] < (CACHE_TTL_S if ttl is None else ttl) and hit.get('rows'):
            return hit['rows'], {'url': hit['url'], 'fetched_at': hit['fetched_at'], 'cached': True}
    except (OSError, ValueError, KeyError):
        pass
    try:
        r = requests.request(method, url, headers=UA, timeout=TIMEOUT, **kw)
        r.raise_for_status()
        rows = parse(r)
    except Exception as exc:   # noqa: BLE001 - any provider failure means "no data from this provider"
        return None, {'url': url, 'error': f'{type(exc).__name__}: {str(exc)[:160]}'}
    if not rows:
        return None, {'url': url, 'error': 'empty'}
    now = datetime.now(timezone.utc)
    meta = {'url': url, 'fetched_at': now.isoformat(timespec='seconds'), 'cached': False}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**meta, 'fetched_ts': now.timestamp(), 'rows': rows}))
    except OSError:
        pass
    return rows, meta


def _ohlc_ok(rows):
    out = []
    for t, o, h, l, c, v in rows:
        if None in (o, h, l, c) or not all(map(math.isfinite, (o, h, l, c))) or min(o, h, l, c) <= 0:
            continue
        out.append([int(t), float(o), float(h), float(l), float(c), float(v or 0)])
    return out


INTERVALS = {'1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800}


def fetch_crypto(sym, interval='1d', bars=150, ttl=None):
    pair = f'{sym}USDT'
    attempts = []
    for host in ('https://data-api.binance.vision', 'https://api.binance.com'):
        url = f'{host}/api/v3/klines?symbol={pair}&interval={interval}&limit={bars}'
        # bars in the key: a 150-bar entry must not answer a 1000-bar request made in the same hour
        rows, meta = _get(url, 'binance', pair, f'{interval}-{bars}-{datetime.now(timezone.utc):%Y%m%d%H}',
                          lambda r: _ohlc_ok([(k[0] // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                                               float(k[5])) for k in r.json()]), ttl=ttl)
        attempts.append(meta)
        if rows:
            return {'rows': rows, 'source': 'Binance spot', 'pair': pair, 'interval': interval, **meta}
    cg = CRYPTO.get(sym, (None, None, None))[2]
    if cg:
        days = 180 if interval in ('1d', '1w') else 30
        url = f'https://api.coingecko.com/api/v3/coins/{cg}/ohlc?vs_currency=usd&days={days}'
        rows, meta = _get(url, 'coingecko', cg, f'{days}d-{datetime.now(timezone.utc):%Y%m%d%H}',
                          lambda r: _ohlc_ok([(k[0] // 1000, k[1], k[2], k[3], k[4], 0) for k in r.json()]), ttl=ttl)
        attempts.append(meta)
        if rows:
            step = rows[1][0] - rows[0][0] if len(rows) > 1 else 0
            label = {14400: '4h', 86400: '1d', 345600: '4d'}.get(step, f'{step // 3600}h')
            return {'rows': rows[-bars:], 'source': 'CoinGecko (data by CoinGecko)', 'pair': f'{sym}/USD',
                    'interval': label, **meta}
    return {'rows': None, 'attempts': attempts}


def fetch_stock(ysym, interval='1d', bars=150, ttl=None):
    rng = {'1d': '1y', '1w': '5y', '1h': '1mo'}.get(interval, '1y')
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(ysym)}?range={rng}&interval={interval}'

    def parse(r):
        res = r.json()['chart']['result'][0]
        q = res['indicators']['quote'][0]
        return _ohlc_ok(list(zip(res['timestamp'], q['open'], q['high'], q['low'], q['close'], q['volume'])))
    rows, meta = _get(url, 'yahoo', ysym, f'{interval}-{datetime.now(timezone.utc):%Y%m%d%H}', parse, ttl=ttl)
    attempts = [meta]
    if rows:
        return {'rows': rows[-bars:], 'source': 'Yahoo Finance', 'pair': ysym.lstrip('^'), 'interval': interval, **meta}
    stooq = (ysym.lstrip('^').lower() if ysym.startswith('^') else f'{ysym.lower()}.us')
    url = f'https://stooq.com/q/d/l/?s={stooq}&i={"w" if interval == "1w" else "d"}'

    def parse_csv(r):
        out = []
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                t = int(datetime.fromisoformat(row['Date']).replace(tzinfo=timezone.utc).timestamp())
                out.append((t, float(row['Open']), float(row['High']), float(row['Low']), float(row['Close']),
                            float(row.get('Volume') or 0)))
            except (KeyError, ValueError):
                continue
        return _ohlc_ok(out)
    rows, meta = _get(url, 'stooq', stooq, f'{interval}-{datetime.now(timezone.utc):%Y%m%d%H}', parse_csv, ttl=ttl)
    attempts.append(meta)
    if rows:
        return {'rows': rows[-bars:], 'source': 'Stooq', 'pair': ysym.lstrip('^'), 'interval': interval, **meta}
    return {'rows': None, 'attempts': attempts}


def fetch_series(spec, ttl=None):
    prov, sid = spec['provider'], spec['series']
    key = datetime.now(timezone.utc).strftime('%Y%m%d')
    if prov == 'fred':
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}'

        def parse(r):
            out = []
            for row in csv.reader(io.StringIO(r.text)):
                try:
                    out.append((int(datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc).timestamp()),
                                float(row[1])))
                except (ValueError, IndexError):
                    continue
            return out
        rows, meta = _get(url, 'fred', sid, key, parse, ttl=ttl)
        source = 'FRED, Federal Reserve Bank of St. Louis'
    elif prov == 'defillama' and sid == 'stablecoins':
        url = 'https://stablecoins.llama.fi/stablecoincharts/all'
        rows, meta = _get(url, 'defillama', sid, key, lambda r: [
            (int(x['date']), float((x.get('totalCirculatingUSD') or {}).get('peggedUSD') or 0)) for x in r.json()
            if (x.get('totalCirculatingUSD') or {}).get('peggedUSD')], ttl=ttl)
        source = 'DefiLlama'
    elif prov == 'defillama' and sid.startswith('tvl:'):
        chain = sid.split(':', 1)[1]
        url = 'https://api.llama.fi/v2/historicalChainTvl' + ('' if chain == 'all' else '/' + requests.utils.quote(chain))
        rows, meta = _get(url, 'defillama', sid, key, lambda r: [(int(x['date']), float(x['tvl'])) for x in r.json()
                                                                 if x.get('tvl')], ttl=ttl)
        source = 'DefiLlama'
    else:
        return {'rows': None}
    if not rows:
        return {'rows': None, 'attempts': [meta]}
    cut = rows[-1][0] - spec.get('days', 730) * 86400
    rows = [r for r in rows if r[0] >= cut and math.isfinite(r[1])]
    return {'rows': rows, 'source': source, **meta} if len(rows) >= 2 else {'rows': None, 'attempts': [meta]}


# ------------------------------------------------------------------ levels named in the draft

# A number is a price level only with a price cue next to it ($, 美元/点/USD after it, or a level word such as
# support / resistance / 支撑 / 突破 / 关口 just before it), a multiplier at most k / 千 / 万, and no unit that makes it
# an amount, share, count, duration or date (亿, million, %, 倍, 小时, 年, BTC, 枚 ...).
NUM = re.compile(r'(?<![\w.$])(\$|＄)?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d,]*\d)\s*'
                 r'(k(?![a-z])|K(?![a-z])|千|万|w(?![a-z])|W(?![a-z]))?')
AMOUNT_AFTER = re.compile(
    r'\s*(?:%|％|亿|億|兆|万亿|百万|千万|bn\b|b\b|B\b|mn\b|m\b|M\b|million|billion|trillion|thousand|x\b|X\b|倍|'
    r'年|月|日|号|天|周|小时|分钟|秒|h\b|d\b|个|家|人|次|笔|张|枚|只|股|手|根|条|篇|位(?!置)|名|期|季|轮|'
    r'bps?\b|基点|shares?|contracts?|coins?|tokens?|days?|hours?|weeks?|months?|years?|times|people|users|'
    r'wallets?|addresses|[-–~到至]\s*\d+\s*(?:%|％)|(?:BTC|ETH|SOL|枚|个比特币))', re.I)
PRICE_AFTER = re.compile(r'\s*(?:[-–~到至]\s*\$?\d|美元|美金|刀|USD\b|USDT\b|点|关口|一线|整数关|附近|区域|区间|上方|下方|支撑|压力|阻力|'
                         r'level|support|resistance|handle|area|zone)', re.I)
PRICE_BEFORE = re.compile(
    r'(?:support|resistance|level|target|opens?|tp|sl|stop|invalidation|break(?:s|ing)?|broke|reclaim(?:s|ed|ing)?|'
    r'hold(?:s|ing)?|lose|lost|loses|retest(?:s|ed)?|above|below|under|over|toward|towards|near|around|at|to|from|'
    r'between|and|or|top|bottom|ceiling|floor|high|low|close[ds]?|price|trades?|trading|sits?|tagged|hit|'
    r'支撑|压力|阻力|目标|突破|跌破|站上|站稳|站回|回踩|守住|失守|守|收复|关口|点位|价位|位置|区间|上方|下方|附近|'
    r'到|至|回到|摸到|涨到|跌到|冲到|拉到|砸到|在|于|上破|下破|破|收在|收于|高点|低点|前高|前低|和|或|、|~|-|–)'
    r'\s*(?:the\s+)?(?:\$|＄)?\s?$', re.I)
DATE_SPAN = re.compile(r'\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|(?<!\d)\d{1,2}[/-]\d{1,2}(?![\d,.]|\s*[kK万])|\d{1,2}:\d{2}|'
                       r'\d{1,2}月\d{1,2}[日号]?|[QH][1-4]\b|第\s*\d+|#\d+|\d+(?:st|nd|rd|th)\b')
MULT = {'k': 1e3, 'K': 1e3, '千': 1e3, '万': 1e4, 'w': 1e4, 'W': 1e4}


def _price_numbers(text):
    """(value, start) for every number in the text that reads as a price level (cue present, not an amount)."""
    text = text or ''
    dates = [m.span() for m in DATE_SPAN.finditer(text)]
    out = []
    for m in NUM.finditer(text):
        dollar, raw, suf = m.groups()
        start = m.start(2)
        if any(a <= start < b for a, b in dates):
            continue
        if AMOUNT_AFTER.match(text, m.end()):
            continue
        try:
            v = float(raw.replace(',', '')) * MULT.get(suf or '', 1)
        except ValueError:
            continue
        if not dollar and not suf and raw.isdigit() and 1990 <= v <= 2035:   # years, not prices
            continue
        cue = bool(dollar) or bool(PRICE_AFTER.match(text, m.end())) or \
            bool(PRICE_BEFORE.search(text[max(0, m.start() - 14):m.start()]))
        if cue and v > 0:
            out.append((v, start))
    return out


def draft_levels(text, lo, hi, last=None, limit=4):
    """Price levels the draft names near the plotted price: inside [0.85 lo, 1.15 hi] and, when the last close is
    given, within -40% / +60% of it. Numbers that are not price levels (amounts, %, counts, dates, durations, years)
    are skipped. Deduped (0.4%), in text order, at most `limit`."""
    out = []
    for v, _start in _price_numbers(text):
        if not lo * 0.85 <= v <= hi * 1.15:
            continue
        if last and not last * 0.6 <= v <= last * 1.6:
            continue
        if all(abs(v - x) / v > 0.004 for x in out):
            out.append(v)
        if len(out) >= limit:
            break
    return out


def pick_interval(text):
    """Chart timeframe the draft names ("4h chart", "4小时线", "周线"); daily otherwise. "4小时内爆仓" is not a timeframe."""
    t = text or ''
    if re.search(r'\b4h (?:chart|candle|close|structure)|\b4H\b|4小时(?:线|图|级别)|四小时(?:线|图|级别)', t):
        return '4h'
    if re.search(r'\b1h (?:chart|candle|close)|1小时(?:线|图|级别)|(?<![0-9四])小时线|hourly (?:chart|close)', t, re.I):
        return '1h'
    if re.search(r'周线|weekly (?:chart|close|candle)|\b1W\b', t, re.I):
        return '1w'
    return '1d'


# ------------------------------------------------------------------ render

TV = {'bg': '#131722', 'grid': '#1f2430', 'text': '#b2b5be', 'dim': '#787b86', 'up': '#26a69a', 'down': '#ef5350',
      'ma20': '#2962ff', 'ma50': '#ff9800', 'level': '#d1d4dc', 'line': '#2962ff'}


def _ma(closes, n):
    out, s = [], 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= n:
            s -= closes[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def _fmt_price(v):
    if v >= 1000:
        return f'{v:,.0f}'
    if v >= 1:
        return f'{v:,.2f}'
    return f'{v:.6g}'


def _fig():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8})
    return plt


def render_candles(data, title, levels_text='', path=None, show=110):
    """Dark candlestick PNG (1600x900) with MA20/MA50, volume and the draft's levels; returns spec dict."""
    plt = _fig()
    rows = data['rows']
    closes = [r[4] for r in rows]
    ma20, ma50 = _ma(closes, 20), _ma(closes, 50)
    rows, ma20, ma50 = rows[-show:], ma20[-show:], ma50[-show:]
    lo, hi = min(r[3] for r in rows), max(r[2] for r in rows)
    levels = draft_levels(levels_text, lo, hi, last=rows[-1][4])
    fig = plt.figure(figsize=(8, 4.5), dpi=200, facecolor=TV['bg'])
    ax = fig.add_axes([0.02, 0.24, 0.89, 0.68], facecolor=TV['bg'])
    axv = fig.add_axes([0.02, 0.08, 0.89, 0.15], facecolor=TV['bg'], sharex=ax)
    xs = range(len(rows))
    for i, (_t, o, h, l, c, v) in enumerate(rows):
        col = TV['up'] if c >= o else TV['down']
        ax.vlines(i, l, h, color=col, linewidth=0.7)
        ax.add_patch(plt.Rectangle((i - 0.34, min(o, c)), 0.68, max(abs(c - o), (hi - lo) * 0.0015),
                                   facecolor=col, edgecolor=col, linewidth=0.4))
        axv.bar(i, v, width=0.68, color=col, alpha=0.45)
    for vals, col in ((ma20, TV['ma20']), (ma50, TV['ma50'])):
        pts = [(i, v) for i, v in enumerate(vals) if v is not None]
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, linewidth=1.0)
    for lv in levels:
        ax.axhline(lv, color=TV['level'], linewidth=0.7, linestyle=(0, (4, 3)), alpha=0.75)
        ax.text(0.5, lv, _fmt_price(lv), color=TV['level'], fontsize=6, va='center', ha='left',
                bbox={'boxstyle': 'round,pad=0.2', 'facecolor': TV['bg'], 'edgecolor': TV['level'], 'linewidth': 0.4,
                      'alpha': 0.9})
    last = rows[-1]
    ax.axhline(last[4], color=TV['up'] if last[4] >= last[1] else TV['down'], linewidth=0.5, linestyle=':', alpha=0.9)
    pad = (hi - lo) * 0.06
    ax.set_ylim(min([lo] + levels) - pad, max([hi] + levels) + pad)
    ax.set_xlim(-1, len(rows) + 1)
    for a in (ax, axv):
        a.yaxis.tick_right()
        a.tick_params(colors=TV['dim'], labelsize=6.5, length=0)
        a.grid(True, color=TV['grid'], linewidth=0.6)
        for s in a.spines.values():
            s.set_visible(False)
    axv.set_yticks([])
    plt.setp(ax.get_xticklabels(), visible=False)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _p: _fmt_price(v)))
    step = max(1, len(rows) // 6)
    axv.set_xticks(list(xs)[::step])
    fmt = '%m-%d %H:%M' if data['interval'] in ('1h', '4h') else '%b %d' if data['interval'] != '1w' else '%Y-%m'
    axv.set_xticklabels([datetime.fromtimestamp(rows[i][0], timezone.utc).strftime(fmt) for i in xs[::step]])
    o, h, l, c = last[1:5]
    chg = (c / rows[-2][4] - 1) * 100 if len(rows) > 1 else 0
    fig.text(0.02, 0.955, f'{title} · {data["interval"].upper()} · {data["source"].split(" (")[0]}', color=TV['text'],
             fontsize=9, fontweight='bold', va='center')
    col = TV['up'] if c >= o else TV['down']
    fig.text(0.02, 0.925, f'O {_fmt_price(o)}  H {_fmt_price(h)}  L {_fmt_price(l)}  C {_fmt_price(c)}  {chg:+.2f}%',
             color=col, fontsize=7, va='center')
    fig.text(0.62, 0.925, 'MA 20', color=TV['ma20'], fontsize=7, va='center')
    fig.text(0.68, 0.925, 'MA 50', color=TV['ma50'], fontsize=7, va='center')
    fetched = data.get('fetched_at', '')[:16].replace('T', ' ')
    fig.text(0.02, 0.02, f'Data: {data["source"]} · last bar {datetime.fromtimestamp(last[0], timezone.utc):%Y-%m-%d %H:%M} '
             f'UTC · fetched {fetched} UTC', color=TV['dim'], fontsize=5.5)
    if path:
        fig.savefig(path, facecolor=TV['bg'])
    plt.close(fig)
    return {'bars': len(rows), 'range': [lo, hi], 'last_close': c, 'last_bar_ts': last[0], 'levels': levels,
            'ma': [20, 50]}


def render_series(data, spec, path=None):
    """Dark line chart for one FRED / DefiLlama series; returns spec dict."""
    plt = _fig()
    rows = data['rows']
    fig = plt.figure(figsize=(8, 4.5), dpi=200, facecolor=TV['bg'])
    ax = fig.add_axes([0.03, 0.1, 0.87, 0.78], facecolor=TV['bg'])
    xs = [datetime.fromtimestamp(t, timezone.utc) for t, _v in rows]
    ys = [v for _t, v in rows]
    scale, suffix = 1, ''
    if spec['unit'] == 'USD' and max(ys) > 1e9:
        scale, suffix = 1e9, 'B'
    ys_s = [y / scale for y in ys]
    ax.plot(xs, ys_s, color=TV['line'], linewidth=1.2)
    ax.fill_between(xs, ys_s, min(ys_s), color=TV['line'], alpha=0.08)
    ax.yaxis.tick_right()
    ax.tick_params(colors=TV['dim'], labelsize=6.5, length=0)
    ax.grid(True, color=TV['grid'], linewidth=0.6)
    for s in ax.spines.values():
        s.set_visible(False)
    unit = '%' if spec['unit'] == '%' else suffix
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _p: f'{v:,.2f}{unit}' if unit == '%' else f'{v:,.0f}{unit}'))
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    last = ys_s[-1]
    ax.annotate(f'{last:,.2f}{unit}' if unit == '%' else f'{last:,.1f}{unit}', (xs[-1], last), xytext=(4, 0),
                textcoords='offset points', color=TV['bg'], fontsize=6.5, va='center',
                bbox={'boxstyle': 'square,pad=0.15', 'facecolor': TV['line'], 'edgecolor': 'none'})
    fig.text(0.03, 0.94, f'{spec["title"]}' + (f'  ({spec["series"]})' if spec['provider'] == 'fred' else ''),
             color=TV['text'], fontsize=9, fontweight='bold', va='center')
    fetched = data.get('fetched_at', '')[:16].replace('T', ' ')
    fig.text(0.03, 0.025, f'Data: {data["source"]} · last obs {xs[-1]:%Y-%m-%d} · fetched {fetched} UTC',
             color=TV['dim'], fontsize=5.5)
    if path:
        fig.savefig(path, facecolor=TV['bg'])
    plt.close(fig)
    return {'points': len(rows), 'last_value': ys[-1], 'last_ts': rows[-1][0], 'first_ts': rows[0][0]}


# ------------------------------------------------------------------ per draft

def plan_chart(row, account):
    """What chart this draft would get (no network): {'kind': 'candle'|'data', ...} or None."""
    text = (row.get('text') or row.get('body') or '').strip()
    if not text:
        return None
    prof = chart_profile(account)
    if prof['candle']:
        subj = pick_subject(text)
        if subj:
            return {'kind': 'candle', **subj, 'interval': pick_interval(text), 'profile': prof}
    if prof['data']:
        series = pick_series(text)
        if series:
            return {'kind': 'data', **series, 'profile': prof}
    return None


def attach(row, account, out_dir, rel_prefix='media', ttl=None):
    """One draft's image. Since Oct 8 live/media_real.py (per-account donor-like media: TradingView-style shots,
    phone app screens, data panels, funding tables, public-page captures, donor image rate); FD_MEDIA_V2=0 is the
    rollback to attach_v1 below, the Oct 7 dark matplotlib chart, unchanged."""
    from live import media_real
    if media_real.enabled():
        return media_real.attach(row, account, out_dir, rel_prefix=rel_prefix, ttl=ttl)
    return attach_v1(row, account, out_dir, rel_prefix=rel_prefix, ttl=ttl)


def attach_v1(row, account, out_dir, rel_prefix='media', ttl=None):
    """Render the chart for one draft into out_dir/<rel_prefix>/<day>/<id>.png (+ .json spec).

    `ttl` is the data-cache age limit in seconds (None = 3h; scripts/refresh_charts.py passes 0 to refetch).
    Returns (media dict, plan) - media None when the draft is not eligible or no provider returned data."""
    plan = plan_chart(row, account)
    if not plan:
        return None, None
    text = row.get('text') or row.get('body') or ''
    if plan['kind'] == 'candle':
        crypto = plan['asset'] == 'crypto'
        data = (fetch_crypto(plan['symbol'], plan['interval'], ttl=ttl) if crypto
                else fetch_stock(plan['symbol'], plan['interval'], ttl=ttl))
        if not data.get('rows') or len(data['rows']) < 25:
            return None, {**plan, 'failed': data.get('attempts')}
    else:
        data = fetch_series(plan, ttl=ttl)
        if not data.get('rows'):
            return None, {**plan, 'failed': data.get('attempts')}
    day = row.get('day') or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()   # inbox day = Beijing date
    rel = Path(rel_prefix) / day / f"{row['id']}.png"
    path = Path(out_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if plan['kind'] == 'candle':
        title = data['pair'] if plan['asset'] == 'crypto' else plan['display']
        info = render_candles(data, title, levels_text=text, path=path)
        alt = f"{title} {data['interval']} candlestick chart with MA20/MA50 ({data['source']})"
    else:
        info = render_series(data, plan, path=path)
        alt = f"{plan['title']} ({data['source']})"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    # What the picture shows, without the fetch stamp: same data_sha = same chart (refresh_charts.py keeps the old one).
    data_sha = hashlib.sha256(json.dumps([plan['kind'], alt, data['rows'], info.get('levels') or []],
                                         default=str).encode()).hexdigest()
    rendered = datetime.now(timezone.utc).isoformat(timespec='seconds')
    spec = {'draft_id': row['id'], 'kind': plan['kind'], 'subject': {k: plan.get(k) for k in
            ('asset', 'symbol', 'display', 'interval', 'provider', 'series', 'title', 'unit') if plan.get(k)},
            'data_source': data['source'], 'url': data['url'], 'fetched_at': data['fetched_at'],
            'render': info, 'account_profile': plan['profile'], 'sha256': sha, 'data_sha': data_sha, 'refreshed_at': rendered}
    path.with_suffix('.json').write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    media = {'kind': 'chart', 'chart_type': plan['kind'], 'path': rel.as_posix(), 'alt': alt,
             'data_sources': [{'name': data['source'], 'url': data['url'], 'fetched_at': data['fetched_at']}],
             'levels': info.get('levels') or [], 'sha256': sha, 'data_sha': data_sha, 'refreshed_at': rendered}
    return media, plan
