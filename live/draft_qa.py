"""Lexical draft checks for reader advice and inconsistent numeric claims."""
import re
from decimal import Decimal
from live.numeric_fidelity import NUMBER, RANGE, quantity, MONTH_PATTERN

_SENTENCES = re.compile(r'(?<!\d)[.!?。！？;；\n]|\.(?!\d)')
_ACTION = re.compile(r'\b(?:buy|sell|short|go long|consider|add(?:ing)? exposure|recommend|should|enter|purchase)\b|买入|卖出|做多|做空|加仓|建仓|可以关注|建议', re.I)
_INSTRUMENT = re.compile(r'(?<![A-Za-z])(?!(?:OTM|ITM|DTE|USD|PMI)(?![A-Za-z]))[A-Z]{2,6}(?![A-Za-z])|\$[A-Z]{1,6}\b|\b(?:bitcoin|treasuries|stocks|shares|options|ETF|gold|oil)\b|[\u4e00-\u9fff]+\d*(?:ETF|股票)|美债|黄金|原油', 0)
_SPECIFIC = re.compile(
    r'\b(?:at|entry|strike|stop|target|limit)\b[^.;。！？]*?\d|'
    r'\d+(?:\.\d+)?\s*(?:%\s*(?:OTM|ITM)|[- ]?cent|DTE|days?\b)|'
    r'\b(?:put|call)\s+(?:fly|spread|butterfly)|'
    r'\b(?:straddle|strangle|iron condor|covered call)\b|'
    r'\d+(?:\.\d+)?(?:点|元|万)|(?:止损|目标价|入场|行权价)[^。！？]*?\d|价差|蝶式|跨式', re.I)

_ATTRIBUTION = re.compile(r'^\s*(?:(?:according to\b|据|根据).*|[\w\s&.-]+\b(?:recommends?|recommended|says?|said|advises?)\b|[\u4e00-\u9fff]+(?:建议|推荐|表示|称))', re.I)


def trade_reco_findings(body, lang):
    findings = []
    for sentence in _SENTENCES.split(body):
        if not _ACTION.search(sentence) or _ATTRIBUTION.search(sentence):
            continue
        instruments = list(_INSTRUMENT.finditer(sentence))
        if not instruments:
            continue
        if not re.search(r'^\s*(?:buy|sell|short|go long|consider|add|enter|purchase)\b|\byou should\b|\btime to (?:buy|sell)\b|买入|卖出|做多|做空|可以关注|建议', sentence, re.I):
            continue
        specifics = sentence
        for instrument in reversed(instruments):
            specifics = specifics[:instrument.start()] + ' ' + specifics[instrument.end():]
        specific = instruments and _SPECIFIC.search(specifics)
        findings.append({'code': 'trade_reco_specific' if specific else 'trade_reco_soft',
                         'detail': sentence.strip()})
    return findings


_COMPARE = re.compile(r'\b(?:from|to|through|vs\.?|versus|compared with|compared to|previous|prior|year.over.year|month.over.month)\b|从|升至|降至|前值|同比|环比|相比', re.I)
_MOVEMENT = re.compile(r'\b(?:rose|rise|rising|fell|fall|falling|added|shed|built|unwound|before|after|then)\b|上升|下降|随后', re.I)
_TIME = re.compile(r'\b(?:Q[1-4]|H[12]|20\d{2}|'+MONTH_PATTERN+r'|today|yesterday|last|current|previous)\b|\d+年|\d+月|本季|上季|去年|今年', re.I)


def _phrase(text):
    text = re.sub(r'\b(?:of|at|is|was|were|the|a|an|stands?|stood|equals?)\b|为|达到|约|是', ' ', text, flags=re.I)
    words = re.findall(r'[a-z]+|[\u4e00-\u9fff]+', text.casefold())
    return ' '.join(words[-4:])


