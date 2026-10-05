"""Sentence-level thesis / grounding check with fixed repair instructions.

Borrowed from x-account-operator (thesis adherence classes + grounding_repair /
thesis_repair reason codes). Deterministic soft checks: warn + map reason codes
to fixed rewrite instructions. Never hard-block or stall the pipeline.

Sentence classes:
  SUPPORTS_THESIS, NECESSARY_CONTEXT, HEDGE, OFF_TOPIC, UNGROUNDED_NEW_CLAIM

Triggering reason codes (soft repair):
  OFF_THESIS, UNSUPPORTED_NEW_CLAIM, UNSUPPORTED_CONSENSUS_CLAIM,
  ANALOGY_AS_EVIDENCE, CLAIM_STRENGTH_UPGRADE
"""
from __future__ import annotations

import re

SENTENCE_CLASSES = (
    'SUPPORTS_THESIS',
    'NECESSARY_CONTEXT',
    'HEDGE',
    'OFF_TOPIC',
    'UNGROUNDED_NEW_CLAIM',
)

REASON_CODES = (
    'OFF_THESIS',
    'UNSUPPORTED_NEW_CLAIM',
    'UNSUPPORTED_CONSENSUS_CLAIM',
    'ANALOGY_AS_EVIDENCE',
    'CLAIM_STRENGTH_UPGRADE',
)

# High-precision codes: soft finding + one compose retry.
# OFF_THESIS / UNSUPPORTED_NEW_CLAIM stay as span labels (advisory) — deterministic
# number matching is too noisy across 亿/$ formats to auto-repair without false positives.
REPAIR_TRIGGERS = frozenset({
    'UNSUPPORTED_CONSENSUS_CLAIM', 'ANALOGY_AS_EVIDENCE', 'CLAIM_STRENGTH_UPGRADE',
})

# Fixed repair instructions by reason code (compose rewrite_note). thesis_repair vs grounding_repair.
REPAIR_FAMILY = {
    'OFF_THESIS': 'thesis_repair',
    'UNSUPPORTED_NEW_CLAIM': 'grounding_repair',
    'UNSUPPORTED_CONSENSUS_CLAIM': 'grounding_repair',
    'ANALOGY_AS_EVIDENCE': 'grounding_repair',
    'CLAIM_STRENGTH_UPGRADE': 'grounding_repair',
}

REPAIR_INSTRUCTIONS = {
    'OFF_THESIS': (
        'Delete or rewrite sentences that do not advance the account_view / primary claim; '
        'do not add new materials. Keep the call, hedges and numbers already grounded in the units.'),
    'UNSUPPORTED_NEW_CLAIM': (
        'Remove facts, numbers or causal claims not supported by the supplied units; '
        'do not search for or invent replacement evidence.'),
    'UNSUPPORTED_CONSENSUS_CLAIM': (
        "Drop consensus / crowd wording (e.g. '市场普遍认为', '大家都觉得', 'widely believed', "
        "'everyone is watching', 'the market expects') unless a unit supplies consensus evidence."),
    'ANALOGY_AS_EVIDENCE': (
        'Analogies may explain, never prove. Drop analogy-as-evidence or reframe as explanation '
        'tied to a grounded unit; do not invent parallel cases.'),
    'CLAIM_STRENGTH_UPGRADE': (
        'Restore the uncertainty in the stance/units. Do not upgrade hedges into absolutes '
        '(彻底/一定/entirely/guaranteed/inevitable) or invent crowd panic.'),
}

_SENTENCE_SPLIT = re.compile(r'(?<!\d)[.!?。！？]|\n+')
_CONSENSUS = {
    'zh': re.compile(
        r'市场普遍(?:认为|觉得|将)|大家都(?:觉得|认为|在)|各方都|投资者都|人人都|没有人不|'
        r'一致认为|主流观点|市场恐慌|人心惶惶|惊弓之鸟|市场都'),
    'en': re.compile(
        r"\b(?:widely (?:believed|seen|expected|regarded)|broadly (?:believed|expected)|"
        r"everyone (?:is|was) watching|the market (?:is (?:afraid|spooked|panicking)|expects?|believes?|thinks?)|"
        r"most (?:investors?|traders?|analysts?) (?:believe|think|expect|agree)|"
        r"consensus (?:is|view|expects?)|investors? (?:are|were) (?:all|universally))\b", re.I),
}
_ANALOGY = {
    'zh': re.compile(r'(?:就像|如同|好比|宛如|类似(?:于)?|可以比作)[^。！？]{0,40}(?:一样|一般|证明|说明|意味着)'),
    'en': re.compile(
        r"\b(?:just like|analogous to|as if|the same way|mirrors?|parallels?)\b[^.]{0,60}"
        r"\b(?:proves?|shows?|means?|demonstrates?|confirms?)\b", re.I),
}
_HEDGE = {
    'zh': re.compile(r'可能|或许|未必|不一定|如果|除非|还要看|仍需|不足以|有待|条件是|只要|否则'),
    'en': re.compile(
        r"\b(?:may|might|could|perhaps|possibly|unlikely|unless|if\b|conditional|"
        r"depends|not enough|insufficient|still needs?|warrants?)\b", re.I),
}
_BACKGROUND = {
    'zh': re.compile(r'此前|此前披露|复盘|拆解|具体数据|根据|据|公司披露|官方'),
    'en': re.compile(
        r"\b(?:previously|historically|the data|according to|disclosed|reported|"
        r"guidance|print|figure|reading)\b", re.I),
}
_NUMBER = re.compile(
    r'(?<![A-Za-z0-9_])(?:[$€£¥]?\d[\d,]*(?:\.\d+)?%?|\d+(?:\.\d+)?(?:%|bp|bps|万|亿|点))(?![A-Za-z0-9_])')
