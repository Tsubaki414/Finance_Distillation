"""ReportGem daily pull: broker research as a CONTENT donor (licence tier B).

Decision (Fiona, 2026-10-04): with the paid ReportGem MCP, excerpts of the
major banks' research may be used as tier-B content: paraphrase only, the bank
named in the attribution frame, never ReportGem; no verbatim copying, charts or
target prices. (source_expansion.md had rated ReportGem D; this overrides it
for excerpts returned by the paid MCP and is recorded in source_licence.json.)

Flow: listing_queries (theme queries per persona over realtime research,
day window, optional targeted/catch-up queries) -> daily_listing (exclude unsafe
banks, filter window, dedup, points cap) -> prescreen (confidence-gated Jev
batches, one retry and batch-local keyword fallback)
-> select_top -> get_evidence passages -> to_source (disclosure boilerplate and
analyst contact details dropped) -> content_units.extract as tier B.

The MCP is reached through a `call(tool, args)` function. On the box that is a
recorded-response replay of calls made through the agent's MCP connector; a
call that is not recorded is appended to `plan` instead of being invented.
"""
from __future__ import annotations

from datetime import date, timedelta
import datetime as dt
import hashlib
import json
import re

BANKS = {
    'Goldman Sachs': ('Goldman Sachs', '高盛'),
    'Morgan Stanley': ('Morgan Stanley', '摩根士丹利', '大摩'),
    'JPMorgan': ('JPMorgan', 'J.P. Morgan', 'JP Morgan', '摩根大通', '小摩'),
    'BofA': ('BofA', 'Bank of America', 'BofA Global Research', '美银'),
    'Citi': ('Citi', 'Citigroup', 'Citi Research', '花旗'),
    'UBS': ('UBS', '瑞银'),
    'Barclays': ('Barclays', '巴克莱'),
    'Deutsche Bank': ('Deutsche Bank', '德意志银行', '德银'),
    'Jefferies': ('Jefferies', '杰富瑞'),
    'Bernstein': ('Bernstein', 'AllianceBernstein', '伯恩斯坦'),
    'Nomura': ('Nomura', '野村'),
    'HSBC': ('HSBC', '汇丰'),
    'Evercore ISI': ('Evercore ISI', 'Evercore', '晓扬'),
    'Macquarie': ('Macquarie', '麦格理'),
}

BANKS.update({
    'Wells Fargo': ('Wells Fargo', 'Wells Fargo Securities'),
    'RBC': ('RBC', 'Royal Bank of Canada'),
    'BNP Paribas': ('BNP Paribas', 'BNPP'),
    'Societe Generale': ('Societe Generale', 'Société Générale', 'SocGen'),
    'Mizuho': ('Mizuho',),
    'SMBC Nikko': ('SMBC Nikko', 'SMBC'),
    'Daiwa': ('Daiwa', '大和'),
    'CLSA': ('CLSA', '里昂'),
    'ING': ('ING',),
    'Santander': ('Santander',),
    'Credit Agricole': ('Credit Agricole', 'Crédit Agricole', 'CA-CIB', 'CACIB'),
    'Natixis': ('Natixis',),
    'TD Securities': ('TD Securities',),
    'Scotiabank': ('Scotiabank', 'Scotia'),
    'Piper Sandler': ('Piper Sandler',),
    'Wolfe Research': ('Wolfe Research',),
    'KeyBanc': ('KeyBanc', 'KeyBank'),
    'Raymond James': ('Raymond James',),
    'Stifel': ('Stifel',),
    'Bank of China International': ('Bank of China International', 'BOCI', '中银国际'),
    '中金公司': ('中金公司', 'CICC'),
    '中信证券': ('中信证券', 'CITIC Securities'),
    '华泰证券': ('华泰证券', 'Huatai'),
    '国泰海通': ('国泰海通', '国泰君安', '海通证券', 'Guotai Haitong', 'Guotai Junan', 'Haitong Securities'),
    '招商证券': ('招商证券',),
    '广发证券': ('广发证券',),
    '申万宏源': ('申万宏源',),
    '中信建投': ('中信建投',),
    '兴业证券': ('兴业证券',),
    '东方证券': ('东方证券',),
    '国信证券': ('国信证券',),
    '光大证券': ('光大证券',),
    '东吴证券': ('东吴证券',),
    '天风证券': ('天风证券',),
    '浙商证券': ('浙商证券',),
    '长江证券': ('长江证券',),
    '民生证券': ('民生证券',),
    '开源证券': ('开源证券',),
    '国盛证券': ('国盛证券',),
    '华创证券': ('华创证券',),
    '方正证券': ('方正证券',),
    '国投证券': ('安信证券', '安信', '国投证券'),
    '国金证券': ('国金证券',),
    '中泰证券': ('中泰证券',),
    '华西证券': ('华西证券',),
    '浦银国际': ('浦银国际',),
})

