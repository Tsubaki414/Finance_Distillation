"""Private, one-shot transport. No HTTP server, tools, retries or prompt rewriting."""
import hashlib
import json
import os
import urllib.error
import urllib.request

PROXY = 'https://openrouter.apify.actor/api/v1/chat/completions'
MODEL = 'anthropic/claude-opus-5'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def validate(payload):
    if set(payload) != {'model', 'messages', 'max_tokens', 'temperature'}:
        raise ValueError('Unexpected request keys')
    if payload['model'] != MODEL or payload['temperature'] != 0:
        raise ValueError('Frozen model/temperature mismatch')
    if type(payload['max_tokens']) is not int or not 1 <= payload['max_tokens'] <= 128000:
        raise ValueError('Invalid output limit')
    if not isinstance(payload['messages'], list) or not payload['messages']:
        raise ValueError('Missing original messages')
    for item in payload['messages']:
        if set(item) != {'role', 'content'} or item['role'] not in ('system', 'user', 'assistant') or not isinstance(item['content'], str):
            raise ValueError('Invalid message contract')
    return payload


def main():
    token = os.environ['APIFY_TOKEN']
    store = os.environ.get('ACTOR_DEFAULT_KEY_VALUE_STORE_ID') or os.environ['APIFY_DEFAULT_KEY_VALUE_STORE_ID']
    api = 'https://api.apify.com/v2/key-value-stores/' + store + '/records/'

    def request(url, body=None, method=None):
        req = urllib.request.Request(url, data=body, method=method,
                                     headers={'Authorization': 'Bearer ' + token,
                                              'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=180 if url == PROXY else 30) as response:
            return json.load(response) if method != 'PUT' else None

    result = {'transport_version': 1, 'model_call_attempts': 0}
    try:
        source = request(api + os.environ.get('ACTOR_INPUT_KEY', 'INPUT'))
        payload = validate(source['payload'])
        body = encoded(payload)
        result.update(call_id=source['call_id'], request_sha256=hashlib.sha256(body).hexdigest(),
                      requested_model=payload['model'], max_tokens=payload['max_tokens'],
                      temperature=payload['temperature'])
        result['model_call_attempts'] = 1
        result['response'] = request(PROXY, body)
        result['status'] = 'completed'
    except urllib.error.HTTPError as exc:
        message = exc.read().decode('utf-8', 'replace').replace(token, '[REDACTED]')
        result.update(status='failed', http_status=exc.code, error=message[:1000])
    except Exception as exc:
        result.update(status='failed', error_type=type(exc).__name__,
                      error=str(exc).replace(token, '[REDACTED]')[:500])
    # Only the authenticated run store receives content; stdout contains no prompts/text/key.
    request(api + 'OUTPUT', encoded(result), 'PUT')
    print('Transport result saved: ' + result['status'], flush=True)


if __name__ == '__main__':
    main()
