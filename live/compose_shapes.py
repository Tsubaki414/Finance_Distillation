"""Composition shapes: structure variety across drafts (Oct 6 v4, PM review of v3).

Root cause of the v3 monotony: every judgment post ran one skeleton - line 1 = call + condition,
2-3 data lines, closing falsifier (除非 / 只要 / 若 / "flips if" / "provided"). It came from the
recipe, not the model: STANCE asked for a "falsifiable call" (so thesis_lock carried the
condition), COMPOSE asked to "end on what would change it", the industry signature cards made
"end on a falsifiable call" HARD, and the Fiona POS line said "concrete falsifier".

Fix: each compose gets ONE composition_shape (structure, number limit, ending family, length
band, line-break habit). Shapes per persona are derived from donor observations where available
(signature closings -> ending families, posting_habits.length_mix -> length weights). Selection
rotates against the persona's recent history and the shapes already used in the same batch, so
consecutive drafts per persona and drafts in one matrix batch do not share a shape, long and
short alternate, and the conditional-falsifier ending stays a minority (only `short_thread`).
Soft cross-draft checks (structure_repeat) back this up; they never hard-block.
"""
from __future__ import annotations

from hashlib import sha256
import re

# ending families
FALSIFIER, VERDICT, IMPLICATION, QUESTION = 'falsifier', 'verdict', 'implication', 'question'

SHAPES = {
    'take_short': {
        'length': 'short', 'max_numbers': 0, 'max_number_lines': 0, 'ending': VERDICT,
        'line_breaks': 'one block or two lines; do NOT break after every sentence',
        'en': ('Take-only short post: the call plus one sharp supporting thought, no numbers at all. '
               '2-3 sentences, may be a single block. End on a flat, committed verdict line.'),
        'zh': ('短观点：判断；一句为什么（因为/背后是…）；一句这对市场/读者有什么影响（对…来说、说白了…），全文不出现数字。'
               '3 句，可以一段写完，不必每句换行。结尾是一句干脆的定论。'),
    },
    'one_number_punch': {
        'length': 'short', 'max_numbers': 1, 'max_number_lines': 1, 'ending': IMPLICATION,
        'line_breaks': 'two or three short lines',
        'en': ('One-number punch: the call, then the single number that carries it, then one line on '
               'what that number means for the call. Exactly one number. Short.'),
        'zh': ('一个数字定胜负：先判断；再用唯一一个最有分量的数字说清为什么（因为/背后是…）；'
               '最后一句用大白话说这对市场/读者有什么影响（对…来说/说白了/接下来要看…）。全文只用一个数字，短。'),
    },
    'contrarian_question': {
        'length': 'short', 'max_numbers': 1, 'max_number_lines': 1, 'ending': QUESTION,
        'line_breaks': 'two or three short lines',
        'en': ('Contrarian question: line 1 states the call against the consensus read; one line of '
               'evidence (at most one number); end on a pointed open question that reframes the debate '
               '(not a conditional).'),
        'zh': ('反问式：首句给出与主流解读相反的判断；一句为什么（因为/背后是… + 证据，最多一个数字）；'
               '结尾用一个尖锐的反问收住，反问要点出这对市场有什么影响，不要写成条件句。'),
    },
    'thesis_mechanism': {
        'length': 'medium', 'max_numbers': 1, 'max_number_lines': 1, 'ending': IMPLICATION,
        'line_breaks': 'short paragraphs of one or two sentences',
        'en': ('Thesis + mechanism: the call, then WHY it works - one causal mechanism in plain words '
               '(how A drives B), at most one number. End on what it means (who gains, what is not priced).'),
        'zh': ('判断+机制：先判断，再用大白话讲清一个传导机制（A 怎么推动 B），最多一个数字。'
               '结尾落在含义上（谁受益、市场还没定价什么）。'),
    },
    'data_punch': {
        'length': 'medium', 'max_numbers': 3, 'max_number_lines': 3, 'ending': VERDICT,
        'line_breaks': 'call, then data lines, then the landing line',
        'en': ('Data punch: the call, then two or three numbers that carry it (separate short lines are '
               'fine here), then a blunt verdict line. The only shape that may stack number lines.'),
        'zh': ('数据连击：先判断，再用两三个数字撑住（可以分行），数字前后用一句话说清它们为什么撑得住判断；'
               '最后一句直接定性，并说这对市场有什么影响。只有这个结构允许连续的数字行。'),
    },
    'short_thread': {
        'length': 'long', 'max_numbers': 3, 'max_number_lines': 2, 'ending': FALSIFIER,
        'line_breaks': 'three or four short paragraphs',
        'en': ('Short thread-style post: the call; one paragraph on the mechanism; one on the evidence '
               '(at most two lines with numbers); close on the concrete condition that would prove the '
               'call wrong.'),
        'zh': ('小长文：判断；一段讲机制；一段讲证据（带数字的行最多两行）；'
               '结尾写清什么条件出现说明判断错了。'),
    },
}
LENGTH_BAND = {'short': (0.0, 0.35), 'medium': (0.3, 0.7), 'long': (0.6, 1.0)}
# Closing-family keywords in signature cards (donor observations) -> ending families.
_CLOSING_FAMILY = (
    (QUESTION, re.compile(r'question|反问|问句|[?？]', re.I)),
    (FALSIFIER, re.compile(r'conditional|falsif|trigger|推翻|可证伪|只要|除非|若|否则|caveat', re.I)),
    (VERDICT, re.compile(r'verdict|commit|kicker|结论|定论|一句', re.I)),
)


