"""Explicit, budgeted relay transport for the existing account content stages.

Credentials stay in process; there is no subprocess, provider retry or fallback.
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
            'authorization', 'api_key', 'apikey', 'access_token', 'api-key'
        } else _safe(item, secret)) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)Bearer\s+[^\s"\x27,}]+', 'Bearer [REDACTED]', value)
    return value


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
            if not value.strip():
                raise ValueError(f'{name} is not set for routed stage {stage}')
            self._route_keys[stage] = value.strip()

    def __call__(self, stage, messages, max_tokens):
        call_id = uuid.uuid4().hex
        path = self.directory / (call_id + '.json')
        routed = stage_models.route(self.stage_models, stage)
        secret = self._route_keys[stage] if routed else self.config['api_key']
        base_url = routed['base_url'] if routed else self.config['base_url']
        selected = stage_models.for_stage(self.stage_models, stage)
        model, temperature = selected['model'], selected['temperature']
        budget_model = PROVIDER + '/' + model
        payload = {'model': model, 'messages': copy.deepcopy(messages),
                   'max_tokens': max_tokens, 'temperature': temperature,
                   'response_format': copy.deepcopy(RESPONSE_FORMAT)}
        record = {'call_id': call_id, 'stage': stage, 'started_at': now(),
                  'messages': messages, 'prompt_hash': digest(messages),
                  'model': model, 'upstream_model': model,
                  'provider': PROVIDER, 'host': urlsplit(base_url).netloc,
                  'routed_key_env': routed['api_key_env'] if routed else None,
                  'configuration_source': self.config.get('configuration_source', 'explicit_configuration'),
                  'temperature': temperature, 'max_tokens': max_tokens, 'status': 'started',
                  'stage_model_table': self.stage_models.get('version', 'inline'),
                  'response_format': copy.deepcopy(RESPONSE_FORMAT),
                  'model_fallback': False, 'model_call_attempts': 0,
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
            reservation = budget.reserve(budget_model, messages, max_tokens, call_id)
            with httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False,
                              transport=self.transport) as client:
                record['model_call_attempts'] = 1
                response = client.post(base_url + '/chat/completions',
                                       headers={'Authorization': 'Bearer ' + secret}, json=payload)
            record['http_status'] = response.status_code
            try:
                data = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError):
                record['response_excerpt'] = _safe(response.text, secret)[:1000]
                if not response.is_success:
                    cls = ProviderQuotaError if _quota(response.status_code, response.text) else RuntimeError
                    raise cls(f'Relay HTTP {response.status_code}: non-JSON error') from None
                # Do not attach the potentially credential-bearing raw JSON document.
                raise json.JSONDecodeError('Relay returned invalid JSON', '', 0) from None
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
                      'provider': PROVIDER, 'usage': data.get('usage'),
                      'response_id': data.get('id'), 'response_model': data.get('model'),
                      'finish_reason': choice.get('finish_reason'), 'refusal': message.get('refusal')}
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
                    record['estimated_cost_usd'] = budget.settle(call_id, record.get('usage'))
            except Exception as exc:
                # A malformed usage object must not erase the request evidence.
                # The existing reservation remains charged until it can settle.
                record.update(status='failed', accounting_error=type(exc).__name__)
                raise RuntimeError('Relay usage settlement failed; reservation retained') from None
            finally:
                record.update(finished_at=now(), latency_seconds=round(time.monotonic() - started, 3))
                save()
                self.calls.append({'stage': stage, 'path': str(path), 'status': record['status']})
