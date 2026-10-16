"""Oct 16: soft 'AI-slop score' for drafts (FD_SLOP_SCORE, default on; 0 = off / rollback).

Every tell adds points to one per-post score. A single tell is weak (< THRESHOLD); stacked tells or a dense
cluster reach it. Over THRESHOLD -> one rewrite retry (deterministic cuts, then the humanize LLM rewrite with the
hit sentences listed); still over -> HOLD (hard post_check `ai_slop_score`, needs_review), never published.

Exempt: text inside quotation marks, and any sentence carrying a numeric fact (digits) for the weak lexical tells
(rule of three, promo / AI vocabulary, dash density). The structural "not X, it's Y" family is still scored.
Source of the rules: slop_lessons_zh.md (video notes) + detectors_test.py.
Env: FD_SLOP_SCORE (0 off), FD_SLOP_THRESHOLD (default 3.0).
"""
from __future__ import annotations

import os
import re

THRESHOLD = 3.0
STRONG, MEDIUM, WEAK = 2.0, 1.0, 0.5


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_SLOP_SCORE', '1') != '0'


def threshold(env=None):
    try:
        return float((env if env is not None else os.environ).get('FD_SLOP_THRESHOLD', THRESHOLD))
    except ValueError:
        return THRESHOLD


_SEP = r"(?:[,;:—–-]|[.!?]\s+)\s*"
# ---- structural tells: code -> (weight, regex). Matched on the whole (quote-masked) text.
EN = {
    'neg_par_just': (STRONG, r"\b(?:isn['’]t|aren['’]t|wasn['’]t|weren['’]t|is not|are not|was not|not)\s+(?:just|merely|only|simply)\b[^.!?\n]{0,60}?" + _SEP
                     + r"(?:it['’]s|it is|they['’]re|that['’]s|but|this is|we['’]re|you['’]re|rather)\b"),
    'dont_just': (STRONG, r"\b(?:don['’]t|doesn['’]t|didn['’]t|won['’]t|do not|does not)\s+(?:just|merely|simply)\b[^.!?\n]{0,60}?" + _SEP
                  + r"(?:they|it|he|she|we|you)\b"),
    'not_only_but': (STRONG, r"\bnot only\b[^.!?\n]{1,80}?\bbut(?: also)?\b"),
    'no_x_no_y_just_z': (STRONG, r"\bno [\w\s-]{1,25}?,\s*no [\w\s-]{1,25}?,?\s*(?:just|only)\b"),
    'think_of': (STRONG, r"\b(?:think of (?:it|this|these|them|your [\w\s]{1,20}?) (?:as|like)|picture (?:this|yourself)|imagine (?:waking|a world|if|this|that|you))\b"),
    'real_question': (MEDIUM, r"\b(?:the real (?:question|problem|issue|test|story) (?:is|here)|the (?:real|actual) (?:question|issue) (?:isn['’]t|is not))\b"),
}
ZH = {
    'bu_zhi': (STRONG, r"不(?:只|仅|单|光|止)是?[^。！？\n]{1,30}?[，,；;：:—]\s*(?:更是|还是|也是|而是|是|更)"),
    'bu_jin': (STRONG, r"不仅(?:仅)?(?:是)?[^。！？\n]{1,30}?[，,]?\s*(?:而且|更是|更|还|也)"),
    'bu_zai': (STRONG, r"不再是[^。！？\n]{1,24}?[，,；]\s*(?:而)?是"),
    'bu_shi_period': (MEDIUM, r"(?:这|它|那)?(?:并)?不是[^。！？\n]{1,24}?[。！]\s*(?:而)?是"),
    'meiyou_zhiyou': (STRONG, r"没有[^，。]{1,10}[，、]\s*没有[^，。]{1,10}[，、]?\s*只有"),
    'think_of': (STRONG, r"想象一下|(?:不妨|可以)?把(?:它|这|这个)想成|试想一下"),
    'zhen_zheng': (MEDIUM, r"(?:真正|真实)(?:的)?(?:问题|关键|考验|意义|挑战)(?:在于|是|就是)"),
}
EN_PROMO = (MEDIUM, r"\b(?:welcome to the (?:future|next)|game[- ]chang\w+|unprecedented|transformative|redefin\w+|ushering in|poised to|a (?:true )?testament to|"
            r"groundbreaking|paradigm|revolutioni[sz]\w*|seamless\w*|stunning)\b")
