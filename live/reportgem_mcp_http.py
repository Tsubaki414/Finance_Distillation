"""Small synchronous ReportGem streamable HTTP client with replay recordings."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from live.reportgem_daily import call_key


class ReportGemHTTP:
    def __init__(self, url=None, token=None, *, run, transport=None):
        url = url or os.environ.get('REPORTGEM_MCP_URL')
        token = token or os.environ.get('REPORTGEM_MCP_TOKEN')
        if not url or not token:
            raise ValueError('reportgem_http_not_configured')
        self.url, self.run, self.sequence = url, Path(run), 0
        self.client = httpx.Client(transport=transport, timeout=120, headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
        })
        self.initialized = False
        (self.run / 'responses').mkdir(parents=True, exist_ok=True)

    def _rpc(self, method, params=None, *, notification=False):
        body = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            body['params'] = params
        if not notification:
            self.sequence += 1
            body['id'] = self.sequence
        response = self.client.post(self.url, json=body)
        response.raise_for_status()
        session = response.headers.get('mcp-session-id')
        if session:
            self.client.headers['Mcp-Session-Id'] = session
        if notification:
            return None
        if 'text/event-stream' in response.headers.get('content-type', ''):
            messages = []
            for event in response.text.replace('\r\n', '\n').split('\n\n'):
                data = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
                if data and data != '[DONE]':
                    messages.append(json.loads(data))
            payload = next((m for m in messages if m.get('id') == body['id']), None)
            if payload is None:
                raise ValueError('reportgem_http_missing_result')
        else:
            payload = response.json()
        if 'error' in payload:
            raise ValueError('reportgem_http_rpc_error: ' + str(payload['error'].get('message', 'unknown')))
        return payload['result']

    def __call__(self, tool, args):
        path = self.run / 'responses' / (call_key(tool, args) + '.json')
        if path.exists():
            return json.loads(path.read_text())
        if not self.initialized:
            result = self._rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                              'clientInfo': {'name': 'reportgem-daily', 'version': '1.0'}})
            self.client.headers['MCP-Protocol-Version'] = result.get('protocolVersion', '2025-03-26')
            self._rpc('notifications/initialized', notification=True)
            self.initialized = True
        result = self._rpc('tools/call', {'name': tool, 'arguments': args})
        if result.get('isError'):
            raise ValueError('reportgem_http_tool_error')
        if result.get('structuredContent') is not None:
            data = result['structuredContent']
        else:
            data = json.loads(result['content'][0]['text'])
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        return data

    def close(self):
        self.client.close()
