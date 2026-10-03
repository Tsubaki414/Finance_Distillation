"""P0-4c data check: frame vs no frame on a stored zh_industry run.

Reads the run's selected passages and localization segments, renders the
mechanism_explainer frame for its source, and prints deterministic finding
codes for: A) no frame, B) frame prepended and declared. Paragraph checks
(fidelity + domain policy) and the post-level check are both reported.
Read-only; no model calls.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('--post-type', default='mechanism_explainer')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    from live import attribution_frame as af, domain_policy, fidelity, registry
    from live.distillation_source import detect_language
    run = json.loads(args.run.read_text())
    attempt = run['source_adaptation']['attempt']
    source = attempt['source']
    passages = attempt['selection']['passages']
    segments = attempt['localization']['segments']
    frame = af.render(args.post_type, source)
    framed = [dict(s) for s in segments]
    if frame['placement'] == 'lead':
        framed[0]['text'] = frame['text'] + framed[0]['text']
    else:
        framed[-1]['text'] = framed[-1]['text'] + frame['text']
    tier = registry.source_licence_tier(source['source_id'])
    report = {'run': run['id'], 'source_id': source['source_id'], 'licence_tier': tier,
              'post_type': args.post_type, 'frame': frame}
    for case, segs, fr in (('A_no_frame', segments, None), ('B_frame', framed, frame)):
        para = fidelity.deterministic(source, passages, segs, 'zh', 'localization', detect_language, frame=fr)
        policy = domain_policy.FINANCE.deterministic(source, passages, segs, 'zh', 'localization', detect_language, frame=fr)
        post = af.check(args.post_type, '\n\n'.join(s['text'] for s in segs), fr, tier)
        report[case] = {'fidelity_codes': sorted({r['code'] for r in para}),
                        'policy_codes': sorted({r['code'] for r in policy}),
                        'post_codes': sorted({r['code'] for r in post})}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