def persona_shapes(persona):
    """{shape_id: weight} derived from donor data (closings -> endings, length_mix -> weights)."""
    sig = getattr(persona, 'signature_card', None) or {}
    endings = {IMPLICATION, VERDICT}
    for closing in sig.get('closings') or []:
        for family, rx in _CLOSING_FAMILY:
            if rx.search(str(closing)):
                endings.add(family)
                break
    if not sig.get('closings'):
        endings |= {FALSIFIER, QUESTION}
    try:
        from live import posting_habits
        mix = (posting_habits.load_card(persona) or {}).get('length_mix') or {}
    except Exception:
        mix = {}
    weight = {'short': mix.get('short', 0.4), 'medium': mix.get('medium', 0.35), 'long': mix.get('long', 0.25)}
    return {sid: round(max(0.05, weight[spec['length']]), 3)
            for sid, spec in SHAPES.items() if spec['ending'] in endings}


def _numbers_in_units(units):
    return sum(len(u.get('numbers') or []) for u in units or [])


def mechanism_count(units):
    """Distinct mechanism units in the extracted source (Oct 6 v5: a thread needs >= 2)."""
    from live.compose import _tokens
    seen = []
    for u in units or ():
        if u.get('kind') != 'mechanism':
            continue
        toks = _tokens(str(u.get('statement') or ''))
        if toks and any(len(toks & t) / max(1, min(len(toks), len(t))) >= 0.6 for t in seen):
            continue
        seen.append(toks)
    return len(seen)


THREAD_MIN_MECHANISMS = 2
LONG_VARIANTS = ('thesis_mechanism', 'data_punch')   # may run long when the batch lacks a long post
LONG_NOTE = {'en': (' LONG variant: two or three short paragraphs reaching length_target.min; every paragraph adds NEW '
                    'information (a new piece of evidence, a new step of the mechanism, or who it hits). '
                    'No restating the call, no filler.'),
             'zh': ('（长版）两到三段，写够 length_target 的下限；每一段都带来新信息：新的证据、机制里新的一环、'
                    '或者这件事落到谁身上。不重复判断，不凑空话。')}
# v7: the old "if there is nothing new, stop early" + body_length "short is fine" let long shapes
# come back short (v5zh data_punch long: 114 chars vs 277-399).
THREAD_NOTE = {'en': ' Every paragraph must add new information; never restate an earlier paragraph.',
               'zh': '每段都必须带来新信息，不重复前面的段落，不凑字数。'}


