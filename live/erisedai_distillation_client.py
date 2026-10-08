"""Explicit, budgeted relay transport for the existing account content stages.

Credentials stay in process; there is no subprocess or provider retry. The only
fallback is a stage's explicitly configured one (stage_models.json "fallback",
e.g. COMPOSE gemini -> claude-opus-5-5) on an availability failure; it is
recorded on the call (model_fallback, fallback_reason). A response-model
mismatch never falls back.
The configured rate is a local spending estimate, not a provider invoice.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from live import stage_models
from live.distillation_source import digest, now
from live.writer_backend import ProviderQuotaError, _dotenv
from ml import budget

PROVIDER = 'erisedai_relay'
DEFAULT_MODEL = 'claude-opus-5'
RESPONSE_FORMAT = {'type': 'json_object'}
TIMEOUT = httpx.Timeout(180.0, connect=15.0, write=30.0, pool=15.0)
# Explicit, non-library User-Agent on every relay / Gemini call: Cloudflare in front of www.micuapi.ai answers
# error 1010 to library default agents (Python-urllib; Oct 7).
USER_AGENT = 'Mozilla/5.0 (compatible; fd-distillation/1.0)'
# Oct 6 v9 reliability: once a stage's primary model answers "quota/balance exhausted" the rest of the process
# goes straight to the documented fallback (v9a: two 403s each kept a conservative reservation, then the slot
# could not afford the fallback). Keyed by (stage, primary model); reset_quota_breaker() clears it.
QUOTA_TRIPPED = {}
# The fallback (claude-opus-5-5) is not a thinking model: the primary's large max_tokens (12000/24000, sized for
# Gemini thinking) made its reservation ~$1 per call. Historical opus compose completions are <2k tokens.
FALLBACK_MAX_TOKENS = int(os.environ.get('FD_FALLBACK_MAX_TOKENS', '4000'))


# Oct 8 (subrouter primary): consecutive provider failures of a stage's primary in this process. After
# PROVIDER_BREAKER_FAILS in a row the stage goes straight to its provider fallback (micuapi, same model) for
# PROVIDER_BREAKER_SECONDS, so a subrouter outage does not cost every call a timeout first.
PROVIDER_FAILS = {}
PROVIDER_BREAKER_FAILS = int(os.environ.get('FD_PROVIDER_BREAKER_FAILS', '3'))
PROVIDER_BREAKER_SECONDS = float(os.environ.get('FD_PROVIDER_BREAKER_SECONDS', '600'))


def reset_quota_breaker():
    QUOTA_TRIPPED.clear()
    PROVIDER_FAILS.clear()


def quota_tripped():
    return dict(QUOTA_TRIPPED)


def relay_config():
    """Read one complete credential pair; never borrow a key across providers.

    REVIEW_* is this workspace's existing erisedai configuration. It is only
    accepted for that exact host, when neither ACCOUNT_RELAY credential is set.
    The account provider selector remains explicit and unchanged.
    """
    file_env = _dotenv()

    def setting(name, default=''):
        return os.environ.get(name, file_env.get(name, default))

    base_url, api_key = setting('ACCOUNT_RELAY_BASE_URL'), setting('ACCOUNT_RELAY_API_KEY')
    namespace = 'ACCOUNT_RELAY'
    if not base_url and not api_key:
        base_url, api_key = setting('REVIEW_BASE_URL'), setting('REVIEW_API_KEY')
        namespace = 'REVIEW'
        if urlsplit(base_url).hostname != 'api.erisedai.com':
            raise ValueError('Existing REVIEW credential pair is not the configured erisedai host')
    if not base_url or not api_key:
        raise ValueError(f'{namespace}_BASE_URL and {namespace}_API_KEY must be configured together')
    config = {
        'base_url': base_url.rstrip('/'),
        'api_key': api_key,
        'configuration_source': namespace,
        'model': setting('ACCOUNT_RELAY_MODEL', DEFAULT_MODEL),
        'input_usd_per_million': float(setting('ACCOUNT_RELAY_INPUT_USD_PER_MILLION', '15')),
        'output_usd_per_million': float(setting('ACCOUNT_RELAY_OUTPUT_USD_PER_MILLION', '75')),
    }
    parsed = urlsplit(config['base_url'])
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('ACCOUNT_RELAY_BASE_URL must be an HTTPS URL without credentials, query or fragment')
    if config['model'] != DEFAULT_MODEL:
        raise ValueError('This validated relay transport requires claude-opus-5; no model fallback')
    for field in ('input_usd_per_million', 'output_usd_per_million'):
        if not math.isfinite(config[field]) or config[field] <= 0:
            raise ValueError('Relay token rates must be finite positive numbers')
    return config


def _safe(value, secret):
    """Redact credentials even when a provider echoes them in a failed response."""
    if isinstance(value, dict):
        return {_safe(key, secret): ('[REDACTED]' if key.lower() in {
            'authorization', 'api_key', 'apikey', 'access_token', 'api-key', 'x-goog-api-key'
        } else _safe(item, secret)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'AQ\.[A-Za-z0-9_\-.]{8,}', '[REDACTED]', value)
        return re.sub(r'(?i)Bearer\s+[^\s"\x27,}]+', 'Bearer [REDACTED]', value)
    return value


GEMINI_PROVIDER = 'gemini_official'
_GEMINI_FINISH = {'STOP': 'stop', 'MAX_TOKENS': 'length', 'SAFETY': 'content_filter', 'RECITATION': 'content_filter',
                  'PROHIBITED_CONTENT': 'content_filter', 'BLOCKLIST': 'content_filter', 'SPII': 'content_filter'}


def gemini_payload(messages, max_tokens, temperature, thinking_level=None):
    """OpenAI-style messages -> native generateContent body (system -> systemInstruction, assistant -> model)."""
    system = [m['content'] for m in messages if m.get('role') == 'system' and m.get('content')]
    contents = [{'role': 'model' if m.get('role') == 'assistant' else 'user', 'parts': [{'text': str(m.get('content') or '')}]}
                for m in messages if m.get('role') != 'system']
    body = {'contents': contents,
            'generationConfig': {'temperature': temperature, 'maxOutputTokens': int(max_tokens),
                                 'responseMimeType': 'application/json'}}
    if thinking_level:
        body['generationConfig']['thinkingConfig'] = {'thinkingLevel': thinking_level}
    if system:
        body['systemInstruction'] = {'parts': [{'text': '\n\n'.join(system)}]}
    return body


def gemini_to_chat(data, model):
    """Native generateContent response -> the chat/completions shape the pipeline validates.
    Thinking tokens are billed as output, so they count in completion_tokens."""
    cands = data.get('candidates') or []
    if not cands:
        block = (data.get('promptFeedback') or {}).get('blockReason')
        return {'error': f'Gemini returned no candidates (blockReason={block})'}
    cand = cands[0]
    text = ''.join(p.get('text', '') for p in ((cand.get('content') or {}).get('parts') or []) if not p.get('thought'))
    meta = data.get('usageMetadata') or {}
    out_tokens = int(meta.get('candidatesTokenCount') or 0) + int(meta.get('thoughtsTokenCount') or 0)
    return {'id': data.get('responseId'), 'model': data.get('modelVersion') or model,
            'choices': [{'index': 0, 'finish_reason': _GEMINI_FINISH.get(cand.get('finishReason'), str(cand.get('finishReason')).lower()),
                         'message': {'role': 'assistant', 'content': text}}],
            'usage': {'prompt_tokens': int(meta.get('promptTokenCount') or 0), 'completion_tokens': out_tokens,
                      'total_tokens': int(meta.get('promptTokenCount') or 0) + out_tokens,
                      'thoughts_tokens': int(meta.get('thoughtsTokenCount') or 0)}}


def _relay_reasoning(base_url, level):
    """Gemini on the micuapi relay: thinking level -> OpenAI-style reasoning_effort (minimal -> low)."""
    if not level or not stage_models.is_gemini_relay(base_url):
        return {}
    return {'reasoning_effort': 'low' if level == 'minimal' else level}


def _fallback_worthy(exc):
    """Availability failures of the primary model (transport, timeout, 408/429/5xx, no channel,
    relay quota exhausted, unusable body). Response-model mismatches, refusals and budget errors are not."""
    text = str(exc)
    if isinstance(exc, ProviderQuotaError):   # relay-side quota/balance exhausted on the primary key
        return True
    if isinstance(exc, json.JSONDecodeError) or text.startswith(('Relay transport failed', 'Relay response has no choices')):
        return True
    if text.startswith('Relay HTTP'):
        return bool(re.match(r'Relay HTTP (?:408|429|5\d\d)\b', text) or
                    re.search(r'model_not_found|No available channel', text, re.I))
    return False


def _quota(status, error):
    return status == 402 or bool(re.search(
        r'额度不足|余额不足|预扣费额度失败|insufficient[_ ]quota|insufficient.*(?:balance|credit)',
        str(error), re.I))


class ErisedaiClient:
    def __init__(self, directory, *, configuration=None, transport=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config = copy.deepcopy(configuration if configuration is not None else relay_config())
        if not self.config['api_key']:
            raise ValueError('ACCOUNT_RELAY_API_KEY is missing')
        self.transport = transport
        self.calls = []
        # Plan 1.4 subset: per-stage model/temperature; shipped defaults keep
        # every stage on the validated model at temperature 0.0.
        table = self.config.get('stage_models')
        if table is None:
            # Explicit env switch (FD_COMPOSE_* / FD_STANCE_*); unset keeps the shipped defaults.
            table = stage_models.from_env(stage_models.load(), os.environ)
        self.stage_models = stage_models.validate(copy.deepcopy(table))
        self.budget_model = PROVIDER + '/' + self.config['model']
        for model in {self.config['model'], *stage_models.models(self.stage_models)}:
            budget.PRICES[PROVIDER + '/' + model] = (
                self.config['input_usd_per_million'], self.config['output_usd_per_million'])
        # Routed stages: resolve each key now (fail before any call), keep it in process only.
        self._route_keys = {}
        self._route_missing = {}
        self._fallback_keys = {}
        file_env = None
        for stage in (self.stage_models.get('stages') or {}):
            routed = stage_models.route(self.stage_models, stage)
            stage_rates = stage_models.rates(self.stage_models, stage)
            if stage_rates:
                budget.PRICES[PROVIDER + '/' + stage_models.for_stage(self.stage_models, stage)['model']] = stage_rates
            if routed is None:
                continue
            name = routed['api_key_env']
            value = os.environ.get(name)
            if not value:
                file_env = _dotenv() if file_env is None else file_env
                value = file_env.get(name, '')
            if value.strip() and stage_models.is_gemini_native(routed['base_url']):
                value = stage_models.gemini_token(value)
            if not value.strip():
                if stage_models.fallback(self.stage_models, stage) is None:
                    raise ValueError(f'{name} is not set for routed stage {stage}')
                # Documented fallback: the stage runs on its fallback model, recorded per call.
                self._route_missing[stage] = f'{name} is not set'
                continue
            self._route_keys[stage] = value.strip()
        for stage in (self.stage_models.get('stages') or {}):
            fb = stage_models.fallback(self.stage_models, stage)
            if fb is None:
                continue
            if fb['rates']:
                budget.PRICES[PROVIDER + '/' + fb['model']] = fb['rates']
            if fb['base_url']:
                name = fb['api_key_env']
                value = os.environ.get(name) or (file_env if file_env is not None else _dotenv()).get(name, '')
                if not value.strip():
                    if fb['provider_fallback'] and stage not in self._route_missing:
                        continue   # provider fallback (micuapi) unavailable: the primary (subrouter) runs alone
                    raise ValueError(f'{name} is not set for the {stage} fallback')
                self._fallback_keys[stage] = value.strip()

    def __call__(self, stage, messages, max_tokens):
        fb = stage_models.fallback(self.stage_models, stage)
        if stage in self._route_missing:
            return self._fallback(stage, messages, max_tokens, fb, self._route_missing[stage])
        routed = stage_models.route(self.stage_models, stage)
        selected = stage_models.for_stage(self.stage_models, stage)
        if (self.config.get('gemini_only') or os.environ.get('FD_GEMINI_ONLY') == '1') and not (
                routed and stage_models.is_gemini_route(routed['base_url'])):
            # Oct 7: daily compose runs Gemini-only; a stage that would go to the Opus relay fails loudly.
            raise RuntimeError(f'stage {stage} is not routed to Gemini (official or relay; FD_GEMINI_ONLY=1)')
        provider_fb = bool(fb and fb['provider_fallback'] and (stage in self._fallback_keys or not fb['base_url']))
        if fb is not None and fb['provider_fallback'] and not provider_fb:
            fb = None   # provider fallback configured but its key is missing: primary only
        tripped = QUOTA_TRIPPED.get((stage, selected['model']))
        if fb is not None and tripped:
            return self._fallback(stage, messages, max_tokens, fb, f'quota breaker open: {tripped}'[:300])
        key = (stage, selected['model'], routed['base_url'] if routed else None)
        fails = PROVIDER_FAILS.get(key)
        if provider_fb and fails and fails[0] >= PROVIDER_BREAKER_FAILS and time.monotonic() - fails[1] < PROVIDER_BREAKER_SECONDS:
            return self._fallback(stage, messages, max_tokens, fb,
                                  f'provider breaker open: {fails[0]} consecutive {selected["model"]} failures: {fails[2]}'[:300])
        args = (stage, messages, stage_models.max_tokens(self.stage_models, stage) or max_tokens,
                selected['model'], selected['temperature'],
                routed['base_url'] if routed else self.config['base_url'],
                self._route_keys[stage] if routed else self.config['api_key'],
                routed['api_key_env'] if routed else None)
        try:
            try:
                out = self._call(*args)
            except ValueError as exc:
                # Oct 8 smoke: subrouter occasionally answers a gemini-3.1-pro-preview request from another channel
                # ("gemini-pro-agent"). Never accepted; on the flat-rate primary one free retry on the same provider
                # comes first (it usually lands on the right channel), then the paid micuapi fallback.
                if not (provider_fb and stage_models.is_flat_rate(args[5]) and 'Unexpected relay response model' in str(exc)):
                    raise
                out = self._call(*args)
            PROVIDER_FAILS.pop(key, None)
            return out
        except Exception as exc:
            # A provider fallback keeps the same Gemini model, so any primary failure except a budget refusal
            # (errors, 4xx/429/5xx, quota, transport, bad body, unexpected response model) moves to it.
            worthy = (not isinstance(exc, budget.BudgetExceeded)) if provider_fb else _fallback_worthy(exc)
            if fb is None or not worthy:
                raise
            if provider_fb:
                n = (fails[0] if fails else 0) + 1
                PROVIDER_FAILS[key] = (n, time.monotonic(), str(exc)[:120])
            if isinstance(exc, ProviderQuotaError):
                QUOTA_TRIPPED[(stage, selected['model'])] = f'{selected["model"]}: {exc}'[:200]
            return self._fallback(stage, messages, max_tokens, fb, f'{selected["model"]}: {exc}'[:300])

    def _fallback(self, stage, messages, max_tokens, fb, reason):
        if fb['base_url']:
            base_url, secret, key_env = fb['base_url'], self._fallback_keys[stage], fb['api_key_env']
        else:
            base_url, secret, key_env = self.config['base_url'], self.config['api_key'], None
        if fb.get('provider_fallback'):
            # Same model on another provider: the stage's own output ceiling (Gemini thinking counts toward it).
            limit = fb.get('max_tokens') or stage_models.max_tokens(self.stage_models, stage) or int(max_tokens)
        else:
            limit = min(int(max_tokens), fb.get('max_tokens') or FALLBACK_MAX_TOKENS)
        return self._call(stage, messages, limit, fb['model'], fb['temperature'],
                          base_url, secret, key_env, fallback_reason=reason,
                          provider_fallback=bool(fb.get('provider_fallback')))

    def _call(self, stage, messages, max_tokens, model, temperature, base_url, secret, routed_key_env,
              fallback_reason=None, provider_fallback=False):
        call_id = uuid.uuid4().hex
        path = self.directory / (call_id + '.json')
        budget_model = PROVIDER + '/' + model
        native = stage_models.is_gemini_native(base_url)
        # Flat-rate provider (subrouter): ledgered at a nominal list-price cost, never counted toward a cap.
        flat = stage_models.is_flat_rate(base_url)
        serving = stage_models.provider_name(base_url)
        model_fb = fallback_reason is not None and not provider_fallback
        payload = ({'model': model, 'messages': copy.deepcopy(messages),
                    'max_tokens': max_tokens, 'temperature': temperature,
                    'response_format': copy.deepcopy(RESPONSE_FORMAT),
                    **_relay_reasoning(base_url, stage_models.thinking_level(self.stage_models, stage))} if not native
                   else gemini_payload(messages, max_tokens, temperature,
                                       stage_models.thinking_level(self.stage_models, stage)))
        record = {'call_id': call_id, 'stage': stage, 'started_at': now(),
                  'messages': messages, 'prompt_hash': digest(messages),
                  'model': model, 'upstream_model': model,
                  'provider': GEMINI_PROVIDER if native else (serving if flat else PROVIDER),
                  'serving_provider': serving, 'host': urlsplit(base_url).netloc,
                  'routed_key_env': routed_key_env, 'cost_counts_toward_cap': not flat,
                  'configuration_source': self.config.get('configuration_source', 'explicit_configuration'),
                  'temperature': temperature, 'max_tokens': max_tokens, 'status': 'started',
                  'stage_model_table': self.stage_models.get('version', 'inline'),
                  'response_format': copy.deepcopy(RESPONSE_FORMAT),
                  'model_fallback': model_fb, 'provider_fallback': bool(provider_fallback and fallback_reason),
                  'model_call_attempts': 0,
                  **({'fallback_reason': _safe(fallback_reason, secret)} if fallback_reason else {}),
                  'cost_basis': 'configured conservative token/rate estimate; not invoice',
                  'rates_usd_per_million': {
                      'input': self.config['input_usd_per_million'],
                      'output': self.config['output_usd_per_million']}}
        reservation = None
        started = time.monotonic()

        def save():
            path.write_text(json.dumps(_safe(record, secret), ensure_ascii=False, indent=2) + '\n')

        save()
        try:
            reservation = budget.reserve(budget_model, messages, max_tokens, call_id,
                                         counts_toward_cap=not flat, provider=serving)
            with httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False,
                              transport=self.transport) as client:
                record['model_call_attempts'] = 1
                if native:
                    response = client.post(f'{base_url}/models/{model}:generateContent',
                                           headers={'x-goog-api-key': secret, 'User-Agent': USER_AGENT}, json=payload)
                else:
                    response = client.post(base_url + '/chat/completions',
                                           headers={'Authorization': 'Bearer ' + secret, 'User-Agent': USER_AGENT},
                                           json=payload)
            record['http_status'] = response.status_code
            if native and not response.is_success:
                # Official Gemini API: a rejected request (429 / 5xx / 4xx) is not billed.
                record['usage'] = {'prompt_tokens': 0, 'completion_tokens': 0, 'basis': 'gemini error response, not billed'}
            try:
                data = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                record['response_excerpt'] = _safe(response.text, secret)[:1000]
                if not response.is_success:
                    cls = ProviderQuotaError if _quota(response.status_code, response.text) else RuntimeError
                    raise cls(f'Relay HTTP {response.status_code}: non-JSON error') from None
                # Do not attach the potentially credential-bearing raw JSON document.
                raise json.JSONDecodeError('Relay returned invalid JSON', '', 0) from None
            if native and response.is_success and isinstance(data, dict) and not data.get('error'):
                data = gemini_to_chat(data, model)
            record['transport_output'] = _safe(data, secret)
            if not response.is_success or (isinstance(data, dict) and data.get('error')):
                error = data.get('error', data) if isinstance(data, dict) else data
                error = str(_safe(error, secret))[:400]
                cls = ProviderQuotaError if _quota(response.status_code, error) else RuntimeError
                raise cls(f'Relay HTTP {response.status_code}: {error}')
            if not isinstance(data, dict) or not data.get('choices'):
                raise ValueError('Relay response has no choices')
            record['usage'] = _safe(data.get('usage'), secret)
            if data.get('model') not in stage_models.accepted(self.stage_models, model):
                raise ValueError('Unexpected relay response model; no model fallback permitted')
            choice = data['choices'][0]
            message = choice.get('message') or {}
            content = message.get('content')
            if content is not None and not isinstance(content, str):
                raise ValueError('Relay response content must be text')
            # Existing pipeline validates finish_reason/refusal before parsing or drafting.
            result = {'text': (content or '').strip(), 'model': model,
                      'provider': PROVIDER, 'serving_provider': serving, 'usage': data.get('usage'),
                      'response_id': data.get('id'), 'response_model': data.get('model'),
                      'finish_reason': choice.get('finish_reason'), 'refusal': message.get('refusal'),
                      'model_fallback': model_fb, 'provider_fallback': bool(provider_fallback and fallback_reason),
                      **({'fallback_reason': fallback_reason} if fallback_reason else {})}
            result = _safe(result, secret)
            record.update(response=result, status='completed')
            return result
        except httpx.HTTPError as exc:
            # httpx exception text can include request details; save only its class.
            record.update(status='failed', error_type=type(exc).__name__, error='Relay transport failed')
            raise RuntimeError('Relay transport failed: ' + type(exc).__name__) from None
        except Exception as exc:
            record.update(status='failed', error_type=type(exc).__name__,
                          error=_safe(str(exc), secret)[:500])
            raise
        finally:
            try:
                if reservation is not None:
                    cost = budget.settle(call_id, record.get('usage'))
                    # estimated_cost_usd is what run budgets sum (daily cap); a flat-rate call adds 0 there and
                    # keeps its list-price figure as nominal_cost_usd.
                    record['estimated_cost_usd'] = 0.0 if flat else cost
                    if flat:
                        record['nominal_cost_usd'] = cost
            except Exception as exc:
                # A malformed usage object must not erase the request evidence.
                # The existing reservation remains charged until it can settle.
                record.update(status='failed', accounting_error=type(exc).__name__)
                raise RuntimeError('Relay usage settlement failed; reservation retained') from None
            finally:
                record.update(finished_at=now(), latency_seconds=round(time.monotonic() - started, 3))
                save()
                self.calls.append({'stage': stage, 'path': str(path), 'status': record['status']})
