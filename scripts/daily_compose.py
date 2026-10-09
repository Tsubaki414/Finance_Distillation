#!/usr/bin/env python3
"""Daily auto-compose for the 20 main accounts -> human review inbox (Oct 7, fd20). Never publishes.

Cron-able: does nothing unless FD_DAILY_COMPOSE=1 (or --force). Chain per day:
  units already ingested (scripts/daily_ingest.py)  ->  route: each account's retrieval beats
  (live/fd20_accounts.json; same- and cross-language material both allowed, no attribution line)  ->
  select up to --per-account packets per account (fresh, unused by that account, angle fit)  ->
  angle per draft (live/angles.py: the account's own donor lenses; one lens per account per event)  ->
  post type / length / suggested post time from the account's habit card (posting_habits.choose_format,
  sample_post_time)  ->  compose_source (stance + compose on Gemini (FD_GEMINI_PROVIDER subrouter|relay|official; subrouter + micuapi fallback when SUBROUTER_API_KEY is set), FD_GEMINI_ONLY=1, no
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
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

import demo_matrix_compose as demo  # noqa: E402
from voice_relay_check import evidence_source  # noqa: E402
from live import (angles, anti_repeat, compose, compose_inbox, editorial_style, fd_accounts, news_hook,  # noqa: E402
                  posting_habits as ph, registry, source_prescreen as prescreen, source_routes, stage_models,
                  topic_div, twins)
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
# one event / 母题 may be taken by at most this many accounts per language per Beijing day (fix26: per language).
# Oct 8 evening: 2 -> 1 (views diagnosis: 13 of 22 published posts were same-news-same-conclusion across accounts);
# FD_EVENT_PER_LANG=2 restores the old cap.
MAX_ACCOUNTS_PER_EVENT = max(1, int(os.environ.get('FD_EVENT_PER_LANG', '1')))
STAGE_CALLS = {'stance': 2, 'compose': 3}   # per draft: stance + 1 repair; first pass + 2 rewrites
# Oct 7 Sirius item 4: the one targeted hard-QA rewrite (compose '[hard_repair]' note) has its own allowance, so
# polish rewrites cannot use it up; 2 = the rewrite + one transport retry inside compose._ask.
HARD_REPAIR_CALLS = 2
EST_PER_DRAFT = 0.12           # reserve kept per draft still to start (flash list prices, conservative)
EST_PER_DRAFT_PRO = 0.30       # same reserve when compose runs on gemini-3.1-pro-preview (4x flash list prices)
# Oct 8: the relay's own balance error ('用户额度不足' / insufficient_user_quota, ProviderQuotaError) and the official
# API's 402 prepayment error also stop new drafts (the relay error let a sample start all 8 drafts into the same wall)
QUOTA_RX = re.compile(r'RESOURCE_EXHAUSTED|PerDay|exceeded your current quota|ProviderQuotaError|额度不足|'
                      r'insufficient_user_quota|insufficient[_ ]quota|prepayment credits', re.I)
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


def packet_entities(group):
    """Named entities of a packet for the cross-language twin rule (live/twins.py)."""
    try:
        return twins.entities(group[0]['source'].get('title'), group_text(group))
    except Exception:   # noqa: BLE001
        return set()


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


def candidates(store, account, beats, lead, ref, x_handles=None, account_cfg=None, reuse=None, support=None,
               diag=None):
    """x_handles: the account's own X sources. X-post units of other handles are skipped (X sources are
    account-scoped); own X posts rank right after timeliness, then packets on the account's own crypto lanes.
    account_cfg (fd20_accounts.json row): beat gate - a non-crypto account never gets a crypto packet and a crypto
    account never gets a packet without crypto content (Oct 7: Momo 美股札记 wrote GenLayer).
    reuse: source ids / titles / hashes this account may use again (its own drafts superseded for a rewrite); they
    rank first.
    support (live/x_support.Index, FD_X_SUPPORT / FD_X_DATA): an own X post with a view but no fact gets a real
    support fact (same-story public source or the latest price of the ticker its view names) appended to its packet;
    an own X post with only numbered facts enters as a data packet (data_take). Both rank after the balanced own X
    posts."""
    from live.jev_front import LANE_BEATS
    from live.x_daily import x_handle
    x_handles = {h.lower() for h in x_handles or ()}
    lane = {b for b in beats if b in LANE_BEATS}   # the account's own lanes (meme / perp / defi / prediction / ipo ...)
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
    extra = own_x_packets(gated, support) if support is not None else []
    extra += routed_data_packets(gated, account, account_cfg)
    options = demo.ranked_balanced(gated, now=ref.date().isoformat())
    options += demo.ranked_balanced([g for g in extra if demo.balanced(g)], now=ref.date().isoformat())
    options += sorted([g for g in extra if not demo.balanced(g)], key=lambda g: -demo.group_freshness(g, ref.date().isoformat()))
    if os.environ.get('FD_PRECHECK', '1') != '0':
        options = precheck(account, options, diag)
    top = set(angles.top_angles(lead, 4))
    # Delphi digest (inspiration_only): its tickers only break ties toward the same topic; nothing of it is passed on.
    # The newest digest written within 36h (not an exact day match: it is London-dated, the drafting day is Beijing's).
    steer = set(delphi_digest.steer_tickers(delphi_digest.latest(now=ref)['units']))

    def key(g):
        fit = len(top & set(angles.angles_of(group_text(g))))
        src = g[0]['source']
        return (not ({src.get('id'), src.get('title'), src.get('source_hash')} & reuse),
                not prescreen.prescreen(account, g)['ok'], not demo.in_shelf(g, ref.date().isoformat()),
                not timely(g, ref), not x_handle(g[0]['source']), packet_kind(g) != 'balanced',
                bool(lane) and not any(lane & set(r.get('tag_personas') or []) for r in g), bool(demo.group_hook_repeat(g, recent)), demo.group_theme_repeat(g, recent),
                -fit, not steered(g, steer), -demo.group_freshness(g, ref.date().isoformat()))
    return sorted(options, key=key)


def stance_ready(account, group):
    """A judgment packet the stance step can take for this account: a structured, valid view whose horizon fits the
    persona (stance_step rejects the rest before any model call - 'Legacy view lacks structured judgment' /
    'Incompatible persona horizon': 43 not_suitable plans on 10-08, Robinhood alone for 6 accounts)."""
    from voice_relay_check import has_valid_view
    return any(r['unit'].get('kind') == 'view' and has_valid_view(r['unit'])
               and compose._horizon_compatible(r['unit'], account) for r in group if not r.get('support'))


_GATE = {}


def source_gate_ok(account, group):
    """compose_source's front gate (source_display: the source must have a creditable name in the account's
    language), checked at selection. 10-08: a zh 华尔街见闻 flash was planned for investing_philosophy in 7 runs and
    each time came back not_suitable 'no English name for ch142_wscn_global'."""
    from live import attribution_frame, source_display
    src = group[0]['source']
    lang = registry.persona_for_account(account).lang
    key = (src.get('source_id'), src.get('publisher'), lang)
    if key not in _GATE:
        try:
            tier = registry.source_licence_tier(src.get('source_id'))
            if tier is None and engage_candidate(src):
                tier = registry.ENGAGE_TIER   # kept for the engagement plan; dropped below unless it becomes a target
            if tier not in registry.WRITABLE_TIERS:
                # Oct 9: X breadth / engagement posts (source_id x-<status id>) carry a B unit tier but have no
                # source_licence.json entry, so compose_source refused them ('post_type not allowed for licence
                # tier', 10 first picks on 10-09); the account takes its next packet instead.
                _GATE[key] = False
                return False
            publisher = attribution_frame.publisher_name(src.get('source_id'))
            _GATE[key] = bool(source_display.display(src, lang, tier=tier, raw_name=publisher or src.get('publisher'),
                                                     check_licence=False)['ok'])
        except Exception:   # noqa: BLE001 - unknown: let compose decide as before
            _GATE[key] = True
    return _GATE[key]


def engage_candidate(src):
    """A big-account X post (x-<status id>) that FD_ENGAGE may pick as a reply / quote target."""
    from live import engagement
    return engagement.enabled() and bool(registry.ENGAGE_SOURCE.match(str(src.get('source_id') or '')))


def precheck(account, options, diag=None):
    """FD_PRECHECK (default 1): drop packets compose would refuse before any model call (source gate; judgment
    packets without a stance-ready view). diag (dict) gets the drop counts."""
    kept = []
    for g in options:
        if not source_gate_ok(account, g):
            why = 'source_gate'
        elif packet_kind(g) != 'data' and not stance_ready(account, g):
            why = 'no_stance_ready_view'
        else:
            kept.append(g)
            continue
        if diag is not None:
            diag[why] = diag.get(why, 0) + 1
    return kept


def own_x_packets(groups, support):
    """Own-X packets that are not balanced, made usable (live/x_support.py): view-only + a support fact
    (FD_X_SUPPORT), fact-only with numbers as a data packet (FD_X_DATA). Others stay out, as before."""
    from live import x_support
    from live.x_daily import x_handle
    from voice_relay_check import has_valid_view
    out = []
    for g in groups:
        if demo.balanced(g) or not x_handle(g[0]['source']):
            continue
        if x_support.enabled() and x_support.view_only(g, has_valid_view):
            hit = support.support(g)
            if hit:
                out.append(list(g) + hit['records'])
        elif x_support.data_enabled() and x_support.data_only(g, has_valid_view):
            out.append(list(g))
    return out


def routed_data_packets(groups, account, account_cfg):
    """Oct 8 (36 accounts): fact-only packets of a structured source routed to this account (source_registry
    route_accounts: Polymarket odds, DefiLlama stablecoin yields, Nasdaq IPO calendar) enter as data packets
    (data_take), like own X fact-only posts (FD_X_DATA). Only for lane_first accounts; FD_LANE_DATA=0 turns it off."""
    from live import x_support
    from live.x_daily import x_handle
    from voice_relay_check import has_valid_view
    if not (account_cfg or {}).get('lane_first') or os.environ.get('FD_LANE_DATA', '1') == '0':
        return []
    out = []
    for g in groups:
        src = g[0]['source']
        r = source_routes.route(src.get('source_id'))
        if (r and account in r['accounts'] and not x_handle(src) and not demo.balanced(g)
                and x_support.data_only(g, has_valid_view)):
            out.append(list(g))
    return out


def packet_kind(group):
    """'balanced' (own view + fact), 'supported' (own view + an attached support fact), 'data' (no grounded view,
    money / percent facts) or 'other'."""
    from live import x_support
    from voice_relay_check import has_valid_view
    if any(x_support.is_support(r) for r in group):
        return 'supported'
    if demo.balanced(group):
        return 'balanced'
    return 'data' if x_support.data_only(group, has_valid_view) else 'other'


def support_of(group):
    """The support attached to a packet ({'kind', 'link', 'source', 'records'}) or None."""
    recs = [r for r in group if r.get('support')]
    if not recs:
        return None
    first = recs[0]['support']
    return {'version': 'x-support-v1', 'kind': first['kind'], 'link': first['link'], 'source': first['source'],
            'records': recs}


def x_support_summary(sup):
    from live import x_support
    return x_support.summary(sup)


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
        if (r.get('hotspot') or {}).get('motif_id'):   # a 母题 taken earlier today counts against the cap too
            events.add(('motif', r['hotspot']['motif_id']))
        try:
            events |= {('hook', h) for h in news_hook.hooks(' '.join([str(src.get('title') or ''), r.get('body') or '']))}
        except Exception:   # noqa: BLE001
            pass
        out += [(e, r['account_id'], angle, lang.get(r['account_id'])) for e in events]
        if twins.twin_of(r['account_id']):   # twin rule: what this account wrote about today (names, not keys)
            out += [(('ent', x), r['account_id'], angle, lang.get(r['account_id']))
                    for x in twins.entities(src.get('title'), r.get('body') or r.get('text'))]
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


def apply_heat(pools, day, ref, reuse=None, skip=()):
    """Public heat (live/heat.py, FD_HEAT=1 default): move the hottest prescreen-ok, timely candidate of each account's
    own pool to the front. Never adds a candidate; skipped for an account that already has a heat-led draft today,
    has rewrite targets to reuse, or (FD_HOTSPOT) has a hotspot WRITE today (`skip`: its heat is in the 母题 score).
    Returns {account: (source key, heat info)} for the promoted candidates."""
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
        if (reuse or {}).get(account) or account in skip:
            continue
        pools[account], info = heat.promote(
            pool, group_text, signals, already_led=account in led,
            ok=lambda g, a=account: prescreen.prescreen(a, g)['ok'] and timely(g, ref))
        if info:
            out[account] = (tuple(demo._key(pools[account][0])), info)
    return out


def hotspot_plan(store, pools, accounts, universes, day, ref, reuse=None, allow_model=False):
    """FD_HOTSPOT (default 1): the day's 母题 pool + per-account WRITE / HOLD / IGNORE (live/hotspot.py). Accounts
    with rewrite targets (--fill) or a hotspot draft already in today's inbox get no new hotspot. allow_model: the one
    flash merge call of the day may run (never in --select-only; a cached merge is reused either way). Never fatal."""
    from live import feedback, hotspot
    if not hotspot.enabled():
        return None
    try:
        rows = compose_inbox.rows(day.isoformat())
        led = hotspot.hotspot_led(rows) | {a for a, m in (reuse or {}).items() if m}
        lang = {a['id']: a['lang'] for a in accounts}
        seed = {}
        for r in rows:
            mid = (r.get('hotspot') or {}).get('motif_id')
            if mid and not r.get('superseded') and not r.get('held'):
                seed.setdefault(mid, []).append((r['account_id'], lang.get(r['account_id'])))
        factory = (lambda: hotspot.merge_client(RUNS / day.isoformat() / 'hotspot_calls')) if allow_model else None
        return hotspot.plan_day(store, pools, accounts, universes, day.isoformat(), ref, text_of=group_text,
                                key_of=lambda g: demo._key(g[0]), promo=X_PROMO_OPENER, led=led,
                                ok=lambda a, g: prescreen.prescreen(a, g)['ok'] and timely(g, ref),
                                merge_client_factory=factory, priors=feedback.load(), seed_takers=seed)
    except Exception as exc:   # noqa: BLE001 - hotspots are advisory; selection runs on without them
        print(f'hotspot: skipped ({type(exc).__name__}: {exc})', flush=True)
        return None


def angle_boost(hot, account, lang, group):
    """FD_HOTSPOT soft angle priors for one candidate: viral structure priors (live/viral_priors.json) x the
    account's review approve rate by angle (live/feedback.py). None when hotspots are off."""
    if hot is None:
        return None
    from live import feedback, viral_priors
    text = group_text(group)
    boost = viral_priors.angle_boost(lang, text, n_numbers=sum(len(r['unit'].get('numbers') or []) for r in group))
    priors = hot.meta.get('_feedback')
    if priors is None:
        priors = hot.meta['_feedback'] = feedback.load()
    for a in angles.ANGLES:
        m = feedback.angle_multiplier(priors, account, a)
        if m != 1.0:
            boost[a] = round(boost.get(a, 1.0) * m, 4)
    return boost or None


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


