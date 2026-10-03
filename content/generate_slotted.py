"""Slot-constrained generation. Step 2 of the content delivery plan.

The model receives twelve pre-rendered fact strings and must place each one verbatim. It never
converts a unit or a scale, so a magnitude error on a mandatory fact cannot occur by construction.
It still chooses the question, the order, the emphasis and the voice.

If a slot is missing after generation, one repair pass names the missing slots and asks only for
them to be added. Both attempts are recorded.

Run: .venv/bin/python -B content/generate_slotted.py [--persona=macro] [--all]
"""
from pathlib import Path
import sys, json, time, fcntl, datetime, hashlib, re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'evidence_loop'))
from model_client import call, parse_json
from qa.gates import evaluate
from qa.status import classify
from content.fact_slots import build_slots, verify_placement, render_value
from content.form_check import check as form_check
from content.leak_check import check as leak_check, faults as leak_faults

PLACEHOLDER = re.compile(r'\{(S\d{2})(:v)?\}')
# Durations and ordinals are the model's own words, not fact values.
DURATION_NUM = re.compile(r'\d+\s*(?:个月|个季度|个交易日|天|周|年|季度|次|成|倍)')
# Calendar references are the writer's own words, not figures from the fact table.
CALENDAR = re.compile(r'(?:20\d{2}\s*年)?\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|Q[1-4]')
# An invalidation condition has to name a threshold, and a threshold the writer proposes is a
# forward-looking test, not a claim about what the data says. Such a figure is allowed, but it is
# recorded separately so a reader can never mistake it for a sourced number.
THRESHOLD_CLAUSE = re.compile(r'(?:若|如果|假如|倘若|一旦|除非|失效条件|更新条件|反转条件|'
                              r'触发条件|需要看到|需观察到|才能确认)[^。！？]*')
RAW_DIGIT = re.compile(r'\d')


NUM_PHRASE = re.compile(r'[-+]?\d[\d,]*(?:\.\d+)?\s*(?:万人|万|亿|个百分点|%|美分|美元|小时|人)?')


DIRECTION_WINDOW = 26


def _scan(text, slots):
    """Credit a slot from an inline figure only when the direction survives with it.

    Matching on the value alone let a draft write "信息业就业月变化 2.3 万人" and be credited for a
    fact that is a decline of 23,000. The number was right, the sign was gone, and the next clause
    called that sector an engine of growth. A figure that arrives without its direction word is
    reported as misframed rather than credited.
    """
    allowed = {s['value_rendered'].replace(' ', ''): s for s in slots}
    stripped = CALENDAR.sub('', DURATION_NUM.sub('', PLACEHOLDER.sub('', text)))
    used, other, misframed = [], [], []
    for m in NUM_PHRASE.finditer(stripped):
        tok = m.group(0).strip().replace(' ', '')
        if not RAW_DIGIT.search(tok):
            continue
        slot = allowed.get(tok)
        if slot is None:
            other.append(m.group(0).strip())
            continue
        word = slot.get('direction_word')
        if word and word not in stripped[max(0, m.start() - DIRECTION_WINDOW):m.start()]:
            misframed.append({'slot_id': slot['slot_id'], 'value': tok,
                              'missing_direction_word': word,
                              'expected': slot['rendered']})
            continue
        used.append(slot['slot_id'])
    return used, other, misframed


def audit_numbers(text, slots, kind=None):
    """Every figure in the prose must be one of the rendered slot values, exactly.

    The model prefers writing the number inline rather than using a placeholder, and it copies the
    value correctly when it does. So instead of fighting that, each figure is matched against the
    slot table: anything the model invented, rounded or reworded fails here.

    The one exception is a threshold inside a condition sentence. "若失业率升至 4.2% 以上" is the
    writer proposing a test, and banning it makes an invalidation condition unwritable. Those
    figures are returned as `proposed`, not as an error, and the ledger keeps them labelled.
    """
    body = text or ''
    used, invented, misframed = _scan(body, slots)
    # The exemption belongs to the construction, not to the label. `kind` is the model's own
    # report, and it labelled a block containing 失效条件 as "fact", which charged the writer's
    # threshold as an invented figure. What earns the exemption is the hypothetical clause itself.
    if not THRESHOLD_CLAUSE.search(body):
        return used, invented, [], misframed
    outside = THRESHOLD_CLAUSE.sub('', body)
    _, still_invented, _ = _scan(outside, slots)
    proposed = _diff_counts(invented, still_invented)
    return used, still_invented, proposed, misframed


