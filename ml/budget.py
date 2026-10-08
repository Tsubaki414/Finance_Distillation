"""A hard spending cap, checked before each paid call rather than tallied after it.

This exists because I spent the user's money without telling them first. Seventy calls to xAI over
five and a half hours — most of the tokens in twelve long generation calls — and the first they
knew of it was three bills. The authorisation was real (they supplied the key; they approved a
plan whose P1 was exactly that experiment) and it is still not an excuse: they could not have
known the size of it, because I never said, and because the endpoints do not return a price.

So the cap is enforced in code, before the request goes out:

  estimate first     A call is priced from its own prompt and its `max_tokens` ceiling before it
                     is sent. If that estimate would cross the cap, the call is refused and
                     nothing is spent finding out.
  assume the worst   The estimate charges the full `max_tokens` as output even though most calls
                     return less, and rounds the token count up. An estimate that runs low is a
                     cap that does not hold.
  reconcile after    Actual usage replaces the estimate in the ledger once the response arrives,
                     so the running total tracks what was really billed, not what was feared.

Prices are the published list rates as I understand them, and **they are my figures, not the
vendors'**. Nothing here reads a real invoice. If a rate below is wrong the ledger is wrong in
the same direction, so it is written to be corrected: change the number, run
`python -B ml/budget.py --recost`, and every past call is repriced from its recorded tokens.
"""
from __future__ import annotations
from pathlib import Path
import json, math, sys, datetime, fcntl
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'ml/store'
LEDGER = STORE / 'spend.json'
RUNS = STORE / 'review_runs.jsonl'
DISTILLATION_RUNS = STORE / 'distillation_spend.jsonl'

DEFAULT_CAP_USD = 10.0

# USD per 1M tokens, (input, output). My figures — see the module docstring.
# The relay resells other vendors' models, so its rows use the underlying vendor's list price as
# a proxy; a reseller's margin would make the real cost higher, never lower.
PRICES = {
    # TypeSafe official Jev API pricing checked 2026-10-02; developer advice only.
    'typesafe/jev-1.13.0': (0.042, 0.0),
    'grok-4.6': (3.00, 15.00),
    'grok-4.5': (3.00, 15.00),
    'grok-4.3': (3.00, 15.00),
    'grok-4.20-0309-reasoning': (3.00, 15.00),
    'grok-4.20-0309-non-reasoning': (3.00, 15.00),
    'grok-4.20-multi-agent-0309': (3.00, 15.00),
    'claude-opus-5': (15.00, 75.00),
    'claude-sonnet-5': (3.00, 15.00),
    'gemini-3.1-pro': (1.25, 10.00),
    'gemini-3.8-flash': (0.30, 2.50),
    'gpt-6-astra': (5.00, 20.00),
    'gpt-5.6-sol': (2.50, 10.00),
    # OpenAI first-party, what this account actually has access to.
    'gpt-4.1': (2.00, 8.00),
    'gpt-4.1-mini': (0.40, 1.60),
    'gpt-4.1-nano': (0.10, 0.40),
    'gpt-4o': (2.50, 10.00),
    'gpt-4o-mini': (0.15, 0.60),
    'gpt-4-turbo': (10.00, 30.00),
    'gpt-5': (1.25, 10.00),
    'gpt-5-mini': (0.25, 2.00),
    'gpt-5-nano': (0.05, 0.40),
    'gpt-5.6-sol': (2.50, 10.00),
    'gpt-5.6-luna': (2.50, 10.00),
    'gpt-5.6-terra': (2.50, 10.00),
    'gpt-6-astra': (5.00, 20.00),
    'o3': (2.00, 8.00),
    'o4-mini': (1.10, 4.40),
}
# Anything unlisted is charged at the most expensive row, so an unknown model cannot slip past
# the cap by being cheap on paper.
FALLBACK = (15.00, 75.00)


class BudgetExceeded(RuntimeError):
    """Raised instead of sending the request. Nothing is spent discovering the cap is reached."""


