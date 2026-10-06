#!/usr/bin/env python3
"""Four matrix drafts, direct evidence -> stance -> compose; human review only.

Defaults to dry mode. Pass --live to probe relays and compose under a hard
ledger cap. Failed/missing live slots receive explicitly synthetic drafts.
No account configuration or production view/history ledger is written.
"""
from __future__ import annotations

import argparse
import json
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
from live import anti_repeat, compose, registry
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


def select_groups(store, accounts, selection=None):
    """Pick one balanced (view + fact) packet per account; ZH prefers its OWN source.

    Oct 6 v2: sharing the EN source made both ZH slots HOLD (same conclusion, same source).
    Order per pair: EN takes its best balanced packet; ZH takes its best balanced packet from a
    DIFFERENT source (ZH-native first). Only when ZH has no other balanced packet does it share
    EN's source, and then only with a differentiated angle: ZH keeps the views EN does not carry
    (slice must stay balanced). Without a different view the slice is kept as-is and marked
    ``shared_same_angle`` so claim arbitration can HOLD the genuine duplicate.
    ``selection`` (optional dict) receives {account: {'mode', 'source_id', ...}}.
    """
    selection = {} if selection is None else selection
    grouped = {}
    for account in accounts:
        groups = {}
        for record in units_for_persona(store, account, max_age_days=45):
            if record.get('licence_tier') not in ('A', 'B'):
                continue
            groups.setdefault(_key(record), []).append(record)
        grouped[account] = groups

    def ranked(account, exclude=()):
        return [g for g in rank_evidence_groups(
            [g for k, g in grouped[account].items() if k not in exclude]) if balanced(g)]

    def note(account, mode, group, **extra):
        selection[account] = {'mode': mode, 'source_id': group[0]['source'].get('id') if group else None,
                              'zh_native': zh_native(group) if group else False, **extra}

    chosen = {}
    for zh, en in (('zh_macro', 'en_macro'), ('zh_industry', 'en_industry')):
        en_group = []
        if en in grouped:
            options = ranked(en)
            en_group = options[0] if options else []   # no balanced packet -> skip, never pure_data
            chosen[en] = en_group
            note(en, 'own' if en_group else 'none', en_group)
        if zh not in grouped:
            continue
        en_key = _key(en_group[0]) if en_group else None
        own = ranked(zh, exclude={en_key} if en_key else ())
        own.sort(key=lambda g: not zh_native(g))   # stable: ZH-native sources first
        if own:
            chosen[zh] = own[0]
            note(zh, 'own_zh_native' if zh_native(own[0]) else 'own_different_source', own[0])
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
            note(zh, 'shared_differentiated', differentiated, dropped_view_ids=sorted(en_views & _view_ids(shared)))
        else:
            chosen[zh] = shared
            note(zh, 'shared_same_angle', shared, reason='no own balanced source and no view EN lacks; '
                 'arbitration decides (genuine duplicate -> HOLD)')
    for account in accounts:   # any account outside the two pairs: own best packet
        if account not in chosen:
            options = ranked(account)
            chosen[account] = options[0] if options else []
            note(account, 'own' if chosen[account] else 'none', chosen[account])
    return chosen


def fake_result(account, ledger, reason, *, record=True):
    """Synthetic evidence and claims, never represented as corpus/model output."""
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


def judgment_type(account):
    mix = registry.persona_for_account(account).post_type_mix
    for name in ('judgment_take', *mix):
        if name in mix and name in ('judgment_take', 'contrarian_take', 'view_relay'):
            return name
    raise ValueError('No judgment-capable post type for ' + account)


