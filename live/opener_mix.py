"""Oct 12 (Fiona, approved): opener quotas by language + opener bans + invented first-hand HARD check.

  * zh accounts: about 15-20% of standalone drafts open with a question (QUESTION_SHARE_ZH, paced per run), assigned
    at plan time (post_format.opener = 'question') and passed to compose as an explicit per-post override of the
    "never open with a question" default.
  * zh stock openers banned: 我看 / 我觉得 and source-label openers (「DefiLlama：」「（来源：X）」「据X：」). Deterministic
    post-step strips them from line 1 (the attribution frame / credit line is untouched; only an opener label goes).
  * en macro accounts: a '🚨 / BREAKING' caps headline + one hard number is allowed only for genuinely fresh news
    (source < BREAKING_MAX_AGE_H at the slot), capped per account (1) and per day across those accounts
    (BREAKING_DAY_CAP). Any other draft that opens with 🚨 / BREAKING has the prefix stripped.
  * First-person story openers only for a real event / observation: invented life details, trades, P&L, tests or
    friend anecdotes are a HARD finding on every draft (not only human kinds) -> needs_review (HOLD).

Kill switch: FD_OPENER_MIX=0 (default on) - no assignment, no post-step, no extra HARD check.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone

QUESTION_SHARE_ZH = 0.18
BREAKING_MAX_AGE_H = 6.0
BREAKING_DAY_CAP = 3
EN_MACRO = frozenset({'crypto_macro_en', 'market_data_charts', 'investing_philosophy', 'single_stock_deepdive_en',
                      'en_macro', 'longterm_investing_en'})


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_OPENER_MIX', '1') != '0'


def _ts(v):
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def source_age_h(published_at, slot):
    a, b = _ts(published_at), _ts(slot) if not isinstance(slot, datetime) else slot
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 3600.0


class Planner:
    """Per-run opener assignment (one instance per select())."""

    def __init__(self):
        self.n = {'zh': 0}
        self.q = {'zh': 0}
        self.breaking_acct = set()
        self.breaking_n = 0

    def assign(self, account, lang, p, fmt, slot):
        """Opener directive for a standalone, non-human, non-explainer pick, or None."""
        if not enabled():
            return None
        lg = str(lang)[:2]
        if lg == 'zh':
            self.n['zh'] += 1
            if fmt.get('type') in ('question',):
                self.q['zh'] += 1
                return None
            if self.q['zh'] < int(QUESTION_SHARE_ZH * self.n['zh'] + 0.5):
                self.q['zh'] += 1
                return 'question'
            return None
        if account in EN_MACRO and account not in self.breaking_acct and self.breaking_n < BREAKING_DAY_CAP:
            age = source_age_h(p.get('published_at'), slot)
            if age is not None and 0 <= age < BREAKING_MAX_AGE_H and int(p.get('numbers') or 0) >= 1 \
                    and p.get('packet') != 'data':
                self.breaking_acct.add(account)
                self.breaking_n += 1
                return 'breaking'
        return None


RULE = {
    'question': ('opener: question (assigned for this post; overrides "never open with a question"): line 1 is ONE '
                 'short question about today\'s event that sets up the call; line 2 gives the call plainly. Not 我看 / '
                 '我觉得, not a source label.',
                 '开头：问句（本条指定，覆盖「不要用问句开头」的默认规则）：第一行是一个关于今天这件事的短问句，引出判断；'
                 '第二行直接给判断。不要用「我看」「我觉得」开头，不要用来源标签开头。'),
    'breaking': ('opener: breaking (assigned; the source is under 6 hours old): line 1 is a caps headline starting with '
                 '"🚨 " that states the news with ONE hard number from the units (e.g. "🚨 US 10Y YIELD HITS 5.3%."); '
                 'then 1-3 plain lines on why it matters. Only this post may use 🚨 / BREAKING.', ''),
}


def rule(opener, lang):
    r = RULE.get(opener)
    if not r:
        return None
    return r[1] if str(lang)[:2] == 'zh' and r[1] else r[0]


# ---------------------------------------------------------------- deterministic post-step
_ZH_STOCK = re.compile(r'^(?:我看(?![了过到见完着好空多])|我觉得)[，,：:\s]*')
_SRC_LABEL = re.compile(r'^(?:[（(](?:来源|参考|数据来源|source)[:：][^）)]{1,30}[）)]\s*|'
                        r'(?:据)?[A-Za-z][\w .&\-]{1,24}[：:]\s*|(?:据)?[\u4e00-\u9fff]{2,8}(?:数据|消息|报道|显示)?[：:]\s*)',
                        re.I)
_BREAKING = re.compile(r'^\s*(?:🚨+\s*)?(?:BREAKING(?:\s+NEWS)?\s*[:：\-–—]?\s*)?', re.I)
# a leading CJK label is only a source label when it names a data source / outlet (keep 「结论：」-style labels out)
_ZH_LABEL_OK = re.compile(r'DefiLlama|Glassnode|CoinGlass|CoinDesk|Coinbase|Binance|币安|彭博|路透|华尔街见闻|财联社|'
                          r'金十|链上|官方|数据|消息|报道|TechFlow|ChainCatcher|PANews|Odaily|律动|Bloomberg|Reuters', re.I)


def _strip_first(body, rx, guard=None):
    lines = str(body or '').split('\n')
    i = next((k for k, l in enumerate(lines) if l.strip()), None)
    if i is None:
        return body, None
    m = rx.match(lines[i].lstrip())
    if not m or not m.group(0).strip():
        return body, None
    if guard is not None and not guard(m.group(0)):
        return body, None
    rest = lines[i].lstrip()[m.end():].lstrip()
    if not rest and len(lines) == i + 1:
        return body, None
    if rest and re.match(r'[a-z]', rest):
        rest = rest[0].upper() + rest[1:]
    lines[i] = rest
    out = '\n'.join(lines)
    out = re.sub(r'^\s*\n', '', out)
    return out, m.group(0).strip()


_EN_FILLER = re.compile(r'^\s*(?:ngl|idk|tbh)\b[\s,.:;!\-–—]*', re.I)


def fix_opener(body, lang, opener=None, source_age=None):
    """(new_body, changes). zh: strip 我看/我觉得 + source-label openers. en: strip an unassigned or stale 🚨/BREAKING."""
    if not enabled() or not body:
        return body, []
    changes = []
    if str(lang)[:2] == 'zh':
        for _ in range(2):
            body2, cut = _strip_first(body, _SRC_LABEL, guard=lambda s: bool(_ZH_LABEL_OK.search(s)) or s.startswith(('（', '(')))
            if cut:
                body, _c = body2, changes.append(f'opener: source label {cut[:24]!r}')
                continue
            body2, cut = _strip_first(body, _ZH_STOCK)
            if cut:
                body, _c = body2, changes.append(f'opener: stock {cut!r}')
                continue
            break
    else:
        # Oct 13 (Fiona): ngl / idk / tbh filler openers are banned here, at the final EN opener step (humanize can
        # re-introduce them after nat_tex ran). Stripped deterministically; the next word is capitalised.
        m = _EN_FILLER.match(str(body))
        if m:
            rest = str(body)[m.end():]
            body = rest[:1].upper() + rest[1:]
            changes.append(f'opener: stripped filler {m.group(0).strip()!r}')
        first = next((l for l in str(body).split('\n') if l.strip()), '')
        if re.match(r'^\s*(?:🚨|BREAKING\b)', first, re.I):
            fresh = source_age is not None and source_age < BREAKING_MAX_AGE_H
            if opener != 'breaking' or not fresh:
                body2, cut = _strip_first(body, _BREAKING)
                if cut:
                    body = body2
                    changes.append(f'opener: stripped {cut!r} (assigned={opener}, age_h={source_age})')
        else:
            body2, cut = _strip_first(body, _SRC_LABEL, guard=lambda s: bool(_ZH_LABEL_OK.search(s)))
            if cut:
                body = body2
                changes.append(f'opener: source label {cut[:24]!r}')
    return body, changes


# ---------------------------------------------------------------- HARD: invented first-hand claims (all drafts)
FIRST_HAND = {
    'zh': re.compile(r'亲测|实测了|我(?:刚|今天|昨天|之前|上周)?(?:试了|试过|测了|用了一下|用过|玩了|撸了|刷了|领到|中签)|'
                     r'我(?:一个|有个|的)?朋友|朋友(?:跟我|告诉我|和我)说|我(?:刚|今天|昨天)?(?:买了|卖了|梭哈|加仓|减仓|清仓|建仓|'
                     r'开了?多|开了?空|止损|止盈|抄底了|上车了|下车了)|我的(?:仓位|持仓)|(?:我)?(?:赚了|亏了|浮盈|浮亏)\s*\d'),
    'en': re.compile(r"\bI (?:just )?(?:tried|tested|used it|played with|farmed|bought|sold|aped|longed|shorted|"
                     r"took profit|went long|went short)\b|\bmy (?:friend|buddy|mate|colleague|bag|bags|position|"
                     r"positions|entry|stack|portfolio|p&l|pnl)\b|\ba friend (?:of mine|told me)\b|\b(?:i'm|i am) "
                     r"(?:up|down) \$?\d|\bI (?:made|lost) \$?\d", re.I),
}


def first_hand_findings(body, lang):
    if not enabled():
        return []
    m = FIRST_HAND['zh' if str(lang)[:2] == 'zh' else 'en'].search(str(body or ''))
    return [{'code': 'invented_first_hand', 'level': 'hard',
             'detail': f'invented first-hand claim {m.group(0)!r} (Fiona hard rule: no invented tests / trades / '
                       'P&L / friend anecdotes)'}] if m else []


# ---------------------------------------------------------------- measurement
def opener_class(body, lang):
    """question / breaking / stock (我看/我觉得) / source_label / first_person / number / assertion."""
    first = next((l.strip() for l in str(body or '').split('\n') if l.strip()), '')
    if not first:
        return 'empty'
    if re.match(r'^(?:🚨|BREAKING\b)', first, re.I):
        return 'breaking'
    if str(lang)[:2] == 'zh':
        if _ZH_STOCK.match(first):
            return 'stock_wo_kan'
        m = _SRC_LABEL.match(first)
        if m and (_ZH_LABEL_OK.search(m.group(0)) or m.group(0).startswith(('（', '('))):
            return 'source_label'
        sent = re.split(r'[。！!；;]', first)[0]
        if re.search(r'[？?]', sent[:60]):
            return 'question'
        if re.match(r'^我(?!们)', first):
            return 'first_person'
        if re.match(r'^[\d$＄]', first):
            return 'number'
        return 'assertion'
    sent = re.split(r'(?<=[.!])\s', first)[0]
    if '?' in sent[:200]:
        return 'question'
    if re.match(r"^(?:I|I'm|I've|My)\b", first):
        return 'first_person'
    if re.match(r'^[\d$]', first):
        return 'number'
    return 'assertion'