EXCLUDED_BANKS = {'BofA': 'redistribution watermark naming another recipient + stale document dates on every evidence pull, 2026-10-04'}

# Persona -> (listing query, screening description, fallback keywords)
THEMES = {
    'macro_rates_en': ('Federal Reserve rates inflation payrolls outlook', 'US/global macro, rates, Fed, inflation, labour data, FX',
                       ('fed', 'rate', 'yield', 'treasur', 'inflation', 'cpi', 'payroll', 'gdp', 'recession', 'ecb', 'boj', 'dollar', 'fx', 'macro')),
    'macro_zh': ('Federal Reserve rates inflation payrolls outlook', '中文宏观：美联储、利率、通胀、就业、汇率、中国宏观',
                 ('fed', 'rate', 'yield', 'inflation', 'cpi', 'payroll', 'gdp', 'china', 'pboc', 'rmb', 'macro', 'dollar')),
    'industry_ai_capex': ('AI capex semiconductors hyperscaler data center memory', 'AI infrastructure, semiconductors, memory, hyperscaler capex',
                          ('ai', 'gpu', 'semiconductor', 'semis', 'dram', 'memory', 'hbm', 'capex', 'data center', 'cloud', 'nvidia', 'tsmc', 'tech')),
    'zh_us_stock_commentary': ('AI capex semiconductors hyperscaler data center memory', '中文美股/科技股：AI、半导体、大型科技公司财报',
                               ('ai', 'gpu', 'semiconductor', 'memory', 'dram', 'nvidia', 'apple', 'microsoft', 'tesla', 'earnings', 'tech')),
    'single_stock_deepdive_en': ('earnings results guidance first take', 'single-company earnings, guidance, filings',
                                 ('earnings', 'results', 'guidance', 'eps', 'first take', 'preview', 'beat', 'miss', 'quarter')),
    'trading_shortterm': ('positioning flows volatility options CTA', 'short-term market structure: options/derivatives positioning, dealer gamma, CTA/systematic flows, volatility; NOT macro outlooks or single-company notes',
                          ('flow', 'positioning', 'volatility', 'vix', 'option', 'cta', 'gamma', 'technical', 'squeeze')),
    'market_data_charts': ('monthly tracker exports survey data chart', 'cross-market data trackers and statistics worth a chart: breadth, sentiment surveys, flows, PMI/data releases with numbers; NOT single-company notes or narrative outlooks',
                           ('tracker', 'chart', 'data', 'monthly', 'exports', 'survey', 'pmi', 'statistics')),
    'investing_philosophy': ('strategy outlook asset allocation valuation long-term', 'long-horizon investing principles: asset allocation frameworks, valuation regimes, risk premia, behavioural lessons; NOT day-to-day market updates, single-company notes or data releases',
                             ('strategy', 'allocation', 'outlook', 'valuation', 'long-term', 'portfolio', 'equity risk premium')),
    'crypto_macro_en': ('bitcoin crypto stablecoin digital assets', 'crypto and digital assets with a macro angle',
                        ('bitcoin', 'crypto', 'stablecoin', 'digital asset', 'blockchain', 'ether', 'tokeni')),
    'crypto_macro_zh': ('bitcoin crypto stablecoin digital assets', '中文加密宏观：比特币、稳定币、数字资产',
                        ('bitcoin', 'crypto', 'stablecoin', 'digital asset', 'blockchain', 'ether', 'tokeni')),
}

