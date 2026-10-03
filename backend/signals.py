"""Signal extraction from the real cleaned corpus.

Everything here is computed from data/clean_posts.jsonl at request time: topic momentum, ticker
leaderboards, per topic voices and posting volume. No hardcoded findings, no illustrative numbers.
The comparison is a trailing window against the window before it, both ending at the corpus edge.
"""
from pathlib import Path
import json, re, collections, datetime as dt

ROOT = Path(__file__).resolve().parents[1]
WINDOW = 14

# Topic lexicons are explicit and auditable. They are keyword incidence, not a trained classifier.
TOPICS = {
    'labour': ('就业与劳动力', r'非农|就业|失业率|劳动力|payroll|jobless|employment|unemployment'),
    'rates': ('通胀与利率', r'通胀|CPI|利率|加息|降息|美联储|沃勒|inflation|rate cut|fed\b|fomc'),
    'aicapex': ('AI 资本开支', r'算力|资本开支|数据中心|云厂商|超大规模|GPU|capex|data ?cent|hyperscal|AI\s*(?:基础设施|基建|资本|投资|支出|infra|capex|spend)|(?:训练|推理)\s*集群'),
    'earnings': ('财报', r'财报|营收|指引|业绩|earnings|guidance|revenue|EPS'),
    'semis': ('存储与半导体', r'内存|存储|半导体|芯片|晶圆|HBM|DRAM|semiconduct|memory'),
    'risk': ('仓位与风险', r'仓位|止损|回撤|杠杆|风险收益|position siz|stop.?loss|drawdown|leverage'),
    'liquidity': ('流动性与资金流', r'流动性|资金流|liquidity|fund flow|\bETF\b|inflow|outflow'),
}

TICKER_RE = re.compile(r'\$([A-Za-z]{1,5})\b')
NAMES = {
    'NVDA': (r'英伟达|NVIDIA|NVDA', 'Nvidia'), 'AVGO': (r'博通|Broadcom|AVGO', 'Broadcom'),
    'AMD': (r'\bAMD\b', 'AMD'), 'MU': (r'美光|Micron|\bMU\b', 'Micron'),
    'TSM': (r'台积电|TSMC|\bTSM\b', 'TSMC'), 'GOOGL': (r'谷歌|Google|GOOGL', 'Alphabet'),
    'MSFT': (r'微软|Microsoft|MSFT', 'Microsoft'), 'AMZN': (r'亚马逊|Amazon|AMZN', 'Amazon'),
    'AAPL': (r'苹果|Apple|AAPL', 'Apple'), 'META': (r'\bMeta\b|脸书', 'Meta'),
    'TSLA': (r'特斯拉|Tesla|TSLA', 'Tesla'), 'COIN': (r'Coinbase|\bCOIN\b', 'Coinbase'),
    'CRWV': (r'CoreWeave|CRWV', 'CoreWeave'), 'BTC': (r'比特币|Bitcoin|\bBTC\b', 'Bitcoin'),
    'ETH': (r'以太坊|\bETH\b', 'Ethereum'),
}
# Display names only, for symbols the corpus actually discusses via $TICKER. Counting is
# driven by the cashtag itself, so an unlisted symbol still ranks; it just shows bare.
DISPLAY = {
    'SIVE': 'SiVeit', 'LITE': 'Lumentum', 'AAOI': 'Applied Opto', 'SNDK': 'SanDisk',
    'INTC': 'Intel', 'QQQ': 'Nasdaq 100 ETF', 'NBIS': 'Nebius', 'MRVL': 'Marvell',
    'COHR': 'Coherent', 'AXTI': 'AXT', 'POET': 'POET Tech', 'SOXX': 'Semis ETF',
    'JBL': 'Jabil', 'SPCX': 'SPCX', 'CCXI': 'CCXI',
}
_COMPILED = {k: (re.compile(p, re.I), label) for k, (p, label) in NAMES.items()}
_TOPIC_C = {k: (label, re.compile(p, re.I)) for k, (label, p) in TOPICS.items()}

_cache = {'mtime': None, 'rows': None}


def load():
    p = ROOT / 'data/clean_posts.jsonl'
    m = p.stat().st_mtime
    if _cache['mtime'] == m:
        return _cache['rows']
    rows = []
    for line in p.read_text().split('\n'):
        if not line:
            continue
        r = json.loads(line)
        r['_dt'] = dt.datetime.fromisoformat(r['created_at'])
        rows.append(r)
    _cache.update(mtime=m, rows=rows)
    return rows