def support_index(store, ref):
    """live/x_support.Index for own-X view-only packets (None when FD_X_SUPPORT=0 and FD_X_DATA=0). Never fatal."""
    from live import x_support
    if not (x_support.enabled() or x_support.data_enabled()):
        return None
    try:
        return x_support.Index(store, ref, group_text)
    except Exception as exc:   # noqa: BLE001 - support is additive; selection runs on without it
        print(f'x_support: skipped ({type(exc).__name__}: {exc})', flush=True)
        return None


def select(accounts, universes, day, per_account, done=None, cap=MAX_PER_ACCOUNT, seed_events=(), reuse=None,
           rewrites=None, now=None, allow_model=False, info=None, skip_sources=None):
    """info: optional dict, filled with the FD_HOTSPOT day summary ('hotspot') for plan.json.
    skip_sources: {account: source ids / titles / hashes} this account already tried today and must not retry."""
    store = ContentStore()
    ref = selection_ref(day, now)
    x_of = {a['id']: [x['handle'] for x in universes[a['id']].get('x_sources') or [] if x.get('enabled', True)]
            for a in accounts}
    from live import x_breadth
    if x_breadth.enabled():   # Oct 8: Sirius-list breadth sources mapped to this account (live/x_breadth.json)
        for row in x_breadth.subscriptions():
            for aid in row['accounts']:
                if aid in x_of and row['handle'] not in x_of[aid]:
                    x_of[aid].append(row['handle'])
    from live import engagement
    if engagement.fetch_enabled():   # Oct 8 (live/engagement.py): big-account ENGAGE targets mapped to this account
        try:
            for row in engagement.subscriptions(fd_accounts.rows(CONFIG)):
                for aid in row['accounts']:
                    if aid in x_of and row['handle'] not in x_of[aid]:
                        x_of[aid].append(row['handle'])
        except Exception as exc:   # noqa: BLE001 - targets are additive
            print(f'engagement targets skipped ({type(exc).__name__}: {exc})', flush=True)
    support = support_index(store, ref)
    diag = {a['id']: {} for a in accounts}
    pools = {a['id']: candidates(store, a['id'], a['retrieval_beats'], universes[a['id']].get('angle_lead') or {}, ref,
                                 x_handles=x_of[a['id']], account_cfg=a, reuse=(reuse or {}).get(a['id']),
                                 support=support, diag=diag[a['id']])
             for a in accounts}
    if info is not None:
        info['precheck_dropped'] = {a: d for a, d in diag.items() if d}
    if skip_sources:   # --fill: sources this account already tried today (not_suitable / held / error) are not retried
        skipped_tried = {}
        for aid in pools:
            gone = skip_sources.get(aid) or set()
            kept = [g for g in pools[aid] if not ({g[0]['source'].get('id'), g[0]['source'].get('title'),
                                                   g[0]['source'].get('source_hash')} & gone)]
            skipped_tried[aid] = len(pools[aid]) - len(kept)
            pools[aid] = kept
        if info is not None:
            info['skipped_tried'] = skipped_tried
    lane_gate(pools, accounts, x_of, info)   # Oct 8 evening: niche accounts take on-lane packets only (FD_LANE_FIT)
    if info is not None:
        info['pool_sizes'] = {aid: len(p) for aid, p in pools.items()}
    div = diversity_prepare(pools, accounts, x_of, day, ref, reuse) if topic_div.enabled() else None
    own_handles = [r.get('handle') for r in fd_accounts.rows(CONFIG) if r.get('handle')]
    if div is not None:   # Oct 8 evening: cold-start quote targets / chartable packets first among equals
        div['prefs'] = {a['id']: pick_prefs(a['id'], day, ref, own_handles, account_lang=a.get('lang'))
                        for a in accounts}
    hot = hotspot_plan(store, pools, accounts, universes, day, ref, reuse=reuse, allow_model=allow_model)
    if div is not None and hot is not None:
        diversity_gate_hotspot(hot, div)
    heat_keys = apply_heat(pools, day, ref, reuse, skip=set(hot.assign) if hot else ())
    order = sorted(pools, key=lambda a: len(pools[a]))     # scarce accounts pick first in every round
    event_takers = {}            # event key (source key / hook / 母题) -> [(account, angle, lang)]
    ent_takers = {}              # twin rule: account -> named entities of its picks today (FD_TWIN_RULE)
    for e, acc, ang, lg in seed_events:
        if e[0] == 'ent':
            ent_takers.setdefault(acc, set()).add(e[1])
        else:
            event_takers.setdefault(e, []).append((acc, ang, lg))
    plan = {a: [] for a in pools}
    done = done or {}
    # Oct 9 (Fiona, perf review): slot rule - per account and day 1 standalone + 1 engagement (reply / quote on an
    # x-<id> target). Earlier ready drafts of the day count; FD_ENGAGE_ONLY fills take engagement picks only.
    slot_rule = engagement.slot_rule()
    slots_done = day_slots(day) if slot_rule else {}
    engage_only_run = os.environ.get('FD_ENGAGE_ONLY') == '1'

    # Oct 9 night (slot-2 fill rate): on 10-09 25-29 of 36 engagement picks were x-<id> posts that failed the target
    # scoring (too_old / low_engagement) and still took the account's engagement slot, so a valid target in the same
    # pool never got picked. An engagement pick must now be a live target at the account's earliest slot, and a target
    # post / (account, author) pair already used today (earlier inbox rows or this plan) is skipped (one of our
    # accounts per post). FD_ENGAGE_PICK_GATE=0: the old behaviour.
    pick_gate = slot_rule and os.environ.get('FD_ENGAGE_PICK_GATE', '1') != '0'
    eng_state, eng_taken, eng_memo = None, {}, {}
    day_s = day.isoformat() if hasattr(day, 'isoformat') else str(day)
    if pick_gate:
        try:
            earlier_rows = [r for r in compose_inbox.rows(day_s) if not r.get('superseded')]
        except Exception:   # noqa: BLE001
            earlier_rows = []
        eng_state = engagement.DayState.from_rows(earlier_rows)
        for r in earlier_rows:
            if r.get('suggested_post_time_london'):
                eng_taken.setdefault(r.get('account_id'), []).append(r['suggested_post_time_london'])
    eng_ref = max([x for x in (ref, now) if x is not None])
    lang_of = {a['id']: a.get('lang') for a in accounts}

    engage_diag = {a['id']: Counter() for a in accounts}   # Oct 9 night: why an account got no engagement pick

    def engage_assess(account, g):
        src = g[0]['source']
        k = (account, src.get('id'))
        if k not in eng_memo:
            slot = engagement.next_slot(day_s, eng_ref, eng_taken.get(account, ()))
            eng_memo[k] = (engagement.assess(src, slot, account_lang=lang_of.get(account), own_handles=own_handles)
                           if slot else {'quote_ok': False, 'reject': 'no_slot', 'score': 0.0})
        return eng_memo[k]

    def engage_live(account, g):
        a = engage_assess(account, g)
        if not a.get('quote_ok'):
            return False
        pid, handle = str(a.get('post_id')), str(a.get('handle') or '').lower()
        if pid in eng_state.targets or (account, handle) in eng_state.authors:
            return False
        owner = engage_reserved().get(pid)
        return owner is None or owner == account or any(slot_kind(p.get('source_id')) == 'engage' for p in plan[owner])

    eng_reserve = {}

    def engage_reserved():
        """Oct 9 night: 10/36 accounts lost their only live target to an account that had others. Reserve targets by
        max bipartite matching (scarce accounts first), so a shared target goes to whoever has no alternative."""
        if 'm' in eng_reserve:
            return eng_reserve['m']
        eng_reserve['m'] = {}
        if os.environ.get('FD_ENGAGE_MATCH', '1') == '0':
            return eng_reserve['m']
        opts = {}
        for a in plan:
            if (slots_done.get(a) or {}).get('engage', 0):
                continue
            ids = []
            for g in pools.get(a) or ():
                if slot_kind(g[0]['source'].get('id')) != 'engage':
                    continue
                ea = engage_assess(a, g)
                pid, h = str(ea.get('post_id')), str(ea.get('handle') or '').lower()
                if ea.get('quote_ok') and pid not in eng_state.targets and (a, h) not in eng_state.authors:
                    ids.append((-float(ea.get('score') or 0), pid))
            if ids:
                opts[a] = [pid for _, pid in sorted(ids)]
        match = {}

        def augment(a, seen):
            for pid in opts[a]:
                if pid in seen:
                    continue
                seen.add(pid)
                if pid not in match or augment(match[pid], seen):
                    match[pid] = a
                    return True
            return False
        for a in sorted(opts, key=lambda x: (len(opts[x]), x)):
            augment(a, set())
        eng_reserve['m'] = match
        return match

    def slot_ok(account, g):
        if not slot_rule:
            return True
        kind = slot_kind(g[0]['source'].get('id'))
        if kind == 'standalone' and engage_only_run:
            return False
        have = (slots_done.get(account) or {}).get(kind, 0) + sum(
            1 for p in plan[account] if slot_kind(p.get('source_id')) == kind)
        if have >= 1:
            return False
        return kind != 'engage' or not pick_gate or engage_live(account, g)

    def engage_first(account, groups):
        """With the gate on: the account's live engagement targets in score order (standalone order unchanged)."""
        if not pick_gate:
            return groups
        mine = {pid for pid, a in engage_reserved().items() if a == account}
        eng = sorted((g for g in groups if slot_kind(g[0]['source'].get('id')) == 'engage'),
                     key=lambda g: (str(engage_assess(account, g).get('post_id')) not in mine,
                                    -float(engage_assess(account, g).get('score') or 0)))
        it = iter(eng)
        return [next(it) if slot_kind(g[0]['source'].get('id')) == 'engage' else g for g in groups]

    def heat_of(g):
        mid = hot.motif_of(demo._key(g[0])) if hot is not None else None
        try:
            return float(hot.by_id[mid]['heat']['score']) if mid else None
        except (KeyError, TypeError, ValueError):
            return None

    def zh_hot_first(account, lang, groups):
        """Rule 3 (Oct 9): a zh account's standalone post goes to a hot 母题 (heat >= ZH_HOT_MIN) first."""
        if not zh_hot_rule(lang) or hot is None:
            return groups
        return sorted(groups, key=lambda g: not ((heat_of(g) or 0) >= ZH_HOT_MIN))

    def hot_on_lane(account):
        test = lane_test(next(x for x in accounts if x['id'] == account), x_of[account])
        return any((heat_of(g) or 0) >= ZH_HOT_MIN and slot_kind(g[0]['source'].get('id')) == 'standalone'
                   and (test is None or test(g)) for g in pools[account])

    def try_pick(account, lang, lead, groups):
        mine = {tuple(p['source_key']) for p in plan[account]}
        for g in groups:
            skey = demo._key(g[0])
            if skey in mine:
                continue
            events = ({('src',) + tuple(skey)} | {('hook', h) for h in group_hooks(g)}
                      | ({('srcid', g[0]['source']['id'])} if g[0]['source'].get('id') else set())
                      | ({title_event(g[0]['source'].get('title'))} - {None}))
            if hot is not None and hot.motif_of(skey):   # FD_HOTSPOT: every source of one 母题 is one event
                events.add(('motif', hot.motif_of(skey)))
            ek = slot_kind(g[0]['source'].get('id')) == 'engage'
            if twins.twin_of(account) and twins.clash(account, events, packet_entities(g), event_takers, ent_takers):
                ek and engage_diag[account].update(['twin'])
                continue   # FD_TWIN_RULE: zh/en twins (27/32, 28/33, 29/34, 30/36) never take one event on one day
            takers = [t for e in events for t in event_takers.get(e, []) if t[2] == lang]
            if len({t[0] for t in takers}) >= MAX_ACCOUNTS_PER_EVENT or any(t[0] == account for t in takers):
                ek and engage_diag[account].update(['event_cap'])
                continue
            if div is not None and len({t[0] for e in events for t in event_takers.get(e, [])}) >= topic_div.MAX_TOTAL_PER_EVENT:
                ek and engage_diag[account].update(['topic_div_cap'])
                continue   # FD_TOPIC_DIV: one story at most 3 accounts across both languages (Polygon/TRON had 4)
            # one 母题 = a different lens per account in either language (FD_HOTSPOT); other events: per language
            lenses = {t[1] for t in takers} | {t[1] for e in events if e[0] == 'motif' for t in event_takers.get(e, [])}
            angle, why = angles.assign(lead, group_text(g), taken=lenses, boost=angle_boost(hot, account, lang, g))
            if lenses and (why == 'shared' or angle in lenses):
                ek and engage_diag[account].update(['no_free_lens'])
                continue
            return (g, events, angle, why, sorted({t[0] for t in takers}))
        return None

    # FD_HOTSPOT: WRITE picks go first (one per account, inside its usual per-run slots), so a 母题's per-language
    # slots go to the accounts the decision chose, each with its own lens; a pick that no longer fits (event cap / no
    # free lens / ceiling) is recorded as HOLD. Without hotspots the first round is empty.
    hot_round = [a for a in order if hot is not None and a in hot.assign]
    for _round in [hot_round] + [None] * per_account:
        for account in (order if _round is None else _round):
            if len(plan[account]) + done.get(account, 0) >= cap or len(plan[account]) >= per_account:
                if _round is not None:
                    hot.record(account, hot.assign[account][0], decision='HOLD', reason='daily ceiling already reached')
                continue
            lang = next(x['lang'] for x in accounts if x['id'] == account)
            if _round is not None and slot_rule:
                hg = next((g for g in pools[account] if tuple(demo._key(g[0])) == tuple(hot.assign[account][1])), None)
                if hg is not None and not slot_ok(account, hg):
                    hot.record(account, hot.assign[account][0], decision='HOLD', reason='slot rule: standalone slot taken')
                    continue
                if (hg is not None and zh_hot_rule(lang) and (heat_of(hg) or 0) < ZH_HOT_MIN
                        and hot_on_lane(account)):
                    hot.record(account, hot.assign[account][0], decision='HOLD',
                               reason=f'zh hot-first: a 母题 with heat >= {ZH_HOT_MIN} is on-lane')
                    continue
            lead = universes[account].get('angle_lead') or universes[account].get('angle_mix') or {}
            motif = None
            if _round is None:
                groups = pools[account]
                if div is not None:   # own sources first, a theme not yet used today, a story nobody took yet
                    groups = diversity_order(account, groups, plan[account], event_takers, div)
                groups = zh_hot_first(account, lang, groups)   # stable: lane_first below keeps on-lane first
                groups = lane_first(next(x for x in accounts if x['id'] == account), groups, x_of[account])
                if slot_rule and not engage_diag[account].get('pool_engage'):
                    eg = [g for g in groups if slot_kind(g[0]['source'].get('id')) == 'engage']
                    engage_diag[account]['pool_engage'] = len(eg)
                    if pick_gate:
                        for g in eg:
                            a_ = engage_assess(account, g)
                            engage_diag[account]['live' if a_.get('quote_ok') else 'reject_' + str(a_.get('reject'))] += 1
                groups = engage_first(account, [g for g in groups if slot_ok(account, g)])
                pick = try_pick(account, lang, lead, groups)
            else:
                motif, key = hot.assign[account]
                group = next((g for g in pools[account] if tuple(demo._key(g[0])) == tuple(key)), None)
                pick = try_pick(account, lang, lead, [group] if group else [])
                if pick is None:
                    hot.record(account, motif, decision='HOLD', reason='event cap / no free lens at pick time')
                    continue
                hot.record(account, motif, angle=pick[2])
            if pick is None:
                continue
            g, events, angle, why, shared_with = pick
            if pick_gate and slot_kind(g[0]['source'].get('id')) == 'engage':   # one of our accounts per target post
                ea = engage_assess(account, g)
                eng_state.targets[str(ea.get('post_id'))] = account
                eng_state.authors.add((account, str(ea.get('handle') or '').lower()))
            for e in events:
                event_takers.setdefault(e, []).append((account, angle, lang))
            if twins.twin_of(account):
                ent_takers.setdefault(account, set()).update(packet_entities(g))
            src = g[0]['source']
            sup = support_of(g)
            plan[account].append({
                'source_key': list(demo._key(g[0])), 'source_id': src.get('id'), 'title': src.get('title'),
                'publisher': src.get('publisher') or src.get('author_name'), 'published_at': src.get('published_at'),
                'url': src.get('url'), 'source_lang': source_lang(g), 'account_lang': lang,
                'same_language': source_lang(g) == lang, 'unit_ids': [r['unit_id'] for r in g if not r.get('support')],
                'packet': packet_kind(g),
                **({'post_type': 'data_take'} if packet_kind(g) == 'data' else {}),
                **({'support': x_support_summary(sup), 'support_records': sup['records']} if sup else {}),
                'in_shelf': demo.in_shelf(g, ref.date().isoformat()), 'timely': timely(g, ref),
                **({'x_metrics': src['x_metrics']} if src.get('x_metrics') else {}),
                'hooks': sorted(group_hooks(g)), 'angle': angle, 'angle_why': why, 'shared_event_with': shared_with,
                'numbers': sum(len(r['unit'].get('numbers') or []) for r in g)})
            if div is not None:
                plan[account][-1]['topic_div'] = div['info'](account, g)
            if heat_of(g) is not None:
                plan[account][-1]['motif_heat'] = heat_of(g)
            if account in heat_keys and heat_keys[account][0] == tuple(demo._key(g[0])):
                plan[account][-1].update(heat_led=True, heat=heat_keys.pop(account)[1])
            if motif:
                plan[account][-1].update(hotspot=hot.tag(motif), reality=hotspot_reality(
                    hot, motif, account, ref, x_of[account], allow_model=allow_model))
            target = next((v for k in (src.get('id'), src.get('title'))
                           for v in [((rewrites or {}).get(account) or {}).get(k)] if k and v), None)
            if target:
                plan[account][-1].update(rewrite_of=target['draft_id'], editor_note=target['note'])
    # Oct 8 (live/engagement.py, FD_ENGAGE): cold accounts reply to / quote the best big-account targets among their
    # picks (1 reply + 1 quote, or 2 replies, a day), timed while the target is hot; other picks stay standalone and
    # never quote a target that fails the scoring.
    eng = engagement_plan(plan, accounts, pools, day, ref, now, own_handles, info) if engagement.enabled() else None
    # post type + length (habit card, rotation inside the day) + suggested post time (habit card hours)
    for account, picks in plan.items():
        persona = registry.persona_for_account(account)
        card = ph.load_card(persona)
        recent = list(anti_repeat.load_recent(account))
        times = [d['slot'] for d in ((eng or {}).get(account) or {}).values() if d.get('mode') and d.get('slot')]
        for p in picks:
            c = copy.deepcopy(card)
            if p['numbers'] < 2:
                c['post_type_mix'] = {k: v for k, v in c['post_type_mix'].items() if k not in ('chart_caption', 'list_dump')}
            d = ((eng or {}).get(account) or {}).get(p['source_id']) if eng is not None else None
            force = None
            if eng is not None:
                force = {'quote': 'quote_comment', 'reply': 'one_liner'}.get((d or {}).get('mode'))
                if not force:   # standalone: no quote card on a post that is not a scored target
                    c['post_type_mix'] = {k: v for k, v in c['post_type_mix'].items() if k != 'quote_comment'} \
                        or c['post_type_mix']
                quote = False
            else:
                from live import cold_start
                quote = (cold_start.force_quote(account, day, {'url': p.get('url'), 'published_at': p.get('published_at'),
                                                               'x_metrics': p.get('x_metrics')},
                                                ref, key=p['source_id'], own_handles=own_handles)
                         and 'quote_comment' in (c.get('post_type_mix') or {}))
                # Oct 8 evening: cold-start accounts quote fresh hot X posts more often (COLD_QUOTE_SHARE)
                force = 'quote_comment' if quote else None
            fmt = ph.choose_format(persona, recent=recent, seed=f'{day}|{account}|{p["source_id"]}', card=c,
                                   force_type=force)
            if quote:
                p['cold_start_quote'] = True
            recent.append({'post_format': fmt['type'], 'text': ''})
            if d and d.get('mode') and d.get('slot'):
                t = d['slot'].astimezone(ZoneInfo(ph.TZ))   # engagement: earliest slot while the target is hot
            else:
                t = ph.sample_post_time(card, day, seed=f'{account}|{p["source_id"]}', taken=times, min_gap_min=90)
                times.append(t)
            p['post_format'] = {k: fmt[k] for k in ('type', 'length', 'thread_parts', 'length_target', 'shapes')}
            if d is not None and (d.get('mode') or (d.get('assess') or {}).get('url')):
                from live import engagement as _eng
                p['engagement'] = _eng.pick_record(d)
                if d.get('mode'):
                    p['post_format'].update(engage=d['mode'], engage_author=(d.get('assess') or {}).get('handle'))
                    # Oct 9 night: a reply / quote is short (10-09 #14 quote got a 400-850 'long' band from the habit
                    # card); it sits under / next to the target post, so it never needs a long body.
                    cap_len = ENGAGE_MAX_LEN[d['mode']]['zh' if str(p.get('account_lang')) == 'zh' else 'en']
                    lt = dict(p['post_format'].get('length_target') or {})
                    lt['max'] = min(int(lt.get('max') or cap_len), cap_len)
                    lt['min'] = min(int(lt.get('min') or 0), lt['max'] // 3)
                    p['post_format'].update(length_target=lt, length='short' if d['mode'] == 'reply' else
                                            ('medium' if p['post_format'].get('length') in ('long', 'thread')
                                             else p['post_format'].get('length')), thread_parts=None)
            p['suggested_post_time_london'] = t.isoformat()
    # Oct 9: an x-<status id> post is licensed only as a reply / quote target; a pick of one that did not become an
    # engagement draft is dropped (never a standalone body source). FD_ENGAGE_ONLY=1 (engagement fill): only the
    # reply / quote picks are composed.
    engage_only = os.environ.get('FD_ENGAGE_ONLY') == '1'
    for account in list(plan):
        plan[account] = [p for p in plan[account]
                         if (p.get('post_format') or {}).get('engage') in ('reply', 'quote')
                         or (not engage_only and not registry.ENGAGE_SOURCE.match(str(p.get('source_id') or '')))]
    if info is not None and slot_rule:
        if pick_gate:   # accounts left without an engagement pick: live targets another account took first
            for a in plan:
                if any(slot_kind(p.get('source_id')) == 'engage' for p in plan[a]):
                    engage_diag[a]['picked'] = 1
                    continue
                for g in pools.get(a) or ():
                    if slot_kind(g[0]['source'].get('id')) != 'engage':
                        continue
                    ea = engage_assess(a, g)
                    owner = eng_state.targets.get(str(ea.get('post_id')))
                    if ea.get('quote_ok') and owner and owner != a:
                        engage_diag[a]['lost_to_other_account'] += 1
        info['engage_pick_diag'] = {a: dict(c) for a, c in engage_diag.items()}
    if div is not None and info is not None:
        info['topic_div'] = div['summary']
    if hot is not None:
        hot.meta.pop('_feedback', None)
        hot.save()
        if info is not None:
            info['hotspot'] = hot.summary()
    return plan, order


ZH_HOT_MIN = float(os.environ.get('FD_ZH_HOT_MIN', '2.5'))
ENGAGE_MAX_LEN = {'reply': {'zh': 90, 'en': 220}, 'quote': {'zh': 140, 'en': 320}}   # chars of the body


def zh_hot_rule(lang, env=None):
    """Oct 9 (Fiona, perf review): zh accounts lead with a hot 母题 (heat >= ZH_HOT_MIN) when one is on-lane;
    FD_ZH_HOT_FIRST=0 turns it off. Re-check against the 10-08 metrics on 10-10."""
    return lang == 'zh' and (env if env is not None else os.environ).get('FD_ZH_HOT_FIRST', '1') != '0'


def slot_kind(source_id):
    """'engage' for an x-<status id> post (licensed only as a reply / quote target), else 'standalone'."""
    return 'engage' if registry.ENGAGE_SOURCE.match(str(source_id or '')) else 'standalone'


def row_slot_kind(row):
    """Slot of an inbox row: engagement (reply / quote draft) or standalone (incl. 回看 / 常青)."""
    e = row.get('engagement') or {}
    if (row.get('post_format') or {}).get('engage') in ('reply', 'quote') or e.get('mode') in ('reply', 'quote'):
        return 'engage'
    return 'standalone'


def day_slots(day):
    """{account: {'standalone': n, 'engage': n}} of the day's ready / published inbox rows (slot rule)."""
    out = {}
    try:
        rows = compose_inbox.rows(day.isoformat() if hasattr(day, 'isoformat') else str(day))
    except Exception:   # noqa: BLE001
        rows = []
    for r in rows:
        if r.get('superseded') or r.get('held') or r.get('draft_status') != 'draft_ready' \
                or not (r.get('text') or '').strip():
            continue
        k = out.setdefault(r.get('account_id'), {'standalone': 0, 'engage': 0})
        k[row_slot_kind(r)] += 1
    return out


def lane_first(account_cfg, groups, x_handles):
    """Oct 8 (36 accounts): a narrow-lane account (row lane_first, the 10 new accounts: meme / airdrop / prediction /
    stablecoin yield / IPO / perp DEX) takes packets of its own X sources or its own lanes before general crypto /
    market news; stable, so the earlier order holds inside both halves. FD_LANE_FIRST=0 turns it off."""
    on_lane = lane_test(account_cfg, x_handles)
    if on_lane is None:
        return groups
    return sorted(groups, key=lambda g: not on_lane(g))


def lane_test(account_cfg, x_handles):
    """The lane_first on-lane predicate of a narrow-lane account; None = every packet counts as on-lane."""
    from live.jev_front import LANE_BEATS
    from live.x_daily import x_handle
    if not account_cfg.get('lane_first') or os.environ.get('FD_LANE_FIRST', '1') == '0':
        return None
    lanes = {b for b in account_cfg.get('retrieval_beats') or () if b in LANE_BEATS}
    own = {h.lower() for h in x_handles or ()}

    def on_lane(g):
        h = x_handle(g[0]['source'])
        return bool(h and h.lower() in own) or any(lanes & set(r.get('tag_personas') or []) for r in g)
    return on_lane


def diversity_prepare(pools, accounts, x_of, day, ref, reuse=None):
    """FD_TOPIC_DIV (default 1): donor topic profiles (live/topic_div.py) + per-account source tiers, and the pools
    re-sorted so that, after reuse / prescreen / timeliness, own X sources come first, then donor-adjacent packets,
    then other packets, then shared news that sits in >= 4 accounts' pools. Stable sort: the old order holds inside
    each tier. Returns the context diversity_order / the hotspot gate use."""
    profs = topic_div.profiles([a['id'] for a in accounts], ref, day.isoformat())
    common = topic_div.common_entities(profs)
    shared = {}
    for pool in pools.values():
        for g in pool:
            shared[tuple(demo._key(g[0]))] = shared.get(tuple(demo._key(g[0])), 0) + 1
    from live.x_daily import x_handle
    meta = {}
    for a in accounts:
        aid, own = a['id'], {h.lower() for h in x_of.get(a['id']) or ()}
        crypto_acct = editorial_style.is_crypto_account(a)
        mine = set((reuse or {}).get(aid) or ())
        for g in pools[aid]:
            key = tuple(demo._key(g[0]))
            text = group_text(g)
            handle = x_handle(g[0]['source'])
            adj = topic_div.adjacency(text, profs.get(aid), common)
            themes = topic_div.themes_of(text)
            tier = topic_div.source_tier(bool(handle and handle.lower() in own), shared[key], adj)
            if tier == 0 and not crypto_acct and (themes[0].startswith('c_') or topic_div.CRYPTO_MARK.search(text)):
                tier = 2   # a non-crypto account's own X source posting on crypto is not its own lane ($HYPE)
            meta[(aid, key)] = {'tier': tier, 'theme': themes[0], 'shared_pools': shared[key],
                                'adjacent': adj[0][:5], 'theme_share': round(adj[1], 4),
                                'off_spread': topic_div.off_spread(themes[0], profs.get(aid)),
                                'base': (not ({g[0]['source'].get('id'), g[0]['source'].get('title'),
                                               g[0]['source'].get('source_hash')} & mine),
                                         not prescreen.prescreen(aid, g)['ok'], not timely(g, ref))}
        pools[aid] = sorted(pools[aid], key=lambda g, aid=aid: (*meta[(aid, tuple(demo._key(g[0])))]['base'],
                                                               meta[(aid, tuple(demo._key(g[0])))]['tier']))

    def info(aid, g):
        m = meta.get((aid, tuple(demo._key(g[0])))) or {}
        return {k: m.get(k) for k in ('tier', 'theme', 'shared_pools', 'adjacent', 'theme_share', 'off_spread')}

    tiers = {}
    for (aid, _), m in meta.items():
        tiers.setdefault(aid, Counter())[m['tier']] += 1
    summary = {'version': topic_div.VERSION, 'tiers': {a: dict(sorted(c.items())) for a, c in tiers.items()},
               'donor_profiles': {a: {k: p[k] for k in ('posts', 'posts_per_day', 'distinct_themes', 'stories')}
                                  | {'top_themes': dict(list(p['themes'].items())[:6])} for a, p in profs.items()}}
    return {'meta': meta, 'profiles': profs, 'info': info, 'summary': summary}


def pick_prefs(account, day, ref, own_handles=(), account_lang=None):
    """Soft per-packet preferences (lower sorts first): (cold-start: not a fresh hot X quote target,
    image-heavy donors: no real chart / screenshot possible). live/cold_start.py; both 0 when off.
    Oct 8 (live/engagement.py, FD_ENGAGE): in the engagement window the first key is (0, -score) for a scored
    big-account / velocity target at the account's first slot, (1, 0) for a fresh X post the scoring cannot judge
    (no metrics), (2, 0) otherwise - so the best quote / reply targets reach the picks."""
    from live import cold_start, engagement
    cold = cold_start.is_cold(account, day)
    heavy = cold_start.image_heavy(account)
    eng = engagement.enabled() and (engagement.is_cold(account, day) or engagement.slot_rule())
    slot = (engagement.next_slot(day, ref) or ref) if eng else None

    memo = {}

    def first(src):
        if not eng:
            return bool(cold) and not cold_start.hot_quote_target(src, ref, own_handles)
        a = engagement.assess(src, slot, account_lang=account_lang, own_handles=own_handles)
        if a['quote_ok']:
            return (0, -a['score'])
        return (1, 0.0) if cold and a['reject'] == 'no_metrics' and cold_start.hot_quote_target(src, ref, own_handles) \
            else (2, 0.0)

    def k(g):
        if id(g) not in memo:
            src = g[0]['source']
            memo[id(g)] = (first(src),
                           bool(heavy) and not cold_start.chartable(
                               group_text(g), sum(len(r['unit'].get('numbers') or []) for r in g)))
        return memo[id(g)]
    return k


def engagement_plan(plan, accounts, pools, day, ref, now, own_handles, info=None):
    """live/engagement.plan_day over the day's picks -> {account: {source_id: decision}}; the targets log goes into
    info['engagement'] (run_round writes it to live/store/engagement/<day>.json). Earlier inbox rows of the day count
    against the per-account quota, the one-target-one-account rule and the 30-minute spacing."""
    from live import engagement
    from live.post_mode import x_target
    day_s = day.isoformat() if hasattr(day, 'isoformat') else str(day)
    try:
        earlier = [r for r in compose_inbox.rows(day_s) if not r.get('superseded')]
    except Exception:   # noqa: BLE001
        earlier = []
    state = engagement.DayState.from_rows(earlier)
    taken = {}
    for r in earlier:
        t = r.get('suggested_post_time_london')
        if t and r.get('account_id') in plan:
            taken.setdefault(r['account_id'], []).append(t)
    langs = {a['id']: a.get('lang') for a in accounts}
    cands = {aid: [{'key': p['source_id'], 'on_lane': True,
                    'source': {'url': p.get('url'), 'published_at': p.get('published_at'),
                               'x_metrics': p.get('x_metrics'), 'source_language': p.get('source_lang')}}
                   for p in picks if p.get('source_id')]
             for aid, picks in plan.items()}
    sel_ref = max([x for x in (ref, now) if x is not None])
    decisions, log = engagement.plan_day(cands, day=day_s, ref=sel_ref, state=state, taken=taken,
                                         own_handles=own_handles, langs=langs)
    holders = {}
    for aid, groups in (pools or {}).items():   # accounts whose pool held the target (they passed it over)
        for g in groups:
            t = x_target(g[0]['source'])
            if t:
                holders.setdefault(t[0], set()).add(aid)
    for e in log:
        e['passed_over'] = sorted((set(e.get('passed_over') or ()) | holders.get(e.get('target_url'), set()))
                                  - {e['account']})
    cold = [a for a in cands if engagement.is_cold(a, day_s)]
    summary = {'targets': log, 'cold_accounts': len(cold),
               'accounts_with_engagement': sorted({e['account'] for e in log}),
               'fallback_standalone': sorted(a for a in cold if not any(d.get('mode') for d in decisions[a].values()))}
    if info is not None:
        info['engagement'] = summary
    if log:
        print('engagement targets', json.dumps([(e['account'], e['mode'], e['author'], e['likes_at_selection'],
                                                 e['age_h_at_post']) for e in log], ensure_ascii=False), flush=True)
    return decisions


def lane_gate(pools, accounts, x_of, info=None):
    """FD_LANE_FIT (live/lane_fit.py): a niche account keeps only packets on its own lane (or own X posts that are not
    broad macro / BTC / ETF news). Off-lane rejects are counted per account in info['off_lane_rejects'] (plan.json)
    and printed; fewer on-lane drafts beat off-lane fill."""
    from live import lane_fit
    from live.x_daily import x_handle
    if not lane_fit.enabled():
        return {}
    rejects = {}
    for a in accounts:
        aid = a['id']
        if aid not in pools or not lane_fit.is_niche(a):
            continue
        own = {h.lower() for h in x_of.get(aid) or ()}
        kept, gone = [], []
        for g in pools[aid]:
            h = x_handle(g[0]['source'])
            chk = lane_fit.packet_check(a, group_text(g), own_x=bool(h and h.lower() in own))
            (kept if chk['ok'] else gone).append(g)
        pools[aid] = kept
        if gone:
            rejects[aid] = {'lane': lane_fit.primary_lane(a), 'rejected': len(gone), 'kept': len(kept),
                            'samples': [str(g[0]['source'].get('title') or '')[:80] for g in gone[:5]]}
    if rejects:
        print('lane_fit off-lane rejects', json.dumps({k: (v['rejected'], v['kept']) for k, v in rejects.items()}),
              flush=True)
    if info is not None:
        info['off_lane_rejects'] = rejects
    return rejects


def diversity_order(account, groups, picked, event_takers, div):
    """Pick-time order for one account (FD_TOPIC_DIV): (reuse, prescreen, timely) as before, then own X sources, then a
    theme this account has not used today, then the remaining source tiers, then stories no account took yet, then
    themes inside the donors' spread; the pool order breaks ties. Hard gates and caps are unchanged (try_pick)."""
    meta = div['meta']
    used_themes = {p.get('topic_div', {}).get('theme') for p in picked}
    taken = {e for e, ts in event_takers.items() if any(t[0] != account for t in ts)}

    def k(item):
        i, g = item
        m = meta.get((account, tuple(demo._key(g[0])))) or {'base': (True, True, True), 'tier': 2, 'theme': 'other',
                                                              'off_spread': False}
        src = g[0]['source']
        evs = {('src',) + tuple(demo._key(g[0]))} | ({('srcid', src['id'])} if src.get('id') else set()) \
            | ({title_event(src.get('title'))} - {None})
        return (*m['base'], *prefs(g)[:1], m['tier'] != 0, packet_kind(g) != 'balanced',
                m['theme'] in used_themes and m['theme'] != 'other', m['tier'],
                bool(evs & taken), *prefs(g)[1:], m['off_spread'], i)
    prefs = div.get('prefs', {}).get(account) or (lambda g: (False, False))
    return [g for _, g in sorted(enumerate(groups), key=k)]


def diversity_gate_hotspot(hot, div):
    """FD_TOPIC_DIV: a hotspot WRITE stands only when the 母题 member the account would write from is its own source
    or donor-adjacent (tier 0/1) - shared news alone does not pull an account onto a trend (recorded as HOLD)."""
    for account, (motif, key) in list(hot.assign.items()):
        m = div['meta'].get((account, tuple(key)))
        if m is None or m['tier'] > 1:
            hot.assign.pop(account)
            hot.record(account, motif, decision='HOLD',
                       reason=f"topic_div: member is not an own / donor-adjacent source (tier {m and m['tier']})")


def hotspot_reality(hot, motif, account, ref, x_handles, allow_model=False):
    """Reality payload of one hotspot pick (live/hotspot.reality): latest price + newest member sources (<= 24h);
    the optional twitter241 X pulse (FD_HOTSPOT_X=1, <= 40 calls/day) runs only in a real compose run."""
    from live import hotspot
    pulse = None
    if allow_model and os.environ.get('FD_HOTSPOT_X') == '1':
        pulse = hotspot.x_pulse_factory(hot.day)
    try:
        return hotspot.reality(hot, motif, account, ref, x_handles=x_handles, x_pulse=pulse)
    except Exception as exc:   # noqa: BLE001
        return {'error': f'{type(exc).__name__}: {str(exc)[:160]}'}


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
        if not route or not stage_models.is_gemini_route(route['base_url']) or stage_models.model_fallback(table, stage):
            raise SystemExit(f'{stage} must run on Gemini (FD_GEMINI_PROVIDER=subrouter|relay|official) without a model fallback')
    config = {'base_url': 'https://api.erisedai.com/v1', 'api_key': os.environ.get('RELAY_API_KEY') or 'unused-gemini-only',
              'configuration_source': 'gemini_only_daily_compose', 'model': ec.DEFAULT_MODEL,
              'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
              'stage_models': table}
    ec.ErisedaiClient(calls_dir, configuration=copy.deepcopy(config))   # fail before any draft if a key is unusable
    # one client per draft: its .calls are that draft's own call records (threads never share them)
    return (lambda: ec.ErisedaiClient(calls_dir, configuration=copy.deepcopy(config))), table


def _ec_fails():
    import live.erisedai_distillation_client as ec
    return bool(ec.PROVIDER_FAILS)


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
    group += [r for r in pick.get('support_records') or [] if group]   # live/x_support: cited support facts
    source = dict(group[0]['source']) if group else {}
    post_time = datetime.fromisoformat(pick['suggested_post_time_london'])
    angle = angles.payload(pick['angle'], lang)
    started = time.monotonic()
    try:
        # inside the guard: a span that no rebuilt paragraph contains (StopIteration) sank the whole Oct 7 run
        source, units = evidence_source(group)
        result = compose.compose_source(
            source, account, dc, post_type=pick.get('post_type') or demo.judgment_type(account), extracted_units=units,
            exemplar_dir=POSTS, exemplar_tags_dir=TAGS, view_ledger=ViewLedger(account),
            now=post_time.astimezone(timezone.utc), post_format=dict(pick['post_format']), angle=angle,
            editor_note=pick.get('editor_note'), reality=pick.get('reality'))
    except budget.BudgetExceeded as exc:
        result = {'status': 'error', 'error': 'budget: ' + str(exc)[:200]}
    except Exception as exc:   # noqa: BLE001 - one bad packet must not sink the day
        result = {'status': 'error', 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    cost = call_cost(dc.paths)
    with lock:
        spend['usd'] += cost
    result = dict(result, account_id=account, source=source, plan=pick, retry_log=log, spend_usd=cost,
                  call_records=dc.paths, seconds=round(time.monotonic() - started, 1), angle=angle)
    if pick.get('support'):
        from live import x_support
        result['support_citations'] = x_support.citations(result, {'records': pick.get('support_records') or []})
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
            **({'hotspot': pick['hotspot'], 'reality': pick.get('reality')} if pick.get('hotspot') else {}),
            # live/x_support: the support fact attached to an own-X view (its own source) and the ledger rows citing it
            **({'support': pick['support'], 'support_citations': result.get('support_citations') or []}
               if pick.get('support') else {}),
            **({'packet': pick['packet']} if pick.get('packet') and pick['packet'] != 'balanced' else {}),
            'draft_status': result.get('draft_status') or ('blocked' if result.get('error') else None),
            'status': result.get('status'), 'error': result.get('error'), 'why': result.get('why'),
            # fix26: a HARD finding left after the one targeted rewrite (needs_review) is a HOLD, never ready
            'held': bool(arb.get('status') == 'HOLD' or result.get('status') == 'error' or not result.get('text')
                         or result.get('draft_status') == 'needs_review' or result.get('lane_fit')),
            # Sirius item 4: hard after the one targeted rewrite = HOLD; a rewrite the model / API never returned is a
            # model_error hold (retry path), not a content verdict
            'hold_reason': ('off_lane: ' + str((result.get('lane_fit') or {}).get('detail') or '')
                            if result.get('lane_fit') and result.get('draft_status') != 'needs_review' else
                            'arbitration' if arb.get('status') == 'HOLD' else
                            ('model_error: ' if repair.get('result') == 'rewrite_error' else 'hard: ')
                            + ','.join(sorted({f['code'] for f in findings if f.get('level') == 'hard'}))
                            if result.get('draft_status') == 'needs_review' else None),
            **({'hook_rewrite': result['hook_rewrite']} if result.get('hook_rewrite') else {}),
            **({'hard_repair': {k: repair.get(k) for k in ('result', 'kept', 'error')}
                               | {'first_codes': sorted({f['code'] for f in repair.get('first_findings') or []}),
                                  'retry_codes': sorted({f['code'] for f in repair.get('retry_findings') or []})}}
               if repair else {}),
            **({'lane_fit': result['lane_fit']} if result.get('lane_fit') else {}),
            **({'cold_start_quote': True} if pick.get('cold_start_quote') else {}),
            # Oct 8 (live/engagement.py): quote / reply target chosen (or refused) by the engagement scoring
            **({'engagement': pick['engagement']} if pick.get('engagement') else {}),
            **({'motif_heat': pick['motif_heat']} if pick.get('motif_heat') is not None else {}),
            'arbitration': arb, 'findings': findings,
            'stance': {k: (result.get('stance') or {}).get(k) for k in ('decision', 'account_view', 'subject', 'direction')},
            'source': {'id': src.get('id'), 'source_id': src.get('source_id'), 'publisher': pick.get('publisher'),
                       'title': pick.get('title'), 'url': pick.get('url'), 'published_at': pick.get('published_at'),
                       'lang': pick.get('source_lang'), 'same_language': pick.get('same_language')},
            'models': models, 'alt_model': [m for m in models if m in stage_models.approved_alt_models()],
            'spend_usd': result.get('spend_usd'), 'publishable': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--day', type=date.fromisoformat, default=None,
                    help='drafting day (default: Beijing calendar date of --now / the current time)')
    ap.add_argument('--now', type=lambda s: datetime.fromisoformat(s.replace('Z', '+00:00')), default=None,
                    help='simulated clock for the day default and selection reference (ISO with offset; '
                         'use with --select-only to check a schedule without model calls)')
    ap.add_argument('--accounts')
    ap.add_argument('--per-account', type=int, default=2)
    ap.add_argument('--budget-usd', type=float, default=float(os.environ.get('FD_DAILY_COMPOSE_BUDGET_USD', '8.0')))
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--select-only', action='store_true', help='selection + plan only, no model calls')
    ap.add_argument('--fill', action='store_true',
                    help='top each account up to --per-account READY drafts for the day (held / superseded drafts do '
                         'not count; sources of drafts an audit superseded for a rewrite may be reused)')
    ap.add_argument('--rewrite-notes', type=Path,
                    help='--fill: JSON {draft_id: editor note}; those held drafts are rewritten from the same source '
                         'with the note (audit-superseded rewrite drafts use their audit reason by default)')
    ap.add_argument('--hotspot-merge', action='store_true',
                    help='with --select-only: still run (or reuse) the day\'s one flash 母题 merge call (FD_HOTSPOT, '
                         'relay, <= $0.30); without it a select-only plan uses a cached merge or deterministic clusters')
    ap.add_argument('--force', action='store_true', help='run even when FD_DAILY_COMPOSE is not 1')
    args = ap.parse_args()
    if args.now and args.now.tzinfo is None:
        ap.error('--now needs a UTC offset, e.g. 2026-10-07T23:13+01:00')
    args.day = args.day or drafting_day(args.now)
    # Oct 8 evening (live/hook_voice.py): a "new high" claim is checked against the latest price in real runs
    os.environ.setdefault('FD_STALE_PRICE', '1')
    if os.environ.get('FD_DAILY_COMPOSE') != '1' and not args.force and not args.select_only:
        print('FD_DAILY_COMPOSE is not 1: daily compose is off; nothing done')
        return 0
    per_account = max(1, min(MAX_PER_ACCOUNT, args.per_account))
    accounts = fd_accounts.rows(CONFIG)   # Oct 8: 36-account roster, FD_ACCOUNTS_EXTRA / FD_ACCOUNTS_NEW gates
    if args.accounts:
        wanted = set(args.accounts.split(','))
        accounts = [a for a in accounts if a['id'] in wanted]
    if not UNIVERSES.exists():
        raise SystemExit(f'{UNIVERSES} missing: run scripts/persona_factory.py first')
    universes = load_json(UNIVERSES)
    # Oct 8: a run keeps topping accounts up - after the first pass, fill rounds (FD_FILL_ROUNDS, default 3; --fill runs
    # are fill rounds from the start) pick the next untried candidate of every account still short of --per-account
    # ready drafts, until all have them or candidates / budget / quota run out. fill_status.json says why each stopped.
    extra = max(0, int(os.environ.get('FD_FILL_ROUNDS', '3')))
    rounds = 1 if args.select_only else 1 + extra
    state = {'spend': {'usd': 0.0}, 'lock': threading.Lock(), 'quota': {}, 'client': None, 'records': None,
             'run_ids': [], 'tally': {a['id']: Counter() for a in accounts}, 'last': {}}
    summary = out = None
    for rnd in range(rounds):
        fill = args.fill or rnd > 0
        accts = accounts
        if fill and rnd > 0:
            ready = drafted_today(args.day, ready_only=True)
            accts = [a for a in accounts if ready.get(a['id'], 0) < per_account]
            if not accts:
                break
        res = run_round(args, accts, accounts, universes, per_account, fill, rnd, state)
        if res is None:   # --select-only
            return 0
        out, summary, planned = res
        if state['quota'] or not planned or summary.get('budget_exhausted'):
            break
    if summary is None:
        return 0
    status = fill_status(args.day, accounts, per_account, state, rounds)
    summary['fill_status'] = status
    write_json(out / 'fill_status.json', status)
    print('fill status', json.dumps({a: v['stopped'] for a, v in status['accounts'].items()}, ensure_ascii=False),
          flush=True)
    # ---- 回看 hook (live/archive_lookback.py): FD_ARCHIVE (default on for its config's pilot accounts) gives an account
    # still short of ready drafts one look-back draft; never fatal to the day.
    if os.environ.get('FD_ARCHIVE', '1') != '0':
        try:
            from live import archive_lookback
            summary['archive'] = archive_lookback.fill_gaps(args.day.isoformat(), accounts=[a['id'] for a in accounts])
        except Exception as exc:   # noqa: BLE001
            summary['archive'] = {'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
    # ---- end 回看 hook
    write_json(out / 'summary.json', summary)
    from backend.compose_inbox import render
    page = DASHBOARD / f'fd20_review_{args.day.isoformat()}.html'
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render(compose_inbox.rows(args.day.isoformat()), args.day.isoformat(), summary=summary))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('per_account', 'fill_status')}, ensure_ascii=False),
          flush=True)
    print('review page', page, flush=True)
    return 0


