"""Per-account view ledger: the account's own published calls (views only, never positions).

The stance step reads related prior views so the account stays consistent across posts; a new
call that flips direction on the same subject without naming the view it revises is a SOFT
'contradicts_prior_view' finding. Entries record the judgment sentence and structured view
(subject, direction, conviction, horizon), the supporting unit/source ids and time - never
holdings, trades, sizes or P&L (rejected on write).
Storage: one JSONL per account under FD_VIEW_LEDGER_DIR (default <repo>/store/view_ledger).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / 'store' / 'view_ledger'
OPPOSITE = {'bullish': 'bearish', 'bearish': 'bullish', 'higher': 'lower', 'lower': 'higher',
            'wider': 'tighter', 'tighter': 'wider', 'accelerating': 'decelerating', 'decelerating': 'accelerating'}
POSITION = re.compile(r"\b(?:we|i)(?:'re| are| am)?\s+(?:long|short)\b|\b(?:our|my)\s+(?:position|book|portfolio|holdings?)\b|"
                      r"\badded to\b|\btrimmed\b|\bbought\b|\bsold\b|\bP&L\b|仓位|持仓|加仓|减仓|建仓|做多了|做空了|我们持有|我持有", re.I)


def _tokens(text):
    from live.compose import _tokens as tok
    return tok(text or '')


class ViewLedger:
    def __init__(self, account_id, directory=None):
        self.account_id = account_id
        root = Path(directory or os.environ.get('FD_VIEW_LEDGER_DIR') or DEFAULT_DIR)
        self.path = root / f'{account_id}.jsonl'

    def entries(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def record(self, stance, *, unit_ids, source_ids, draft_id=None):
        text = str(stance.get('account_view') or '').strip()
        if not text or stance.get('decision') == 'reject':
            raise ValueError('view ledger: only take/adapt calls with an account_view are recorded')
        if POSITION.search(text):
            raise ValueError('view ledger: views only - position/trade language is never recorded')
        v = stance.get('view') or {}
        entry = {'id': 'view-' + uuid.uuid4().hex[:12], 'account_id': self.account_id, 'account_view': text,
                 'subject': v.get('subject'), 'direction': v.get('direction'), 'conviction': v.get('conviction'),
                 'horizon': v.get('horizon'), 'revises_view_id': stance.get('revises_view_id'),
                 'unit_ids': list(unit_ids), 'source_ids': list(source_ids), 'draft_id': draft_id,
                 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return entry

    def current(self):
        """Entries not superseded by a later revision."""
        rows = self.entries()
        revised = {r.get('revises_view_id') for r in rows if r.get('revises_view_id')}
        return [r for r in rows if r['id'] not in revised]

    def related(self, text, k=5):
        want = _tokens(text)
        scored = []
        for r in self.current():
            have = _tokens(' '.join(str(x or '') for x in (r.get('subject'), r.get('account_view'))))
            overlap = len(want & have) / (len(want) or 1)
            if overlap > 0:
                scored.append((overlap, r['created_at'], r))
        scored.sort(key=lambda t: (-t[0], t[1]), reverse=False)
        return [dict(r, overlap=round(o, 2)) for o, _, r in scored[:k]]

    def contradictions(self, stance):
        v = stance.get('view') or {}
        direction = v.get('direction')
        if not direction or stance.get('decision') == 'reject':
            return []
        out = []
        subject = _tokens(str(v.get('subject') or ''))
        for r in self.current():
            if r['id'] == stance.get('revises_view_id'):
                continue
            same = subject and len(subject & _tokens(str(r.get('subject') or ''))) / len(subject) >= 0.5
            if same and OPPOSITE.get(direction) == r.get('direction'):
                out.append({'code': 'contradicts_prior_view',
                            'detail': f"flips {r.get('direction')} call {r['id']} ({r['account_view'][:80]}) without revises_view_id"})
        return out[:1]
