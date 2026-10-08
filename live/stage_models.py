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
GEMINI_HOST = 'generativelanguage.googleapis.com'
GEMINI_KEY_PATTERN = r'AQ\.\S+'


GEMINI_RELAY_BASE = 'https://www.micuapi.ai/v1'
GEMINI_RELAY_HOST = 'www.micuapi.ai'
# Oct 8 (Fiona): subrouter, a flat-rate ("unlimited token") OpenAI-compatible relay, is the PRIMARY Gemini provider
# whenever its key is present (SUBROUTER_API_KEY, sourced from ~/.secrets/subrouter.env; never logged / committed).
# Every Gemini stage then carries a provider fallback to micuapi with the SAME model (errors / 429 / 5xx / quota /
# missing key). Calls served by subrouter are recorded in the ledger at a nominal list-price cost tagged
# provider=subrouter but do not count toward the daily or cumulative caps (ml/budget.py: counts_toward_cap=False).
SUBROUTER_BASE = 'https://subrouter.ai/v1'
SUBROUTER_HOST = 'subrouter.ai'
SUBROUTER_PROVIDER = 'subrouter'
# subrouter model ids for the pipeline's Gemini ids (/models checked Oct 8): gemini-3.1-pro-preview is listed as-is;
# gemini-3-flash-preview is not (503 model_not_found) - its GA id gemini-3-flash is the same model family/tier.
SUBROUTER_MODEL_MAP = {'gemini-3-flash-preview': 'gemini-3-flash'}
FLAT_RATE_HOSTS = (SUBROUTER_HOST,)
GEMINI_PROVIDERS = ('subrouter', 'relay', 'official')
# Oct 7 (Fiona): official Gemini credits depleted (402); the micuapi relay serves the same Gemini model names.
# Oct 8: default = subrouter when SUBROUTER_API_KEY is set (micuapi as provider fallback), else relay (micuapi only).
DEFAULT_GEMINI_PROVIDER = 'relay'


def is_gemini_native(base_url):
    return bool(base_url) and urlsplit(base_url).hostname == GEMINI_HOST


def is_gemini_relay(base_url):
    """An OpenAI-compatible Gemini relay (micuapi, or subrouter for gemini-* models)."""
    return bool(base_url) and urlsplit(base_url).hostname in (GEMINI_RELAY_HOST, SUBROUTER_HOST)


def is_subrouter(base_url):
    return bool(base_url) and urlsplit(base_url).hostname == SUBROUTER_HOST


def is_flat_rate(base_url):
    """Flat-rate provider: calls are ledgered at a nominal cost but never count toward a spending cap."""
    return bool(base_url) and urlsplit(base_url).hostname in FLAT_RATE_HOSTS


def provider_name(base_url):
    host = urlsplit(base_url).hostname if base_url else None
    return {SUBROUTER_HOST: SUBROUTER_PROVIDER, GEMINI_RELAY_HOST: 'micuapi', GEMINI_HOST: 'gemini_official'}.get(host, host)


def is_gemini_route(base_url):
    """A Gemini route on either provider (official native API or the micuapi OpenAI-compatible relay)."""
    return is_gemini_native(base_url) or is_gemini_relay(base_url)


def gemini_provider(environ=None):
    import os
    env = environ if environ is not None else os.environ
    default = SUBROUTER_PROVIDER if (env.get('SUBROUTER_API_KEY') or '').strip() else DEFAULT_GEMINI_PROVIDER
    value = (env.get('FD_GEMINI_PROVIDER') or default).strip()
    if value not in GEMINI_PROVIDERS:
        raise ValueError(f'FD_GEMINI_PROVIDER must be one of {GEMINI_PROVIDERS}')
    return value


def apply_gemini_provider(table, environ=None):
    """Move every Gemini stage to the selected provider (FD_GEMINI_PROVIDER=subrouter|relay|official; default
    subrouter when SUBROUTER_API_KEY is set, else relay).

    relay / official: same model names, rates, max_tokens and thinking level; only base_url + key env change, no
    fallback is added. subrouter: the stage runs on subrouter (model id mapped by SUBROUTER_MODEL_MAP) with a
    provider fallback (`provider_fallback: true`) to the same Gemini model on micuapi - not a model fallback."""
    import os
    env = environ if environ is not None else os.environ
    provider = gemini_provider(env)
    if provider == SUBROUTER_PROVIDER:
        # FD_SUBROUTER_STAGES=stance,extract,... limits subrouter to those stages (default: every Gemini stage); the
        # others stay on micuapi alone. Oct 8 probe: subrouter's gemini-3.1-pro-preview is served through Google
        # Antigravity channels with a ~250-token injected coding-assistant prompt (flash ids showed none).
        only = {x.strip() for x in (env.get('FD_SUBROUTER_STAGES') or '').split(',') if x.strip()} or None
        return _apply_subrouter(apply_gemini_provider(table, {'FD_GEMINI_PROVIDER': 'relay'}), only)
    base_url, key_env = ((GEMINI_RELAY_BASE, 'GEMINI_RELAY_API_KEY') if provider == 'relay'
                         else ('https://' + GEMINI_HOST + '/v1beta', 'GEMINI_API_KEY'))
    out = copy.deepcopy(table)
    for stage, entry in (out.get('stages') or {}).items():
        if entry.get('base_url') and is_gemini_route(entry['base_url']) and entry['base_url'].rstrip('/') != base_url:
            entry.update(base_url=base_url, api_key_env=key_env)
    return validate(out)


