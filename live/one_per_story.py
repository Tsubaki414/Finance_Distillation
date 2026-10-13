"""One draft per account per story per day (Oct 12 2026).

The 10-12 audit found crypto_btc_cycle_zh with four inbox drafts built from a single ChainCatcher article
(web3vc moving 1.79M UNI to Binance), and similar same-story repeats on other accounts. Cause: every round
(nightly, midday, each --fill round) re-selects from the day's pool, and the existing guards do not cover it —
`tried_sources` skips a source only within a fill run of the same process, `story_dedupe` compares the day's
story ledger across *accounts* (not repeats inside one account) and only for rows that are still shippable, so
a round of held drafts leaves the story free for the next round to pick again.

Rule: for one Beijing day, one account keeps ONE draft per story key. Story key = the source's canonical URL
when it has one, else its source id, else its normalised title (same chain of fallbacks the pipeline already
uses for dedupe). The keeper is the best row: a ready (not held, draft_ready) row beats a held one; among
equals the earliest written row wins, so the first round's result is preserved and later rounds are held.

Kill switch: FD_ONE_PER_STORY=0 disables it (default 1 = on). Nothing is deleted — losing rows stay in the
inbox as holds with reason `dup_story: ...`, so a reviewer can still promote one by hand.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

CODE = 'dup_story'
WS = re.compile(r'\s+')


def enabled(env: dict | None = None) -> bool:
    return (env or os.environ).get('FD_ONE_PER_STORY', '1') != '0'


def story_key(row: dict) -> str | None:
    """Canonical story key for a row: source URL (tracking params dropped) > source id > title."""
    src = row.get('source') or {}
    url = str(src.get('url') or '').strip()
    if url:
        return 'u:' + url.split('?')[0].rstrip('/').lower()
    for k in ('source_id', 'id'):
        v = str(src.get(k) or '').strip()
        if v and v not in ('None', 'null'):
            return 's:' + v.lower()
    title = WS.sub('', str(src.get('title') or '')).lower()
    return 't:' + title[:120] if title else None


def _rank(row: dict) -> tuple:
    """Lower sorts better: ready beats held, then the earliest stored row."""
    ready = 0 if (row.get('draft_status') == 'draft_ready' and not row.get('held')) else 1
    return (ready, str(row.get('stored_at') or row.get('created_at') or ''), str(row.get('id') or ''))


def apply(rows: list[dict], env: dict | None = None, log=None) -> list[dict]:
    """Hold every row after the first for each (account, story key) of one day. Rows are modified in place.

    Rows already held keep their own reason; only un-held duplicates and duplicates held by a weaker code are
    re-marked, so a real content hold is never overwritten by a duplicate hold."""
    if not enabled(env):
        return []
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if not str(r.get('text') or r.get('body') or '').strip():
            continue
        if r.get('superseded') or r.get('published'):
            continue
        key = story_key(r)
        if not key:
            continue
        groups.setdefault((r.get('account_id'), key), []).append(r)
    held = []
    for (account, key), grp in groups.items():
        if len(grp) < 2:
            continue
        ordered = sorted(grp, key=_rank)
        keeper = ordered[0]
        for row in ordered[1:]:
            if row.get('held') and row.get('hold_reason') and not str(row['hold_reason']).startswith(CODE):
                continue   # a real content hold: leave its reason alone
            row['held'] = True
            row['hold_reason'] = f'{CODE}: {len(grp)} drafts for this account share one story ({key[2:60]})'
            row['dup_story_of'] = keeper.get('id')
            if row.get('draft_status') == 'draft_ready':
                row['draft_status'] = 'needs_review'
            held.append({'account_id': account, 'id': row.get('id'), 'kept': keeper.get('id'), 'key': key})
            if log:
                log(f"[one_per_story] {account} {row.get('id')}: dup of {keeper.get('id')} ({key[2:60]})")
    return held


def apply_day(day: str, base: Path | None = None, env: dict | None = None, log=None,
              write: bool = True) -> dict:
    """Run the rule over one inbox day and (by default) write the changed rows back.

    Returns {'day', 'rows', 'held': [...], 'kept': n}."""
    from live import compose_inbox
    rows = compose_inbox.rows(str(day), base=base) if base else compose_inbox.rows(str(day))
    before = {r.get('id'): (r.get('held'), r.get('hold_reason')) for r in rows}
    held = apply(rows, env=env, log=log)
    changed = 0
    for r in rows:
        if before.get(r.get('id')) != (r.get('held'), r.get('hold_reason')):
            changed += 1
            if write:
                compose_inbox.add(r, base=base) if base else compose_inbox.add(r)
    return {'day': str(day), 'rows': len(rows), 'changed': changed, 'held': held}


# ---------------------------------------------------------------- Oct 13: cross-account cap at SELECTION time
# Fiona (10-13): do not spend tokens drafting a story that a later gate will hold. One pick per story across all
# accounts of the day, decided before any model call. Story keys of a pick: its canonical source key (URL > source
# id > title, as story_key) plus its day motif keys ('motif:<day>:<id>' from the story labeller). Today's ready
# inbox rows lock their keys first; then picks are taken in pick_order, round-robin, first come first kept.
# Kill switch: FD_STORY_CAP_SELECT=0.

def select_cap_enabled(env: dict | None = None) -> bool:
    return (env or os.environ).get('FD_STORY_CAP_SELECT', '1') != '0'


def pick_keys(pick: dict) -> set:
    keys = set()
    k = story_key({'source': {'url': pick.get('url'), 'source_id': pick.get('source_id'), 'title': pick.get('title')}}
                  if 'source' not in pick else pick)
    if k:
        keys.add(k)
    for s in ((pick.get('story') or {}).get('keys') or []):
        if str(s).startswith('motif:'):
            keys.add(str(s))
    return keys


def cap_plan(plan: dict, order: list, existing_rows=(), env: dict | None = None, log=None) -> list:
    """Drop picks whose story is already taken (today's ready rows, or an earlier pick of another account).
    plan is modified in place; returns [(account, title, key)] dropped."""
    if not select_cap_enabled(env):
        return []
    taken = {}
    for r in existing_rows or ():
        if r.get('superseded') or r.get('held') or r.get('draft_status') != 'draft_ready':
            continue
        for k in pick_keys(r):
            taken.setdefault(k, r.get('account_id'))
    accts = [a for a in (order or []) if a in plan] + [a for a in plan if a not in (order or [])]
    kept = {a: [] for a in plan}
    from live import depth_check as _dc   # Oct 13: analysis sources before headline/flash sources (stable)
    queues = {a: sorted(plan[a], key=lambda p: _dc.enabled(env) and _dc.is_headline_source(p)) for a in plan}
    dropped = []
    while any(queues.values()):
        for a in accts:
            if not queues[a]:
                continue
            p = queues[a].pop(0)
            ks = pick_keys(p)
            hit = next((k for k in ks if taken.get(k) not in (None, a)), None)
            if hit:
                dropped.append((a, str(p.get('title'))[:60], hit))
                if log:
                    log(f'[{a}] story cap: skip pick (story taken by {taken[hit]}: {hit[:60]})')
                continue
            for k in ks:
                taken.setdefault(k, a)
            kept[a].append(p)
    for a in plan:
        plan[a][:] = kept[a]
    return dropped
