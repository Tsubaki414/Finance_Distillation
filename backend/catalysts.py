"""Real forward calendar for the names the corpus is actually discussing.

Earnings dates come from Yahoo via the already-installed yfinance (1.7.0), the same supplementary
source the project used before. Results are cached on disk so a page load never hits the network:
one refresh covers every ticker, and the cache records observed_at plus the request count.

Yahoo is supplementary market data, not a primary issuer source. A date here is a scheduling
signal for planning, not a confirmed company announcement.
"""
from pathlib import Path
import json, datetime as dt

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'data/finance_supplement/earnings_calendar.json'
MACRO = ROOT / 'data/finance_supplement/macro_calendar.json'
MAX_AGE_HOURS = 12
MAX_TICKERS = 12
# Cashtags in the corpus that are not single-issuer equities.
SKIP = {'BTC', 'ETH', 'QQQ', 'SOXX', 'SPY', 'IWM', 'USD', 'GLD', 'TLT'}


def _load_cache():
    if not CACHE.exists():
        return None
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return None


def _fresh(cache):
    if not cache:
        return False
    try:
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cache['observed_at'])
        return age.total_seconds() < MAX_AGE_HOURS * 3600
    except Exception:
        return False


def refresh(symbols):
    """Network call. Run explicitly; the request path only reads the cache."""
    import yfinance as yf
    rows, requests, errors = [], 0, []
    for sym in symbols[:MAX_TICKERS]:
        if sym in SKIP:
            continue
        try:
            cal = yf.Ticker(sym).calendar or {}
            requests += 1
            dates = cal.get('Earnings Date') or []
            iso = [d.isoformat() for d in dates if hasattr(d, 'isoformat')]
            rows.append({
                'symbol': sym,
                'earnings_dates': iso,
                'next_earnings': iso[0] if iso else None,
                'revenue_estimate': cal.get('Revenue Average'),
                'eps_estimate': cal.get('EPS Average'),
                'source': 'yahoo_via_yfinance',
                'rights': 'supplementary market data; not a primary issuer disclosure',
            })
        except Exception as e:
            requests += 1
            errors.append({'symbol': sym, 'error': type(e).__name__ + ': ' + str(e)[:120]})
    payload = {
        'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'provider': 'yfinance 1.7.0 / Yahoo Finance',
        'http_requests': requests,
        'paid_api_cost': 0,
        'tickers_requested': [s for s in symbols[:MAX_TICKERS] if s not in SKIP],
        'skipped_non_equity': sorted(SKIP & set(symbols[:MAX_TICKERS])),
        'rows': rows,
        'errors': errors,
        'caveat': 'Yahoo scheduling data. Treat as a planning signal, confirm against issuer IR '
                  'before publishing a date.',
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def build(tickers, today=None):
    """Read-only. Merges the official macro schedule with the earnings calendar.

    Macro releases dominate the near term, so an earnings-only calendar leaves a false gap: with
    these tickers the next print is 25 days out, while CPI, PPI and the FOMC all land inside 10.
    """
    today = today or dt.date(2026, 9, 6)
    cache = _load_cache()
    by_sym = {r['symbol']: r for r in (cache or {}).get('rows', [])}
    mentions = {t['symbol']: t for t in tickers}

    items = []
    for sym, row in by_sym.items():
        nd = row.get('next_earnings')
        if not nd:
            continue
        try:
            d = dt.date.fromisoformat(nd)
        except Exception:
            continue
        days = (d - today).days
        if days < 0:
            continue
        m = mentions.get(sym, {})
        items.append({
            'date': nd, 'days': days, 'kind': 'Earnings',
            'symbol': sym, 'name': m.get('name') or sym,
            'title': f"{m.get('name') or sym} earnings",
            'mentions': m.get('posts'), 'mention_delta': m.get('delta'),
            'voices': m.get('voices'),
            'revenue_estimate': row.get('revenue_estimate'),
            'evidence': 'real', 'source': 'Yahoo via yfinance',
        })
    macro = json.loads(MACRO.read_text()) if MACRO.exists() else {'events': [], 'sources': []}
    for ev in macro.get('events', []):
        try:
            d = dt.date.fromisoformat(ev['date'])
        except Exception:
            continue
        days = (d - today).days
        if days < 0:
            continue
        items.append({
            'date': ev['date'], 'days': days, 'kind': ev['kind'], 'symbol': None,
            'name': ev['publisher'], 'title': ev['title'], 'time': ev.get('time'),
            'importance': ev.get('importance'), 'publisher': ev['publisher'],
            'mentions': None, 'mention_delta': None, 'voices': None,
            'evidence': 'real', 'source': ev['publisher'] + ' official schedule',
        })

    items.sort(key=lambda x: (x['days'], {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
                              .get(x.get('importance'), 2)))
    return {
        'macro_sources': macro.get('sources', []),
        'macro_caveat': macro.get('caveat'),
        'items': items,
        'observed_at': (cache or {}).get('observed_at'),
        'provider': (cache or {}).get('provider'),
        'http_requests_last_refresh': (cache or {}).get('http_requests'),
        'cache_path': 'data/finance_supplement/earnings_calendar.json',
        'stale': not _fresh(cache),
        'caveat': (cache or {}).get('caveat'),
    }


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import signals
    syms = [t['symbol'] for t in signals.build()['tickers']]
    out = refresh(syms)
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=1))
    for r in out['rows']:
        print(f"  {r['symbol']:6} {r['next_earnings']}")
