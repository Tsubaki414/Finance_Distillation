"""ReportGem daily pull: broker research as a CONTENT donor (licence tier B).

Decision (Fiona, 2026-10-04): with the paid ReportGem MCP, excerpts of the
major banks' research may be used as tier-B content: paraphrase only, the bank
named in the attribution frame, never ReportGem; no verbatim copying, charts or
target prices. (source_expansion.md had rated ReportGem D; this overrides it
for excerpts returned by the paid MCP and is recorded in source_licence.json.)

Flow: listing_queries (theme queries per persona over realtime research,
day window) -> daily_listing (filter major banks + window, dedup, points cap)
-> prescreen (one bounded Jev choice call per persona; keyword fallback)
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
    'trading_shortterm': ('positioning flows volatility options CTA', 'positioning, flows, volatility, options, short-term trading',
                          ('flow', 'positioning', 'volatility', 'vix', 'option', 'cta', 'gamma', 'technical', 'squeeze')),
    'market_data_charts': ('monthly tracker exports survey data chart', 'data trackers, charts, monthly statistics',
                           ('tracker', 'chart', 'data', 'monthly', 'exports', 'survey', 'pmi', 'statistics')),
    'investing_philosophy': ('strategy outlook asset allocation valuation long-term', 'strategy, asset allocation, valuation, long-term outlook',
                             ('strategy', 'allocation', 'outlook', 'valuation', 'long-term', 'portfolio', 'equity risk premium')),
    'crypto_macro_en': ('bitcoin crypto stablecoin digital assets', 'crypto and digital assets with a macro angle',
                        ('bitcoin', 'crypto', 'stablecoin', 'digital asset', 'blockchain', 'ether', 'tokeni')),
    'crypto_macro_zh': ('bitcoin crypto stablecoin digital assets', '中文加密宏观：比特币、稳定币、数字资产',
                        ('bitcoin', 'crypto', 'stablecoin', 'digital asset', 'blockchain', 'ether', 'tokeni')),
}

BOILERPLATE = re.compile(r'Reg AC|Disclosure Appendix|hereby certify|conflict of interest|single factor in making|'
                         r'not registered/qualified|FINRA|important disclosures|www\.\S+/research|'
                         r'does and seeks to do business', re.I)
CONTACT = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s()-]{7,}\d')
SENTENCE = re.compile(r'(?<=[.!?。])\s+')
# Ratings / price targets are bank recommendations, not facts we may relay.
RATING = re.compile(r'Price Target|Price Objective|\bPO:|\bTP\b|target price|Maintain Rating|\bRating:|'
                    r'\b(?:Overweight|Underweight|Outperform|Underperform)\b|Price \(\d', re.I)
RATING_TITLE = re.compile(r'\b(?:TP|PO|price target|target price)\b|\b(?:upgrade|downgrade|initiat\w*)\b.*\b(?:buy|sell|overweight|underweight|neutral)\b|'
                          r'(?:raising|cutting|lowering) (?:TP|PO|target)', re.I)
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

    def __init__(self, cap, per_call_estimate=1.0):
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


def listing_queries(personas, *, day, limit=6):
    seen, out = set(), []
    for p in personas:
        q = THEMES[p][0]
        if q in seen:
            continue
        seen.add(q)
        out.append({'query': q, 'sources': ['realtime_research'], 'date_from': window_start(day),
                    'date_to': day, 'limit': limit})
    return out


def bank_of(institution):
    low = (institution or '').casefold()
    for bank, aliases in BANKS.items():
        if any(a.casefold() in low for a in aliases if a.isascii()):
            return bank
    return None


def daily_listing(call, queries, *, day, budget, plan=None):
    lo = window_start(day)
    items, seen = [], set()
    for args in queries:
        response = _call(call, 'search_research', args, budget, plan)
        for r in (response or {}).get('results') or []:
            bank = bank_of(r.get('institution'))
            key = (r.get('source_type'), r.get('source_id'))
            if bank and lo <= (r.get('published_at') or '') <= day and key not in seen:
                seen.add(key)
                items.append({**r, 'bank': bank, 'query': args['query']})
    return items


def _keyword_choice(item, persona):
    text = (item.get('title', '') + ' ' + (item.get('industry') or '')).lower()
    hits = sum(1 for k in THEMES[persona][2] if re.search(r'\b' + re.escape(k), text))
    return 'strong' if hits >= 1 and any(re.search(r'\b' + re.escape(k), item.get('title', '').lower()) for k in THEMES[persona][2]) else ('weak' if hits else 'none')


CRITERIA = {'strong': 'The report is squarely on this persona\'s beat and has concrete facts or a clear view worth a post today.',
            'weak': 'Related to the beat but tangential, too narrow, or mostly housekeeping.',
            'none': 'Off the beat for this persona.'}


def prescreen(items, personas, *, jev=None):
    scores = {'_method': {}}
    for p in personas:
        by_id = {str(i['source_id']): i for i in items}
        result, chosen = None, None
        if jev is not None and items:
            questions = {f'r{sid}': {'type': 'choice', 'criteria': CRITERIA,
                                     'instructions': f'Persona beat: {THEMES[p][1]}. Broker report from {i["bank"]}, '
                                                     f'{i.get("published_at")}: "{i.get("title", "")[:220]}". '
                                                     'How good is it as today\'s content source for this persona?'}
                         for sid, i in list(by_id.items())[:16]}
            result = jev.review({'task': 'broker research pre-screen', 'persona': p}, questions)
            if result.get('status') == 'completed':
                chosen = {q[1:]: a['choice'] for q, a in result['answers'].items()}
        if chosen is None:
            chosen = {sid: _keyword_choice(i, p) for sid, i in by_id.items()}
            scores['_method'][p] = 'keyword'
        else:
            scores['_method'][p] = 'jev'
        scores[p] = chosen
    return scores


def select_top(scores, *, per_persona=1, max_total=6, exclude=()):
    out, used, excluded = [], set(), set(map(str, exclude))
    rank = {'strong': 0, 'weak': 1}
    for p, chosen in scores.items():
        if p.startswith('_'):
            continue
        picks = sorted((rank[c], sid) for sid, c in chosen.items()
                       if c in rank and sid not in used and sid not in excluded)
        for _, sid in picks[:per_persona]:
            out.append((p, sid))
            used.add(sid)
    return out[:max_total]


def source_id_for(bank):
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
    return re.sub(r'[ \t]{2,}', ' ', ' '.join(keep)).strip()


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
            'published_at': (item.get('published_at') or '') + 'T00:00:00Z', 'source_language': 'en',
            'source_version': 'reportgem-mcp-excerpt',
            'provenance': {'via': 'ReportGem MCP', 'reportgem_source_type': item['source_type'],
                           'reportgem_id': str(item['source_id']), 'url': item.get('url'),
                           'licence_basis': 'tier B by owner decision 2026-10-04; paraphrase + bank attribution only'}}
