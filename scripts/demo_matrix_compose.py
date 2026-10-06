#!/usr/bin/env python3
"""Four matrix drafts, direct evidence -> stance -> compose; human review only.

Defaults to dry mode. Pass --live to probe relays and compose under a hard
ledger cap. Failed/missing live slots receive explicitly synthetic drafts.
No account configuration or production view/history ledger is written.
"""
from __future__ import annotations

import argparse
import json
import os
import math
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import compose_ab
from voice_relay_check import evidence_source, has_valid_view, rank_evidence_groups
from live import anti_repeat, compose, registry, source_prescreen as prescreen
from live.content_store import ContentStore
from live.retrieval import units_for_persona
from live.view_ledger import ViewLedger
from ml import budget

ACCOUNTS = ('zh_macro', 'zh_industry', 'en_macro', 'en_industry')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def balanced(records):
    """A judgment packet needs >=1 grounded view AND >=1 fact (else zh/en slice may be pure_data)."""
    return (any(has_valid_view(r['unit']) for r in records)
            and any(r['unit'].get('kind') == 'fact' for r in records))


def _key(record):
    source = record['source']
    return (source.get('source_hash'), source.get('id'))


def zh_native(group):
    source = group[0]['source'] if group else {}
    lang = str(source.get('source_language') or source.get('language') or '').lower()
    return lang.startswith('zh') or bool(re.search(r'[\u4e00-\u9fff]', str(source.get('title') or '')))


def _view_ids(group):
    return {r['unit_id'] for r in group if has_valid_view(r['unit'])}


def group_freshness(group, now=None):
    """Freshness boost of a packet = its freshest dated fact/view (shelf classes in
    live/freshness_policy.json: market_flow 1bd, macro 3d, commentary 5d, filings/research 10d).
    1.0 fresh; stale decays to 0.3; expired 0.3; undated 0.4. Evergreen units are ignored."""
    from live import freshness
    best = None
    for record in group:
        if record['unit'].get('kind') not in ('fact', 'view'):
            continue
        status = freshness.status(record, now)
        if status['status'] == 'evergreen':
            continue
        value = freshness.boost(status)
        best = value if best is None else max(best, value)
    return 0.4 if best is None else round(best, 3)


def ranked_balanced(groups, now=None):
    """Balanced packets, freshest first (stable within equal freshness = retrieval order)."""
    balanced_groups = [g for g in rank_evidence_groups(list(groups)) if balanced(g)]
    return sorted(balanced_groups, key=lambda g: -group_freshness(g, now))


# Oct 6 v10 (Fiona: "这是今天收取的素材写出来的吗？"): for timely beats a packet inside its shelf life
# (live/freshness_policy.json: market_flow 1 business day, macro 3d, commentary 5d, filings 10d; evergreen
# unchanged) is a strong tier, not just a ranking weight. Older packets are a recorded fallback only.
TIMELY_BEATS = frozenset({'macro_zh', 'macro_rates_en', 'industry_ai_capex', 'zh_us_stock_commentary',
                          'market_data_charts', 'trading_shortterm', 'crypto_macro_en', 'crypto_macro_zh'})


def timely(account):
    from live.jev_front import jev_persona_for
    return jev_persona_for(account) in TIMELY_BEATS


def in_shelf(group, now=None):
    """True when at least one dated fact/view of the packet is still inside its own shelf life."""
    return group_freshness(group, now) >= 1.0


def group_hook_repeat(group, recent, now=None):
    """Events (one payroll release, one CPI print ...) of this packet the persona already wrote on."""
    from live import news_hook
    return news_hook.repeated(group, recent, now)


def group_theme_repeat(group, recent):
    """True when the packet's view subjects strongly overlap one of the persona's last drafts
    (Oct 6 v5: zh_industry wrote 财富集中 again from a different source)."""
    from live import anti_repeat
    views = [r['unit'] for r in group if isinstance(r['unit'].get('view'), dict)]
    subjects = ' '.join(str(u['view'].get('subject') or '') for u in views)
    statements = ' '.join(str(u.get('statement') or '') for u in views)
    for row in (recent or [])[-anti_repeat.THEME_WINDOW:]:
        subj, text = anti_repeat.theme_overlap(subjects, statements, row)
        if subj >= anti_repeat.THEME_SUBJECT_MIN or text >= anti_repeat.THEME_TEXT_MIN:
            return True
    return False


MAX_AGE_DAYS = 45


def _funnel(records, licensed, dropped, groups):
    """v10b: counts behind a slot's selection (why an account has no balanced packet)."""
    def n_sources(rs):
        return len({_key(r) for r in rs})
    remaining = list(groups.values())
    return {'max_age_days': MAX_AGE_DAYS,
            'tagged_units': len(records), 'tagged_sources': n_sources(records),
            'licence_dropped_units': len(records) - len(licensed),
            'licence_dropped_sources': n_sources(records) - n_sources(licensed),
            'excluded_used_sources': len(dropped),
            'excluded_used_units': sum(map(len, dropped.values())),
            'excluded_balanced_sources': sum(1 for g in dropped.values() if balanced(g)),
            'remaining_sources': len(remaining),
            'balanced_sources': sum(1 for g in remaining if balanced(g)),
            'no_valid_view_sources': sum(1 for g in remaining if not any(has_valid_view(r['unit']) for r in g)),
            'no_fact_sources': sum(1 for g in remaining if not any(r['unit'].get('kind') == 'fact' for r in g))}


def no_candidate_reason(funnel, selection=None):
    """Human-readable cause of an empty slot, from the actual filter counts (replaces the old
    'No eligible tagged evidence within 45 days.', which blamed the window for chain exclusion)."""
    f = funnel or {}
    parts = [f"{f.get('tagged_units', 0)} tagged units/{f.get('tagged_sources', 0)} sources within "
             f"{f.get('max_age_days', MAX_AGE_DAYS)}d"]
    if f.get('licence_dropped_sources'):
        parts.append(f"{f['licence_dropped_sources']} sources dropped by licence tier (not A/B)")
    parts.append(f"{f.get('excluded_used_sources', 0)} sources excluded as already used by this account"
                 + (f" ({f['excluded_balanced_sources']} of them balanced)" if f.get('excluded_balanced_sources') else ''))
    unbalanced = f.get('remaining_sources', 0) - f.get('balanced_sources', 0)
    parts.append(f"{unbalanced} remaining lacked a valid view + fact "
                 f"({f.get('no_valid_view_sources', 0)} no valid view, {f.get('no_fact_sources', 0)} no fact)")
    if f.get('balanced_sources'):
        parts.append(f"{f['balanced_sources']} balanced source(s) left only as the pair partner's pick with no "
                     "balanced shared slice")
    return 'no balanced packet: ' + '; '.join(parts)


