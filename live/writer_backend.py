"""Public-facing writer backends.

Production copy uses the relay named by environment variables. The local
4B model stays available as a fallback and as the A side of a comparison.
It is not the default public writer.

    WRITER_BASE_URL
    WRITER_API_KEY
    WRITER_MODEL

The key is read from the environment. It is not stored in this file and
it is not written into call logs.
"""
from __future__ import annotations
from pathlib import Path
import os, json, subprocess
import re

ROOT = Path(__file__).resolve().parents[1]


class ProviderQuotaError(RuntimeError):
    retry_requires_external_change=True


def _dotenv():
    found = {}
    for path in (ROOT / '.env', ROOT / '.venv' / '.env'):
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            s = line.strip()
            if not s or s.startswith('#') or '=' not in s:
                continue
            key, value = s.split('=', 1)
            found.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return found


def writer_config():
    """Relay settings. Environment wins over the local env file."""
    file_env = _dotenv()
    base = (os.environ.get('WRITER_BASE_URL') or file_env.get('WRITER_BASE_URL') or '').rstrip('/')
    key = os.environ.get('WRITER_API_KEY') or file_env.get('WRITER_API_KEY') or ''
    model = os.environ.get('WRITER_MODEL') or file_env.get('WRITER_MODEL') or ''
    missing = [name for name, value in (
        ('WRITER_BASE_URL', base), ('WRITER_API_KEY', key), ('WRITER_MODEL', model),
    ) if not value]
    return {'base_url': base, 'api_key': key, 'model': model, 'missing': missing}


def list_models():
    cfg = writer_config()
    if cfg['missing']:
        raise RuntimeError('writer config missing: ' + ', '.join(cfg['missing']))
    url = cfg['base_url'] + '/models'
    proc = subprocess.run(
        ['curl', '-sS', '-m', '40', '-H', 'Authorization: Bearer ' + cfg['api_key'], url],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError('writer model list failed')
    data = json.loads(proc.stdout or '{}')
    return [row.get('id') for row in (data.get('data') or []) if isinstance(row, dict)]


def complete(messages, max_tokens=900, temperature=0.4):
    """One chat completion on the configured writer. Returns text only.

    The request log keeps model name and status. It does not keep the key.
    """
    cfg = writer_config()
    if cfg['missing']:
        raise RuntimeError('writer config missing: ' + ', '.join(cfg['missing']))
    url = cfg['base_url'] + '/chat/completions'
    payload = {
        'model': cfg['model'],
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }
    proc = subprocess.run(
        ['curl', '-sS', '-m', '180',
         '-H', 'Authorization: Bearer ' + cfg['api_key'],
         '-H', 'Content-Type: application/json',
         '--data-binary', '@-',
         url],
        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
    )
    raw = proc.stdout or ''
    if proc.returncode != 0 or not raw.strip():
        err = (proc.stderr or '')[:160]
        raise RuntimeError('writer request failed: ' + err)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError('writer returned non-json: ' + raw[:120]) from exc
    if data.get('error'):
        err = data['error']
        message = err.get('message') if isinstance(err, dict) else str(err)
        cls=ProviderQuotaError if re.search(r'额度不足|预扣费额度失败|insufficient[_ ]quota|insufficient.*(?:balance|credit)',str(message),re.I) else RuntimeError
        raise cls('writer error: ' + str(message)[:180])
    choices = data.get('choices') or []
    if not choices:
        raise RuntimeError('writer returned no choices')
    text = ((choices[0].get('message') or {}).get('content') or '').strip()
    return {
        'text': text,
        'model': cfg['model'],
        'provider': 'writer_relay',
        'usage': data.get('usage'),
        'response_id': data.get('id'),
        'response_model': data.get('model'),
        'finish_reason': choices[0].get('finish_reason'),
        'refusal': (choices[0].get('message') or {}).get('refusal'),
    }


def complete_local(messages, max_tokens=900, temperature=0.4):
    """The existing local 4B, used as fallback and as comparison side A."""
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from model_client import call
    user = '\n\n'.join(m.get('content') or '' for m in messages if m.get('role') != 'system')
    system = '\n\n'.join(m.get('content') or '' for m in messages if m.get('role') == 'system')
    record = call(system + '\n\n' + user if system else user,
                  task='public-writer-local', max_tokens=max_tokens,
                  temperature=temperature, model_role='modern')
    return {
        'text': (record.get('text') or '').strip(),
        'model': 'local-qwen3.5-4b',
        'provider': 'local_mlx',
        'usage': record.get('usage'),
    }
