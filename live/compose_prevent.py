"""Oct 13 (Fiona 08:42): quality rules as PREVENTION at compose time (FD_COMPOSE_PREVENT, default on; 0 = off).

1. prompt_block(): rules ride the compose payload BEFORE writing - a figure whitelist extracted from the source,
   the banned-opener list with good opener examples per language, format rules (no empty step labels, jargon
   explained on first use), verbatim-only quotes, keep >= 1 of the source's own insights, no invented opinions.
2. findings(): cheap rule checks right after generation, per sentence.
3. repair(): ONE pass that rewrites only the offending sentences (never a full regen); a sentence still failing
   after that is left for the post-draft review (the final safety net, unchanged).
"""
from __future__ import annotations

import os
import re

BANNED_OPENERS = {
    'en': ['ngl', 'idk', 'tbh', 'honestly,', "here's the thing", "let's talk about", 'in this post', 'thread:',
           'quick thread', 'hot take:', "it's not X, it's Y"],
    'zh': ['我看', '说实话', '讲真', '今天聊聊', '今天来说说', '本帖', '这篇', '先说结论', '不是X而是Y', '不是…而是…'],
}
GOOD_OPENERS = {
    'en': ['BTC lost $60k in under an hour and funding barely moved.',
           'CPI lands this week and the curve is already leaning one way.',
           'Who else stayed up for the Fed minutes?'],
    'zh': ['凌晨两点还在盯盘，这根针插得太狠了',
           '韩国股市一天跌掉一大截，外资是真的在跑',
           '这周CPI，大家押哪边？'],
}
_OPEN_RE = {
    'en': re.compile(r"^\s*(ngl|idk|tbh|honestly,|here'?s the thing|let'?s talk about|in this post|"
                     r"(quick )?thread:|hot take:)", re.I),
    'zh': re.compile(r'^\s*(我看|说实话|讲真|今天(聊聊|来说说)|本帖|这篇|先说结论)'),
}
_NOT_BUT = {'en': re.compile(r"\b(it'?s|this is|that'?s|the (?:story|point|issue|reason|problem) is) not (just |about |really )?[^.?!;\n]{1,50}?[,;—–-]\s*(it'?s|but|rather)\b"
                              r"|\bnot (?:because of |about )?[^.?!;\n]{1,40}?[,;—–-]\s*(?:it'?s|but) (?:about |because )?", re.I),
            'zh': re.compile(r'不是[^。！？\n]{1,24}?[，,；;]?\s*(?:而是|是|就是|反而是)|(?:原因|关键|问题|重点|核心|真相)(?:并)?不在[^。！？\n]{1,24}?[，,]\s*(?:而)?(?:是|在)|与其说[^。！？\n]{1,24}?不如说')}
_NFA = re.compile(r'not (?:financial|investment) advice|\bNFA\b|DYOR|不构成(?:任何)?投资建议|仅供参考|非投资建议', re.I)
_EMPTY_STEP = re.compile(r'^\s*(?:\d+|[一二三四五六七八九十]+|[①-⑩]|step\s*\d+)\s*[.、)）:：]\s*[:：]?\s*$', re.I | re.M)
_EMPTY_LABEL = re.compile(r'^\s*(?:\d+|[一二三四五六七八九十]+)\s*[.、)）]\s*[:：]\s*$|[:：]\s*$', re.M)
_QUOTE = re.compile(r'[“"「『]([^”"」』\n]{6,})[”"」』]')
_NUM = re.compile(r'(?<![\w.])[$€£¥]?\d[\d,]*(?:\.\d+)?\s*(?:%|bp|bps|[kKmMbBtT](?![a-z])|万亿|亿|万|倍|美元|点)?')
_SENT = re.compile(r'(?:[^。！？!?\n.]|\.(?=\d))+(?:[。！？!?]+|\.+(?!\d)|\n|$)')
JARGON = ['funding rate', 'basis', 'open interest', 'OI', 'CPI', 'PCE', 'FOMC', 'dot plot', 'term premium',
          'liquidation', 'perp', 'ETF', 'TGA', 'RRP', '资金费率', '基差', '未平仓', '爆仓', '缩表', '点阵图', '期限溢价']


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_COMPOSE_PREVENT', '1') != '0'


