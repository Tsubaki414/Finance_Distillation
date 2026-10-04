"""Narrow Jev judgments for the pipeline front end (advisory; nothing here publishes).

- route_sources: which persona (or none) an incoming source item belongs to (J2/J3-style).
- prescreen_units: keep / weak / drop for content units against one persona's beat.
- tag_posts: donor-post post_type and hook (style stats); structure / data usage are deterministic.

Bounded choice questions only (live/jev_review_client.py, <=16 per call). Any
Jev failure falls back to a rule and records jev_fallback=True (task card rule 5).
"""
from __future__ import annotations

import re

PERSONAS = {
    'macro_rates_en': 'English macro: Fed, rates, Treasuries, credit spreads, inflation, jobs data',
    'macro_zh': 'Chinese-language macro: Fed, US data, China data, global liquidity',
    'industry_ai_capex': 'English AI infrastructure: semiconductors, memory, data centers, power, hyperscaler capex',
    'zh_us_stock_commentary': 'Chinese-language US stocks and AI industry news explained',
    'market_data_charts': 'English market data: breadth, sentiment, flows, historical comparisons',
    'investing_philosophy': 'English investing philosophy: risk, behaviour, long-term principles',
    'trading_shortterm': 'English short-term market structure: options positioning, dealer hedging, flows, technicals',
    'crypto_macro_zh': 'Chinese-language crypto with a macro angle: bitcoin, stablecoins, regulation',
    'single_stock_deepdive_en': 'English single-company earnings and filings first takes',
    'crypto_macro_en': 'English crypto with a macro angle: bitcoin, stablecoins, regulation, on-chain data',
}
KEYWORDS = {
    'macro_rates_en': ('fed', 'fomc', 'treasury', 'yield', 'rates', 'inflation', 'cpi', 'payroll', 'unemployment', 'credit'),
    'industry_ai_capex': ('ai', 'semiconductor', 'chip', 'memory', 'hbm', 'dram', 'data center', 'capex', 'gpu', 'micron', 'nvidia'),
    'crypto_macro_en': ('bitcoin', 'crypto', 'stablecoin', 'ether', 'digital asset', 'etf flows'),
    'trading_shortterm': ('options', 'gamma', 'positioning', 'volatility', 'vix', 'cta', 'flows'),
    'single_stock_deepdive_en': ('earnings', 'guidance', 'quarter', '10-q', '8-k', 'revenue'),
    'market_data_charts': ('breadth', 'sentiment', 'chart', 'record', 'since'),
    'investing_philosophy': ('investor', 'patience', 'risk', 'compounding', 'letter'),
}
ROUTE_CRITERIA = {**{p: f'Best fit: {d}.' for p, d in PERSONAS.items()},
                  'none': 'Fits no persona beat, or is housekeeping / promotion / off-topic.'}
UNIT_CRITERIA = {'keep': 'Concrete, self-contained, on this beat, worth using as a fact or view in a post.',
                 'weak': 'On the beat but vague, generic, or needs other context to be useful.',
                 'drop': 'Boilerplate, disclosure, housekeeping, promotion, a rating/price target, or off the beat.'}
POST_TYPE_CRITERIA = {'data_take': 'Built around one or more numbers / data points and what they mean.',
                      'mechanism_explainer': 'Explains how or why something works (a causal chain), usually longer.',
                      'view_relay': 'Relays or reacts to someone else\'s view, report, quote or news.',
                      'earnings_take': 'About a company\'s results, guidance or filing.',
                      'hot_take': 'A short opinion, joke or reaction without data or explanation.'}
HOOK_CRITERIA = {'data_point': 'Opens with a number or data point.', 'bold_claim': 'Opens with a short assertion or contrarian claim.',
                 'question': 'Opens with a question.', 'news_peg': 'Opens with a news event or headline.',
                 'story': 'Opens with a personal story or anecdote.', 'list': 'Opens with a list / numbered thread marker.',
                 'quote': 'Opens by quoting someone.'}
NUMBER = re.compile(r'[$€£¥]?\d[\d,.]*\s?(?:%|bp|bps|k|m|bn|b|x|万|亿|倍)?', re.I)


def _batches(items, size=16):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _ask(jev, state, questions):
    if jev is None:
        return None
    try:
        result = jev.review(state, questions)
    except Exception:
        return None
    return result['answers'] if result.get('status') == 'completed' else None


