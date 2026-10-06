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
  drift     - `drift_of_view_id` = an on-topic prior whose direction changed (not a flip, e.g.
              lower -> neutral) WITHOUT the model setting revises_view_id, when the model cited that
              prior (cited_prior_view_ids / a meta-continuation phrase) or the subject matches.
              Set deterministically; carries the SOFT finding `direction_drift_unmarked` (human
              review) - never a block (docs/2026-10-06_direction_drift.md).
  fresh     - none of the above.
All three links supersede the parent in `current()`, so a lasting view stays one chain head
instead of accumulating near-duplicates.
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


# Deterministic continue-link thresholds (min-normalised token overlap; EN stems / ZH bigrams /
# bilingual alias concepts). Thresholds are unchanged by the alias layer (2026-10-06).
CONTINUE_SUBJECT_MIN = 0.4     # subject vs subject
CONTINUE_TEXT_MIN = 0.3        # subject + account_view vs subject + account_view
LINK_KEYS = ('revises_view_id', 'continues_view_id', 'drift_of_view_id')   # each supersedes its parent


def _tokens(text):
    """EN stems / ZH bigrams, with bilingual finance aliases folded into '@concept' tokens first
    (live/finance_aliases.py) so ZH<->EN peers ("美联储降息路径" / "Fed rate cut path") overlap."""
    from live.compose import _tokens as tok
    from live.finance_aliases import canonicalize
    concepts, segments = canonicalize(str(text or ''))
    out = set(concepts)
    for seg in segments:
        out |= tok(seg)
    return out


def _overlap(a, b):
    """Min-normalised token overlap; 0 when both sides name different entities in one family."""
    from live.finance_aliases import entity_conflict
    if entity_conflict(a, b):
        return 0.0
    return len(a & b) / (min(len(a), len(b)) or 1)


def _asymmetric_overlap(want, have):
    """want-normalised overlap (related()); same entity-family veto as _overlap."""
    from live.finance_aliases import entity_conflict
    if entity_conflict(want, have):
        return 0.0
    return len(want & have) / (len(want) or 1)


def _same_subject(subject, other):
    """True when `subject` substantially overlaps `other` and entities do not conflict."""
    from live.finance_aliases import entity_conflict
    if not subject or entity_conflict(subject, other):
        return False
    return len(subject & other) / len(subject) >= 0.5


def continue_score(view, account_view, row):
    """(subject_overlap, text_overlap) between a new call and a ledger row."""
    subject = _tokens(str((view or {}).get('subject') or ''))
    text = subject | _tokens(str(account_view or ''))
    row_subject = _tokens(str(row.get('subject') or ''))
    row_text = row_subject | _tokens(str(row.get('account_view') or ''))
    return round(_overlap(subject, row_subject), 3), round(_overlap(text, row_text), 3)


SYNTHETIC_SOURCE = re.compile(r'^synthetic-(?:macro|industry)$')   # demo fallback-slot source ids


def is_synthetic(row):
    """Placeholder rows from synthetic/fallback drafts (demo fallback source ids, or flagged)."""
    return bool(row.get('synthetic')) or any(SYNTHETIC_SOURCE.match(str(x)) for x in row.get('source_ids') or [])


