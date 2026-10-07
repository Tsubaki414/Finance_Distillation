#!/usr/bin/env python3
"""Apply an editorial audit to one day of the compose review inbox (Oct 7, fix26).

The audit file is {"day": ..., "reviewer": ..., "verdicts": {draft_id: [verdict, reason]}} with verdict keep /
rewrite / drop. Every audited row gets audit={verdict, reason, reviewer, at}. rewrite and drop rows are marked
superseded + held, so the ops page and `daily_compose.py --fill` stop counting them as ready; `--fill` may reuse the
source of a rewrite row for the same account. review_status (the human decision) is never touched, and nothing is
deleted.

  python scripts/apply_inbox_audit.py /workspace/x/cc_jobs/fix26/audit_2026-10-07.json
  python scripts/apply_inbox_audit.py --recheck 2026-10-07

--recheck re-runs live/editorial_style.py on the stored bodies after a rule change (see recheck()).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import compose_inbox, editorial_style  # noqa: E402

VERDICTS = ('keep', 'rewrite', 'drop')


def apply(audit, base=None):
    day = audit['day']
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    counts = dict.fromkeys(VERDICTS, 0)
    for draft_id, (verdict, reason) in audit['verdicts'].items():
        if verdict not in VERDICTS:
            raise ValueError(f'{draft_id}: verdict must be one of {VERDICTS}')
        path = Path(base or compose_inbox.root()) / day / f'{draft_id}.json'
        row = json.loads(path.read_text())
        row['audit'] = {'verdict': verdict, 'reason': reason, 'reviewer': audit.get('reviewer'), 'at': at}
        if verdict != 'keep':
            row['superseded'] = True
            row['held'] = True
            row['hold_reason'] = f'audit: {verdict}'
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n')
        counts[verdict] += 1
    return counts


def recheck(day, base=None):
    """Re-run live/editorial_style.py on the stored bodies after a rule change. Ready drafts that now trip a code
    are held (hold_reason 'hard: <codes>'); held drafts whose only HARD findings were style codes and that no longer
    trip one become ready again (not arbitration or audit holds). Old state is kept under recheck."""
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    changed = []
    for path in sorted((Path(base or compose_inbox.root()) / day).glob('*.json')):
        row = json.loads(path.read_text())
        body = (row.get('body') or '').strip()
        if not body or row.get('superseded'):
            continue
        fmt = (row.get('post_format') or {}).get('type')
        now = editorial_style.findings(body, row.get('lang'), post_format=fmt)
        hard = {f.get('code') for f in row.get('findings') or [] if f.get('level') == 'hard'}
        style = set(editorial_style.CODES)
        ready = not row.get('held') and row.get('draft_status') == 'draft_ready'
        mark = {'at': at, 'version': editorial_style.VERSION, 'old_hard': sorted(hard),
                'old_hold_reason': row.get('hold_reason'), 'old_draft_status': row.get('draft_status')}
        if ready and now:
            row['findings'] = list(row.get('findings') or []) + [{'code': f['code'], 'level': 'hard'} for f in now]
            row.update(held=True, draft_status='needs_review',
                       hold_reason='hard: ' + ','.join(sorted({f['code'] for f in now})), recheck=mark)
        elif (not ready and not now and hard and hard <= style
              and (row.get('arbitration') or {}).get('status') != 'HOLD'):
            row['findings'] = [f for f in row['findings'] if f.get('code') not in hard]
            row.update(held=False, hold_reason=None, draft_status='draft_ready', recheck=mark)
        else:
            continue
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n')
        changed.append((row['account_id'], row['id'], row['draft_status'], row.get('hold_reason')))
    return changed


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--recheck':
        for row in recheck(sys.argv[2]):
            print(*row)
        return 0
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(apply(json.loads(Path(sys.argv[1]).read_text())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
