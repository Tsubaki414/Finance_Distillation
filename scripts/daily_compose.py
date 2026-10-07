#!/usr/bin/env python3
"""Daily auto-compose for the 20 main accounts -> human review inbox (Oct 7, fd20). Never publishes.

Cron-able: does nothing unless FD_DAILY_COMPOSE=1 (or --force). Chain per day:
  units already ingested (scripts/daily_ingest.py)  ->  route: each account's retrieval beats
  (live/fd20_accounts.json; same- and cross-language material both allowed, no attribution line)  ->
  select up to --per-account packets per account (fresh, unused by that account, angle fit)  ->
  angle per draft (live/angles.py: the account's own donor lenses; one lens per account per event)  ->
  post type / length / suggested post time from the account's habit card (posting_habits.choose_format,
  sample_post_time)  ->  compose_source (stance + compose on Gemini (FD_GEMINI_PROVIDER relay|official, default relay), FD_GEMINI_ONLY=1, no
  Opus fallback)  ->  cross-account check (claim arbitration + batch shape findings, soft: losers HOLD)  ->
  review inbox (live/compose_inbox.py) + static page.

Spend: every call reserves against the ml/budget ledger; this run also stops starting drafts once its own
Gemini spend (call records) would pass --budget-usd.

  FD_DAILY_COMPOSE=1 python scripts/daily_compose.py [--day 2026-10-07] [--accounts a,b] [--per-account 2]
                                                     [--budget-usd 4] [--workers 4] [--select-only] [--fill]
                                                     [--now 2026-10-07T23:13+01:00]

The drafting day is the Beijing (Asia/Shanghai) calendar date: the inbox day, run dir, review page and the ops
dashboard's 08:00-22:59 北京时间 slots all use it. The cron run at 23:13 London (06:13 Beijing in BST, 07:13 in GMT)
drafts for that Beijing morning's date; selection then sees material up to the run time.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
import json
import os
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

import demo_matrix_compose as demo  # noqa: E402
from voice_relay_check import evidence_source  # noqa: E402
from live import (angles, anti_repeat, compose, compose_inbox, editorial_style, news_hook,  # noqa: E402
                  posting_habits as ph, registry, source_prescreen as prescreen, source_routes, stage_models)
from live.adapters import delphi_digest  # noqa: E402
from live.content_store import ContentStore  # noqa: E402
from live.retrieval import units_for_persona  # noqa: E402
from live.view_ledger import ViewLedger  # noqa: E402
from ml import budget  # noqa: E402

BJT = ZoneInfo('Asia/Shanghai')   # drafting day = Beijing calendar date (Oct 7)
CONFIG = ROOT / 'live' / 'fd20_accounts.json'
UNIVERSES = ROOT / 'live' / 'store' / 'fd20' / 'universes.json'
POSTS = ROOT / 'live' / 'donors' / 'posts'
TAGS = ROOT / 'live' / 'donors' / 'tags'
RUNS = Path(os.environ.get('FD_COMPOSE_RUNS', '/workspace/x/compose_runs'))
DASHBOARD = Path(os.environ.get('FD_COMPOSE_DASHBOARD', '/workspace/x/dashboard'))
MAX_PER_ACCOUNT = 3            # Fiona: 3 a day is a ceiling, not a quota
MAX_ACCOUNTS_PER_EVENT = 2     # one event may be taken by at most 2 accounts per language, each with its own lens
                               # (fix26: per language - 14 crypto accounts share ~12 crypto stories a day)
STAGE_CALLS = {'stance': 2, 'compose': 3}   # per draft: stance + 1 repair; first pass + 2 rewrites
# Oct 7 Sirius item 4: the one targeted hard-QA rewrite (compose '[hard_repair]' note) has its own allowance, so
# polish rewrites cannot use it up; 2 = the rewrite + one transport retry inside compose._ask.
HARD_REPAIR_CALLS = 2
EST_PER_DRAFT = 0.12           # reserve kept per draft still to start (flash list prices, conservative)
EST_PER_DRAFT_PRO = 0.30       # same reserve when compose runs on gemini-3.1-pro-preview (4x flash list prices)
QUOTA_RX = re.compile(r'RESOURCE_EXHAUSTED|PerDay|exceeded your current quota', re.I)
MAX_AGE_DAYS = 10              # selection window; inside it fresher (in-shelf, timely) packets rank first


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


# ---------------------------------------------------------------- selection

def used_sources(account):
    used = set()
    path = anti_repeat.HISTORY_DIR / f'{account}.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            used |= {row.get('source_hash'), row.get('source_title')}
    return {x for x in used if x}


def group_text(group):
    src = group[0]['source']
    return ' '.join([str(src.get('title') or '')] + [str(r['unit'].get('statement') or '') for r in group]
                    + [str((r['unit'].get('view') or {}).get('subject') or '') for r in group])


_TITLE_STOP = set('a an the of to in on for and or as at by with from is are its worth says after over new'.split())


def title_event(title):
    """('title', lead word, numbers) - two outlets' headlines on one story ("Robinhood adds $25 million worth of
    bitcoin to balance sheet as it deepens crypto push" / "Robinhood adds bitcoin worth $25 million to its balance
    sheet") share it. Headlines without a number key on their first three words; None for short titles."""
    toks = re.findall(r'[a-z0-9$.,]+|[\u4e00-\u9fff]{2,}', re.sub(r'\(part \d+/\d+\)', '', str(title or '').lower()))
    toks = [t.strip('.,') for t in toks if t.strip('.,') and t.strip('.,') not in _TITLE_STOP]
    if len(toks) < 3:
        return None
    nums = sorted({t for t in toks if re.search(r'\d', t)})
    return ('title', toks[0], *nums) if nums else ('title', *toks[:3])


