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
# Jev routes and tags units over these ten beats only (question count per unit is the Jev cost driver).
JEV_BEATS = dict(PERSONAS)
# Oct 7 (fd20): crypto sub-beats so the 14 crypto accounts read their own lanes instead of all sharing
# crypto_macro_*. Language-neutral (topic only). Tagged deterministically (live/beat_rules.py: keywords, plus
# the subscribing accounts' beat for account-scoped X posts); never sent to Jev.
SUB_BEATS = {
    'crypto_meme': 'Memecoins and launchpads: pump.fun, meme rotations, degen flows, new token launches',
    'crypto_perp': 'Crypto derivatives: perps, funding, open interest, liquidations, leverage, perp DEXs',
    'crypto_defi': 'DeFi: lending, DEXs, yields, TVL, restaking, stablecoin protocols, tokenomics',
    'crypto_airdrop': 'Airdrops and points programs: TGEs, farming, snapshots, claims, testnets',
    'crypto_onchain': 'On-chain data: whale and wallet flows, exchange flows, holder cohorts, MVRV/SOPR, ETF flows',
}
PERSONAS.update(SUB_BEATS)
# Jev beat IDs -> account IDs (live/accounts.json). Routing/prescreen speak Jev IDs; everything
# downstream (compose, view ledger, queues) speaks account IDs.
ACCOUNT_FOR_PERSONA = {
    'macro_rates_en': 'en_macro', 'macro_zh': 'zh_macro', 'industry_ai_capex': 'en_industry',
    'zh_us_stock_commentary': 'zh_industry', 'market_data_charts': 'market_data_charts',
    'investing_philosophy': 'investing_philosophy', 'trading_shortterm': 'trading_shortterm',
    'crypto_macro_zh': 'crypto_macro_zh', 'single_stock_deepdive_en': 'single_stock_deepdive_en',
    'crypto_macro_en': 'crypto_macro_en',
}
PERSONA_FOR_ACCOUNT = {a: p for p, a in ACCOUNT_FOR_PERSONA.items()}


def _fd20_beats():
    """Oct 7 (fd20): the 20 main accounts read units of existing beats (live/fd20_accounts.json retrieval_beats,
    primary first). Only accounts without their own beat are added; routing still speaks the 10 Jev beats."""
    import json
    from pathlib import Path
    try:
        rows = json.loads((Path(__file__).with_name('fd20_accounts.json')).read_text())['accounts']
    except (OSError, ValueError, KeyError):
        return {}
    # an account whose first beat is a crypto sub-beat maps to its first Jev beat (sub-beats are not Jev beats)
    out = {}
    for r in rows:
        jev = [b for b in r.get('retrieval_beats') or [] if b in JEV_BEATS]
        if jev and r['id'] not in PERSONA_FOR_ACCOUNT:
            out[r['id']] = jev[0]
    return out


PERSONA_FOR_ACCOUNT.update(_fd20_beats())


def account_for(jev_persona):
    """Account ID for a Jev beat ID ('none' or unknown -> None)."""
    return ACCOUNT_FOR_PERSONA.get(jev_persona)


def jev_persona_for(account_or_persona):
    """Jev beat ID for an account ID; a Jev ID passes through."""
    if account_or_persona in PERSONAS:
        return account_or_persona
    return PERSONA_FOR_ACCOUNT.get(account_or_persona, account_or_persona)


