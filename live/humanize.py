"""Deterministic naturalness post-processor (nat3, Oct 10 2026).

Runs after hook_rewrite + engage_sibling_pass and before arbitration (daily_compose.py).
Also called on the engage-only fill path.

Flags: FD_HUMANIZE (default 1; 0 = skip entirely), FD_HUMANIZE_LLM (default 1 after the Oct 10 20-draft guard check: 12 accepted, 0 fabricated numbers / names; 0 = skip).
FD_HUMANIZE_LLM_MAX: max LLM rewrites per run (default 30).

Deterministic transforms (seeded by draft id, per-account donor rates from donor_rates.py):
  (a) intensifiers: keep at most 1 per post; drop the rest; additionally drop the remaining one
      with probability so account's post-level rate ≈ donor rate.
  (b) numbers: round over-precise figures to 2-3 sig figs + k/M/B / 万/亿 at donor rounding rate;
      never touch price levels that are the post's point, dates, years, tickers, %/bps/ratios.
  (c) texture at donor rates: emoji (top-5 only, max 1, at end of a line), $ticker first mention,
      zh crypto aliases (BTC→大饼 etc.), en lowercase at donor all_lower rate,
      zh particle (吧/啊/呢/哈, max 1) appended to a judgement line, never after a number.

After each transform the numeric fidelity check runs (live/fidelity.py numbers());
a hard finding reverts the pre-humanize body.

LLM pass (FD_HUMANIZE_LLM, subrouter only): for drafts still flagged by cheap detector
(formula closer, lens jargon, 0 first person when donor rate >= 35%, >= 2 intensifiers left).
One rewrite prompt with 3 real donor posts as few-shot; then fidelity + fabrication checks; revert on fail.

Records row['humanize'] = {changes: [...], llm: bool, reverted: bool}.
"""
from __future__ import annotations

import collections
import json
import os
import re
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------ flags

def enabled(env=None):
    return (env or os.environ).get('FD_HUMANIZE', '1') != '0'

def llm_enabled(env=None):
    return enabled(env) and (env or os.environ).get('FD_HUMANIZE_LLM', '1') != '0'   # on: 20-draft guard check 10-10 18:35, 12 accepted, 0 fabricated

def llm_max(env=None):
    try:
        return int((env or os.environ).get('FD_HUMANIZE_LLM_MAX', '30'))
    except (ValueError, TypeError):
        return 30

# ------------------------------------------------------------------ deterministic seed

def _u(draft_id: str, tag: str, n: int = 0) -> float:
    h = sha256(f'{draft_id}\x00{tag}\x00{n}'.encode()).hexdigest()
    return int(h[:12], 16) / float(1 << 48)

# ------------------------------------------------------------------ intensifiers

_INTENS_ZH = re.compile(r'(简直|直接|根本|绝对|彻底|硬生生|死死|狠狠|疯狂|赤裸裸|纯粹|实打实|离谱|砸)')
_INTENS_EN = re.compile(
    r'\b(absolute(?:ly)?|completely|entirely|massive(?:ly)?|violent(?:ly)?|'
    r'aggressive(?:ly)?|brutal|wild(?:ly)?|insane|relentless(?:ly)?|'
    r'severely|strictly|fundamental(?:ly)?|structural(?:ly)?|clearly|simply)\b', re.I)

_QUOTED_NAME = re.compile(r'["「『].*?["」』]|\$[A-Za-z]{2,10}\b|@[A-Za-z0-9_]+')

# Droppable adverbs only (deleting them never breaks the sentence). Adjectives / predicates (离谱, 疯狂, massive,
# insane, brutal, structural) count toward the cap metric but are never deleted.
_DROP_ZH = re.compile(r'(简直|根本|硬生生|死死|狠狠|彻彻底底|直接(?=[\u4e00-\u9fff])(?!的)|绝对(?=[是会要能不没就])|纯粹(?=[是就])|'
                      r'实打实地?(?=[\u4e00-\u9fff])(?!的)|彻底(?=[\u4e00-\u9fff])(?![的了])|疯狂(?=[\u4e00-\u9fff])(?![了的]))')
_DROP_EN = re.compile(r'\b(completely|entirely|absolutely|simply|clearly|massively|violently|aggressively|relentlessly|'
                      r'severely|strictly|fundamentally|structurally|wildly|totally|utterly|literally)\b (?!put\b|speaking\b)', re.I)


def _protected(text):
    return [(q.start(), q.end()) for q in _QUOTED_NAME.finditer(text)]


