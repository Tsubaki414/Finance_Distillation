"""Pinned private Apify transport for shared account drafting and saved evaluations.

Every model call is logged and budget-reserved. No provider or model fallback.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from live.distillation_source import digest, now
from live.writer_backend import ProviderQuotaError
from live.xsearch import _token
from ml import budget
from scripts.apify_passthrough.main import encoded, validate

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / 'runs/account_sources_v1/apify_transport'
CONFIG = TRANSPORT / 'private_actor.json'
API = 'https://api.apify.com/v2'
MODEL = 'claude-opus-5'
UPSTREAM_MODEL = 'anthropic/claude-opus-5'
TERMINAL = {'SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED'}


def api(path, payload=None, method=None, timeout=30):
    token = _token()
    request = Request(API + path, data=encoded(payload) if payload is not None else None,
                      method=method, headers={'Authorization': 'Bearer ' + token,
                                             'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace').replace(token, '[REDACTED]')
        raise RuntimeError(f'Apify HTTP {exc.code}: {body[:500]}') from None


def source_hashes():
    return {name: hashlib.sha256((ROOT / 'scripts/apify_passthrough' / name).read_bytes()).hexdigest()
            for name in ('main.py', 'Dockerfile')}


def response_from(output, payload, call_id):
    if output.get('call_id') != call_id or output.get('request_sha256') != hashlib.sha256(encoded(payload)).hexdigest():
        raise ValueError('Transport request identity/hash mismatch')
    if output.get('model_call_attempts') != 1:
        raise ValueError('Expected exactly one upstream attempt')
    if output.get('status') != 'completed':
        error = output.get('error', 'Remote request failed')
        if output.get('http_status') == 402:
            raise ProviderQuotaError('Apify model quota: ' + str(error)[:300])
        raise RuntimeError('Apify model transport: ' + str(error)[:300])
    data = output.get('response') or {}
    if data.get('error') or not data.get('choices'):
        raise RuntimeError('Apify upstream returned error or no choices')
    if data.get('model') != UPSTREAM_MODEL:
        raise ValueError('Unexpected response model; no model fallback permitted')
    choice = data['choices'][0]
    message = choice.get('message') or {}
    return {'text': (message.get('content') or '').strip(), 'model': MODEL,
            'provider': 'apify_openrouter', 'usage': data.get('usage'),
            'response_id': data.get('id'), 'response_model': data.get('model'),
            'finish_reason': choice.get('finish_reason'), 'refusal': message.get('refusal')}


class ApifyClient:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.calls = []
        self.config = json.loads(CONFIG.read_text())
        if self.config['source_hashes'] != source_hashes() or self.config['is_public'] is not False:
            raise ValueError('Private transport source/config changed; inspect before running')
        actor = api('/acts/' + self.config['actor_id'])['data']
        if actor.get('isPublic') is not False or actor.get('actorPermissionLevel') != 'LIMITED_PERMISSIONS':
            raise ValueError('Transport must remain private with limited permissions')

    def __call__(self, stage, messages, max_tokens):
        payload = validate({'model': UPSTREAM_MODEL, 'messages': messages,
                            'max_tokens': max_tokens, 'temperature': 0.0})
        call_id = uuid.uuid4().hex
        path = self.directory / (call_id + '.json')
        record = {'call_id': call_id, 'stage': stage, 'started_at': now(), 'messages': messages,
                  'prompt_hash': digest(messages), 'model': MODEL, 'upstream_model': UPSTREAM_MODEL,
                  'provider': 'apify_openrouter', 'host': 'openrouter.apify.actor',
                  'temperature': 0.0, 'max_tokens': max_tokens, 'status': 'started',
                  'provider_changed_from': 'koalaapi.com', 'model_fallback': False,
                  'actor_id': self.config['actor_id'], 'build_id': self.config['build_id'],
                  'source_hashes': self.config['source_hashes'],
                  'cost_basis': 'conservative token/rate estimate plus observed Actor cost; not full invoice'}
        reservation = run = None
        overhead = None
        started = time.monotonic()

        def save():
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')

        save()
        try:
            reservation = budget.reserve('apify/' + UPSTREAM_MODEL, messages, max_tokens,
                                         call_id, overhead_usd=0.25)
            options = urlencode({'build': self.config['build_number'], 'memory': 256,
                                 'timeout': 240, 'waitForFinish': 1,
                                 'forcePermissionLevel': 'LIMITED_PERMISSIONS', 'restartOnError': 'false'})
            run = api('/acts/' + self.config['actor_id'] + '/runs?' + options,
                      {'call_id': call_id, 'payload': payload})['data']
            record['apify_run_id'] = run['id']
            record['apify_store_id'] = run['defaultKeyValueStoreId']
            save()
            deadline = time.monotonic() + 270
            while run['status'] not in TERMINAL:
                if time.monotonic() > deadline:
                    raise TimeoutError('Actor deadline; no automatic retry')
                time.sleep(3)
                run = api('/actor-runs/' + run['id'])['data']
            record['actor_status'] = run['status']
            if run.get('buildId') != self.config['build_id']:
                raise ValueError('Unpinned Actor build returned')
            output = api('/key-value-stores/' + run['defaultKeyValueStoreId'] + '/records/OUTPUT')
            record['transport_output'] = output
            response = response_from(output, payload, call_id)
            record.update(response=response, usage=response.get('usage'), status='completed')
            return response
        except Exception as exc:
            record.update(status='failed', error_type=type(exc).__name__,
                          error=str(exc).replace(_token(), '[REDACTED]')[:500])
            raise
        finally:
            if run:
                try:
                    if run['status'] not in TERMINAL:
                        api('/actor-runs/' + run['id'] + '/abort', {}, method='POST')
                    # Accounting may settle after completion; zero is unknown, not free.
                    for _ in range(3):
                        run = api('/actor-runs/' + run['id'])['data']
                        if run.get('usageTotalUsd'):
                            overhead = run['usageTotalUsd']
                            break
                        time.sleep(2)
                    record.update(actor_status=run['status'], actor_usage_usd=overhead,
                                  upstream_usage_cost=(record.get('usage') or {}).get('cost'))
                except Exception as exc:
                    record['accounting_error'] = type(exc).__name__
            if reservation is not None:
                record['estimated_cost_usd'] = budget.settle(call_id, record.get('usage'),
                                                            overhead_actual_usd=overhead)
            record.update(finished_at=now(), latency_seconds=round(time.monotonic() - started, 3))
            save()
            self.calls.append({'stage': stage, 'path': str(path), 'status': record['status']})
