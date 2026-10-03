"""Re-score stored cases with the current gate version. No regeneration.

Gate fixes must not require paying for new drafts. Each case keeps its original QA block under
`qa_history` so the effect of a gate change is auditable rather than silently overwritten.

Run: .venv/bin/python -B qa/rescore_cases.py [--dir=evidence_loop/experiments/cases_v2]
"""
from pathlib import Path
import sys, json, datetime, collections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa.gates import evaluate
from qa.status import classify


def main():
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    d = ROOT / args.get('dir', 'evidence_loop/experiments/cases_v2')
    packet = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
    must = packet['coverage']['required_core_ids']
    allowed = {f['id'] for f in packet['facts']}

    changed, summary = [], collections.Counter()
    for p in sorted(d.glob('*.json')):
        c = json.loads(p.read_text())
        if not c.get('sentence_to_source_ledger'):
            continue
        before = (c.get('qa') or {}).get('status', {}).get('blocking_count')
        plan_req = [x for x in ((c.get('analysis_plan') or {}).get('evidence_to_compare') or [])
                    if x in allowed]
        qa = evaluate({'sentence_to_source_ledger': c['sentence_to_source_ledger']},
                      packet, must_include=must, plan_required=plan_req)
        hist = c.get('qa_history', [])
        if c.get('qa'):
            hist.append({'gate_version': c['qa'].get('gate_version'),
                         'blocking_count': before,
                         'archived_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         'findings': c['qa'].get('findings', [])})
        c.update(qa=qa, qa_history=hist,
                 qa_status=qa['status']['qa_status'],
                 content_status=qa['status']['content_status'],
                 rescored_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        c['delivery'] = classify(c)
        c['classification'] = ('smoke_candidate' if c['delivery']['deliverable']
                               else 'qa_blocked_smoke_case')
        p.write_text(json.dumps(c, ensure_ascii=False, indent=2))
        after = qa['status']['blocking_count']
        summary[qa['status']['content_status']] += 1
        changed.append({'id': c['id'], 'condition': c['condition'], 'persona': c['persona_id'],
                        'blocking_before': before, 'blocking_after': after,
                        'codes': sorted({f['code'] for f in qa['findings']
                                         if f['severity'] == 'blocking'})})

    print(json.dumps({'rescored': len(changed), 'content_status': dict(summary)},
                     ensure_ascii=False))
    for c in changed:
        print(f"  {c['condition']:28} {c['persona']:9} {c['blocking_before']:>2} -> "
              f"{c['blocking_after']:<2} {c['codes']}")
    return changed


if __name__ == '__main__':
    main()