def eligible_shapes(shapes, units, mechanisms=None):
    n = _numbers_in_units(units)
    mech = mechanism_count(units) if mechanisms is None else mechanisms
    out = {}
    for sid, w in shapes.items():
        spec = SHAPES[sid]
        if sid == 'data_punch' and n < 2:
            continue
        if sid == 'one_number_punch' and n < 1:
            continue
        if sid == 'short_thread' and mech < THREAD_MIN_MECHANISMS:
            continue   # v4b zh_industry: 1 view + 1 fact padded into 4 paragraphs
        out[sid] = w
    return out


def _batch_items(batch):
    ids, lengths = [], []
    for b in batch or ():
        sid = b.get('id') if isinstance(b, dict) else b
        if sid not in SHAPES:
            continue
        ids.append(sid)
        lengths.append((b.get('length') if isinstance(b, dict) else None) or SHAPES[sid]['length'])
    return ids, lengths


def choose_shape(persona, *, units=(), recent=(), batch=(), seed='', all_units=None, batch_size=None):
    """Pick one shape. recent: persona history rows (oldest first, may carry 'shape');
    batch: shapes already used in this batch (ids, or {'id', 'length'} dicts). Deterministic for a seed.
    all_units: every extracted unit of the source (mechanism count gates short_thread).
    batch_size: when given, the remaining picks guarantee >= 1 long and >= 1 short post per batch."""
    mech = mechanism_count(all_units if all_units is not None else units)
    shapes = eligible_shapes(persona_shapes(persona), units, mechanisms=mech) or {'take_short': 1.0}
    batch_ids, batch_lengths = _batch_items(batch)
    batch = tuple(batch_ids)
    force = None
    if batch_size:
        remaining = int(batch_size) - len(batch_ids)
        missing = [c for c in ('long', 'short') if c not in batch_lengths]
        if remaining >= 1 and missing and len(missing) >= remaining:
            force = missing[0]
    recent_shapes = [r.get('shape') for r in recent if isinstance(r, dict) and r.get('shape') in SHAPES]
    last = recent_shapes[-1] if recent_shapes else None
    last_len = SHAPES[last]['length'] if last else None
    window = recent_shapes[-4:]
    falsifier_recent = sum(SHAPES[s]['ending'] == FALSIFIER for s in window)
    pool = {s: w for s, w in shapes.items() if s not in set(batch)} or dict(shapes)
    reasons = {}
    scored = []
    for sid, w in pool.items():
        spec, score = SHAPES[sid], w
        if sid == last:
            score *= 0.05
        elif sid in window:
            score *= 0.35
        if last_len and spec['length'] == last_len:
            score *= 0.4          # long / short alternation
        elif last_len in ('medium', 'long') and spec['length'] == 'short':
            score *= 1.3
        if spec['ending'] == FALSIFIER and falsifier_recent:
            score *= 0.2          # conditional-falsifier ending stays a minority
        tie = int(sha256(f'{seed}|{sid}'.encode()).hexdigest()[:6], 16) / 0xFFFFFF
        scored.append((score * (0.85 + 0.3 * tie), sid))
        reasons[sid] = round(score, 4)
    scored.sort(reverse=True)
    sid, length, mix = scored[0][1], None, None
    if force == 'short' and SHAPES[sid]['length'] != 'short':
        shorts = [x for x in scored if SHAPES[x[1]]['length'] == 'short']
        sid = shorts[0][1] if shorts else 'take_short'
        mix = 'forced short (batch had no short post)'
    elif force == 'long' and SHAPES[sid]['length'] != 'long':
        longs = [x for x in scored if SHAPES[x[1]]['length'] == 'long']
        if longs:
            sid = longs[0][1]
        else:
            variants = [x for x in scored if x[1] in LONG_VARIANTS] or [
                (0, v) for v in LONG_VARIANTS if v in shapes] or [(0, 'thesis_mechanism')]
            sid, length = variants[0][1], 'long'
        mix = 'forced long (batch had no long post)'
    spec = SHAPES[sid]
    out = {'id': sid, **{k: spec[k] for k in ('length', 'max_numbers', 'max_number_lines', 'ending', 'line_breaks')},
           'candidates': reasons, 'last_shape': last, 'batch_excluded': sorted(set(batch) & set(shapes)),
           'mechanisms': mech}
    if length:
        out.update(length=length, length_override=True, line_breaks='two or three short paragraphs')
    if mix:
        out['batch_mix'] = mix
    return out


