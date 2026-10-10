"""Oct 10 17:30 (PM decision B): fluency check for the short non-argument shapes (one-line take, quick note,
question, reaction, short list).

A one-liner squeezed to 8-36 characters can come out garbled ('我看Zcash ETF首月超10亿美元，机构所谓变严只是换花样搞多元资产').
Every draft that took a nat_shape gets one judge call (compose stage, flat-rate subrouter): is it grammatical, natural
{zh|en} and one complete thought a reader understands without context? When it is not, the judge's minimal rewrite
is used only if it keeps every number (humanize._fidelity_ok) and adds no name / ticker / handle
(humanize._entities_ok), stays short, and passes a second judge call; otherwise the caller re-composes the post in a
normal (argument) shape. FD_FLUENCY=0 turns it off. Judge failures (API / parse) keep the draft as is.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

PROMPT = '''You are a strict native-speaker copy editor for short {lang_name} social posts about markets.

Post:
<<<
{body}
>>>

Judge it on exactly two things:
1. fluent: grammatical, natural {lang_name} a native finance poster would write; no garbled clause joins, no missing
   verb / object, no word salad, no machine-translation feel. Casual style, fragments and slang are fine if a native
   speaker would say them.
2. complete: one complete thought a reader understands on its own (what is being said about what), not a dangling
   half-sentence or a list of noun phrases with no point.

If both hold, return {{"fluent": true, "complete": true, "issue": "", "rewrite": ""}}.
Otherwise return fluent / complete as judged, a short issue, and "rewrite": a minimal fix that reads naturally,
keeps every number, name, ticker and fact exactly, adds nothing new, keeps the same point and stays about as short.
Return JSON only.'''


def enabled(env=None):
    return (env or os.environ).get('FD_FLUENCY', '1') != '0'


def _parse(text):
    text = (text or '').strip().strip('`')
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def judge(client: Any, body: str, lang: str) -> dict | None:
    """{'fluent','complete','issue','rewrite'} or None when the call / parse failed."""
    prompt = PROMPT.format(lang_name='Chinese (Simplified)' if lang == 'zh' else 'English', body=body)
    try:
        resp = client('compose', [{'role': 'user', 'content': prompt}], 4000)
    except Exception:   # noqa: BLE001 - a judge failure never blocks a draft
        return None
    text = (resp.get('text') or resp.get('content') or '') if isinstance(resp, dict) else str(resp or '')
    out = _parse(text)
    if out is None:
        return None
    return {'fluent': bool(out.get('fluent')), 'complete': bool(out.get('complete')),
            'issue': str(out.get('issue') or '')[:200], 'rewrite': str(out.get('rewrite') or '').strip()}


def _length(text):
    return len(re.sub(r'\s+', '', text or ''))


def rewrite_ok(orig: str, new: str, lang: str) -> bool:
    from live import humanize as hum
    if not new or new == orig:
        return False
    if _length(new) > max(int(_length(orig) * 1.4), _length(orig) + 12):
        return False
    return bool(hum._fidelity_ok(orig, new) and hum._entities_ok(orig, new))


def _set_body(row, new):
    old = row.get('body') or ''
    row['body'] = new
    t = row.get('text')
    if t == old or not t:
        row['text'] = new
    elif old and old in str(t):
        row['text'] = str(t).replace(old, new, 1)


def nat_shape(row):
    pf = row.get('post_format')
    return pf.get('nat_shape') if isinstance(pf, dict) else None


def check_row(row: dict, client: Any, lang: str) -> dict:
    """Judge one nat-shape draft in place. Returns {'ok': bool, 'action': 'pass'|'rewrite'|'fallback'|'skip', ...};
    on 'fallback' the body is untouched and the caller re-composes in a normal shape."""
    body = row.get('body') or ''
    v = judge(client, body, lang)
    if v is None:
        return {'ok': True, 'action': 'skip', 'issue': 'judge unavailable'}
    if v['fluent'] and v['complete']:
        return {'ok': True, 'action': 'pass'}
    new = v['rewrite']
    if rewrite_ok(body, new, lang):
        v2 = judge(client, new, lang)
        if v2 and v2['fluent'] and v2['complete']:
            _set_body(row, new)
            return {'ok': True, 'action': 'rewrite', 'issue': v['issue'], 'from': body, 'to': new}
    return {'ok': False, 'action': 'fallback', 'issue': v['issue'], 'from': body}


def apply_batch(results: list[dict], client_factory: Callable[[], Any],
                recompose: Callable[[dict], dict | None] | None = None) -> list[dict]:
    """Fluency-check every nat-shape draft; garbled ones are rewritten or re-composed (recompose(row) -> new result
    or None). Results are changed in place (identity kept). Returns the per-draft log."""
    log = []
    if not enabled():
        return log
    for r in results:
        shape = nat_shape(r)
        if not shape or not r.get('body') or r.get('status') == 'error':
            continue
        lang = (r.get('plan') or {}).get('account_lang') or 'zh'
        out = check_row(r, client_factory(), lang)
        entry = {'account_id': r.get('account_id'), 'id': r.get('id'), 'shape': shape, **out}
        if out['action'] == 'fallback' and recompose is not None:
            try:
                new = recompose(r)
            except Exception as exc:   # noqa: BLE001
                new, entry['recompose_error'] = None, str(exc)[:200]
            if new and new.get('body') and new.get('status') != 'error':
                keep = {'fluency': None}
                r.clear()
                r.update(new)
                r.update(keep)
                entry['to'] = new.get('body')
                entry['action'] = 'fallback_recomposed'
            else:
                entry['action'] = 'fallback_failed'   # keep the draft but hold it for review
                r['draft_status'] = 'needs_review'
                r.setdefault('post_checks', []).append({'code': 'short_not_fluent', 'level': 'hard',
                                                        'detail': out.get('issue')})
        r['fluency'] = {k: v for k, v in entry.items() if k not in ('account_id', 'id')}
        print(f"[fluency] {r.get('account_id')} {shape} {entry['action']} {entry.get('issue', '')[:80]!r}", flush=True)
        log.append(entry)
    return log