def group_hooks(group):
    try:
        return set(news_hook.hooks(group_text(group)))
    except Exception:   # noqa: BLE001
        return set()


def timely(group, ref):
    src = group[0]['source']
    if str(src.get('adapter') or '').startswith('flash') or src.get('source_version') == 'flash-v1':
        return True
    try:
        t = datetime.fromisoformat(str(src.get('published_at') or '').replace('Z', '+00:00'))
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        return ref - t <= timedelta(hours=30)
    except ValueError:
        return False


def source_lang(group):
    return 'zh' if demo.zh_native(group) else 'en'


# Oct 7: X posts that open as a thank-you / congrats / welcome / announcement are promo, not material (an OKX
# "Thank you to the nearly 1,000 people..." post produced an invented first-person thesis).
X_PROMO_OPENER = re.compile(r'^\W*(thank(s| you)|huge congrats|congrat|grateful|welcome|excited to|proud to|'
                            r'thrilled|happy to announce|we(\'re| are) hiring|gm\b)', re.I)


def steered(group, tickers):
    """True when a pack names one of the inspiration-only digest tickers ($ETH / ETH as a whole word)."""
    if not tickers:
        return False
    text = group_text(group)
    return any(re.search(r'(?<![A-Za-z0-9])\$?' + re.escape(t) + r'(?![A-Za-z0-9])', text) for t in tickers)


def candidates(store, account, beats, lead, ref, x_handles=None, account_cfg=None, reuse=None):
    """x_handles: the account's own X sources. X-post units of other handles are skipped (X sources are
    account-scoped); own X posts rank right after timeliness, then packets on the account's own crypto lanes.
    account_cfg (fd20_accounts.json row): beat gate - a non-crypto account never gets a crypto packet and a crypto
    account never gets a packet without crypto content (Oct 7: Momo 美股札记 wrote GenLayer).
    reuse: source ids / titles / hashes this account may use again (its own drafts superseded for a rewrite); they
    rank first."""
    from live.jev_front import SUB_BEATS
    from live.x_daily import x_handle
    x_handles = {h.lower() for h in x_handles or ()}
    lane = {b for b in beats if b in SUB_BEATS}   # the account's own crypto lanes (meme / perp / defi / ...)
    reuse = set(reuse or ())
    used = used_sources(account) - reuse
    recent = anti_repeat.load_recent(account)
    seen, groups = set(), {}
    for beat in beats:
        for record in units_for_persona(store, beat, max_age_days=MAX_AGE_DAYS, as_of=ref):
            if record.get('licence_tier') not in ('A', 'B') or record['unit_id'] in seen:
                continue
            seen.add(record['unit_id'])
            src = record['source']
            if {src.get('id'), src.get('title'), src.get('source_hash')} & used:
                continue
            handle = x_handle(src)
            if handle and (handle.lower() not in x_handles or X_PROMO_OPENER.search(str(src.get('title') or ''))):
                continue
            if not source_routes.allowed(src, account):   # account-scoped research sources (Four Pillars)
                continue
            groups.setdefault(demo._key(record), []).append(record)
    gated = list(groups.values())
    if account_cfg:
        gated = [g for g in gated if editorial_style.beat_gate(account_cfg, group_text(g))[0]]
    options = demo.ranked_balanced(gated, now=ref.date().isoformat())
    top = set(angles.top_angles(lead, 4))
    # Delphi digest (inspiration_only): its tickers only break ties toward the same topic; nothing of it is passed on.
    # The newest digest written within 36h (not an exact day match: it is London-dated, the drafting day is Beijing's).
    steer = set(delphi_digest.steer_tickers(delphi_digest.latest(now=ref)['units']))

    def key(g):
        fit = len(top & set(angles.angles_of(group_text(g))))
        src = g[0]['source']
        return (not ({src.get('id'), src.get('title'), src.get('source_hash')} & reuse),
                not prescreen.prescreen(account, g)['ok'], not demo.in_shelf(g, ref.date().isoformat()),
                not timely(g, ref), not x_handle(g[0]['source']),
                bool(lane) and not any(lane & set(r.get('tag_personas') or []) for r in g), bool(demo.group_hook_repeat(g, recent)), demo.group_theme_repeat(g, recent),
                -fit, not steered(g, steer), -demo.group_freshness(g, ref.date().isoformat()))
    return sorted(options, key=key)


