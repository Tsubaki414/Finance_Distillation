"""Oct 12 (Fiona, approved): explainer / tutorial / practical-checklist post type (机制拆解 / 怎么做 / 工具清单).

Why: the like-type audit (/workspace/x/audit1012/like_types.md) found 65% of our posts were single-line judgment_take,
while top-decile zh donor posts skew long (200+ chars, lift 1.34) and en DeFi / on-chain explainers over-index
(lift 2.15-3.43). This module turns part of the standalone judgment picks into explainers:

  * zh accounts: about one explainer a day each (EXPLAINER_PER_DAY), always in the account's own lane (the pick is one
    of the account's own lane-checked standalone picks - nothing here changes topic selection);
  * en accounts: only where their donors post this kind of thing (donor explainer share >= EN_MIN_SHARE, built by
    scripts/build_explainer_share.py into live/personas/posting_habits/explainer_share.json);
  * zh body >= 200 characters with numbered steps and concrete numbers from the units only (official docs,
    DefiLlama, project docs, ingested material) - never an invented first-hand claim (亲测 / 我试了 / "I tried");
  * it only replaces a standalone pick in a judgment / short format (never an engagement reply / quote, human kind,
    archive row or look-back pick) that carries >= MIN_NUMBERS numbers; data packets (DefiLlama / flash numbers) are
    the best grounding and are allowed (compose then applies the explainer format to the data_take too).

Freshness (explicit): an explainer gets NO exemption from live/fresh_hold.py. It is built on a fresh pick (passed the pool fresh_gate,
not a FD_FRESH_LOOKBACK look-back) and its row is a normal news / original row for fresh_hold (post_type stays the
pick's judgment type, no archive id / kind), so the 48 h source-age HOLD applies. The evergreen part (how the
mechanism works) is tied to today's hook in line 1; the rule also forbids news framing (刚刚 / 突发 / "just in") for
the evergreen steps. An explainer with no current hook is not produced by this path at all.

Kill switch: FD_EXPLAINER=0 (default on) restores the old behaviour exactly.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARE = ROOT / 'live' / 'personas' / 'posting_habits' / 'explainer_share.json'

EXPLAINER_PER_DAY = 1
EN_MIN_SHARE = 0.04      # en: donors post explainers in >= 4% of their originals
MIN_NUMBERS = 2          # concrete numbers needed in the packet
LENGTH = {'zh': {'min': 200, 'max': 420}, 'en': {'min': 280, 'max': 900}}
# format types an explainer may replace (single-line / short judgment formats and long takes); data formats stay
REPLACEABLE = {'one_liner', 'quick_take', 'long_take', 'question', 'news_flash', 'chart_caption'}

_NUM_LINE = re.compile(r'^\s*(?:\d{1,2}\s*[.)、/）]|[①②③④⑤⑥⑦⑧⑨]|第[一二三四五六七八九]|[-•▪]\s)', re.M)
_KW = {
    'zh': re.compile(r'怎么|如何|步骤|教程|清单|攻略|原理|机制|拆解|方法|指南|新手|入门|科普|一文|详解|手把手|流程|操作'),
    'en': re.compile(r"\bhow to\b|here'?s how|\bstep\b|\bsteps\b|\bguide\b|checklist|explained|explainer|\bprimer\b|"
                     r"breakdown|\bhow (?:it|this|they) works\b|walkthrough|tutorial|🧵|\b1/\s", re.I),
}


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_EXPLAINER', '1') != '0'


def is_explainer_text(text, lang):
    """Donor classifier: a numbered / bulleted list of >= 3 items, or >= 2 items plus an explainer keyword."""
    t = str(text or '')
    items = len(_NUM_LINE.findall(t))
    kw = bool(_KW['zh' if lang == 'zh' else 'en'].search(t))
    long_enough = len(re.sub(r'\s+', '', t)) >= (120 if lang == 'zh' else 200)
    return bool(long_enough and (items >= 3 or (items >= 2 and kw)))


_SHARE_CACHE = {}


def donor_share(account):
    if 'd' not in _SHARE_CACHE:
        try:
            _SHARE_CACHE['d'] = json.loads(SHARE.read_text()).get('accounts') or {}
        except (OSError, ValueError):
            _SHARE_CACHE['d'] = {}
    return float((_SHARE_CACHE['d'].get(account) or {}).get('share') or 0.0)


def account_allowed(account, lang, day=None):
    """zh: always (about one a day). en: donors must post explainers (share >= EN_MIN_SHARE); the day is then drawn
    with probability min(1, 7 x share) so an en account's explainer rate follows its donors (defi ~daily, perp ~2-3
    a week). Deterministic per (account, day)."""
    if str(lang)[:2] == 'zh':
        return True
    share = donor_share(account)
    if share < EN_MIN_SHARE:
        return False
    if day is None:
        return True
    import hashlib
    u = int(hashlib.sha1(f'{account}|{day}|explainer'.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return u < min(1.0, 7 * share)


def pick_ok(p):
    """A pick that can become an explainer: fresh standalone judgment pick with concrete numbers."""
    if p.get('kind') or p.get('slot') or p.get('lookback_frame'):
        return False
    if p.get('engagement') or str(p.get('source_id') or '').startswith(('x-', 'arc', 'evg')):
        return False
    # no extra 30 h 'timely' cut: the pick already passed the pool fresh_gate and the row still meets fresh_hold (48 h)
    return int(p.get('numbers') or 0) >= MIN_NUMBERS


def done_today(account, rows, day_s):
    return sum(1 for r in rows or () if r.get('account_id') == account and str(r.get('day')) == day_s
               and ((r.get('post_format') or {}).get('explainer') or r.get('explainer'))
               and not r.get('held'))


def post_format(lang, base=None):
    """post_format for an explainer pick: long_take form, explainer length band, own HARD rule, no nat3 re-sample."""
    lg = 'zh' if str(lang)[:2] == 'zh' else 'en'
    out = {'type': 'long_take', 'length': 'long', 'thread_parts': None,
           'shapes': ['thesis_mechanism'], 'length_target': dict(LENGTH[lg])}
    out.update(explainer=True, no_nat=True)
    return out


RULE = {
    'en': ('KIND explainer (how it works / how to / practical checklist), HARD: line 1 names today\'s event from the '
           'units in a few words and says what this post makes clear (no question, no "BREAKING"). Then 3-5 numbered '
           'steps ("1." "2." ...), each carrying a concrete number, name, threshold or mechanism step taken ONLY from '
           'the units (official docs, DefiLlama, project docs, ingested reports). Last line: one short landing line on '
           'what to watch or what it means. The evergreen part (how the mechanism works) is not news: no "just in" / '
           '"breaking" framing for it. Never invent first-hand experience ("I tried", "I tested", "I used", a friend '
           'told me), trades, positions or P&L. No buy / sell instruction. Stay in the account\'s lane.'),
    'zh': ('类型 explainer（机制拆解 / 怎么做 / 工具清单），硬性要求：第一行用几个字点出 units 里今天这件事，并说清这条要讲明白什么'
           '（不用问句开头，不写「突发」）。接着 3-5 条编号步骤（1. 2. 3.），每条都要带 units 里的具体数字、名称、门槛或机制环节'
           '（只用官方文档、DefiLlama、项目文档、已收录材料里的事实）。最后一行一句落点：接下来盯什么或这意味着什么。'
           '正文至少 200 字。机制本身是常青内容，别写成新闻（不写「刚刚」「突发」）。绝不编造第一手经历（亲测、我试了、我用过、'
           '朋友说），不写自己买卖、仓位、盈亏，不给买卖指令。不要用「我看」「我觉得」开头，也不要用「DefiLlama：」「（来源：X）」'
           '这种来源标签开头。只写本账号赛道内的内容。'),
}


def rule(lang):
    return RULE['zh' if str(lang)[:2] == 'zh' else 'en']


def body_findings(body, lang, fmt):
    """SOFT checks on an explainer body: length, numbered steps, numbers (for review + measurement)."""
    if not (fmt or {}).get('explainer'):
        return []
    b = str(body or '')
    out = []
    n_chars = len(re.sub(r'\s+', '', b))
    lg = 'zh' if str(lang)[:2] == 'zh' else 'en'
    if n_chars < LENGTH[lg]['min']:
        out.append({'code': 'explainer_too_short', 'level': 'soft', 'detail': f'{n_chars} chars'})
    if len(re.findall(r'^\s*\d{1,2}\s*[.)、）]', b, re.M)) < 2:
        out.append({'code': 'explainer_no_steps', 'level': 'soft', 'detail': 'fewer than 2 numbered steps'})
    if len(re.findall(r'\d+(?:[.,]\d+)?', b)) < 2:
        out.append({'code': 'explainer_no_numbers', 'level': 'soft', 'detail': 'fewer than 2 numbers'})
    return out
