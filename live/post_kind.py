"""Per-account weekly post-kind mix + human post kinds + diary slot (Oct 11 account audit fix 3).

The audit: 99% of our drafts are a/b/c/h analysis kinds vs donors' 64%; 34/36 accounts had zero gossip / diary /
meme / question posts in 4 days (donors 28%). Targets per account (live/personas/posting_habits/account_mix.json weekly_14, the audit's
Appendix B: a 14-post week from the account's own donors):
  - data + news + opinion (a+b+c) share capped at the donor share + 15pp,
  - >= 2 human posts a week and at least the donor human share (d+e+f+g),
counted over the account's ready standalone drafts of the last 7 Beijing days plus today's plan. When a standalone
pick would break the targets it is written as a human kind that can use today's material without heavy data:
  reaction (e), question (g), industry_people (d), meme (f, meme lanes only), diary (e; diary-lane accounts get one
  extra daily diary slot, live/personas/posting_habits/account_mix.json diary_slot).
Diary / personal posts carry NO biographical facts - only feelings / reactions about real market events in the units or
about the account's own posting / chart-watching. No trades, positions, P&L, places, family, job, health (bio_findings
HARD). No persona life details (dropped for good 10-11).
FD_POST_KIND=0 turns the mix off; FD_DIARY_SLOT=0 the diary slot.
"""
from __future__ import annotations

import os
import re

from live import lane_allow

HUMAN = ('reaction', 'question', 'industry_people', 'meme', 'diary')
LETTER = {'industry_people': 'd', 'diary': 'e', 'reaction': 'e', 'meme': 'f', 'question': 'g'}
CAP_PP = 0.15
MIN_HUMAN_WEEK = 2


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_POST_KIND', '1') != '0'


def diary_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_DIARY_SLOT', '1') != '0' and enabled(env)


def is_diary_account(account):
    return bool(lane_allow.cfg(account).get('diary_slot'))


def targets(account):
    w = lane_allow.cfg(account).get('weekly_14') or {}
    n = max(1, sum(w.values()))
    human = sum(w.get(k, 0) for k in 'defg') / n
    return {'abc_cap': min(1.0, sum(w.get(k, 0) for k in 'abc') / n + CAP_PP), 'human_share': human,
            'weekly': w, 'n': n}


def row_kind(row):
    """Kind of an inbox row / plan pick: its 'kind' field, else a legacy guess (a data / b news / c take)."""
    k = row.get('kind') or (row.get('post_format') or {}).get('kind')
    if k:
        return k
    fmt = row.get('post_format') or {}
    t = fmt.get('type') if isinstance(fmt, dict) else fmt
    if (row.get('archive') or {}) or str(row.get('id') or '').startswith('arc'):
        return 'h'
    if t in ('list_dump', 'chart_caption'):
        return 'a'
    if t == 'news_flash':
        return 'b'
    body = str(row.get('body') or '')
    return 'a' if len(re.findall(r'\d[\d.,%]*', body)) >= 4 else 'c'


def is_human(kind):
    return kind in HUMAN or kind in ('d', 'e', 'f', 'g')


def week_counts(account, rows):
    """Counter-like dict of kinds over the account's ready standalone rows (engagement rows excluded)."""
    out = {}
    for r in rows:
        if r.get('account_id') != account:
            continue
        if (r.get('post_format') or {}).get('engage') in ('reply', 'quote') or r.get('post_mode') in ('reply', 'quote'):
            continue
        k = row_kind(r)
        out[k] = out.get(k, 0) + 1
    return out


def human_per_week(account):
    """Human posts a week for the account: the donor human share of ~7 standalone posts, 2..4."""
    import math
    t = targets(account)
    h = (t['weekly'].get('h', 0)) / t['n']
    need_for_cap = math.ceil(max(0.0, 1 - t['abc_cap'] - h) * 7 - 1e-9)   # keeps a+b+c <= donor share + 15pp
    return max(MIN_HUMAN_WEEK, min(4, max(round(t['human_share'] * 7), need_for_cap)))


def human_days(account):
    """The weekdays (date.toordinal() % 7) an account's human posts are spread over (stable per account)."""
    import hashlib
    k = human_per_week(account)
    off = int(hashlib.sha1(str(account).encode()).hexdigest()[:6], 16) % 7
    return {(off + round(i * 7 / k)) % 7 for i in range(k)}


def needs_human(account, counts, day=None):
    """True when the next standalone post should be a human kind: fewer human posts in the last 7 days than the
    account's weekly target (human_per_week: >= 2, the donor human share, enough to keep a+b+c <= donor + 15pp) and
    today is one of its spread-out human days (day=None: no spreading)."""
    if not enabled() or not lane_allow.cfg(account):
        return False
    human = sum(v for k, v in counts.items() if is_human(k))
    if human >= human_per_week(account):
        return False
    return day is None or day.toordinal() % 7 in human_days(account)


