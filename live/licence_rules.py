"""Explicit source restrictions take precedence over quote permission."""
import re
from decimal import Decimal

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


# ---------------------------------------------------------------- inspiration_only sources (Delphi Digital)
# Members-only research reaches us only as a browser digest (live/adapters/delphi_digest.py). It may steer topic
# and stance; a draft may never cite it, reuse its title wording, or use one of its key numbers unless the same
# number also comes from a public (tier A/B) unit or source text in the draft's own pack.
INSPIRATION_CODES = ('inspiration_only_number', 'inspiration_only_text', 'inspiration_only_cited')
INSPIRATION_ALIASES = {'delphi_digital': ('Delphi Digital', 'Delphi', '德尔菲')}
_TITLE_NGRAM = 5
_WORD = re.compile(r"[A-Za-z0-9$%.']+")


def _quantities(text):
    from live.numeric_fidelity import inventory
    out = []
    for value, dim in inventory(text or ''):
        n = Decimal(value)
        if dim == 'number' and (abs(n) <= 10 or (n == n.to_integral_value() and 1900 <= n <= 2100)):
            continue   # bare small counts and years are anchors, not exclusive figures
        out.append((n, dim))
    return out


def _same(a, b):
    """b as written in a body matches the figure a (exact, or a rounded to b's precision)."""
    (na, da), (nb, db) = a, b
    if da != db:
        return False
    if na == nb:
        return True
    # values are normalized (2 billion -> 2E+9), so the exponent is the precision the body wrote
    return na.quantize(Decimal(1).scaleb(nb.as_tuple().exponent)) == nb


def _public_text(units, source):
    parts = [(source or {}).get('original_text') or '']
    for u in units or []:
        if u.get('licence_tier') not in ('A', 'B'):
            continue
        parts += [s.get('exact_text') or '' for s in u.get('source_spans') or []]
        parts += [n.get('text') or '' for n in u.get('numbers') or []]
        parts.append(u.get('statement') or '')
    return '\n'.join(parts)


def inspiration_findings(body, inspiration_units, units=(), source=None):
    """HARD findings for a draft against inspiration-only units (Delphi digest).

    inspiration_only_cited   the body names the source (Delphi Digital / Delphi / aliases)
    inspiration_only_text    the body reuses >= 5 consecutive words of a digest title (or the whole short title)
    inspiration_only_number  a body number equals (or rounds from) a digest key number and no public unit / source
                             text in the pack gives that number
    """
    inspiration_units = [u for u in inspiration_units or [] if u.get('licence') == 'inspiration_only']
    if not inspiration_units or not body:
        return []
    findings, low = [], body.casefold()
    for sid in sorted({u['source_id'] for u in inspiration_units}):
        for name in INSPIRATION_ALIASES.get(sid, ()):
            if re.search(r'(?<![A-Za-z])' + re.escape(name.casefold()) + r'(?![A-Za-z])', low):
                findings.append({'code': 'inspiration_only_cited', 'detail': name})
                break
    body_words = [w.casefold() for w in _WORD.findall(body)]
    body_grams = {}
    for u in inspiration_units:
        words = [w.casefold() for w in _WORD.findall(u.get('title') or '')]
        n = min(_TITLE_NGRAM, len(words))
        if n < 4:
            continue
        grams = body_grams.setdefault(n, {tuple(body_words[i:i + n]) for i in range(len(body_words) - n + 1)})
        hit = next((g for g in (tuple(words[i:i + n]) for i in range(len(words) - n + 1)) if g in grams), None)
        if hit:
            findings.append({'code': 'inspiration_only_text', 'detail': ' '.join(hit)[:80]})
    body_q = _quantities(body)
    if body_q:
        public = _quantities(_public_text(units, source))
        for u in inspiration_units:
            for kn in u.get('key_numbers') or []:
                for q in _quantities(kn.get('value')):
                    used = [b for b in body_q if _same(q, b)]
                    if used and not any(_same(p, b) or _same(b, p) for b in used for p in public):
                        # detail names the body's own figure only (it goes into the rewrite note): never the
                        # digest context or any other digest number
                        detail = ', '.join(sorted({f'{b[0]:f}' + ('%' if b[1] == 'percent' else '') for b in used}))
                        if not any(f['code'] == 'inspiration_only_number' and f['detail'] == detail for f in findings):
                            findings.append({'code': 'inspiration_only_number', 'detail': detail})
    return findings