NOT_TRIED = re.compile(r'configured spending cap|run budget|RESOURCE_EXHAUSTED|PerDay|quota|prepayment|\b402\b', re.I)


def tried_sources(day, keep=None):
    """{account: source ids / titles / hashes} this account already composed today (any outcome but a budget / quota
    stop that never reached the model), from the day's run dirs and inbox. keep: {account: keys} not to list (rewrite
    targets). --fill rounds skip them, so a not_suitable / held / failed source is not drafted again (10-08: three
    fill runs re-planned the same not_suitable packets)."""
    entries = []

    def add(account, *keys):
        entries.append((account, {k for k in keys if k}))
    for path in sorted((RUNS / day.isoformat()).glob('*/drafts/*.json')):
        try:
            r = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if NOT_TRIED.search(str(r.get('error') or '')):
            continue
        p, src = r.get('plan') or {}, r.get('source') or {}
        add(r.get('account_id'), p.get('source_id'), p.get('title'), (p.get('source_key') or [None])[0],
            src.get('id'), src.get('original_source_hash'))
    for r in compose_inbox.rows(day.isoformat()):
        src = r.get('source') or {}
        add(r.get('account_id'), src.get('id'), src.get('title'))
    out = {}
    for account, keys in entries:
        if keys & set((keep or {}).get(account) or ()):
            continue   # a rewrite target: every key of that source stays usable
        out.setdefault(account, set()).update(keys)
    return out


