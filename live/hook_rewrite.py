"""First-line diversity rewrite (Oct 9, hook1009).

Rewrites only the first line / first sentence of a draft when it was flagged with opener_repeat
or still carries a weak_hook after compose's own rewrite pass.

One call per draft, max FD_HOOK_REWRITE_MAX (default 12) per run, only when FD_HOOK_DIVERSITY != '0'.

Acceptance rules (all must pass, else keep original):
  - new first line has no weak opener (hook_findings returns empty for the first line alone)
  - digits / $tickers / @handles in the new first line are a subset of those in the whole original draft
  - editorial_style.findings on the new body adds no new HARD code
  - length change <= 40%

The client object is the same 'compose' stage client daily_compose passes to compose_source; provider
routing and the budget ledger are already wired inside it.
"""
from __future__ import annotations

import json
import re
from typing import Any

from live import editorial_style, hook_voice

_DIGITS_TICKERS = re.compile(r'\d[\d,.]*|\$[A-Za-z]{2,10}\b|@[A-Za-z0-9_]{1,50}\b')

MAX_LENGTH_CHANGE = 0.40


def _tokens_in(text: str) -> set[str]:
    return set(_DIGITS_TICKERS.findall(str(text or '')))


def _first_line(body: str) -> str:
    return next((ln.strip() for ln in str(body or '').splitlines() if ln.strip()), '')


def _replace_first_line(body: str, new_first: str) -> str:
    """Replace the first non-empty line of body with new_first, preserving the rest."""
    lines = str(body or '').splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.strip():
            lines[i] = new_first + ('\n' if ln.endswith('\n') else '')
            return ''.join(lines)
    return new_first


def rewrite_first_line(
    client: Any,
    row: dict,
    avoid_openers: list[str],
    lang: str,
) -> dict:
    """Make ONE compose-stage call to rewrite only the first line of row['body'].

    Returns a dict:
      {'from': old_first_line, 'to': new_first_line, 'reason': [codes], 'kept': bool}

    Updates row['body'] and row['text'] in place only when the rewrite is accepted.
    row['text'] = row['body'] when body == text (same-language source, no attribution frame);
    when there is a frame, only the body part is swapped.

    kept=True only when the rewrite was accepted. On any exception: logs one line, returns {'kept': False, 'error': ...}
    and the draft is unchanged.
    """
    body = str(row.get('body') or '')
    old_first = _first_line(body)
    codes = sorted({
        f['code'] for f in (row.get('post_checks') or [])
        if f.get('code') in ('weak_hook', 'opener_repeat')
    })

    avoid_str = ', '.join(f'"{p}"' for p in avoid_openers[:30]) if avoid_openers else '(see instructions)'
    prompt = (
        'Rewrite ONLY the first line / first sentence of the following draft. '
        'Open on the most concrete number or named fact already present in the draft. '
        'Do NOT add any new facts, numbers, or claims not already in the draft. '
        'Do NOT use 不是X而是Y / 本质上 / 值得注意的是. '
        f'Do NOT start with any of these openers: {avoid_str}. '
        'Return JSON: {"first_line": "..."}  (the new first line only, nothing else).\n\n'
        f'DRAFT:\n{body}'
    )
    messages = [{'role': 'user', 'content': prompt}]
    try:
        resp = client('compose', messages, 4000)   # pro model: thinking tokens count
        raw = (resp.get('text') or resp.get('content') or '').strip()
        # accept {"first_line": "..."} or bare text wrapped in json
        try:
            parsed = json.loads(raw)
            new_first = str(parsed.get('first_line') or '').strip()
        except (json.JSONDecodeError, AttributeError):
            m = re.search(r'"first_line"\s*:\s*"([^"]+)"', raw)
            new_first = m.group(1).strip() if m else raw.split('\n')[0].strip()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.warning('hook_rewrite: exception on %s: %s', row.get('id'), exc)
        return {'from': old_first, 'to': '', 'reason': codes, 'kept': False, 'error': str(exc)[:200]}

    if not new_first:
        return {'from': old_first, 'to': '', 'reason': codes, 'kept': False, 'error': 'empty response'}

    # --- acceptance checks ---

    # 1. no weak opener in the new first line
    if hook_voice.hook_findings(new_first, lang):
        return {'from': old_first, 'to': new_first, 'reason': codes, 'kept': False,
                'reject': 'still weak opener'}

    # 2. digits/$tickers/@handles in new first line must be a subset of original draft's
    new_tokens = _tokens_in(new_first)
    orig_tokens = _tokens_in(body)
    if not new_tokens.issubset(orig_tokens):
        extra = new_tokens - orig_tokens
        return {'from': old_first, 'to': new_first, 'reason': codes, 'kept': False,
                'reject': f'new tokens not in original: {extra}'}

    # 3. editorial_style hard codes must not increase
    orig_hard = {f['code'] for f in editorial_style.findings(body, lang) if f.get('code') in editorial_style.HARD_CODES}
    new_body = _replace_first_line(body, new_first)
    new_hard = {f['code'] for f in editorial_style.findings(new_body, lang) if f.get('code') in editorial_style.HARD_CODES}
    added_hard = new_hard - orig_hard
    if added_hard:
        return {'from': old_first, 'to': new_first, 'reason': codes, 'kept': False,
                'reject': f'new hard codes: {sorted(added_hard)}'}

    # 4. length change <= 40%
    if old_first:
        change = abs(len(new_first) - len(old_first)) / max(1, len(old_first))
        if change > MAX_LENGTH_CHANGE:
            return {'from': old_first, 'to': new_first, 'reason': codes, 'kept': False,
                    'reject': f'length change {change:.0%} > 40%'}

    # accepted — update body and text in place
    row['body'] = new_body
    # text derives from body: same-language source -> body IS the text;
    # cross-language source -> text = body + attribution frame (frame appended after body)
    old_text = str(row.get('text') or '')
    if old_text == body or not old_text:
        # same-language: text == body
        row['text'] = new_body
    elif old_text.startswith(body):
        # cross-language: frame is a suffix of text; replace the body prefix
        row['text'] = new_body + old_text[len(body):]
    else:
        # fallback: if old first line is unambiguously at the start of text, replace it there too
        if old_text.lstrip().startswith(old_first):
            row['text'] = old_text.replace(old_first, new_first, 1)

    return {'from': old_first, 'to': new_first, 'reason': codes, 'kept': True}