def _apply_subrouter(table, only=None):
    out = copy.deepcopy(table)
    out['accepted_response_models'] = dict(out['accepted_response_models'])
    rates_table = dict(out.get('model_rates') or {})
    for stage, entry in (out.get('stages') or {}).items():
        if not (entry.get('base_url') and is_gemini_route(entry['base_url'])) or is_subrouter(entry['base_url']):
            continue
        if entry.get('fallback') or (only is not None and stage not in only):
            continue   # a documented model fallback stays as configured (no nested fallback); stage not selected
        model = entry['model']
        sub_model = SUBROUTER_MODEL_MAP.get(model, model)
        fb = {'model': model, 'temperature': entry.get('temperature', 0.0), 'base_url': GEMINI_RELAY_BASE,
              'api_key_env': 'GEMINI_RELAY_API_KEY', 'provider_fallback': True}
        for k in ('rates', 'max_tokens'):
            if entry.get(k):
                fb[k] = copy.deepcopy(entry[k])
        entry.update(model=sub_model, base_url=SUBROUTER_BASE, api_key_env='SUBROUTER_API_KEY', fallback=fb)
        if sub_model != model and model in rates_table:
            rates_table.setdefault(sub_model, rates_table[model])
        if sub_model not in out['accepted_response_models']:
            out['accepted_response_models'][sub_model] = [sub_model]
    if rates_table:
        out['model_rates'] = rates_table
    return validate(out)


def gemini_token(raw):
    """The usable token inside GEMINI_API_KEY (the env value carries a prefix). Never log the result."""
    import re
    m = re.search(GEMINI_KEY_PATTERN, raw or '')
    if not m:
        raise ValueError('GEMINI_API_KEY does not contain an AQ. token')
    return m.group(0)
# A stage may be routed to another OpenAI-compatible relay. The entry names the env var
# holding that relay's key (never the key itself), and each key name is bound to its
# host so a credential is never sent to a different provider.
KEY_HOSTS = {'GEMINI_RELAY_API_KEY': ('www.micuapi.ai',),
             # Official Gemini API (Oct 7): native generateContent with the x-goog-api-key header.
             'GEMINI_API_KEY': (GEMINI_HOST,),
             'RELAY_API_KEY': ('api.erisedai.com',),
             'ACCOUNT_RELAY_API_KEY': ('api.erisedai.com',),
             'SUBROUTER_API_KEY': (SUBROUTER_HOST,)}
ENV_STAGES = ('compose', 'stance', 'extract', 'extract_flash', 'view_enrich')
GEMINI_MODELS = ('gemini-3-flash-preview', 'gemini-3.1-pro-preview', 'gemini-3-flash')


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
        if entry.get('thinking_level') is not None and entry['thinking_level'] not in THINKING_LEVELS:
            raise ValueError(f'stage {stage}: thinking_level must be one of {THINKING_LEVELS}')
        mt = entry.get('max_tokens')
        if mt is not None and (isinstance(mt, bool) or not isinstance(mt, int) or mt <= 0):
            raise ValueError(f'stage {stage}: max_tokens must be a positive integer')
        names = accepted.get(entry['model'])
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError(f'stage {stage}: model {entry["model"]} has no accepted response mapping')
        fb = entry.get('fallback')
        if fb is not None:
            if not isinstance(fb, dict) or not isinstance(fb.get('model'), str) or not fb['model'] or 'fallback' in fb:
                raise ValueError(f'stage {stage}: fallback needs a model (and no nested fallback)')
            _check_route(stage + '.fallback', fb.get('base_url'), fb.get('api_key_env'))
            _check_rates(stage + '.fallback', fb.get('rates'))
            mt = fb.get('max_tokens')
            if mt is not None and (isinstance(mt, bool) or not isinstance(mt, int) or mt <= 0):
                raise ValueError(f'stage {stage}: fallback max_tokens must be a positive integer')
            names = accepted.get(fb['model'])
            if not isinstance(names, list) or not names:
                raise ValueError(f'stage {stage}: fallback model {fb["model"]} has no accepted response mapping')
    return table


def load(path=PATH):
    return validate(json.loads(Path(path).read_text()))


def for_stage(table, stage):
    entry = (table.get('stages') or {}).get(stage) or table['default']
    return {'model': entry['model'], 'temperature': float(entry.get('temperature', 0.0))}


def accepted(table, model):
    return list(table['accepted_response_models'][model])


