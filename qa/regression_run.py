"""Replay the frozen S1 draft through the seven-layer gates.

S1 is never modified. This writes a separate regression run so the question "would the gates have
caught what a human found" is answered with evidence rather than assertion.

Run: .venv/bin/python -B qa/regression_run.py
"""
from pathlib import Path
import sys, json, datetime, hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa.gates import evaluate

CASE = ROOT / 'evidence_loop/experiments/cases/case-a29c6b6c0325.json'
PACKET = ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json'
OUT = ROOT / 'qa/runs'

# The manual audit findings, mapped to the gate expected to catch each one.
EXPECTED = {
    'H1': ('numeric_magnitude', 2, 'revision_previous written as 0.44 万 instead of 4.4 万'),
    'H2': ('out_of_evidence_assertion', 3, 'consensus comparison with no consensus source'),
    'H3': ('citation_relation_mismatch', 4, 'change asserted, level fact cited'),
    'H4': ('clause_attribution', 6, 'overall 12m mean attached to a sector'),
    'H5': ('must_include_missing', 5, 'mandatory facts absent from the draft'),
}


def main():
    case = json.loads(CASE.read_text())
    packet = json.loads(PACKET.read_text())
    source = (ROOT / 'evidence_loop' / packet['artifact_path']).read_text()
    before = hashlib.sha256(CASE.read_bytes()).hexdigest()

    must = packet.get('coverage', {}).get('required_core_ids') or []
    result = evaluate(case, packet, source_text=source, must_include=must)

    got = {}
    for code, layer, why in EXPECTED.values():
        got[code] = [f for f in result['findings'] if f['code'] == code]
    coverage = {k: {'code': v[0], 'layer': v[1], 'human_finding': v[2],
                    'caught': bool(got[v[0]]),
                    'gate_detail': (got[v[0]][0].get('detail') if got[v[0]] else None),
                    'sentence': (got[v[0]][0].get('sentence_id') if got[v[0]] else None)}
                for k, v in EXPECTED.items()}

    after = hashlib.sha256(CASE.read_bytes()).hexdigest()
    run_id = 'qa-reg-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')
    payload = {
        'run_id': run_id,
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'parent_case': case['id'],
        'parent_case_untouched': before == after,
        'parent_case_sha256': after,
        'input': 'frozen S1 sentence ledger and the real fact packet, unchanged',
        'gate_version': result['gate_version'],
        'layers_run': result['layers_run'],
        'status': result['status'],
        'metrics': result['metrics'],
        'human_finding_coverage': coverage,
        'caught': sum(1 for v in coverage.values() if v['caught']),
        'expected': len(coverage),
        'findings': result['findings'],
        'note': ('S1 keeps run_status=completed, qa_status=failed, content_status=blocked and '
                 'classification=qa_failed_regression_case. This run is a separate artifact.'),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (run_id + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    (OUT / 'latest.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"run {run_id}")
    print(f"parent case untouched: {payload['parent_case_untouched']}")
    print(f"status: {result['status']['qa_status']} / {result['status']['content_status']} "
          f"({result['status']['blocking_count']} blocking)")
    print(f"human findings reproduced by gates: {payload['caught']}/{payload['expected']}")
    for k, v in coverage.items():
        mark = 'CAUGHT' if v['caught'] else 'MISSED'
        print(f"  {k} L{v['layer']:<2} {mark:7} {v['code']}")
        if v['caught']:
            print(f"        {str(v['gate_detail'])[:110]}")
    return payload


if __name__ == '__main__':
    main()
