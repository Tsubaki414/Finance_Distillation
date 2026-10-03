"""Logged, budget-reserved relay calls. No automatic model fallback or retry."""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from live import writer_backend
from live.distillation_source import digest, now
from ml import budget


class RelayClient:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.calls = []

    def __call__(self, stage, messages, max_tokens):
        cfg = writer_backend.writer_config()
        call_id = uuid.uuid4().hex
        host = urlparse(cfg['base_url']).hostname
        billed_model = ('relay2/' if host == 'koalaapi.com' else '') + cfg['model']
        record = {'call_id': call_id, 'stage': stage, 'started_at': now(),
                  'messages': messages, 'prompt_hash': digest(messages), 'model': cfg['model'],
                  'provider': 'writer_relay', 'host': host, 'temperature': 0.0,
                  'max_tokens': max_tokens, 'status': 'started', 'cost_basis': 'configured rate estimate, not invoice'}
        path = self.directory / (call_id + '.json')
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        started = time.monotonic()
        reservation = None
        try:
            if cfg['missing']:
                raise RuntimeError('writer configuration missing')
            reservation = budget.reserve(billed_model, messages, max_tokens, call_id)
            response = writer_backend.complete(messages, max_tokens=max_tokens, temperature=0.0)
            record.update(response=response, usage=response.get('usage'), status='completed')
            return response
        except Exception as exc:
            # Do not put credential-bearing transport diagnostics in artifacts.
            message = str(exc)
            if cfg.get('api_key'):
                message = message.replace(cfg['api_key'], '[REDACTED]')
            record.update(status='failed', error_type=type(exc).__name__, error=message[:300])
            raise
        finally:
            if reservation is not None:
                record['estimated_cost_usd'] = budget.settle(call_id, record.get('usage'))
            record.update(finished_at=now(), latency_seconds=round(time.monotonic() - started, 3))
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
            self.calls.append({'stage': stage, 'path': str(path), 'status': record['status']})