# Query-specific source groups; retain beat descriptions and fallback keywords.
_SECOND = {
 'macro_rates_en': 'Treasury yields central banks FX economic outlook',
 'macro_zh': '宏观',
 'industry_ai_capex': 'GPU HBM cloud infrastructure power demand',
 'zh_us_stock_commentary': '半导体',
 'single_stock_deepdive_en': 'company quarterly revenue margins earnings guidance',
 'trading_shortterm': 'market technicals dealer gamma fund flows',
 'market_data_charts': 'market breadth sentiment PMI statistics',
 'investing_philosophy': 'portfolio risk equity strategy investment principles',
 'crypto_macro_en': 'digital asset regulation ETF flows tokenization',
 'crypto_macro_zh': '数字资产',
}
_ZH_KEYWORDS = {
 'macro_zh': ('宏观', '美联储', '美债', '利率', '通胀', '降息', '经济', '政策', '汇率', '国债'),
 'zh_us_stock_commentary': ('半导体', '人工智能', '算力', '美股', '财报', '科技', '芯片', '存储'),
 'crypto_macro_zh': ('数字资产', '比特币', '稳定币', '加密', '区块链', '代币'),
}
for _p, (_q, _description, _keywords) in list(THEMES.items()):
    _zh = _p in ('macro_zh', 'zh_us_stock_commentary', 'crypto_macro_zh')
    THEMES[_p] = ([(_q, ['realtime_research']),
                   (_SECOND[_p], ['chinese_research'] if _zh else ['realtime_research'])],
                  _description, _keywords + (_ZH_KEYWORDS[_p] if _zh else ()))

TARGETED_LIMIT = 10
TARGETED = {
    'investing_philosophy': [('long-term asset allocation outlook', ['realtime_research']),
                             ('equity strategy valuation risk premium', ['realtime_research'])],
    'trading_shortterm': [('equity derivatives volatility positioning', ['realtime_research']),
                          ('CTA systematic flows', ['realtime_research'])],
    'industry_ai_capex': [('semiconductors AI data center', ['realtime_research']),
                          ('hyperscaler capex memory', ['realtime_research'])],
    'zh_us_stock_commentary': [('美股', ['chinese_research']), ('人工智能', ['chinese_research'])],
}

# Narrow title signals; generic keywords still contribute to weak/two-hit matches.
SPECIFIC = {
    'macro_rates_en': ('fed', 'treasur', 'inflation', 'cpi', 'payroll', 'ecb', 'boj', 'fx'),
    'macro_zh': ('fed', 'inflation', 'cpi', 'payroll', 'pboc', 'rmb', '美联储', '美债', '通胀', '降息', '汇率', '国债'),
    'industry_ai_capex': ('gpu', 'semiconductor', 'semis', 'dram', 'hbm', 'capex', 'data center', 'nvidia', 'tsmc'),
    'zh_us_stock_commentary': ('gpu', 'semiconductor', 'dram', 'nvidia', 'apple', 'microsoft', 'tesla', '半导体', '人工智能', '算力', '美股', '芯片', '存储'),
    'single_stock_deepdive_en': ('earnings', 'guidance', 'eps', 'first take'),
    'trading_shortterm': ('positioning', 'volatility', 'vix', 'option', 'cta', 'gamma', 'squeeze'),
    'market_data_charts': ('tracker', 'exports', 'survey', 'pmi', 'statistics'),
    'investing_philosophy': ('allocation', 'valuation', 'long-term', 'portfolio', 'equity risk premium'),
    'crypto_macro_en': ('bitcoin', 'crypto', 'stablecoin', 'digital asset', 'blockchain', 'ether', 'tokeni'),
    'crypto_macro_zh': ('bitcoin', 'crypto', 'stablecoin', 'digital asset', 'blockchain', 'ether', 'tokeni', '数字资产', '比特币', '稳定币', '加密', '区块链', '代币'),
}

BOILERPLATE = re.compile(r'Reg AC|Disclosure Appendix|hereby certify|conflict of interest|single factor in making|'
                         r'not registered/qualified|FINRA|important disclosures|www\.\S+/research|'
                         r'does and seeks to do business|请务必阅读|敬请阅读|免责声明|重要声明|投资咨询证号|执业证书|分析师|联系人|数据来源', re.I)
CONTACT = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s()-]{7,}\d')
SENTENCE = re.compile(r'(?<=[.!?])\s+|(?<=[。！？；])\s*')
# Ratings / price targets are bank recommendations, not facts we may relay.
RATING = re.compile(r'Price Target|Price Objective|\bPO:|\bTP\b|target price|Maintain Rating|\bRating:|'
                    r'目标价|评级|买入|增持|减持|跑赢|跑输|推荐评级|\b(?:Overweight|Underweight|Outperform|Underperform)\b|Price \(\d', re.I)
