"""One explicit OpenAI API client for the authorized content batch, not production.

Uses the existing stage-client contract and spending reservations. No retries,
silent fallback, manual content, provider-specific prompt rewriting or new service.
"""
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import uuid

from live.distillation_source import digest, now
from live.writer_backend import _dotenv
from ml import budget

MODEL = 'gpt-5.6-sol'
PRICE_KEY = 'openai-content-batch-v2/' + MODEL
PRICING_REF = 'https://developers.openai.com/api/docs/models/gpt-5.6-sol'


class BatchClient:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.calls = []
        config = _dotenv()
        self.base = (os.getenv('OPENAI_BASE_URL') or config.get('OPENAI_BASE_URL', '')).rstrip('/')
        self.key = os.getenv('OPENAI_API_KEY') or config.get('OPENAI_API_KEY', '')
        if self.base != 'https://api.openai.com/v1' or not self.key:
            raise ValueError('This batch requires the configured official OpenAI endpoint')
        # Separate key preserves historical budget estimates; verified 2026-09-30.
        budget.PRICES[PRICE_KEY] = (4.0, 20.0)

    def __call__(self, stage, messages, max_tokens):
        call_id = uuid.uuid4().hex
        payload = {'model': MODEL, 'messages': messages, 'max_completion_tokens': max_tokens,
                   'reasoning_effort': 'low', 'response_format': {'type': 'json_object'},
                   'store': False}
        path = self.directory / (call_id + '.json')
        record = {'call_id': call_id, 'stage': stage, 'started_at': now(), 'messages': messages,
                  'prompt_hash': digest(messages), 'model': MODEL, 'provider': 'openai_direct',
                  'host': urlparse(self.base).hostname, 'request': payload, 'status': 'started',
                  'generation_origin': 'automated_pipeline', 'fallback': False,
                  'pricing': {'input_per_million': 4.0, 'output_per_million': 20.0,
                              'reference': PRICING_REF, 'estimate_not_invoice': True}}
        reserved = False
        started = time.monotonic()
        def save():
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        save()
        try:
            budget.reserve(PRICE_KEY, messages, max_tokens, call_id)
            reserved = True
            request = Request(self.base + '/chat/completions',
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
            with urlopen(request, timeout=180) as response:
                raw = json.load(response)
            record['raw_response'] = raw
            record['usage'] = raw.get('usage')
            if raw.get('error') or not raw.get('choices'):
                raise ValueError('OpenAI returned an error or no choices')
            if raw.get('model') != MODEL:
                raise ValueError('Unexpected response model; inspect before continuing')
            choice = raw['choices'][0]
            message = choice.get('message') or {}
            result = {'text': message.get('content') or '', 'finish_reason': choice.get('finish_reason'),
                      'refusal': message.get('refusal'), 'usage': raw.get('usage'),
                      'model': MODEL, 'response_model': raw.get('model'), 'response_id': raw.get('id'),
                      'provider': 'openai_direct', 'call_ref': str(path)}
            record.update(status='completed', response=result)
            return result
        except Exception as exc:
            record.update(status='failed', error_type=type(exc).__name__,
                          error=str(exc).replace(self.key, '[REDACTED]')[:300])
            raise
        finally:
            if reserved:
                record['estimated_cost_usd'] = budget.settle(call_id, record.get('usage'))
            record.update(finished_at=now(), latency_seconds=round(time.monotonic() - started, 3))
            save()
            self.calls.append({'path': str(path), 'stage': stage, 'status': record['status']})
