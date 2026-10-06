"""Emotion contract for compose (soft).

Borrowed from x-account-operator editorial_emotion_brief: from source sentences
+ stance, pick a dominant emotion and target intensity 0–5; require a real
reaction in the first two lines. Soft EMOTION_DROP when the draft is weaker
than the source/stance target — never hard-block.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Bilingual markers (xao Chinese set + EN finance-voice equivalents).

TIERS_PATH = Path(__file__).with_name('emotion_tiers.json')


def _load_tiers():
    return json.loads(TIERS_PATH.read_text())


def persona_tier(account_id):
    """Return tier name for an account/persona id (high|mid|low)."""
    cfg = _load_tiers()
    return (cfg.get('personas') or {}).get(account_id) or cfg.get('default_tier') or 'mid'


def restrained_devices(account_id):
    """v11 follow-up: personas listed in emotion_tiers.json restrained_devices_personas (zh_macro, zh_industry)
    lose irony / light exaggeration and carry the restraint rule. Data-driven, never 'lang == zh'."""
    return account_id in (_load_tiers().get('restrained_devices_personas') or ())


def why_cites_fact_en(account_id):
    """v11 follow-up: EN personas (crypto_macro_en) whose why sentence must cite a fact, not just 'X said'."""
    return account_id in (_load_tiers().get('why_cites_fact_en_personas') or ())


def tier_policy(account_id):
    """Resolved policy dict for this persona: target, retry, findings, include_brief."""
    cfg = _load_tiers()
    name = persona_tier(account_id)
    base = dict((cfg.get('tiers') or {}).get(name) or {})
    base['tier'] = name
    base['account_id'] = account_id
    return base

EMOTION_MARKERS = {
    'excited': ('冲', '暴涨', '爆', '牛市', '机会', '起飞', 'bull', 'moon', 'rally', 'breakout', '🔥'),
    'anxious': ('焦虑', '恐慌', '慌', '错过', '来不及', '不安', 'overwhelmed', 'anxiety', 'panic', 'spooked', 'nervous', 'uneasy'),
    'annoyed': ('离谱', '荒谬', '烂', '骗', '割', '砸盘', '崩', 'dump', 'crash', 'nonsense', 'ridiculous', 'absurd', 'unimpressed'),
    'absurd': ('绷不住', '笑死', '人才', '搞笑', 'meme', 'lol', 'farce', 'circus', 'joke'),
    'curious': ('为什么', '怎么会', '有意思', '没想到', 'why', 'interesting', 'curious', 'odd', 'strange'),
    'skeptical': ('未必', '不足以', '还早', '撑不住', '别急', '怀疑', '存疑', '打问号', '打个问号', '不买账', 'unlikely', 'not enough', 'skeptical', 'doubt', 'thin', 'fragile', 'overdone', 'shrug', 'tell'),
    'wary': ('警惕', '小心', '风险', '压制', 'overhang', 'wary', 'caution', 'risk', 'watch'),
    'relieved': ('松一口气', '缓和', '好转', 'relief', 'relieved', 'easing', 'cooling'),
}

# High-arousal registers. Only these may push a HIGH persona to intensity 5 or count as overfire.
HOT_EMOTIONS = ('excited', 'anxious', 'annoyed', 'absurd')

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
    r"shrug\w*|stubborn\w*|trapped|questionable|doubtful|not convinced|hard to believe|distraction|screaming|asleep|mistake|starved|too (?:cheap|rich|early|late|complacent)|losing (?:its|their) grip|don't front-run|isn't landing|wrong|misread\w*|mispric\w*|underpric\w*|overpric\w*|complacen\w*|bias|trap|blind\w*|ignor\w*|overreact\w*|hype\w*|stretched|frothy|premature|overstat\w*|understat\w*|bullish|bearish|unimpressed|impatient|annoyed)\b|"
    r'未必|不足以|还早|撑不住|别急|离谱|荒谬|焦虑|恐慌|警惕|有意思|没想到|'
    r'怀疑|存疑|打个?问号|不买账|持保留|'
    r'根本不|免疫|无法主导|只会引来|别碰|别追|误判|错杀|高估|低估|过度|太早|想多了|陷阱|别被|当心|不对劲|看错|反应过度|泡沫|站不住|谈不上|看好|看空|偏弱|偏强|钝化|失效|压制|韧性|乐观|悲观|别急|还早|撑不住',
    re.I,
)
# Dry source = at most this many emotion-marker hits in the dominant register and no '!'.
DRY_SOURCE_MAX_MARKERS = 1
# Lowest accept_intensity per tier under the dry-source clamp (LOW is not clamped).
DRY_CLAMP_FLOOR = {'mid': 2, 'high': 3}

_SENTENCE = re.compile(r'(?<!\d)[.!?。！？]|\n+')


# Per-tier effect (Oct 6 root cause): line 1 must paraphrase thesis_lock, and stance writes that
# call as a plain analytic sentence, so a neutral paraphrase left no slot for the reaction the brief
# asked for "in the first two lines" (line 2 is evidence by signature). The effect now says WHERE the
# register goes: inside the line-1 call itself. LOW is restrained conviction, not emotion.
REQUIRED_EFFECT = {
    None: ('The reader must feel a real reaction from the author in the first two lines — '
           'not a calm recap of the materials.'),
    'high': ('Line 1 is the thesis_lock call said WITH the dominant emotion (an emotion-bearing verb, '
             'a short punchy framing, irony or a rhetorical jab) — never a neutral restatement of '
             'thesis_lock. The reader must feel the author react in the first two lines.'),
    # v4: no example words here - the v3 list (怀疑 / 警惕 / 别急 ...) became the opener of every
    # MID draft (zh_macro opened 别急 three drafts in a row). Describe the effect, not the lexeme.
    'mid': ('Line 1 is the thesis_lock call carrying one clear reaction from the dominant emotion, in '
            'words of your own that differ from your recent openers - a neutral paraphrase of '
            'thesis_lock reads as a calm recap.'),
    # v4: no conditional examples ("only if" / 除非) - they fed the conditional line-1 skeleton.
    'low': ('Restrained: line 1 is a committed call in plain words - a clear stance verb or negation, '
            'stated unconditionally. Conviction, not emotion: no hype, no exclamation marks, no rhetorical jabs.'),
}


# v11 (Oct 6 root cause #3): ZH drafts used attitude instead of explanation (走过场 / 打没了 / 直接放话,
# intensifiers 19.6 per 1k CJK chars vs donors 1.5). Restrained personas (emotion_tiers.json
# restrained_devices_personas: zh_macro, zh_industry) never get irony, a jab or exaggeration; the emotion
# rides on the judgment verb. Crypto / HIGH personas keep their devices and required_effect (Fiona follow-up).
RESTRAINED_NO_DEVICES = ('light exaggeration', 'irony')
ZH_EMOTION_RULE = '情绪靠判断动词带出来，不靠夸张、反讽或强化词（直接、纯粹、根本、完全、彻底、一点都不、毫无、砸到、放话）。'


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


def build_emotion_brief(units, stance, *, source=None, lang='en', account_id=None, tier=None):
    """Pick dominant emotion + target intensity 0–5 from source/stance text.

    When account_id/tier is set, clamp target to that persona tier's policy.
    """
    statements = _statements_from(units, stance, source)
    joined = '\n'.join(statements).casefold()
    ranked = sorted(
        ((_score_text(joined, markers), name) for name, markers in EMOTION_MARKERS.items()),
        reverse=True,
    )
    emotions = [name for score, name in ranked if score][:2] or ['skeptical']
    marker_energy = ranked[0][0] if ranked else 0
    punct = min(2, joined.count('!') + joined.count('！'))
    policy = None
    if tier or account_id:
        policy = tier_policy(account_id) if account_id else dict((_load_tiers().get('tiers') or {}).get(tier) or {}, tier=tier)
    # Base intensity from source energy, then clamp into the persona tier band.
    raw = 2 + int(marker_energy >= 1) + int(marker_energy >= 3) + int(marker_energy >= 5 or punct >= 2)
    if policy:
        floor = int(policy.get('target_intensity') or 3)
        ceil = int(policy.get('target_intensity_max') or (4 if policy.get('tier') == 'high' else floor))
        if policy.get('tier') == 'high':
            # 5 only for a genuinely hot source register; 'wary'/'skeptical' saturate on finance
            # vocabulary (risk/watch) and pushing them to 5 is what made HIGH personas overfire.
            hot_source = emotions[0] in HOT_EMOTIONS and marker_energy >= 5
            target = max(floor, min(5 if hot_source or punct >= 2 else ceil, max(raw, floor)))  # ~4
        elif policy.get('tier') == 'low':
            # Restrained voice: stay at the floor. Finance vocabulary (risk / watch / caution) saturates
            # 'wary', which used to lift LOW to 3 on almost every macro source (Oct 6: en_macro 3/3).
            # Only a genuinely hot source register may lift LOW to its ceiling.
            hot_source = emotions[0] in HOT_EMOTIONS and marker_energy >= 3
            target = min(ceil, max(floor, raw)) if hot_source else floor   # 2 (3 only when hot)
        else:
            target = floor                                        # ~3
    else:
        target = min(5, max(3, raw))  # legacy default when no persona tier
    # Dry-source clamp (PM relax 2026-10-05 eve). target_intensity is unchanged (the prompt still
    # aims at it); accept_intensity is the floor the existing soft emotion retry may accept when
    # the source text itself is dry. MID/HIGH only, one step down, never below 2 (MID) / 3 (HIGH),
    # never above target. LOW and any non-dry source: accept_intensity == target.
    tier_name = (policy or {}).get('tier')
    source_dry = marker_energy <= DRY_SOURCE_MAX_MARKERS and punct == 0
    accept = int(target)
    if source_dry and tier_name in DRY_CLAMP_FLOOR:
        accept = min(int(target), max(int(target) - 1, DRY_CLAMP_FLOOR[tier_name]))
    energetic = sorted(
        statements,
        key=lambda t: -sum(_score_text(t, ms) for ms in EMOTION_MARKERS.values()),
    )[:3]
    labels = [EMOTION_LABEL.get(e, e) for e in emotions]
    restrained = restrained_devices(account_id)
    return {
        'dominant_emotions': emotions,
        'dominant_labels': labels,
        'target_intensity': int(target),
        'source_dry': bool(source_dry),
        'accept_intensity': int(accept),
        'tier': (policy or {}).get('tier'),
        'emotion_retry': bool((policy or {}).get('emotion_retry')),
        'source_high_energy_lines': energetic,
        'required_effect': REQUIRED_EFFECT.get((policy or {}).get('tier'), REQUIRED_EFFECT[None]),
        # v9: ZH drops 'rhetorical question' (v7/v8 ZH openers ran 3/4 and 1/2 questions; donors ~6%).
        # v11: restrained personas also drop 'light exaggeration' and 'irony' (RESTRAINED_NO_DEVICES).
        'allowed_devices': [d for d in ('short lines', 'rhetorical question', 'light exaggeration',
                                        'irony', 'rhythm break', 'emotion-bearing judgment verbs')
                            if not (lang == 'zh' and d == 'rhetorical question')
                            and not (restrained and d in RESTRAINED_NO_DEVICES)],
        **({'zh_rule': ZH_EMOTION_RULE} if restrained and lang == 'zh' else {}),
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


def first_two_have_judgment(body):
    """Committed-call marker (compose.JUDGMENT_MARKERS) in the first two lines; LOW tier only."""
    from live.compose import JUDGMENT_MARKERS
    sentences = [s.strip() for s in _SENTENCE.split(body or '') if s.strip()]
    return bool(JUDGMENT_MARKERS.search(' '.join(sentences[:2])))


def emotion_findings(body, brief):
    """Soft findings only. EMOTION_DROP when draft weaker than target without reaction."""
    if not brief:
        return []
    target = int(brief.get('target_intensity') or 0)
    intensity = draft_intensity(body, brief)
    findings = []
    has_reaction = first_two_have_reaction(body)
    if brief.get('tier') == 'low':
        # LOW = restrained register: a committed call in the first two lines IS the target voice.
        # Only a calm recap (no reaction AND no judgment marker) under target is an emotion_drop.
        drop = not has_reaction and not first_two_have_judgment(body) and intensity < target
    else:
        # Soft gate: missing a real reaction in the first two lines (intensity is advisory).
        drop = not has_reaction and target >= 3
    if drop:
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


def dry_source_accepts(body, brief):
    """True when the dry-source clamp accepts this draft's intensity (MID/HIGH only)."""
    if not brief or not brief.get('source_dry') or brief.get('tier') not in DRY_CLAMP_FLOOR:
        return False
    accept = int(brief.get('accept_intensity') or brief.get('target_intensity') or 0)
    return accept < int(brief.get('target_intensity') or 0) and draft_intensity(body, brief) >= accept