def _drop(text, rx, keep):
    """Delete droppable matches after the first `keep` intensifier slots; returns (text, removed)."""
    prot = _protected(text)
    out, removed, last, seen = [], [], 0, 0
    for m in rx.finditer(text):
        if any(a <= m.start() < b for a, b in prot):
            continue
        if m.group(0).strip() == '直接' and text[m.end():m.end() + 1] in '。，,.!?！？' :
            continue
        seen += 1
        if seen <= keep:
            continue
        # a sentence-initial EN adverb: capitalise the next word
        out.append(text[last:m.start()])
        removed.append(m.group(0).strip())
        last = m.end()
    out.append(text[last:])
    new = ''.join(out)
    if removed and rx is _DROP_EN:
        new = re.sub(r'(^|[.!?]\s+)([a-z])', lambda x: x.group(1) + x.group(2).upper(), new) if text[:1].isupper() else new
    return new, removed


def _apply_intensifiers(body: str, lang: str, draft_id: str, donor_rate: float) -> tuple[str, list[str]]:
    """At most 1 intensifier per post (only droppable adverbs are deleted); the last droppable one goes with
    probability 1 - donor_rate so the account's post-level rate approaches its donors'."""
    count_rx, drop_rx = (_INTENS_ZH, _DROP_ZH) if lang == 'zh' else (_INTENS_EN, _DROP_EN)
    n = len(count_rx.findall(body))
    if n == 0:
        return body, []
    # keep the first non-droppable intensifier if there is one, else the first droppable one
    non_drop = n - len(drop_rx.findall(body))
    keep = 0 if non_drop >= 1 else 1
    body, removed = _drop(body, drop_rx, keep)
    changes = [f'removed intensifier: {w!r}' for w in removed]
    if keep == 1 and _u(draft_id, 'intensifier_drop') > donor_rate:
        body, more = _drop(body, drop_rx, 0)
        changes += [f'dropped remaining intensifier: {w!r}' for w in more]
    return body, changes


# ------------------------------------------------------------------ number rounding

_NUM_EN = re.compile(
    r'(?<!\w)'
    r'(?P<currency>\$|USD\s*)?'
    r'(?P<val>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d{2,}|-?\d{7,})'
    r'(?P<scale>\s*(?:trillion|billion|million|thousand)\b)?'
    r'(?P<unit>\s*(?:%|bps|bp\b))?'
    r'(?!\w)', re.I)

_NUM_ZH = re.compile(
    r'(?P<val>-?\d+(?:\.\d+)?)'
    r'(?P<scale>亿|万亿|万|千万|百万)?'
    r'(?P<unit>美元|美金|刀|元|%|个点)?'
)

# don't round these contexts
_PRICE_CONTEXT_EN = re.compile(
    r'(?:at|above|below|around|near|from|hit|reach|broke?|under|over|trading at|at a low of|at a high of)\s+\$?-?\d', re.I)
_PERCENT_ONLY = re.compile(r'-?\d+(?:\.\d+)?%')
_DATE_LIKE = re.compile(r'\b20\d\d\b|\bQ[1-4]\b|\b[12]\d{3}\b')
_TICKER_NUM = re.compile(r'\$[A-Z]{2,10}\d|\bBTC\d|\bETH\d')


def _is_precise_en(s: str) -> bool:
    """Return True when the string looks like an over-precise number (>= 2 decimals or 7+ digit integer or comma-sep 7+ digits)."""
    s = s.replace(',', '')
    if re.fullmatch(r'-?\d{7,}', s):
        return True
    if re.search(r'\.\d{2,}', s):
        return True
    return False


def _round_en(val_str: str, scale_str: str) -> tuple[str | None, str | None]:
    """Round to 2-3 sig figs + SI suffix. Returns (new_val, new_scale) or (None, None) if unchanged."""
    raw = val_str.replace(',', '')
    try:
        v = float(raw)
    except ValueError:
        return None, None
    # pick scale
    abs_v = abs(v)
    if abs_v >= 1e12 or scale_str.lower().strip() == 'trillion':
        canon = v / 1e12
        suf = 'T'
    elif abs_v >= 1e9 or 'billion' in scale_str.lower():
        canon = v / 1e9
        suf = 'B'
    elif abs_v >= 1e6 or 'million' in scale_str.lower():
        canon = v / 1e6
        suf = 'M'
    elif abs_v >= 1e3 or 'thousand' in scale_str.lower():
        canon = v / 1e3
        suf = 'k'
    else:
        # small number — just round to 2 sig figs
        if abs_v == 0:
            return None, None
        from math import log10, floor
        mag = floor(log10(abs_v))
        factor = 10 ** (mag - 1)
        rounded = round(v / factor) * factor
        new_val = f'{rounded:g}'
        return new_val, ''
    # round canon to 2-3 sig figs
    if abs(canon) >= 100:
        rounded = round(canon)
        new_val = f'{rounded:g}'
    elif abs(canon) >= 10:
        rounded = round(canon, 1)
        new_val = f'{rounded:g}'
    else:
        rounded = round(canon, 2)
        new_val = f'{rounded:g}'
    return new_val, suf


