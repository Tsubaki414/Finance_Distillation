"""Sentence -> source-span grounding for composed drafts (Oct 7, Sirius borrow item 2, lightweight).

Every factual sentence of the body is mapped to a source span: the selected units' `source_spans` first, then the
parent source text (paragraphs). A sentence is factual when it carries a number, a direct quote, a named entity or
a reporting verb (said / announced / 宣布 / 数据显示 ...). Codes:

  ungrounded_number  HARD  a number (with its unit / scale / currency, via live.numeric_fidelity) that no span holds;
                           rounding to the precision the body writes is fine (1.234bn -> 1.2bn, 45.6% -> 46%)
  ungrounded_quote   HARD  a same-language direct quote that is not a span substring (translated quotes stay the
                           existing SOFT translated_quote)
  ungrounded_entity  SOFT  a ticker / Latin-script name that appears in no span or unit statement
  ungrounded_claim   SOFT  a reporting sentence (said / announced / 宣布 ...) with no number, quote or entity hit and
                           no same-language span sharing enough words with it

Dates, years, quarters, clock times and bare counts up to 10 are anchors, not metric claims, and are skipped.
`ground()` returns (findings, map); the map is stored on the draft so a reviewer sees which span each sentence uses.
Opinion lines without facts are not checked: they are the account's call, not a claim about the source.
"""
from __future__ import annotations

import re
from decimal import Decimal

from live.draft_qa import KNOWN_ACRONYMS
from live.numeric_fidelity import DATE_EN, DATE_ZH, MONTH_PATTERN, NUMBER, normalize, quantity

VERSION = 'span-grounding-v1'
HARD_CODES = ('ungrounded_number', 'ungrounded_quote')
SOFT_CODES = ('ungrounded_entity', 'ungrounded_claim')
FIXES = {
    'ungrounded_number': ('Every number must come from the units: drop or replace the number(s) in the detail with '
                          'the exact figure the source gives (rounding is fine); do not compute or invent new ones.'),
    'ungrounded_quote': ('Quote only words that appear verbatim in the source; otherwise paraphrase without quote '
                         'marks.'),
    'ungrounded_entity': 'Name only companies, tickers and people that appear in the units.',
    'ungrounded_claim': 'Reported facts (X said / announced / data show) must be ones the units actually contain.',
}

_SENT = re.compile(r'[^。！？!?\n]+?(?:[。！？!?]+|\.(?=\s|$)|\n|$)')
_ANCHORS = re.compile(
    r'\b(?:19|20)\d{2}s?\b|\d{4}\s*年|\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?|\d{1,2}\s*[日号]|'
    r'\b[QH][1-4]\b|第?[一二三四1-4]季度|\b\d{1,2}:\d{2}\b|\b\d+(?:st|nd|rd|th)\b|'
    r'\b(?:' + MONTH_PATTERN + r')\.?\s+\d{1,2}\b|^\s*\d+[.)、]\s|#\d+', re.I | re.M)
_QUOTE = re.compile(r'“([^”]{6,})”|「([^」]{6,})」|"([^"]{6,})"')
_ENTITY = re.compile(r'\$[A-Z]{1,6}\b|(?<![\w$])[A-Z][A-Za-z0-9&.-]*[A-Z0-9][A-Za-z0-9&-]*\b|'
                     r'(?<=[a-z,;:] )[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*')
_COMMON = frozenset('''I A The This That These Those It Its We You They He She But And Or So If When While Why What How
Not No Yes Still Even Just Now Then Here There One Two All Any Each Every Most More Less Fed US USD AI CEO OK'''.split())
_REPORTING = re.compile(r"\b(?:said|says|told|announced|announces|reported|reports|according to|disclosed|filed|"
                        r"confirmed|approved|launched|data (?:show|showed)|figures? (?:show|showed))\b|"
                        r"宣布|表示|称|透露|披露|数据显示|据.{0,12}(?:报道|消息|统计)|报道|发布了|批准|证实|公告", re.I)
_CJK = re.compile(r'[一-鿿]')
_WORD = re.compile(r'[a-z0-9]+|[一-鿿]{2}', re.I)


def _is_zh(text):
    return len(_CJK.findall(text or '')) * 3 >= len((text or '').strip() or 'x')