_STOP = set('the a an and or but of to in on for with is are was were be been it its this that these those '
            'right now than from by as at into over more less most very just still also'.split())


def _tokens(text):
    words = {re.sub(r'(?:ing|ed|es|s)$', '', w) for w in re.findall(r"[a-z][a-z'-]{2,}", (text or '').lower())
             if w not in _STOP}
    cjk = re.sub(r'[^\u4e00-\u9fff]', '', text or '')
    return {w[:6] for w in words if len(w) >= 3} | {cjk[i:i + 2] for i in range(len(cjk) - 1)}


def split_sentences(body):
    return [s.strip() for s in _SENTENCE_SPLIT.split(body or '') if s and s.strip()]


def _evidence_blob(units, stance):
    view = (stance or {}).get('view') or {}
    parts = [str((stance or {}).get('account_view') or ''), str(view.get('subject') or ''),
             str(view.get('reasoning') or '')]
    for u in units or []:
        parts.append(str(u.get('statement') or ''))
        for sp in u.get('source_spans') or []:
            if isinstance(sp, dict):
                parts.append(str(sp.get('exact_text') or ''))
        for n in u.get('numbers') or []:
            parts.append(str(n.get('text') if isinstance(n, dict) else n))
    return ' '.join(parts)


def _has_consensus_evidence(units):
    blob = ' '.join(str(u.get('statement') or '') for u in (units or [])).casefold()
    return bool(re.search(
        r'consensus|survey|poll|majority|most (?:investors?|traders?|respondents?)|'
        r'市场共识|一致预期|调查|多数(?:投资者|交易者)|民意', blob))


def classify_sentence(sentence, thesis_tokens, evidence_tokens, evidence_blob, units, lang):
    """Return (class, reason_code|None, detail)."""
    lang = 'zh' if lang == 'zh' else 'en'
    s = sentence.strip()
    if not s:
        return 'NECESSARY_CONTEXT', None, ''
    stoks = _tokens(s)
    thesis_overlap = (len(stoks & thesis_tokens) / len(thesis_tokens)) if thesis_tokens else 0.0
    evid_overlap = (len(stoks & evidence_tokens) / len(stoks)) if stoks else 0.0

    if _CONSENSUS[lang].search(s) and not _has_consensus_evidence(units):
        return 'UNGROUNDED_NEW_CLAIM', 'UNSUPPORTED_CONSENSUS_CLAIM', s[:120]

    if _ANALOGY[lang].search(s):
        return 'UNGROUNDED_NEW_CLAIM', 'ANALOGY_AS_EVIDENCE', s[:120]

    blob = evidence_blob.casefold().replace(',', '')
    nums = []
    ungrounded_num = None
    for m in _NUMBER.finditer(s):
        num = m.group().replace(',', '')
        bare = re.sub(r'[$€£¥%]', '', num)
        # Years and calendar anchors (10月 / 5年 / 30日) are not metric claims.
        if re.fullmatch(r'(?:19|20)\d{2}', bare):
            continue
        if m.end() < len(s) and s[m.end()] in '年月日号':
            continue
        nums.append(bare or num)
        if bare and bare.casefold() not in blob and num.casefold() not in blob:
            ungrounded_num = m.group()
    if ungrounded_num and evid_overlap < 0.35 and thesis_overlap < 0.25:
        return 'UNGROUNDED_NEW_CLAIM', 'UNSUPPORTED_NEW_CLAIM', f'number {ungrounded_num}: {s[:100]}'
    # Numbers that all resolve into the evidence count as grounded context (cross-lang OK).
    grounded_nums = bool(nums) and ungrounded_num is None

    if _HEDGE[lang].search(s) and thesis_overlap >= 0.1:
        return 'HEDGE', None, ''

    if grounded_nums or (_BACKGROUND[lang].search(s) and evid_overlap >= 0.2):
        return 'NECESSARY_CONTEXT', None, ''
    if evid_overlap >= 0.35 and thesis_overlap < 0.2:
        return 'NECESSARY_CONTEXT', None, ''

    if thesis_overlap >= 0.25 or (thesis_overlap >= 0.15 and evid_overlap >= 0.15):
        return 'SUPPORTS_THESIS', None, ''

    if thesis_overlap < 0.1 and evid_overlap < 0.15 and len(stoks) >= 4:
        return 'OFF_TOPIC', 'OFF_THESIS', s[:120]

    if stoks and evid_overlap < 0.1 and thesis_overlap < 0.15:
        return 'UNGROUNDED_NEW_CLAIM', 'UNSUPPORTED_NEW_CLAIM', s[:120]

    return 'NECESSARY_CONTEXT', None, ''


