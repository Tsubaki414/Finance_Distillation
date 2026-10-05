"""Per-account view ledger: the account's own published calls (views only, never positions).

The stance step reads related prior views so the account stays consistent across posts; a new
call that flips direction on the same subject without naming the view it revises is a SOFT
'contradicts_prior_view' finding. Entries record the judgment sentence and structured view
(subject, direction, conviction, horizon), the supporting unit/source ids and time - never
holdings, trades, sizes or P&L (rejected on write).
Storage: one JSONL per account under FD_VIEW_LEDGER_DIR (default <repo>/store/view_ledger).

Continuity links (see docs/2026-10-05_continues_view_id.md): every recorded call is exactly one of
  continue  - `continues_view_id` = the prior call it carries forward (same subject, same direction);
              set DETERMINISTICALLY by `link_continuity` from ledger match scores, never from raw
              model-typed ids;
  revise    - `revises_view_id` = the prior call it changes (model-set, validated against the
              supplied prior_views; flips must be explained in rationale);
  fresh     - neither.
Both supersede the parent in `current()`, so a lasting view stays one chain head instead of
accumulating near-duplicates.
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


# Deterministic continue-link thresholds (min-normalised token overlap; EN stems / ZH bigrams).
CONTINUE_SUBJECT_MIN = 0.4     # subject vs subject
CONTINUE_TEXT_MIN = 0.3        # subject + account_view vs subject + account_view


def _tokens(text):
    from live.compose import _tokens as tok
    return tok(text or '')


def _overlap(a, b):
    return len(a & b) / (min(len(a), len(b)) or 1)


def continue_score(view, account_view, row):
    """(subject_overlap, text_overlap) between a new call and a ledger row."""
    subject = _tokens(str((view or {}).get('subject') or ''))
    text = subject | _tokens(str(account_view or ''))
    row_subject = _tokens(str(row.get('subject') or ''))
    row_text = row_subject | _tokens(str(row.get('account_view') or ''))
    return round(_overlap(subject, row_subject), 3), round(_overlap(text, row_text), 3)


class ViewLedger:
    def __init__(self, account_id, directory=None):
        self.account_id = account_id
        root = Path(directory or os.environ.get('FD_VIEW_LEDGER_DIR') or DEFAULT_DIR)
        self.path = root / f'{account_id}.jsonl'

    def entries(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def record(self, stance, *, unit_ids, source_ids, draft_id=None, input_view=None):
        text = str(stance.get('account_view') or '').strip()
        if not text or stance.get('decision') == 'reject':
            raise ValueError('view ledger: only take/adapt calls with an account_view are recorded')
        if POSITION.search(text):
            raise ValueError('view ledger: views only - position/trade language is never recorded')
        continues, revises = stance.get('continues_view_id'), stance.get('revises_view_id')
        if continues and revises:
            raise ValueError('view ledger: a call either continues or revises a prior view, not both')
        if continues or revises:
            known = {r['id'] for r in self.entries()}
            for name, vid in (('continues_view_id', continues), ('revises_view_id', revises)):
                if vid and vid not in known:
                    raise ValueError(f'view ledger: {name} {vid} is not a recorded view of this account')
        # A 'take' adopts the input view and may omit `view`; record the adopted view's structure so
        # later flips on the same subject can still be flagged (else subject/direction are None).
        v = stance.get('view') or input_view or {}
        entry = {'id': 'view-' + uuid.uuid4().hex[:12], 'account_id': self.account_id, 'account_view': text,
                 'subject': v.get('subject'), 'direction': v.get('direction'), 'conviction': v.get('conviction'),
                 'horizon': v.get('horizon'), 'revises_view_id': revises or None,
                 'continues_view_id': continues or None,
                 'unit_ids': list(unit_ids), 'source_ids': list(source_ids), 'draft_id': draft_id,
                 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return entry

    def current(self):
        """Entries not superseded by a later revision or continuation (chain heads)."""
        rows = self.entries()
        superseded = {r.get(k) for r in rows for k in ('revises_view_id', 'continues_view_id') if r.get(k)}
        return [r for r in rows if r['id'] not in superseded]

    def lineage(self, view_id):
        """[view_id, parent, grandparent, ...] following continues/revises links."""
        by_id = {r['id']: r for r in self.entries()}
        chain, seen = [], set()
        while view_id and view_id in by_id and view_id not in seen:
            seen.add(view_id)
            chain.append(view_id)
            r = by_id[view_id]
            view_id = r.get('continues_view_id') or r.get('revises_view_id')
        return chain

    def link_continuity(self, stance, prior_rows=None, input_view=None):
        """Return a copy of stance with exactly one of continue / revise / fresh resolved.

        - reject: no links.
        - revises_view_id already set (model, validated upstream): keep it, continues cleared.
        - otherwise pick the best current prior on the same subject AND same direction by
          deterministic match score (subject / text token overlap; a prior the model cited in
          cited_prior_view_ids wins ties, then the latest call) and set continues_view_id.
          An opposite-direction match is a flip: it is NOT linked as a continuation (the
          contradicts_prior_view finding stays until the model sets revises_view_id).
        Any model-supplied continues_view_id is ignored (ids are linked from scores, not trusted).
        `continuity` records which branch fired and why.
        """
        out = dict(stance)
        out.pop('continues_view_id', None)
        if out.get('decision') not in ('take', 'adapt') or not str(out.get('account_view') or '').strip():
            out['revises_view_id'] = out['continues_view_id'] = None
            out['continuity'] = {'link': 'none', 'source': 'not_recordable'}
            return out
        if out.get('revises_view_id'):
            out['continues_view_id'] = None
            out['continuity'] = {'link': 'revise', 'source': 'model', 'view_id': out['revises_view_id']}
            return out
        v = out.get('view') or input_view or {}
        direction = v.get('direction')
        rows = prior_rows if prior_rows is not None else self.related(
            ' '.join(str(x or '') for x in (v.get('subject'), out.get('account_view'))), k=5)
        order = {r['id']: i for i, r in enumerate(self.current())}   # append order = recency
        cited = set(out.get('cited_prior_view_ids') or [])
        best, flip = None, None
        for r in rows:
            if r.get('id') not in order:
                continue
            subj, text = continue_score(v, out.get('account_view'), r)
            if subj < CONTINUE_SUBJECT_MIN and text < CONTINUE_TEXT_MIN:
                continue
            if direction and OPPOSITE.get(direction) == r.get('direction'):
                flip = flip or r['id']
                continue
            if not (direction and r.get('direction') == direction):
                continue   # direction changed / unknown: a revise is the model's call, not ours
            key = (r['id'] in cited, max(subj, text), str(r.get('created_at') or ''), order[r['id']])
            if best is None or key > best[0]:
                best = (key, r['id'], subj, text)
        out['revises_view_id'] = None
        if best:
            out['continues_view_id'] = best[1]
            out['continuity'] = {'link': 'continue', 'source': 'ledger_match', 'view_id': best[1],
                                 'subject_overlap': best[2], 'text_overlap': best[3]}
        else:
            out['continues_view_id'] = None
            out['continuity'] = {'link': 'fresh', 'source': 'ledger_match',
                                 **({'unacknowledged_flip_of': flip} if flip else {})}
        return out

    def related(self, text, k=5):
        want = _tokens(text)
        scored = []
        for r in self.current():
            have = _tokens(' '.join(str(x or '') for x in (r.get('subject'), r.get('account_view'))))
            overlap = len(want & have) / (len(want) or 1)
            if overlap > 0:
                scored.append((overlap, r['created_at'], r))
        scored.sort(key=lambda t: t[1], reverse=True)   # ties: latest call first
        scored.sort(key=lambda t: -t[0])
        return [dict(r, overlap=round(o, 2)) for o, _, r in scored[:k]]

    def ignores_prior(self, stance, prior_rows=None):
        """Soft flag when take/adapt on an overlapping subject neither continues nor revises."""
        if stance.get('decision') not in ('take', 'adapt'):
            return []
        if stance.get('revises_view_id') or stance.get('continues_view_id') or stance.get('cited_prior_view_ids'):
            return []
        v = stance.get('view') or {}
        subject = _tokens(str(v.get('subject') or ''))
        if not subject:
            return []
        rows = prior_rows if prior_rows is not None else self.related(
            ' '.join(str(x or '') for x in (v.get('subject'), stance.get('account_view'))), k=5)
        for r in rows:
            same = len(subject & _tokens(str(r.get('subject') or ''))) / len(subject) >= 0.5
            if not same:
                continue
            # Continuity: account_view shares substantial tokens with the prior call
            prior_toks = _tokens(str(r.get('account_view') or ''))
            new_toks = _tokens(str(stance.get('account_view') or ''))
            overlap = len(prior_toks & new_toks) / (len(prior_toks) or 1)
            if overlap >= 0.35:
                return []  # continuing the same call in substance
            return [{'code': 'ignores_prior_view',
                     'detail': f"new take on overlapping subject ignores prior {r['id']} "
                               f"({(r.get('account_view') or '')[:80]}) — continue or set revises_view_id"}]
        return []

    def contradictions(self, stance):
        v = stance.get('view') or {}
        direction = v.get('direction')
        if not direction or stance.get('decision') == 'reject':
            return []
        out = []
        subject = _tokens(str(v.get('subject') or ''))
        for r in self.current():
            if r['id'] in (stance.get('revises_view_id'), stance.get('continues_view_id')):
                continue
            same = subject and len(subject & _tokens(str(r.get('subject') or ''))) / len(subject) >= 0.5
            if same and OPPOSITE.get(direction) == r.get('direction'):
                out.append({'code': 'contradicts_prior_view',
                            'detail': f"flips {r.get('direction')} call {r['id']} ({r['account_view'][:80]}) without revises_view_id"})
        return out[:1]
