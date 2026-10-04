"""Explicit source restrictions take precedence over quote permission."""
import re

NO_REPRODUCTION = re.compile(
    r'\bmay not be reproduced\b|\bnot (?:investment )?research\b|'
    r'\bmay not be (?:copied|redistributed|forwarded)\b|'
    r'\bno part of this .{0,60} may be reproduced\b|\bfor the exclusive use of\b',
    re.I | re.S)
OVERRIDES = {'licence_tier': 'B', 'usage': 'paraphrase', 'no_reproduction': True,
             'quote_allowed': False, 'attribution_required': True}
DIRECT_QUOTE = re.compile(
    r'“([^”]+)”|「([^」]+)」|『([^』]+)』|"([^"\n]+)"|‘([^’]+)’|(?<!\w)\'([^\'\n]+)\'(?!\w)')


def detect_no_reproduction(text):
    return bool(NO_REPRODUCTION.search(re.sub(r'\s+', ' ', text or '')))


def apply_no_reproduction(units):
    for unit in units:
        unit.update(OVERRIDES)
    return units


def quote_findings(body, units):
    """Block quoted material, including exact quotes otherwise allowed by QA."""
    restricted = [u for u in units if u.get('quote_allowed') is False]
    if not restricted:
        return []
    quotes = [next(g for g in m.groups() if g).strip() for m in DIRECT_QUOTE.finditer(body)]
    # A composition using restricted units must paraphrase; translated direct
    # quotes are prohibited too, even when they cannot match an English span.
    return [{'code': 'no_reproduction_quote', 'detail': q[:80]} for q in quotes]