def _lang(lang):
    return 'zh' if str(lang or '').startswith('zh') else 'en'


def whitelist(evidence_text, cap=40):
    """Figures stated in the source / selected units (literal strings, deduped, order kept)."""
    out, seen = [], set()
    for m in _NUM.finditer(evidence_text or ''):
        t = m.group(0).strip()
        key = re.sub(r'[^\d.]', '', t)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= cap:
            break
    return out


def prompt_block(lang, evidence_text, disputed=()):
    lg = _lang(lang)
    wl = whitelist(evidence_text)
    block = {
        'number_whitelist': wl,
        'number_rule': ('HARD: the only figures you may write are in number_whitelist (copy them as written; '
                        'round only by dropping decimals). No other number, date math or derived percentage. '
                        'If a point needs a figure that is not listed, say it in words without a number.'),
        'banned_openers': BANNED_OPENERS[lg],
        'opener_rule': ('HARD: never open with a banned opener or a meta opener about the post itself, and never use '
                        'the "not X but Y" family anywhere (不是X而是Y, 原因不在X，是Y, 与其说X不如说Y, "it\'s not X, it\'s Y", '
                        '"not because of X, but Y"). Good openers look like good_opener_examples '
                        '(shape only, do not copy).'),
        'good_opener_examples': GOOD_OPENERS[lg],
        'numbers_rule': ('Use only the 2-3 key figures that carry the point; never list figure after figure.'),
        'human_rule': ('Write like a person reacting to a REAL event, in a conversational rhythm: keep the source\'s '
                       'insight, and add one genuine reaction (hesitation, still watching it, surprise, asking readers '
                       'what they make of it). No invented holdings, trades, P&L or life details.'),
        'disclaimer_rule': ('Do NOT add "Not financial advice" / NFA / DYOR / 不构成投资建议 / 仅供参考 to ordinary '
                            'commentary. Only a post that describes a strategy or how to trade may carry one.'),
        'format_rule': ('HARD: no empty step labels (e.g. "1. ：" or a numbered line with nothing after it); explain '
                        'each piece of jargon in a few plain words the first time it appears.'),
        'quote_rule': 'HARD: anything inside quotation marks must be a verbatim copy from the source text.',
        'insight_rule': ('HARD: keep at least one analysis / insight that the SOURCE itself makes (attributed or in '
                         'your voice); do not invent opinions, forecasts or reasons the source does not give.'),
    }
    if disputed:
        block['disputed_figures'] = list(disputed)
        block['disputed_rule'] = ('Sources disagree on these facts: do not state the disputed figure/day, or hedge it '
                                  '("around", "reports differ").')
    return block


def sentences(body):
    return [s for s in (m.group(0) for m in _SENT.finditer(body or '')) if s.strip()]


def _num_ok(tok, evidence_text):
    from live.compose import _number_in_text
    return _number_in_text(tok, evidence_text)