def _round_zh(val_str: str, scale_str: str) -> tuple[str | None, str | None]:
    """Round to 2-3 sig figs + 万/亿. Returns (new_val, new_scale) or (None, None)."""
    raw = val_str.replace(',', '')
    try:
        v = float(raw)
    except ValueError:
        return None, None
    abs_v = abs(v)
    # apply existing scale
    mult = {'亿': 1e8, '万亿': 1e12, '万': 1e4, '千万': 1e7, '百万': 1e6}.get(scale_str, 1.0)
    v_abs_raw = abs_v * mult

    if v_abs_raw >= 1e12:
        canon = v_abs_raw / 1e12
        suf = '万亿'
    elif v_abs_raw >= 1e8:
        canon = v_abs_raw / 1e8
        suf = '亿'
    elif v_abs_raw >= 1e4:
        canon = v_abs_raw / 1e4
        suf = '万'
    else:
        return None, None

    if abs(canon) >= 100:
        rounded = round(canon)
        new_val = f'{int(rounded)}'
    elif abs(canon) >= 10:
        rounded = round(canon, 1)
        new_val = f'{rounded:g}'
    else:
        rounded = round(canon, 1)
        new_val = f'{rounded:g}'
    sign = '-' if v < 0 else ''
    return sign + new_val, suf


def _apply_numbers(body: str, lang: str, draft_id: str, precise_share: float,
                   donor_precise_share: float) -> tuple[str, list[str]]:
    """Round over-precise numbers at probability = 1 - donor_precise_share / precise_share."""
    if donor_precise_share >= precise_share or donor_precise_share >= 0.99:
        return body, []
    # probability to round each precise number
    p_round = 1.0 - donor_precise_share / max(precise_share, 0.01)
    p_round = min(0.95, p_round)

    changes = []

    def try_round_en(m):
        full = m.group(0)
        val_str = m.group('val')
        scale_str = m.group('scale') or ''
        currency = m.group('currency') or ''
        unit = m.group('unit') or ''
        if unit.strip() in ('%', 'bps', 'bp'):
            return full  # never round % or bps
        if not _is_precise_en(val_str):
            return full
        # don't round price-level context (e.g. "at $82,000")
        start = m.start()
        ctx = body[max(0, start - 30):start + len(full) + 10]
        if _PRICE_CONTEXT_EN.search(ctx):
            return full
        # probabilistic gate
        idx = len(changes)
        if _u(draft_id, 'num_en', idx) > p_round:
            return full
        new_val, new_scale = _round_en(val_str, scale_str)
        if new_val is None:
            return full
        if new_scale:
            result = f'{currency}{new_val}{new_scale}'
        else:
            result = f'{currency}{new_val}'
        changes.append(f'rounded: {full!r} -> {result!r}')
        return result

    def try_round_zh(m):
        full = m.group(0)
        val_str = m.group('val')
        scale_str = m.group('scale') or ''
        unit = m.group('unit') or ''
        if unit in ('%', '个点'):
            return full
        # needs at least 2 decimal places or >= 7 digits to be "precise"
        raw = val_str.replace(',', '')
        if not (re.search(r'\.\d{2,}', raw) or re.fullmatch(r'-?\d{7,}', raw) or
                (scale_str and re.search(r'\.\d{2,}', val_str))):
            return full
        idx = len(changes)
        if _u(draft_id, 'num_zh', idx) > p_round:
            return full
        new_val, new_scale = _round_zh(val_str, scale_str)
        if new_val is None:
            return full
        result = f'{new_val}{new_scale}{unit}'
        changes.append(f'rounded: {full!r} -> {result!r}')
        return result

    if lang == 'en':
        new_body = _NUM_EN.sub(try_round_en, body)
    else:
        new_body = _NUM_ZH.sub(try_round_zh, body)

    return new_body, changes

# ------------------------------------------------------------------ texture

_EMO = re.compile(r'[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]')
_TICKER_MENTION = re.compile(r'\$([A-Za-z]{2,10})\b')

# zh crypto aliases
_ZH_ALIASES = {
    'BTC': '大饼', 'BITCOIN': '大饼',
    'ETH': '姨太', 'ETHEREUM': '姨太',
    'USDT': 'U',
}
_ZH_ALIAS_RX = re.compile(r'(?<![A-Za-z$])(' + '|'.join(_ZH_ALIASES) + r')(?![A-Za-z0-9])')

def _line_is_judgement(line: str, lang: str) -> bool:
    """True when a line looks like a judgement/opinion (not just a number or a fact line)."""
    t = line.strip()
    if not t:
        return False
    if re.search(r'^\s*[-•·]\s|\d{1,3}[.)]\s', t):
        return False  # list item
    if re.fullmatch(r'[\d,.%$\s]+', t):
        return False  # pure number line
    if re.search(r'\d$', t):
        return False  # ends with a number
    # has a verb or opinion word
    if lang == 'zh':
        return bool(re.search(r'[会可能是认为看觉得说觉感有没]', t))
    return bool(re.search(r'\b(is|are|was|were|will|would|could|should|think|believe|see|seems|expect|looks?)\b', t, re.I))