def run_round(args, accts, all_accounts, universes, per_account, fill, rnd, state):
    """One select -> compose -> arbitrate -> inbox pass. Returns (run dir, summary, planned jobs) or None (select-only)."""
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    if run_id in state['run_ids'] or (RUNS / args.day.isoformat() / run_id).exists():
        run_id += f'-r{rnd}'
    state['run_ids'].append(run_id)
    out = RUNS / args.day.isoformat() / run_id
    info = {}
    if fill:
        done = drafted_today(args.day, ready_only=True)
        rewrites = (rewrite_targets(args.day, load_json(args.rewrite_notes) if args.rewrite_notes else None)
                    if rnd == 0 else {})   # a rewrite gets one attempt per run
        reuse = {a: set(m) for a, m in rewrites.items()}
        skip = tried_sources(args.day, keep=reuse) if os.environ.get('FD_FILL_SKIP_TRIED', '1') != '0' else None
        plan, order = select(accts, universes, args.day, per_account, done=done, cap=per_account,
                             seed_events=ready_events(args.day, fd_accounts.rows(CONFIG)),
                             reuse=reuse, rewrites=rewrites, now=args.now,
                             allow_model=not args.select_only or args.hotspot_merge, info=info, skip_sources=skip)
    else:
        done = drafted_today(args.day)
        # Oct 8 evening: a first run on a day that already has drafts respects their events too (per-language cap)
        plan, order = select(accts, universes, args.day, per_account, done=done, now=args.now,
                             seed_events=ready_events(args.day, fd_accounts.rows(CONFIG)),
                             allow_model=not args.select_only or args.hotspot_merge, info=info)
    write_json(out / 'plan.json', {'day': args.day.isoformat(), 'day_basis': 'Asia/Shanghai calendar date',
                                   'selection_ref': selection_ref(args.day, args.now).isoformat(), 'pick_order': order, 'per_account': per_account,
                                   'fill': fill, 'round': rnd, 'drafted_earlier_today': done,
                                   **info, 'accounts': plan})
    if (info.get('engagement') or {}).get('targets') and not args.select_only:   # live/engagement.py daily log
        from live import engagement
        engagement.write_log(args.day.isoformat(), info['engagement']['targets'], run_id=run_id)
    for a in accts:
        print(a['id'], [f"{'REWRITE ' if p.get('rewrite_of') else ''}{'HOT ' if p.get('hotspot') else ''}{p['suggested_post_time_london'][11:16]} {p['post_format']['type']} {p['angle']} "
                        f"{p['source_lang']}{'=' if p['same_language'] else '>'}{a['lang']} {str(p['title'])[:40]}"
                        for p in plan[a['id']]], flush=True)
    for a in accts:
        state['last'][a['id']] = {'round': rnd, 'picks': len(plan[a['id']]), 'pool': (info.get('pool_sizes') or {}).get(a['id']),
                                  'skipped_tried': (info.get('skipped_tried') or {}).get(a['id'], 0)}
    if args.select_only:
        return None
    if state['client'] is None:
        state['client'], state['table'] = make_client(out / 'calls')
        store = ContentStore()
        records = {}
        for a in all_accounts:
            for beat in a['retrieval_beats']:
                for r in units_for_persona(store, beat, max_age_days=MAX_AGE_DAYS + 2):
                    records.setdefault(r['unit_id'], r)
        state['records'] = records
    client, table, records = state['client'], state['table'], state['records']
    jobs = [(a, p) for i in range(per_account) for a in accts if i < len(plan[a['id']]) for p in [plan[a['id']][i]]]
    spend, lock, quota = state['spend'], state['lock'], state['quota']
    est = EST_PER_DRAFT_PRO if 'pro' in stage_models.for_stage(table, 'compose')['model'] else EST_PER_DRAFT
    # Oct 8: compose on flat-rate subrouter costs the run budget nothing (calls ledgered at nominal cost, 0 toward the
    # cap), so no per-draft reserve is held while it serves; while its provider breaker counts failures (calls are
    # going to the micuapi fallback, which is paid) the normal reserve applies again.
    flat_primary = stage_models.is_flat_rate((stage_models.route(table, 'compose') or {}).get('base_url'))
    results, skipped = [], []
    by_id = {a['id']: a for a in all_accounts}
    spent_before = spend['usd']

    def guarded(job):
        a, p = job
        with lock:
            if quota:   # a daily Gemini quota is exhausted: starting more drafts would only fail
                skipped.append({'account_id': a['id'], 'source_id': p['source_id'], 'reason': quota['reason']})
                return None
            est_now = 0.0 if flat_primary and not _ec_fails() else est
            if spend['usd'] + est_now > args.budget_usd:
                skipped.append({'account_id': a['id'], 'source_id': p['source_id'],
                                'reason': f'run budget: ${spend["usd"]:.3f} spent of ${args.budget_usd}'})
                return None
        r = compose_one(client, a['id'], p, args.day, records, spend, lock)
        if QUOTA_RX.search(str(r.get('error') or '')):
            with lock:
                quota.setdefault('reason', 'Gemini quota / balance exhausted: ' + str(r['error'])[:160])
        print(f"[r{rnd} {a['id']}] {p['angle']} {p.get('packet', 'balanced')} {r.get('draft_status')} "
              f"${r['spend_usd']:.4f} {r['seconds']}s err={r.get('error')} | {(r.get('body') or '')[:90]!r}", flush=True)
        return r

    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for r in pool.map(guarded, jobs):
            if r is not None:
                results.append(r)
    # cross-account check on the whole day: shape / skeleton findings + claim arbitration (soft: losers HOLD)
    from live import compose_shapes, hook_rewrite as hr, hook_voice as hv, lane_fit
    ok = [r for r in results if r.get('status') != 'error' and r.get('text')]
    compose_shapes.batch_findings(ok)
    # Oct 9 hook1009: opener-repeat check then targeted first-line rewrite for weak/repeat openers.
    if os.environ.get('FD_HOOK_DIVERSITY', '1') != '0':
        _rewrite_max = int(os.environ.get('FD_HOOK_REWRITE_MAX', '12'))
        _rw_count = 0
        # batch_opener_findings expects rows sorted by suggested_post_time_london then id
        _opener_rows = sorted(
            [r for r in ok if r.get('body')],
            key=lambda r: (r.get('plan', {}).get('suggested_post_time_london') or '', r.get('id') or ''))
        _opener_input = [{'id': r.get('id', ''), 'account_id': r.get('account_id', ''),
                          'lang': r.get('plan', {}).get('account_lang', 'zh'),
                          'body': r.get('body', '')} for r in _opener_rows]
        for _item in hv.batch_opener_findings(_opener_input):
            _did = _item['id']
            _finding = _item['finding']
            _match = next((r for r in ok if r.get('id') == _did), None)
            if _match is not None:
                _match.setdefault('post_checks', [])
                _match['post_checks'].append(_finding)
                _match.setdefault('risks', [])
                _match['risks'].append({**_finding, 'status': 'warning'})
        # rewrite drafts that have opener_repeat or a residual weak_hook (after compose's own pass)
        _avoid = list(hv.WEAK_OPENERS_ZH) + list(hv.WEAK_OPENERS_EN)
        for r in ok:
            if _rw_count >= _rewrite_max:
                break
            _codes = {f.get('code') for f in (r.get('post_checks') or []) if isinstance(f, dict)}
            if not (_codes & {'opener_repeat', 'weak_hook'}):
                continue
            _lang = r.get('plan', {}).get('account_lang', 'zh')
            # respect budget: skip if run budget is exhausted
            with lock:
                _est_now = 0.0 if flat_primary and not _ec_fails() else est
                _budget_ok = spend['usd'] + _est_now <= args.budget_usd and not quota
            if not _budget_ok:
                break
            _rw = hr.rewrite_first_line(client(), r, _avoid, _lang)
            r['hook_rewrite'] = _rw
            _rw_count += 1
            if _rw.get('kept') and _rw.get('to') and not _rw.get('error'):
                print(f'[hook_rewrite] {r.get("account_id")} rewritten: {_rw["from"]!r} -> {_rw["to"]!r}', flush=True)
    for r in ok:   # arbitration compares drafts of this Beijing day (not the sources' own dates) in one language
        r['day'], r['account_lang'] = args.day.isoformat(), r['plan']['account_lang']
        # Oct 8 evening (FD_LANE_FIT): a niche draft on broad news without a lane tie-in is held off_lane
        lf = lane_fit.draft_check(by_id[r['account_id']], r.get('body') or '')
        if not lf['ok']:
            r['lane_fit'] = lf
    # Oct 8: only drafts that can ship take part in arbitration - a needs_review draft (hard finding after its rewrite)
    # won the lane on 10-08 (crypto_onchain_en) and its duplicate was held too, so neither was publishable
    eligible = [r for r in ok if r.get('draft_status') != 'needs_review' and not r.get('lane_fit')]
    # FD_ARB_SAME_LANG (default 1): only accounts of one language can duplicate each other (0 = cross-language too).
    # Oct 8 evening: FD_ARB_CONCLUSION (default 1) also holds a same-conclusion draft from a different source, and
    # today's ready drafts from earlier runs take part as fixed keepers (a fill round cannot repeat them).
    locked = [x for x in compose_inbox.rows(args.day.isoformat())
              if x.get('text') and not x.get('held') and not x.get('superseded')
              and x.get('draft_status') == 'draft_ready' and x.get('run_id') != run_id]
    arbitrated = ({id(r): r for r in compose.arbitrate_batch(
        eligible, same_language=os.environ.get('FD_ARB_SAME_LANG', '1') != '0',
        same_conclusion=os.environ.get('FD_ARB_CONCLUSION', '1') != '0', locked=locked)} if eligible else {})
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
                                 own_handles=[a.get('handle') for a in all_accounts])
            replies[row['account_id']] = replies.get(row['account_id'], 0) + (row.get('post_mode') == 'reply')
        if row['text']:   # only real drafts enter the review inbox; failures stay in the run summary
            compose_inbox.add(row)
            supersede_previous(row, earlier)
        rows.append(row)
        write_json(out / 'drafts' / f"{row['id']}.json", r)
        t = state['tally'][row['account_id']]
        t['attempts'] += 1
        t['ready' if row['text'] and not row['held'] else
          'held:' + (row.get('hold_reason') or 'held') if row['text'] else
          'not_suitable' if r.get('draft_status') == 'not_suitable' else 'error'] += 1
    for x in skipped:
        state['tally'][x['account_id']]['skipped:' + ('quota' if 'quota' in x['reason'] else 'budget')] += 1
    counts = {a['id']: {'drafts': sum(1 for x in rows if x['account_id'] == a['id'] and x['text']),
                        'held': sum(1 for x in rows if x['account_id'] == a['id'] and x['held']),
                        'errors': sum(1 for x in rows if x['account_id'] == a['id'] and x['error'])} for a in accts}
    summary = {'day': args.day.isoformat(), 'run_id': run_id, 'round': rnd, 'fill': fill, 'accounts': len(accts),
               'planned': len(jobs), 'blocked': quota.get('reason'),
               'composed': len(results), 'skipped_budget': skipped, 'drafts_with_text': sum(1 for x in rows if x['text']),
               'held': sum(1 for x in rows if x['held'] and x['text']), 'spend_usd': round(spend['usd'] - spent_before, 4),
               'spend_usd_run_total': round(spend['usd'], 4),
               'errors': [{'account_id': x['account_id'], 'source': x['source'].get('title'), 'error': x['error']}
                          for x in rows if x['error']],
               'budget_usd': args.budget_usd, 'budget_exhausted': bool(skipped) or spend['usd'] + (0.0 if flat_primary and not _ec_fails() else est) > args.budget_usd,
               'models': sorted({m for x in rows for m in x['models']}),
               'compose_model': stage_models.for_stage(table, 'compose')['model'], 'per_account': counts,
               'inbox': str(compose_inbox.root() / args.day.isoformat()), 'publishing_enabled': False}
    write_json(out / 'summary.json', summary)
    print(f'round {rnd}: planned {len(jobs)}, composed {len(results)}, with text {summary["drafts_with_text"]}, '
          f'held {summary["held"]}, spend ${summary["spend_usd"]:.3f} (run ${spend["usd"]:.3f})', flush=True)
    return out, summary, len(jobs)


