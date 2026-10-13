"""LLM call through Fiona's Claude subscription (Oct 13): the `claude` CLI in print mode with the API-key / base-URL
env vars removed, so it bills the subscription, never a relay. Returns (text, meta); meta has the CLI's notional
total_cost_usd (subscription: not billed per call). FD_CLAUDE_MODEL picks the model (default: CLI default)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

STRIP = ('ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
LEDGER = []   # per-process notional cost log


def available():
    return bool(shutil.which('claude') or os.path.exists(os.path.expanduser('~/.local/bin/claude')))


def ask(prompt, *, system=None, timeout=300, model=None):
    exe = shutil.which('claude') or os.path.expanduser('~/.local/bin/claude')
    env = {k: v for k, v in os.environ.items() if k not in STRIP}
    cmd = [exe, '-p', '--output-format', 'json', '--tools', '']
    m = model or os.environ.get('FD_CLAUDE_MODEL')
    if m:
        cmd += ['--model', m]
    if system:
        cmd += ['--append-system-prompt', system]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=env,
                       cwd='/tmp')
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f'claude cli failed rc={r.returncode}: {(r.stderr or r.stdout)[:300]}')
    if out.get('is_error'):
        raise RuntimeError(f"claude cli error: {str(out.get('result'))[:300]}")
    meta = {'cost_usd_notional': out.get('total_cost_usd') or 0.0, 'model': m or 'cli-default',
            'duration_ms': out.get('duration_ms')}
    LEDGER.append(meta)
    return out.get('result') or '', meta


def ask_json(prompt, **kw):
    text, meta = ask(prompt, **kw)
    m = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    body = m.group(1) if m else text
    i = min([x for x in (body.find('{'), body.find('[')) if x >= 0] or [0])
    return json.loads(body[i:].strip()), meta