def phase(delta_pp, recent_n):
    """Phase is a rule over measured change, stated as such. Not a trained detector."""
    if recent_n < 8:
        return 'Emerging'
    if delta_pp >= 4:
        return 'Accelerating'
    if delta_pp <= -4:
        return 'Decaying'
    if delta_pp >= 1.2:
        return 'Emerging'
    if delta_pp <= -1.2:
        return 'Reversing'
    return 'Diverging'


def build():
    rows = load()
    edge = max(r['_dt'] for r in rows)
    cur = [r for r in rows if r['_dt'] > edge - dt.timedelta(days=WINDOW)]
    prv = [r for r in rows if edge - dt.timedelta(days=2 * WINDOW) < r['_dt'] <= edge - dt.timedelta(days=WINDOW)]

    # ---- topics ----
    topics = []
    for key, (label, rx) in _TOPIC_C.items():
        hit_c = [r for r in cur if rx.search(r['text'])]
        hit_p = [r for r in prv if rx.search(r['text'])]
        ra = len(hit_c) / max(len(cur), 1) * 100
        rb = len(hit_p) / max(len(prv), 1) * 100
        voices = collections.Counter(r['source_account_id'] for r in hit_c)
        langs = collections.Counter(r['language'] for r in hit_c)
        # Pick the quote that is most on topic, then by reach. Raw view count alone surfaces a
        # popular post that merely brushes the keyword.
        def fit(r):
            body = r.get('analysis_text') or r['text']
            density = len(rx.findall(body)) / max(len(body) / 400, 1)
            views = (r.get('engagement_snapshot') or {}).get('view_count') or 0
            return (round(density, 2), views)
        best = max(hit_c, key=fit, default=None)
        topics.append({
            'id': key, 'label': label,
            'posts': len(hit_c), 'posts_prior': len(hit_p),
            'share': round(ra, 1), 'share_prior': round(rb, 1),
            'delta_pp': round(ra - rb, 1),
            'delta_posts': len(hit_c) - len(hit_p),
            'phase': phase(ra - rb, len(hit_c)),
            'voices': [{'donor': d, 'posts': n} for d, n in voices.most_common(4)],
            'voice_count': len(voices),
            'languages': dict(langs),
            'lead_quote': ({'donor': best['source_account_id'],
                            'date': best['created_at'][:10],
                            'text': (best.get('analysis_text') or best['text'])[:150],
                            'views': (best.get('engagement_snapshot') or {}).get('view_count'),
                            'url': best.get('url')} if best else None),
        })
    topics.sort(key=lambda t: -t['delta_pp'])

    # ---- tickers ----
    def count(rs):
        c = collections.Counter()
        who = collections.defaultdict(set)
        for r in rs:
            t = r['text']
            seen = set()
            for m in TICKER_RE.findall(t):
                seen.add(m.upper())
            for k, (rx, _) in _COMPILED.items():
                if rx.search(t):
                    seen.add(k)
            for k in seen:
                c[k] += 1
                who[k].add(r['source_account_id'])
        return c, who

    cc, cw = count(cur)
    pc, _ = count(prv)
    tickers = []
    for sym, n in cc.most_common(10):
        prior = pc.get(sym, 0)
        tickers.append({
            'symbol': sym, 'name': DISPLAY.get(sym) or NAMES.get(sym, ('', ''))[1] or '',
            'posts': n, 'posts_prior': prior, 'delta': n - prior,
            'multiple': round(n / prior, 1) if prior else None,
            'voices': len(cw[sym]),
        })

    # ---- volume ----
    per_day = collections.Counter(r['_dt'].date().isoformat() for r in cur)
    days = sorted(per_day)
    volume = [{'date': d, 'posts': per_day[d]} for d in days]

    return {
        'window_days': WINDOW,
        'corpus_edge': edge.isoformat(),
        'posts_current': len(cur), 'posts_prior': len(prv),
        'authors_active': len({r['source_account_id'] for r in cur}),
        'topics': topics,
        'tickers': tickers,
        'volume': volume,
        'method': 'Keyword incidence over cleaned posts, trailing 14 days against the prior 14. '
                  'Auditable lexicons, not a trained classifier.',
        'source_artifact': 'data/clean_posts.jsonl',
    }