def fill_status(day, accounts, per_account, state, rounds):
    """Per account: ready drafts at the end, what each round tried, and why the run stopped topping it up."""
    ready = drafted_today(day, ready_only=True)
    out = {}
    for a in accounts:
        aid = a['id']
        last, t = state['last'].get(aid) or {}, state['tally'][aid]
        if ready.get(aid, 0) >= per_account:
            why = 'reached'
        elif state['quota']:
            why = 'quota: ' + state['quota']['reason'][:160]
        elif t.get('skipped:budget'):
            why = 'budget'
        elif last.get('picks') == 0:
            why = (f"no_candidates (pool {last.get('pool')} after skipping {last.get('skipped_tried', 0)} sources "
                   f"tried today; event caps / used sources take the rest)")
        elif last.get('round', 0) >= rounds - 1:
            why = 'max_rounds'
        else:
            why = 'stopped_with_run'   # another account's quota / the run budget ended the loop
        out[aid] = {'ready': ready.get(aid, 0), 'target': per_account, 'stopped': why, 'tried': dict(t)}
    return {'day': day.isoformat(), 'rounds_run': len(state['run_ids']), 'run_ids': state['run_ids'],
            'spend_usd': round(state['spend']['usd'], 4),
            'short': sorted(a for a, v in out.items() if v['ready'] < per_account), 'accounts': out}


if __name__ == '__main__':
    sys.exit(main())