def models(table):
    entries = [table['default'], *(table.get('stages') or {}).values()]
    return sorted({e['model'] for e in entries} | {e['fallback']['model'] for e in entries if e.get('fallback')})


def fallback(table, stage):
    """The stage's documented fallback {'model','temperature','base_url','api_key_env','rates','max_tokens'} or None.

    max_tokens (optional) replaces the global fallback clamp for that stage (EXTRACT on opus needs its full
    12000-token ceiling; compose fallbacks stay clamped)."""
    entry = (table.get('stages') or {}).get(stage) or table['default']
    fb = entry.get('fallback')
    if not fb:
        return None
    return {'model': fb['model'], 'temperature': float(fb.get('temperature', 0.0)),
            'base_url': fb['base_url'].rstrip('/') if fb.get('base_url') else None,
            'api_key_env': fb.get('api_key_env'), 'rates': tuple(fb['rates']) if fb.get('rates') else None,
            'max_tokens': int(fb['max_tokens']) if fb.get('max_tokens') else None,
            'provider_fallback': bool(fb.get('provider_fallback'))}


def model_fallback(table, stage):
    """The stage's fallback only when it switches MODEL (e.g. gemini -> opus); None for a provider fallback
    (same Gemini model on another relay: subrouter -> micuapi). Gemini-only guards use this."""
    fb = fallback(table, stage)
    return None if fb is None or fb['provider_fallback'] else fb


def max_tokens(table, stage):
    """The stage primary's own output ceiling (e.g. Gemini EXTRACT: reasoning tokens count toward it) or None."""
    entry = (table.get('stages') or {}).get(stage) or table['default']
    return int(entry['max_tokens']) if entry.get('max_tokens') else None


THINKING_LEVELS = ('minimal', 'low', 'medium', 'high')


def thinking_level(table, stage, environ=None):
    """Gemini thinkingConfig.thinkingLevel for the stage (FD_GEMINI_THINKING overrides every stage) or None."""
    import os
    env = (environ if environ is not None else os.environ).get('FD_GEMINI_THINKING')
    if env:
        if env not in THINKING_LEVELS:
            raise ValueError(f'FD_GEMINI_THINKING must be one of {THINKING_LEVELS}')
        return env
    entry = (table.get('stages') or {}).get(stage) or table['default']
    return entry.get('thinking_level')


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
    prior = (out.get('stages') or {}).get(stage) or {}
    if base_url is not None and prior.get('base_url') == entry.get('base_url'):
        # Same route, other model: keep the stage's own output ceiling / planning estimate.
        entry.update({k: prior[k] for k in ('max_tokens', 'est_usd_per_doc', 'thinking_level') if k in prior})
        entry['temperature'] = prior.get('temperature', temperature) if temperature == 0.0 else temperature
    out['stages'] = dict(out.get('stages') or {}, **{stage: entry})
    names = list(accepted) if accepted else [model]
    out['accepted_response_models'] = dict(out['accepted_response_models'])
    out['accepted_response_models'][model] = sorted(set(out['accepted_response_models'].get(model, [])) | set(names))
    return validate(out)


def from_env(table, environ):
    """Explicit env configuration: FD_<STAGE>_MODEL [+ FD_<STAGE>_BASE_URL + FD_<STAGE>_API_KEY_ENV,
    FD_<STAGE>_ACCEPTED_MODELS, FD_<STAGE>_RATES "in,out"] for compose, stance and extract. No vars -> unchanged."""
    out = table
    gemini_all = environ.get('FD_GEMINI_MODEL') or None
    for stage in ENV_STAGES:
        key = 'FD_' + stage.upper() + '_'
        model = environ.get(key + 'MODEL') or None
        base_url = environ.get(key + 'BASE_URL') or None
        key_env = environ.get(key + 'API_KEY_ENV') or None
        current = route(out, stage) if stage in (out.get('stages') or {}) else None
        if model is None and gemini_all and current and is_gemini_route(current['base_url']):
            model = gemini_all
        if model is not None and base_url is None and key_env is None and current \
                and is_gemini_route(current['base_url']) and model.startswith('gemini-'):
            base_url, key_env = current['base_url'], current['api_key_env']
        if model is None:
            if base_url or key_env:
                raise ValueError(f'{key}BASE_URL / {key}API_KEY_ENV need {key}MODEL')
            continue
        accepted = [m.strip() for m in (environ.get(key + 'ACCEPTED_MODELS') or '').split(',') if m.strip()] or None
        raw_rates = environ.get(key + 'RATES')
        stage_rates = tuple(float(x) for x in raw_rates.split(',')) if raw_rates else None
        if stage_rates is None and model in (out.get('model_rates') or {}):
            stage_rates = tuple(out['model_rates'][model])
        out = override(out, stage, model, base_url=base_url, api_key_env=key_env, accepted=accepted, rates=stage_rates)
    return apply_gemini_provider(out, environ)


def copy_of(table):
    return copy.deepcopy(table)
