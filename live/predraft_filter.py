"""Pre-draft filters (Oct 13 07:37 London, Fiona): drop picks BEFORE any compose call when the draft would be held.

Applied to daily_compose's plan right after selection (and the cross-account story cap). Each rule has a kill switch,
default on; FD_PREDRAFT=0 turns all of them off.
  FD_PRE_FRESH     source > 48 h old at the planned slot (or the selection time) -> skip. Archive / look-back rows do
                   not come through this plan (live/archive_lookback.py, gated on a dated past post + framing).
  FD_PRE_LOOKBACK  a fresh-news pick whose own title already carries a look-back frame (回看 / 再看 / 复盘 / look back)
                   -> skip: compose turns it into an unanchored 回看 (lookback_unframed holds).
  FD_PRE_FACTS     the pick must carry extractable source facts: a headline / flash source (lf- / *flash* / sina-flash
                   / em-flash) with no numbers -> skip (headline-only, no source insight); any pick with no numbers and
                   at most one unit -> skip.
  FD_PRE_BTC_TVN   BTC then-vs-now look-backs: at most FD_PRE_BTC_TVN_MAX (default 1) per Beijing day across accounts
                   (counted in live/archive_lookback.py from today's inbox rows + this run).
Accounts left with no pick simply get no draft (no padding)."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

LOOKBACK_TITLE = re.compile(r'^\s*(?:回看|再看|复盘|回顾|look\s*back|looking\s*back|throwback)', re.I)
HEADLINE_SRC = re.compile(r'^(?:lf-|em-flash|sina-flash|wscn-flash)|flash', re.I)


def on(name, env=None):
    env = env if env is not None else os.environ
    return env.get('FD_PREDRAFT', '1') != '0' and env.get(name, '1') != '0'


def _ts(v):
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _num_count(p):
    n = p.get('numbers')
    return len(n) if isinstance(n, (list, tuple, dict)) else int(n or 0)


def reason(pick, ref=None, max_age_h=None, env=None):
    """Why this pick would be held, or None to keep it."""
    env = env if env is not None else os.environ
    max_age_h = float(max_age_h or env.get('FD_PRE_FRESH_H', 48))
    evergreen = (str((pick.get('archive') or {}).get('variant') or pick.get('variant') or '') == 'evergreen'
                 or str(pick.get('id') or pick.get('source_id') or '').startswith('evg-'))
    if on('FD_PRE_FRESH', env) and not evergreen:   # Oct 13 07:56 (Fiona): 常青 exempt from the 48 h rule
        pub = _ts(pick.get('published_at'))
        at = _ts(pick.get('suggested_post_time_london')) or ref
        if pub is None:
            return 'pre_fresh: no publish time'
        if at is not None and (at - pub).total_seconds() / 3600 > max_age_h:
            return f'pre_fresh: source {(at - pub).total_seconds() / 3600:.1f}h old at the slot (> {max_age_h:g}h)'
    if on('FD_PRE_LOOKBACK', env) and LOOKBACK_TITLE.match(str(pick.get('title') or '')):
        return 'pre_lookback: look-back framed title on a fresh-news pick (no dated past anchor)'
    if on('FD_PRE_FACTS', env):
        nums, units = _num_count(pick), len(pick.get('unit_ids') or [])
        if nums == 0 and HEADLINE_SRC.search(str(pick.get('source_id') or '')):
            return 'pre_facts: headline/flash source with no extractable figures or insight'
        if nums == 0 and units <= 1:
            return 'pre_facts: no source numbers and a single unit'
    return None


def apply(plan, ref=None, env=None, log=None):
    """Drop held-to-be picks from plan (in place). Returns [(account, source_id, reason)]."""
    if (env if env is not None else os.environ).get('FD_PREDRAFT', '1') == '0':
        return []
    dropped = []
    for aid, picks in plan.items():
        keep = []
        for p in picks:
            if p.get('rewrite_of'):
                keep.append(p)   # a reviewer-requested rewrite always runs
                continue
            why = reason(p, ref, env=env)
            if why:
                dropped.append((aid, p.get('source_id'), why))
                if log:
                    log(f'[{aid}] predraft skip: {why} ({str(p.get("title"))[:40]})')
            else:
                keep.append(p)
        picks[:] = keep
    return dropped


def btc_tvn_max(env=None):
    env = env if env is not None else os.environ
    return int(env.get('FD_PRE_BTC_TVN_MAX', 1)) if on('FD_PRE_BTC_TVN', env) else None


def btc_tvn_today(rows):
    """Today's live (not held / superseded) BTC then-vs-now archive rows."""
    return sum(1 for r in rows or () if not r.get('held') and not r.get('superseded')
               and r.get('draft_status') in ('draft_ready', None, '')
               and ((r.get('archive') or {}).get('variant', 'then_vs_now') == 'then_vs_now')
               and str(((r.get('archive') or {}).get('then_vs_now') or {}).get('label') or '').upper() == 'BTC')
