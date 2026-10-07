"""Shared-store retrieval gated by semantic tags, with explicit legacy routing."""
from datetime import date, datetime, timedelta, timezone
import re

from live.jev_front import KEYWORDS, PERSONAS, jev_persona_for
from live.reportgem_daily import THEMES

_ZH_EQUIVALENTS = {'macro_zh': 'macro_rates_en', 'crypto_macro_zh': 'crypto_macro_en',
                   'zh_us_stock_commentary': 'industry_ai_capex'}


def _date(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def units_for_persona(store, persona, *, limit=None, as_of=None, max_age_days=None, mode='tags'):
    """Return copied records, tagged by default and ordered by confidence/date.

    Legacy mode preserves routing/keyword matching and its original ordering.

    Keyword hits count distinct keywords in statements and bound metric text.
    English matches use a left word boundary, retaining keyword stems from THEMES.
    as_of excludes future publications; max_age_days excludes unknown dates and
    publications older than its inclusive UTC window (relative to as_of or now).
    Without a date filter unknown publication dates sort last. Routing overrides
    keyword scoring; ties are deterministic by unit_id. No store writes occur.
    """
    original_persona = persona
    persona = jev_persona_for(persona)
    if persona not in PERSONAS:
        raise ValueError(f'Unknown persona: {original_persona}')
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError('limit must be a nonnegative integer')
    if max_age_days is not None and max_age_days < 0:
        raise ValueError('max_age_days must be nonnegative')
    if mode not in ('tags', 'legacy'):
        raise ValueError('mode must be tags or legacy')
    words = set(KEYWORDS.get(persona, ())) | set(THEMES[persona][2] if persona in THEMES else ())
    words.update(KEYWORDS.get(_ZH_EQUIVALENTS.get(persona), ()))
    cutoff = _date(as_of) if as_of is not None else datetime.now(timezone.utc)
    earliest = cutoff - timedelta(days=max_age_days) if max_age_days is not None else None
    ranked = []
    for row in store.units():
        unit = row.get('unit') or {}
        try:
            published = _date((row.get('source') or {}).get('published_at'))
        except (ValueError, TypeError):
            published = None
        if as_of is not None or earliest is not None:
            if published is None or published > cutoff or (earliest is not None and published < earliest):
                continue
        source = row.get('source') or {}
        morris = persona == 'investing_philosophy' and any(record.get(k) in ('x_Morris_LT', 'Morris_LT')
                                                                    for record in (source, row)
                                                                    for k in ('source_id', 'author_handle', 'handle'))
        if mode == 'tags':
            if persona not in row.get('tag_personas', []) and not morris:
                continue
            confidence = (row.get('persona_tags', {}).get(persona) or {}).get('confidence', 0.5)
            ranked.append(((-confidence, -published.timestamp() if published else float('inf'),
                            str(row.get('unit_id'))), dict(row, match='tagged')))
            continue
        numbers = unit.get('numbers') or []
        text = ' '.join([str(unit.get('statement') or '')] +
                        [str(n.get('metric') or '') for n in numbers if isinstance(n, dict)]).lower()
        hits = sum(bool(re.search((r'(?<![a-z])' if w.isascii() else '') + re.escape(w.lower()), text))
                   for w in words)
        routed = persona in (row.get('personas') or [])
        if not routed and not hits and not morris:
            continue
        record = dict(row, match='routed' if routed else 'keyword')
        ranked.append(((0 if routed else 1, 0 if routed else -hits,
                        -published.timestamp() if published else float('inf'), str(row.get('unit_id'))), record))
    ranked.sort(key=lambda item: item[0])
    return [record for _, record in ranked][:limit]


RELEVANCE_CRITERIA = {
    'relevant': 'Directly usable as a fact or view in a post for this persona beat.',
    'tangential': 'Related but would need a stretch to use for this beat.',
    'irrelevant': 'Off the beat for this persona.',
}


def _review_relevance(jev, state, questions, *, max_calls=None, stats=None, valid_answer=None):
    """Retry unresolved questions once, then isolate failures by bisecting.

    Optional shared stats and a call cap apply across all batches/recursion.
    valid_answer lets the tagging caller require a usable confidence too.
    """
    if stats is None:
        stats = {'calls': 0, 'retries': 0, 'splits': 0}
    resolved = {}
    pending = dict(questions)
    for attempt in range(2):
        if not pending or jev is None or (max_calls is not None and stats['calls'] >= max_calls):
            return resolved
        stats['calls'] += 1
        stats['retries'] += int(attempt == 1)
        try:
            response = jev.review(state, pending)
            answers = response.get('answers', {}) if response.get('status') == 'completed' else {}
            for uid in pending:
                answer = answers.get(uid)
                if (isinstance(answer, dict) and answer.get('choice') in RELEVANCE_CRITERIA
                        and (valid_answer is None or valid_answer(answer))):
                    resolved[uid] = {'verdict': answer['choice'],
                                     'confidence': answer.get('confidence'), 'jev_fallback': False}
        except Exception:
            pass  # A provider failure must never establish relevance.
        pending = {uid: q for uid, q in pending.items() if uid not in resolved}
        if not pending:
            return resolved
    if len(pending) > 1 and (max_calls is None or stats['calls'] < max_calls):
        stats['splits'] += 1
        items = list(pending.items())
        middle = len(items) // 2
        for half in (items[:middle], items[middle:]):
            resolved.update(_review_relevance(jev, state, dict(half), max_calls=max_calls,
                                             stats=stats, valid_answer=valid_answer))
    return resolved


def judge_relevance(units_by_persona, *, jev, per_persona=None):
    """Return {persona: {unit_id: judgment}} for served store records.

    per_persona optionally caps the number reviewed for each beat. All skipped
    or unresolved records remain unjudged, with no keyword relevance fallback.
    """
    from live.jev_front import _batches

    if per_persona is not None and (type(per_persona) is not int or per_persona < 0):
        raise ValueError('per_persona must be a nonnegative integer')
    out = {}
    for persona, records in units_by_persona.items():
        beat = PERSONAS[persona]
        records = list(records)
        out[persona] = {r['unit_id']: {'verdict': 'unjudged', 'confidence': None,
                                      'jev_fallback': True} for r in records}
        if jev is None:
            continue
        for batch in _batches(records[:per_persona]):
            questions = {}
            for record in batch:
                unit = record.get('unit') or {}
                publisher = (record.get('source') or {}).get('publisher') or (
                    record.get('attribution') or {}).get('publisher') or ''
                questions[record['unit_id']] = {
                    'type': 'choice', 'criteria': RELEVANCE_CRITERIA,
                    'instructions': f'Persona beat: {beat}. Unit kind: {unit.get("kind", "")}. '
                                    f'Statement: "{str(unit.get("statement") or "")[:400]}". '
                                    f'Publisher: {publisher}. Judge relevance for this beat.'}
            out[persona].update(_review_relevance(
                jev, {'task': 'served unit relevance', 'persona': persona}, questions))
    return out


def counts(store):
    """Store coverage, including unresolved/never-tagged units."""
    rows = store.units()
    return {'units': len(rows), 'untagged': len(store.untagged()),
            'by_persona': {p: sum(p in r.get('tag_personas', []) for r in rows) for p in PERSONAS}}
