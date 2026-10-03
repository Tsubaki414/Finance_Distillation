"""Client for the review relay: an OpenAI-compatible endpoint serving several vendors' models.

Authorised scope is narrow and encoded in the variable names. The relay judges and gates text in
both languages; it does not write any. Nothing here has a generation entry point, so a later
caller cannot quietly turn the reviewer into an author.

Two properties matter more than convenience:

  the key never travels further than the request   It is read from the project-root `.env` into
      this process, put in one Authorization header and never logged, echoed, cached or written
      into a run record. Run records keep a prompt hash, not the prompt's secrets.

  every verdict carries its own provenance   Model, temperature, seed, prompt hash, token usage
      and the wall-clock time are appended to `ml/store/review_runs.jsonl` before the caller sees
      the answer. A verdict that cannot say which model produced it under which settings is not
      evidence, and the project already treats undocumented model self-assessment as worthless.

The relay is a third party. Everything sent through it leaves this machine and passes through a
host that is neither Anthropic, Google nor OpenAI, so callers pass excerpts, never the corpus.
"""
from pathlib import Path
import os, sys, json, time, hashlib, urllib.request, urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml import budget
STORE = ROOT / 'ml/store'
CACHE = STORE / 'review_cache'
RUNS = STORE / 'review_runs.jsonl'

# Two providers, routed by model name. Both are read from the project-root .env and neither is
# ever used to write; the authorised scope is review and advice.
#
#   relay   api.erisedai.com   six models from three vendors, one key. Convenient and, as of
#           2026-09-21, returning 503 "No available channel" for every new request — a rotated
#           key did not change that, so it is the relay's upstream capacity, not the credential.
#   xai     api.x.ai           first-party. No silent SKU substitution: the relay answered a
#           request for gemini-3.1-pro with gemini-3.1-pro-high, which is a different price and a
#           different model than the one recorded in the run log.
#
# A first-party endpoint is preferred for anything whose provenance has to hold up later.
MODELS = ('claude-opus-5', 'claude-sonnet-5', 'gemini-3.1-pro', 'gemini-3.8-flash',
          'gpt-5.6-sol', 'gpt-6-astra')
XAI_MODELS = ('grok-4.6', 'grok-4.5', 'grok-4.3',
              'grok-4.20-0309-reasoning', 'grok-4.20-0309-non-reasoning',
              'grok-4.20-multi-agent-0309')


# A second relay was supplied on 2026-09-24 with 「请用大模型去生成」. Its catalogue overlaps the
# first relay's and OpenAI's almost entirely — it lists claude-opus-5, gpt-5.5, gemini-3.1-pro and
# the Grok family under the same names — so a name alone cannot say which endpoint should serve it.
# Routing is therefore explicit: `relay2/claude-opus-5` goes there, the bare name does not. The
# prefix is stripped before the request and kept in the log, so a later reader can tell which
# endpoint answered without inferring it from a price.
RELAY2_PREFIX = 'relay2/'


def strip_route(model):
    """The name to put on the wire. The prefix is ours, not the vendor's."""
    m = str(model)
    return m[len(RELAY2_PREFIX):] if m.startswith(RELAY2_PREFIX) else m


def _provider(model):
    m = str(model)
    if m.startswith(RELAY2_PREFIX):
        return 'relay2'
    if m.startswith('grok'):
        return 'xai'
    # Every gpt-* and o-series name goes to OpenAI first-party. The relay also lists two of
    # these names, but it swaps SKUs silently and its balance is $0.01; a first-party endpoint
    # that reports the model it actually ran is worth more than a reseller's convenience.
    if m.startswith(('gpt-', 'o3', 'o4', 'chatgpt')):
        return 'openai'
    return 'relay' 

