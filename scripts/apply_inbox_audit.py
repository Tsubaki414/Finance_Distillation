#!/usr/bin/env python3
"""Apply an editorial audit to one day of the compose review inbox (Oct 7, fix26).

The audit file is {"day": ..., "reviewer": ..., "verdicts": {draft_id: [verdict, reason]}} with verdict keep /
rewrite / drop. Every audited row gets audit={verdict, reason, reviewer, at}. rewrite and drop rows are marked
superseded + held, so the ops page and `daily_compose.py --fill` stop counting them as ready; `--fill` may reuse the
source of a rewrite row for the same account. review_status (the human decision) is never touched, and nothing is
deleted.

  python scripts/apply_inbox_audit.py /workspace/x/cc_jobs/fix26/audit_2026-10-07.json
  python scripts/apply_inbox_audit.py --recheck 2026-10-07
  python scripts/apply_inbox_audit.py --triage /workspace/x/cc_jobs/relax/triage_2026-10-07.json

--recheck re-runs live/editorial_style.py on the stored bodies after a rule change (see recheck()).
--triage applies a human re-triage (Oct 7 relax, see triage()): release / reassign / hold, one reason per draft.
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
    """Re-run live/editorial_style.py on the stored bodies after a rule change. Ready drafts that now trip a HARD
    code are held (hold_reason 'hard: <codes>'); held drafts whose only HARD findings were style codes and that no
    longer trip a HARD one become ready again (not arbitration or audit holds; SOFT codes such as research_tone are
    warnings since v5). Old state is kept under recheck."""
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    changed = []
    for path in sorted((Path(base or compose_inbox.root()) / day).glob('*.json')):
        row = json.loads(path.read_text())
        body = (row.get('body') or '').strip()
        if not body or row.get('superseded'):
            continue
        fmt = (row.get('post_format') or {}).get('type')
        now = editorial_style.hard(editorial_style.findings(body, row.get('lang'), post_format=fmt))
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


ACCOUNTS = ROOT / 'live' / 'fd20_accounts.json'
TRIAGE_ACTIONS = ('release', 'reassign', 'hold')


def triage(plan, base=None):
    """Apply {"day", "reviewer", "items": {draft_id: {"action", "reason", "to"?, "ready"?}}} (Oct 7 relax).

    release: the draft is ready again (held / superseded / arbitration HOLD cleared; stored SOFT style findings are
    relevelled soft). reassign: the draft moves to account `to` (account fields from fd20_accounts.json, the body is
    untouched) and is ready, or held as 'needs light edit' when ready is false. hold: stays held with the reason.
    The previous state is kept under triage.old; review_status is never touched and nothing is deleted."""
    day = plan['day']
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    accounts = {a['id']: a for a in json.loads(ACCOUNTS.read_text())['accounts']}
    counts = dict.fromkeys(TRIAGE_ACTIONS, 0)
    for draft_id, item in plan['items'].items():
        action = item['action']
        if action not in TRIAGE_ACTIONS:
            raise ValueError(f'{draft_id}: action must be one of {TRIAGE_ACTIONS}')
        path = Path(base or compose_inbox.root()) / day / f'{draft_id}.json'
        row = json.loads(path.read_text())
        arb = row.get('arbitration') or {}
        old = {k: row.get(k) for k in ('account_id', 'name', 'held', 'superseded', 'draft_status', 'hold_reason')}
        old['arbitration_status'] = arb.get('status')
        mark = {'action': action, 'reason': item['reason'], 'reviewer': plan.get('reviewer'), 'at': at, 'old': old}
        ready = action == 'release' or (action == 'reassign' and item.get('ready', True))
        if action == 'reassign':
            to = accounts[item['to']]
            mark['from'] = {'account_id': row['account_id'], 'name': row.get('name')}
            row.update(account_id=to['id'], no=to.get('no'), name=to.get('name'), beat=to.get('beat'))
            if to.get('lang') != row.get('lang'):
                raise ValueError(f"{draft_id}: {to['id']} writes {to.get('lang')}, the draft is {row.get('lang')}")
        if ready:
            row.update(held=False, superseded=False, draft_status='draft_ready', hold_reason=None)
            row['findings'] = [{**f, 'level': 'soft'} if f.get('code') in editorial_style.SOFT_CODES else f
                               for f in row.get('findings') or []]
            if arb.get('status') == 'HOLD':
                row['arbitration'] = {**arb, 'status': 'WRITE', 'released_from': 'HOLD'}
        else:
            reason = item['reason'] if action == 'hold' else 'needs light edit: ' + item['reason']
            row.update(held=True, hold_reason=reason)
            if action == 'reassign':
                row.update(superseded=False, draft_status='needs_review')
        row['triage'] = mark
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n')
        counts[action] += 1
    return counts


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--triage':
        print(triage(json.loads(Path(sys.argv[2]).read_text())))
        return 0
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