def findings(body, lang, evidence_text, strategy=False):
    """[{'sentence', 'codes': [...]}] for sentences breaking a prevention rule; plus whole-body codes."""
    lg = _lang(lang)
    out = []
    first = (body or '').strip().split('\n', 1)[0]
    ev_norm = re.sub(r'\s+', ' ', evidence_text or '')
    seen_jargon = set()
    for i, s in enumerate(sentences(body)):
        codes = []
        for m in _NUM.finditer(s):
            tok = m.group(0).strip()
            lit = re.sub(r'[^\d.]', '', tok)
            if not lit or (lit.isdigit() and len(lit) == 4 and 1990 <= int(lit) <= 2035):
                continue   # years
            if not _num_ok(tok, evidence_text):
                codes.append(f'number_not_in_source:{tok}')
        if i == 0 and (_OPEN_RE[lg].search(s) or _OPEN_RE['en'].search(s)):
            codes.append('banned_opener')
        if not strategy and _NFA.search(s):
            codes.append('disclaimer_on_commentary')
        if _NOT_BUT[lg].search(s) or _NOT_BUT['en' if lg == 'zh' else 'zh'].search(s):
            codes.append('not_x_but_y')
        for q in _QUOTE.findall(s):
            if re.sub(r'\s+', ' ', q.strip()) not in ev_norm:
                codes.append('quote_not_verbatim')
        if _EMPTY_STEP.search(s.strip()):
            codes.append('empty_step_label')
        if codes:
            out.append({'sentence': s.strip(), 'codes': codes})
    nums = [m.group(0) for m in _NUM.finditer(body or '') if not re.fullmatch(r'(19|20)\d\d', m.group(0).strip())]
    if len(nums) > 4 and not strategy:
        out.append({'sentence': '', 'codes': [f'too_many_numbers:{len(nums)}'], 'whole_body': True})
    for line in (body or '').split('\n'):
        if line.strip() and _EMPTY_STEP.match(line) and not any(f['sentence'] == line.strip() for f in out):
            out.append({'sentence': line.strip(), 'codes': ['empty_step_label']})
    return out


REPAIR_SYSTEM = ('[prevent_repair] You fix individual sentences of a social post. Rewrite ONLY the listed sentences so they break no '
                 'rule; keep voice, language and meaning; keep line-end punctuation habits. Numbers must come from '
                 'number_whitelist or be dropped; quotes must be verbatim from source_text or unquoted paraphrase; '
                 'no banned opener, no "not X but Y" family (不是X而是Y / 原因不在X是Y / it\'s not X, it\'s Y); an empty step label or a '
                 'disclaimer sentence (NFA / 不构成投资建议) is deleted (return ""). too_many_numbers: return the '
                 'whole body as one fix (old = "__BODY__") keeping only the 2-3 key figures and the same wording '
                 'otherwise. '
                 'Return JSON {"fixes": [{"old": <sentence as given>, "new": <rewritten sentence or "">}]}.')


def repair(body, lang, evidence_text, found, ask, strategy=False):
    """One repair pass: ask(system, payload) -> parsed dict. Splices rewritten sentences only. Returns (body, info)."""
    if not found:
        return body, None
    payload = {'body': body, 'task': REPAIR_SYSTEM, 'lang': _lang(lang), 'sentences': [{'sentence': f['sentence'], 'problems': f['codes']} for f in found],
               'number_whitelist': whitelist(evidence_text), 'banned_openers': BANNED_OPENERS[_lang(lang)],
               'source_text': (evidence_text or '')[:6000]}
    try:
        value = ask(REPAIR_SYSTEM, payload) or {}
    except Exception as exc:   # never fatal: post-draft review stays the safety net
        return body, {'error': str(exc)[:160], 'found': found}
    new = body
    applied = 0
    for fx in value.get('fixes') or []:
        old, rep = str(fx.get('old') or '').strip(), str(fx.get('new') or '').strip()
        if old == '__BODY__' and rep:
            new = rep
            applied += 1
        elif old and old in new:
            new = new.replace(old, rep, 1)
            applied += 1
    new = re.sub(r'\n{3,}', '\n\n', new).strip()
    if not new:
        return body, {'error': 'repair emptied body', 'found': found}
    left = findings(new, lang, evidence_text, strategy)
    return new, {'found': found, 'applied': applied, 'remaining': left, 'before': body}


def disputed_for(text):
    import json
    from pathlib import Path
    try:
        items = json.loads((Path(__file__).with_name('disputed_facts.json')).read_text())['items']
    except Exception:
        return []
    return [i['fact'] for i in items if re.search(i['match'], text or '', re.I)]