_NEUTRAL_EMOJI = frozenset('👀🤔🧐😅🫠🙃😌🫡🤷🙏😶🫢😮🥲😬')   # no 👇: it points at nothing at the end of a post


def _apply_texture(body: str, lang: str, draft_id: str, rates: dict) -> tuple[str, list[str]]:
    """Add emoji, $ticker, zh aliases, en lowercase, zh particle at donor rates."""
    if os.environ.get('FD_HUMANIZE', '1') == '0':
        return body, []
    changes = []
    lines = body.split('\n')
    # only tone-neutral emoji (a 🚀 under a bearish line reads wrong); no flag halves / modifiers
    top5 = [e for e in (rates.get('top5_emoji') or []) if e in _NEUTRAL_EMOJI]
    emoji_rate = rates.get('emoji', 0.0)
    ticker_rate = rates.get('ticker', 0.0)
    slang_rate = rates.get('slang', 0.0)
    particle_rate = rates.get('particle', 0.0) if lang == 'zh' else 0.0
    lowercase_rate = rates.get('all_lower', 0.0) if lang == 'en' else 0.0

    # (a) emoji: at most 1, appended to the last non-empty line, at donor rate
    already_has_emoji = bool(_EMO.search(body))
    if (not already_has_emoji and top5 and
            _u(draft_id, 'emoji') < emoji_rate):
        pick = top5[int(_u(draft_id, 'emoji_pick') * len(top5))]
        # append to last non-empty line
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                lines[i] = lines[i].rstrip() + ' ' + pick
                changes.append(f'added emoji: {pick!r}')
                break
        body = '\n'.join(lines)

    # (b) $ticker: convert first mention of a known ticker name to $TICKER at donor rate
    if lang == 'en' and not _TICKER_MENTION.search(body):
        if _u(draft_id, 'ticker') < ticker_rate:
            # find first crypto/stock ticker-like word (all caps 2-5 letters not at start of sentence)
            def add_dollar(m):
                if not add_dollar.done:
                    add_dollar.done = True
                    changes.append(f'added $ticker: ${m.group(1)}')
                    return f'${m.group(1)}'
                return m.group(0)
            add_dollar.done = False
            tickers = re.findall(r'\b([A-Z]{2,6})\b', body)
            crypto_words = {'BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'AVAX', 'MATIC', 'LINK', 'DOT', 'ADA',
                           'NEAR', 'SUI', 'APT', 'ARB', 'OP', 'INJ', 'TIA', 'JTO', 'OKLO'}
            first_tick = next((t for t in tickers if t in crypto_words), None)
            if first_tick:
                body = re.sub(r'(?<!\$)\b' + re.escape(first_tick) + r'\b', f'${first_tick}', body, count=1)
                changes.append(f'added $ticker: ${first_tick}')

    # (c) zh crypto aliases at slang rate
    if lang == 'zh' and _u(draft_id, 'alias') < slang_rate:
        def replace_alias(m):
            sym = m.group(1).upper()
            alias = _ZH_ALIASES.get(sym)
            if alias:
                changes.append(f'zh alias: {sym} -> {alias}')
                return alias
            return m.group(0)
        body = _ZH_ALIAS_RX.sub(replace_alias, body)
        body = re.sub(r'(大饼|姨太|U) (?=[\u4e00-\u9fff])', r'\1', body)

    # (d) en lowercase: lowercase the whole post at donor all_lower rate
    if lang == 'en' and lowercase_rate >= 0.30:
        if _u(draft_id, 'lowercase') < lowercase_rate:
            new_body = re.sub(r"[A-Za-z][A-Za-z']*", lambda m: m.group(0) if m.group(0).isupper() and len(m.group(0)) > 1
                              else m.group(0).lower(), body)
            if new_body != body:
                body = new_body
                changes.append('applied all-lowercase')

    # (e) zh particle: append to one judgement line at donor rate
    if lang == 'zh' and particle_rate > 0:
        # max 1 particle
        if not re.search(r'[吧啊呢嘛哈]$', body):
            if _u(draft_id, 'particle') < particle_rate:
                pick_p = '吧' if _u(draft_id, 'particle_pick') < 0.6 else '啊'
                pick_p = '吧'   # 啊 / 呢 mid-post on a statement read odd; 吧 on the closing judgment is the donor habit
                lines_body = body.split('\n')
                last_i = max((k for k, l in enumerate(lines_body) if l.strip()), default=-1)
                for i, ln in enumerate(lines_body):
                    if i != last_i:
                        continue
                    core = ln.rstrip()
                    stem = core.rstrip('。.')
                    if (not _line_is_judgement(stem, lang) or not stem or stem[-1] in '？?！!…~～）)」"'
                            or re.search(r'[\dA-Za-z%]$', stem)):
                        continue
                    lines_body[i] = stem + pick_p + core[len(stem):].replace('.', '').replace('。', '')
                    changes.append(f'added zh particle: {pick_p!r}')
                    body = '\n'.join(lines_body)
                    break

    return body, changes