def _fold(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip().casefold()


def spans_of(units, source=None):
    """[(ref, text)]: unit source spans, then the source document by paragraph."""
    out = []
    for u in units or []:
        for i, s in enumerate(u.get('source_spans') or []):
            text = s.get('exact_text') if isinstance(s, dict) else s
            if text:
                out.append((f"{u.get('unit_id')}#{i}", str(text)))
    for i, para in enumerate(p for p in re.split(r'\n\s*\n|\n', str((source or {}).get('original_text') or ''))
                             if p.strip()):
        out.append((f'source#p{i}', para))
    return out


def _numbers(text):
    """[(value Decimal, dim, tolerance Decimal, literal)] after removing date / period anchors."""
    clean = _ANCHORS.sub(' ', normalize(re.sub(r'https?://\S+', ' ', text or '')))
    for pattern in (DATE_EN, DATE_ZH):
        clean = pattern.sub(' ', clean)
    clean = re.sub(r'(?<![A-Za-z0-9_])[A-Za-z]+[-_]?\d+(?:\.\d+)?[A-Za-z]*(?![A-Za-z0-9_])', ' ', clean)  # H100, GLM-5
    out = []
    for m in NUMBER.finditer(clean):
        raw = m['n']
        try:
            value, dim = quantity(raw, m['s'], m['u'], m['c'])
        except Exception:   # noqa: BLE001
            continue
        value = Decimal(value)
        decimals = len(raw.split('.')[1]) if '.' in raw else 0
        scale = Decimal(value) / Decimal(raw.replace(',', '')) if Decimal(raw.replace(',', '')) else Decimal(1)
        tol = Decimal('0.5') * Decimal(10) ** -decimals * abs(scale)
        out.append((value, dim, tol, m.group().strip(), raw, m['s'] or m['u'] or m['c']))
    return out


def _number_ok(n, pool):
    value, dim, tol = n[0], n[1], n[2]
    for v, d, *_ in pool:
        if d == dim or 'number' in (d, dim):
            if abs(v - value) <= max(tol, abs(v) * Decimal('0.005')):
                return True
    return False


def _entities(sentence):
    hits = []
    for m in _ENTITY.finditer(sentence):
        word = m.group().strip(' .-')
        if (word in _COMMON or word in KNOWN_ACRONYMS or word.rstrip('s') in KNOWN_ACRONYMS or len(word) < 2
                or word.isdigit() or re.fullmatch(r'[QH][1-4]|FY\d{2,4}', word)):
            continue
        hits.append(word)
    return list(dict.fromkeys(hits))


def ground(body, units, source=None, *, published_year=None):
    """(findings, map) for one draft body. map rows: {sentence, kind, span, numbers, quotes, entities}."""
    spans = spans_of(units, source)
    span_numbers = [(ref, _numbers(text)) for ref, text in spans]
    year = published_year or str((source or {}).get('published_at') or '')[:4]
    folded = [(ref, _fold(text)) for ref, text in spans]
    known = ' '.join([t for _, t in folded] + [_fold(u.get('statement')) for u in units or []]
                     + [_fold(' '.join(str(n.get('text') or '') for n in u.get('numbers') or [])) for u in units or []])
    findings, rows = [], []
    bad_numbers, bad_quotes, bad_entities, bad_claims = [], [], [], []
    for sm in _SENT.finditer(str(body or '')):
        sentence = sm.group().strip()
        if not sentence:
            continue
        refs = []
        nums = [n for n in _numbers(sentence)
                if not (n[1] == 'number' and not n[5] and n[0] == n[0].to_integral_value() and abs(n[0]) <= 10)
                and not (year and n[4] == year)]
        for n in nums:
            ref = next((r for r, pool in span_numbers if _number_ok(n, pool)), None)
            if ref:
                refs.append(ref)
            else:
                bad_numbers.append({'number': n[3], 'sentence': sentence[:120]})
        quotes = [next(g for g in m.groups() if g).strip() for m in _QUOTE.finditer(sentence)]
        for q in quotes:
            ref = next((r for r, t in folded if _fold(q) in t), None)
            if ref:
                refs.append(ref)
            elif any(_is_zh(q) == _is_zh(t) for _, t in spans):
                bad_quotes.append({'quote': q[:80], 'sentence': sentence[:120]})
        ents = [] if quotes else _entities(sentence)
        lead = re.match(r'\s*([A-Z][a-z]{2,})\b', sentence)
        if not quotes and lead and lead.group(1) not in _COMMON and _REPORTING.search(sentence):
            ents = list(dict.fromkeys([lead.group(1)] + ents))   # "Intel announced ...": a sentence-initial name
        for e in ents:
            ref = next((r for r, t in folded if e.casefold() in t), None)
            if ref:
                refs.append(ref)
            elif e.casefold().lstrip('$') not in known:
                bad_entities.append(e)
        reporting = bool(_REPORTING.search(sentence))
        kind = ('number' if nums else 'quote' if quotes else 'entity' if ents else
                'claim' if reporting else 'opinion')
        if kind == 'claim':
            words = set(w.casefold() for w in _WORD.findall(sentence))
            best, score = None, 0.0
            for ref, text in spans:
                if _is_zh(text) != _is_zh(sentence):
                    continue
                overlap = len(words & set(w.casefold() for w in _WORD.findall(text))) / max(1, len(words))
                if overlap > score:
                    best, score = ref, overlap
            if best and score >= 0.3:
                refs.append(best)
            elif any(_is_zh(t) == _is_zh(sentence) for _, t in spans):   # cross-language: lexical check can't judge
                bad_claims.append(sentence[:120])
        rows.append({'sentence': sentence[:200], 'kind': kind, 'span': refs[0] if refs else None,
                     'spans': list(dict.fromkeys(refs))})
    if bad_numbers:
        findings.append({'code': 'ungrounded_number', 'detail': bad_numbers[:6]})
    if bad_quotes:
        findings.append({'code': 'ungrounded_quote', 'detail': bad_quotes[:4]})
    if bad_entities:
        findings.append({'code': 'ungrounded_entity', 'detail': list(dict.fromkeys(bad_entities))[:8]})
    if bad_claims:
        findings.append({'code': 'ungrounded_claim', 'detail': bad_claims[:4]})
    return findings, rows


def findings(body, units, source=None):
    return ground(body, units, source)[0]