def _keyword_persona(text):
    text = text.lower()
    zh = bool(re.search(r'[\u4e00-\u9fff]', text))
    best, hits = 'none', 0
    for p, words in KEYWORDS.items():
        n = sum(1 for w in words if re.search(r'(?<![a-z])' + re.escape(w), text))
        if n > hits:
            best, hits = p, n
    if zh and best in ('macro_rates_en', 'crypto_macro_en', 'industry_ai_capex'):
        best = {'macro_rates_en': 'macro_zh', 'crypto_macro_en': 'crypto_macro_zh',
                'industry_ai_capex': 'zh_us_stock_commentary'}[best]
    return best


def route_sources(items, *, jev=None):
    """items: [{'id','title','publisher','snippet'}] -> {id: {'persona', 'confidence', 'jev_fallback'}}"""
    out = {}
    for batch in _batches(list(items)):
        questions = {it['id']: {'type': 'choice', 'criteria': ROUTE_CRITERIA,
                                'instructions': f'Incoming source from {it.get("publisher", "")}: "{it.get("title", "")[:200]}". '
                                                f'{(it.get("snippet") or "")[:400]} Which persona beat does it belong to?'}
                     for it in batch}
        answers = _ask(jev, {'task': 'source routing per persona'}, questions)
        for it in batch:
            a = (answers or {}).get(it['id'])
            if a:
                out[it['id']] = {'persona': a['choice'], 'confidence': a.get('confidence'), 'jev_fallback': False}
            else:
                out[it['id']] = {'persona': _keyword_persona(it.get('title', '') + ' ' + (it.get('snippet') or '')),
                                 'confidence': None, 'jev_fallback': True}
    return out


def prescreen_units(units, *, persona, jev=None):
    out = {}
    for batch in _batches(list(units)):
        questions = {u['unit_id']: {'type': 'choice', 'criteria': UNIT_CRITERIA,
                                    'instructions': f'Persona beat: {PERSONAS.get(persona, persona)}. Content unit ({u.get("kind")}): '
                                                    f'"{u.get("statement", "")[:400]}". Is it usable for this persona?'}
                     for u in batch}
        answers = _ask(jev, {'task': 'content unit pre-screen', 'persona': persona}, questions)
        for u in batch:
            a = (answers or {}).get(u['unit_id'])
            out[u['unit_id']] = ({'verdict': a['choice'], 'jev_fallback': False, 'confidence': a.get('confidence')} if a
                                 else {'verdict': 'keep', 'jev_fallback': True, 'confidence': None})
    return out


def structure(text):
    lines = [l for l in text.splitlines() if l.strip()]
    return {'chars': len(text), 'lines': len(lines),
            'list': sum(1 for l in lines if re.match(r'\s*(?:[-•·▪️✅👉]|\d+[.)、]|[①-⑩])', l)) >= 2,
            'thread_marker': bool(re.search(r'(?:^|\s)\d+/\d*(?:\s|$)|🧵|thread', text, re.I)),
            'question_open': bool(re.match(r'[^\n]{0,120}[?？]', text)),
            'has_link': 'http' in text}


def _rule_post_type(text, numbers):
    if len(text) > 500:
        return 'mechanism_explainer'
    if re.search(r'earnings|guidance|revenue|EPS|财报|营收|指引', text, re.I) and numbers >= 2:
        return 'earnings_take'
    if numbers >= 3:
        return 'data_take'
    if re.search(r'@\w+|according to|says|认为|表示', text, re.I):
        return 'view_relay'
    return 'hot_take'


def tag_posts(posts, *, jev=None):
    out = {}
    for p in posts:
        text = p.get('text') or ''
        nums = len([m for m in NUMBER.findall(text) if re.search(r'\d', m)])
        out[p['id']] = {'numbers': nums, 'structure': structure(text), 'post_type': _rule_post_type(text, nums),
                        'hook': None, 'jev_fallback': True}
    for batch in _batches(list(posts), size=8):
        questions = {}
        for p in batch:
            t = (p.get('text') or '')[:700]
            questions[f'{p["id"]}:post_type'] = {'type': 'choice', 'criteria': POST_TYPE_CRITERIA,
                                                 'instructions': f'Finance post: "{t}". Which post type is it?'}
            questions[f'{p["id"]}:hook'] = {'type': 'choice', 'criteria': HOOK_CRITERIA,
                                            'instructions': f'Finance post: "{t[:300]}". How does its first sentence hook the reader?'}
        answers = _ask(jev, {'task': 'donor post style tagging'}, questions)
        if not answers:
            continue
        for p in batch:
            a, h = answers.get(f'{p["id"]}:post_type'), answers.get(f'{p["id"]}:hook')
            if a and h:
                out[p['id']].update(post_type=a['choice'], hook=h['choice'], jev_fallback=False)
    return out