# The relay publishes its own rates at https://koalaapi.com/api/pricing as `model_ratio` and
# `completion_ratio`, in the new-api convention where input $/M = model_ratio x 2 and output
# $/M = that x completion_ratio. Read 2026-09-24.
#
# Charging vendor list price for these was not the harmless conservatism it looked like. The
# ledger said $8.00 of a $10 cap and the true figure was $3.36, so a decision about whether to
# raise the cap was being made against a number inflated by 2.4x. A spending cap that errs high
# still errs: it stops work that the budget could afford.
#
# The spread also matters for choosing a model. gemini-3.1-pro-preview is $75/$300 — fifteen
# times gpt-5.5 on input — and nothing in the name says so.
RELAY2_PRICES = {
    'gpt-5.5': (5.00, 30.00),
    'gpt-5.4': (2.50, 15.00),
    'gpt-5.4-mini': (0.75, 4.50),
    'claude-opus-5': (5.00, 25.00),
    'claude-sonnet-5': (2.00, 10.00),
    'gemini-3-flash': (0.50, 3.00),
    'gemini-3.1-pro-preview': (75.00, 300.00),
}


def price_of(model):
    m = str(model)
    if m.startswith('relay2/'):
        bare = m[len('relay2/'):]
        # Relay rates first: the same SKU costs a different amount through the relay than
        # first-party, and using the first-party row silently mis-bills every relay call.
        return RELAY2_PRICES.get(bare, PRICES.get(bare, FALLBACK))
    return PRICES.get(m, FALLBACK)


def estimate_tokens(messages, max_tokens):
    """Conservative token counts for a call that has not happened yet.

    Chinese runs about 1.5 characters per token and English about 4, so the mixed-script estimate
    divides by 2 — deliberately low, which makes the token count high.
    """
    chars = sum(len(m.get('content') or '') for m in messages)
    return math.ceil(chars / 2) + 8, int(max_tokens or 0)


def cost_of(model, prompt_tokens, completion_tokens):
    pin, pout = price_of(model)
    return (prompt_tokens / 1e6) * pin + (completion_tokens / 1e6) * pout


def _load():
    if LEDGER.is_file():
        return json.loads(LEDGER.read_text())
    return {'cap_usd': DEFAULT_CAP_USD, 'spent_usd': 0.0, 'calls': 0,
            'note': 'estimated from recorded token counts and the price table in ml/budget.py; '
                    'no invoice is read'}


def cap():
    return float(_load().get('cap_usd') or DEFAULT_CAP_USD)


def spent():
    return float(_load().get('spent_usd') or 0.0)


def remaining():
    return cap() - spent() - _hold_now()


# Oct 6 v8: a per-slot coherence reserve. Inside `advisory()` (optional polish retries) the last
# `hold` dollars of the cap are off limits, so a later coherence repair (judgment / contradiction)
# still fits; outside it (main calls, coherence repairs) the whole cap is usable. hold=0 by default.
import contextlib as _contextlib
import contextvars as _contextvars
_HOLD = _contextvars.ContextVar('budget_advisory_hold', default=0.0)
_ADVISORY = _contextvars.ContextVar('budget_advisory_active', default=False)


def set_advisory_hold(usd):
    _HOLD.set(max(0.0, float(usd or 0.0)))


def advisory_hold():
    return _HOLD.get()


def _hold_now():
    return _HOLD.get() if _ADVISORY.get() else 0.0


@_contextlib.contextmanager
def advisory():
    token = _ADVISORY.set(True)
    try:
        yield
    finally:
        _ADVISORY.reset(token)


def check(model, messages, max_tokens):
    """Refuse the call if its own worst case would cross the cap. Returns the estimate."""
    pt, ct = estimate_tokens(messages, max_tokens)
    est = cost_of(model, pt, ct)
    left = remaining()
    if est > left:
        raise BudgetExceeded(
            f'refused before sending: this {model} call is estimated at ${est:.4f} '
            f'(worst case {pt} in + {ct} out) and only ${left:.4f} of the ${cap():.2f} cap is '
            f'left. Nothing was spent. Raise the cap in {LEDGER} or reduce max_tokens.')
    return est


def record(model, usage, estimate=None):
    """Reconcile: replace the estimate with what the response says was actually used."""
    u = usage or {}
    pt = u.get('prompt_tokens')
    ct = u.get('completion_tokens')
    if pt is None or ct is None:
        actual = estimate if estimate is not None else 0.0
        basis = 'estimate kept; the response reported no usage'
    else:
        actual = cost_of(model, pt, ct)
        basis = 'actual token counts from the response'
    d = _load()
    d['spent_usd'] = round(float(d.get('spent_usd') or 0.0) + actual, 6)
    d['calls'] = int(d.get('calls') or 0) + 1
    d['last'] = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 'model': model, 'usd': round(actual, 6), 'basis': basis}
    STORE.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    return actual


