"""Internal coherence (Oct 6 v4): a draft must not contradict its own line-1 call. SOFT, LLM-free.

v3 en_macro: "The Fed is likely done after a December hike" ... "I do think they pause here".
Line 1 = one more hike, then stop; the closer = stop now. Cheap heuristics, two families:
- timing: "stop AFTER one more move" in one sentence vs "stop NOW / no more moves" in another;
- direction: explicit bullish/看多 and bearish/看空 both asserted (non-negated) in one body.
Findings are soft (`internal_contradiction`); compose regenerates once on a hit.
"""
from __future__ import annotations

import re

_SPLIT = re.compile(r'(?<=[。！？!?；;])|(?<=\.)\s+|\n+')
_MOVE_EN = r'(?:hike|hikes|raise|cut|cuts|move|tightening|easing)'
AFTER_MORE = re.compile(
    r"\b(?:done|finished|stop\w*|paus\w*|end\w*|over)\b[^.?!\n]{0,40}\bafter\b[^.?!\n]{0,30}\b" + _MOVE_EN + r"\b"
    r"|\b(?:last|final|one more|another|second and final)\s+(?:rate\s+)?" + _MOVE_EN + r"\b"
    r"|再(?:加|降)(?:一次|一回)?息?(?:后|之后|就)|最后一次(?:加|降)息|(?:加|降)息[^，。]{0,8}(?:后|之后)(?:就)?(?:停|暂停|收手)",
    re.I)
STOP_NOW = re.compile(
    r"\b(?:pause|paus\w*|stop\w*|hold|done|finished)\b\s+(?:here|now|right now|already|at this meeting|from here)\b"
    r"|\bno (?:more|further) " + _MOVE_EN + r"\b|\bskip (?:the )?(?:december|next) (?:hike|cut|move)\b"
    r"|现在就(?:停|暂停|收手)|到此为止|就此(?:停|暂停|收手)|不再(?:加|降)息|(?:12月|下次)(?:不|不会)(?:加|降)息",
    re.I)
BULL = re.compile(r'\b(?:bullish|upside case wins|buy the dip)\b|看多|看涨|看好', re.I)
BEAR = re.compile(r'\b(?:bearish|downside case wins|sell the rip)\b|看空|看跌|唱空', re.I)
NEG = re.compile(r"\b(?:not|n't|no|never|hardly)\b[^.?!\n]{0,12}$|(?:不|没|未|别|并非)[^，。]{0,3}$", re.I)


def _sentences(body):
    return [s.strip() for s in _SPLIT.split(body or '') if s and s.strip()]


def _asserted(rx, sentence):
    for m in rx.finditer(sentence):
        if not NEG.search(sentence[:m.start()]):
            return m.group(0)
    return None


def internal_contradiction_findings(body):
    sents = _sentences(body)
    out = []
    after = [(i, _asserted(AFTER_MORE, s)) for i, s in enumerate(sents)]
    now = [(i, _asserted(STOP_NOW, s)) for i, s in enumerate(sents)]
    a = next(((i, m) for i, m in after if m), None)
    n = next(((i, m) for i, m in now if m and (not a or i != a[0])), None)
    if a and n:
        out.append({'code': 'internal_contradiction',
                    'detail': f'timing: "{a[1]}" (one more move, then stop) vs "{n[1]}" (stop now)'})
    bull = next((m for m in (_asserted(BULL, s) for s in sents) if m), None)
    bear = next((m for m in (_asserted(BEAR, s) for s in sents) if m), None)
    if bull and bear:
        out.append({'code': 'internal_contradiction', 'detail': f'direction: "{bull}" vs "{bear}"'})
    return out


REPAIR = ('[coherence_repair] The body contradicts its own call ({detail}). Keep line 1\'s call and make '
          'every later line agree with it: same direction, same timing and sequence (if line 1 says it '
          'stops after an event, no line may say it stops now). Do not invent facts.')