def run(out, cap, *, live=False, command=''):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    budget.STORE = out / 'ledger'
    budget.LEDGER = budget.STORE / 'spend.json'
    budget.RUNS = budget.STORE / 'review_runs.jsonl'
    budget.DISTILLATION_RUNS = budget.STORE / 'distillation_spend.jsonl'
    # Reuse existing spending/reservations instead of resetting an existing ledger.
    budget.set_cap(cap)
    anti_repeat.HISTORY_DIR = out / 'history'
    anti_repeat.FALLBACK_DIR = out / 'history'
    rows = {a['id']: a for a in json.loads((ROOT / 'live/accounts.json').read_text())['accounts']}
    accounts = [a for a in ACCOUNTS if rows.get(a, {}).get('enabled')]
    skipped = [a for a in ACCOUNTS if a not in accounts]
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
    selected = select_groups(ContentStore(compose_ab.STORE), accounts, selection) if client else {}
    if selection:
        notes.append('Selection: ' + json.dumps({a: v['mode'] for a, v in selection.items()}, ensure_ascii=False))
    results = []
    for account in accounts:
        ledger = ViewLedger(account, out / 'views' / account)
        before = budget.spent()
        result = None
        if client:
            group = selected.get(account) or []
            if not group:
                reason = 'No eligible tagged evidence within 45 days.'
            else:
                try:
                    source, units = evidence_source(group)
                    prior_count = len(ledger.current())
                    result = compose.compose_source(
                        source, account, client, post_type=judgment_type(account),
                        extracted_units=units, exemplar_dir=compose_ab.POSTS,
                        exemplar_tags_dir=compose_ab.TAGS, view_ledger=ledger)
                    result.update(key=account, source=source, mode='live',
                                  stored_unit_ids=[r['unit_id'] for r in group],
                                  ledger_prior_count=prior_count, selection=selection.get(account))
                except budget.BudgetExceeded:
                    reason = 'BudgetExceeded: live composes stopped before sending the refused call.'
                    notes.append(reason)
                    client = None
                except Exception as exc:
                    reason = f'Live compose failed: {type(exc).__name__}; slot synthetic.'
                    notes.append(account + ': ' + reason)
        if result is None:
            result = fake_result(account, ledger, reason)
        result.setdefault('pack_balance', compose.pack_balance(result.get('units') or []))
        result.setdefault('post_checks', [])
        result['ledger_findings'] = (result.get('stance') or {}).get('ledger_findings') or []
        result['publishable'] = False
        result['spend_usd'] = round(budget.spent() - before, 6)
        results.append(result)
    results = compose.arbitrate_batch(results)   # default soft; FD_ARBITRATION=off disables
    synthetic = []
    if not any(r.get('arbitration', {}).get('status') == 'HOLD' for r in results):
        synthetic = compose.arbitrate_batch([
            fake_result(a, ViewLedger(a, out / 'synthetic_example_views'),
                        'Synthetic arbitration example only.', record=False)
            for a in ('zh_macro', 'en_macro')], mode='soft')
        write_json(out / 'synthetic_arbitration_example.json', synthetic)
    for result in results:
        write_json(out / 'drafts' / (result['account_id'] + '.json'), result)
    decisions = {r['key']: r.get('arbitration', {'status': 'NO_CANDIDATE'}) for r in results}
    write_json(out / 'arbitration.json', decisions)
    lines = ['# Matrix compose demo', '', 'publishable=false / human review only', '',
             f'Command: `{command}`', f'Spend USD: ${budget.spent():.6f} / cap ${cap:.2f} (includes probes and failed calls).',
             f'Skipped disabled accounts: {", ".join(skipped) or "none"}', '', *notes, '']
    for r in results:
        stance = r.get('stance') or {}
        text = r.get('text') or stance.get('account_view') or ''
        first = next((line.strip() for line in text.splitlines() if line.strip()), '(no judgment; see draft status)')
        continuity = {k: stance[k] for k in ('continues_view_id', 'revises_view_id') if stance.get(k)}
        if r['ledger_findings']:
            continuity['ledger_findings'] = r['ledger_findings']
        note = json.dumps(continuity, ensure_ascii=False) if continuity else (
            'no prior views (day-1)' if not r.get('ledger_prior_count') else
            'prior views exist; no continuity link (inspect stance)')
        lines += [f'## {r["account_id"]} ({r["mode"]})', '', f'Judgment first line: {first}',
                  'pack_balance: ' + json.dumps(r['pack_balance'], ensure_ascii=False),
                  'Ledger continuity: ' + note,
                  'Arbitration: ' + json.dumps(r.get('arbitration', {'status': 'NO_CANDIDATE'})),
                  f'Spend USD: ${r["spend_usd"]:.6f}',
                  f'Draft status: {r["draft_status"]}; publishable=false / human review only',
                  'Fallback: ' + r.get('fallback_reason', 'none'), '']
    if synthetic:
        lines += ['## Synthetic arbitration example', '',
                  '**Synthetic, not model output or corpus evidence.** Same conclusion, shared source.', '']
        lines += [f'{r["account_id"]}: {r["arbitration"]["status"]} — {r["arbitration"].get("reason_code") or "keeper"}' for r in synthetic]
    elif any(r.get('synthetic') for r in results):
        lines += ['WRITE/HOLD examples above include labeled synthetic drafts; they do not measure writing quality.']
    (out / 'SUMMARY.md').write_text('\n'.join(lines) + '\n')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('/workspace/x/demo_matrix_oct6'))
    parser.add_argument('--cap', type=float, default=2.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry', action='store_true')
    mode.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    if not math.isfinite(args.cap) or not 0 < args.cap <= 2:
        parser.error('--cap must be finite, positive and at most $2')
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
    run(args.out, args.cap, live=args.live, command=command)
    print(args.out / 'SUMMARY.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