_CLOSER_MARK = re.compile(r'(接下来(?:要)?(?:盯|看|关注)|关键(?:还是)?看|后续(?:要)?(?:盯|看|关注)|值得(?:持续)?关注|拭目以待|盯紧|盯好|'
                          r'(?<![A-Za-z])(?:Watch|Keep an eye on|Expect|The question is|Time will tell|What to watch|Worth watching)\b)')


def drop_formula_closer(body: str):
    """Cut a formula closer (接下来盯 / 关键看 / Watch X / Expect X ...) at the end of the post: the whole last line when
    it opens with one and the post has another line, else the trailing sentence of the last line that opens with
    one. Returns (body, removed text or '')."""
    lines = body.rstrip().split('\n')
    idx = max((i for i, l in enumerate(lines) if l.strip()), default=None)
    if idx is None:
        return body, ''
    last = lines[idx]
    m = None
    for m in _CLOSER_MARK.finditer(last):
        pass
    if not m:
        return body, ''
    head = last[:m.start()]
    if not head.strip() or re.fullmatch(r'\W*', head):
        if sum(1 for l in lines if l.strip()) < 2:
            return body, ''
        removed = last.strip()
        new = '\n'.join(lines[:idx]).rstrip()
        return new, removed
    cut = max(head.rfind(c) for c in '。.!！？?；;，,')
    if cut < 0 or len(head[:cut].strip()) < 6:
        return body, ''
    keep = head[:cut + 1]
    if keep[-1] in '，,；;':
        keep = keep[:-1] + ('。' if re.search(r'[\u4e00-\u9fff]', keep) else '.')
    removed = last[cut + 1:].strip()
    lines[idx] = keep.rstrip()
    return '\n'.join(lines[:idx + 1]).rstrip(), removed


def _moral_candidate(last: str, lang: str) -> bool:
    """A neat moral / summary line: no number / ticker / question / name, not too long, not a short punch or first person."""
    if re.search(r'\d|\$[A-Za-z]|[?？]', last) or (lang == 'zh' and re.search(r'[A-Za-z]{2,}', last)):
        return False
    if lang != 'zh' and re.search(r'(?<!^)(?<![.!?] )\b[A-Z][a-z]+', last):
        return False
    if len(re.sub(r'\s', '', last)) > (70 if lang == 'zh' else 160):
        return False
    # a short punch ("Bitcoin barely blinked") or a first-person line is voice, not a moral
    if (len(re.sub(r'\s', '', last)) < 16 if lang == 'zh' else len(last.split()) < 6) or \
            re.search(r'我|俺|咱|\b(I|I\'m|my|me)\b', last):
        return False
    return True


_SENT_ZH = re.compile(r'(?<=[。！!])')
_SENT_EN = re.compile(r'(?<=[.!])\s+(?=[A-Za-z])')


def drop_moral_line(body: str, lang: str):
    lines = [l for l in body.rstrip().split('\n')]
    idx = [i for i, l in enumerate(lines) if l.strip()]
    if not idx or re.match(r'^\s*\d+/', lines[idx[0]]):   # threads keep their parts
        return body, ''
    rx = _SENT_ZH if lang == 'zh' else _SENT_EN
    if len(idx) >= 3:
        last = lines[idx[-1]].strip()
        if len([x for x in rx.split(last) if x.strip()]) < 2:
            if _moral_candidate(last, lang):
                return '\n'.join(lines[:idx[-1]]).rstrip(), last
            return body, ''
        # Oct 11: a multi-sentence last paragraph is never cut whole (it carries facts); only its last sentence below
    # Oct 11: 10-11 nightly, 23 of 41 drafts closed on an aphorism_verdict, most inside a 1-2 paragraph post where the
    # line rule never looks. The last SENTENCE of a post of >= 3 sentences is checked with the same rule.
    para = lines[idx[-1]]
    sents = [x for x in rx.split(para.strip()) if x.strip()]
    total = sum(len([x for x in rx.split(lines[i].strip()) if x.strip()]) for i in idx)
    if len(sents) < 2 or total < 3:
        return body, ''
    last = sents[-1].strip()
    if not _moral_candidate(last, lang):
        return body, ''
    keep = ('' if lang == 'zh' else ' ').join(x.strip() for x in sents[:-1]).strip()
    return '\n'.join(lines[:idx[-1]] + [keep]).rstrip(), last


# ------------------------------------------------------------------ lens jargon detector

_LENS_ZH = re.compile(r'流动性|宏观(?!经济数据|政策|背景)|底层(?!逻辑|技术)|筹码(?!分析)|结构(?!性机会)')
_LENS_EN = re.compile(r'\b(structural(?:ly)?|liquidity|macro\b|capital flows?)\b', re.I)

