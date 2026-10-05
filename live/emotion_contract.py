"""Emotion contract for compose (soft).

Borrowed from x-account-operator editorial_emotion_brief: from source sentences
+ stance, pick a dominant emotion and target intensity 0–5; require a real
reaction in the first two lines. Soft EMOTION_DROP when the draft is weaker
than the source/stance target — never hard-block.
"""
from __future__ import annotations

import re

# Bilingual markers (xao Chinese set + EN finance-voice equivalents).
EMOTION_MARKERS = {
    'excited': ('冲', '暴涨', '爆', '牛市', '机会', '起飞', 'bull', 'moon', 'rally', 'breakout', '🔥'),
    'anxious': ('焦虑', '恐慌', '慌', '错过', '来不及', '不安', 'overwhelmed', 'anxiety', 'panic', 'spooked', 'nervous', 'uneasy'),
    'annoyed': ('离谱', '荒谬', '烂', '骗', '割', '砸盘', '崩', 'dump', 'crash', 'nonsense', 'ridiculous', 'absurd', 'unimpressed'),
    'absurd': ('绷不住', '笑死', '人才', '搞笑', 'meme', 'lol', 'farce', 'circus', 'joke'),
    'curious': ('为什么', '怎么会', '有意思', '没想到', 'why', 'interesting', 'curious', 'odd', 'strange'),
    'skeptical': ('未必', '不足以', '还早', '撑不住', '别急', 'unlikely', 'not enough', 'skeptical', 'doubt', 'thin', 'fragile', 'overdone', 'shrug', 'tell'),
    'wary': ('警惕', '小心', '风险', '压制', 'overhang', 'wary', 'caution', 'risk', 'watch'),
    'relieved': ('松一口气', '缓和', '好转', 'relief', 'relieved', 'easing', 'cooling'),
}

# Maps to a short compose-facing label (EN; ZH personas still understand these).
EMOTION_LABEL = {
    'excited': 'excited / 兴奋',
    'anxious': 'anxious / 焦虑',
    'annoyed': 'annoyed / 不爽',
    'absurd': 'absurd / 荒诞',
    'curious': 'curious / 好奇',
    'skeptical': 'skeptical / 怀疑',
    'wary': 'wary / 警惕',
    'relieved': 'relieved / 松一口气',
}

_REACTION = re.compile(
    r"\b(?:unlikely|skeptical|doubt|thin|fragile|overdone|nonsense|ridiculous|absurd|"
    r"panic|nervous|uneasy|wary|relief|relieved|curious|odd|interesting|crash|dump|"
    r"bullish|bearish|unimpressed|impatient|annoyed)\b|"
    r'未必|不足以|还早|撑不住|别急|离谱|荒谬|焦虑|恐慌|警惕|有意思|没想到|'
    r'看好|看空|偏弱|偏强|钝化|失效|压制|韧性|乐观|悲观|别急|还早|撑不住',
    re.I,
)
_SENTENCE = re.compile(r'(?<!\d)[.!?。！？]|\n+')


def _score_text(text, markers):
    """Count marker hits; EN short tokens use word boundaries so 'odd' ≠ 'odds'."""
    low = (text or '').casefold()
    hits = 0
    for m in markers:
        m = m.casefold()
        if not m:
            continue
        if re.search(r'[a-z]', m) and not re.search(r'[一-鿿]', m):
            hits += len(re.findall(r'\b' + re.escape(m) + r'\b', low))
        else:
            hits += low.count(m)
    return hits


def _statements_from(units, stance, source=None):
    out = []
    for u in units or []:
        s = str(u.get('statement') or '').strip()
        if s:
            out.append(s)
        for sp in u.get('source_spans') or []:
            if isinstance(sp, dict) and sp.get('exact_text'):
                out.append(str(sp['exact_text']))
    st = stance or {}
    for key in ('account_view',):
        if st.get(key):
            out.append(str(st[key]))
    view = st.get('view') or {}
    for key in ('reasoning', 'subject', 'conditions'):
        if view.get(key):
            out.append(str(view[key] if not isinstance(view[key], list) else ' '.join(map(str, view[key]))))
    if source and source.get('title'):
        out.append(str(source['title']))
    return [s for s in out if s.strip()]


