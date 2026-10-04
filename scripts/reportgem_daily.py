"""ReportGem daily pull (content donor): listing -> Jev pre-screen -> evidence -> tier-B sources -> EXTRACT.

By default this script replays recorded MCP
responses from <run>/responses/<key>.json and writes every call it still needs
to <run>/plan.json (tool, args, key). Re-run after the plan's calls have been
recorded. Points are read from each response's mcp_usage; --cap stops calls.
With --transport http, REPORTGEM_MCP_URL and REPORTGEM_MCP_TOKEN enable live
streamable HTTP calls; every result is saved in the same replay directory.

  python scripts/reportgem_daily.py --run /workspace/x/reportgem/2026-10-04 --day 2026-10-04 --cap 15
  python scripts/reportgem_daily.py ... --extract   # EXTRACT top sources via the relay (tier B units)
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import reportgem_daily as rg  # noqa: E402

PERSONAS = list(rg.THEMES)


def replay(run):
    responses = {}
    for path in (run / 'responses').glob('*.json'):
        responses[path.stem] = json.loads(path.read_text())

    def call(tool, args):
        key = rg.call_key(tool, args)
        if key not in responses:
            raise rg.Unrecorded(tool, args)
        return responses[key]
    return call


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--day', required=True)
    ap.add_argument('--cap', type=float, default=40.0)
    ap.add_argument('--limit', type=int, default=6)
    ap.add_argument('--per-persona', type=int, default=3)
    ap.add_argument('--max-top', type=int, default=30)
    ap.add_argument('--passages', type=int, default=2)
    ap.add_argument('--no-jev', action='store_true')
    ap.add_argument('--transport', choices=('replay', 'http'), default='replay')
    ap.add_argument('--extract', action='store_true')
    ap.add_argument('--partial', action='store_true', help='extract recorded sources even if planned calls remain (agent-relay runs)')
    args = ap.parse_args()
    (args.run / 'responses').mkdir(parents=True, exist_ok=True)
    recorded = replay(args.run)
    if args.transport == 'http':
        from live.reportgem_mcp_http import ReportGemHTTP
        try:
            call = ReportGemHTTP(run=args.run)
        except ValueError as exc:
            ap.exit(2, str(exc) + '\n')
    else:
        call = recorded
    plan = []
    budget = rg.Points(args.cap, per_call_estimate=0.6)
    items = rg.daily_listing(call, rg.listing_queries(PERSONAS, day=args.day, limit=args.limit),
                             day=args.day, budget=budget, plan=plan)
    listing_points = budget.spent
    scores, top, sources = {}, [], []
    report = {'day': args.day, 'listing_items': len(items), 'items': [
        {k: i.get(k) for k in ('source_id', 'source_type', 'bank', 'published_at', 'title', 'query')} for i in items]}
    if plan:
        report['stage'] = 'listing'
    else:
        jev = None
        if not args.no_jev:
            from live.jev_review_client import JevReviewClient
            from ml import budget as spend
            spend.STORE = args.run / 'ledger'
            spend.LEDGER = spend.STORE / 'spend.json'
            jev = JevReviewClient(args.run / 'jev_calls')
        cached = args.run / 'prescreen.json'
        if cached.exists():
            scores = json.loads(cached.read_text())
        if not cached.exists():
            scores = rg.prescreen(items, PERSONAS, jev=jev)
            cached.write_text(json.dumps(scores, ensure_ascii=False, indent=1))
        by_id = {str(i['source_id']): i for i in items}
        rejected = set()
        for sid, it in by_id.items():  # recorded evidence already known to be unusable -> pick the next item
            args_ev = {'source_type': it['source_type'], 'source_id': sid, 'query': it['title'][:300], 'max_passages': args.passages}
            try:
                ev = recorded('get_evidence', args_ev)
            except rg.Unrecorded:
                continue
            if rg.screen_evidence(it, ev):
                rejected.add(sid)
        excluded = sorted(sid for sid, i in by_id.items() if rg.is_rating_call(i) or sid in rejected)
        top = rg.select_top(scores, items=by_id, per_persona=args.per_persona, max_total=args.max_top, exclude=excluded)
        report.update(prescreen_method=scores['_method'], prescreen={p: s for p, s in scores.items() if not p.startswith('_')},
                      top=[{'persona': p, 'source_id': sid} for p, sid in top])
        report['rejected_recorded'] = sorted(rejected)
        budget.estimate = 0.2
        evidence_cache = {}
        for persona, sid in top:
            it = by_id[sid]
            if sid not in evidence_cache:
                evidence_cache[sid] = rg._call(call, 'get_evidence', {'source_type': it['source_type'], 'source_id': sid,
                                                  'query': it['title'][:300], 'max_passages': args.passages}, budget, plan)
            ev = evidence_cache[sid]
            flags = rg.screen_evidence(it, ev) if ev else []
            if flags:
                report.setdefault('rejected', []).append({'source_id': sid, 'title': it['title'], 'flags': flags})
            src = rg.to_source(it, ev) if ev else None
            if src:
                sources.append({'persona': persona, 'source': src})
        report['stage'] = 'evidence' if plan else 'sources'
        report['sources'] = [{'persona': s['persona'], 'id': s['source']['id'], 'source_id': s['source']['source_id'],
                              'title': s['source']['title'], 'chars': len(s['source']['original_text'])} for s in sources]
        (args.run / 'sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=1))
        if args.extract and (not plan or args.partial):
            from live import content_units, registry
            from live.erisedai_distillation_client import ErisedaiClient
            from ml import budget as spend
            spend.STORE = args.run / 'ledger'
            spend.LEDGER = spend.STORE / 'spend.json'
            client = ErisedaiClient(args.run / 'extract_calls')
            report['units'] = []
            for s in sources:
                src = s['source']
                tier = registry.source_licence_tier(src['source_id'])
                done = args.run / f'units_{src["id"]}.json'
                try:
                    if done.exists():  # resume: never pay twice for the same source
                        out = json.loads(done.read_text())
                    else:
                        out = content_units.extract(src, client, licence_tier=tier, publisher=src['publisher'])
                        done.write_text(json.dumps(out, ensure_ascii=False, indent=1))
                    stored = rg.store_units(src, out['units'], s['persona'], jev=jev)
                    report['units'].append({'store': stored, 'id': src['id'], 'persona': s['persona'], 'tier': tier, 'units': stored['kept'],
                                            'dropped': len(out['dropped_units']),
                                            'usage': sorted({u['usage'] for u in out['units']})})
                except Exception as exc:
                    report['units'].append({'id': src['id'], 'persona': s['persona'], 'error': f'{type(exc).__name__}: {str(exc)[:160]}'})
    report['personas'] = {}
    queries_by_persona = {p: {q['query'] for q in rg.listing_queries([p], day=args.day, limit=args.limit)} for p in PERSONAS}
    for p in PERSONAS:
        chosen = scores.get(p, {})
        report['personas'][p] = {
            'listed_items': sum(bool(set(i.get('queries', [i['query']])) & queries_by_persona[p]) for i in items),
            'prescreen_strong': sum(c == 'strong' for c in chosen.values()),
            'prescreen_weak': sum(c == 'weak' for c in chosen.values()),
            'selected_reports': sum(persona == p for persona, _ in top),
            'sources': sum(s['persona'] == p for s in sources),
            'units': sum(u.get('units', 0) for u in report.get('units', []) if u.get('persona') == p),
        }
    report['points'] = {'listing_points': listing_points, 'evidence_points': budget.spent - listing_points,
                        'total': budget.spent}
    report['projection'] = rg.projection(budget.spent)
    report['points_cap_stopped'] = budget.stopped
    if args.transport == 'http':
        call.close()
    report['points_spent'] = round(budget.spent, 4)
    report['mcp_calls_replayed'] = budget.calls
    report['plan'] = plan
    (args.run / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    (args.run / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k not in ('items', 'prescreen', 'plan')}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