PEOPLE_RX = re.compile(r'\b(?:ceo|founder|co-?founder|cto|team|kol|influencer|said|says|told|tweeted|posted|'
                       r'interview|resign|fired|hired|feud|drama|accus|apolog|lawsuit|sued)\b|@\w+|创始人|团队|老板|'
                       r'表示|回应|喊话|发文|道歉|离职|互撕|吵|大V|KOL', re.I)


def choose_kind(account, counts, text='', numbers=0):
    """The human kind with the biggest deficit vs the donor weekly target that fits this material."""
    w = targets(account)['weekly']
    c = lane_allow.cfg(account)
    have = {L: sum(v for k, v in counts.items() if LETTER.get(k, k) == L) for L in 'defg'}
    total = max(1, sum(counts.values()) + 1)
    n = max(1, sum(w.values()))
    options = []
    for L in 'defg':
        deficit = w.get(L, 0) / n - have[L] / total
        options.append((deficit, w.get(L, 0), L))
    for _d, _w, L in sorted(options, reverse=True):
        if L == 'd':
            if PEOPLE_RX.search(str(text or '')):
                return 'industry_people'
            continue
        if L == 'f':
            if c.get('meme_lane'):
                return 'meme'
            continue
        if L == 'g':
            return 'question'
        if L == 'e':
            return 'diary' if (c.get('diary_slot') or w.get('e', 0) >= 3) and numbers < 6 else 'reaction'
    return 'reaction'


# ---------------------------------------------------------------- compose format + prompt rules
_FORMAT = {   # kind -> posting_habits type, compose_shapes shape, length target (zh, en) chars without whitespace
    'reaction': ('one_liner', 'reaction', (8, 60), (20, 140)),
    'meme': ('one_liner', 'reaction', (8, 60), (15, 140)),
    'question': ('question', 'question_only', (12, 80), (25, 180)),
    'industry_people': ('quick_take', 'take_short', (30, 140), (60, 300)),
    'diary': ('one_liner', 'reaction', (12, 80), (25, 200)),
}
NO_BIO_EN = ('Never invent anything about yourself: no trades, buys / sells, positions, entries, P&L, gains or losses, '
             'places, travel, family, job, health or purchases. Feelings and observations only.')
NO_BIO_ZH = '绝不编造自己的事：不写自己买卖、仓位、建仓、盈亏、去过哪里、家人、工作、身体、买了什么。只写感受和观察。'
RULES = {
    'reaction': ('KIND reaction (a feeling, not a take): 1-2 short lines that are mostly YOUR FEELING about one fact from '
                 'the units - surprise, eye-roll, relief, FOMO, boredom, "lol", "ngl", "welp", "bruh". Name the fact in a '
                 'few words only. At most one number. No "because" / "as" / "which means" clause, no analysis, no '
                 'forecast, no "watch X" closer, no moral. e.g. "ngl did not expect ETF demand to cool this fast. '
                 'welp" / "everyone sitting on fat profits and nobody buying. classic". ' + NO_BIO_EN,
                 '类型 reaction（情绪，不是观点）：一两句短话，主要写你看到 units 里某个事实时的情绪——惊了、无语、松口气、'
                 '眼红、麻了、笑死、绷不住。事实只用几个字带过，最多一个数字。不写「因为/所以/意味着」，不分析、不预测、'
                 '不写「接下来盯」、不总结道理。例：「ETF 资金说凉就凉，麻了」「大家都躺着赚，就是没人买，绷不住」。' + NO_BIO_ZH),
    'meme': ('KIND meme: a deadpan joke / meme-format line about ONE fact from the units in the lane\'s own slang '
             '(e.g. "nobody: / devs:", "me refreshing the chart", "ser, this is a casino"). Irony, not analysis; at most '
             'one number. No new claims, no fake quotes or screenshots. ' + NO_BIO_EN,
             '类型 meme：用这个圈子自己的梗和说法，对 units 里的一个事实来一句冷幽默/段子（比如「韭菜：我悟了。行情：你没有」）。'
             '是调侃不是分析，最多一个数字。不编新事实、不编别人说的话。' + NO_BIO_ZH),
    'question': ('KIND question: the fact in one short line, then a genuine question to followers (what would they do, '
                 'how do they read it, have they used it) - the post ENDS with that question mark. Not a rhetorical take; '
                 'no answer after it, no analysis before it. At most one number.',
                 '类型 question：一句话交代事实，然后真诚地问关注者一个问题（你们怎么看/会怎么做/用过没有），'
                 '整条以问号结尾。不是反问式观点，问完不要自己回答，前面也不要分析。最多一个数字。'),
    'industry_people': ('KIND industry_people (gossip, not analysis): the people side of the story - who did or said '
                        'what (founder, team, fund, KOL, regulator), how the community took it, the irony or the drama, '
                        'in a chatty register. Only names and facts that are in the units; no rumours, no insults, '
                        'nothing the units do not say. At most two numbers, no market analysis.',
                        '类型 industry_people（圈内八卦，不是分析）：写这件事里「人」的那一面——谁做了什么、说了什么'
                        '（创始人、团队、机构、大V、监管），圈里怎么看，哪里讽刺或有戏剧性，用聊天的口吻。只用 units 里有的'
                        '名字和事实，不传谣、不人身攻击。最多两个数字，不做行情分析。'),
    'diary': ('KIND diary: at most 3 short lines. ONE feeling or small observation about YOUR day of watching the market '
              'or your own posting / chart-watching habits ("refreshed the chart way too many times today", "told myself '
              'no screens tonight. lasted 10 minutes"); open with the feeling, not the event; ONE real event from the '
              'units only as a light backdrop in a few words. No analysis, no "because"/"which means", no forecast, no level / target, no advice, no number '
              'needed. ' + NO_BIO_EN,
              '类型 diary：最多三行短句。只写一个感受或一个小观察——你自己今天看盘/刷推/发帖的状态（比如「今天又没忍住看盘」'
              '「说好今晚不看盘，坚持了十分钟」），先写感受、别用事件开头，只用几个字把 units 里的一个真实事件当背景。不分析、不写「因为/所以/意味着」、'
              '不预测、不报点位、不给建议，不需要数字，不要用「我看/我觉得」开头去下判断。' + NO_BIO_ZH),
}
OFFLANE_RULE = ('This post is a deliberate aside outside your usual lane (your donors post about this too): write it '
                'as a short personal take from your own vantage point, not as lane analysis, and do not pretend it is '
                'your speciality.',
                '这条是你平时赛道之外的一次顺口聊（你关注的博主也会聊这个）：从你自己的角度简短说两句，不要写成本赛道分析，'
                '也别装成专业领域。')


