"""Oct 10 (Fiona, shared targets): up to 2 of our accounts may engage one target post (live/engagement.open_for).
Readers see both drafts under the same post, so the second one must take a clearly different angle / opening - a
different lead fact or a counterpoint, never the sibling's first line or lead number.

- siblings(rows, row): the other ready / published drafts of the day on the same target post (earlier ones first).
- rewrite(client, row, sibs, lang): ONE compose-stage call (subrouter) that rewrites the draft with the sibling in
  view; accepted only when engagement.sibling_findings is clean, every number is already in the draft or the target
  post, no new engagement / editorial HARD code, and the length stays within +-50%. Updates row body/text in place.
FD_ENGAGE_SIBLING=0 turns it off.
"""
from __future__ import annotations

import json
import re

from live import editorial_style, engagement

MAX_LENGTH_CHANGE = 0.5


def target_id(row):
    e = _eng(row)
    m = re.search(r'/status/(\d+)', str(e.get('url') or row.get('quote_target_url') or row.get('reply_to_url') or ''))
    return m.group(1) if m and e.get('mode') else None


def siblings(rows, row):
    """Other non-superseded, ready (or already posted) engagement drafts on row's target post, oldest first."""
    pid = target_id(row)
    if not pid:
        return []
    out = [r for r in rows if r is not row and r.get('id') != row.get('id') and target_id(r) == pid
           and not r.get('superseded') and r.get('account_id') != row.get('account_id')
           and r.get('draft_status') in ('draft_ready', 'published') and str(r.get('text') or '').strip()]
    out.sort(key=lambda r: (str(r.get('stored_at') or ''), str(r.get('id') or '')))
    return [{'account': r.get('account_id'), 'mode': (r.get('engagement') or {}).get('mode'),
             'text': r.get('body') or r.get('text')} for r in out]


def _eng(row):
    e = row.get('engagement') if isinstance(row.get('engagement'), dict) else None
    return e or ((row.get('plan') or {}).get('engagement') if isinstance(row.get('plan'), dict) else None) or {}


def _target_text(row):
    src = row.get('source') if isinstance(row.get('source'), dict) else {}
    plan = row.get('plan') if isinstance(row.get('plan'), dict) else {}
    return ' '.join(dict.fromkeys(str(x or '') for x in (src.get('title'), src.get('original_text'), src.get('text'),
                                                           plan.get('title'))))


def _avoid(sib):
    """What line 1 must not repeat from the sibling's first line: its lead number and content words."""
    f = engagement.first_line(sib.get('text'))
    nums = re.findall(r'\$?\d[\d,.]*\s*(?:%|million|billion|[kmb]\b|万|亿)?', f, re.I)[:1]
    words = sorted(w for w in engagement.topic_tokens(f) if not re.search(r"\d", w))[:8]
    return ', '.join([f'the number {n.strip()} (in any form)' for n in nums] + [f'"{w}"' for w in words]) or 'its wording'


def _num_ok(new, allowed_text):
    allowed = engagement.numbers(allowed_text)
    return all(any(engagement._same_num(n, a) for a in allowed) for n in engagement.numbers(new))


def _hard(body, mode, lang):
    eng = {f['code'] for f in engagement.findings(body, mode, lang) if f['code'] in engagement.HARD_CODES}
    ed = {f['code'] for f in editorial_style.findings(body, lang) if f.get('code') in editorial_style.HARD_CODES}
    return eng | ed


def rewrite(client, row, sibs, lang):
    body = str(row.get('body') or row.get('text') or '')
    mode = _eng(row).get('mode')
    found = engagement.sibling_findings(body, sibs)
    if not found:
        return {'kept': False, 'skipped': 'no sibling repeat'}
    sib = sibs[0]
    prompt = (
        f"This is a {mode} from one of our X accounts under @{_eng(row).get('author') or 'the author'}'s "
        f"post. Another of our accounts (@{sib.get('account')}) already {sib.get('mode') or 'engage'}s the same post; "
        'readers will see both. Rewrite OUR draft so it takes a clearly different angle and opening: lead with a '
        "different fact already in our draft or the target post, or push back on the other draft's point. Do NOT "
        f"open with the other draft's first line, its wording or its lead number: our FIRST LINE must not contain "
        f"{_avoid(sib)}. A good first line here is our own take or counterpoint, or a different fact; the shared "
        "facts can come later in the draft. Keep our account's voice, the same "
        'language, about the same length, line breaks between short paragraphs. Do NOT add any number, name or claim '
        'that is not in our draft or the target post. No 不是X而是Y / 本质上 / 值得注意的是, no praise.\n'
        'Return JSON: {"text": "..."}\n\n'
        f"TARGET POST: {_target_text(row)[:600]}\n\nOTHER ACCOUNT'S DRAFT:\n{str(sib.get('text') or '')[:600]}\n\n"
        f'OUR DRAFT:\n{body}')
    try:
        resp = client('compose', [{'role': 'user', 'content': prompt}], 4000)
        raw = (resp.get('text') or resp.get('content') or '').strip()
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
        try:
            new = str(json.loads(raw).get('text') or '').strip()
        except (json.JSONDecodeError, AttributeError):
            m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.S)
            new = json.loads('"' + m.group(1) + '"').strip() if m else ''
    except Exception as exc:   # noqa: BLE001
        return {'kept': False, 'from': engagement.first_line(body), 'error': f'{type(exc).__name__}: {str(exc)[:160]}'}
    res = {'from': engagement.first_line(body), 'to': engagement.first_line(new), 'reason': found[0]['detail'],
           'kept': False}
    if not new:
        return dict(res, reject='empty response')
    if engagement.sibling_findings(new, sibs):
        return dict(res, reject='still repeats the sibling: ' + engagement.sibling_findings(new, sibs)[0]['detail'])
    if not _num_ok(new, body + ' ' + _target_text(row)):
        return dict(res, reject='number not in the draft / target post')
    if _hard(new, mode, lang) - _hard(body, mode, lang):
        return dict(res, reject=f'new hard codes {sorted(_hard(new, mode, lang) - _hard(body, mode, lang))}')
    if abs(len(new) - len(body)) / max(1, len(body)) > MAX_LENGTH_CHANGE:
        return dict(res, reject='length change > 50%')
    old_text = str(row.get('text') or '')
    row['body'] = new
    row['text'] = new if (old_text == body or not old_text) else (
        new + old_text[len(body):] if old_text.startswith(body) else new)
    return dict(res, kept=True)
