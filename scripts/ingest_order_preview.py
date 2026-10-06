"""Dry-run preview of the next ingest's extract order (Oct 6 v8). No fetch, no LLM call.

Uses the previous run's deferred list as the candidate set (tomorrow's gather will add new items
on top; those rank after prior-deferred ones in every persona) and its fresh_by_persona_after.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import ingest_priority  # noqa: E402
from live.daily_ingest import priority  # noqa: E402


def preview(summary_path, *, cap=None, per_extract=None, floor=2, flash_budget_usd=1.75, usd_per_flash=None,
            flash_dry_run=None):
    data = json.loads(Path(summary_path).read_text())
    fresh = data.get('fresh_by_persona_after') or data.get('fresh_by_persona_before') or {}
    cap = float(cap if cap is not None else (data.get('cost_usd') or {}).get('cap', 8.0))
    extracted = next((s.get('extracted') for s in data.get('steps') or [] if s.get('id') == 'extract'), None)
    relay = float((data.get('cost_usd') or {}).get('relay') or 0)
    per = float(per_extract or (relay / extracted if extracted else 0.83))
    # v10: flashes run first on their ring-fenced budget; documents get the rest of the cap (plus any
    # flash budget left unused, which rolls over - not counted here, so this is the conservative fit).
    flash = None
    if flash_budget_usd:
        fd = json.loads(Path(flash_dry_run).read_text()).get('flashes') if flash_dry_run else None
        n = (fd or {}).get('selected')
        est = round(n * usd_per_flash, 3) if (n is not None and usd_per_flash) else None
        flash = dict(budget_usd=float(flash_budget_usd), selected=n, usd_per_flash=usd_per_flash,
                     est_cost_usd=est, est_rollover_to_docs_usd=round(flash_budget_usd - est, 2) if est is not None else None,
                     outlets=(fd or {}).get('outlets'), duplicates=(fd or {}).get('duplicates'),
                     overflow_flash_max=(fd or {}).get('overflow_flash_max'), preview=(fd or {}).get('preview'))
    docs_cap = max(0.0, cap - float(flash_budget_usd or 0))
    fit = int(docs_cap // per) if per else 0
    ranks, tasks = Counter(), []
    for d in data.get('deferred') or []:
        ch = {'id': d['channel']}
        src = {'id': d['id'], 'source_id': d['channel'].split(':')[-1]}
        tasks.append((ch, src, None, d['channel'], [d['id']], ranks[d['channel']]))
        ranks[d['channel']] += 1
    ids = {d['id'] for d in data.get('deferred') or []}
    _, plan = ingest_priority.order_tasks(tasks, fresh, ids, floor=floor, legacy_priority=priority)
    legacy = sorted(tasks, key=lambda t: (priority(t[0]['id'], t[1]), t[5]))
    tim = {(t[0]['id'], t[1]['id']): ingest_priority.timeliness(t[0]['id'], t[1]) for t in tasks}
    for i, row in enumerate(plan):
        row['pos'] = i + 1
        row.setdefault('timeliness', tim.get((row['channel'], row['id'])))
        row['within_cap'] = i < fit
    covered = Counter(r['persona'] for r in plan if r['within_cap'])
    legacy_cov = Counter(ingest_priority.channel_personas(t[0]['id'], t[1])[0] for t in legacy[:fit])
    return dict(source=str(summary_path), cap_usd=cap, docs_cap_usd=round(docs_cap, 2), flashes=flash,
                usd_per_extract=round(per, 3), extracts_within_cap=fit,
                fresh_by_persona=fresh, floor=floor, plan=plan,
                personas_within_cap=dict(covered), legacy_personas_within_cap=dict(legacy_cov),
                legacy_first=[t[0]['id'] for t in legacy[:fit]],
                note='Candidate set = previous deferred list only; new items gathered tomorrow rank '
                     'after prior-deferred ones within each persona. No ingest was run.')


def to_md(p):
    lines = [f"# Ingest order preview (dry-run) — from {Path(p['source']).name}", '',
             f"cap ${p['cap_usd']:.2f} = flashes ${(p.get('flashes') or {}).get('budget_usd', 0):.2f} (ring-fenced, first) + "
             f"documents ${p.get('docs_cap_usd', p['cap_usd']):.2f}; ≈${p['usd_per_extract']}/extract → ~{p['extracts_within_cap']} "
             f"document extracts fit; fair-share floor {p['floor']}/persona. Order: timely → floor → rest → transcripts last.", '',
             'flashes: ' + json.dumps({k: v for k, v in (p.get('flashes') or {}).items() if k not in ('preview', 'outlets')},
                                      ensure_ascii=False), '',
             'fresh_by_persona: ' + json.dumps(p['fresh_by_persona'], ensure_ascii=False), '',
             '| # | phase | timeliness | persona (fresh) | channel | id | within cap |', '|---|---|---|---|---|---|---|']
    for r in p['plan']:
        lines.append(f"| {r['pos']} | {r['phase']} | {r.get('timeliness')} | {r['persona']} ({r['fresh']}) | {r['channel']} | {r['id']} | "
                     f"{'yes' if r['within_cap'] else ''} |")
    lines += ['', 'Personas within cap (new): ' + json.dumps(p['personas_within_cap'], ensure_ascii=False),
              'Personas within cap (legacy order): ' + json.dumps(p['legacy_personas_within_cap'], ensure_ascii=False),
              '', p['note']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--summary', type=Path, default=Path('/workspace/x/ingest_runs/20261006.json'))
    ap.add_argument('--out-json', type=Path, default=Path('/workspace/x/ingest_runs/preview_20261007.json'))
    ap.add_argument('--out-md', type=Path, default=Path('/workspace/x/ingest_runs/preview_20261007.md'))
    ap.add_argument('--floor', type=int, default=2)
    ap.add_argument('--flash-budget-usd', type=float, default=1.75)
    ap.add_argument('--usd-per-flash', type=float, default=None, help='measured cost per flash (live trial)')
    ap.add_argument('--flash-dry-run', type=Path, default=None, help='daily_ingest --dry-run summary JSON (flash gather)')
    args = ap.parse_args(argv)
    p = preview(args.summary, floor=args.floor, flash_budget_usd=args.flash_budget_usd,
                usd_per_flash=args.usd_per_flash, flash_dry_run=args.flash_dry_run)
    args.out_json.write_text(json.dumps(p, ensure_ascii=False, indent=1) + '\n')
    args.out_md.write_text(to_md(p))
    print(to_md(p))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