def _lens_jargon_count(body: str, lang: str) -> int:
    rx = _LENS_ZH if lang == 'zh' else _LENS_EN
    return len(rx.findall(body))

# ------------------------------------------------------------------ formula closer detector

_FORMULA_ZH = re.compile(r'(接下来盯|关键看|后续要盯|后续盯|值得关注|拭目以待|后续关注|盯好)\s*.{0,40}$', re.M)
_FORMULA_EN = re.compile(
    r'(Watch\s+\w[^.!?\n]{0,50}|Expect\s+\w[^.!?\n]{0,50}|keep an eye[^.!?\n]{0,50}|'
    r'time will tell[^.!?\n]{0,30}|The question is[^.!?\n]{0,50}|worth watching[^.!?\n]{0,50})'
    r'\s*[.!?]?\s*$', re.I | re.M)

def _has_formula_closer(body: str, lang: str) -> bool:
    rx = _FORMULA_ZH if lang == 'zh' else _FORMULA_EN
    return bool(rx.search(body))

# ------------------------------------------------------------------ first-person detector

_FP_ZH = re.compile(r'我|俺|咱')
_FP_EN = re.compile(r"\b(I|I'm|I've|I'd|I'll|my|me)\b")

def _first_person_count(body: str, lang: str) -> int:
    rx = _FP_ZH if lang == 'zh' else _FP_EN
    return len(rx.findall(body))

# ------------------------------------------------------------------ cheap trigger detector

def _needs_llm(body: str, lang: str, rates: dict) -> bool:
    """True when the draft has a pattern that LLM rewrite is likely to fix."""
    if _has_formula_closer(body, lang):
        return True
    if _lens_jargon_count(body, lang) > 1:
        return True
    fp_rate = rates.get('first_person', 0)
    if fp_rate >= 0.35 and _first_person_count(body, lang) == 0:
        return True
    # count remaining intensifiers
    rx = _INTENS_ZH if lang == 'zh' else _INTENS_EN
    if len(rx.findall(body)) >= 2:
        return True
    return False

# ------------------------------------------------------------------ fidelity guard

_VAL = re.compile(r'(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(%|万亿|亿|万|千万|百万|trillion|billion|million|thousand|bn|[kKmMbBtT](?![a-zA-Z]))?')
_SCALE = {'万亿': 1e12, '亿': 1e8, '千万': 1e7, '百万': 1e6, '万': 1e4, 'trillion': 1e12, 'billion': 1e9, 'bn': 1e9,
          'million': 1e6, 'thousand': 1e3, 'k': 1e3, 'm': 1e6, 'b': 1e9, 't': 1e12}


def _values(text):
    """[(value, is_percent)] of every number in text, scale words / k M B / 万 亿 applied."""
    out = []
    for m in _VAL.finditer(str(text or '')):
        try:
            v = float(m.group(1).replace(',', ''))
        except ValueError:
            continue
        unit = (m.group(2) or '')
        if unit == '%':
            out.append((v, True))
            continue
        out.append((v * _SCALE.get(unit.lower() if unit.isascii() else unit, 1.0), False))
    return out


def _close(a, b, tol=0.02):
    return a[1] == b[1] and (a[0] == b[0] or (a[0] and abs(a[0] - b[0]) / abs(a[0]) <= tol))


def _fidelity_ok(original_body: str, new_body: str, tol: float = 0.02) -> bool:
    """Numbers survive humanize: every number of the original is still there (exact, or a rounding within 2 %,
    same kind: percent vs amount) and the new body has no number the original lacks. Any error: not ok."""
    try:
        old, new = _values(original_body), _values(new_body)
        return (all(any(_close(o, n, tol) for n in new) for o in old)
                and all(any(_close(o, n, tol) for o in old) for n in new))
    except Exception:   # noqa: BLE001
        return False


_ENT_EN = re.compile(r'\$[A-Za-z]{2,10}\b|@\w+|\b[A-Z][A-Za-z0-9&.-]+\b')
_ENT_ZH = re.compile(r'\$?[A-Za-z][A-Za-z0-9&.-]+|@\w+')
_ENT_OK = frozenset('I Im Ive Id Ill IMO NGL TBH The This That It A An And But So If We You My Me Not No Yes Just Still '
                    'Wild Lol Lmao Ok Okay Meanwhile Also Now Then Today Tonight Yesterday What Why How Who Watching'.split())


def _entities_ok(original_body: str, new_body: str) -> bool:
    """LLM guard: no new names / tickers / handles (EN capitalised tokens, ZH Latin tokens) beyond the original."""
    rx = _ENT_ZH if re.search(r'[\u4e00-\u9fff]', original_body) else _ENT_EN
    have = {t.lower().lstrip('$') for t in rx.findall(original_body)}
    for t in rx.findall(new_body):
        k = t.lower().lstrip('$')
        if k in have or t.strip("'.").replace("'", '') in _ENT_OK:
            continue
        return False
    return True


