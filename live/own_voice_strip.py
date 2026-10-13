"""Oct 13 (Fiona): every FD draft reads as the account's OWN view - no attribution / credit line, no @handle.

Cheap deterministic check (compose_prevent.py / archive_voice.py style) applied in-generation and at the inbox
chokepoint (compose_inbox.add): drops whole credit lines ('(translated from @x)', '译自…', '来源：@x', 'via @x',
'h/t @x', '(from @x)', 'Source: …') and removes any remaining @handle. FD_OWN_VOICE_STRIP=0 disables.
"""
from __future__ import annotations

import os
import re

CREDIT_LINE = re.compile(
    r'^\s*[(（\[]?\s*(?:translated\s+from|translation\s+of|译自|翻译自|编译自|来源\s*[:：]|出处\s*[:：]|source\s*[:：]|'
    r'via\s+@|h/?t\s+@|hat\s*tip|credit\s*[:：]|from\s+@|cc\s+@|by\s+@)[^\n]*$', re.I)
HANDLE = re.compile(r'(?<![\w.])@[A-Za-z0-9_]{1,15}\b')
TEXT_FIELDS = ('text', 'body', 'edited_text', 'final_text', 'reviewed_text', 'approved_text')


def enabled(env=None):
    return (env or os.environ).get('FD_OWN_VOICE_STRIP', '1') != '0'


def findings(text):
    out = []
    for line in (text or '').splitlines():
        if CREDIT_LINE.match(line):
            out.append({'code': 'attribution_line', 'level': 'hard', 'detail': line.strip()[:80]})
    for h in HANDLE.findall(text or ''):
        out.append({'code': 'handle_in_body', 'level': 'hard', 'detail': h})
    return out


def strip(text):
    """Return (clean_text, changed)."""
    if not text or not isinstance(text, str):
        return text, False
    lines = [l for l in text.splitlines() if not CREDIT_LINE.match(l)]
    # a line that is only handles goes; an inline handle loses its '@' so the sentence still parses
    lines = [l for l in lines if not (HANDLE.search(l) and not HANDLE.sub('', l).strip(' \t:：,，()（）-—|'))]
    lines = [HANDLE.sub(lambda m: m.group(0)[1:], l) for l in lines]
    out = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()
    return out, out != text.strip()


def clean_row(row):
    """Strip every text field of a draft row in place; returns list of fields changed."""
    changed = []
    if not enabled():
        return changed
    for k in TEXT_FIELDS:
        if isinstance(row.get(k), str):
            new, ch = strip(row[k])
            if ch:
                row[k] = new; changed.append(k)
    for part in row.get('thread_parts') or [] if isinstance(row.get('thread_parts'), list) else []:
        if isinstance(part, dict) and isinstance(part.get('text'), str):
            new, ch = strip(part['text'])
            if ch:
                part['text'] = new; changed.append('thread_parts')
    if changed and row.get('attribution_line') not in (None, 'none'):
        row['attribution_line'] = None
    if changed:
        row['own_voice_strip'] = sorted(set(changed))
    return changed
