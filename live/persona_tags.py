"""Semantic persona tags. Failed reviews never establish relevance."""
import math
import json
from live.jev_front import JEV_BEATS, PERSONAS
from live.retrieval import RELEVANCE_CRITERIA, _review_relevance


def tagged_personas(tags_for_unit, threshold=0.7):
    return sorted(p for p, tag in tags_for_unit.items()
                  if tag.get('verdict') == 'relevant'
                  and type(tag.get('confidence')) in (int, float)
                  and math.isfinite(tag['confidence']) and tag['confidence'] >= threshold)


def tag_units(records, *, jev, personas=None, threshold=0.7, max_calls=None, stats=None):
    """Review pairs in batches of at most 16; stats counts actual provider calls.

    Retry pending pairs once, then bisect. The call cap includes retries and
    split calls. Threshold is applied by tagged_personas, never to judgments.
    """
    if not 0 <= threshold <= 1:
        raise ValueError('threshold must be between zero and one')
    if max_calls is not None and (type(max_calls) is not int or max_calls < 0):
        raise ValueError('max_calls must be a nonnegative integer')
    beats = list(JEV_BEATS if personas is None else personas)
    if len(beats) != len(set(beats)) or any(p not in PERSONAS for p in beats):
        raise ValueError('personas must be unique known personas')
    stats = stats if stats is not None else {}
    stats.update(calls=0, retries=0, splits=0, unresolved=0)
    groups, pairs = [], {}
    for record in records:
        unit = record.get('unit', record)
        uid = record.get('unit_id') or unit['unit_id']
        source = record.get('source') or {}
        attribution = record.get('attribution') or {}
        group = {}
        for persona in beats:
            key = json.dumps([uid, persona])
            pairs[key] = (uid, persona)
            group[key] = {'type': 'choice', 'criteria': RELEVANCE_CRITERIA,
                          'instructions': f'Persona beat: {PERSONAS[persona]}. '
                          f'Unit kind: {unit.get("kind", "")}. '
                          f'Statement: "{str(unit.get("statement") or "")[:400]}". '
                          f'Publisher: {source.get("publisher") or attribution.get("publisher") or unit.get("publisher", "")}. '
                          f'Source title: {source.get("title") or unit.get("title", "")}. Judge relevance for this beat '
                          'on topic fit only: the persona writes in its own language and may use '
                          'sources in any language, so the unit\'s language is not a reason to reject it.'}
        groups.append(group)
    resolved = {}

    def valid_answer(answer):
        confidence = answer.get('confidence')
        return (type(confidence) in (int, float) and math.isfinite(confidence)
                and 0 <= confidence <= 1)

    def review(questions):
        resolved.update(_review_relevance(jev, {'task': 'unit persona relevance'}, questions,
                                         max_calls=max_calls, stats=stats, valid_answer=valid_answer))

    batch = {}
    for group in groups:
        if len(batch) + len(group) > 16:
            review(batch)
            batch = {}
        batch.update(group)
    if batch:
        review(batch)
    stats['unresolved'] = len(pairs) - len(resolved)
    out = {}
    for key, tag in resolved.items():
        uid, persona = pairs[key]
        out.setdefault(uid, {})[persona] = {k: tag[k] for k in ('verdict', 'confidence')}
    return out


def target_units(source, units, *, jev):
    """Ingest gate: keep any resolved relevant verdict, regardless of confidence."""
    tags = tag_units([{'unit_id': u['unit_id'], 'unit': u, 'source': source} for u in units], jev=jev)
    kept = [u for u in units if any(t['verdict'] == 'relevant' for t in tags.get(u['unit_id'], {}).values())]
    return kept, {u['unit_id']: tags[u['unit_id']] for u in kept}
