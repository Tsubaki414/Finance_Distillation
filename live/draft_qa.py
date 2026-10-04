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
