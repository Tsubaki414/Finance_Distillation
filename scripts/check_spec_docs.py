"""P0-4a spec sync check: current-state docs must describe the post_type form.

Scans the current-state sections of CLAUDE.md, docs/CURRENT_DELIVERY_PLAN.md,
the whole of docs/DAILY_PIPELINE.md and live/owned_accounts.json. Prints every
violating line. "Translation + light edit" may only appear as the description
of aphorism_translation (Morris). Exit code 1 when any line violates.
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('source_grounded_translation_or_light_edit', 'historical_translation_light_edit',
             'same-language light editing', '同语言轻编', '同语言直接使用原文')
LIGHT_EDIT = re.compile(r'轻编|light[ -]?edit|light[ -]?localization|minimal localization', re.I)
ALLOWED_TREATMENTS = {'aphorism_translation', 'composed_post'}


def _section(text, heading_prefix):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading_prefix))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
    return [(i + 1, lines[i]) for i in range(start, end)]


def scopes(root=ROOT):
    claude = (root / 'CLAUDE.md').read_text()
    plan = (root / 'docs' / 'CURRENT_DELIVERY_PLAN.md').read_text()
    daily = (root / 'docs' / 'DAILY_PIPELINE.md').read_text()
    return {
        'CLAUDE.md': _section(claude, '## 2026-10-02 当前状态'),
        'docs/CURRENT_DELIVERY_PLAN.md': _section(plan, '## 目标与范围'),
        'docs/DAILY_PIPELINE.md': list(enumerate(daily.splitlines(), 1)),
    }


def hits(root=ROOT):
    found = []
    for name, lines in scopes(root).items():
        for number, line in lines:
            reason = next((f'forbidden:{f}' for f in FORBIDDEN if f in line), None)
            if not reason and LIGHT_EDIT.search(line) and 'aphorism_translation' not in line:
                reason = 'light_edit_outside_aphorism_translation'
            if not reason and 'production.py' in line:
                reason = 'legacy_production_entry'
            if reason:
                found.append({'file': name, 'line': number, 'reason': reason, 'text': line[:160]})
        mentions = any('post_type' in line or '帖型' in line for _, line in lines)
        if not mentions:
            found.append({'file': name, 'line': 0, 'reason': 'no_post_type_reference', 'text': ''})
    accounts = json.loads((root / 'live' / 'owned_accounts.json').read_text())['accounts']
    raw = (root / 'live' / 'owned_accounts.json').read_text().splitlines()
    for number, line in enumerate(raw, 1):
        reason = next((f'forbidden:{f}' for f in FORBIDDEN if f in line), None)
        if reason:
            found.append({'file': 'live/owned_accounts.json', 'line': number, 'reason': reason, 'text': line.strip()[:160]})
    for account in accounts:
        expected = 'aphorism_translation' if account['id'] == 'en_morris_archive' else 'composed_post'
        if account.get('treatment') not in ALLOWED_TREATMENTS or account['treatment'] != expected:
            found.append({'file': 'live/owned_accounts.json', 'line': 0, 'reason': 'treatment',
                          'text': f"{account['id']}: {account.get('treatment')}"})
    return found


def main():
    found = hits()
    for row in found:
        print(f"{row['file']}:{row['line']}: {row['reason']}: {row['text']}")
    print(f'{len(found)} violating line(s)')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
