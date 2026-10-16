"""Oct 16 (Fiona: independent lanes): primitives that let several compose lanes run at the same time.

Lanes: main (nightly compose + idle guard), engage (reply / quote pull), midday (fresh, per language),
fill (evergreen / archive / translation fill), mindmap. One blocked lane must not stall the others, so:

  * each lane holds its OWN flock (lane_lock), never one global compose lock;
  * the few places that read-check-write shared state (inbox rows, story / pick claims, the day spend ledger)
    take a short blocking file lock (day_lock, ~ms) - never held across a model call;
  * files are written atomically (atomic_write_text: temp file + os.replace) and appended with a lock;
  * one model call has a hard wall-clock deadline and one account's compose a total deadline.

Rollback: FD_LANES=0 -> enabled() is False and every caller falls back to the pre-lane behaviour (one global compose
lock, midday / engage skip while compose runs, plain writes, no deadlines).
Nothing here talks to the network or to the real store unless a caller passes a path under it.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

LANES = ('main', 'engage', 'midday', 'fill', 'mindmap')


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_LANES', '1') != '0'


def lock_dir(env=None):
    return Path((env if env is not None else os.environ).get('FD_LANE_LOCK_DIR') or '/workspace/x/compose_runs')


def lane_name(env=None):
    """Lane of this process: FD_LANE, else derived from the env the cron scripts already set."""
    env = env if env is not None else os.environ
    if env.get('FD_LANE'):
        return env['FD_LANE']
    if env.get('FD_ENGAGE_ONLY') == '1':
        return 'engage'
    if env.get('FD_MIDDAY') == '1':
        return 'midday'
    return 'main'


def lane_lock_path(lane, suffix='', env=None):
    """main keeps the historic .daily_compose.lock so a still-running pre-lane compose keeps excluding a new main."""
    d = lock_dir(env)
    if lane == 'main' and not suffix:
        return d / '.daily_compose.lock'
    return d / f'.lane_{lane}{("_" + suffix) if suffix else ""}.lock'


@contextlib.contextmanager
def lane_lock(lane, suffix='', env=None):
    """Non-blocking per-lane lock. Yields True when taken, False when another process of that lane holds it."""
    path = lane_lock_path(lane, suffix, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    got = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
        except OSError:
            got = False
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextlib.contextmanager
def day_lock(day, name='inbox', env=None, timeout=120.0):
    """Short blocking critical-section lock for <day>/<name>. Never hold it across a model call.
    On timeout it proceeds without the lock (and says so) rather than stalling a lane."""
    if not enabled(env):   # FD_LANES=0: pre-lane behaviour, no lock
        yield False
        return
    d = lock_dir(env) / 'locks'
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / f'{name}_{day}.lock', os.O_CREAT | os.O_RDWR, 0o644)
    got = False
    end = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.monotonic() > end:
                    print(f'[lanes] day_lock {name}_{day}: timeout after {timeout:.0f}s, continuing unlocked', flush=True)
                    break
                time.sleep(0.05)
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write_text(path, text):
    """Write temp file in the same directory then os.replace: a reader never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        with open(tmp, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def locked_append(path, line):
    """Append one line under an exclusive flock (O_APPEND alone interleaves long lines)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line if line.endswith('\n') else line + '\n')
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ------------------------------------------------------------------ pick claims (cross-lane anti-repeat)
CLAIM_TTL_S = 2 * 3600


def _claims_path(day, env=None):
    return lock_dir(env) / 'locks' / f'claims_{day}.json'


def claim_keys(account, pick):
    """Keys a pick takes: (account, story) for a standalone; the target post itself (any account) for engagement."""
    sid = str(pick.get('source_id') or '')
    keys = []
    if sid.startswith('x-'):
        keys.append(f'target:{sid}')          # one of our accounts per reply / quote target, across lanes
    else:
        keys.append(f'acct:{account}:{sid}')   # one story per account per day, across lanes
    return [k for k in keys if k.split(':')[-1]]


def claim_plan(day, plan, lane, run_id, env=None, now=None, log=None):
    """Cross-lane reservation of plan picks. Under day_lock: drop picks another LIVE claim (other lane / run, < TTL)
    already holds, record the rest. plan is modified in place; returns [(account, title, key, owner_lane)] dropped.
    Only a DIFFERENT lane's claim blocks: runs of one lane are serialised by its lane lock and already see each
    other through the inbox (one_per_story, tried_sources). Claims expire after CLAIM_TTL_S (crashed lane)."""
    now = now if now is not None else time.time()
    dropped = []
    with day_lock(day, 'claims', env):
        path = _claims_path(day, env)
        try:
            cur = json.loads(path.read_text())
        except (OSError, ValueError):
            cur = {}
        cur = {k: v for k, v in cur.items() if now - float(v.get('t', 0)) < CLAIM_TTL_S}
        for acct in list(plan):
            kept = []
            for p in plan[acct]:
                ks = claim_keys(acct, p)
                hit = next((k for k in ks if k in cur and cur[k].get('lane') != lane), None)
                if hit:
                    dropped.append((acct, str(p.get('title'))[:60], hit, cur[hit].get('lane')))
                    if log:
                        log(f'[{acct}] lane claim: skip pick ({hit[:70]} already claimed by lane {cur[hit].get("lane")})')
                    continue
                for k in ks:
                    cur[k] = {'lane': lane, 'run_id': run_id, 't': now}
                kept.append(p)
            plan[acct] = kept
        atomic_write_text(path, json.dumps(cur, ensure_ascii=False, indent=1))
    return dropped


# ------------------------------------------------------------------ day spend ledger (shared by lanes)
def _spend_path(day, env=None):
    return lock_dir(env) / 'locks' / f'spend_{day}.json'


def spend_add(day, lane, usd, env=None):
    """Add paid spend of a lane to the day ledger (read-modify-write under day_lock). Returns the day total."""
    usd = float(usd or 0)
    with day_lock(day, 'spend', env):
        p = _spend_path(day, env)
        try:
            cur = json.loads(p.read_text())
        except (OSError, ValueError):
            cur = {'total': 0.0, 'lanes': {}}
        if usd:
            cur['total'] = round(float(cur.get('total', 0)) + usd, 6)
            cur['lanes'][lane] = round(float(cur['lanes'].get(lane, 0)) + usd, 6)
            atomic_write_text(p, json.dumps(cur, indent=1))
        return float(cur.get('total', 0))


def spend_total(day, env=None):
    try:
        return float(json.loads(_spend_path(day, env).read_text()).get('total', 0))
    except (OSError, ValueError):
        return 0.0


def day_cap(env=None):
    try:
        return float((env if env is not None else os.environ).get('FD_DAILY_TOTAL_USD', '25'))
    except ValueError:
        return 25.0


def day_has_room(day, est, env=None):
    """True while the paid spend of all lanes today plus this call's estimate stays within FD_DAILY_TOTAL_USD."""
    return spend_total(day, env) + float(est or 0) <= day_cap(env)


# ------------------------------------------------------------------ deadlines + latency log
_ctx = threading.local()


class DeadlineExceeded(TimeoutError):
    pass


def call_timeout_s(env=None):
    try:
        return float((env if env is not None else os.environ).get('FD_CALL_TIMEOUT_S', '180'))
    except ValueError:
        return 240.0


def account_timeout_s(env=None):
    try:
        return float((env if env is not None else os.environ).get('FD_ACCOUNT_TIMEOUT_S', '900'))
    except ValueError:
        return 900.0


def grace_s(env=None):
    """Extra seconds the account runner waits past the account deadline for its helper thread to wind down."""
    try:
        return float((env if env is not None else os.environ).get('FD_ACCOUNT_GRACE_S', '30'))
    except ValueError:
        return 30.0


def set_context(**kw):
    """Per-thread context (account, deadline) read by the model client for the latency line and the account deadline."""
    for k, v in kw.items():
        setattr(_ctx, k, v)


def clear_context():
    for k in ('account', 'deadline'):
        if hasattr(_ctx, k):
            delattr(_ctx, k)


def context(name, default=None):
    return getattr(_ctx, name, default)


def time_left():
    """Seconds left of this thread's account deadline (None: no deadline)."""
    d = getattr(_ctx, 'deadline', None)
    return None if d is None else d - time.monotonic()


def call_budget_s(env=None):
    """Wall-clock allowed for the next model call: the per-call cap, shrunk to what the account deadline leaves.
    Raises DeadlineExceeded when the account deadline has already passed."""
    cap = call_timeout_s(env)
    left = time_left()
    if left is None:
        return cap
    if left <= 0:
        raise DeadlineExceeded('account compose deadline exceeded before the call')
    return max(1.0, min(cap, left))


def run_with_deadline(fn, seconds, *, what='call', ctx=None):
    """Run fn() in a helper thread; raise DeadlineExceeded when it has not finished in `seconds` wall-clock.
    The abandoned thread cannot be killed (its own HTTP read timeout ends it); its result is dropped. ctx: dict of
    thread-context values (account, deadline) copied into the helper thread."""
    box = {}

    def target():
        if ctx:
            set_context(**ctx)
        try:
            box['v'] = fn()
        except BaseException as exc:   # noqa: BLE001 - re-raised in the caller
            box['e'] = exc
        finally:
            clear_context()
    t = threading.Thread(target=target, daemon=True, name=f'deadline-{what}')
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise DeadlineExceeded(f'{what} exceeded {seconds:.0f}s wall-clock')
    if 'e' in box:
        raise box['e']
    return box.get('v')


def latency_line(account, stage, seconds, status):
    return f'[latency] account={account or "-"} stage={stage} seconds={seconds:.1f} status={status}'


def log_latency(stage, seconds, status, env=None, account=None):
    """Print one line and (when FD_LATENCY_JSONL is set) append a json row. Never raises."""
    try:
        env = env if env is not None else os.environ
        account = account or context('account')
        print(latency_line(account, stage, seconds, status), flush=True)
        path = env.get('FD_LATENCY_JSONL')
        if path:
            locked_append(path, json.dumps({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                            'lane': lane_name(env), 'account': account, 'stage': stage,
                                            'seconds': round(seconds, 1), 'status': status}))
    except Exception:   # noqa: BLE001
        pass