class ViewLedger:
    def __init__(self, account_id, directory=None):
        self.account_id = account_id
        root = Path(directory or os.environ.get('FD_VIEW_LEDGER_DIR') or DEFAULT_DIR)
        self.path = root / f'{account_id}.jsonl'

    def entries(self, include_synthetic=False):
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
        if include_synthetic:
            return rows
        # Oct 6 v7: synthetic placeholder views (demo fallback slots) never anchor continuity.
        return [r for r in rows if not is_synthetic(r)]

    def record(self, stance, *, unit_ids, source_ids, draft_id=None, input_view=None):
        text = str(stance.get('account_view') or '').strip()
        if not text or stance.get('decision') == 'reject':
            raise ValueError('view ledger: only take/adapt calls with an account_view are recorded')
        if POSITION.search(text):
            raise ValueError('view ledger: views only - position/trade language is never recorded')
        if any(SYNTHETIC_SOURCE.match(str(x)) for x in source_ids or []):
            raise ValueError('view ledger: synthetic/fallback drafts never write views')
        continues, revises = stance.get('continues_view_id'), stance.get('revises_view_id')
        drift = stance.get('drift_of_view_id')
        if sum(bool(x) for x in (continues, revises, drift)) > 1:
            raise ValueError('view ledger: a call links one prior view (continue, revise or drift), not both')
        if continues or revises or drift:
            known = {r['id'] for r in self.entries()}
            for name, vid in (('continues_view_id', continues), ('revises_view_id', revises),
                              ('drift_of_view_id', drift)):
                if vid and vid not in known:
                    raise ValueError(f'view ledger: {name} {vid} is not a recorded view of this account')
        # A 'take' adopts the input view and may omit `view`; record the adopted view's structure so
        # later flips on the same subject can still be flagged (else subject/direction are None).
        v = stance.get('view') or input_view or {}
        entry = {'id': 'view-' + uuid.uuid4().hex[:12], 'account_id': self.account_id, 'account_view': text,
                 'subject': v.get('subject'), 'direction': v.get('direction'), 'conviction': v.get('conviction'),
                 'horizon': v.get('horizon'), 'revises_view_id': revises or None,
                 'continues_view_id': continues or None, 'drift_of_view_id': drift or None,
                 'unit_ids': list(unit_ids), 'source_ids': list(source_ids), 'draft_id': draft_id,
                 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return entry

    def current(self):
        """Entries not superseded by a later revision or continuation (chain heads)."""
        rows = self.entries()
        superseded = {r.get(k) for r in rows for k in LINK_KEYS if r.get(k)}
        return [r for r in rows if r['id'] not in superseded]

    def lineage(self, view_id):
        """[view_id, parent, grandparent, ...] following continues/revises links."""
        by_id = {r['id']: r for r in self.entries()}
        chain, seen = [], set()
        while view_id and view_id in by_id and view_id not in seen:
            seen.add(view_id)
            chain.append(view_id)
            r = by_id[view_id]
            view_id = r.get('continues_view_id') or r.get('revises_view_id') or r.get('drift_of_view_id')
        return chain

    def link_continuity(self, stance, prior_rows=None, input_view=None):
        """Return a copy of stance with exactly one of continue / revise / drift / fresh resolved.

        - reject: no links.
        - revises_view_id already set (model, validated upstream): keep it, continues cleared.
        - otherwise pick the best current prior on the same subject AND same direction by
          deterministic match score (subject / text token overlap; a prior the model cited in
          cited_prior_view_ids wins ties, then the latest call) and set continues_view_id.
          An opposite-direction match is a flip: it is NOT linked as a continuation (the
          contradicts_prior_view finding stays until the model sets revises_view_id).
        - no same-direction match, but an on-topic prior with a different, non-opposite direction
          that the model cited (or referenced via a meta-continuation phrase) or whose subject
          matches: link it as drift_of_view_id (supersedes the prior; soft finding
          direction_drift_unmarked via drift_findings) instead of a silent second current entry.
        Any model-supplied continues_view_id is ignored (ids are linked from scores, not trusted).
        `continuity` records which branch fired and why.
        """
        out = dict(stance)
        out.pop('continues_view_id', None)
        out.pop('drift_of_view_id', None)
        if out.get('decision') not in ('take', 'adapt') or not str(out.get('account_view') or '').strip():
            out['revises_view_id'] = out['continues_view_id'] = out['drift_of_view_id'] = None
            out['continuity'] = {'link': 'none', 'source': 'not_recordable'}
            return out
        v = out.get('view') or input_view or {}
        direction = v.get('direction')
        dropped = None
        if out.get('revises_view_id'):
            # Topic gate (Oct 6 v5): v4b zh_industry revised "AI wealth concentration" with an "AI
            # infrastructure demand" call and en_macro revised "Fed path" with "market resilience";
            # the stance prompt only validated that the id was a supplied prior. A revise needs the
            # same on-topic bar as a continuation; otherwise drop the link (soft revise_off_topic).
            parent = next((r for r in self.entries() if r['id'] == out['revises_view_id']), None)
            if parent is not None:
                subj, text = continue_score(v, out.get('account_view'), parent)
                if subj < CONTINUE_SUBJECT_MIN and text < CONTINUE_TEXT_MIN:
                    dropped = {'view_id': out['revises_view_id'], 'subject_overlap': subj, 'text_overlap': text}
                    out['revises_view_id'] = None
        if out.get('revises_view_id'):
            out['continues_view_id'] = out['drift_of_view_id'] = None
            out['continuity'] = {'link': 'revise', 'source': 'model', 'view_id': out['revises_view_id']}
            parent = next((r for r in self.entries() if r['id'] == out['revises_view_id']), {})
            if direction and parent.get('direction') == direction:
                # Diagnostic only: prompt says same-direction horizon/conviction updates are continues.
                out['continuity']['same_direction'] = True
            return out
        rows = prior_rows if prior_rows is not None else self.related(
            ' '.join(str(x or '') for x in (v.get('subject'), out.get('account_view'))), k=5)
        order = {r['id']: i for i, r in enumerate(self.current())}   # append order = recency
        cited = set(out.get('cited_prior_view_ids') or [])
        referenced = bool((out.get('stance_scrub') or {}).get('meta_continuation'))
        best, flip, drift = None, None, None
        for r in rows:
            if r.get('id') not in order:
                continue
            subj, text = continue_score(v, out.get('account_view'), r)
            on_topic = subj >= CONTINUE_SUBJECT_MIN or text >= CONTINUE_TEXT_MIN
            if not on_topic and r['id'] not in cited:
                continue
            if direction and OPPOSITE.get(direction) == r.get('direction'):
                if on_topic:
                    flip = flip or r['id']
                continue
            if not (direction and r.get('direction') == direction):
                # Direction changed without revises_view_id: a drift candidate when the model leaned on
                # this prior (cited / meta-continuation phrase) or the subject itself matches.
                if (direction and r.get('direction') and (r['id'] in cited or referenced
                                                          or subj >= CONTINUE_SUBJECT_MIN)):
                    key = (r['id'] in cited, subj, order[r['id']])
                    if drift is None or key > drift[0]:
                        drift = (key, r['id'], r.get('direction'))
                continue
            if not on_topic:
                continue
            key = (r['id'] in cited, max(subj, text), str(r.get('created_at') or ''), order[r['id']])
            if best is None or key > best[0]:
                best = (key, r['id'], subj, text)
        out['revises_view_id'] = out['drift_of_view_id'] = None
        if best:
            out['continues_view_id'] = best[1]
            out['continuity'] = {'link': 'continue', 'source': 'ledger_match', 'view_id': best[1],
                                 'subject_overlap': best[2], 'text_overlap': best[3]}
        elif drift and not flip:
            out['continues_view_id'] = None
            out['drift_of_view_id'] = drift[1]
            out['continuity'] = {'link': 'drift', 'source': 'ledger_match', 'view_id': drift[1],
                                 'from_direction': drift[2], 'to_direction': direction}
        else:
            out['continues_view_id'] = None
            out['continuity'] = {'link': 'fresh', 'source': 'ledger_match',
                                 **({'unacknowledged_flip_of': flip} if flip else {})}
        if dropped:
            out['continuity']['dropped_revise'] = dropped
        return out

    def related(self, text, k=5):
        want = _tokens(text)
        scored = []
        for r in self.current():
            have = _tokens(' '.join(str(x or '') for x in (r.get('subject'), r.get('account_view'))))
            overlap = _asymmetric_overlap(want, have)
            if overlap > 0:
                scored.append((overlap, r['created_at'], r))
        scored.sort(key=lambda t: t[1], reverse=True)   # ties: latest call first
        scored.sort(key=lambda t: -t[0])
        return [dict(r, overlap=round(o, 2)) for o, _, r in scored[:k]]

    def drift_findings(self, stance):
        """SOFT `direction_drift_unmarked` when link_continuity linked a direction drift."""
        c = stance.get('continuity') or {}
        out = []
        if c.get('dropped_revise'):
            d = c['dropped_revise']
            out.append({'code': 'revise_off_topic',
                        'detail': f"model revises_view_id {d['view_id']} is off-topic (subject overlap "
                                  f"{d['subject_overlap']}, text overlap {d['text_overlap']}); link dropped"})
        if c.get('link') != 'drift':
            return out
        return out + [{'code': 'direction_drift_unmarked',
                 'detail': f"direction {c.get('from_direction')} -> {c.get('to_direction')} on prior {c.get('view_id')} "
                           f"without revises_view_id; linked as drift_of_view_id (supersedes it) - confirm "
                           f"it is a revise and say why, or keep the prior direction"}]

    def ignores_prior(self, stance, prior_rows=None):
        """Soft flag when take/adapt on an overlapping subject neither continues nor revises."""
        if stance.get('decision') not in ('take', 'adapt'):
            return []
        if (stance.get('revises_view_id') or stance.get('continues_view_id') or stance.get('drift_of_view_id')
                or stance.get('cited_prior_view_ids')):
            return []
        v = stance.get('view') or {}
        subject = _tokens(str(v.get('subject') or ''))
        if not subject:
            return []
        rows = prior_rows if prior_rows is not None else self.related(
            ' '.join(str(x or '') for x in (v.get('subject'), stance.get('account_view'))), k=5)
        for r in rows:
            same = _same_subject(subject, _tokens(str(r.get('subject') or '')))
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
            if r['id'] in (stance.get('revises_view_id'), stance.get('continues_view_id'), stance.get('drift_of_view_id')):
                continue
            same = _same_subject(subject, _tokens(str(r.get('subject') or '')))
            if same and OPPOSITE.get(direction) == r.get('direction'):
                out.append({'code': 'contradicts_prior_view',
                            'detail': f"flips {r.get('direction')} call {r['id']} ({r['account_view'][:80]}) without revises_view_id"})
        return out[:1]