RATING_TITLE = re.compile(r'\b(?:TP|PO|price target|target price)\b|;\s*(?:buy|sell|overweight|underweight)\b|\b(?:maintain|reiterate)\w*\s+(?:buy|sell|overweight|underweight|neutral)\b|\b(?:upgrade|downgrade|initiat\w*)\b.*\b(?:buy|sell|overweight|underweight|neutral)\b|'
                          r'目标价|评级|买入|增持|减持|跑赢|跑输|(?:raising|cutting|lowering) (?:TP|PO|target)', re.I)
WATERMARK = re.compile(r'Unauthori[sz]ed redistribution|intended for [\w.+-]+@|prepared for [\w.+-]+@', re.I)
DOC_DATE = re.compile(r'\b(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (20\d\d)\b')
MONTHS = {m: i for i, m in enumerate(('January February March April May June July August September October '
                                      'November December').split(), 1)}
STALE_DAYS = 21


class Unrecorded(LookupError):
    def __init__(self, tool, args):
        super().__init__(f'{tool} not recorded')
        self.tool, self.args = tool, args


def call_key(tool, args):
    return tool + ':' + hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class Points:
    """ReportGem MCP points (10,000 returned tokens = 1 point), read from mcp_usage."""

    def __init__(self, cap, per_call_estimate=0.6):
        self.cap, self.estimate, self.spent, self.stopped, self.calls = cap, per_call_estimate, 0.0, False, 0

    def allow(self):
        if self.spent + self.estimate > self.cap:
            self.stopped = True
        return not self.stopped

    def add(self, response):
        self.calls += 1
        self.spent += float(((response or {}).get('mcp_usage') or {}).get('points') or 0)


def _call(call, tool, args, budget, plan):
    if not budget.allow():
        return None
    try:
        response = call(tool, args)
    except Unrecorded:
        if plan is not None:
            plan.append({'tool': tool, 'args': args, 'key': call_key(tool, args)})
        return None
    budget.add(response)
    return response


def window_start(day):
    """Previous business day: realtime research lands same day or T+1; weekends roll back to Friday."""
    d = date.fromisoformat(day) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def listing_queries(personas, *, day, limit=6, targeted=(), date_from=None):
    seen, out = set(), []
    week = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    queries = [(query, False) for p in personas for query in THEMES[p][0]]
    queries.extend((query, True) for p in targeted for query in TARGETED[p])
    for (q, sources), is_targeted in queries:
        key = (q, tuple(sources))
        if key in seen:
            continue
        seen.add(key)
        # Targeted (thin-persona) queries look back a week and ask for more rows: their topics are not daily.
        lo = week if 'chinese_research' in sources else (date_from or (week if is_targeted else window_start(day)))
        out.append({'query': q, 'sources': sources, 'date_from': lo, 'date_to': day,
                    'limit': min(max(limit, TARGETED_LIMIT) if is_targeted else limit, 20)})
    return out


def bank_of(institution):
    low = (institution or '').casefold()
    for bank, aliases in BANKS.items():
        if any((re.search(r'(?<![a-z0-9])' + re.escape(a.casefold()) + r'(?![a-z0-9])', low) if a.isascii() else a in low) for a in aliases):
            return bank
    return None


def daily_listing(call, queries, *, day, budget, plan=None, report=None, date_from=None):
    foreign_lo = date_from or window_start(day)
    cn_lo = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    items, seen = [], {}
    excluded_seen = set()
    excluded_counts = {bank: 0 for bank in EXCLUDED_BANKS}
    if report is not None:
        report['excluded_banks'] = excluded_counts
    for args in queries:
        response = _call(call, 'search_research', args, budget, plan)
        for r in (response or {}).get('results') or []:
            bank = bank_of(r.get('institution'))
            key = (r.get('source_type'), r.get('source_id'))
            lo = args.get('date_from') or foreign_lo
            if r.get('source_type') == 'cn':
                lo = min(lo, cn_lo)
            if bank and lo <= (r.get('published_at') or '')[:10] <= day:
                if bank in EXCLUDED_BANKS:
                    if key not in excluded_seen:
                        excluded_counts[bank] += 1
                        excluded_seen.add(key)
                    continue
                if key in seen:
                    if args['query'] not in seen[key]['queries']:
                        seen[key]['queries'].append(args['query'])
                    continue
                row = {**r, 'bank': bank, 'query': args['query'], 'queries': [args['query']]}
                seen[key] = row
                items.append(row)
    return items