def retry_improved(first_body, retry_body, brief, lang, first_findings, retry_findings):
    """Acceptance rule for the soft emotion retry.

    (reason, ok): ok when the retry clears an emotion finding ('fewer_findings'), or — dry-source
    clamp, MID/HIGH only — when emotion_drop still fires but the retry reaches accept_intensity,
    is strictly more intense than the first draft, and adds no emotion_overfire
    ('dry_source_clamp'). The clamp only lowers the acceptance bar; it never raises a target.
    """
    if len(retry_findings) < len(first_findings):
        return 'fewer_findings', True
    if (dry_source_accepts(retry_body, brief)
            and draft_intensity(retry_body, brief) > draft_intensity(first_body, brief)
            and len(overfire_findings(retry_body, brief, lang)) <= len(overfire_findings(first_body, brief, lang))):
        return 'dry_source_clamp', True
    return None, False


def repair_instruction(brief, findings):
    if not findings or not brief:
        return ''
    labels = ', '.join(brief.get('dominant_labels') or brief.get('dominant_emotions') or [])
    return (
        f"[emotion_repair] Target intensity {brief.get('target_intensity')}/5 with dominant emotion(s): {labels}. "
        'Put a real reaction in the first two lines (short punchy judgment, not a calm recap). '
        'Hold one register through the post. Amplify rhetoric only — never facts or certainty. '
        f"Devices: {', '.join(brief.get('allowed_devices') or [])}. "
        'Do not add crowd feelings (市场都/大家都/everyone is panicking), absolutes, superlatives, '
        "or more than one exclamation mark; the reaction is the author's own judgment, not invented market mood."
    )


def overfire_findings(body, brief, lang):
    """Advisory ceiling for rhetoric, including restrained persona tiers."""
    if brief is None:
        return []
    body = body or ''
    reasons = []
    exclamations = body.count('!') + body.count('！')
    if exclamations > 2:
        reasons.append(f'{exclamations} exclamation marks')
    # Hot-register words only (hype / panic / scorn / meme). Skeptical or wary judgment words are
    # the restrained voice we want, so draft_intensity (which counts them) is not used here.
    hot = sum(_score_text(body, EMOTION_MARKERS[e]) for e in HOT_EMOTIONS)
    limit = 4 if brief.get('tier') == 'high' else 2
    if hot > limit:
        reasons.append(f'{hot} hot-register words (limit {limit} for tier {brief.get("tier") or "default"})')
    # Pictographic emoji only; market symbols such as ▲▼ ° stay allowed for chart personas.
    emojis = sum(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in body)
    if lang in ('zh', 'en') and emojis >= 2:
        reasons.append(f'{emojis} emoji/symbols')
    return [{'code': 'emotion_overfire', 'level': 'soft', 'detail': '; '.join(reasons)}] if reasons else []