# ------------------------------------------------------------------ LLM pass

def _load_donor_posts(persona_id: str, lang: str, n: int = 3) -> list[str]:
    """Load n real donor posts for few-shot (read at run time, never stored/committed)."""
    try:
        from live import registry
        p = registry.load_personas().get(persona_id)
        if not p:
            return []
        from live.exemplars import load_posts
        from live.line_end import lang_of, _originals
        donors = list((p.donor_weights or {}).keys())[:6]
        posts = []
        for h in donors:
            try:
                raw = load_posts(h)
                for rp in raw:
                    if not _is_original_post(rp):
                        continue
                    t = rp.get('text', '')
                    if lang_of(t) == lang:
                        posts.append(t)
                if len(posts) >= n:
                    break
            except Exception:
                pass
        return posts[:n]
    except Exception:
        return []


def _is_original_post(p: dict) -> bool:
    return (bool(p.get('text')) and not p.get('rt') and not p.get('reply')
            and not p.get('pinned'))


def _llm_rewrite(client: Any, row: dict, lang: str, donor_posts: list[str],
                 persona_name: str) -> str | None:
    """Single subrouter call; returns rewritten body or None on failure."""
    body = row.get('body') or ''
    few_shot = '\n---\n'.join(f'[donor] {t[:400]}' for t in donor_posts[:3])
    issues = []
    if _has_formula_closer(body, lang):
        issues.append('formula closer at end (接下来盯/Watch X/etc.)')
    if _lens_jargon_count(body, lang) > 1:
        issues.append('lens jargon words in text (流动性/structural/etc. — use the lens to frame, not label)')
    if _first_person_count(body, lang) == 0 and (row.get('_donor_fp_rate', 0) or 0) >= 0.35:
        issues.append('no first-person voice despite high donor rate')

    issues_str = '; '.join(issues) if issues else 'reads like a template'
    prompt = (
        f'Rewrite the following {lang} finance post to sound like a real person.\n\n'
        f'Account: {persona_name}\n\n'
        f'Issues to fix: {issues_str}\n\n'
        f'Rules:\n'
        f'- Keep every number, name, and fact exactly as written\n'
        f'- No new facts, no invented positions or trades\n'
        f'- Remove any formula closer (接下来盯/关键看/Watch X/Expect X/time will tell) and any neat moral / summary last line\n'
        f'- No intensifier adverbs (直接/根本/简直/绝对/completely/simply); emotion = one particle or fragment\n'
        f'- If there is lens jargon (流动性/structural/macro/capital flows/筹码/底层), remove it unless the source used it\n'
        f'- Match the voice of the donor examples below\n\n'
        f'Donor examples (real posts, ground truth for voice):\n{few_shot}\n\n'
        f'Post to rewrite:\n{body}\n\n'
        f'Return ONLY the rewritten post, no explanation.')
    try:
        resp = client('compose', [{'role': 'user', 'content': prompt}], 4000)
        text = (resp.get('text') or resp.get('content') or '') if isinstance(resp, dict) else str(resp or '')
        return text.strip().strip('`').strip() or None
    except Exception:   # noqa: BLE001
        return None

# ------------------------------------------------------------------ main entry point