def post_format(kind, lang):
    """post_format dict for a human kind (daily_compose sets it on the pick; compose keeps it, no nat3 re-sample)."""
    t, shape, zh, en = _FORMAT[kind]
    lo, hi = zh if lang == 'zh' else en
    return {'type': t, 'length': 'short', 'thread_parts': None, 'shapes': [shape],
            'length_target': {'min': lo, 'max': hi}, 'kind': kind, 'no_nat': True}


def rule(kind, lang, account=None):
    if kind not in RULES:
        return None
    text = RULES[kind][1 if lang == 'zh' else 0]
    return text


# ---------------------------------------------------------------- invented-biography check (HARD for human kinds)
BIO_RX = {
    'en': re.compile(r"\bI(?:'m| am| was)? (?:just )?(?:bought|sold|longed|shorted|aped|entered|closed|added|trimmed|"
                     r"took profit|went long|went short)\b|\bmy (?:bag|bags|position|positions|entry|stack|portfolio|"
                     r"p&l|pnl|wife|husband|kids?|son|daughter|boss|job|office|flight)\b|\b(?:i'm|i am) (?:up|down) "
                     r"\d|\bI (?:made|lost) \$?\d|\bjust (?:landed|got back) (?:in|from)\b", re.I),
    'zh': re.compile(r'我(?:刚|今天|昨天)?(?:买了|卖了|梭哈|加仓|减仓|清仓|建仓|开了?多|开了?空|止损|止盈|抄底了|上车了|下车了)|'
                     r'我的(?:仓位|持仓|老婆|老公|孩子|儿子|女儿|老板|公司|工位)|(?:赚了|亏了|浮盈|浮亏)\s*\d|'
                     r'我(?:在|刚到|刚回)(?:北京|上海|深圳|香港|杭州|成都|广州|新加坡|东京|纽约|伦敦|迪拜)'),
}


def density_findings(body, lang, kind):
    """SOFT: a human kind that came back as analysis (numbers / causal chain / long)."""
    if kind not in HUMAN:
        return []
    b = str(body or '')
    nums = len(re.findall(r'\d+(?:[.,]\d+)?%?', b))
    limit = 2 if kind == 'industry_people' else 1
    out = []
    if nums > limit + (1 if kind == 'diary' else 0):
        out.append({'code': 'kind_too_dense', 'level': 'soft', 'detail': f'{kind} with {nums} numbers'})
    if kind == 'diary' and len([ln for ln in b.splitlines() if ln.strip()]) > 3:
        out.append({'code': 'kind_diary_too_long', 'level': 'soft', 'detail': 'diary over 3 lines'})
    if kind == 'question' and not re.search(r'[?？]\s*\S{0,3}\s*$', b.strip()):
        out.append({'code': 'kind_question_no_question', 'level': 'soft', 'detail': 'question kind does not end on a question'})
    return out


def bio_findings(body, lang, kind):
    if kind not in HUMAN:
        return []
    m = BIO_RX['zh' if lang == 'zh' else 'en'].search(str(body or ''))
    return [{'code': 'kind_invented_bio', 'level': 'hard',
             'detail': f'human post kind {kind} claims a personal fact: {m.group(0)!r}'}] if m else []