def drafted_today(day, ready_only=False):
    """{account: drafts with text already in the inbox for `day`} (an earlier run the same day counts toward the
    3-a-day ceiling). ready_only (--fill): only drafts still ready - not held, not superseded by an audit."""
    out = {}
    for r in compose_inbox.rows(day.isoformat()):
        if (r.get('text') or '').strip() and r.get('day') == day.isoformat():
            if ready_only and (r.get('held') or r.get('superseded') or r.get('draft_status') != 'draft_ready'):
                continue
            out[r['account_id']] = out.get(r['account_id'], 0) + 1
    return out


def ready_events(day, accounts):
    """(event, account, angle, lang) for today's ready drafts, so a fill run respects the per-event cap."""
    lang = {a['id']: a['lang'] for a in accounts}
    out = []
    for r in compose_inbox.rows(day.isoformat()):
        if r.get('held') or r.get('superseded') or r.get('draft_status') != 'draft_ready' or not r.get('text'):
            continue
        src = r.get('source') or {}
        angle = (r.get('angle') or {}).get('id') if isinstance(r.get('angle'), dict) else r.get('angle')
        events = ({('srcid', src.get('id'))} if src.get('id') else set()) | ({title_event(src.get('title'))} - {None})
        try:
            events |= {('hook', h) for h in news_hook.hooks(' '.join([str(src.get('title') or ''), r.get('body') or '']))}
        except Exception:   # noqa: BLE001
            pass
        out += [(e, r['account_id'], angle, lang.get(r['account_id'])) for e in events]
    return out


def superseded_sources(day):
    """{account: source ids/titles of its drafts an audit superseded with verdict rewrite} (--fill reuses them)."""
    return {a: set(m) for a, m in rewrite_targets(day).items()}


def rewrite_targets(day, notes=None):
    """{account: {source id/title: {'draft_id', 'note'}}} for --fill rewrites.

    Drafts an audit superseded with verdict rewrite carry the audit reason as the editor note. notes ({draft_id:
    note}, --rewrite-notes) adds held drafts to rewrite and/or replaces the note with targeted wording."""
    notes = dict(notes or {})
    out = {}
    for r in compose_inbox.rows(day.isoformat()):
        audit = r.get('audit') or {}
        if r['id'] in notes:
            note = notes[r['id']]
        elif r.get('superseded') and audit.get('verdict') == 'rewrite':
            note = audit.get('reason')
        else:
            continue
        src = r.get('source') or {}
        mine = out.setdefault(r['account_id'], {})
        for key in (src.get('id'), src.get('title')):
            if key and (r['id'] in notes or key not in mine):   # an explicit note beats an older audit reason
                mine[key] = {'draft_id': r['id'], 'note': note}
    return out


def supersede_previous(row, earlier):
    """Sirius item 4: a rerun / rewrite of the same account + source soft-replaces the earlier draft (marked
    superseded, superseded_by=row id); nothing is deleted and human-reviewed drafts are untouched."""
    src = (row.get('source') or {}).get('id')
    done = []
    for old in earlier:
        if old.get('id') == row['id'] or old.get('account_id') != row['account_id'] or old.get('run_id') == row['run_id']:
            continue
        rewrite = old.get('id') == row.get('rewrite_of')
        # a held rerun never replaces a draft that is still ready
        if rewrite or (src and (old.get('source') or {}).get('id') == src and (not row.get('held') or old.get('held'))):
            if compose_inbox.supersede(old['id'], by=row['id'], reason='rewrite' if rewrite else 'rerun'):
                done.append(old['id'])
    return done


def heat_led_today(day):
    return {r['account_id'] for r in compose_inbox.rows(day.isoformat()) if r.get('heat_led')}