def select_groups(store, accounts, selection=None, exclude_sources=(), recent=None, backups=None):
    """Pick one balanced (view + fact) packet per account; ZH prefers its OWN source.

    Oct 6 v2: sharing the EN source made both ZH slots HOLD (same conclusion, same source).
    Order per pair: EN takes its best balanced packet; ZH takes its best balanced packet from a
    DIFFERENT source (ZH-native first). Only when ZH has no other balanced packet does it share
    EN's source, and then only with a differentiated angle: ZH keeps the views EN does not carry
    (slice must stay balanced). Without a different view the slice is kept as-is and marked
    ``shared_same_angle`` so claim arbitration can HOLD the genuine duplicate.
    ``selection`` (optional dict) receives {account: {'mode', 'source_id', ...}}.
    ``recent`` (optional {account: history rows}): packets repeating a recent theme rank last.
    """
    recent = recent or {}
    selection = {} if selection is None else selection
    grouped = {}
    excluded_fresh = {}
    funnels = {}
    # v10b: a legacy (unattributed) entry whose document hash is in some account's history belongs to that
    # account only; the per-account hash check below already covers it.
    attributed_hashes = (set().union(*exclude_sources.by_account.values())
                         if isinstance(exclude_sources, ExcludedSources) else set())
    for account in accounts:
        groups = {}
        dropped = {}
        own_used = excluded_for(exclude_sources, account)
        legacy = exclude_sources.unattributed if isinstance(exclude_sources, ExcludedSources) else set()
        records = units_for_persona(store, account, max_age_days=MAX_AGE_DAYS)
        licensed = [r for r in records if r.get('licence_tier') in ('A', 'B')]
        for record in licensed:
            src = record['source']
            keys = {src.get('id'), src.get('title'), src.get('source_hash')} - {None, ''}
            hit = keys & own_used
            if hit and not (hit <= legacy and src.get('source_hash') in attributed_hashes):
                dropped.setdefault(_key(record), []).append(record)
                continue   # already used by this account (id, or same document under another id / hash)
            groups.setdefault(_key(record), []).append(record)
        grouped[account] = groups
        # v10: in-shelf packets the --continue-from chain excluded (Oct 6 v9a: today's 3 fresh sources had
        # all been used by v7, so every slot fell back to older material)
        excluded_fresh[account] = sum(1 for g in dropped.values() if balanced(g) and in_shelf(g))
        funnels[account] = _funnel(records, licensed, dropped, groups)

    def strong(account, g):
        """v10 tier: a timely beat's in-shelf packet beats any older one that passes the same pre-screen."""
        return in_shelf(g) if timely(account) else True

    def ranked(account, exclude=()):
        # Oct 6 v4: freshness weight (en_industry used a 9/17 commentary source on 10/6).
        options = ranked_balanced([g for k, g in grouped[account].items() if k not in exclude])
        # v5: prefer a fresh theme over the persona's last drafts (stable sort keeps freshness order)
        # v9: persona pre-screen first - packets with a cheap reason to expect a stance reject rank last
        # v10: in-shelf tier (timely beats), then news-hook repeat (same event the persona already wrote on)
        return sorted(options, key=lambda g: (not prescreen.prescreen(account, g)['ok'], not strong(account, g),
                                              bool(group_hook_repeat(g, recent.get(account))),
                                              group_theme_repeat(g, recent.get(account))))

    def fallback_info(account, group, pool):
        """v10: why a timely beat's slot is not on an in-shelf packet (None when it is / beat not timely)."""
        if not group or not timely(account) or in_shelf(group):
            return None
        fresh = [g for g in pool if in_shelf(g)]
        return {'reason': 'in_shelf_failed_prescreen' if fresh else 'no_in_shelf_candidate',
                'in_shelf_candidates': len(fresh),
                'in_shelf_excluded_by_chain': excluded_fresh.get(account, 0),
                'chosen_published_at': group[0]['source'].get('published_at'),
                'chosen_freshness': group_freshness(group)}

    def note(account, mode, group, pool=(), **extra):
        selection[account] = {'mode': mode, 'source_id': group[0]['source'].get('id') if group else None,
                              'theme_repeat': group_theme_repeat(group, recent.get(account)) if group else False,
                              'news_hook_repeat': group_hook_repeat(group, recent.get(account)) if group else [],
                              'zh_native': zh_native(group) if group else False,
                              'freshness': group_freshness(group) if group else None,
                              'in_shelf': in_shelf(group) if group else None,
                              'freshness_fallback': fallback_info(account, group, pool),
                              'published_at': group[0]['source'].get('published_at') if group else None,
                              'prescreen': prescreen.prescreen(account, group) if group else None, **extra}

    chosen = {}
    for zh, en in (('zh_macro', 'en_macro'), ('zh_industry', 'en_industry')):
        en_group = []
        if en in grouped:
            options = ranked(en)
            en_group = options[0] if options else []   # no balanced packet -> skip, never pure_data
            chosen[en] = en_group
            note(en, 'own' if en_group else 'none', en_group, options)
            if backups is not None:
                backups[en] = options[1:3]
        if zh not in grouped:
            continue
        en_key = _key(en_group[0]) if en_group else None
        own = ranked(zh, exclude={en_key} if en_key else ())
        # ZH-native first among sources that are not past shelf life; a stale native source does
        # not beat a fresh different-angle one.
        # v10: in-shelf tier and news-hook repeat come before theme repeat / ZH-native preference.
        own.sort(key=lambda g: (not prescreen.prescreen(zh, g)['ok'], not strong(zh, g),
                                bool(group_hook_repeat(g, recent.get(zh))), group_theme_repeat(g, recent.get(zh)),
                                group_freshness(g) < 1.0, not zh_native(g)))
        if own:
            chosen[zh] = own[0]
            note(zh, 'own_zh_native' if zh_native(own[0]) else 'own_different_source', own[0], own)
            if selection[zh]['freshness_fallback'] and en_group and in_shelf(en_group):
                selection[zh]['freshness_fallback']['in_shelf_taken_by_pair'] = en
            if backups is not None:
                backups[zh] = own[1:3]
            continue
        shared = grouped[zh].get(en_key) if en_key else None
        if not shared or not balanced(shared):
            chosen[zh] = []
            note(zh, 'none', [])
            continue
        en_views = _view_ids(en_group)
        differentiated = [r for r in shared if r['unit_id'] not in en_views]
        if balanced(differentiated):
            chosen[zh] = differentiated
            note(zh, 'shared_differentiated', differentiated, own, dropped_view_ids=sorted(en_views & _view_ids(shared)))
        else:
            chosen[zh] = shared
            note(zh, 'shared_same_angle', shared, own, reason='no own balanced source and no view EN lacks; '
                 'arbitration decides (genuine duplicate -> HOLD)')
    for account in accounts:   # any account outside the two pairs: own best packet
        if account not in chosen:
            options = ranked(account)
            chosen[account] = options[0] if options else []
            note(account, 'own' if chosen[account] else 'none', chosen[account], options)
            if backups is not None:
                backups[account] = options[1:3]
    for account in accounts:
        if account in selection:
            selection[account]['funnel'] = funnels[account]
            if not chosen.get(account):
                selection[account]['no_candidate_reason'] = no_candidate_reason(funnels[account], selection[account])
    return chosen