def payload_block(shape, lang, length_range):
    """composition_shape block for the COMPOSE payload (HARD for this post)."""
    spec = SHAPES[shape['id']]
    length = shape.get('length') or spec['length']
    lo, hi = length_range['min'], length_range['max']
    a, b = LENGTH_BAND[length]
    target = {'min': int(lo + a * (hi - lo)), 'max': int(lo + b * (hi - lo))}
    ending_rule = {
        FALSIFIER: 'End on the concrete condition that would prove the call wrong.',
        VERDICT: 'End on a flat committed verdict. NO conditional ending (no if / unless / provided / '
                 'only if / until / flips if / 只要 / 除非 / 若 / 如果 / 一旦 / 否则).',
        IMPLICATION: 'End on what the call means (who gains, what is not priced, what it implies). '
                     'NO conditional ending (no if / unless / provided / until / 只要 / 除非 / 若 / 一旦).',
        QUESTION: 'End on one pointed open question. NO conditional ending.',
    }[spec['ending']]
    key = 'zh' if lang == 'zh' else 'en'
    structure = spec[key]
    if shape.get('length_override') and length == 'long':
        structure += LONG_NOTE[key]
    elif shape['id'] == 'short_thread':
        structure += THREAD_NOTE[key]
    return {'id': shape['id'], 'structure': structure, 'length': length,
            'length_target': target, 'max_numbers': spec['max_numbers'],
            'max_number_lines': spec['max_number_lines'], 'line_breaks': shape.get('line_breaks') or spec['line_breaks'],
            'ending': spec['ending'], 'ending_rule': ending_rule,
            'line1_rule': ('Line 1 is the unconditional call: no if / unless / provided / until / 若 / 只要 / '
                           '除非 / 一旦 clause in line 1; stance.view.conditions is background, not line 1.')}


# ---------------- structure detection (soft checks) ----------------
_COND_ZH = re.compile(r'若|如果|只要|除非|一旦|假如|倘若|否则|前提是|直到|取决于|不[^，,。！？\n]{1,12}[，,][^。！？\n]{0,20}就')
_COND_EN = re.compile(r"\b(?:if|unless|provided|as long as|only if|until|flips? if|breaks? if|would change|"
                      r"proves? (?:me|it|this|the call) wrong|contingent on|depends on)\b", re.I)
_SENT = re.compile(r'(?<=[。！？!?])|(?<=\.)\s+|\n+')
_NUM = re.compile(r'\d')


def _lines(body):
    return [ln.strip() for ln in (body or '').splitlines() if ln.strip()]


def _last_sentence(body):
    lines = _lines(body)
    if not lines:
        return ''
    parts = [p.strip() for p in _SENT.split(lines[-1]) if p and p.strip()]
    return parts[-1] if parts else lines[-1]


def is_conditional(text):
    return bool(_COND_ZH.search(text or '') or _COND_EN.search(text or ''))


def ending_family(body):
    last = _last_sentence(body)
    if re.search(r'[?？]\s*$', last):
        return QUESTION
    if is_conditional(last):
        return FALSIFIER
    return 'other'


def skeleton(body, length_range=None):
    lines = _lines(body)
    first = lines[0] if lines else ''
    num_lines = [bool(_NUM.search(ln)) for ln in lines]
    run = best = 0
    for flag in num_lines:
        run = run + 1 if flag else 0
        best = max(best, run)
    size = len(re.sub(r'\s+', '', body or ''))
    length = None
    if length_range:
        lo, hi = length_range['min'], length_range['max']
        frac = (size - lo) / max(1, hi - lo)
        length = 'short' if frac < 0.33 else 'long' if frac > 0.66 else 'medium'
    return {'opener': 'conditional' if is_conditional(first) else 'question' if re.search(r'[?？]', first) else 'call',
            'ending': ending_family(body), 'number_lines': sum(num_lines), 'number_run': best,
            'lines': len(lines), 'length': length}