ZH_PROMO = (MEDIUM, r"重塑|重构|范式|新纪元|划时代|里程碑|颠覆|前所未有|深刻(?:改变|影响)|开启了?.{0,6}新(?:篇章|时代)|革命性")
EN_RULE3_ADV = (WEAK, r"\b\w+, \w+,? and (?:\w+ly|ultimately|truly|genuinely) \w+\b")
# ZH three-list whose last item is a vague filler noun (情绪 / 信心 / 预期 ...) - plain 三连 of facts is not scored
_ZH_FILLER = r"(?:情绪|信心|预期|格局|生态|趋势|影响|变化|叙事|氛围|心态|周期|逻辑)"
ZH_RULE3 = (WEAK, r"[\u4e00-\u9fff]{2,5}、[\u4e00-\u9fff]{2,5}(?:、|和|与|以及)[\u4e00-\u9fff]{0,3}" + _ZH_FILLER)
# EN three-list whose last (or any) item is a filler abstraction
_EN_FILLER = r"(?:sentiment|confidence|momentum|narrative|dynamics|expectations|uncertainty|volatility|trends?|impact|vibes|energy)"
EN_RULE3_FILLER = (WEAK, r"\b[a-z]+, [a-z]+,? and " + _EN_FILLER + r"\b")

# AI vocabulary (lessons list; 'shift', 'significant', 'deep', 'leap', 'leverage', 'fundamentals', 'unlock' left out: ordinary finance / token words)
AI_VOCAB_EN = re.compile(r"\b(?:transform\w*|enhanc\w+|profound\w*|genuine\w*|vital|crucial\w*|robust\w*|vibrant|fundamental(?!s)|effortless\w*|"
                         r"groundbreaking|landscape\w*|empower\w*|unprecedented|testament|tapestry|delve\w*|pivotal|navigat\w+|realm|elevat\w+)\b", re.I)
AI_VOCAB_ZH = re.compile(r"赋能|至关重要|彰显|深刻|变革|助力|全方位|不可或缺|引领|底层逻辑|格局")

_QUOTED = re.compile(r'[“"「『][^”"」』\n]{4,}[”"」』]')
_DIGIT = re.compile(r'\d')
_SENT = re.compile(r'[^。！？!?.\n]+(?:[。！？!?]+|\.(?!\d)|\n|$)')


def _lang(lang):
    return 'zh' if str(lang or '').lower().startswith('zh') else 'en'


def _mask_quotes(text):
    return _QUOTED.sub(lambda m: 'Q' * len(m.group(0)), text or '')


def _hit(rx, text, flags=0):
    m = re.search(rx, text, flags)
    return m.group(0).strip() if m else None


def score(body, lang):
    """-> {'score': float, 'tells': [{'code','weight','text'}]}. Pure function, no I/O."""
    lg = _lang(lang)
    text = _mask_quotes(body or '')
    tells = []

    def add(code, weight, snippet):
        tells.append({'code': code, 'weight': weight, 'text': snippet[:80]})

    # structural tells (both languages are checked: EN phrases do appear in zh posts and vice versa)
    for table, flags in ((EN, re.I), (ZH, 0)):
        for code, (w, rx) in table.items():
            m = _hit(rx, text, flags)
            if m:
                add(code, w, m)
    # lexical / weak tells run per sentence; a sentence with digits (numeric fact) is exempt
    ai_en, ai_zh = set(), set()
    for s in (m.group(0) for m in _SENT.finditer(text)):
        if _DIGIT.search(s):
            continue
        for code, (w, rx), flags in (('promo_en', EN_PROMO, re.I), ('promo_zh', ZH_PROMO, 0),
                                     ('rule3_filler', EN_RULE3_FILLER, re.I), ('rule3_adv', EN_RULE3_ADV, re.I),
                                     ('rule3_zh', ZH_RULE3, 0)):
            m = _hit(rx, s, flags)
            if m:
                add(code, w, m)
        ai_en.update(x.lower() for x in AI_VOCAB_EN.findall(s))
        ai_zh.update(AI_VOCAB_ZH.findall(s))
    n_ai = len(ai_en) + len(ai_zh)
    if n_ai >= 2:   # density: >= 2 distinct AI words in one post
        add('ai_vocab', MEDIUM if n_ai == 2 else STRONG, ', '.join(sorted(ai_en | ai_zh)))
    # dash density (numeric exemption does not apply: the dash is the tell). EN em-dash, ZH 「——」
    n_en = text.count('—') - 2 * text.count('——')
    n_zh = text.count('——')
    if lg == 'en' and n_en >= 2:
        add('em_dash', MEDIUM if n_en == 2 else STRONG, f'{n_en} em-dashes')
    elif lg == 'zh' and n_zh >= 1:
        add('zh_dash', WEAK if n_zh == 1 else MEDIUM + WEAK, f'{n_zh} ——')
    total = round(sum(t['weight'] for t in tells), 2)
    return {'score': total, 'tells': tells}


