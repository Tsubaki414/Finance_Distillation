"""Structural viral priors (Oct 8, Sirius borrow: hotspot item 4).

A prior is a post *structure* (not a topic) and how much more engagement it gets, measured on our own donor corpus:
for each donor, a post's engagement is views (likes when views are missing) divided by that donor's own median, so a
big account does not dominate. lift(f) = median over donors of median(norm. engagement | f) / median(... | not f),
per language, only donors with >= MIN_POSTS originals and >= MIN_SIDE posts on each side. This is an association in
donor data, not a causal effect, and no number here is invented: `scripts/build_viral_priors.py` writes
live/viral_priors.json (aggregates only, no post text) and records n_donors / n_posts per feature.

Use: a soft ranking signal for angle choice only (`angle_boost`). An angle whose structure the source can carry
(e.g. data_history -> then_vs_now when the source has a dated comparison) gets at most +-MAX_BOOST on its share in
the account's own angle mix; it never adds a fact, never changes the account's lenses and never picks a topic.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'live' / 'viral_priors.json'
MIN_POSTS, MIN_SIDE = 40, 8
MAX_BOOST = 0.15      # an angle's share moves by at most +-15%
K = 0.5               # boost = K * (lift - 1), averaged over the angle's supported features, then clipped

_NUM = r'(?:[$＄]\s?\d|\d[\d,.]*\s?(?:%|％|[kKmMbB]\b|万|亿|倍|x\b|美元|刀|bps?\b)|\d{3,})'
FEATURES = {
    # the first line carries a concrete number (a price, %, amount, count >= 100)
    'lead_number': lambda t: bool(re.search(_NUM, _first(t))),
    # a then-vs-now / dated comparison with at least two numbers
    'then_vs_now': lambda t: bool(re.search(
        r'a year ago|last year|years? ago|back in (?:19|20)\d\d|since (?:19|20)\d\d|compared (?:with|to)|\bvs\.?\b|versus|'
        r'from \S+ to \S+|一年前|去年|当年|那时|相比|对比|同比|上一次|上次|以来', t, re.I))
        and len(re.findall(_NUM, t)) >= 2,
    # names a concrete counterparty: an institution, exchange, regulator or listed company
    'named_counterparty': lambda t: bool(re.search(
        r'BlackRock|Fidelity|Robinhood|Tether|Circle|Coinbase|Binance|OKX|Bybit|Grayscale|MicroStrategy|Strategy Inc|'
        r'JPMorgan|Goldman|Morgan Stanley|Citadel|Vanguard|\bSEC\b|CFTC|\bFed\b|Treasury|Nvidia|Apple|Microsoft|Tesla|'
        r'Meta\b|Amazon|Google|TSMC|OpenAI|Anthropic|贝莱德|富达|币安|灰度|微策略|摩根|高盛|美联储|财政部|英伟达|苹果|'
        r'微软|特斯拉|台积电|证监会', t)),
    # opens with a question
    'question_lead': lambda t: bool(re.search(r'[?？]\s*$', _first(t))),
    # three or more list lines
    'list_format': lambda t: len(re.findall(r'(?m)^\s*(?:[-•·▪*→✅❌🔹🔸]|\d{1,2}[.)、])\s*\S', t)) >= 3,
}
# which structures an angle naturally carries (only these can move that angle)
ANGLE_FEATURES = {
    'data_history': ('then_vs_now', 'lead_number'), 'cycle_position': ('then_vs_now',),
    'flows_etf': ('named_counterparty', 'lead_number'), 'regulation_institutional': ('named_counterparty',),
    'stablecoin_rwa': ('named_counterparty',), 'supply_chain_capacity': ('named_counterparty',),
    'fundamentals_valuation': ('lead_number', 'named_counterparty'), 'onchain_holders': ('lead_number',),
    'derivatives_positioning': ('lead_number',), 'macro_liquidity': ('lead_number',),
    'price_structure': ('lead_number',), 'tokenomics_yield': ('lead_number',), 'contrarian_check': ('question_lead',),
    'narrative_sector': ('list_format',),
}


def _first(text):
    return next((ln.strip() for ln in str(text or '').splitlines() if ln.strip()), '')[:120]


def features_of(text):
    return {k for k, fn in FEATURES.items() if fn(str(text or ''))}


def _flag(v):
    return v is True or str(v).lower() == 'true'


def _engagement(post):
    for k in ('views', 'likes'):
        try:
            v = float(post.get(k) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            return v, k
    return None, None


def compute(posts_by_donor):
    """posts_by_donor: {handle: [post dicts with text / lang / views / likes / rt / reply]} -> priors dict."""
    per = {}   # (lang, feature) -> [donor ratios]
    used = {}
    for handle, posts in posts_by_donor.items():
        rows = []
        for p in posts:
            if not p.get('text') or _flag(p.get('rt')) or _flag(p.get('reply')) or _flag(p.get('pinned')):
                continue
            eng, _kind = _engagement(p)
            if eng is None:
                continue
            lang = 'zh' if re.search(r'[一-鿿]', p['text']) else 'en'
            rows.append((lang, eng, features_of(p['text'])))
        for lang in ('zh', 'en'):
            mine = [r for r in rows if r[0] == lang]
            if len(mine) < MIN_POSTS:
                continue
            med = statistics.median(r[1] for r in mine) or 1.0
            for f in FEATURES:
                yes = [r[1] / med for r in mine if f in r[2]]
                no = [r[1] / med for r in mine if f not in r[2]]
                if len(yes) < MIN_SIDE or len(no) < MIN_SIDE:
                    continue
                base = statistics.median(no)
                if base <= 0:
                    continue
                per.setdefault((lang, f), []).append(statistics.median(yes) / base)
                used.setdefault((lang, f), [0, 0])
                used[(lang, f)][0] += 1
                used[(lang, f)][1] += len(yes)
    out = {}
    for (lang, f), ratios in sorted(per.items()):
        out.setdefault(lang, {})[f] = {'lift': round(statistics.median(ratios), 3), 'n_donors': used[(lang, f)][0],
                                       'n_posts_with': used[(lang, f)][1],
                                       'iqr': [round(q, 3) for q in statistics.quantiles(ratios, n=4)[::2]]
                                       if len(ratios) >= 4 else None}
    return out


def load(path=None):
    try:
        return json.loads(Path(path or PATH).read_text())
    except (OSError, ValueError):
        return {}


def source_supports(text, n_numbers=0):
    """Structures the material can carry honestly: lead_number needs numbers, then_vs_now a dated comparison."""
    have = features_of(text)
    if n_numbers >= 1 or re.search(_NUM, str(text or '')):
        have.add('lead_number')
    return have


def angle_boost(lang, source_text, priors=None, n_numbers=0):
    """{angle: multiplier in [1-MAX_BOOST, 1+MAX_BOOST]} for angles whose structure this source supports."""
    priors = (priors if priors is not None else load()).get('priors', {}).get(lang) or {}
    if not priors:
        return {}
    have = source_supports(source_text, n_numbers)
    out = {}
    for angle, feats in ANGLE_FEATURES.items():
        lifts = [priors[f]['lift'] for f in feats if f in have and f in priors]
        if lifts:
            b = K * (sum(lifts) / len(lifts) - 1)
            out[angle] = round(1 + max(-MAX_BOOST, min(MAX_BOOST, b)), 4)
    return out