def apply_heat(pools, day, ref, reuse=None):
    """Public heat (live/heat.py, FD_HEAT=1 default): move the hottest prescreen-ok, timely candidate of each account's
    own pool to the front. Never adds a candidate; skipped for an account that already has a heat-led draft today or
    has rewrite targets to reuse. Returns {account: (source key, heat info)} for the promoted candidates."""
    from live import heat
    if not heat.enabled():
        return {}
    try:
        signals = heat.signals_for(day.isoformat())
        led = heat_led_today(day)
    except Exception as exc:   # noqa: BLE001 - heat is advisory; selection runs on without it
        print(f'heat: skipped ({type(exc).__name__}: {exc})', flush=True)
        return {}
    out = {}
    for account, pool in pools.items():
        if (reuse or {}).get(account):
            continue
        pools[account], info = heat.promote(
            pool, group_text, signals, already_led=account in led,
            ok=lambda g, a=account: prescreen.prescreen(a, g)['ok'] and timely(g, ref))
        if info:
            out[account] = (tuple(demo._key(pools[account][0])), info)
    return out


def drafting_day(now=None):
    """The Beijing calendar date a run at `now` drafts for (23:13 London on Oct 7 -> 2026-10-08)."""
    return (now or datetime.now(timezone.utc)).astimezone(BJT).date()


def selection_ref(day, now=None):
    """As-of time for selection. 08:00 Beijing on `day` for a backfill of an older day; a run on the day itself (any
    hour) or in the 24h before its 08:00 sees material up to `now` - never a future reference that would shift the
    freshness date or the 30h timely window past what has been published."""
    now = now or datetime.now(timezone.utc)
    ref = datetime.combine(day, datetime.min.time(), BJT).replace(hour=8).astimezone(timezone.utc)
    if now.astimezone(BJT).date() == day or ref - timedelta(hours=24) <= now < ref:
        return now.astimezone(timezone.utc)
    return ref


def select(accounts, universes, day, per_account, done=None, cap=MAX_PER_ACCOUNT, seed_events=(), reuse=None,
           rewrites=None, now=None):
    store = ContentStore()
    ref = selection_ref(day, now)
    pools = {a['id']: candidates(store, a['id'], a['retrieval_beats'], universes[a['id']].get('angle_lead') or {}, ref,
                                 x_handles=[x['handle'] for x in universes[a['id']].get('x_sources') or [] if x.get('enabled', True)],
                                 account_cfg=a, reuse=(reuse or {}).get(a['id']))
             for a in accounts}
    heat_keys = apply_heat(pools, day, ref, reuse)
    order = sorted(pools, key=lambda a: len(pools[a]))     # scarce accounts pick first in every round
    event_takers = {}            # event key (source key / hook) -> [(account, angle, lang)]
    for e, acc, ang, lg in seed_events:
        event_takers.setdefault(e, []).append((acc, ang, lg))
    plan = {a: [] for a in pools}
    done = done or {}
    for _round in range(per_account):
        for account in order:
            if len(plan[account]) + done.get(account, 0) >= cap:
                continue
            lang = next(x['lang'] for x in accounts if x['id'] == account)
            lead = universes[account].get('angle_lead') or universes[account].get('angle_mix') or {}
            mine = {tuple(p['source_key']) for p in plan[account]}
            pick = None
            for g in pools[account]:
                skey = demo._key(g[0])
                if skey in mine:
                    continue
                events = ({('src',) + tuple(skey)} | {('hook', h) for h in group_hooks(g)}
                          | ({('srcid', g[0]['source']['id'])} if g[0]['source'].get('id') else set())
                          | ({title_event(g[0]['source'].get('title'))} - {None}))
                takers = [t for e in events for t in event_takers.get(e, []) if t[2] == lang]
                if len({t[0] for t in takers}) >= MAX_ACCOUNTS_PER_EVENT or any(t[0] == account for t in takers):
                    continue
                angle, why = angles.assign(lead, group_text(g), taken={t[1] for t in takers})
                if takers and (why == 'shared' or angle in {t[1] for t in takers}):
                    continue
                pick = (g, events, angle, why, sorted({t[0] for t in takers}))
                break
            if pick is None:
                continue
            g, events, angle, why, shared_with = pick
            for e in events:
                event_takers.setdefault(e, []).append((account, angle, lang))
            src = g[0]['source']
            plan[account].append({
                'source_key': list(demo._key(g[0])), 'source_id': src.get('id'), 'title': src.get('title'),
                'publisher': src.get('publisher') or src.get('author_name'), 'published_at': src.get('published_at'),
                'url': src.get('url'), 'source_lang': source_lang(g), 'account_lang': lang,
                'same_language': source_lang(g) == lang, 'unit_ids': [r['unit_id'] for r in g],
                'in_shelf': demo.in_shelf(g, ref.date().isoformat()), 'timely': timely(g, ref),
                'hooks': sorted(group_hooks(g)), 'angle': angle, 'angle_why': why, 'shared_event_with': shared_with,
                'numbers': sum(len(r['unit'].get('numbers') or []) for r in g)})
            if account in heat_keys and heat_keys[account][0] == tuple(demo._key(g[0])):
                plan[account][-1].update(heat_led=True, heat=heat_keys.pop(account)[1])
            target = next((v for k in (src.get('id'), src.get('title'))
                           for v in [((rewrites or {}).get(account) or {}).get(k)] if k and v), None)
            if target:
                plan[account][-1].update(rewrite_of=target['draft_id'], editor_note=target['note'])
    # post type + length (habit card, rotation inside the day) + suggested post time (habit card hours)
    for account, picks in plan.items():
        persona = registry.persona_for_account(account)
        card = ph.load_card(persona)
        recent = list(anti_repeat.load_recent(account))
        times = []
        for p in picks:
            c = copy.deepcopy(card)
            if p['numbers'] < 2:
                c['post_type_mix'] = {k: v for k, v in c['post_type_mix'].items() if k not in ('chart_caption', 'list_dump')}
            fmt = ph.choose_format(persona, recent=recent, seed=f'{day}|{account}|{p["source_id"]}', card=c)
            recent.append({'post_format': fmt['type'], 'text': ''})
            t = ph.sample_post_time(card, day, seed=f'{account}|{p["source_id"]}', taken=times, min_gap_min=90)
            times.append(t)
            p['post_format'] = {k: fmt[k] for k in ('type', 'length', 'thread_parts', 'length_target', 'shapes')}
            p['suggested_post_time_london'] = t.isoformat()
    return plan, order