_HEDGE_OPENER = re.compile(r"^\s*(?:我(?:个人)?(?:觉得|认为|感觉)|在我看来|个人(?:觉得|认为)|(?:I think|IMO|In my view|My view is|I feel)\b)", re.I)


def hedged_opener_findings(body):
    """SOFT: line 1 softened by an opinion marker (v4 zh_macro 我个人觉得，… / v3 en_industry IMO).
    Opinion markers are fine later in the body; the opening call is said flat."""
    first = next((ln for ln in (body or '').splitlines() if ln.strip()), '')
    m = _HEDGE_OPENER.search(first)
    return [{'code': 'hedged_opener', 'detail': f'line 1 opens with "{m.group(0).strip()}"'}] if m else []


def _paragraphs(body):
    paras = [p.strip() for p in re.split(r'\n\s*\n', body or '') if p.strip()]
    return paras if len(paras) > 1 else _lines(body)


def thread_padding_findings(body, shape):
    """SOFT thread_padding (long posts): a paragraph that mostly restates earlier ones, or more
    paragraphs than the source has content for (v4b zh_industry: 4 paragraphs from 1 view + 1 fact)."""
    if not shape or not (shape.get('id') == 'short_thread' or shape.get('length') == 'long'):
        return []
    from live.compose import _tokens
    paras = _paragraphs(body)
    out, seen = [], set()
    for i, p in enumerate(paras):
        toks = _tokens(p)
        if i and toks and len(toks & seen) / len(toks) >= 0.5:
            out.append({'code': 'thread_padding',
                        'detail': f'paragraph {i + 1} mostly restates earlier paragraphs; cut it or add new information'})
            break
        seen |= toks
    mech = shape.get('mechanisms')
    if not out and mech is not None and len(paras) >= 4 and mech < THREAD_MIN_MECHANISMS:
        out.append({'code': 'thread_padding',
                    'detail': f'{len(paras)} paragraphs from a source with {mech} mechanism unit(s); write it shorter'})
    return out


_FILLER_EN = re.compile(r"^\W*(?:carry on|stay tuned|time will tell|we(?:'ll| will) see|let'?s see|buckle up|watch this space|"
                        r"enough said|nuff said|just saying|game on|you'?ve been warned|over to you|food for thought|"
                        r"make of (?:that|this) what you will)\W*$", re.I)
_FILLER_ZH = re.compile(r'拭目以待|静观其变|敬请期待|走着瞧|且看后续|让子弹飞一会|边走边看|咱们拭目|留给时间|交给时间|时间会给出答案')


def filler_closer_findings(body):
    """SOFT filler_closer: the post ends on an empty verdict (v5 en_macro "Carry on.", 拭目以待)."""
    last = _last_sentence(body)
    if not last:
        return []
    if _FILLER_EN.search(last) or (len(last) <= 30 and _FILLER_ZH.search(last)):
        return [{'code': 'filler_closer', 'detail': f'ends on filler "{last.strip()[:40]}"'}]
    return []


def number_run_findings(body, shape_id=None):
    """SOFT: >=3 consecutive number lines (罗列), or >2 number lines outside data_punch."""
    sk = skeleton(body)
    limit = SHAPES.get(shape_id or '', {}).get('max_number_lines', 2)
    if shape_id == 'data_punch':
        return []
    if sk['number_run'] >= 3 or sk['number_lines'] > max(2, limit):
        return [{'code': 'number_run',
                 'detail': f"{sk['number_lines']} lines with numbers ({sk['number_run']} in a row); "
                           'keep at most 2 and say the mechanism instead'}]
    return []


