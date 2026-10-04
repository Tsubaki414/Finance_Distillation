"""Offline retrieval over the shared store; routing plus beat keyword matches."""
from datetime import date, datetime, timedelta, timezone
import re

from live.jev_front import KEYWORDS, PERSONAS
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


def units_for_persona(store, persona, *, limit=None, as_of=None, max_age_days=None):
    """Return copied records marked routed/keyword, ordered by relevance then date.

    Keyword hits count distinct keywords in statements and bound metric text.
    English matches use a left word boundary, retaining keyword stems from THEMES.
    as_of excludes future publications; max_age_days excludes unknown dates and
    publications older than its inclusive UTC window (relative to as_of or now).
    Without a date filter unknown publication dates sort last. Routing overrides
    keyword scoring; ties are deterministic by unit_id. No store writes occur.
    """
    if persona not in PERSONAS:
        raise ValueError(f'Unknown persona: {persona}')
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError('limit must be a nonnegative integer')
    if max_age_days is not None and max_age_days < 0:
        raise ValueError('max_age_days must be nonnegative')
    words = set(KEYWORDS.get(persona, ())) | set(THEMES[persona][2])
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
        numbers = unit.get('numbers') or []
        text = ' '.join([str(unit.get('statement') or '')] +
                        [str(n.get('metric') or '') for n in numbers if isinstance(n, dict)]).lower()
        hits = sum(bool(re.search((r'(?<![a-z])' if w.isascii() else '') + re.escape(w.lower()), text))
                   for w in words)
        routed = persona in (row.get('personas') or [])
        if not routed and not hits:
            continue
        record = dict(row, match='routed' if routed else 'keyword')
        ranked.append(((0 if routed else 1, 0 if routed else -hits,
                        -published.timestamp() if published else float('inf'), str(row.get('unit_id'))), record))
    ranked.sort(key=lambda item: item[0])
    return [record for _, record in ranked][:limit]