KEYWORDS = {
    'macro_rates_en': ('fed', 'fomc', 'treasury', 'yield', 'rates', 'inflation', 'cpi', 'payroll', 'unemployment', 'credit'),
    'industry_ai_capex': ('ai', 'semiconductor', 'chip', 'memory', 'hbm', 'dram', 'data center', 'capex', 'gpu', 'micron', 'nvidia'),
    'crypto_macro_en': ('bitcoin', 'crypto', 'stablecoin', 'ether', 'digital asset', 'etf flows'),
    'trading_shortterm': ('options', 'gamma', 'positioning', 'volatility', 'vix', 'cta', 'flows'),
    'single_stock_deepdive_en': ('earnings', 'guidance', 'quarter', '10-q', '8-k', 'revenue'),
    'market_data_charts': ('breadth', 'sentiment', 'chart', 'record', 'since'),
    'investing_philosophy': ('investor', 'patience', 'risk', 'compounding', 'letter'),
}
ROUTE_CRITERIA = {**{p: f'Best fit: {d}.' for p, d in JEV_BEATS.items()},
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
    except Exception as exc:
        from ml.budget import BudgetExceeded
        if isinstance(exc, BudgetExceeded):
            raise
        return None
    return result['answers'] if result.get('status') == 'completed' else None


def _resilient_ask(jev, state, questions, groups, stats=None, max_calls=None):
    """Retry each node once, then split whole items; stop at the call budget.

    A full binary retry tree is at most 4*n-2 calls. Tagging additionally
    caps the tree at 2*n+2; exhausted branches keep their rule fallback.
    """
    if jev is None:
        return {}
    remaining = max_calls if max_calls is not None else 4 * len(groups) - 2

    def count(key):
        if stats is not None:
            stats[key] = stats.get(key, 0) + 1

    def visit(part):
        nonlocal remaining
        subset = {qid: questions[qid] for group in part for qid in group}
        for attempt in range(2):
            if remaining <= 0:
                return {}
            remaining -= 1
            count('calls')
            if attempt:
                count('retried')
            answers = _ask(jev, state, subset)
            if answers and all(qid in answers for qid in subset):
                return answers
            count('failed_calls')
        if len(part) == 1 or remaining <= 0:
            return {}
        count('split')
        middle = len(part) // 2
        left = visit(part[:middle])
        right = visit(part[middle:])
        return {**left, **right}

    return visit(groups) if groups else {}


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
        answers = _resilient_ask(jev, {'task': 'source routing per persona'}, questions,
                                 [[qid] for qid in questions])
        for it in batch:
            a = (answers or {}).get(it['id'])
            if a:
                out[it['id']] = {'persona': a['choice'], 'confidence': a.get('confidence'), 'jev_fallback': False}
            else:
                out[it['id']] = {'persona': _keyword_persona(it.get('title', '') + ' ' + (it.get('snippet') or '')),
                                 'confidence': None, 'jev_fallback': True}
            out[it['id']]['account_id'] = account_for(out[it['id']]['persona'])
    return out


def prescreen_units(units, *, persona, jev=None):
    """persona: a Jev beat ID or an account ID (mapped via PERSONA_FOR_ACCOUNT)."""
    persona = jev_persona_for(persona)
    out = {}
    for batch in _batches(list(units)):
        questions = {u['unit_id']: {'type': 'choice', 'criteria': UNIT_CRITERIA,
                                    'instructions': f'Persona beat: {PERSONAS.get(persona, persona)}. Content unit ({u.get("kind")}): '
                                                    f'"{u.get("statement", "")[:400]}". Is it usable for this persona?'}
                     for u in batch}
        answers = _resilient_ask(jev, {'task': 'content unit pre-screen', 'persona': persona},
                                 questions, [[qid] for qid in questions])
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


def tag_posts(posts, *, jev=None, stats=None, questions_per_call=16):
    """Tag eight posts per batch; 8 questions separates type and hook calls.

    questions_per_call is 1..16. Stats accumulate across invocations.
    Each batch uses at most 2*len(batch)+2 calls, including retries/splits.
    """
    if type(questions_per_call) is not int or not 1 <= questions_per_call <= 16:
        raise ValueError('questions_per_call must be an integer from 1 to 16')
    posts = list(posts)
    if stats is not None:
        for key in ('calls', 'failed_calls', 'retried', 'split', 'fallback_posts'):
            stats.setdefault(key, 0)
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
        groups = [[f'{p["id"]}:post_type', f'{p["id"]}:hook'] for p in batch]
        state = {'task': 'donor post style tagging'}
        if questions_per_call == 16:
            answers = _resilient_ask(jev, state, questions, groups, stats, 2 * len(batch) + 2)
        else:
            answers = {}
            # Separate dimensions so a malformed hook cannot discard a type response.
            used = 0
            for dimension in ('post_type', 'hook'):
                for part in _batches(batch, questions_per_call):
                    single_groups = [[f'{p["id"]}:{dimension}'] for p in part]
                    local = {}
                    answers.update(_resilient_ask(jev, state, questions, single_groups, local,
                                                 2 * len(batch) + 2 - used))
                    used += local.get('calls', 0)
                    if stats is not None:
                        for key, value in local.items():
                            stats[key] = stats.get(key, 0) + value
        if not answers:
            continue
        for p in batch:
            a, h = answers.get(f'{p["id"]}:post_type'), answers.get(f'{p["id"]}:hook')
            if a and h:
                out[p['id']].update(post_type=a['choice'], hook=h['choice'], jev_fallback=False)
    if stats is not None:
        stats['fallback_posts'] += sum(t['jev_fallback'] for t in out.values())
    return out