def shape_findings(body, shape):
    """SOFT: the draft ignored its composition_shape (conditional ending / opener, number lines)."""
    if not shape:
        return []
    sk = skeleton(body)
    out = []
    if shape['ending'] != FALSIFIER and sk['ending'] == FALSIFIER:
        out.append({'code': 'shape_mismatch', 'detail': f"conditional ending but shape {shape['id']} ends on {shape['ending']}"})
    if sk['opener'] == 'conditional':
        out.append({'code': 'shape_mismatch', 'detail': 'line 1 carries a condition (if / unless / provided / 若 / 只要)'})
    if shape['id'] != 'data_punch' and sk['number_lines'] > shape['max_number_lines'] + 1:
        out.append({'code': 'shape_mismatch',
                    'detail': f"{sk['number_lines']} number lines vs shape limit {shape['max_number_lines']}"})
    return out


def opener_key(body):
    """First lexeme of line 1: first 2 CJK chars (ZH) or first two words (EN), lower-cased."""
    first = next((ln.strip() for ln in (body or '').splitlines() if ln.strip()), '')
    cjk = re.match(r'[\u4e00-\u9fff]{2}', first)
    if cjk:
        return cjk.group(0)
    words = re.findall(r"[A-Za-z']+", first.lower())[:2]
    return ' '.join(words) if len(words) == 2 else ''


_GENERIC_OPENERS = {'the fed', 'the market', '美联储', '美国', '市场'}
# v5/v6 live: ZH openers rotated words but kept one move - 别急着 / 别指望 / 别看 / 别把 / 别被 (imperative "don't").
_OPENER_FAMILY = re.compile(r'^\s*(别|不要|千万别|先别|don\'t|do not|stop)', re.I)


def opener_family(body):
    first = next((ln for ln in (body or '').splitlines() if ln.strip()), '')
    m = _OPENER_FAMILY.search(first)
    return m.group(1).lower().replace('千万别', '别').replace('先别', '别') if m else ''


def history_findings(body, recent, *, shape=None):
    """SOFT structure_repeat vs this persona's recent drafts (structure, not exact strings)."""
    sk = skeleton(body)
    prior = [r for r in recent or [] if isinstance(r, dict) and r.get('text')][-5:]
    if not prior:
        return []
    prior_sk = [r.get('skeleton') or skeleton(r['text']) for r in prior]
    out = []
    last = prior_sk[-1]
    if sk['ending'] == FALSIFIER and last.get('ending') == FALSIFIER:
        out.append({'code': 'structure_repeat', 'detail': 'conditional-falsifier ending again (previous draft too)'})
    elif sk['ending'] == FALSIFIER and sum(p.get('ending') == FALSIFIER for p in prior_sk[-3:]) >= 1 \
            and sum(p.get('ending') == FALSIFIER for p in prior_sk) >= 2:
        out.append({'code': 'structure_repeat', 'detail': 'conditional-falsifier ending is the majority of recent drafts'})
    if sk['opener'] == 'conditional' and last.get('opener') == 'conditional':
        out.append({'code': 'structure_repeat', 'detail': 'conditional opener again (previous draft too)'})
    fam = opener_family(body)
    if fam and sum(opener_family(r['text']) == fam for r in prior[-3:]) >= 2:
        out.append({'code': 'structure_repeat',
                    'detail': f'opener family "{fam}…" again (2+ of the last 3 drafts open the same way)'})
    key = opener_key(body)
    if key and key not in _GENERIC_OPENERS and any(opener_key(r['text']) == key for r in prior):
        out.append({'code': 'structure_repeat', 'detail': f'same opener "{key}" as a recent draft of this persona'})
    if shape and prior[-1].get('shape') == shape.get('id'):
        out.append({'code': 'structure_repeat', 'detail': f"same composition shape as previous draft: {shape['id']}"})
    return out