def _keyword_choice(item, persona):
    text = (item.get('title', '') + ' ' + (item.get('industry') or '')).lower()
    def matches(k, value):
        return bool(re.search((r'\b' if k.isascii() else '') + re.escape(k), value))
    title = item.get('title', '').lower()
    title_hits = {k for k in THEMES[persona][2] if matches(k, title)}
    if len(title_hits) >= 2 or title_hits.intersection(SPECIFIC[persona]):
        return 'strong'
    return 'weak' if any(matches(k, text) for k in THEMES[persona][2]) else 'none'


CRITERIA = {'strong': 'The report is squarely on this persona\'s beat and has concrete facts or a clear view worth a post today.',
            'weak': 'Related to the beat but tangential, too narrow, or mostly housekeeping.',
            'none': 'Off the beat for this persona.'}


def prescreen(items, personas, *, jev=None):
    scores = {'_method': {}, '_downgraded': {}}
    fallback_counts = {}
    rows = list({str(i['source_id']): i for i in items}.items())
    for p in personas:
        chosen, fallback_count, downgraded = {}, 0, 0
        for start in range(0, len(rows), 16):
            batch = rows[start:start + 16]
            questions = {f'r{sid}': {'type': 'choice', 'criteria': CRITERIA,
                'instructions': f'Persona beat: {THEMES[p][1]}. Broker report from {i["bank"]}, {i.get("published_at")}: "{i.get("title", "")[:220]}".'} for sid, i in batch}
            answers = None
            if jev is not None:
                for _attempt in range(2):
                    try:
                        result = jev.review({'task': 'broker research pre-screen', 'persona': p}, questions)
                        candidate = result.get('answers') or {}
                        if result.get('status') == 'completed' and all(
                                isinstance(candidate.get(q), dict) and candidate[q].get('choice') in CRITERIA for q in questions):
                            answers = candidate
                            break
                    except Exception:
                        pass
            if answers is None:
                fallback_count += len(batch)
            for sid, i in batch:
                if answers is None:
                    choice = _keyword_choice(i, p)
                else:
                    answer = answers['r' + sid]
                    choice = answer['choice']
                    confidence = answer.get('confidence')
                    if choice == 'strong' and not (isinstance(confidence, (int, float)) and confidence >= 0.7):
                        choice = 'weak'
                        downgraded += 1
                chosen[sid] = choice
        scores[p] = chosen
        scores['_downgraded'][p] = downgraded
        scores['_method'][p] = ('keyword' if jev is None or fallback_count and fallback_count == len(rows)
                                else 'mixed' if fallback_count else 'jev')
        fallback_counts[p] = fallback_count
    if any(fallback_counts.values()):
        scores['_method']['fallback_items'] = fallback_counts
        scores['_method']['jev_fallback'] = {p: bool(n) for p, n in fallback_counts.items()}
    return scores


ZH_PERSONAS = ('macro_zh', 'zh_us_stock_commentary', 'crypto_macro_zh')


def _order_key(sid, choice, persona, items):
    it = (items or {}).get(sid) or {}
    zh_item = it.get('source_type') == 'cn'
    lang_miss = zh_item != (persona in ZH_PERSONAS)
    no_excerpt = it.get('evidence_status') not in (None, 'matched_excerpt')
    return ({'strong': 0, 'weak': 1}[choice], lang_miss, no_excerpt, '' if not it else ''.join(chr(0x10FFFF - ord(c)) for c in it.get('published_at', '')), sid)


def select_top(scores, *, items=None, per_persona=3, max_total=30, exclude=()):
    """Round-robin over personas. Strong items first (language fit, excerpt-backed, newest);
    weak items only as a coverage pick for a persona with no strong item; English personas
    never get Chinese-language (cn) reports."""
    excluded = set(map(str, exclude))
    queues = {}
    for p, chosen in scores.items():
        if p.startswith('_'):
            continue
        ok = [(sid, c) for sid, c in chosen.items() if c in ('strong', 'weak') and sid not in excluded
              and not (items and p not in ZH_PERSONAS and (items.get(sid) or {}).get('source_type') == 'cn')]
        if any(c == 'strong' for _, c in ok):
            ok = [(sid, c) for sid, c in ok if c == 'strong']
        else:
            ok = ok[:]  # weak-only persona: one coverage pick below
        queues[p] = [sid for sid, c in sorted(ok, key=lambda x: _order_key(x[0], x[1], p, items))]
        if queues[p] and all(chosen[s] == 'weak' for s in queues[p]):
            queues[p] = queues[p][:1]
    out, used = [], set()
    for turn in range(per_persona):
        for p, queue in queues.items():
            if len(out) >= max_total:
                return out
            # A shared report may serve multiple personas in the coverage round.
            candidates = [sid for sid in queue if sid not in used]
            sid = candidates[0] if candidates else (queue[0] if turn == 0 and queue else None)
            if sid is not None:
                out.append((p, sid))
                used.add(sid)
                queue.remove(sid)
    return out


