"""Cross-persona claim arbitration (soft mode).

Same day / same event: personas MAY disagree (opposite directions stay).
If they only rephrase the same conclusion — overlapping subject + compatible
direction, and similar account_view or a shared source — keep the best-fit
persona for that topic lane; others HOLD with reason. Soft mode flags and
reassigns; it never deletes drafts.

Pattern borrowed from x-account-operator resolve_persona_editorial_collisions
(DUPLICATED_BY_STRONGER_PERSONA), adapted to FD stance fields
(account_view / subject / direction) and persona beats in live/accounts.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = ROOT / 'live' / 'accounts.json'

# Opposite directions = real disagreement → never collide.
OPPOSITE = {
    'bullish': 'bearish', 'bearish': 'bullish',
    'higher': 'lower', 'lower': 'higher',
    'wider': 'tighter', 'tighter': 'wider',
    'accelerating': 'decelerating', 'decelerating': 'accelerating',
}
# Soft near-synonyms: both are non-directional takes, often the same conclusion.
COMPATIBLE = {
    'neutral': frozenset({'neutral', 'mixed'}),
    'mixed': frozenset({'neutral', 'mixed'}),
}

# Same-sign directional labels across persona vocabularies (wider/tighter excluded: spread-dependent).
POLARITY = {'bullish': 1, 'higher': 1, 'accelerating': 1, 'bearish': -1, 'lower': -1, 'decelerating': -1}

WRITE, HOLD, IGNORE = 'WRITE', 'HOLD', 'IGNORE'
REASON_DUPLICATE = 'DUPLICATED_BY_STRONGER_PERSONA'
REASON_CODE_SOFT = 'cross_persona_claim_duplicate'

_WORD = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def _tokens(text):
    return {t.casefold() for t in _WORD.findall(text or '') if len(t) > 1}


def _overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _bigrams(text):
    s = re.sub(r'\s+', '', (text or '').casefold())
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


def _load_beats():
    rows = json.loads(ACCOUNTS.read_text()).get('accounts') or []
    out = {r['id']: {'beats': list(r.get('beats') or []), 'lanes': list(r.get('lanes') or []),
                     'lang': r.get('lang') or ''} for r in rows if r.get('id')}
    # Oct 7 (fd20): the 20 main accounts not in accounts.json get their beat line from live/fd20_accounts.json.
    try:
        extra = json.loads((ACCOUNTS.parent / 'fd20_accounts.json').read_text()).get('accounts') or []
    except (OSError, ValueError):
        extra = []
    for r in extra:
        if r.get('id') and r['id'] not in out:
            out[r['id']] = {'beats': [r.get('focus') or r.get('beat') or ''], 'lanes': [], 'lang': r.get('lang') or ''}
    return out


def direction_compatible(left, right):
    """True when directions agree or are soft near-synonyms; False on opposites.

    Missing direction falls through to text/source similarity (caller decides).
    """
    if not left or not right:
        return None  # unknown — do not block on direction alone
    if left == right:
        return True
    if OPPOSITE.get(left) == right:
        return False
    # Oct 6 v8: stance vocabularies differ by persona (en_industry 'bullish' vs zh_industry 'higher'
    # on the same source); same polarity is the same direction (v7_zi duplicate slipped through).
    if POLARITY.get(left) and POLARITY.get(left) == POLARITY.get(right):
        return True
    return right in COMPATIBLE.get(left, frozenset({left}))


def subject_overlap(left, right):
    return _overlap(_tokens(left), _tokens(right))


def view_overlap(left, right):
    """Token Jaccard with a bigram fallback for cross-script paraphrases."""
    tok = _overlap(_tokens(left), _tokens(right))
    if tok >= 0.25:
        return tok
    return _overlap(_bigrams(left), _bigrams(right))


def claims_collide(a, b, *, subject_floor=0.5, view_floor=0.55, same_language=False):
    """Same conclusion rephrase? Opposite directions never collide.
    same_language=True (fd20 daily, FD_ARB_SAME_LANG): a zh and an en account post to different readers and never
    duplicate each other; selection already allows one story per language (10-08: 6 of 12 holds were zh drafts held
    for an en keeper). The legacy 4-account matrix keeps cross-language arbitration (Oct 6 v2)."""
    if a.get('account_id') == b.get('account_id'):
        return False
    if same_language and a.get('account_lang') and b.get('account_lang') and a['account_lang'] != b['account_lang']:
        return False
    day_a, day_b = a.get('day'), b.get('day')
    if day_a and day_b and day_a != day_b:
        return False
    compat = direction_compatible(a.get('direction'), b.get('direction'))
    if compat is False:
        return False
    subj = subject_overlap(a.get('subject') or '', b.get('subject') or '')
    shared_source = bool(a.get('source_id') and a.get('source_id') == b.get('source_id'))
    shared_unit = bool(set(a.get('unit_ids') or []) & set(b.get('unit_ids') or []))
    same_event = shared_source or shared_unit or (
        a.get('event_key') and a.get('event_key') == b.get('event_key'))
    views = view_overlap(a.get('account_view') or '', b.get('account_view') or '')
    # Strong path: overlapping subject + compatible/unknown direction + (view or same event).
    if subj >= subject_floor and (compat is not False) and (views >= view_floor or same_event):
        return True
    # Same-event path: shared source/unit is enough when the take overlaps at all and
    # directions are not opposite (covers missing subject labels and cross-script paraphrases).
    if same_event and compat is not False and (views >= 0.25 or subj >= 0.3 or not (a.get('subject') and b.get('subject'))):
        return True
    return False


# Content words kept when scoring beat ownership (drop filler from beat sentences).
_STOP = frozenset('english chinese language with a an the and or for of to in on at by from into over '
                  'short-term long-term market data angle macro'.split())
# Explicit topic-lane owners (first listed wins ties). Specialty beats before generic chart/flow lanes.
_LANE_OWNERS = (
    (('bitcoin', 'btc', 'crypto', 'stablecoin', 'onchain', 'on-chain', 'etf', 'regulation'),
     ('crypto_macro_en', 'crypto_macro_zh', 'trading_shortterm', 'market_data_charts')),
    (('fed', 'fomc', 'pce', 'inflation', 'jobs', 'payroll', 'rates', 'yield'),
     ('en_macro', 'zh_macro', 'crypto_macro_en', 'crypto_macro_zh')),
    (('options', 'dealer', 'gamma', 'vix', 'skew', 'put', 'call', 'positioning'),
     ('trading_shortterm', 'market_data_charts', 'crypto_macro_en')),
    (('breadth', 'sentiment', 'flows', 'volume', 'chart'),
     ('market_data_charts', 'trading_shortterm')),
)


def _specialty_tokens(beat_texts):
    return {t for t in _tokens(' '.join(beat_texts)) if t not in _STOP and not t.isdigit()}


def lane_score(account_id, subject='', account_view='', *, beats=None, source_lang=None):
    """How well this persona's beats own the topic. Higher wins the lane."""
    beats = beats or _load_beats()
    info = beats.get(account_id) or {}
    specialty = _specialty_tokens(info.get('beats') or [])
    probe = _tokens(f'{subject} {account_view}')
    text = f'{subject} {account_view}'.casefold()
    # Hits: specialty keywords that appear in the claim (recall against the beat, not jaccard).
    hits = sum(1 for t in specialty if t in probe or t in text)
    base = hits / max(len(specialty), 1)
    # Topic-owner list rank (earlier = stronger for this subject).
    owner_bonus = 0.0
    for keys, owners in _LANE_OWNERS:
        if any(k in text or k in probe for k in keys):
            if account_id in owners:
                owner_bonus = 0.4 * (1 - owners.index(account_id) / max(len(owners), 1))
            break
    lang_bonus = 0.2 if source_lang and info.get('lang') == source_lang else 0.0
    return round(base + owner_bonus + lang_bonus, 4)


