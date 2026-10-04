"""Optional TypeSafe Jev development advice; never a production decision executor.

Only bounded Choice questions are supported. A successful answer, including high
confidence, cannot generate, approve, route or publish content. No provider retry,
fallback, credential borrowing, or response repair is performed.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
import uuid

import httpx

from live.distillation_source import now
from live.writer_backend import _dotenv
from ml import budget

MODEL = 'jev-1.13.0'
BUDGET_MODEL = 'typesafe/' + MODEL
ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MAX_PAYLOAD_BYTES = 32768
MAX_RESPONSE_BYTES = 65536
MAX_QUESTIONS = 16
TIMEOUT_SECONDS = 30.0


class ContractError(ValueError):
    pass


def _require(condition, check="invalid_contract"):
    if not condition:
        raise ContractError(check)


def _json_value(value, depth=0):
    _require(depth <= 32)
    if isinstance(value, dict):
        _require(all(isinstance(key, str) for key in value))
        for item in value.values():
            _json_value(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json_value(item, depth + 1)
    else:
        _require(value is None or type(value) in (str, int, float, bool))
        if type(value) is float:
            _require(math.isfinite(value))


def _request(state, questions):
    _require(isinstance(state, dict) and isinstance(questions, dict))
    _require(1 <= len(questions) <= MAX_QUESTIONS)
    for qid, question in questions.items():
        _require(isinstance(qid, str) and bool(qid.strip()))
        _require(isinstance(question, dict) and set(question) == {'type', 'instructions', 'criteria'})
        _require(question['type'] == 'choice')
        _require(isinstance(question['instructions'], str) and bool(question['instructions'].strip()))
        criteria = question['criteria']
        _require(isinstance(criteria, dict) and 2 <= len(criteria) <= 255)
        _require(all(isinstance(label, str) and bool(label.strip()) and
                     isinstance(description, str) and bool(description.strip())
                     for label, description in criteria.items()))
    payload = {'model': MODEL, 'state': state, 'questions': questions}
    _json_value(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    _require(len(encoded.encode('utf-8')) <= MAX_PAYLOAD_BYTES)
    return json.loads(encoded), encoded


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _reject_constant(value):
    raise ContractError('Non-finite JSON number')


def _usage(data):
    _require(isinstance(data, dict) and isinstance(data.get('usage'), dict), 'usage_object')
    usage = data['usage']
    _require(set(usage) == {'input_tokens', 'output_tokens'}, 'usage_keys')
    _require(all(type(value) is int and value >= 0 for value in usage.values()), 'usage_tokens')
    return {'prompt_tokens': usage['input_tokens'], 'completion_tokens': usage['output_tokens']}


def _probability(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _response(data, questions):
    _require(isinstance(data, dict) and set(data) == {'model', 'answers', 'usage'}, 'top_level_keys')
    _require(data['model'] == MODEL, 'model_mismatch')
    _require(isinstance(data['answers'], dict) and set(data['answers']) == set(questions), 'answers_keys_mismatch')
    for qid, answer in data['answers'].items():
        _require(isinstance(answer, dict) and
                 set(answer) == {'type', 'choice', 'probabilities', 'confidence'}, 'answer_keys')
        labels = set(questions[qid]['criteria'])
        _require(answer['type'] == 'choice', 'answer_type')
        _require(isinstance(answer['choice'], str) and answer['choice'] in labels, 'choice_not_in_labels')
        probabilities = answer['probabilities']
        _require(isinstance(probabilities, dict) and set(probabilities) == labels, 'probabilities_keys')
        _require(all(_probability(value) for value in probabilities.values()), 'probabilities_range')
        _require(math.isclose(sum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-6), 'probabilities_sum')
        _require(probabilities[answer['choice']] == max(probabilities.values()), 'choice_not_argmax')
        _require(_probability(answer['confidence']), 'confidence_range')
    _usage(data)
    return data


def _safe(value, secret):
    if isinstance(value, dict):
        return {_safe(key, secret): ('[REDACTED]' if key.lower() in {
            'authorization', 'api_key', 'apikey', 'access_token', 'api-key',
            'typesafe_api_key', 'jev_api_key', 'openrouter_api_key'} else _safe(item, secret))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)Bearer\s+[^\s"\x27,}]+', 'Bearer [REDACTED]', value)
    return value


def _contains_secret(value, secret):
    if isinstance(value, dict):
        return any(_contains_secret(key, secret) or _contains_secret(item, secret)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item, secret) for item in value)
    return isinstance(value, str) and secret in value


class JevReviewClient:
    def __init__(self, directory, *, api_key=None, transport=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if api_key is None:
            api_key = os.environ.get('TYPESAFE_API_KEY')
            if api_key is None:
                api_key = _dotenv().get('TYPESAFE_API_KEY', '')
        self._api_key = api_key.strip() if isinstance(api_key, str) else ''
        self.transport = transport
        self.calls = []

    def review(self, state, questions):
        call_id = uuid.uuid4().hex
        path = self.directory / (call_id + '.json')
        result = {'call_id': call_id, 'log_path': str(path), 'status': 'blocked',
                  'answers': {}, 'error_code': None, 'model': MODEL,
                  'advisory_only': True, 'human_review_required': True,
                  'execution_authorized': False}
        record = {'call_id': call_id, 'started_at': now(), 'endpoint': ENDPOINT,
                  'model': MODEL, 'model_call_attempts': 0, 'request': None,
                  'advisory_only': True, 'human_review_required': True,
                  'execution_authorized': False, 'accounting_status': 'not_reserved',
                  'rates_usd_per_million': {'input': 0.042, 'output': 0.0},
                  'cost_basis': 'published token rates; local estimate, not provider invoice'}
        started = time.monotonic()
        reserved = False
        usage = None
        invalid_usage = False

        def save():
            path.write_text(json.dumps(_safe(record, self._api_key), ensure_ascii=False,
                                       allow_nan=False, indent=2) + '\n')

        def finish():
            record.update(finished_at=now(), latency_seconds=round(time.monotonic() - started, 3))
            safe_result = _safe(result, self._api_key)
            record['result'] = safe_result
            record['status'] = result['status']
            save()
            self.calls.append({'call_id': call_id, 'path': str(path), 'status': result['status']})
            return safe_result

        try:
            payload, encoded = _request(state, questions)
            record['request'] = _safe(payload, self._api_key)
        except (ContractError, TypeError, ValueError, OverflowError, RecursionError):
            result['error_code'] = 'invalid_request'
            return finish()
        if not self._api_key:
            result['error_code'] = 'missing_api_key'
            return finish()
        # Credentials belong in the Authorization header, never in advisory state.
        if _contains_secret(payload, self._api_key):
            result['error_code'] = 'credential_in_request'
            return finish()
        try:
            estimate = budget.reserve(BUDGET_MODEL, [{'role': 'user', 'content': encoded}], 0, call_id)
            reserved = True
            record['accounting_status'] = 'reserved'
            record['reserved_estimate_usd'] = estimate
        except budget.BudgetExceeded:
            result['error_code'] = 'budget_exceeded'
            return finish()
        except Exception as exc:
            record['accounting_error_type'] = type(exc).__name__
            result['error_code'] = 'budget_reservation_failed'
            return finish()

        result['status'] = 'failed'
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, trust_env=False, follow_redirects=False,
                              transport=self.transport) as client:
                record['model_call_attempts'] = 1
                record['status'] = 'started'
                save()
                response = client.post(ENDPOINT, headers={'Authorization': 'Bearer ' + self._api_key,
                                                         'Content-Type': 'application/json'},
                                       content=encoded.encode('utf-8'))
            record['http_status'] = response.status_code
            if not response.is_success:
                result['error_code'] = {401: 'http_unauthorized', 403: 'http_forbidden',
                                       402: 'provider_balance', 429: 'http_rate_limited'}.get(
                                           response.status_code, 'http_error')
            else:
                _require(len(response.content) <= MAX_RESPONSE_BYTES)
                try:
                    data = json.loads(response.content, object_pairs_hook=_object,
                                      parse_constant=_reject_constant)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    result['error_code'] = 'invalid_json'
                else:
                    try:
                        candidate_usage = _usage(data)
                    except ContractError:
                        invalid_usage = True
                        result['error_code'] = 'usage_contract'
                    else:
                        try:
                            validated = _response(data, payload['questions'])
                        except ContractError as exc:
                            result['contract_error'] = record['contract_error'] = str(exc)
                            record['response_raw_truncated'] = _safe(response.text, self._api_key)[:4000]
                            raise
                        usage = candidate_usage
                        record['response'] = validated
                        result.update(status='completed', answers=validated['answers'],
                                      usage=validated['usage'])
        except httpx.HTTPError as exc:
            record['error_type'] = type(exc).__name__
            result['error_code'] = 'transport_error'
        except (ContractError, TypeError, ValueError, OverflowError, RecursionError):
            result['error_code'] = 'response_contract'
        finally:
            if reserved:
                if invalid_usage:
                    record['accounting_status'] = 'reservation_retained_invalid_usage'
                else:
                    try:
                        record['estimated_cost_usd'] = budget.settle(call_id, usage)
                        record['accounting_status'] = ('settled_reported_usage' if usage is not None
                                                       else 'settled_reservation_estimate')
                    except Exception as exc:
                        record.update(accounting_status='reservation_retained_settlement_failed',
                                      accounting_error_type=type(exc).__name__)
                        result.update(status='failed', answers={}, error_code='accounting_error')
        return finish()
