"""Re-run current draft QA offline on voice_check results; never call an LLM."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import compose, registry, qa_levels


def requalify(results):
    rows = []
    for group in results:
        for index, draft in enumerate(group.get('drafts', [])):
            stored = draft.get('compose')
            before = qa_levels.summary((stored or {}).get('post_checks', []))['hard']
            row = {'account_id': group.get('account_id'), 'draft': index + 1,
                   'hard_before': len(before), 'codes_before': before,
                   'hard_after': 0, 'codes_after': [], 'draft_status': 'needs_review'}
            body = (stored or {}).get('body')
            if not body and (stored or {}).get('text'):
                from live import attribution_frame
                body = attribution_frame.strip(stored['text'], stored.get('attribution_frame', stored.get('frame', {})))[0]
            if stored and body:
                account = stored.get('account_id') or (stored.get('persona') or {}).get('persona_id') or group['account_id']
                persona = registry.persona_for_account(account)
                findings = compose.post_checks(stored['post_type'], body, stored.get('text', body),
                    stored.get('attribution_frame', stored.get('frame', {})), stored['licence_tier'],
                    stored['units'], persona, registry.load_post_types(), stored.get('stance'), source=draft.get('source'))
                codes = qa_levels.summary(findings)
                row.update(hard_after=len(codes['hard']), codes_after=codes['hard'],
                           codes=codes, post_checks=findings, draft_status=qa_levels.draft_status(findings))
            else:
                row['reason'] = 'missing compose result'
            rows.append(row)
    publishable = sum(r['draft_status'] == 'draft_ready' for r in rows)
    return {'drafts': rows, 'total': len(rows), 'hard_before': sum(r['hard_before'] for r in rows),
            'hard_after': sum(r['hard_after'] for r in rows), 'publishable': publishable,
            'pass_rate': publishable / len(rows) if rows else 0.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = requalify(json.loads(args.results.read_text()))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'drafts'}))


if __name__ == '__main__':
    main()