# ---------------------------------------------------------------- client

class DraftClient:
    """Per-draft stage caps over the shared Gemini client; refuses non-Gemini responses."""

    def __init__(self, inner, log):
        self.inner, self.log = inner, log
        self.stage_models = inner.stage_models
        self.prompt_context = getattr(inner, 'prompt_context', None)
        self.left = dict(STAGE_CALLS)
        self.hard_repair_left = HARD_REPAIR_CALLS
        self.last_error = ''

    def _hard_repair(self, stage, messages, max_tokens):
        if self.hard_repair_left <= 0:
            self.log.append('compose: hard_repair call not run (per-draft cap)')
            raise budget.BudgetExceeded('per-draft cap: hard_repair call not run')
        self.hard_repair_left -= 1
        try:
            r = self.inner(stage, messages, max_tokens)
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: {exc}'[:400]
            raise
        if r.get('model_fallback') or not str(r.get('response_model') or '').startswith('gemini-'):
            raise RuntimeError(f'non-Gemini response {r.get("response_model")}')
        return r

    @property
    def paths(self):
        return [c['path'] for c in self.inner.calls]

    def __call__(self, stage, messages, max_tokens):
        if stage not in self.left:
            raise RuntimeError(f'stage {stage} is not part of daily compose')
        if stage == 'compose' and '[hard_repair]' in json.dumps(messages[-1:], ensure_ascii=False, default=str):
            return self._hard_repair(stage, messages, max_tokens)
        if self.left[stage] <= 0:
            if QUOTA_RX.search(self.last_error):   # the cap was used up by quota failures: report the quota
                raise RuntimeError(self.last_error)
            self.log.append(f'{stage}: extra call not run (per-draft cap)')
            raise budget.BudgetExceeded(f'per-draft cap: extra {stage} call not run')
        self.left[stage] -= 1
        try:
            r = self.inner(stage, messages, max_tokens)
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: {exc}'[:400]
            raise
        if r.get('model_fallback') or not str(r.get('response_model') or '').startswith('gemini-'):
            raise RuntimeError(f'non-Gemini response {r.get("response_model")}')
        return r


def make_client(calls_dir):
    import live.erisedai_distillation_client as ec
    os.environ['FD_GEMINI_ONLY'] = '1'
    table = stage_models.from_env(stage_models.load(), os.environ)
    for stage in ('compose', 'stance'):
        route = stage_models.route(table, stage)
        if not route or not stage_models.is_gemini_route(route['base_url']) or stage_models.fallback(table, stage):
            raise SystemExit(f'{stage} must run on Gemini (FD_GEMINI_PROVIDER=relay|official) without fallback')
    config = {'base_url': 'https://api.erisedai.com/v1', 'api_key': os.environ.get('RELAY_API_KEY') or 'unused-gemini-only',
              'configuration_source': 'gemini_only_daily_compose', 'model': ec.DEFAULT_MODEL,
              'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
              'stage_models': table}
    ec.ErisedaiClient(calls_dir, configuration=copy.deepcopy(config))   # fail before any draft if a key is unusable
    # one client per draft: its .calls are that draft's own call records (threads never share them)
    return (lambda: ec.ErisedaiClient(calls_dir, configuration=copy.deepcopy(config))), table