def repair_instruction(reason_codes, *, thesis_claim=''):
    """Fixed rewrite note from reason codes (thesis_repair + grounding_repair)."""
    codes = [c for c in dict.fromkeys(reason_codes) if c in REPAIR_INSTRUCTIONS]
    if not codes:
        return ''
    parts = [REPAIR_INSTRUCTIONS[c] for c in codes]
    families = sorted({REPAIR_FAMILY[c] for c in codes})
    head = f"[{'+'.join(families)}] "
    tail = f' Frozen claim stays: {thesis_claim}' if thesis_claim else ''
    return head + ' '.join(parts) + tail


def review(body, stance, units, lang):
    """Classify each sentence; return soft findings + repair instruction.

    Also folds in certainty_overreach as CLAIM_STRENGTH_UPGRADE so EN and ZH
    share one soft repair path. Never hard-blocks.
    """
    from live import compose as compose_mod  # local import avoids cycle at module load

    lang = 'zh' if lang == 'zh' else 'en'
    thesis = str((stance or {}).get('account_view') or '')
    thesis_tokens = _tokens(thesis)
    evidence_blob = _evidence_blob(units, stance)
    evidence_tokens = _tokens(evidence_blob)

    spans = []
    reason_codes = []
    for sentence in split_sentences(body):
        klass, code, detail = classify_sentence(
            sentence, thesis_tokens, evidence_tokens, evidence_blob, units, lang)
        spans.append({'text': sentence, 'classification': klass, 'reason_code': code, 'detail': detail})
        if code:
            reason_codes.append(code)

    # Certainty / crowd-strength upgrades (existing checker) → CLAIM_STRENGTH_UPGRADE.
    for f in compose_mod.certainty_findings(body, units or [], stance, lang):
        reason_codes.append('CLAIM_STRENGTH_UPGRADE')
        spans.append({'text': '', 'classification': 'UNGROUNDED_NEW_CLAIM',
                      'reason_code': 'CLAIM_STRENGTH_UPGRADE', 'detail': f.get('detail')})

    # Dedupe codes preserving order.
    reason_codes = list(dict.fromkeys(reason_codes))
    # A single OFF_THESIS data/context line is noise; require ≥2 before soft-repair.
    off_n = sum(1 for sp in spans if sp.get('reason_code') == 'OFF_THESIS')
    if off_n < 2:
        reason_codes = [c for c in reason_codes if c != 'OFF_THESIS']
        for sp in spans:
            if sp.get('reason_code') == 'OFF_THESIS':
                sp['reason_code'] = None
                sp['classification'] = 'NECESSARY_CONTEXT'
    triggers = [c for c in reason_codes if c in REPAIR_TRIGGERS]
    findings = []
    for code in triggers:
        if code == 'CLAIM_STRENGTH_UPGRADE':
            continue  # compose.post_checks already emits certainty_overreach
        details = [sp['detail'] or sp['text'][:80] for sp in spans if sp.get('reason_code') == code]
        findings.append({
            'code': 'thesis_grounding',
            'reason_code': code,
            'repair_family': REPAIR_FAMILY[code],
            'detail': f'{code}: ' + '; '.join(d for d in details if d)[:240],
            'level': 'soft',
        })
    instruction = repair_instruction(triggers, thesis_claim=thesis[:160])
    return {
        'decision': 'REPAIR' if triggers else 'PASS',
        'reason_codes': triggers,
        'spans': spans,
        'findings': findings,
        'repair_instruction': instruction,
        'soft': True,
    }


def findings(body, stance, units, lang):
    """QA-shaped soft findings only (for post_checks)."""
    return review(body, stance, units, lang)['findings']