def contradiction_findings(body):
    """Compare repeated local metric phrases, retaining units and time anchors.

    Comparison/change sentences and ranges are excluded rather than interpreted
    as simultaneous observations. Unrecognised subjects use adjacent noun words.
    """
    seen = {}; findings = []
    for sentence in _SENTENCES.split(body):
        if _COMPARE.search(sentence) or RANGE.search(sentence) or _MOVEMENT.search(sentence):
            continue
        time = tuple(m.group().casefold() for m in _TIME.finditer(sentence))
        matches = list(NUMBER.finditer(sentence))
        for i, match in enumerate(matches):
            # Dates are anchors, not metric values ('2026年9月', '7月', '15日', 'in 2026').
            if re.match(r'\s*(?:年|月|日|号)', sentence[match.end():]) or re.fullmatch(r'(?:19|20)\d{2}', match.group().strip()):
                continue
            before = sentence[matches[i-1].end() if i else 0:match.start()]
            after = sentence[match.end():matches[i+1].start() if i+1 < len(matches) else len(sentence)]
            # Strip period anchors before extracting the adjacent subject.
            before = _TIME.sub('', before)
            after = _TIME.sub('', after)
            phrase = _phrase(before) or _phrase(after)
            if not phrase:
                continue
            q = quantity(match['n'], match['s'], match['u'], match['c'])
            key = (phrase, q[1], time)
            value = Decimal(q[0])
            if key in seen:
                old = seen[key]
                denominator = max(abs(old), abs(value))
                if denominator and abs(old-value) / denominator > Decimal('0.005'):
                    findings.append({'code': 'self_contradiction', 'detail': {'metric': phrase,
                                     'values': [str(old), str(value)], 'unit': q[1]}})
            else:
                seen[key] = value
    return findings


def stale_time_findings(body, units, now=None, lang=None):
    """Conservative clause-local date/number binding for supplied cited units."""
    from live import freshness
    from datetime import date
    stale = [u for u in units if freshness.status(u, now)['status'] in ('stale', 'expired')]
    findings = []
    if stale and re.search(r"\b(?:today(?:'s)?|this week|just|latest)\b|今天|今日|本周|刚刚|最新|昨日", body, re.I):
        findings.append({'code': 'stale_time_word', 'detail': 'Current-time wording cites aged material'})
    clauses = re.split(r'[。！？!?;；\n]|\.(?:\s|$)', body)
    def number_in(clause, unit):
        unit=unit.get('unit',unit)
        values=[]
        for n in unit.get('numbers',[]):
            values += re.findall(r'\d[\d,]*(?:\.\d+)?',str(n.get('text') or ''))
        return any(re.search(r'(?<!\d)'+re.escape(v)+r'(?!\d)',clause) for v in values)
    date_pattern = r'\d{4}-\d{2}-\d{2}|(?:\d{4}年)?\d{1,2}月\d{1,2}日|\b(?:'+freshness.MONTH_PATTERN+r')\.?\s+\d{1,2}(?:,?\s+\d{4})?\b'
    for clause in clauses:
        if re.search(r'\b(?:now|currently|current)\b|目前|当前|现在',clause,re.I) and any(number_in(clause,u) for u in stale):
            if not any(f['code']=='stale_number_as_current' for f in findings):
                findings.append({'code':'stale_number_as_current','detail':clause.strip()})
        dates = re.findall(date_pattern, clause, re.I)
        event_text = re.sub(date_pattern, '', clause, flags=re.I).casefold()
        bound = []
        for row in units:
            unit = row.get('unit', row)
            statement = str(unit.get('statement') or '').strip().rstrip('.。!?！？').casefold()
            if number_in(event_text, row) or (len(statement) >= 12 and statement in event_text):
                bound.append(row)
        for stated in dates:
            comparisons=[]
            for row in bound:
                u=row.get('unit',row)
                derived=u if 'as_of' in u else freshness.derive_dates(row)
                # Normalise every candidate to YYYY-MM-DD: raw values may be ISO datetimes ending in 'Z'.
                raw=(derived.get('as_of'),u.get('published_at_norm'),u.get('published_at'),derived.get('published_at'))
                known=list(dict.fromkeys(d for d in (freshness.normalize_date(str(v)) if v else None for v in raw) if d))
                if not known: continue
                year=int(known[0][:4])
                text=stated
                if re.match(r'[A-Za-z]',text) and not re.search(r'\d{4}',text): text+=f', {year}'
                parsed=freshness.parse_period(text,year)
                if parsed:
                    comparisons.append(any(abs((date.fromisoformat(parsed)-date.fromisoformat(k)).days)<=1 for k in known))
            if comparisons and not any(comparisons):
                findings.append({'code':'wrong_date_fact','detail':clause.strip()})
    return findings