# Oct 6 v9 slot budget sizing. Observed on Oct 6 v5-v8 live calls (configured token/rate estimates):
# opus stance actual mean $0.170 / p90 $0.213 (reservation $0.315-0.328); gemini compose actual mean
# $0.094 / p90 $0.129 (reservation $0.212-0.221); slot spend mean $0.31, p90 $0.52.
COST_DEFAULTS = {'stance_usd': 0.213, 'compose_usd': 0.129, 'stance_reserve_usd': 0.328, 'compose_reserve_usd': 0.221}


def _p(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def slot_cost_model(root, *, limit=300):
    """p90 actual cost per stance / compose call and max reservation, from recent demo runs under `root`
    (demo_matrix_*/calls, */ledger/spend.json). Falls back to COST_DEFAULTS when < 10 samples."""
    model, source = dict(COST_DEFAULTS), 'defaults (Oct 6 v5-v8 observed)'
    try:
        calls = sorted(Path(root).glob('demo_matrix_*/calls/*.json'), key=lambda p: p.stat().st_mtime)[-limit:]
        stance, comp = [], []
        for path in calls:
            row = json.loads(path.read_text())
            if row.get('status') != 'completed' or not row.get('estimated_cost_usd'):
                continue
            if row.get('stage') == 'stance' and (row.get('max_tokens') or 0) >= 1000:
                stance.append(row['estimated_cost_usd'])
            elif row.get('stage') == 'compose':
                comp.append(row['estimated_cost_usd'])
        res = {'opus': [], 'gemini': []}
        for path in sorted(Path(root).glob('demo_matrix_*/ledger/spend.json'))[-40:]:
            for r in (json.loads(path.read_text()).get('reservations') or {}).values():
                for k in res:
                    if k in str(r.get('model')):
                        res[k].append(float(r.get('estimate') or 0))
        if len(stance) >= 10 and len(comp) >= 10:
            model.update(stance_usd=round(_p(stance, 0.9), 3), compose_usd=round(_p(comp, 0.9), 3))
            if res['opus']:
                model['stance_reserve_usd'] = round(max(res['opus']), 3)
            if res['gemini']:
                model['compose_reserve_usd'] = round(max(res['gemini']), 3)
            source = f'observed p90 of {len(stance)} stance / {len(comp)} compose calls under {root}'
    except Exception as exc:   # never block a run on the estimator
        source = f'defaults (estimator error {type(exc).__name__})'
    model['source'] = source
    return model


def budget_plan(cap, n_slots, m):
    """Per-slot need and how many slots the cap funds. base = stance + compose + 1 regen headroom
    (the regen needs a full compose reservation when it is sent); full = base + 1 backup stance."""
    base = float(os.environ.get('FD_SLOT_BASE_USD') or round(m['stance_usd'] + m['compose_usd'] + m['compose_reserve_usd'], 3))
    full = round(base + m['stance_usd'], 3)
    funded = min(n_slots, int((cap + 1e-9) // base)) if base > 0 else n_slots
    pool = round(cap - n_slots * base, 3)
    status = ('OK_FULL' if cap + 1e-9 >= n_slots * full else
              'OK_BASE_SHARED_BACKUP' if cap + 1e-9 >= n_slots * base else 'INSUFFICIENT')
    return {'cap_usd': cap, 'slots': n_slots, 'base_need_usd': base, 'full_need_usd': full,
            'slots_funded': funded, 'shared_pool_usd': max(0.0, pool),
            'backups_covered': max(0, int(max(0.0, pool) // m['stance_usd'])) if status != 'OK_FULL' else n_slots,
            'cap_for_full_guarantee_usd': math.ceil(n_slots * full * 10) / 10,
            'status': status, 'cost_model': m}


def plan_lines(plan):
    m = plan['cost_model']
    out = [f"Cost model ({m['source']}): stance ${m['stance_usd']:.3f}, compose ${m['compose_usd']:.3f}, "
           f"compose reservation ${m['compose_reserve_usd']:.3f}.",
           f"Per slot: base (stance + compose + 1 regen) ${plan['base_need_usd']:.3f}; "
           f"full (+1 backup stance) ${plan['full_need_usd']:.3f}.",
           f"Status: **{plan['status']}** — cap ${plan['cap_usd']:.2f} for {plan['slots']} slots."]
    if plan.get('no_candidate_accounts'):
        out.append('No candidate (zero need, not funded, error row with the selection funnel): '
                   + ', '.join(plan['no_candidate_accounts']) + '.')
    if plan['status'] == 'INSUFFICIENT':
        out.append(f"**FAIL LOUD: cap funds only {plan['slots_funded']} of {plan['slots']} slots at base need; "
                   f"the rest are error rows (not attempted). Need ≥ ${plan['slots'] * plan['base_need_usd']:.2f}.**")
    elif plan['status'] == 'OK_BASE_SHARED_BACKUP':
        out.append(f"Every slot funded at base; shared pool ${plan['shared_pool_usd']:.2f} covers "
                   f"{plan['backups_covered']} backup stance(s) first-come. Full guarantee for all slots needs "
                   f"${plan['cap_for_full_guarantee_usd']:.2f}.")
    return out


SLOT_MIN_USD = round(COST_DEFAULTS['stance_usd'] + COST_DEFAULTS['compose_usd'] + COST_DEFAULTS['compose_reserve_usd'], 3)


def relay_quota_tripped():
    try:
        from live import erisedai_distillation_client as relay
        return relay.quota_tripped()
    except Exception:   # noqa: BLE001 - SUMMARY must still be written
        return {}


def error_result(account, kind, detail):
    """v9: explicit error row for a live slot (never dressed up as a synthetic draft)."""
    return dict(id='error-' + account, key=account, account_id=account, mode='error', status='error',
                draft_status='error', text='', stance={}, units=[], post_checks=[], ledger_findings=[],
                publishable=False, synthetic=False, error_kind=kind, error=detail, fallback_reason=detail)


def no_candidate_result(account, sel=None):
    """v10b: error row for a slot select_groups left empty, with the real reason and the funnel."""
    sel = sel or {}
    reason = sel.get('no_candidate_reason') or no_candidate_reason(sel.get('funnel'), sel)
    return dict(error_result(account, 'no_candidate', reason), funnel=sel.get('funnel'), selection=sel or None)


def run_slot(account, out, client, selected, backups, selection, batch_shapes, batch_size, notes):
    """One live slot: stance + compose on the best pre-screened packet; one backup packet on a reject."""
    ledger = ViewLedger(account, out / 'views' / account)
    group = selected.get(account) or []
    if not group:
        return no_candidate_result(account, selection.get(account))
    rejected, result, source = [], None, {}
    try:
        for attempt, grp in enumerate([group] + list(backups.get(account) or [])[:1]):
            source, units = evidence_source(grp)
            prior_count = len(ledger.current())
            result = compose.compose_source(
                source, account, client, post_type=judgment_type(account),
                extracted_units=units, exemplar_dir=compose_ab.POSTS,
                exemplar_tags_dir=compose_ab.TAGS, view_ledger=ledger,
                shape_batch=tuple(batch_shapes), shape_batch_size=batch_size)
            group = grp
            if (result.get('stance') or {}).get('decision') != 'reject' or attempt:
                break
            rejected.append({'source_id': source.get('id'), 'title': source.get('title'),
                             'rationale': ((result.get('stance') or {}).get('rationale') or '')[:200]})
        if rejected:
            result['selection_fallback'] = {'rejected': rejected}
        if (result.get('composition_shape') or {}).get('id'):
            batch_shapes.append({'id': result['composition_shape']['id'],
                                 'length': result['composition_shape'].get('length')})
        result.update(key=account, source=source, mode='live',
                      stored_unit_ids=[r['unit_id'] for r in group],
                      ledger_prior_count=prior_count, selection=selection.get(account))
        return result
    except budget.BudgetExceeded as exc:
        reason = f'BudgetExceeded: slot sub-cap refused a call before sending ({str(exc)[:120]}).'
        notes.append(account + ': ' + reason)
        return _keep_rejected(result, account, rejected, reason, 'budget') or error_result(account, 'budget', reason)
    except Exception as exc:
        reason = f'Live compose failed: {type(exc).__name__}: {str(exc)[:160]}.'
        notes.append(account + ': ' + reason)
        return (_keep_rejected(result, account, rejected, reason, 'exception')
                or error_result(account, 'exception', reason))


# Oct 6 v8: inside each slot the last COHERENCE_RESERVE_USD of the slot sub-cap is held back from
# optional polish retries (info_dump / repeat / plain structure) so a coherence repair (judgment or
# internal-contradiction retry) still fits. ~one gemini compose worst-case reservation ($0.21).
COHERENCE_RESERVE_USD = float(os.environ.get('FD_COHERENCE_RESERVE_USD', '0.22'))


def load_fill_into(batch, accounts):
    """Oct 6 v8: drafts of the batch a fill-in run completes (v7_zi filled v7's zh_industry slot but
    was arbitrated alone and duplicated v7 en_industry). Accounts re-run here are not carried."""
    carried = []
    for path in sorted((Path(batch) / 'drafts').glob('*.json')):
        row = json.loads(path.read_text())
        if row.get('account_id') in accounts or row.get('synthetic'):
            continue
        carried.append(dict(row, carried=True, key='carried:' + str(row.get('account_id'))))
    return carried


def arbitrate_with_carried(results, carried=()):
    """Arbitrate new slots together with carried drafts of the same batch. Carried drafts were
    already decided in their own batch, so they stay keepers: a new draft that collides with a carried
    WRITE is HOLD (soft) even if its lane score is higher. Only the new results are returned."""
    carried = list(carried or [])
    merged = compose.arbitrate_batch(list(results) + carried)
    new, old = merged[:len(results)], merged[len(results):]
    if not old or not any('arbitration' in r for r in merged):
        return new
    from live.claim_arbitration import REASON_CODE_SOFT
    for row in old:
        arb = row.get('arbitration') or {}
        if arb.get('status') != 'HOLD':
            continue
        group = arb.get('collision_group')
        for r in new:
            ra = r.get('arbitration') or {}
            if ra.get('status') == 'WRITE' and group is not None and ra.get('collision_group') == group:
                r['arbitration'] = dict(ra, status='HOLD', reason_code='carried_keeper',
                                        reassigned_to=row.get('account_id'), soft=True)
                finding = {'code': REASON_CODE_SOFT, 'level': 'soft',
                           'detail': f"same-conclusion claim held; keeper={row.get('account_id')} (carried batch draft)"}
                r['post_checks'] = list(r.get('post_checks') or []) + [finding]
                r['risks'] = list(r.get('risks') or []) + [{**finding, 'status': 'warning'}]
                if r.get('status') not in ('skipped', 'error', 'needs_review'):
                    r['status'] = 'held'
    for r in new:
        if 'arbitration' in r:
            r['arbitration']['with_carried'] = [c.get('account_id') for c in carried]
    return new


def fake_result(account, ledger, reason, *, record=False):
    """Synthetic evidence and claims, never represented as corpus/model output.

    Oct 6 v7: never writes the synthetic view to the ledger (record=False is the default and the
    loop never overrides it); v6 en_industry's placeholder view became a continuity anchor."""
    macro = account.endswith('macro')
    subject = 'Fed rate cut path' if macro else 'AI capex demand'
    english = ('The Fed easing path remains conditional on inflation cooling.' if macro else
               'AI capex demand needs revenue conversion before conviction rises.')
    chinese = ('美联储降息路径仍取决于通胀降温。' if macro else
               'AI资本开支需求需要收入兑现，才能提高判断信心。')
    view = dict(subject=subject, direction='neutral', conviction='low', horizon='quarters',
                reasoning=['Synthetic conditional judgment for ledger/arbitration plumbing.'])
    stance = dict(decision='adapt', account_view=chinese if account.startswith('zh_') else english,
                  view=view, confidence=0.5, rationale='Synthetic plumbing check; no investment evidence.',
                  supporting_unit_ids=['synthetic-view', 'synthetic-fact'],
                  cited_prior_view_ids=[], revises_view_id=None)
    prior = ledger.related(subject)
    stance = ledger.link_continuity(stance, prior_rows=prior)
    findings = ledger.contradictions(stance) + ledger.ignores_prior(stance, prior_rows=prior)
    stance['ledger_findings'] = findings
    source = dict(id='synthetic-macro' if macro else 'synthetic-industry',
                  source_id='synthetic-macro' if macro else 'synthetic-industry',
                  lang='en', evidence_packet=True, synthetic=True)
    units = [dict(unit_id='synthetic-view', kind='view', view=view, statement=english),
             dict(unit_id='synthetic-fact', kind='fact', statement='Synthetic observation only.')]
    entry = ledger.record(stance, unit_ids=stance['supporting_unit_ids'],
                          source_ids=[source['id']]) if record else None
    return dict(id='synthetic-' + account, key=account, account_id=account, text=stance['account_view'],
                stance=stance, source=source, units=units, pack_balance=compose.pack_balance(units),
                post_checks=[], ledger_findings=findings, ledger_entry=entry,
                ledger_prior_count=len(prior), publishable=False, draft_status='needs_review',
                status='held', mode='synthetic', synthetic=True, fallback_reason=reason,
                spend_usd=0.0)


def _keep_rejected(result, account, rejected, reason, kind='exception'):
    """v8: a backup attempt that fails after a real stance reject keeps the reject (live, key set)
    instead of leaving a half-built result (v8 run crashed on KeyError 'key').
    v9: the row carries error_kind='backup_<kind>' so SUMMARY counts it as an error, not a quiet skip
    (v9a zh_industry: backup stance accepted, its compose timed out, the fallback was refused)."""
    if not result or result.get('key'):
        return result if result and result.get('key') else None
    if (result.get('stance') or {}).get('decision') != 'reject':
        return None
    return dict(result, key=account, account_id=account, mode='live', draft_status='not_suitable',
                status='skipped', fallback_reason=reason, error_kind='backup_' + kind, error=reason,
                selection_fallback={'rejected': rejected,
                                                                               'backup_error': reason})


def judgment_type(account):
    mix = registry.persona_for_account(account).post_type_mix
    for name in ('judgment_take', *mix):
        if name in mix and name in ('judgment_take', 'contrarian_take', 'view_relay'):
            return name
    raise ValueError('No judgment-capable post type for ' + account)


class ExcludedSources(set):
    """Sources (ids / titles / source hashes) already used along a --continue-from chain.

    Oct 6 v10b (v9b zh_macro "No eligible tagged evidence"): the flat chain set excluded a source for
    every account, so ZH-native macro sources only en_macro had written were lost to zh_macro. Now each
    source is attributed to the account(s) that drafted or rejected it; an account only skips its own.
    ``unattributed`` (legacy flat entries no draft of the chain names) still applies to all accounts.
    As a set it is the union of everything, so older callers / tests that compare sets keep working."""

    def __init__(self, by_account=None, unattributed=()):
        self.by_account = {a: {x for x in v if x} for a, v in (by_account or {}).items()}
        self.unattributed = {x for x in unattributed if x}
        super().__init__(self.unattributed.union(*self.by_account.values()))

    def add_for(self, account, values):
        values = {x for x in values if x}
        if account in ACCOUNTS:
            self.by_account.setdefault(account, set()).update(values)
        else:
            self.unattributed.update(values)
        self.update(values)

    def for_account(self, account):
        return self.by_account.get(account, set()) | self.unattributed

    def to_json(self):
        return {'version': 2, 'by_account': {a: sorted(v) for a, v in sorted(self.by_account.items()) if v},
                'unattributed': sorted(self.unattributed), 'all': sorted(self)}


def excluded_for(exclude_sources, account):
    """Per-account view of ``exclude_sources``: ExcludedSources / v2 dict -> that account's set
    (+ unattributed); a plain flat set or list applies to every account (backward compatible)."""
    if isinstance(exclude_sources, ExcludedSources):
        return exclude_sources.for_account(account)
    if isinstance(exclude_sources, dict):
        return set((exclude_sources.get('by_account') or {}).get(account) or ()) | set(
            exclude_sources.get('unattributed') or ())
    return set(exclude_sources or ())


def _draft_sources(batch):
    """{account: ids/titles} its drafts used (a rejected slot's document id and rejected backups count)."""
    used = ExcludedSources()
    for path in sorted((Path(batch) / 'drafts').glob('*.json')):
        row = json.loads(path.read_text())
        source = row.get('source') or {}
        values = {source.get('id'), source.get('title')}
        # v8: a rejected slot has no `source` block; its document id and rejected backups still count
        if not row.get('synthetic') and not source:
            values.add(row.get('source_id'))
        values.update(r.get('source_id') for r in (row.get('selection_fallback') or {}).get('rejected') or [])
        used.add_for(row.get('account_id') or path.stem, values)
    return used


def _history_hashes(batch):
    """{account: source hashes} from the carried draft history rows (history/<account>.jsonl)."""
    out = {}
    for account in ACCOUNTS:
        path = Path(batch) / 'history' / (account + '.jsonl')
        if path.exists():
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            out[account] = {r.get('source_hash') for r in rows if r.get('source_hash')}
    return out


def _flat_excluded(batch):
    path = Path(batch) / 'excluded_sources.json'
    data = json.loads(path.read_text()) if path.exists() else []
    return set(data.get('all') or ()) if isinstance(data, dict) else {x for x in data if x}


def _chain_parents(batch):
    """--continue-from / --fill-into dirs named by the batch's SUMMARY.md Command line. A batch without
    one (v8 crashed before SUMMARY) gets the unique sibling whose used sources (its exclusions + its drafts)
    equal this batch's exclusion list exactly; ambiguous or partial matches give no parent."""
    path = Path(batch) / 'SUMMARY.md'
    line = next((l for l in path.read_text().splitlines() if l.startswith('Command:')), '') if path.exists() else ''
    if line:
        try:
            argv = shlex.split(line.partition('`')[2].rpartition('`')[0])
        except ValueError:
            return []
        return [Path(argv[i + 1]) for i, a in enumerate(argv[:-1]) if a in ('--continue-from', '--fill-into')]
    flat = _flat_excluded(batch)
    if not flat:
        return []
    matches = [p for p in sorted(Path(batch).resolve().parent.iterdir())
               if p.is_dir() and p != Path(batch).resolve() and (p / 'drafts').is_dir()
               and _flat_excluded(p) | set(_draft_sources(p)) == flat]
    return matches if len(matches) == 1 else []


def _chain_draft_sources(batch, seen=None):
    """Per-account draft sources of `batch` and every ancestor (legacy flat attribution)."""
    seen = set() if seen is None else seen
    batch = Path(batch).resolve()
    if batch in seen or not batch.is_dir():
        return ExcludedSources()
    seen.add(batch)
    used = _draft_sources(batch)
    for parent in _chain_parents(batch):
        for account, values in _chain_draft_sources(parent, seen).by_account.items():
            used.add_for(account, values)
    return used


def load_excluded(batch):
    """ExcludedSources from a batch's excluded_sources.json. v2 -> as written; legacy flat list ->
    each entry goes to the account(s) whose drafts along the chain used it, the rest to all accounts."""
    path = Path(batch) / 'excluded_sources.json'
    if not path.exists():
        return ExcludedSources()
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        return ExcludedSources(data.get('by_account'), data.get('unattributed') or ())
    flat = {x for x in data if x}
    chain = _chain_draft_sources(batch)
    return ExcludedSources({a: v & flat for a, v in chain.by_account.items()},
                           flat - set().union(*chain.by_account.values()))


def continue_batch(prev, out):
    """Second consecutive batch: carry the previous batch's draft history (shape rotation) and
    view ledgers into `out`; return the sources it used (per account) so this batch picks new sources."""
    import shutil
    prev = Path(prev).resolve()
    for name in ('history', 'views'):
        if (prev / name).is_dir() and not (out / name).exists():
            shutil.copytree(prev / name, out / name)
    # Oct 6 v5: exclusions accumulate along the chain (v5 continued from v4b but re-picked v4's
    # wealth-concentration source because only v4b's own drafts were excluded).
    # v10b: per account (v2 file); the history rows' source hashes name the account that wrote them.
    used = load_excluded(prev)
    own = _draft_sources(prev)
    for account, values in own.by_account.items():
        used.add_for(account, values)
    used.add_for(None, own.unattributed)
    for account, hashes in _history_hashes(prev).items():
        used.add_for(account, hashes)
    write_json(Path(out) / 'excluded_sources.json', used.to_json())
    return used


def run(out, cap, *, live=False, command='', continue_from=None, only_accounts=None, fill_into=None):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:   # v9: a quota breaker from an earlier run in this process must not leak into this batch
        from live import erisedai_distillation_client as relay
        relay.reset_quota_breaker()
    except Exception:   # noqa: BLE001
        pass
    exclude_sources = continue_batch(continue_from, out) if continue_from else ExcludedSources()
    if fill_into:   # v8: a fill-in never re-picks a source the batch it completes already used
        # v10b: ... for the account that drafted it (cross-account duplicates are left to arbitration)
        for path in sorted((Path(fill_into) / 'drafts').glob('*.json')):
            row = json.loads(path.read_text())
            src = row.get('source') or {}
            exclude_sources.add_for(row.get('account_id') or path.stem, (src.get('id'), src.get('title')))
    budget.STORE = out / 'ledger'
    budget.LEDGER = budget.STORE / 'spend.json'
    budget.RUNS = budget.STORE / 'review_runs.jsonl'
    budget.DISTILLATION_RUNS = budget.STORE / 'distillation_spend.jsonl'
    # Reuse existing spending/reservations instead of resetting an existing ledger.
    budget.set_cap(cap)
    anti_repeat.HISTORY_DIR = out / 'history'
    anti_repeat.FALLBACK_DIR = out / 'history'
    rows = {a['id']: a for a in json.loads((ROOT / 'live/accounts.json').read_text())['accounts']}
    wanted = [a for a in ACCOUNTS if not only_accounts or a in only_accounts]
    accounts = [a for a in wanted if rows.get(a, {}).get('enabled')]
    skipped = [a for a in wanted if a not in accounts]
    notes = ['Explicit --live is required; default mode is dry.',
             'Spend uses configured token/rate estimates and retained reservations; not an invoice.']
    client = None
    reason = 'Dry mode requested/default; no live LLM calls.'
    if live:
        try:
            from live.erisedai_distillation_client import ErisedaiClient, relay_config
            from live import stage_models
            compose_ab.relay_env()
            # Cheap HTTP probes first (no budget burn beyond optional later client call).
            gemini = compose_ab.probe('gemini-3.1-pro-preview', (compose_ab.MICU, 'GEMINI_RELAY_API_KEY'))
            opus = compose_ab.probe('claude-opus-5', (compose_ab.ERISED, 'RELAY_API_KEY'))
            if not gemini.get('available'):
                raise RuntimeError(f"compose relay unavailable: {gemini}")
            if not opus.get('available'):
                raise RuntimeError(f"stance relay unavailable: {opus}")
            configuration = relay_config()
            configuration['stage_models'] = stage_models.load()
            client = ErisedaiClient(out / 'calls', configuration=configuration)
            notes.append('Live relays probed OK (gemini compose + opus stance path).')
            notes.append(f"probe_gemini={gemini.get('response_model')}; probe_opus={opus.get('response_model')}")
        except Exception as exc:
            reason = f'Live probe unavailable: {type(exc).__name__}: {exc}; remaining slots synthetic.'
            notes.append(reason)
            client = None
    selection = {}
    if continue_from or fill_into:
        per = ', '.join(f'{a} {len(exclude_sources.by_account.get(a) or ())}' for a in accounts)
        notes.append((f'Continues batch {continue_from}: history + view ledgers carried over; ' if continue_from
                      else f'Fill-in for {fill_into}: ') + f'{len(exclude_sources)} previous sources/hashes excluded per account (used by: {per}; '
                     f'{len(exclude_sources.unattributed)} legacy entries unattributed -> all accounts unless a '
                     'history source hash names the account).')
    recent_rows = {a: anti_repeat.load_recent(registry.persona_for_account(a).persona_id) for a in accounts}
    backups = {}
    selected = (select_groups(ContentStore(compose_ab.STORE), accounts, selection, exclude_sources=exclude_sources,
                              backups=backups,
                              recent=recent_rows)
                if client else {})
    if selection:
        notes.append('Selection: ' + json.dumps({a: v['mode'] for a, v in selection.items()}, ensure_ascii=False))
        for a, v in selection.items():   # v10: an older-than-shelf pick or a repeated event is said out loud
            if v.get('freshness_fallback'):
                notes.append(f"{a}: freshness_fallback {json.dumps(v['freshness_fallback'], ensure_ascii=False)}")
            if v.get('news_hook_repeat'):
                notes.append(f"{a}: news_hook_repeat {v['news_hook_repeat']} (persona already wrote on this event; "
                             'no non-repeating candidate in the same tier)')
    results = []
    batch_shapes = []   # composition shapes already used in this batch (structure variety)
    carried = []
    synthetic = []
    # v10b: selection runs before the budget split; only slots with a candidate need funding (v9b funded the
    # empty zh_macro slot and left en_industry unfunded with $1.9 of the cap unspent).
    candidates = [a for a in accounts if selected.get(a)] if client else list(accounts)
    no_candidate = [a for a in accounts if a not in candidates]
    plan = budget_plan(cap, len(candidates), slot_cost_model(out.parent))
    plan['no_candidate_accounts'] = no_candidate
    write_json(out / 'budget_plan.json', plan)
    funded = candidates[:plan['slots_funded']] if client else list(accounts)   # dry mode spends nothing
    try:
        carried = load_fill_into(fill_into, accounts) if fill_into else []
        if carried:
            notes.append(f'Fill-in for batch {fill_into}: arbitration + shape mix include carried drafts '
                         + ', '.join(c['account_id'] for c in carried) + '.')
            batch_shapes += [{'id': c['composition_shape']['id'], 'length': c['composition_shape'].get('length')}
                             for c in carried if (c.get('composition_shape') or {}).get('id')]
        for account in accounts:   # v9: top-3 pre-screened candidates per slot, recorded up front
            if account in selection:
                top = [selected.get(account) or []] + list(backups.get(account) or [])
                selection[account]['top3'] = [
                    {'source_id': g[0]['source'].get('id'), 'title': g[0]['source'].get('title'),
                     'prescreen': prescreen.prescreen(account, g)} for g in top[:3] if g]
        slot_caps = {}
        notes.append(f'Coherence reserve per slot: ${COHERENCE_RESERVE_USD:.2f} held back from polish retries.')
        for idx, account in enumerate(accounts):
            before = budget.spent()
            later = sum(1 for a in accounts[idx + 1:] if a in funded)
            # v9: every later slot keeps the base need (stance + compose + 1 regen at observed p90 cost +
            # reservation headroom); this slot may use the rest (first-come shared pool for a backup
            # stance / extra regen). Slots the plan cannot fund are error rows, never silent starvation.
            left = max(0.0, cap - before)
            slot_cap = round(max(min(left, plan['base_need_usd']), left - plan['base_need_usd'] * later), 6)
            slot_cap = slot_cap if account in funded else 0.0   # v10b: no-candidate / unfunded slots need $0
            slot_caps[account] = slot_cap
            result = None
            try:
                budget.set_cap(min(cap, before + slot_cap))
                budget.set_advisory_hold(COHERENCE_RESERVE_USD)
                if account in no_candidate:   # zero need; never consumes funding
                    result = no_candidate_result(account, selection.get(account))
                    notes.append(f"{account}: {result['error']}")
                elif account not in funded:
                    result = error_result(account, 'unfunded', f'Budget plan: cap ${cap:.2f} funds '
                                          f'{plan["slots_funded"]} of {len(candidates)} candidate slots at '
                                          f'${plan["base_need_usd"]:.2f} base need; slot not attempted.')
                elif client:
                    result = run_slot(account, out, client, selected, backups, selection, batch_shapes,
                                      len(batch_shapes) + (len(accounts) - idx), notes)
                else:
                    result = fake_result(account, ViewLedger(account, out / 'views' / account), reason)
            except Exception as exc:   # v9 crash-proof: any slot exception is an explicit error row
                result = error_result(account, 'exception', f'{type(exc).__name__}: {str(exc)[:200]}')
                notes.append(account + ': slot error ' + result['error'])
            finally:
                budget.set_advisory_hold(0.0)
                budget.set_cap(cap)
            result.setdefault('pack_balance', compose.pack_balance(result.get('units') or []))
            result.setdefault('post_checks', [])
            result['ledger_findings'] = (result.get('stance') or {}).get('ledger_findings') or []
            result['publishable'] = False
            result['spend_usd'] = round(budget.spent() - before, 6)
            result['slot_cap_usd'] = slot_cap
            result['coherence_reserve_usd'] = COHERENCE_RESERVE_USD
            results.append(result)
    except Exception as exc:   # v9: batch-level failure still writes SUMMARY / arbitration below
        notes.append(f'BATCH ERROR {type(exc).__name__}: {str(exc)[:200]}')
    finally:
        _write_outputs(out, cap, command, skipped, notes, results, carried, plan)
    return results


def _write_outputs(out, cap, command, skipped, notes, results, carried, plan):
    """v9: always runs (try/finally). Each step is guarded so one failure never hides the rest."""
    errors = []
    def guard(name, fn):
        try:
            return fn()
        except Exception as exc:
            errors.append(f'{name}: {type(exc).__name__}: {str(exc)[:160]}')
            return None
    from live import compose_shapes
    structure = guard('structure', lambda: compose_shapes.batch_findings(
        [r for r in results if r.get('mode') != 'error'] + carried))
    if structure is not None:
        guard('structure_write', lambda: write_json(out / 'structure.json', structure))
    # default soft; FD_ARBITRATION=off disables. v8: fill-ins arbitrate with the batch they complete.
    arbitrated = guard('arbitration', lambda: arbitrate_with_carried(results, carried))
    if arbitrated is not None:
        results[:] = arbitrated
    synthetic = []
    if not any((r.get('arbitration') or {}).get('status') == 'HOLD' for r in results):
        synthetic = guard('synthetic_example', lambda: compose.arbitrate_batch([
            fake_result(a, ViewLedger(a, out / 'synthetic_example_views'),
                        'Synthetic arbitration example only.')
            for a in ('zh_macro', 'en_macro')], mode='soft')) or []
        if synthetic:
            guard('synthetic_write', lambda: write_json(out / 'synthetic_arbitration_example.json', synthetic))
    for result in results:
        guard('draft_' + str(result.get('account_id')),
              lambda result=result: write_json(out / 'drafts' / (str(result.get('account_id')) + '.json'), result))
    decisions = {(r.get('key') or r.get('account_id')): r.get('arbitration', {'status': 'NO_CANDIDATE'}) for r in results}
    guard('arbitration_write', lambda: write_json(out / 'arbitration.json', decisions))
    live_n = sum(1 for r in results if r.get('mode') == 'live' and (r.get('body') or r.get('text')))
    lines = ['# Matrix compose demo', '', 'publishable=false / human review only', '',
             f'Command: `{command}`', f'Spend USD: ${budget.spent():.6f} / cap ${cap:.2f} (includes probes and failed calls).',
             f'Live drafts: {live_n}/{len(results)}; '
             f'errors: {sum(1 for r in results if r.get("mode") == "error" or r.get("error_kind"))}; '
             f'synthetic: {sum(1 for r in results if r.get("synthetic"))}',
             f'Skipped disabled accounts: {", ".join(skipped) or "none"}', '']
    tripped = relay_quota_tripped()
    if tripped:
        lines += ['**FAIL LOUD — provider quota exhausted** (relay answered insufficient quota; every later call of the '
                  'stage went straight to its documented fallback; a top-up is needed before the next batch):', '']
        lines += [f'- {stage} / {model}: {why}' for (stage, model), why in sorted(tripped.items())] + ['']
    if plan:
        lines += ['## Budget plan', ''] + plan_lines(plan) + ['']
    lines += [*notes, '']
    for r in results:
        try:
            stance = r.get('stance') or {}
            text = r.get('text') or stance.get('account_view') or ''
            first = next((line.strip() for line in text.splitlines() if line.strip()), '(no judgment; see draft status)')
            continuity = {k: stance[k] for k in ('continues_view_id', 'revises_view_id') if stance.get(k)}
            if r.get('ledger_findings'):
                continuity['ledger_findings'] = r['ledger_findings']
            note = json.dumps(continuity, ensure_ascii=False) if continuity else (
                'no prior views (day-1)' if not r.get('ledger_prior_count') else
                'prior views exist; no continuity link (inspect stance)')
            lines += [f'## {r.get("account_id")} ({r.get("mode")})', '', f'Judgment first line: {first}',
                      'pack_balance: ' + json.dumps(r.get('pack_balance'), ensure_ascii=False),
                      'Ledger continuity: ' + note,
                      'Arbitration: ' + json.dumps(r.get('arbitration', {'status': 'NO_CANDIDATE'})),
                      'Shape: ' + json.dumps({k: (r.get('composition_shape') or {}).get(k) for k in ('id', 'ending', 'length', 'skeleton')}, ensure_ascii=False),
                      f'Spend USD: ${float(r.get("spend_usd") or 0):.6f}',
                      f'Draft status: {r.get("draft_status")}; publishable=false / human review only',
                      'Fallback: ' + str(r.get('fallback_reason', 'none'))]
            funnel = r.get('funnel') or (r.get('selection') or {}).get('funnel')
            lines += (['Selection funnel: ' + json.dumps(funnel, ensure_ascii=False)] if funnel else []) + ['']
        except Exception as exc:
            errors.append(f'summary_row: {type(exc).__name__}: {exc}')
    if synthetic:
        lines += ['## Synthetic arbitration example', '',
                  '**Synthetic, not model output or corpus evidence.** Same conclusion, shared source.', '']
        lines += [f'{r["account_id"]}: {r["arbitration"]["status"]} — {r["arbitration"].get("reason_code") or "keeper"}' for r in synthetic]
    elif any(r.get('synthetic') for r in results):
        lines += ['WRITE/HOLD examples above include labeled synthetic drafts; they do not measure writing quality.']
    if errors:
        lines += ['', '## Output errors', ''] + errors
    (out / 'SUMMARY.md').write_text('\n'.join(lines) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('/workspace/x/demo_matrix_oct6'))
    parser.add_argument('--cap', type=float, default=2.5,
                        help='batch cap USD (v9 default 2.5 = 4 base slots + 1 shared backup; full guarantee ~3.1)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry', action='store_true')
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--continue-from', type=Path, default=None,
                        help='previous batch dir: reuse its draft history + view ledgers, exclude its sources')
    parser.add_argument('--fill-into', type=Path, default=None,
                        help='batch dir this run completes (missing slot): arbitrate with its drafts')
    parser.add_argument('--accounts', default=None,
                        help='comma-separated subset of ' + ','.join(ACCOUNTS) + ' (e.g. a ZH-only round)')
    args = parser.parse_args(argv)
    if not math.isfinite(args.cap) or not 0 < args.cap <= 4:
        parser.error('--cap must be finite, positive and at most $4')
    if args.cap > 2.5:
        print(f'NOTE: --cap ${args.cap:.2f} exceeds the $2.50 per-batch guideline', file=sys.stderr)
    for flag, path in (('--continue-from', args.continue_from), ('--fill-into', args.fill_into)):
        if path is not None and not (path / 'drafts').is_dir():
            parser.error(f'{flag} {path}: not a finished batch dir (no drafts/); refusing to run '
                         'with an empty chain (v9a first attempt silently started fresh)')
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
    only = [a.strip() for a in args.accounts.split(',') if a.strip()] if args.accounts else None
    if only and set(only) - set(ACCOUNTS):
        parser.error('--accounts must be a subset of ' + ','.join(ACCOUNTS))
    run(args.out, args.cap, live=args.live, command=command, continue_from=args.continue_from, only_accounts=only,
        fill_into=args.fill_into)
    print(args.out / 'SUMMARY.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
