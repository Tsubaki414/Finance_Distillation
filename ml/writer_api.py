"""Remote generation, for the stronger-model comparison the skill asks for.

`ml/review_api.py` states in its own docstring that it has no generation entry point, so that a
later caller could not quietly turn the reviewer into an author. That property is worth keeping,
so this is a separate module rather than a flag on that one. Review calls and generation calls
stay distinguishable in the run log for as long as the log exists.

Authorisation, recorded because it was not the original scope:

    2026-09-17  relay key supplied. Scope stated by the user: 「英文中文都可以用他来把关，
                以及盲测评审」 — gating and blind-test judging. Not writing.
    2026-09-21  xAI key supplied, and the plan whose P1 is exactly this comparison — three
                writers on identical evidence and budget — was approved with "go". P1 was
                marked 「需要你授权……在你说可以之前不会跑」 in that plan before approval.
    2026-09-24  a second relay supplied with 「我刚刚加了一个中转站api在里面，请用大模型去生成」.
                That is generation, stated as such, so it is no longer a comparison arm — it is
                the writer. Reached as `relay2/<model>`; see `ml/review_api.RELAY2_PREFIX` for
                why the route is explicit rather than inferred from the model name.

Why a comparison and not a switch. `financial-persona-distillation/SKILL.md`:

    When a small-model baseline invents numbers or confuses style metrics with evidence,
    preserve the failed run. Compare a stronger frozen model and structured fact rendering
    before considering training.

The local 4B clears every gate except sentence-length variation, and every external cause for
that has been ruled out one at a time: the per-sentence prompt scaffold is gone, exemplars are
now selected for pacing, attempts were raised to seven, the floor was re-derived per piece
length, and the example sentence the model had been pasting was removed. What remains is either
the model or something still unnoticed in the pipeline, and only a controlled swap answers that.

So the same fact pack, the same rendered slots, the same prompt, the same attempt budget and the
same gates go to each writer. The only thing that varies is which model writes.

Run records land in `runs/model_calls/` and `runs/api_run_ledger.jsonl` alongside the local ones,
in the same shape, so a later reader can compare them without knowing which module produced them.
"""
from pathlib import Path
import sys, json, time, uuid, datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml import review_api

LEDGER = ROOT / 'runs/api_run_ledger.jsonl'
CALLS = ROOT / 'runs/model_calls'

# The system prompt the local path sends, so the comparison differs by model and nothing else.
try:
    from model_client import SYSTEM_PROMPT
except Exception:  # pragma: no cover - only when scripts/ is not on the path
    sys.path.insert(0, str(ROOT / 'scripts'))
    from model_client import SYSTEM_PROMPT


def remote_call(prompt, task, tokens, temperature=0.2, model='grok-4.6'):
    """One generation call, shaped like `content.generate_slotted.local_call`'s return.

    Same keys, same ledger, same failure behaviour: a failed call raises rather than returning
    something a caller might mistake for output.
    """
    rid = 'remote-' + uuid.uuid4().hex[:16]
    started = time.monotonic()
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt}]
    record = {
        'run_id': rid, 'task': task,
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'provider': review_api._provider(model),
        'model_lock': {'model': model, 'frozen': False,
                       'note': 'hosted model; the vendor may change it under this name'},
        'request': {'model': model, 'messages': messages, 'max_tokens': tokens,
                    'temperature': temperature},
        'paid_api_cost': None,
        'cost_scope': 'paid hosted inference; the endpoint does not return a price',
        'authorised_for': 'writer comparison (PLAN.md P1), approved 2026-09-21',
        'status': 'started',
    }
    CALLS.mkdir(parents=True, exist_ok=True)
    (CALLS / f'{rid}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    try:
        text, meta = review_api.ask(messages, model=model, temperature=temperature,
                                    seed=42, max_tokens=tokens, purpose=f'generate:{task}',
                                    use_cache=False, timeout=600)
        record.update(status='completed', text=text, usage=meta.get('usage'),
                      model_reported=meta.get('model_reported'),
                      endpoint_host=meta.get('endpoint_host'))
    except Exception as e:
        record.update(status='failed', error=type(e).__name__ + ': ' + str(e)[:400])
    record['duration_seconds'] = round(time.monotonic() - started, 3)
    record['_latency_s'] = record['duration_seconds']
    (CALLS / f'{rid}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open('a') as f:
        f.write(json.dumps({k: v for k, v in record.items()
                            if k not in ('request', 'text', 'model_lock')},
                           ensure_ascii=False) + '\n')
    if record['status'] != 'completed':
        raise RuntimeError(record['error'])
    return record


def writer(model):
    """A callable with `local_call`'s signature, for whichever model was asked for.

    `--writer=local` returns the local path unchanged, so the control arm runs through exactly the
    same code as the treatment arms.
    """
    if model in (None, '', 'local'):
        from content.generate_slotted import local_call
        return local_call

    def call(prompt, task, tokens, temperature=0.2):
        return remote_call(prompt, task, tokens, temperature, model=model)
    return call