def _diff_counts(all_items, kept):
    """Items that the threshold clause accounted for."""
    rest = list(kept)
    out = []
    for x in all_items:
        if x in rest:
            rest.remove(x)
        else:
            out.append(x)
    return out


def used_slot_ids(sentences):
    """Authoritative record of which slots were expanded, taken from substitution itself."""
    out = []
    for row in sentences:
        out += row.get('slot_ids') or []
    return out


def placement_from_usage(sentences, slots):
    used = set(used_slot_ids(sentences))
    missing = [s['slot_id'] for s in slots if s['slot_id'] not in used]
    return {'placed': len(slots) - len(missing), 'total': len(slots),
            'missing_slot_ids': missing, 'wrong_frame': [],
            'coverage': round((len(slots) - len(missing)) / max(len(slots), 1), 4),
            'source': 'substitution record, not string matching'}


def substitute(text, slots):
    """Replace placeholders with the rendered fact strings.

    Placement becomes a property of the code, not of the model's ability to copy thirteen long
    strings verbatim. What the model is judged on is the analysis around them.
    """
    full = {s['slot_id']: s['rendered'] for s in slots}
    value = {s['slot_id']: s['value_rendered'] for s in slots}
    used, unknown = [], []

    def sub(m):
        sid, inline = m.group(1), m.group(2)
        table = value if inline else full
        if sid not in table:
            unknown.append(sid)
            return ''
        used.append(sid)
        return table[sid]

    out = PLACEHOLDER.sub(sub, text or '')
    return collapse_duplicate_frames(out, slots), used, unknown


def collapse_duplicate_frames(text, slots):
    """The model often writes the frame itself and then references the slot, which expands to the
    frame again: "前两个月合计上修 前两个月合计上修 5.5 万人". The wording is the renderer's either
    way, so the leading copy is dropped rather than failing the draft over it."""
    out = text or ''
    for s in slots:
        rendered = s['rendered']
        idx = rendered.rfind(s['value_rendered'])
        stem = rendered[:idx].strip()
        if len(stem) < 3:
            continue
        dup = re.compile(re.escape(stem) + r'\s*' + re.escape(rendered))
        out = dup.sub(rendered, out)
    return out
import profile_registry as reg
sys.path.insert(0, str(ROOT / 'live'))
import style as style_mod

OUT = ROOT / 'content/drafts'
DRAFT_TOKENS = 2600
MAX_ATTEMPTS = 4
EXEMPLAR_CHARS = 700