def apply(row: dict, client: Any = None, lang: str | None = None,
          rates: dict | None = None, llm_count: list | None = None) -> dict:
    """Apply humanize transforms to row in place. Returns row.

    row: compose result dict (has 'body', 'account_id', 'id').
    client: compose-stage client (only used for LLM pass).
    lang: override language (default: from row['plan']['account_lang'] or rates['lang']).
    rates: donor_rates.account_rates() override.
    llm_count: [n] mutable int counter for FD_HUMANIZE_LLM_MAX tracking.
    """
    if not enabled():
        return row

    body = str(row.get('body') or '')
    if not body:
        return row

    account_id = row.get('account_id') or ''
    draft_id = row.get('id') or account_id

    # resolve lang
    if lang is None:
        lang = (row.get('plan') or {}).get('account_lang') or 'zh'
    lang = str(lang)[:2].lower() or 'zh'

    # resolve rates
    if rates is None:
        try:
            from live import donor_rates as _dr
            from live import registry
            p = registry.persona_for_account(account_id)
            rates = _dr.account_rates(p.persona_id) or {}
        except Exception:
            rates = {}

    all_changes: list[str] = []
    reverted = False
    # --- (0) formula closer: cut it unless this draft falls inside the account's donor closer rate. Facts may go
    # with it (nothing is added), so the cut body is the fidelity baseline for the steps below.
    if _u(draft_id, 'closer') >= float(rates.get('formula_closer', 0.05) or 0.0):
        cut, removed = drop_formula_closer(body)
        if removed and len(re.sub(r'\s', '', cut)) >= 8:
            all_changes.append(f'dropped formula closer: {removed[:60]!r}')
            body = cut
    original_body = body
    raw_body = str(row.get('body') or '')

    # --- LLM pass first (the deterministic steps below then clean up whatever the rewrite brings back) ---
    llm_used = False
    if (not reverted and llm_enabled() and client is not None
            and _needs_llm(body, lang, rates)):
        cap = llm_max()
        if llm_count is not None:
            if llm_count[0] >= cap:
                pass  # skip
            else:
                llm_count[0] += 1
                _do_llm = True
        else:
            _do_llm = True

        if locals().get('_do_llm'):
            try:
                persona_id = ''
                persona_name = account_id
                from live import registry
                p = registry.persona_for_account(account_id)
                persona_id = p.persona_id
                persona_name = p.name
            except Exception:
                pass
            row['_donor_fp_rate'] = rates.get('first_person', 0)
            donor_posts = _load_donor_posts(persona_id, lang)
            if donor_posts:
                new_body = _llm_rewrite(client, {**row, 'body': body}, lang, donor_posts, persona_name)
                if new_body and new_body != body:
                    if (_fidelity_ok(original_body, new_body) and _entities_ok(original_body, new_body)
                            and len(new_body) <= max(len(body) * 1.15, len(body) + 20)):
                        body = new_body
                        llm_used = True
                        all_changes.append('llm_rewrite')
                    else:
                        all_changes.append('REVERTED(llm): fidelity fail')

    original_body = body   # LLM output (number-checked) is the baseline from here

    # --- (0b) neat moral / summary last line (aphorism_verdict: 21 of 31 drafts on 10-10): a post of >= 3 lines whose
    # last line carries no number, ticker or Latin name restates the call; cut it unless the draft falls inside the
    # account's donor closer rate.
    if _u(draft_id, 'moral') >= float(rates.get('formula_closer', 0.05) or 0.0):
        cut, removed = drop_moral_line(body, lang)
        if removed:
            all_changes.append(f'dropped moral line: {removed[:60]!r}')
            body = cut
            original_body = body

    # --- (a) intensifiers ---
    donor_intens = rates.get('intensifier', 0.19)   # nat1010 donor median
    body, chg = _apply_intensifiers(body, lang, draft_id, donor_intens)
    all_changes += chg

    # fidelity guard after intensifiers
    if chg and not _fidelity_ok(original_body, body):
        body = original_body
        all_changes = [f'REVERTED(intensifier): fidelity fail']
        reverted = True

    if not reverted:
        # --- (b) numbers ---
        donor_precise = rates.get('precise_number', 0.10)
        # measure current precise share (use 0.5 as "has precise numbers" threshold — actually 1 post flag)
        # for the post-level rate we just use donor_precise vs a fixed "1.0 per-post if has precise"
        body_pre_num = body
        body, chg = _apply_numbers(body, lang, draft_id,
                                   precise_share=1.0,   # treat this post as having precise numbers
                                   donor_precise_share=donor_precise)
        all_changes += chg

        # fidelity guard after numbers
        if chg and not _fidelity_ok(original_body, body):
            body = body_pre_num
            all_changes = [c for c in all_changes if not c.startswith('rounded')] + ['REVERTED(number): fidelity fail']

        # --- (c) texture ---
        body, chg = _apply_texture(body, lang, draft_id, rates)
        all_changes += chg

        # fidelity guard after texture
        if chg and not _fidelity_ok(original_body, body):
            body = body_pre_num   # revert to pre-texture
            all_changes = [c for c in all_changes if not c.startswith(('added', 'applied', 'zh alias'))]
            all_changes.append('REVERTED(texture): fidelity fail')

    row['body'] = body
    # also update row['text'] if it matches original body (no frame)
    if row.get('text') == raw_body:
        row['text'] = body
    elif row.get('body') != row.get('text'):
        # frame present: update only the body portion
        if raw_body and raw_body in str(row.get('text') or ''):
            row['text'] = str(row['text']).replace(raw_body, body, 1)

    row['humanize'] = {'changes': all_changes, 'llm': llm_used, 'reverted': reverted}
    return row


def apply_batch(results: list[dict], client: Any = None) -> None:
    """Apply humanize to a batch in place (daily_compose.py batch stage)."""
    if not enabled():
        return
    llm_count = [0]
    for r in results:
        if not r.get('body'):
            continue
        lang = (r.get('plan') or {}).get('account_lang') or 'zh'
        try:
            apply(r, client=client, lang=lang, llm_count=llm_count)
        except Exception as exc:   # noqa: BLE001 - humanize never blocks a draft
            r['humanize'] = {'changes': [], 'error': str(exc)[:200]}
            continue
        h = r.get('humanize') or {}
        if h.get('changes'):
            if 'length' in r:
                try:
                    from live.compose import length_of
                    r['length'] = length_of(r['body'])
                except Exception:   # noqa: BLE001
                    pass
            print(f"[humanize] {r.get('account_id')} {'LLM ' if h.get('llm') else ''}{'; '.join(h['changes'])[:200]}",
                  flush=True)