def call_cost(paths):
    total = 0.0
    for p in paths:
        try:
            total += float(json.loads(Path(p).read_text()).get('estimated_cost_usd') or 0)
        except (OSError, ValueError):
            pass
    return round(total, 6)


# ---------------------------------------------------------------- compose

def compose_one(new_client, account, pick, day, store_records, spend, lock):
    log = []
    dc = DraftClient(new_client(), log)
    lang = pick['account_lang']
    group = [store_records[u] for u in pick['unit_ids'] if u in store_records]
    source = dict(group[0]['source']) if group else {}
    post_time = datetime.fromisoformat(pick['suggested_post_time_london'])
    angle = angles.payload(pick['angle'], lang)
    started = time.monotonic()
    try:
        # inside the guard: a span that no rebuilt paragraph contains (StopIteration) sank the whole Oct 7 run
        source, units = evidence_source(group)
        result = compose.compose_source(
            source, account, dc, post_type=demo.judgment_type(account), extracted_units=units,
            exemplar_dir=POSTS, exemplar_tags_dir=TAGS, view_ledger=ViewLedger(account),
            now=post_time.astimezone(timezone.utc), post_format=dict(pick['post_format']), angle=angle,
            editor_note=pick.get('editor_note'))
    except budget.BudgetExceeded as exc:
        result = {'status': 'error', 'error': 'budget: ' + str(exc)[:200]}
    except Exception as exc:   # noqa: BLE001 - one bad packet must not sink the day
        result = {'status': 'error', 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    cost = call_cost(dc.paths)
    with lock:
        spend['usd'] += cost
    result = dict(result, account_id=account, source=source, plan=pick, retry_log=log, spend_usd=cost,
                  call_records=dc.paths, seconds=round(time.monotonic() - started, 1), angle=angle)
    return result


def inbox_row(result, account_cfg, day, run_id):
    pick = result['plan']
    src = result.get('source') or {}
    findings = [{'code': f.get('code'), 'level': f.get('level')} for f in (result.get('post_checks') or [])
                if isinstance(f, dict)]
    arb = result.get('arbitration') or {}
    repair = result.get('hard_repair') or {}
    models = sorted({(r or {}).get('response_model') for r in (result.get('model_responses') or [])
                     if isinstance(r, dict)} - {None})
    return {'id': (result.get('id') or f'err-{run_id[:6]}-{account_cfg["id"]}-{pick["source_id"]}').replace('/', '_')[:80],
            'day': day.isoformat(), 'run_id': run_id, 'account_id': account_cfg['id'], 'no': account_cfg['no'],
            'name': account_cfg['name'], 'beat': account_cfg['beat'], 'lang': account_cfg['lang'],
            # same-language material needs no attribution line (Oct 7 rule): the body is the post; cross-language
            # drafts keep the compose credit frame. The frame is kept on the row for the reviewer either way.
            'text': (result.get('body') if pick.get('same_language') else result.get('text')) or '',
            'body': result.get('body') or '', 'attribution_frame': result.get('attribution_frame'),
            'attribution_line': 'omitted (same-language source)' if pick.get('same_language') else 'kept',
            'post_type': result.get('post_type'), 'post_format': pick['post_format'],
            'suggested_post_time_london': pick['suggested_post_time_london'], 'angle': result.get('angle'),
            'angle_why': pick['angle_why'], 'shared_event_with': pick['shared_event_with'],
            **({'rewrite_of': pick['rewrite_of']} if pick.get('rewrite_of') else {}),
            **({'heat_led': True, 'heat': pick.get('heat')} if pick.get('heat_led') else {}),
            'draft_status': result.get('draft_status') or ('blocked' if result.get('error') else None),
            'status': result.get('status'), 'error': result.get('error'), 'why': result.get('why'),
            # fix26: a HARD finding left after the one targeted rewrite (needs_review) is a HOLD, never ready
            'held': bool(arb.get('status') == 'HOLD' or result.get('status') == 'error' or not result.get('text')
                         or result.get('draft_status') == 'needs_review'),
            # Sirius item 4: hard after the one targeted rewrite = HOLD; a rewrite the model / API never returned is a
            # model_error hold (retry path), not a content verdict
            'hold_reason': ('arbitration' if arb.get('status') == 'HOLD' else
                            ('model_error: ' if repair.get('result') == 'rewrite_error' else 'hard: ')
                            + ','.join(sorted({f['code'] for f in findings if f.get('level') == 'hard'}))
                            if result.get('draft_status') == 'needs_review' else None),
            **({'hard_repair': {k: repair.get(k) for k in ('result', 'kept', 'error')}
                               | {'first_codes': sorted({f['code'] for f in repair.get('first_findings') or []}),
                                  'retry_codes': sorted({f['code'] for f in repair.get('retry_findings') or []})}}
               if repair else {}),
            'arbitration': arb, 'findings': findings,
            'stance': {k: (result.get('stance') or {}).get(k) for k in ('decision', 'account_view', 'subject', 'direction')},
            'source': {'id': src.get('id'), 'source_id': src.get('source_id'), 'publisher': pick.get('publisher'),
                       'title': pick.get('title'), 'url': pick.get('url'), 'published_at': pick.get('published_at'),
                       'lang': pick.get('source_lang'), 'same_language': pick.get('same_language')},
            'models': models, 'spend_usd': result.get('spend_usd'), 'publishable': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--day', type=date.fromisoformat, default=None,
                    help='drafting day (default: Beijing calendar date of --now / the current time)')
    ap.add_argument('--now', type=lambda s: datetime.fromisoformat(s.replace('Z', '+00:00')), default=None,
                    help='simulated clock for the day default and selection reference (ISO with offset; '
                         'use with --select-only to check a schedule without model calls)')
    ap.add_argument('--accounts')
    ap.add_argument('--per-account', type=int, default=2)
    ap.add_argument('--budget-usd', type=float, default=float(os.environ.get('FD_DAILY_COMPOSE_BUDGET_USD', '4.0')))
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--select-only', action='store_true', help='selection + plan only, no model calls')
    ap.add_argument('--fill', action='store_true',
                    help='top each account up to --per-account READY drafts for the day (held / superseded drafts do '
                         'not count; sources of drafts an audit superseded for a rewrite may be reused)')
    ap.add_argument('--rewrite-notes', type=Path,
                    help='--fill: JSON {draft_id: editor note}; those held drafts are rewritten from the same source '
                         'with the note (audit-superseded rewrite drafts use their audit reason by default)')
    ap.add_argument('--force', action='store_true', help='run even when FD_DAILY_COMPOSE is not 1')
    args = ap.parse_args()
    if args.now and args.now.tzinfo is None:
        ap.error('--now needs a UTC offset, e.g. 2026-10-07T23:13+01:00')
    args.day = args.day or drafting_day(args.now)
    if os.environ.get('FD_DAILY_COMPOSE') != '1' and not args.force and not args.select_only:
        print('FD_DAILY_COMPOSE is not 1: daily compose is off; nothing done')
        return 0
    per_account = max(1, min(MAX_PER_ACCOUNT, args.per_account))
    accounts = load_json(CONFIG)['accounts']
    if args.accounts:
        wanted = set(args.accounts.split(','))
        accounts = [a for a in accounts if a['id'] in wanted]
    if not UNIVERSES.exists():
        raise SystemExit(f'{UNIVERSES} missing: run scripts/persona_factory.py first')
    universes = load_json(UNIVERSES)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    out = RUNS / args.day.isoformat() / run_id
    if args.fill:
        done = drafted_today(args.day, ready_only=True)
        rewrites = rewrite_targets(args.day, load_json(args.rewrite_notes) if args.rewrite_notes else None)
        plan, order = select(accounts, universes, args.day, per_account, done=done, cap=per_account,
                             seed_events=ready_events(args.day, load_json(CONFIG)['accounts']),
                             reuse={a: set(m) for a, m in rewrites.items()}, rewrites=rewrites, now=args.now)
    else:
        done = drafted_today(args.day)
        plan, order = select(accounts, universes, args.day, per_account, done=done, now=args.now)
    write_json(out / 'plan.json', {'day': args.day.isoformat(), 'day_basis': 'Asia/Shanghai calendar date',
                                   'selection_ref': selection_ref(args.day, args.now).isoformat(), 'pick_order': order, 'per_account': per_account,
                                   'fill': args.fill, 'drafted_earlier_today': done,
                                   'accounts': plan})
    for a in accounts:
        print(a['id'], [f"{'REWRITE ' if p.get('rewrite_of') else ''}{p['suggested_post_time_london'][11:16]} {p['post_format']['type']} {p['angle']} "
                        f"{p['source_lang']}{'=' if p['same_language'] else '>'}{a['lang']} {str(p['title'])[:40]}"
                        for p in plan[a['id']]], flush=True)
    if args.select_only:
        return 0
    client, table = make_client(out / 'calls')
    store = ContentStore()
    records = {}
    for a in accounts:
        for beat in a['retrieval_beats']:
            for r in units_for_persona(store, beat, max_age_days=MAX_AGE_DAYS + 2):
                records.setdefault(r['unit_id'], r)
    jobs = [(a, p) for i in range(per_account) for a in accounts if i < len(plan[a['id']]) for p in [plan[a['id']][i]]]
    spend, lock = {'usd': 0.0}, threading.Lock()
    est = EST_PER_DRAFT_PRO if 'pro' in stage_models.for_stage(table, 'compose')['model'] else EST_PER_DRAFT
    results, skipped = [], []
    by_id = {a['id']: a for a in accounts}

    quota = {}

    def guarded(job):
        a, p = job
        with lock:
            if quota:   # a daily Gemini quota is exhausted: starting more drafts would only fail
                skipped.append({'account_id': a['id'], 'source_id': p['source_id'], 'reason': quota['reason']})
                return None
            if spend['usd'] + est > args.budget_usd:
                skipped.append({'account_id': a['id'], 'source_id': p['source_id'],
                                'reason': f'run budget: ${spend["usd"]:.3f} spent of ${args.budget_usd}'})
                return None
        r = compose_one(client, a['id'], p, args.day, records, spend, lock)
        if QUOTA_RX.search(str(r.get('error') or '')):
            with lock:
                quota.setdefault('reason', 'Gemini daily quota exhausted: ' + str(r['error'])[:160])
        print(f"[{a['id']}] {p['angle']} {r.get('draft_status')} ${r['spend_usd']:.4f} {r['seconds']}s "
              f"err={r.get('error')} | {(r.get('body') or '')[:90]!r}", flush=True)
        return r

    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for r in pool.map(guarded, jobs):
            if r is not None:
                results.append(r)
    # cross-account check on the whole day: shape / skeleton findings + claim arbitration (soft: losers HOLD)
    from live import compose_shapes
    ok = [r for r in results if r.get('status') != 'error' and r.get('text')]
    compose_shapes.batch_findings(ok)
    arbitrated = {id(r): r for r in compose.arbitrate_batch(ok)} if ok else {}
    final = []
    for r in results:
        match = next((x for x in arbitrated.values() if x.get('id') and x.get('id') == r.get('id')), None)
        final.append(match or r)
    rows = []
    earlier = compose_inbox.rows(args.day.isoformat())
    replies = {}
    for old in earlier:
        if old.get('post_mode') == 'reply' and not old.get('superseded'):
            replies[old['account_id']] = replies.get(old['account_id'], 0) + 1
    for r in final:
        row = inbox_row(r, by_id[r['account_id']], args.day, run_id)
        if row['text'] and os.environ.get('FD_DRAFT_MEDIA', '1') != '0':
            from live import draft_media
            draft_media.annotate(row, by_id[r['account_id']], charts_on=not row['held'],
                                 replies_given=replies.get(row['account_id'], 0),
                                 own_handles=[a.get('handle') for a in accounts])
            replies[row['account_id']] = replies.get(row['account_id'], 0) + (row.get('post_mode') == 'reply')
        if row['text']:   # only real drafts enter the review inbox; failures stay in the run summary
            compose_inbox.add(row)
            supersede_previous(row, earlier)
        rows.append(row)
        write_json(out / 'drafts' / f"{row['id']}.json", r)
    counts = {a['id']: {'drafts': sum(1 for x in rows if x['account_id'] == a['id'] and x['text']),
                        'held': sum(1 for x in rows if x['account_id'] == a['id'] and x['held']),
                        'errors': sum(1 for x in rows if x['account_id'] == a['id'] and x['error'])} for a in accounts}
    summary = {'day': args.day.isoformat(), 'run_id': run_id, 'accounts': len(accounts), 'planned': len(jobs),
               'blocked': quota.get('reason'),
               'composed': len(results), 'skipped_budget': skipped, 'drafts_with_text': sum(1 for x in rows if x['text']),
               'held': sum(1 for x in rows if x['held'] and x['text']), 'spend_usd': round(spend['usd'], 4),
               'errors': [{'account_id': x['account_id'], 'source': x['source'].get('title'), 'error': x['error']}
                          for x in rows if x['error']],
               'budget_usd': args.budget_usd, 'models': sorted({m for x in rows for m in x['models']}),
               'compose_model': stage_models.for_stage(table, 'compose')['model'], 'per_account': counts,
               'inbox': str(compose_inbox.root() / args.day.isoformat()), 'publishing_enabled': False}
    write_json(out / 'summary.json', summary)
    from backend.compose_inbox import render
    page = DASHBOARD / f'fd20_review_{args.day.isoformat()}.html'
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render(compose_inbox.rows(args.day.isoformat()), args.day.isoformat(), summary=summary))
    print(json.dumps({k: v for k, v in summary.items() if k != 'per_account'}, ensure_ascii=False), flush=True)
    print('review page', page, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