def local_call(prompt, task, tokens, temperature=.2):
    with (ROOT / 'evidence_loop/model.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        t0 = time.monotonic()
        r = call(prompt, task, tokens, temperature, model_role='modern')
        r['_latency_s'] = round(time.monotonic() - t0, 2)
        return r


# Level facts and the change facts that license a claim of movement.
LEVEL_TO_CHANGE = {
    'participation': 'participation_since_jan',
    'workweek': 'workweek_change',
    'unemployment_rate': None,
    'employment_population': None,
}


def change_hint(packet):
    """Tell the model which claims of movement the evidence actually licenses."""
    facts = {f['id']: f for f in packet['facts']}
    ok, no = [], []
    for level, change in LEVEL_TO_CHANGE.items():
        if level not in facts:
            continue
        if change and change in facts:
            c = facts[change]
            ok.append(f"说“{facts[level]['label']}下降/上升”时，必须同时写出"
                      f"「{c['label']} {render_value(c)}」")
        else:
            no.append(facts[level]['label'])
    lines = []
    if ok:
        lines.append('可以谈变化的指标：' + '；'.join(ok))
    if no:
        lines.append('以下指标只给了水平值，没有变化量，因此**不得写“上升/下降/升至/降至”**，'
                     '只能陈述其水平：' + '、'.join(no))
    return ('\n'.join(lines) + '\n') if lines else ''


def prompt_for(persona, slots, packet, exemplars, plan=None, missing=None, faults=None,
               style_target=None):
    """One page of instruction, not a rulebook.

    An earlier version carried six numbered rules plus methodology text plus constraints, and the
    model responded by ignoring the placeholder mechanism entirely. Fewer, sharper instructions
    work better than more of them.
    """
    # Show the rendered frame, not the neutral label. Listing "信息业就业月变化：2.3 万人" is what
    # taught the model to write the magnitude without the direction and call a shrinking sector an
    # engine of growth.
    slot_lines = '\n'.join(f"  {s['rendered']}" for s in slots)
    signed = [s for s in slots if s.get('direction_word')]
    signed_rule = ''
    if signed:
        signed_rule = ('以下几条带方向，写到它们时必须保留方向词，不能改成“月变化”这类中性说法：\n'
                       + '\n'.join(f"  {s['rendered']}（方向词：{s['direction_word']}）"
                                   for s in signed) + '\n')
    ex = ''
    if exemplars:
        ex = ('\n参考这几位作者的表达方式（只学语气与推理节奏，不要抄内容、不要复制其身份）：\n'
              + '\n'.join(f"[{e['donor']}] {e['text'][:280]}" for e in exemplars) + '\n')
    who = f"你是{persona['name']}，关心的问题是：{persona['question']}\n" if persona else ''
    fix = ('\n这一稿要修正的问题：\n' + '\n'.join('  · ' + x for x in faults) + '\n') if faults else ''
    voice = ('\n' + style_mod.instructions(style_target, 'zh') + '\n') \
        if (style_target or {}).get('usable') else ''
    return (
        f"{who}"
        f"事件：{packet['title']}（{packet['published_at'][:10]} 发布）\n"
        f"\n"
        f"【最重要的一条规则】正文里出现的每一个数字，都必须与下表**一字不差**，"
        f"包括单位。不要换算、不要四舍五入、不要写表外的数字：\n{slot_lines}\n"
        f"\n"
        f"按下面的骨架写一篇中文金融分析稿，**每一条各写一句，共 10 句，一句都不能少**：\n"
        # These were phrased as headings and the model wrote them into the prose: three drafts
        # shipped containing "价格与工时这条线" and "修正与参与率改变读法". Same ten moves,
        # phrased as instructions that cannot be lifted as a sentence.
        f"  1 先给出你的判断，这一句里不要出现数字\n"
        f"  2 用最能支撑它的一组数字\n"
        f"  3 再和更长时间尺度的水平做比较\n"
        f"  4 说清哪些行业在增、哪些在减\n"
        f"  5 说清工资与工时说明了什么\n"
        f"  6 说清修正与参与率如何改变前面的读法\n"
        f"  7 给出最强的相反读法\n"
        f"  8 说明你为什么仍然维持或调整原判断\n"
        f"  9 写明看到什么就说明你错了\n"
        f"  10 写明下一步该看哪个数据\n"
        f"  （以上是写作要求，不是小标题；不要把这些说法本身写进正文）\n"
        f"\n"
        f"上表每条事实都要用到，各用一次。每句都要有你自己的分析，不要只罗列数字。\n"
        f"事实包里没有市场预期，也没有失业率的变化量，所以不要写“高于预期”或“失业率下降”。\n"
        f"第 9 句可以提出你自己的观察阈值（例如“若某指标跌破某水平”），这是唯一允许出现"
        f"表外数字的地方。\n"
        f"{voice}"
        f"{signed_rule}"
        f"{change_hint(packet)}"
        f"{fix}"
        f"{ex}"
        f"\n只输出 JSON：{{\"title\":\"...\",\"sentences\":[{{\"text\":\"...\","
        f"\"kind\":\"fact 或 interpretation 或 condition\",\"fact_ids\":[]}}]}}")


def repair_prompt(persona, missing, existing_sentences, packet=None):
    """Ask only for the missing slots as new sentences. The existing draft is not rewritten,
    because a full regeneration adds one slot and drops another.

    The repair carries the same evidence rules as the first pass. Without them a repair sentence
    reached the draft claiming a trend while citing only a level, and the whole draft was blocked
    on a sentence the model had never been given the rule for.
    """
    names = '\n'.join(
        f"  {{{s['slot_id']}}} = {s['rendered']}   |   {{{s['slot_id']}:v}} = {s['value_rendered']}"
        for s in missing)
    have = '\n'.join(f"  {i + 1}. {x['text']}" for i, x in enumerate(existing_sentences))
    return (f"你是{persona['name']}。下面是一篇已经写好的稿子，它还缺几条必须出现的事实。\n\n"
            f"已有正文（不要改动，不要重写）：\n{have}\n\n"
            f"还缺的事实及其占位符：\n{names}\n\n"
            f"请只写出需要**新增**的句子，每句用一个占位符引用一条缺失事实，并加上你自己的分析，"
            f"使其能自然接在已有正文之后。不要重复已有内容，不要输出已有句子。\n"
            f"**不要自己写数字**，一律用占位符。"
            f"描述行业间流动时方向必须与数字一致：只能从下降的行业流向上升的行业。\n"
            f"新句子若要说某指标“上升/下降/走弱/收紧”，必须引用事实表里的变化量事实，"
            f"不能只引用一个水平值；也不要回指前文的趋势来代替引用。\n"
            f"{change_hint(packet) if packet else ''}\n"
            f"只输出合法 JSON：{{\"sentences\":[{{\"text\":\"一句完整文字\","
            f"\"kind\":\"fact 或 interpretation 或 condition\",\"fact_ids\":[\"实际 fact ID\"],"
            f"\"insert_after\":\"接在第几句之后，填数字\"}}]}}")


FAULT_TEXT = {
    'citation_relation_mismatch': '上一稿里有句子说某个指标“上升/下降/升至/降至”，但引用的事实'
                                  '只是一个水平值。只有事实表里明确给出变化量的指标才能谈变化。',
    'unsupported_causal_claim': '上一稿写了因果结论，但事实包只支持同期出现。改成描述同时发生，'
                                '或明确写成推断。',
    'must_include_missing': '上一稿漏掉了必须出现的事实，每条都要用到。',
    'flow_direction_reversed': '上一稿描述行业间流动时方向反了。只能从数字下降的行业流向上升的。',
    'model_wrote_a_number': '上一稿在非条件句里写了事实表以外的数字。除失效条件中的阈值外，'
                            '正文数字必须与表内完全一致。',
    'direction_word_dropped': '上一稿写数字时丢掉了方向词。事实表里标注“减少/下降”的指标，'
                              '写出数值时必须带上该方向词，不能改写成“月变化”这类中性说法。',
    'sign_direction_mismatch': '上一稿把一个下降的指标描述成了增长（或反之）。方向词必须与'
                               '事实表一致。',
    'too_short': '上一稿句数不足。骨架 10 条每条各写一句，不能合并。',
    'sentence_restates_another': '上一稿有两句在讲同一组事实，等于同一句写了两遍。每条事实只用一次。',
    'compound_direction_over_opposite_facts': '上一稿把一个方向词同时套在两个反向的指标上。'
                                              '一升一降的指标要分开写，不能合并成一句结论。',
    'bare_slot_sentences': '上一稿有些句子只是把数字念了一遍，每句都要有你的判断。',
    'insufficient_analysis': '上一稿解释性句子太少，第 1、7、8、9、10 句都应是判断而非陈述。',
}


def fault_notes(qa, form):
    """Name what the gates rejected, in the writer's terms rather than gate codes."""
    codes = ([f['code'] for f in qa['findings'] if f['severity'] == 'blocking']
             + [f['code'] for f in form['findings'] if f['severity'] == 'blocking'])
    seen, out = set(), []
    for c in codes:
        if c in FAULT_TEXT and c not in seen:
            seen.add(c)
            out.append(FAULT_TEXT[c])
    return out


def build_ledger(sentences, slots, packet):
    """Sentence-to-source rows. Slots carry their own fact ids, so coverage is credited from
    what was actually placed, never from the model's self-report."""
    allowed = {f['id']: f for f in packet['facts']}
    by_slot = {s['slot_id']: s for s in slots}
    ledger = []
    for i, s in enumerate(sentences):
        refs = [x for x in (s.get('fact_ids') or []) if x in allowed]
        blocks = {b for r in refs for b in allowed[r]['source_block_ids']}
        for sid in (s.get('slot_ids') or []):
            slot = by_slot.get(sid)
            if slot and slot['fact_id'] not in refs:
                refs.append(slot['fact_id'])
                blocks |= set(slot['source_block_ids'])
        ledger.append({'sentence_id': 's' + str(i + 1), 'text': s['text'],
                       'kind': s.get('kind'), 'fact_ids': refs,
                       'slot_ids': s.get('slot_ids') or [],
                       'model_written_digits': s.get('model_written_digits') or [],
                       'proposed_thresholds': s.get('proposed_thresholds') or [],
                       'misframed_values': s.get('misframed_values') or [],
                       'source_block_ids': sorted(blocks),
                       'primary_url': packet['primary_url'],
                       'source_hash': packet['artifact_sha256']})
    return ledger


def load_exemplars(persona_id, roles_doc, retrieval, corpus, limit=2):
    persona = roles_doc['personas'][persona_id]
    donors = {r['donor'] for r in persona['roles'].values() if r and r.get('donor')}
    out = []
    for e in retrieval['results'].get(persona_id, []):
        if e['source_account_id'] in donors and len(out) < limit * len(donors):
            r = corpus.get(e['post_id'])
            if not r:
                continue
            body = (r.get('analysis_text') or r.get('text') or '').strip()
            out.append({'post_id': e['post_id'], 'donor': e['source_account_id'],
                        'created_at': e['created_at'], 'text': body[:EXEMPLAR_CHARS]})
    return out


def generate(persona_id, packet, roles_doc, retrieval, corpus, use_exemplars=True):
    slots = build_slots(packet, packet['coverage']['required_core_ids'])
    persona = roles_doc['personas'][persona_id]
    # This path pasted exemplars and never checked the result. Its three drafts sat at the 100th
    # percentile of the assigned donor's own spread — closest to phyrexni only because they were
    # closer to him than to anyone else, while reading like nothing he writes.
    donor = (persona['roles'].get('language') or {}).get('donor')
    tpath = ROOT / 'live/store/style_targets.json'
    targets = json.loads(tpath.read_text()) if tpath.exists() else {}
    style_target = targets.get(donor) or {}
    exemplars = load_exemplars(persona_id, roles_doc, retrieval, corpus) if use_exemplars else []

    cid = 'draft-' + hashlib.sha256(
        (persona_id + datetime.datetime.now().isoformat()).encode()).hexdigest()[:12]
    rec = {
        'id': cid, 'persona_id': persona_id, 'persona_name': persona['name'],
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_id': packet['id'], 'source_version': packet['version'],
        'method': 'slot_constrained_v1',
        'profile_channel': reg.active_version(), 'roles_run': roles_doc['run_id'],
        'roles': {k: (v or {}).get('donor') for k, v in persona['roles'].items()},
        'exemplars_in_prompt': [{'post_id': e['post_id'], 'donor': e['donor'],
                                 'chars': len(e['text'])} for e in exemplars],
        'slots': [{'slot_id': s['slot_id'], 'fact_id': s['fact_id'],
                   'rendered': s['rendered']} for s in slots],
        'run_status': 'running', 'qa_status': 'not_run', 'content_status': 'blocked',
        'attempts': [],
    }

    # A repair regenerates the whole draft, so it can add one slot and drop another. Keep the
    # best attempt seen rather than the last one.
    obj, last, best_score, faults = None, None, -1, []
    for attempt in range(MAX_ATTEMPTS):
        missing = None
        if last is not None:
            placed = placement_from_usage(obj['sentences'], slots) if obj else last['placed']
            missing = [s for s in slots if s['slot_id'] in placed['missing_slot_ids']]
            if not missing and not faults:
                break
        if missing and obj is not None:
            p = repair_prompt(persona, missing, obj['sentences'], packet)
        else:
            # A gate failure with the slots already complete cannot be repaired by adding
            # sentences, so the draft is written again with the specific fault named.
            p = prompt_for(persona, slots, packet, exemplars, faults=faults,
                           style_target=style_target)
        r = local_call(p, 'slotted_draft', DRAFT_TOKENS)
        rec['attempts'].append({'attempt': attempt + 1, 'run_id': r['run_id'],
                                'latency_s': r['_latency_s'], 'usage': r['usage'],
                                'repaired_slots': [s['slot_id'] for s in (missing or [])]})
        try:
            o = parse_json(r['text'])
            if missing and obj is not None:
                # splice the new sentences into the existing draft at their requested position
                merged = list(obj['sentences'])
                for extra in o.get('sentences', []):
                    raw2 = extra.get('text', '')
                    filled, ph2, unknown2 = substitute(raw2, slots)
                    inline2, invented2, proposed2, mis2 = audit_numbers(filled, slots,
                                                                        extra.get('kind'))
                    extra['_raw'] = raw2
                    extra['slot_ids'] = sorted(set(ph2) | set(inline2))
                    extra['unknown_placeholders'] = unknown2
                    extra['model_written_digits'] = invented2
                    extra['proposed_thresholds'] = proposed2
                    extra['misframed_values'] = mis2
                    extra['text'] = filled
                # The invalidation condition closes the piece. A repair that appends after it
                # left a draft ending on a stray sector fact, so new sentences land before it.
                limit = next((i for i, s in enumerate(merged) if s.get('kind') == 'condition'),
                             len(merged))
                for extra in o.get('sentences', []):
                    try:
                        at = int(str(extra.get('insert_after', limit)))
                    except Exception:
                        at = limit
                    at = min(max(at, 0), limit)
                    merged.insert(at, extra)
                    limit += 1
                o = {'title': obj.get('title'), 'sentences': merged}
            for row in o['sentences']:
                raw = row.get('text', '')
                # Digits the model typed itself, outside any placeholder, are never allowed.
                filled, ph_used, unknown = substitute(raw, slots)
                inline_used, invented, proposed, mis = audit_numbers(filled, slots,
                                                                     row.get('kind'))
                row['_raw'] = raw
                row['slot_ids'] = sorted(set(ph_used) | set(inline_used))
                row['unknown_placeholders'] = unknown
                row['model_written_digits'] = invented
                row['proposed_thresholds'] = proposed
                row['misframed_values'] = mis
                row['text'] = filled
            text = '\n\n'.join(s['text'] for s in o['sentences'])
        except Exception as e:
            rec['attempts'][-1]['error'] = type(e).__name__ + ': ' + str(e)[:200]
            continue
        chk = placement_from_usage(o['sentences'], slots)
        led = build_ledger(o['sentences'], slots, packet)
        fm = form_check(text, led, slots)
        st = (style_mod.check(text, style_target) if style_target.get('usable')
              else {'checked': False})
        lk = leak_check(text, led)
        # The evidence gates decide whether a draft is usable, so they belong inside the retry
        # loop. Scoring only on slots and form let an attempt win while failing QA outright.
        qa = evaluate({'sentence_to_source_ledger': led}, packet,
                      must_include=packet['coverage']['required_core_ids'])
        qa_blocking = qa['status']['blocking_count']
        score = (chk['placed'] * 10 - qa_blocking * 8
                 + (5 if fm['form_status'] == 'passed' else 0)
                 - 2 * len(st.get('misses') or []) - 4 * lk['blocking_count']
                 + min(len(o['sentences']), 12))
        rec['attempts'][-1].update(slot_coverage=chk, form_status=fm['form_status'],
                                   leaks=[x['code'] for x in lk['findings']],
                                   style_passed=st.get('passed'),
                                   style_misses=[m['feature'] for m in st.get('misses') or []],
                                   qa_status=qa['status']['qa_status'],
                                   qa_blocking=qa_blocking, score=score,
                                   qa_codes=sorted({f['code'] for f in qa['findings']
                                                    if f['severity'] == 'blocking'}))
        last = {'text_joined': text, 'placed': chk}
        faults = (fault_notes(qa, fm) + (style_mod.faults(st, 'zh') if st.get('checked') else [])
                  + leak_faults(lk, 'zh'))
        if score > best_score:
            obj, best_score = o, score
            rec['best_attempt'] = attempt + 1
        if (not chk['missing_slot_ids'] and fm['form_status'] == 'passed' and not qa_blocking
                and lk['status'] == 'passed'
                and (not st.get('checked') or st.get('passed'))):
            break

    if obj is None:
        rec.update(run_status='failed', finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / (cid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return rec

    text = '\n\n'.join(s['text'] for s in obj['sentences'])
    ledger = build_ledger(obj['sentences'], slots, packet)
    used = set(used_slot_ids(obj['sentences']))
    placed_facts = {s['fact_id'] for s in slots if s['slot_id'] in used}

    qa = evaluate({'sentence_to_source_ledger': ledger}, packet,
                  must_include=packet['coverage']['required_core_ids'])
    form = form_check(text, ledger, slots)
    placement = placement_from_usage(obj['sentences'], slots)
    # Evidence and form are independent. A draft has to clear both.
    leak = leak_check(text, ledger)
    ok = (qa['status']['qa_status'] == 'passed' and form['form_status'] == 'passed'
          and not placement['missing_slot_ids'] and leak['status'] == 'passed')
    rec.update(title=obj.get('title'), text=text, sentence_to_source_ledger=ledger,
               slot_placement=placement,
               facts_placed_by_code=sorted(placed_facts),
               qa=qa, form=form,
               language_donor=donor, leak_check=leak,
               style_check=(style_mod.check(text, style_target)
                            if style_target.get('usable') else {'checked': False}),
               run_status='completed',
               qa_status=qa['status']['qa_status'],
               form_status=form['form_status'],
               content_status=('ready_for_pipeline' if ok else 'blocked'),
               finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    rec['delivery'] = classify(rec)
    rec['human_review'] = 'none'
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (cid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    packet = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
    roles_doc = json.loads((ROOT / 'evidence_loop/experiments/roles_v2.json').read_text())
    retrieval = json.loads((ROOT / 'evidence_loop/experiments/retrieval.json').read_text())
    corpus = {}
    for line in (ROOT / 'data/clean_posts.jsonl').read_text().split('\n'):
        if line:
            r = json.loads(line)
            corpus[r['post_id']] = r

    targets = ([args['persona']] if args.get('persona')
               else list(roles_doc['personas']))
    for pid in targets:
        r = generate(pid, packet, roles_doc, retrieval, corpus)
        sp = r.get('slot_placement', {})
        print(json.dumps({'id': r['id'], 'persona': pid, 'run': r['run_status'],
                          'qa': r.get('qa_status'), 'content': r.get('content_status'),
                          'slots': f"{sp.get('placed')}/{sp.get('total')}",
                          'blocking': (r.get('qa') or {}).get('status', {}).get('blocking_count'),
                          'attempts': len(r['attempts'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