@contextmanager
def _reservation_lock():
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _save_atomic(data):
    tmp = LEDGER.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(LEDGER)


def _nonnegative_finite(value, name):
    """Reject invalid amounts before any ledger write or paid request."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite nonnegative number')
    if not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be a finite nonnegative number')
    return value


def _usage_cost(reservation, usage):
    """Only the model component is retained when token usage is unavailable."""
    u = usage or {}
    for field in ('prompt_tokens', 'completion_tokens'):
        if u.get(field) is not None:
            _nonnegative_finite(u[field], field)
    if u.get('prompt_tokens') is not None and u.get('completion_tokens') is not None:
        return _nonnegative_finite(cost_of(reservation['model'], u['prompt_tokens'],
                                          u['completion_tokens']), 'model cost')
    return reservation.get('model_estimate', reservation['estimate'])


def flat_rate_spent():
    """Nominal USD of calls served by flat-rate providers (subrouter): recorded, never counted toward the cap."""
    return float(_load().get('flat_rate_nominal_usd') or 0.0)


def reserve(model, messages, max_tokens, call_id, *, overhead_usd=0, counts_toward_cap=True, provider=None):
    """Reserve model estimate plus optional compute overhead before sending.

    Defaults preserve the legacy reservation schema and calculation. A provider's
    compute overhead is separate from token/rate estimates, not a model invoice.

    counts_toward_cap=False (Oct 8: flat-rate subrouter): no cap check and nothing added to spent_usd; the call is
    still ledgered (reservation + distillation_spend.jsonl line, tokens and nominal list-price cost, provider tag)
    and its settled nominal cost accumulates in flat_rate_nominal_usd / by_provider.
    """
    _nonnegative_finite(max_tokens, 'max_tokens')
    _nonnegative_finite(overhead_usd, 'overhead_usd')
    with _reservation_lock():
        d = _load()
        if call_id in d.get('reservations', {}):
            raise ValueError('duplicate budget reservation')
        # UTF-8 bytes is a conservative token upper bound, including JSON/chat overhead.
        pt = len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 256
        model_estimate = cost_of(model, pt, max_tokens)
        estimate = _nonnegative_finite(model_estimate + overhead_usd, 'reservation estimate')
        if not counts_toward_cap:
            reservation = {'model': model, 'estimate': estimate, 'settled': False,
                           'counts_toward_cap': False, 'provider': provider or 'flat_rate'}
            d.setdefault('reservations', {})[call_id] = reservation
            d['calls'] = int(d.get('calls', 0)) + 1
            _save_atomic(d)
            return estimate
        if estimate > float(d.get('cap_usd', DEFAULT_CAP_USD)) - float(d.get('spent_usd', 0)) - _hold_now():
            raise BudgetExceeded('distillation call would exceed configured spending cap'
                                 + (' (coherence reserve held)' if _hold_now() else ''))
        reservation = {'model': model, 'estimate': estimate, 'settled': False}
        if provider:
            reservation['provider'] = provider
        if overhead_usd:
            reservation.update(model_estimate=model_estimate, overhead_estimate=overhead_usd)
        d.setdefault('reservations', {})[call_id] = reservation
        d['spent_usd'] = round(float(d.get('spent_usd', 0)) + estimate, 6)
        d['calls'] = int(d.get('calls', 0)) + 1
        _save_atomic(d)
        return estimate


def settle(call_id, usage, *, overhead_actual_usd=None):
    """Reconcile known model tokens and overhead independently; keep unknown reserves."""
    if overhead_actual_usd is not None:
        _nonnegative_finite(overhead_actual_usd, 'overhead_actual_usd')
    with _reservation_lock():
        d = _load()
        r = d['reservations'][call_id]
        if r['settled']:
            return r['cost']
        model_cost = _usage_cost(r, usage)
        has_overhead = 'overhead_estimate' in r or overhead_actual_usd is not None
        overhead_cost = (r.get('overhead_estimate', 0) if overhead_actual_usd is None
                         else overhead_actual_usd)
        cost = _nonnegative_finite(model_cost + overhead_cost, 'settlement cost')
        if r.get('counts_toward_cap', True):
            d['spent_usd'] = round(float(d['spent_usd']) - r['estimate'] + cost, 6)
        else:
            d['flat_rate_nominal_usd'] = round(float(d.get('flat_rate_nominal_usd') or 0) + cost, 6)
            bp = d.setdefault('by_provider', {}).setdefault(r.get('provider') or 'flat_rate',
                                                            {'calls': 0, 'nominal_usd': 0.0, 'prompt_tokens': 0,
                                                             'completion_tokens': 0, 'counts_toward_cap': False})
            u = usage or {}
            bp['calls'] += 1
            bp['nominal_usd'] = round(bp['nominal_usd'] + cost, 6)
            bp['prompt_tokens'] += int(u.get('prompt_tokens') or 0)
            bp['completion_tokens'] += int(u.get('completion_tokens') or 0)
        r.update(settled=True, cost=cost, usage=usage)
        if has_overhead:
            r.update(model_estimate=r.get('model_estimate', r['estimate']),
                     overhead_estimate=r.get('overhead_estimate', 0),
                     model_cost=model_cost, overhead_cost=overhead_cost,
                     overhead_actual_usd=overhead_actual_usd,
                     overhead_basis=('reserved estimate kept; overhead usage unknown'
                                     if overhead_actual_usd is None else 'provider reported compute usage'))
        basis = ('token/rate estimate plus separate compute usage/reserve; not invoice'
                 if has_overhead else 'token/rate estimate; not invoice')
        if not r.get('counts_toward_cap', True):
            basis = 'nominal list-price estimate; flat-rate provider, not counted toward the cap'
        d['last'] = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'model': r['model'], 'usd': cost, 'basis': basis,
                     **({'provider': r['provider']} if r.get('provider') else {}),
                     **({'counts_toward_cap': False} if not r.get('counts_toward_cap', True) else {})}
        _save_atomic(d)
        DISTILLATION_RUNS.parent.mkdir(parents=True, exist_ok=True)
        with DISTILLATION_RUNS.open('a') as stream:
            stream.write(json.dumps({'call_id': call_id, **r}) + '\n')
        return cost


def recost():
    """Reprice every recorded call from its tokens. Run after correcting a price."""
    if not RUNS.is_file():
        return _load()
    total, n, by = 0.0, 0, {}
    for line in RUNS.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        u = r.get('usage') or {}
        pt, ct = u.get('prompt_tokens') or 0, u.get('completion_tokens') or 0
        c = cost_of(r.get('model'), pt, ct)
        total += c
        n += 1
        b = by.setdefault(r.get('model'), {'calls': 0, 'usd': 0.0})
        b['calls'] += 1
        b['usd'] = round(b['usd'] + c, 6)
    d = _load()
    # New reserved calls are in the ledger, not the legacy review-only journal.
    flat = 0.0
    for r in d.get('reservations', {}).values():
        if not r.get('counts_toward_cap', True):   # flat-rate (subrouter): nominal only, never toward the cap
            flat += _usage_cost(r, r.get('usage'))
            continue
        c = _usage_cost(r, r.get('usage'))
        # Never erase separately reserved/reported compute charges when repricing tokens.
        overhead = r.get('overhead_actual_usd')
        if overhead is None:
            overhead = r.get('overhead_estimate', 0)
        c += _nonnegative_finite(overhead, 'overhead cost')
        total += c
        n += 1
    if flat:
        d['flat_rate_nominal_usd'] = round(flat, 6)
    d.update(spent_usd=round(total, 6), calls=n, by_model=by,
             recost_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    STORE.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    return d


def set_cap(usd):
    d = _load()
    d['cap_usd'] = float(usd)
    STORE.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    return d


if __name__ == '__main__':
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    if 'cap' in args and args['cap'] is not True:
        set_cap(float(args['cap']))
    d = recost() if 'recost' in args else _load()
    print(json.dumps(d, ensure_ascii=False, indent=2))
    print(f"\n  已花 ${d.get('spent_usd', 0):.4f} / 上限 ${d.get('cap_usd', DEFAULT_CAP_USD):.2f}"
          f"   剩余 ${d.get('cap_usd', DEFAULT_CAP_USD) - d.get('spent_usd', 0):.4f}")
    print('  价格为我填写的估算值，非厂商账单；改价后跑 --recost 可重算全部历史。')
