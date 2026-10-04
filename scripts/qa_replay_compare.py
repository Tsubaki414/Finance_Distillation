"""Offline QA rescore of recorded COMPOSE samples (no model calls).

Each <dir>/<run>/compose.json holds a recorded draft (body, units, frame,
post_type, licence tier). The current code's post checks are re-run on it and
the draft status recomputed, so a QA change can be compared on identical
drafts. Prints one row per sample plus the draft_ready rate.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def rescore(result):
    from live import compose, registry
    persona = registry.persona_for_account(result['account_id'])
    post_types = registry.load_post_types()
    findings = compose.post_checks(result['post_type'], result['body'], result['text'],
                                   result['attribution_frame'], result['licence_tier'],
                                   result['units'], persona, post_types)
    try:
        from live import qa_levels
        status = qa_levels.draft_status(findings)
    except ImportError:  # before two-level QA every finding blocked
        status = 'draft_ready' if not findings else 'needs_review'
    return status, findings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dirs', nargs='+', type=Path)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    rows = []
    for d in args.dirs:
        for path in sorted(d.glob('run-*/compose.json')):
            result = json.loads(path.read_text())
            if not result.get('body'):
                rows.append({'sample': f'{d.name}/{path.parent.name}', 'draft_status': result.get('draft_status'),
                             'skipped': True})
                continue
            status, findings = rescore(result)
            rows.append({'sample': f'{d.name}/{path.parent.name}', 'account': result['account_id'],
                         'source_id': result.get('source_id'), 'post_type': result['post_type'],
                         'draft_status': status,
                         'hard': sorted({f['code'] for f in findings if f.get('level', 'hard') == 'hard'}),
                         'soft': sorted({f['code'] for f in findings if f.get('level') == 'soft'}),
                         'findings': findings})
            print(json.dumps({k: v for k, v in rows[-1].items() if k != 'findings'}, ensure_ascii=False))
    scored = [r for r in rows if not r.get('skipped')]
    ok = sum(r['draft_status'] == 'draft_ready' for r in scored)
    print(json.dumps({'draft_ready': ok, 'scored': len(scored), 'skipped': len(rows) - len(scored)}))
    if args.out:
        args.out.write_text(json.dumps({'rows': rows, 'draft_ready': ok, 'scored': len(scored)},
                                       ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