# A judge must not grade its own family's writing, and a blind test needs a reader that never
# saw the generator. Both are picked here so no caller has to remember the rule.
# Cross-vendor and, now, cross-provider. Picked from what a cache-disabled probe found live on
# 2026-09-21: the relay serves only the two Claude models, xAI serves the Grok family directly.
# Neither judge may share a family with a writer. The drafts under test were written by the local
# Qwen 4B and by Grok, so the Grok models are disqualified as judges this round however capable
# they are — a model grading its own family's output is the one bias this test cannot absorb.
# That leaves the two Anthropic models. They are not independent of each other, which weakens
# agreement as a signal; it does not weaken either one's verdict on a piece neither family wrote.
# No judge may share a family with a writer. The drafts under test were written by the local
# Qwen 4B and by Grok, which disqualifies every Grok model as a judge this round however capable
# it is. OpenAI first-party is clear of both and, unlike the relay, reports the model it ran.
JUDGE = 'gpt-6-astra'
SECOND_JUDGE = 'gpt-4.1'

# 503/502/429/500 from this relay mean it has no upstream channel free, not that the request is
# wrong. Retry those and nothing else.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 4
BACKOFF = 3.0


class ReviewUnavailable(RuntimeError):
    """Raised instead of returning a guess, so a gate fails closed rather than passing silently."""


def _env(provider='relay'):
    f = ROOT / '.env'
    if not f.is_file():
        raise ReviewUnavailable('no project-root .env')
    out = {}
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    prefix = {'xai': 'XAI', 'openai': 'OPENAI', 'relay2': 'RELAY2'}.get(provider, 'REVIEW')
    key, base = out.get(f'{prefix}_API_KEY'), out.get(f'{prefix}_BASE_URL')
    if not key or not base:
        raise ReviewUnavailable(f'{prefix}_API_KEY or {prefix}_BASE_URL missing from .env')
    return {'key': key, 'base': base, 'provider': provider}


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True)
                          .encode('utf-8')).hexdigest()[:16]


def ask(messages, model=JUDGE, temperature=0.0, seed=7, max_tokens=1600,
        json_object=False, purpose='unspecified', use_cache=True, timeout=180):
    """One review call. Returns `(text, record)`; the record is what was written to the log.

    Cached on the exact request, because a gate gets re-run constantly while downstream code is
    being fixed and an identical question should not be re-billed or, worse, answered differently
    the second time — a threshold that moves under a stable input is not a threshold.
    """
    # `model` may carry our own routing prefix; the vendor must not see it.
    wire_model = strip_route(model)
    payload = {'model': wire_model, 'messages': messages}
    # OpenAI's gpt-5 and o-series renamed the output cap and stopped accepting a temperature
    # other than the default; sending the older field names is a 400 before anything runs.
    newer_openai = _provider(model) == 'openai' and wire_model.startswith(('gpt-5', 'gpt-6', 'o3', 'o4'))
    if newer_openai:
        payload['max_completion_tokens'] = max_tokens
    else:
        payload['max_tokens'] = max_tokens
        payload['temperature'] = temperature
        if seed is not None:
            payload['seed'] = seed
    if json_object:
        payload['response_format'] = {'type': 'json_object'}

    key = _digest(payload)
    CACHE.mkdir(parents=True, exist_ok=True)
    hit = CACHE / f'{key}.json'
    if use_cache and hit.is_file():
        c = json.loads(hit.read_text())
        return c['text'], {**c['record'], 'cache': 'hit'}

    # Checked before the request is built, so a call that would cross the cap costs nothing.
    estimate = budget.check(model, messages, max_tokens)

    env = _env(_provider(model))
    req = urllib.request.Request(
        env['base'].rstrip('/') + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + env['key'],
                 'Content-Type': 'application/json'})
    t0 = time.time()
    # The relay answered 43 consecutive calls and then failed 22 of the next 40 with
    # 503 "No available channel for model" — it runs out of upstream capacity and says so. That
    # is transient infrastructure, not a verdict, and treating it as a verdict silently halved a
    # blind test's sample. Retries are bounded and only for that class; a 4xx is the request's
    # fault and is not repeated.
    body, last = None, None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode('utf-8', 'replace')
            last = f'HTTP {e.code} from {env["provider"]}: {detail}'
            if e.code not in RETRY_STATUS or attempt == RETRIES - 1:
                raise ReviewUnavailable(last) from None
        except Exception as e:
            last = f'{type(e).__name__}: {e}'
            if attempt == RETRIES - 1:
                raise ReviewUnavailable(last) from None
        time.sleep(BACKOFF * (2 ** attempt))
    if body is None:
        raise ReviewUnavailable(last or 'no response')

    try:
        text = body['choices'][0]['message']['content']
    except (KeyError, IndexError):
        raise ReviewUnavailable(f'unexpected relay response shape: {str(body)[:200]}') from None

    spent = budget.record(model, body.get('usage'), estimate)
    record = {
        'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'usd_estimated': round(estimate, 6), 'usd_charged': round(spent, 6),
        'usd_spent_total': round(budget.spent(), 6), 'usd_cap': budget.cap(),
        'purpose': purpose, 'model': model, 'model_reported': body.get('model'),
        'temperature': temperature, 'seed': seed, 'max_tokens': max_tokens,
        'prompt_sha256_16': key, 'messages': len(messages),
        'prompt_chars': sum(len(m.get('content', '')) for m in messages),
        'usage': body.get('usage'), 'seconds': round(time.time() - t0, 2),
        'provider': env['provider'], 'endpoint_host': env['base'].split('/')[2],
        'review_label': 'model_reviewed',
        'note': 'a model verdict; never a human approval',
    }
    STORE.mkdir(parents=True, exist_ok=True)
    with RUNS.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    hit.write_text(json.dumps({'text': text, 'record': record}, ensure_ascii=False, indent=2))
    return text, {**record, 'cache': 'miss'}