def batch_findings(results):
    """SOFT cross-draft check for one batch (matrix / daily): shared shape or skeleton, and more
    than one conditional-falsifier ending. Adds findings in place on later drafts; returns summary."""
    seen_shapes, seen_skeletons, falsifiers = {}, {}, []
    summary = []
    for r in results:
        body = r.get('body') or ''
        if not body:
            continue
        sk = skeleton(body)
        shape = (r.get('composition_shape') or {}).get('id')
        key = (sk['opener'], sk['ending'], min(sk['number_lines'], 3))
        found = []
        if shape and shape in seen_shapes:
            found.append({'code': 'structure_repeat', 'level': 'soft',
                          'detail': f'batch: same composition shape {shape} as {seen_shapes[shape]}'})
        elif key in seen_skeletons and (not shape or sk['opener'] == 'conditional'):
            found.append({'code': 'structure_repeat', 'level': 'soft',
                          'detail': f'batch: same skeleton {key} as {seen_skeletons[key]}'})
        if sk['ending'] == FALSIFIER:
            if falsifiers:
                found.append({'code': 'structure_repeat', 'level': 'soft',
                              'detail': f'batch: another conditional-falsifier ending (also {", ".join(falsifiers)})'})
            falsifiers.append(r.get('account_id'))
        if found:
            r['post_checks'] = list(r.get('post_checks') or []) + found
            r['risks'] = list(r.get('risks') or []) + [{**f, 'status': 'warning'} for f in found]
        if shape:
            seen_shapes.setdefault(shape, r.get('account_id'))
        seen_skeletons.setdefault(key, r.get('account_id'))
        summary.append({'account_id': r.get('account_id'), 'shape': shape, 'skeleton': sk,
                        'findings': [f['detail'] for f in found]})
    return summary


LENGTH_TOLERANCE = {'long_min': 0.85, 'medium_min': 0.6, 'max': 1.2}


def length_band_findings(body, shape):
    """SOFT length_band (v7): long shape well under its band, or any shape well over it.
    Length = characters excluding whitespace (same unit as body_length / length_target)."""
    target = (shape or {}).get('length_target') or {}
    if not body or not target:
        return []
    n = len(re.sub(r'\s', '', body))
    length = shape.get('length')
    lo, hi = target.get('min', 0), target.get('max', 0)
    if length == 'long' and n < LENGTH_TOLERANCE['long_min'] * lo:
        return [{'code': 'length_band', 'detail': f'long shape but {n} chars (target {lo}-{hi}); add a new evidence/mechanism paragraph'}]
    if length == 'medium' and n < LENGTH_TOLERANCE['medium_min'] * lo:
        return [{'code': 'length_band', 'detail': f'medium shape but {n} chars (target {lo}-{hi})'}]
    if hi and n > LENGTH_TOLERANCE['max'] * hi:
        return [{'code': 'length_band', 'detail': f'{n} chars over the {length} band ({lo}-{hi}); cut'}]
    return []


def recent_opener_findings(body, recent):
    """SOFT opener_move (EN/any): same opener family (don\'t / stop / 别…) as either of the last two
    drafts - c26d3a4's history rule, now feeding the structure regen."""
    fam = opener_family(body)
    prior = [r['text'] for r in (recent or []) if isinstance(r, dict) and r.get('text')][-2:]
    if fam and any(opener_family(t) == fam for t in prior):
        return [{'code': 'opener_move', 'detail': f'opener family "{fam}…" again (one of the last two drafts)'}]
    return []


def is_filler(phrase):
    t = str(phrase or '').strip()
    return bool(_FILLER_EN.search(t) or (len(t) <= 30 and _FILLER_ZH.search(t)))


_QUOTED = re.compile(r"\s*/?\s*['‘“「]([^'’”」]{1,40})['’”」]\s*/?")


def strip_filler_examples(text):
    """Drop quoted filler examples from a card line (en_macro closing: "A short, flat verdict:
    'Carry on.' / 'There is no one left to cut.'" -> keeps the second example)."""
    def repl(m):
        return ' ' if is_filler(m.group(1)) else m.group(0)
    out = _QUOTED.sub(repl, str(text))
    return re.sub(r'\s{2,}', ' ', out).replace(': /', ':').strip()