def over(result, env=None):
    return result['score'] >= threshold(env)


def hit_sentences(body, tells):
    """Sentences that carry a tell snippet (for the rewrite prompt)."""
    out = []
    for s in (m.group(0).strip() for m in _SENT.finditer(body or '')):
        if s and any(t['text'].split('…')[0][:12] and t['text'][:12] in s for t in tells) and s not in out:
            out.append(s)
    return out[:6]


def finding(result):
    codes = ', '.join(f"{t['code']}({t['weight']})" for t in result['tells'])
    return {'code': 'ai_slop_score', 'level': 'hard', 'severity': 'hard',
            'detail': f"score {result['score']} >= {threshold()}: {codes}"[:200]}


def gate(row, lang, client=None, rewrite=None):
    """Score row['body']; over threshold -> one retry; still over -> returns [hard finding] (caller HOLDs).
    Returns (findings, info). Edits row['body'] / row['text'] in place only when the retry lowers the score under
    every existing guard (fidelity / entities / length / edit_guard). Never raises."""
    if not enabled():
        return [], None
    body = row.get('body') or ''
    if not body.strip():
        return [], None
    lang = _lang(lang)
    first = score(body, lang)
    info = {'score': first['score'], 'tells': [t['code'] for t in first['tells']], 'threshold': threshold()}
    if not over(first):
        return [], info
    cur, cur_res = body, first
    try:
        from live import humanize as hum
        # 1. deterministic: cut a neat moral line, compress dashes (also zh)
        cut, removed = hum.drop_moral_line(cur, lang)
        if removed:
            cur = cut
        from live import nat_tex
        cur, _ = nat_tex.compress_dashes(cur, lang)
        # 2. LLM: the existing humanize rewrite, told which sentences read as template
        if client is not None and cur_res and score(cur, lang)['score'] >= threshold():
            hits = hit_sentences(cur, score(cur, lang)['tells'])
            donor = []
            persona_name = row.get('account_id') or ''
            try:
                from live import registry
                p = registry.persona_for_account(row.get('account_id') or '')
                persona_name = p.name
                donor = hum._load_donor_posts(p.persona_id, lang)
            except Exception:   # noqa: BLE001
                pass
            fn = rewrite or hum._llm_rewrite
            new = fn(client, {**row, 'body': cur}, lang, donor, persona_name,
                     extra_issues='AI-template phrasing (not-X-but-Y / think-of-it-as / no X no Y just Z / promo words / '
                                  'stacked dashes / filler lists); say the plain point directly. Sentences: ' + ' | '.join(hits))
            if new and new != cur and hum._fidelity_ok(cur, new) and hum._entities_ok(cur, new) \
                    and len(new) <= max(len(cur) * 1.15, len(cur) + 20) \
                    and score(new, lang)['score'] < score(cur, lang)['score']:
                cur = new
                info['llm'] = True
    except Exception as exc:   # noqa: BLE001 - the retry is best effort; the hold below is the safety net
        info['retry_error'] = str(exc)[:120]
    final = score(cur, lang)
    if cur != body and final['score'] < first['score']:
        raw = row.get('body')
        row['body'] = cur
        if row.get('text') == raw:
            row['text'] = cur
        elif raw and raw in str(row.get('text') or ''):
            row['text'] = str(row['text']).replace(raw, cur, 1)
        info['retried'] = True
    else:
        final = first if cur != body else final
    info['after'] = final['score']
    if over(final):
        info['held'] = True
        return [finding(final)], info
    return [], info