def ask_json(messages, **kw):
    """Same call, but the caller needs a parsed object and a malformed answer must not pass.

    The relay fronts several vendors and they do not all honour `response_format`, so the text is
    recovered from a fenced block when the model wraps it.
    """
    text, rec = ask(messages, json_object=kw.pop('json_object', True), **kw)
    raw = text.strip()
    if raw.startswith('```'):
        raw = raw.split('```')[1]
        raw = raw.split('\n', 1)[1] if raw[:4].lower() in ('json', 'json\n') or \
            raw.lower().startswith('json') else raw
    start = min((i for i in (raw.find('{'), raw.find('[')) if i >= 0), default=-1)
    if start < 0:
        raise ReviewUnavailable(f'no JSON in reply: {text[:160]}')
    end = max(raw.rfind('}'), raw.rfind(']'))
    try:
        return json.loads(raw[start:end + 1]), rec
    except json.JSONDecodeError as e:
        raise ReviewUnavailable(f'unparseable JSON from {rec["model"]}: {e}') from None


def usage_summary():
    """What the relay has been asked so far, by purpose. Paid calls should be countable."""
    if not RUNS.is_file():
        return {'calls': 0}
    rows = [json.loads(l) for l in RUNS.read_text(encoding='utf-8').splitlines() if l.strip()]
    by = {}
    for r in rows:
        b = by.setdefault(r['purpose'], {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0})
        b['calls'] += 1
        u = r.get('usage') or {}
        b['prompt_tokens'] += u.get('prompt_tokens') or 0
        b['completion_tokens'] += u.get('completion_tokens') or 0
    return {'calls': len(rows), 'by_purpose': by,
            'models': sorted({r['model'] for r in rows})}


if __name__ == '__main__':
    if '--usage' in sys.argv:
        print(json.dumps(usage_summary(), ensure_ascii=False, indent=2))
        raise SystemExit
    if '--all-models' in sys.argv:
        for m in MODELS + XAI_MODELS:
            try:
                txt, rec = ask([{'role': 'user', 'content': 'Reply with the single word: ready'}],
                               model=m, max_tokens=16, purpose='connectivity_check')
                print(f"  {m:32} {_provider(m):6} -> {txt.strip()[:12]!r} "
                      f"reported={rec.get('model_reported')}")
            except ReviewUnavailable as e:
                print(f"  {m:32} {_provider(m):6} -> {str(e)[:70]}")
        raise SystemExit
    model = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--model=')), JUDGE)
    text, rec = ask([{'role': 'user', 'content': 'Reply with the single word: ready'}],
                    model=model, max_tokens=16, purpose='connectivity_check')
    print(f"{rec['model']} -> {text.strip()!r}  cache={rec['cache']}  usage={rec.get('usage')}")