def source_id_for(bank):
    if not bank.isascii():
        return 'reportgem_cn_' + bank.encode().hex()
    return 'reportgem_' + re.sub(r'[^a-z0-9]+', '_', bank.lower()).strip('_')


def is_rating_call(item):
    return bool(RATING_TITLE.search(item.get('title') or ''))


def screen_evidence(item, evidence):
    """Flags that disqualify an item: a redistribution watermark naming another
    recipient (licence red flag) or a document date far older than the listing date."""
    flags = []
    texts = [p.get('matched_text') or p.get('text') or '' for p in (evidence or {}).get('passages') or []]
    if any(WATERMARK.search(t) for t in texts):
        flags.append('redistribution_watermark')
    listed = (item.get('published_at') or '')[:10]
    if listed and texts:
        m = DOC_DATE.search(texts[0])
        if m:
            doc = dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
            if (dt.date.fromisoformat(listed) - doc).days > STALE_DAYS:
                flags.append('stale_document')
    return flags


def clean_passage(text):
    text = CONTACT.sub(' ', text or '')
    text = re.sub(r'[“”„"]', "'", text)
    keep = [s.strip() for s in SENTENCE.split(text) if s.strip() and not BOILERPLATE.search(s) and not RATING.search(s)]
    joined = re.sub(r'(?<=[。！？；]) +', '', ' '.join(keep))
    return re.sub(r'[ \t]{2,}', ' ', joined).strip()


def to_source(item, evidence):
    if screen_evidence(item, evidence):
        return None
    passages = []
    for p in (evidence or {}).get('passages') or []:
        cleaned = clean_passage(p.get('matched_text') or p.get('text') or '')
        if len(cleaned) >= 60 and cleaned not in passages:
            passages.append(cleaned)
    if not passages:
        return None
    text = '\n\n'.join(passages)
    bank = item['bank']
    return {'id': f'reportgem-{item["source_type"]}-{item["source_id"]}', 'source_id': source_id_for(bank),
            'source_hash': hashlib.sha256(text.encode()).hexdigest(), 'original_text': text,
            'author_name': bank, 'publisher': bank, 'title': item.get('title'),
            'published_at': (item.get('published_at') or '') + 'T00:00:00Z', 'source_language': 'zh' if item['source_type'] == 'cn' else 'en',
            'source_version': 'reportgem-mcp-excerpt',
            'provenance': {'via': 'ReportGem MCP', 'reportgem_source_type': item['source_type'],
                           'reportgem_id': str(item['source_id']), 'url': item.get('url'),
                           'licence_basis': 'tier B by owner decision 2026-10-04; paraphrase + bank attribution only'}}


def projection(points):
    return {'daily_points': points, 'monthly_points_30d': points * 30,
            'pack_169': {'points': 400, 'days_covered': 400 / points if points else None},
            'pack_299': {'points': 1300, 'days_covered': 1300 / points if points else None},
            'recommendation': 'Upgrade to the ¥299/1300 pack' if points * 30 > 400 * 0.9 else 'The ¥169/400 pack covers the projection'}


def store_units(source, units, persona, *, store=None, jev=None):
    from live.content_store import ContentStore
    from live.jev_front import prescreen_units
    verdicts = prescreen_units(units, persona=persona, jev=jev) if jev is not None else {}
    kept = [u for u in units if verdicts.get(u['unit_id'], {}).get('verdict') != 'drop']
    result = (store or ContentStore()).add(source, kept, adapter='reportgem',
              personas={u['unit_id']: [persona] for u in kept}, prescreen=verdicts)
    return {**result, 'kept': len(kept), 'dropped': len(units) - len(kept),
            'verdict_counts': {v: sum(a['verdict'] == v for a in verdicts.values()) for v in ('keep', 'weak', 'drop')}}