def _components(items, collide):
    n = len(items)
    links = {i: {i} for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if collide(items[i], items[j]):
                links[i].add(j)
                links[j].add(i)
    unseen, groups = set(range(n)), []
    while unseen:
        start = unseen.pop()
        stack, comp = [start], {start}
        while stack:
            linked = links[stack.pop()] - comp
            comp |= linked
            stack.extend(linked)
            unseen -= linked
        groups.append(sorted(comp))
    return groups


def arbitrate(candidates, *, mode='soft', beats=None, same_language=False):
    """Assign WRITE / HOLD across a batch of stance claims.

    Soft mode: losers keep their draft payload; they are flagged HOLD with
    reason_code DUPLICATED_BY_STRONGER_PERSONA and reassigned_to the keeper.
    IGNORE is reserved for a future hard mode (not used here).
    """
    if mode not in ('soft', 'hard'):
        raise ValueError('mode must be soft or hard')
    beats = beats or _load_beats()
    items = [dict(c) for c in candidates]
    for c in items:
        c.setdefault('account_lang', (beats.get(c.get('account_id')) or {}).get('lang') or None)
        c['_lane_score'] = lane_score(c.get('account_id'), c.get('subject') or '',
                                      c.get('account_view') or '', beats=beats,
                                      source_lang=c.get('source_lang'))
    decisions = []
    for gi, group in enumerate(_components(items, lambda a, b: claims_collide(a, b, same_language=same_language))):
        members = [items[i] for i in group]
        if len(members) == 1:
            m = members[0]
            decisions.append(_decision(m, WRITE, None, None, gi, mode))
            continue
        members.sort(key=lambda m: (-m['_lane_score'], m.get('account_id') or ''))
        keeper = members[0]
        decisions.append(_decision(keeper, WRITE, None, None, gi, mode))
        for loser in members[1:]:
            status = HOLD if mode == 'soft' else IGNORE
            decisions.append(_decision(loser, status, REASON_DUPLICATE,
                                       keeper.get('account_id'), gi, mode))
    # Stable output order: input order.
    by_key = {(d.get('key') or d.get('account_id'), d.get('account_id')): d for d in decisions}
    ordered = []
    for c in candidates:
        k = (c.get('key') or c.get('account_id'), c.get('account_id'))
        ordered.append(by_key[k])
    return ordered


def _decision(claim, status, reason_code, keeper, group_id, mode):
    return {
        'key': claim.get('key'),
        'account_id': claim.get('account_id'),
        'status': status,
        'reason_code': reason_code,
        'reassigned_to': keeper,
        'collision_group': group_id,
        'lane_score': claim.get('_lane_score'),
        'subject': claim.get('subject'),
        'direction': claim.get('direction'),
        'account_view': claim.get('account_view'),
        'mode': mode,
        'soft': mode == 'soft' and status == HOLD,
    }


def candidate_from_stance(account_id, stance, *, key=None, source=None, unit_ids=None, day=None):
    """Build an arbitration candidate from a stance_step / compose result."""
    stance = stance or {}
    view = stance.get('view') or {}
    source = source or {}
    return {
        'key': key or account_id,
        'account_id': account_id,
        'subject': view.get('subject') or '',
        'direction': view.get('direction'),
        'account_view': stance.get('account_view') or '',
        # v8: the document id, not the publisher (two wallstreetcn articles are not one event)
        'source_id': source.get('id') or source.get('source_id'),
        'source_lang': source.get('lang') or ('zh' if any('\u4e00' <= ch <= '\u9fff' for ch in (source.get('title') or '')[:80]) else 'en'),
        'unit_ids': list(unit_ids or stance.get('supporting_unit_ids') or []),
        'event_key': source.get('url') or source.get('title') or source.get('id'),
        'day': day or (source.get('published_at') or '')[:10] or None,
    }


def apply_to_results(results, *, mode='soft', same_language=False):
    """Post-stance / post-compose soft arbitration over a batch of draft dicts.

    Each result must carry account_id and stance (or top-level subject/direction/
    account_view). HOLD adds a soft finding and arbitration block; drafts are
    never deleted. WRITE results get arbitration.status=WRITE.
    """
    cands, index = [], []
    for i, r in enumerate(results):
        stance = r.get('stance') or {
            'account_view': r.get('account_view'),
            'view': {'subject': r.get('subject'), 'direction': r.get('direction')},
            'supporting_unit_ids': r.get('supporting_unit_ids') or [],
        }
        if not stance.get('account_view') and not (stance.get('view') or {}).get('subject'):
            continue
        if (stance.get('decision') == 'reject') or r.get('status') in ('skipped', 'no_stance', 'error'):
            continue
        cands.append(candidate_from_stance(
            r.get('account_id') or r.get('persona_id'), stance,
            key=r.get('key') or r.get('id') or f'{r.get("account_id")}#{i}',
            source=r.get('source') or {},
            unit_ids=[u.get('unit_id') for u in (r.get('units') or []) if isinstance(u, dict)],
            day=r.get('day')))
        index.append(i)
    decisions = arbitrate(cands, mode=mode, same_language=same_language)
    out = [dict(r) for r in results]
    for i, dec in zip(index, decisions):
        row = out[i]
        row['arbitration'] = {k: dec[k] for k in (
            'status', 'reason_code', 'reassigned_to', 'collision_group', 'lane_score', 'mode', 'soft')}
        if dec['status'] == HOLD:
            finding = {'code': REASON_CODE_SOFT, 'level': 'soft',
                       'detail': (f"same-conclusion claim held; keeper={dec['reassigned_to']} "
                                  f"({dec['reason_code']})")}
            checks = list(row.get('post_checks') or [])
            checks.append(finding)
            row['post_checks'] = checks
            # Soft hold: keep text, mark status held for queue filtering (never delete).
            if row.get('status') not in ('skipped', 'error', 'needs_review'):
                row['status'] = 'held'
            risks = list(row.get('risks') or [])
            risks.append({**finding, 'status': 'warning'})
            row['risks'] = risks
    return out
