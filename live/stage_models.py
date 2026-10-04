"""Per-stage model configuration (plan 1.4 subset, pulled into P0-4).

The table maps each stage to a requested model and temperature, and each
requested model to the response model names the relay may report for it.
A response model outside that list is an error, never a silent fallback.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

PATH = Path(__file__).with_name('stage_models.json')
# A stage may be routed to another OpenAI-compatible relay. The entry names the env var
# holding that relay's key (never the key itself), and each key name is bound to its
# host so a credential is never sent to a different provider.
KEY_HOSTS = {'GEMINI_RELAY_API_KEY': ('www.micuapi.ai',),
             'RELAY_API_KEY': ('api.erisedai.com',),
             'ACCOUNT_RELAY_API_KEY': ('api.erisedai.com',)}
ENV_STAGES = ('compose', 'stance')


def _check_route(stage, base_url, api_key_env):
    if (base_url is None) != (api_key_env is None):
        raise ValueError(f'stage {stage}: base_url and api_key_env must be configured together')
    if base_url is None:
        return
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError(f'stage {stage}: base_url must be HTTPS without credentials, query or fragment')
    hosts = KEY_HOSTS.get(api_key_env)
    if hosts is None:
        raise ValueError(f'stage {stage}: api_key_env {api_key_env!r} is not a known relay key name')
    if parsed.hostname not in hosts:
        raise ValueError(f'stage {stage}: {api_key_env} is bound to {", ".join(hosts)}, not {parsed.hostname}')


def _check_rates(stage, rates):
    if rates is None:
        return
    if (not isinstance(rates, (list, tuple)) or len(rates) != 2
            or any(isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) or r <= 0 for r in rates)):
        raise ValueError(f'stage {stage}: rates must be two positive numbers (input, output USD per 1M)')


def validate(table):
    if not isinstance(table, dict):
        raise ValueError('stage model table must be an object')
    accepted = table.get('accepted_response_models')
    if not isinstance(accepted, dict):
        raise ValueError('accepted_response_models must be an object')
    entries = [('default', table.get('default'))] + list((table.get('stages') or {}).items())
    for stage, entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('model'), str) or not entry['model']:
            raise ValueError(f'stage {stage}: model is required')
        temperature = entry.get('temperature', 0.0)
        if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
                or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError(f'stage {stage}: temperature must be within [0, 2]')
        _check_route(stage, entry.get('base_url'), entry.get('api_key_env'))
        _check_rates(stage, entry.get('rates'))
        names = accepted.get(entry['model'])
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError(f'stage {stage}: model {entry["model"]} has no accepted response mapping')
    return table


def load(path=PATH):
    return validate(json.loads(Path(path).read_text()))


def for_stage(table, stage):
    entry = (table.get('stages') or {}).get(stage) or table['default']
    return {'model': entry['model'], 'temperature': float(entry.get('temperature', 0.0))}


def accepted(table, model):
    return list(table['accepted_response_models'][model])


def models(table):
    return sorted({e['model'] for e in [table['default'], *(table.get('stages') or {}).values()]})


def route(table, stage):
    """{'base_url', 'api_key_env'} when the stage is routed to another relay, else None."""
    entry = (table.get('stages') or {}).get(stage) or table['default']
    if entry.get('base_url'):
        return {'base_url': entry['base_url'].rstrip('/'), 'api_key_env': entry['api_key_env']}
    return None


def rates(table, stage):
    entry = (table.get('stages') or {}).get(stage) or table['default']
    return tuple(entry['rates']) if entry.get('rates') else None


def override(table, stage, model, *, temperature=0.0, base_url=None, api_key_env=None, accepted=None, rates=None):
    """New table with one stage on another model (and optionally another relay); input untouched."""
    if not isinstance(model, str) or not model:
        raise ValueError(f'stage {stage}: model is required')
    _check_route(stage, base_url, api_key_env)
    _check_rates(stage, rates)
    out = copy.deepcopy(table)
    entry = {'model': model, 'temperature': temperature}
    if base_url is not None:
        entry.update(base_url=base_url.rstrip('/'), api_key_env=api_key_env)
    if rates is not None:
        entry['rates'] = list(rates)
    out['stages'] = dict(out.get('stages') or {}, **{stage: entry})
    names = list(accepted) if accepted else [model]
    out['accepted_response_models'] = dict(out['accepted_response_models'])
    out['accepted_response_models'][model] = sorted(set(out['accepted_response_models'].get(model, [])) | set(names))
    return validate(out)


def from_env(table, environ):
    """Explicit env configuration: FD_<STAGE>_MODEL [+ FD_<STAGE>_BASE_URL + FD_<STAGE>_API_KEY_ENV,
    FD_<STAGE>_ACCEPTED_MODELS, FD_<STAGE>_RATES "in,out"] for compose and stance. No vars -> unchanged."""
    out = table
    for stage in ENV_STAGES:
        key = 'FD_' + stage.upper() + '_'
        model = environ.get(key + 'MODEL') or None
        base_url = environ.get(key + 'BASE_URL') or None
        key_env = environ.get(key + 'API_KEY_ENV') or None
        if model is None:
            if base_url or key_env:
                raise ValueError(f'{key}BASE_URL / {key}API_KEY_ENV need {key}MODEL')
            continue
        accepted = [m.strip() for m in (environ.get(key + 'ACCEPTED_MODELS') or '').split(',') if m.strip()] or None
        raw_rates = environ.get(key + 'RATES')
        stage_rates = tuple(float(x) for x in raw_rates.split(',')) if raw_rates else None
        out = override(out, stage, model, base_url=base_url, api_key_env=key_env, accepted=accepted, rates=stage_rates)
    return out


def copy_of(table):
    return copy.deepcopy(table)
