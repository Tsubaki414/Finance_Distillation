"""The single place where a model request's messages are assembled (P0-2).

Callers name a base template (by passing a registered template string) and the
ordered outer rules that apply to the stage. The stage client (ContentStages) may
contribute a stage context: a replacement template, appended addenda and payload
extras. Everything is joined here, once, and recorded:

    template_id / template_sha256   which registered base template was asked for
    effective_template_id           what was actually sent as the base (after replace)
    rules_applied / rules_dropped   outer rules that reached / did not reach the model
    messages_sha256                 sha256 of the exact messages handed to transport

This module changes no prompt wording; the drop of outer rules on replaced
stages is preserved as-is and made explicit (restoring them is a separate,
replay-checked change).
"""
from __future__ import annotations

import hashlib
import json

from live import distillation_prompts as prompts
from live import source_hygiene as hygiene

_TEMPLATES: dict[str, str] = {}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def messages_sha256(messages) -> str:
    return sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True))


def register(template_id: str, text: str) -> str:
    existing = _TEMPLATES.get(template_id)
    if existing is not None and existing != text:
        raise ValueError('Template id re-registered with different text: ' + template_id)
    _TEMPLATES[template_id] = text
    return text


def template_id(text: str) -> str:
    for key, value in _TEMPLATES.items():
        if value == text:
            return key
    return 'unregistered:' + sha256(text)[:12]


for _name in ('ROUTE', 'SELECT', 'TRANSLATE', 'LOCALIZE', 'QA'):
    register('prompts.' + _name, getattr(prompts, _name))
SOURCE_HYGIENE = register('prompts.SOURCE_HYGIENE', prompts.DATA_RULE + '\n' + hygiene.editorial_prompt())


def assemble(stage, base, payload, *, outer_rules=(), stage_context=None):
    """Return (messages, record). outer_rules: ordered [(rule_id, text)]."""
    context = stage_context or {}
    base_id = template_id(base)
    replace = context.get('replace')
    if replace:
        effective_id, system = replace
        applied, dropped = [], [rule_id for rule_id, _ in outer_rules]
    else:
        effective_id, system = base_id, base
        applied, dropped = [rule_id for rule_id, _ in outer_rules], []
        for _, text in outer_rules:
            system += '\n\n' + text
    for rule_id, text in context.get('append', ()):
        system += '\n\n' + text
        applied.append(rule_id)
    payload = {**payload, **context.get('payload_extras', {})}
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    record = {'stage': stage, 'template_id': base_id, 'template_sha256': sha256(base),
              'effective_template_id': effective_id, 'rules_applied': applied,
              'rules_dropped': dropped, 'messages_sha256': messages_sha256(messages)}
    return messages, record
