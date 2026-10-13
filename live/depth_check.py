"""Analysis depth (Oct 13, Fiona). FD_DEPTH_CHECK=0 disables both parts (default on).

Prompt (Fiona clarification): depth comes from the SOURCE's own analysis (reasoning, comparisons, implications),
kept and credited by the attribution frame, translate-and-light-edit; the model never invents insights.
Post-check (no model call): a news / original draft whose body carries none of those moves is a pure relay and is
HELD (needs_review, hold_reason 'depth: ...'). Archive / 回看 rows (their then-vs-now is the comparison) are exempt.
Deterministic marker lists, deliberately broad: it catches bare relays, not weak analysis."""
from __future__ import annotations

import os
import re

CODE = 'depth'
PROMPT = ('Depth (HARD): carry at least one of the SOURCE\'s own insights from the units - its reasoning, its '
          'comparison to a prior event, who it says is affected, or what it says to watch - translated and lightly '
          'edited, not just the headline. Never invent an insight, figure, date or precedent the units lack; if the '
          'units hold only a headline, say only what they support.')


def is_headline_source(pick):
    """Flash / headline-only sources (7x24 flashes, lane flashes): ranked after analysis sources."""
    sid = str(pick.get('source_id') or '')
    return sid.startswith(('lf-', 'flash', 'fl-')) or 'flash' in sid.lower()[:20]


MARKERS = {
    'en': re.compile(r"\b(?:last time|previous(?:ly)?|prior|compared|versus|vs\.?|unlike|like in|since|again|"
                     r"watch|next|until|unless|if\b|once\b|when\b|depends|the test|the tell|key level|"
                     r"means|for (?:holders|traders|borrowers|lenders|users|savers|investors|LPs|miners|issuers)|"
                     r"who (?:pays|wins|loses|gets)|squeez|pressure on|exposed|at risk|hurts?|benefits?)\b", re.I),
    'zh': re.compile(r'上次|此前|之前|以往|历史上|相比|对比|同比|环比|不同于|和.{0,8}一样|又一次|再次|'
                     r'关注|盯着|接下来|下一步|如果|一旦|除非|取决于|关键在|意味着|对.{0,12}(?:来说|而言)|'
                     r'受影响|受益|承压|吃亏|买单|风险在|压力'),
}


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_DEPTH_CHECK', '1') != '0'


def prompt_rule(env=None):
    return ('\n' + PROMPT) if enabled(env) else ''


def findings(body, lang, post_kind=None, env=None):
    """[] when the body shows depth (or check off / archive row); else one finding dict."""
    if not enabled(env) or not (body or '').strip():
        return []
    if post_kind in ('archive_lookback', 'anniversary') or re.match(r'^\s*(?:回看|Look back)', body, re.I):
        return []
    rx = MARKERS['zh' if str(lang)[:2] == 'zh' else 'en']
    if rx.search(body):
        return []
    return [{'code': CODE, 'severity': 'hard',
             'detail': 'pure news relay: no comparison, affected party or what-to-watch beyond the source'}]