def build_emotion_brief(units, stance, *, source=None, lang='en'):
    """Pick dominant emotion + target intensity 0–5 from source/stance text."""
    statements = _statements_from(units, stance, source)
    joined = '\n'.join(statements).casefold()
    ranked = sorted(
        ((_score_text(joined, markers), name) for name, markers in EMOTION_MARKERS.items()),
        reverse=True,
    )
    emotions = [name for score, name in ranked if score][:2] or ['skeptical']
    marker_energy = ranked[0][0] if ranked else 0
    punct = min(2, joined.count('!') + joined.count('！'))
    # Hot / high-energy source → floor 3; stronger markers push toward 5.
    target = min(5, max(3 if marker_energy or punct else 2, 2 + int(marker_energy >= 2) + int(marker_energy >= 4) + punct))
    energetic = sorted(
        statements,
        key=lambda t: -sum(_score_text(t, ms) for ms in EMOTION_MARKERS.values()),
    )[:3]
    labels = [EMOTION_LABEL.get(e, e) for e in emotions]
    return {
        'dominant_emotions': emotions,
        'dominant_labels': labels,
        'target_intensity': int(target),
        'source_high_energy_lines': energetic,
        'required_effect': (
            'The reader must feel a real reaction from the author in the first two lines — '
            'not a calm recap of the materials.'),
        'allowed_devices': ['short lines', 'rhetorical question', 'light exaggeration',
                            'irony', 'rhythm break', 'emotion-bearing judgment verbs'],
        'boundary': 'Amplify emotion and rhetoric; never amplify fact certainty or invent lived experience.',
        'lang': 'zh' if lang == 'zh' else 'en',
    }


def draft_intensity(body, brief):
    """Heuristic 0–5 intensity of the draft vs the brief's emotion set."""
    sentences = [s.strip() for s in _SENTENCE.split(body or '') if s.strip()]
    head = ' '.join(sentences[:2])
    whole = body or ''
    emotions = (brief or {}).get('dominant_emotions') or list(EMOTION_MARKERS)
    markers = []
    for e in emotions:
        markers.extend(EMOTION_MARKERS.get(e, ()))
    # Also allow any emotion marker for intensity (register may shift slightly).
    all_markers = [m for ms in EMOTION_MARKERS.values() for m in ms]
    head_hits = _score_text(head, markers) + _score_text(head, all_markers) * 0.25
    body_hits = _score_text(whole, markers) + _score_text(whole, all_markers) * 0.2
    punct = min(2, whole.count('!') + whole.count('！') + whole.count('?') + whole.count('？'))
    reaction = 2.5 if _REACTION.search(head) else (1.0 if _REACTION.search(whole) else 0.0)
    # Map hits → 0–5.
    raw = reaction + punct + min(2.0, head_hits) + min(1.0, body_hits * 0.35)
    return max(0, min(5, int(round(raw))))


def first_two_have_reaction(body):
    sentences = [s.strip() for s in _SENTENCE.split(body or '') if s.strip()]
    head = ' '.join(sentences[:2])
    if not head:
        return False
    if _REACTION.search(head):
        return True
    return any(_score_text(head, ms) for ms in EMOTION_MARKERS.values())


def emotion_findings(body, brief):
    """Soft findings only. EMOTION_DROP when draft weaker than target without reaction."""
    if not brief:
        return []
    target = int(brief.get('target_intensity') or 0)
    intensity = draft_intensity(body, brief)
    findings = []
    has_reaction = first_two_have_reaction(body)
    # Soft gate: missing a real reaction in the first two lines (intensity is advisory).
    if target >= 3 and not has_reaction:
        findings.append({
            'code': 'emotion_drop',
            'level': 'soft',
            'detail': (f'EMOTION_DROP: draft intensity {intensity}/5 vs target {target}/5 '
                       f'({", ".join(brief.get("dominant_labels") or brief.get("dominant_emotions") or [])}); '
                       f'first_two_reaction={has_reaction}'),
            'target_intensity': target,
            'draft_intensity': intensity,
            'dominant_emotions': brief.get('dominant_emotions'),
        })
    return findings


def repair_instruction(brief, findings):
    if not findings or not brief:
        return ''
    labels = ', '.join(brief.get('dominant_labels') or brief.get('dominant_emotions') or [])
    return (
        f"[emotion_repair] Target intensity {brief.get('target_intensity')}/5 with dominant emotion(s): {labels}. "
        'Put a real reaction in the first two lines (short punchy judgment, not a calm recap). '
        'Hold one register through the post. Amplify rhetoric only — never facts or certainty. '
        f"Devices: {', '.join(brief.get('allowed_devices') or [])}."
    )
