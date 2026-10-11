"""Per-account formula-closer n-gram memory (naturalness A2, Oct 11 2026).

Detects when a draft's closing sentence repeats a key seen in the account's last 14 Beijing
days, or when the account's last 5 shippable drafts stack >= 3 forward-watch closers.

Kill switch: FD_CLOSER_NGRAM=0  (default on).

Findings are soft-only — never a HOLD on their own.  One targeted last-line rewrite is
attempted via the same deterministic transforms already in humanize; if that produces no
change the draft ships with a soft warning attached.

Finding codes:
  closer_ngram_repeat       — this draft's closer key is in the account's 14-day memory
  closer_forward_watch_stack — >= 3 forward-watch closers in the account's last 5 drafts
                               (including this one)
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Optional

VERSION = 'closer-ngram-v1'

# ------------------------------------------------------------------ kill switch

def enabled(env=None) -> bool:
    return (env if env is not None else os.environ).get('FD_CLOSER_NGRAM', '1') != '0'


# ------------------------------------------------------------------ forward-watch patterns
# Mirror humanize._CLOSER_MARK + _FORMULA_ZH / _FORMULA_EN for consistency.

_FW_ZH = re.compile(
    r'(接下来(?:要)?(?:盯|看|关注)|关键(?:还是)?看|后续(?:要)?(?:盯|看|关注)|'
    r'值得(?:持续)?关注|拭目以待|盯紧|盯好|继续(?:盯|看|关注)|接着盯)',
    re.UNICODE,
)
_FW_EN = re.compile(
    r'(?<![A-Za-z])(?:Watch|Keep an eye on|Expect|The question is|Time will tell|'
    r'What to watch|Worth watching)\b',
    re.IGNORECASE,
)

# CJK character range used for ZH key extraction
_CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')   # Oct 11 review: the old class also matched ASCII 0-9A-Za-z


def _is_forward_watch(last_line: str, lang: str) -> bool:
    pat = _FW_ZH if lang == 'zh' else _FW_EN
    return bool(pat.search(last_line))


# ------------------------------------------------------------------ key extraction

def _last_nonempty_line(body: str) -> str:
    for line in reversed(str(body or '').splitlines()):
        if line.strip():
            return line.strip()
    return ''


def closer_key(body: str, lang: str) -> str:
    """Normalised key for the closing line.

    ZH: first 8 CJK characters of the last non-empty line.
    EN: first 3 words (lowercased) of the last non-empty line.
    Returns '' when the line is empty or has no extractable key.
    """
    last = _last_nonempty_line(body)
    if not last:
        return ''
    if lang == 'zh':
        cjk = ''.join(_CJK.findall(last))
        return cjk[:8]
    else:
        words = re.findall(r"[a-zA-Z0-9']+", last)
        return ' '.join(words[:3]).lower()


# ------------------------------------------------------------------ beijing day helpers

_BJT_OFFSET_H = 8   # UTC+8; matches feedback.BJT_OFFSET_H


def _bjt_today(now=None) -> date:
    from datetime import datetime, timezone
    utc = now if now is not None else datetime.now(timezone.utc)
    return (utc + timedelta(hours=_BJT_OFFSET_H)).date()


def _day_str_in_window(day_str: str, today_bjt: date, window_days: int = 14) -> bool:
    """True when day_str (YYYY-MM-DD) falls within the last window_days Beijing days (exclusive of today)."""
    try:
        d = date.fromisoformat(day_str)
    except (ValueError, TypeError):
        return False
    delta = (today_bjt - d).days
    return 0 <= delta < window_days + 1   # Oct 11 review: earlier drafts of the same day count too (the current one is excluded by id)


# ------------------------------------------------------------------ inbox reader

def _shippable(row: dict) -> bool:
    """True for draft_ready rows and expired rows that still carry a body."""
    ds = row.get('draft_status', '')
    body = row.get('body') or ''
    return ds == 'draft_ready' or (ds == 'expired' and bool(body.strip()))


def _load_account_history(
    account_id: str,
    current_draft_id: str,
    today_bjt: date,
    window_days: int = 14,
    inbox_base=None,
) -> list[dict]:
    """Return shippable drafts for account_id in the 14-day window, excluding current draft.

    Each item has: day, body, lang.
    """
    try:
        from live import compose_inbox
    except ImportError:
        return []

    all_days = compose_inbox.days(base=inbox_base)
    out = []
    for day_str in all_days:
        if not _day_str_in_window(day_str, today_bjt, window_days):
            continue
        try:
            day_rows = compose_inbox.rows(day=day_str, account=account_id, base=inbox_base)
        except Exception:  # noqa: BLE001
            continue
        for r in day_rows:
            if r.get('id') == current_draft_id:
                continue
            if not _shippable(r):
                continue
            body = r.get('body') or ''
            lang = r.get('lang') or 'zh'
            if body.strip():
                out.append({'day': day_str, 'body': body, 'lang': lang})
    return out


# ------------------------------------------------------------------ findings

def closer_findings(
    row: dict,
    *,
    today_bjt: Optional[date] = None,
    inbox_base=None,
) -> list[dict]:
    """Return soft findings for closer_ngram_repeat and/or closer_forward_watch_stack.

    row must have: id, account_id, body, lang (or plan.account_lang).
    Returns [] when FD_CLOSER_NGRAM=0 or when no finding fires.
    """
    if not enabled():
        return []

    body = str(row.get('body') or '')
    if not body.strip():
        return []

    lang = row.get('lang') or (row.get('plan') or {}).get('account_lang') or 'zh'
    lang = str(lang)[:2].lower()
    account_id = str(row.get('account_id') or '')
    draft_id = str(row.get('id') or '')

    if today_bjt is None:
        today_bjt = _bjt_today()

    history = _load_account_history(account_id, draft_id, today_bjt, inbox_base=inbox_base)

    findings: list[dict] = []

    # --- a) closer_ngram_repeat ---
    this_key = closer_key(body, lang)
    if this_key:
        for prev in history:
            prev_lang = prev.get('lang') or lang
            prev_key = closer_key(prev['body'], prev_lang)
            if prev_key and prev_key == this_key:
                findings.append({
                    'code': 'closer_ngram_repeat',
                    'level': 'soft',
                    'detail': f'closer key {this_key!r} already appeared in {account_id} on {prev["day"]}',
                })
                break

    # --- b) closer_forward_watch_stack ---
    # Look at the last 5 shippable drafts (history is already sorted newest-first by compose_inbox.days),
    # plus this draft.
    last5_history = history[:4]   # up to 4 prior + this one = last 5
    fw_count = 1 if _is_forward_watch(_last_nonempty_line(body), lang) else 0
    for prev in last5_history:
        prev_lang = prev.get('lang') or lang
        if _is_forward_watch(_last_nonempty_line(prev['body']), prev_lang):
            fw_count += 1

    if fw_count >= 3:
        findings.append({
            'code': 'closer_forward_watch_stack',
            'level': 'soft',
            'detail': f'{fw_count} forward-watch closers in last 5 shippable drafts for {account_id}',
        })

    return findings


# ------------------------------------------------------------------ deterministic last-line repair

def _replace_last_line(body: str, new_last: str) -> str:
    """Swap the last non-empty line in body for new_last, preserving surrounding blank lines."""
    lines = str(body or '').splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            suffix = '\n' if not lines[i].endswith('\n') else ''
            lines[i] = new_last + suffix
            return ''.join(lines)
    return body


def _fix_last_line(body: str, lang: str) -> tuple[str, str]:
    """Try to improve the last line via the same deterministic helpers humanize already uses.

    Strategy (no LLM, no new claims):
      1. If it's a formula closer, drop it (humanize.drop_formula_closer).
      2. Else if it reads as a moral/summary line, drop it (humanize.drop_moral_line).
      3. Otherwise strip to the period before the forward-watch phrase in the last line.

    Returns (new_body, what_was_removed).  new_body == body when nothing could be trimmed.
    """
    try:
        from live.humanize import drop_formula_closer, drop_moral_line
    except ImportError:
        return body, ''

    cut, removed = drop_formula_closer(body)
    if removed:
        return cut, removed

    cut, removed = drop_moral_line(body, lang)
    if removed:
        return cut, removed

    return body, ''


def repair_last_line(row: dict, findings: list[dict]) -> dict:
    """Apply deterministic last-line repair for closer_ngram_repeat / closer_forward_watch_stack.

    Mutates row['body'] (and row['text'] when body == text) in place when a change is made.
    Returns a result dict: {'kept': bool, 'removed': str, 'reason': [codes]}.

    Never introduces new claims.  Never HOLDs.  On any failure, returns kept=False and leaves
    the row unchanged.
    """
    codes = [f['code'] for f in findings if f.get('code') in
             ('closer_ngram_repeat', 'closer_forward_watch_stack')]
    if not codes:
        return {'kept': False, 'removed': '', 'reason': []}

    body = str(row.get('body') or '')
    lang = row.get('lang') or (row.get('plan') or {}).get('account_lang') or 'zh'
    lang = str(lang)[:2].lower()

    new_body, removed = _fix_last_line(body, lang)
    if (not removed or new_body == body) and 'closer_ngram_repeat' in codes:
        # Oct 11 (account audit fix 4): a repeated closer is rejected even when it is not a formula / moral line -
        # the last line goes when the post has >= 2 non-empty lines and that line carries no number / ticker
        lines = [l for l in body.splitlines() if l.strip()]
        last = _last_nonempty_line(body)
        if len(lines) >= 2 and not re.search(r'\d|\$[A-Za-z]{2,10}\b', last):
            idx = body.rstrip().rfind(last)
            new_body, removed = body[:idx].rstrip(), last

    if not removed or new_body == body:
        return {'kept': False, 'removed': '', 'reason': codes}

    # Safety: new body must not be empty and must not lose numbers/tickers from earlier lines
    if not new_body.strip():
        return {'kept': False, 'removed': removed, 'reason': codes}

    # Numbers / tickers from all lines except the removed last line must survive
    _NUM_TICK = re.compile(r'\d[\d,.]*|\$[A-Za-z]{2,10}\b')
    earlier_tokens = set(_NUM_TICK.findall('\n'.join(
        l for l in body.splitlines()[:-1]
    )))
    new_tokens = set(_NUM_TICK.findall(new_body))
    if earlier_tokens and not earlier_tokens.issubset(new_tokens):
        return {'kept': False, 'removed': removed, 'reason': codes}

    row['body'] = new_body
    old_text = str(row.get('text') or '')
    if old_text == body or not old_text:
        row['text'] = new_body
    elif old_text.startswith(body):
        row['text'] = new_body + old_text[len(body):]

    return {'kept': True, 'removed': removed, 'reason': codes}
