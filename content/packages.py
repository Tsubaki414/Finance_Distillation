"""Platform packages. Step 3 of the content delivery plan.

A draft that clears the gates is not yet something an editor can use. This turns each passing
draft into the forms operations actually take away: an X post, an X thread, a 小红书 title with
body and card script, a Reddit discussion opener, and a community brief.

Adaptation is real writing, not truncation, so the model writes each form. The discipline from
step 2 carries over unchanged:

  - the only facts available are the ones already in the source draft
  - every figure must match a rendered slot string exactly, direction word included
  - each derived piece is re-run through the same seven-layer gates, not assumed correct
    because its parent passed

Each package ships with the source pack, so any sentence can be traced to a character range in
the original release, plus the update and invalidation conditions taken from the draft itself.

Run: .venv/bin/python -B content/packages.py [--draft=draft-xxxx] [--form=x_post]
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
from content import sources as src
from content.generate_slotted import (audit_numbers, substitute, local_call,
                                      THRESHOLD_CLAUSE)
sys.path.insert(0, str(ROOT / 'live'))
import write as live_write

OUT = ROOT / 'content/packages'
PACKAGE_TOKENS = 1800
MAX_ATTEMPTS = 4


CJK = re.compile(r'[ᄀ-ᇿ⺀-〾ぁ-㏿㐀-䶿一-鿿'
                 r'ꀀ-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]')


def x_weight(text):
    """X counts a CJK character as two units, so a 280-limit post is 140 Chinese characters.

    Measuring in characters would have let a package ship at twice the platform limit.
    """
    return sum(2 if CJK.match(c) else 1 for c in (text or ''))


# Each form states its own shape. Length limits are the platform's, not ours to relax.
FORMS = {
    'x_post': {
        'name': 'X 单帖',
        'shape': '一条 X 单帖。**segments 数组里只能有 1 个元素**，它就是这条帖子的全文，'
                 '不要拆成多段（那是 thread，不是单帖）。全文 3 到 4 句，'
                 '中文总共不超过 135 个字（X 对中文按两个单位计，这是硬上限）。'
                 '**只选 3 到 4 条最关键的事实**，不要罗列全部。'
                 '第一句给判断，中间给这几个数字，最后一句给失效条件。'
                 '不要话题标签，不要 emoji，不要引流语。',
        # The floor is 2, not 3. A post that opens "判断：数据…" with a colon carries the
        # judgement, the evidence and the invalidation in two sentences; the count was a proxy for
        # structure, and structure is already checked directly. The 280-unit platform limit is not
        # a proxy and is not adjustable.
        'limit': 280, 'floor': 120, 'weigh': True, 'units': (2, 5), 'max_segments': 1,
    },
    'x_thread': {
        'name': 'X thread',
        'shape': '一条 X thread，5 到 6 段。第 1 段抛出判断，第 2 到 4 段各用一组数字推进论证，'
                 '倒数第二段给相反读法，最后一段给失效条件与下一步该看什么。'
                 '每段独立成立，中文每段不超过 130 字。',
        'limit': 280, 'floor': 40, 'weigh': True, 'units': (5, 7), 'per_segment': True,
    },
    'xiaohongshu': {
        'name': '小红书',
        'shape': '小红书笔记。标题必须在 24 个字以内，要具体，不要「速看」「重磅」这类词。'
                 '正文 5 到 7 段，口语一些但不能牺牲准确，解释清楚每个数字为什么重要。'
                 '最后给失效条件。',
        'limit': 1000, 'floor': 300, 'units': (5, 8), 'needs_title': True, 'per_segment': True,
    },
    'reddit': {
        'name': 'Reddit 讨论稿',
        'shape': '一篇 Reddit 讨论帖。先摆事实与数据，再给你的读法，明确标出哪些是推断、'
                 '哪些是数据本身，最后提一个具体的、能被数据回答的问题给读者。5 到 7 句。',
        'limit': 1600, 'floor': 300, 'units': (5, 8),
    },
    'brief': {
        'name': '社群简报',
        'shape': '给内部社群的简报，4 到 6 条要点，每条一行。先结论后依据。'
                 '最后一行写失效条件。不要客套话。',
        'limit': 800, 'floor': 150, 'units': (4, 7), 'per_segment': True,
    },
}

SENTENCE_END = re.compile(r'[。！？!?]')


def source_pack(draft, packet, raw):
    """Fact id -> the exact characters it came from, so any claim can be opened at its origin."""
    facts = {f['id']: f for f in packet['facts']}
    used = sorted({fid for row in draft['sentence_to_source_ledger']
                   for fid in (row.get('fact_ids') or [])})
    entries = []
    for fid in used:
        fx = facts.get(fid)
        if not fx:
            continue
        span = fx['source_span']
        entries.append({
            'fact_id': fid, 'label': fx['label'], 'value': fx['value'], 'unit': fx['unit'],
            'period': fx['period'], 'survey': fx.get('survey'),
            'primary_url': packet['primary_url'],
            'artifact_path': packet['artifact_path'],
            'artifact_sha256': packet['artifact_sha256'],
            'char_span': [span['start'], span['end']],
            'quote': span['quote'],
            'quote_resolves': raw[span['start']:span['end']] == span['quote'],
            'source_block_ids': fx['source_block_ids'],
        })
    return entries


def conditions_from(draft):
    """Update and invalidation conditions are the writer's, so they are carried, not re-derived."""
    invalid, thresholds = [], []
    for row in draft['sentence_to_source_ledger']:
        if row.get('kind') == 'condition':
            invalid.append(row['text'])
        thresholds += row.get('proposed_thresholds') or []
    return {
        'invalidation': invalid,
        'author_proposed_thresholds': sorted(set(thresholds)),
        'threshold_note': ('这些阈值是作者提出的观察条件，不是事实包里的数据，'
                           '不得当作已发生的数字引用。'),
        'update_when': ['原始事实包发布新版本或数据被修订', '下一期同一指标发布'],
        'next_release': draft.get('next_update'),
    }


PACKAGE_FAULT = {
    'model_wrote_a_number': '上一版出现了事实表以外的数字。除失效条件里的阈值外，'
                            '所有数字必须与表内一字不差。',
    'direction_word_dropped': '上一版写数字时丢了方向词，「减少/下降/上修」必须跟着数值一起写。',
    'no_invalidation_condition': '上一版没有写失效条件，必须写明什么情况会推翻这个判断。',
    'missing_title': '上一版缺标题。',
    'citation_relation_mismatch': '上一版有句子说某指标「上升/下降」，但引用的只是一个水平值。',
    'compound_direction_over_opposite_facts':
        '上一版把一个方向词同时套在一升一降两个指标上，要分开写。',
    'sign_direction_mismatch': '上一版把一个下降的指标描述成了增长（或反之）。',
}


def package_faults(form_key, form_result, qa):
    """Tell the writer by how much it missed. Three attempts in a row failed on length because
    "上一版超长" never said 323 against a limit of 280."""
    form = FORMS[form_key]
    cn = form['limit'] // 2 if form.get('weigh') else form['limit']
    out, seen = [], set()
    for x in form_result['findings'] + qa['findings']:
        if x.get('severity') != 'blocking' or x['code'] in seen:
            continue
        seen.add(x['code'])
        c, detail = x['code'], x.get('detail')
        if c == 'too_long':
            over = form_result['measured'] - form['limit']
            out.append(f'上一版长度 {form_result["measured"]}，上限 {form["limit"]}，'
                       f'超出 {over}。中文正文总共不能超过约 {cn} 个字，请重写得更短，'
                       f'不能靠删掉失效条件来达标。')
        elif c == 'segment_too_long':
            out.append(f'上一版有段落超出上限：{detail}。每段中文不超过约 {cn} 个字。')
        elif c == 'too_short':
            need = form['floor'] - form_result['measured']
            out.append(f'上一版长度 {form_result["measured"]}，下限 {form["floor"]}，'
                       f'还差 {need}，需要展开论证而不是加套话。')
        elif c == 'unit_count':
            lo, hi = form['units']
            out.append(f'上一版是 {form_result["units"]} {form_result["unit_name"]}，'
                       f'要求 {lo} 到 {hi} 个。')
        elif c == 'too_many_segments':
            out.append(f'上一版把它写成了 {form_result["segments"]} 段。'
                       f'这是单帖，segments 数组里只能有 1 个元素，全文放在里面。')
        elif c == 'title_too_long':
            out.append(f'上一版标题 {detail}。标题必须控制在 24 个字以内，写得更短更具体。')
        elif c in PACKAGE_FAULT:
            out.append(PACKAGE_FAULT[c])
    return out


def prompt_for(form_key, draft, slots_used, faults=None):
    form = FORMS[form_key]
    body = '\n'.join(f"  {r['text']}" for r in draft['sentence_to_source_ledger'])
    table = '\n'.join(f"  {s['rendered']}" for s in slots_used)
    title_field = '"title":"标题",' if form.get('needs_title') else ''
    fix = ('\n这一版要修正的问题：\n' + '\n'.join('  · ' + x for x in faults) + '\n') if faults else ''
    return (
        f"你是{draft.get('persona_name') or draft.get('account_name')}。"
        f"下面是你已经写好并通过事实核查的稿子。\n\n"
        f"原稿：\n{body}\n\n"
        f"现在把它改写成{form['name']}。{form['shape']}\n\n"
        f"【硬约束】只能使用原稿里已有的事实，不得引入新数字、新指标、新来源。\n"
        f"正文里出现的每一个数字都必须与下表**一字不差**，包括方向词：\n{table}\n"
        f"表里带“减少/下降/上修”等方向词的，写出数值时必须连方向词一起写。\n"
        f"不需要用满全部事实，选与这个平台读者相关的即可，但用到的必须一字不差。\n"
        f"失效条件里可以提出你自己的观察阈值，那是这篇唯一允许出现表外数字的地方。\n"
        f"{fix}\n"
        f"只输出 JSON：{{{title_field}\"segments\":[{{\"text\":\"一段完整文字\","
        f"\"kind\":\"fact 或 interpretation 或 condition\",\"fact_ids\":[]}}]}}")


def audit_segments(segments, slots, allowed_facts, generic=False):
    """Same audit as the draft that produced it.

    There were two number audits in the codebase: the curated one matches a rendered Chinese
    frame as a string and checks the direction word travelled with the figure; the live one
    compares value and unit, so "534 亿" and "534 亿美元" are the same number written two ways.
    Running the curated matcher over live slots rejected correct figures — 534 亿, 661 亿,
    1162 亿 are exactly the Amazon numbers — because it was the wrong audit for those slots,
    not because anything was wrong with the writing.
    """
    for i, seg in enumerate(segments):
        raw = seg.get('text', '')
        filled, ph, unknown = substitute(raw, slots)
        if generic:
            inline, invented, proposed = live_write.audit(filled, slots)
            misframed = []
        else:
            inline, invented, proposed, misframed = audit_numbers(filled, slots, seg.get('kind'))
        seg['text'] = filled
        seg['segment_id'] = 'p' + str(i + 1)
        seg['slot_ids'] = sorted(set(ph) | set(inline))
        seg['model_written_digits'] = invented
        seg['proposed_thresholds'] = proposed
        seg['misframed_values'] = misframed
        refs = [x for x in (seg.get('fact_ids') or []) if x in allowed_facts]
        for sid in seg['slot_ids']:
            slot = next((s for s in slots if s['slot_id'] == sid), None)
            if slot and slot['fact_id'] not in refs:
                refs.append(slot['fact_id'])
        seg['fact_ids'] = refs
    return segments


def check_form(form_key, segments, title):
    """Platform shape. A package that breaks the platform's limit is not deliverable."""
    form = FORMS[form_key]
    f = []
    joined = ''.join(s['text'] for s in segments)
    measure = x_weight if form.get('weigh') else len
    unit = 'weighted units' if form.get('weigh') else 'chars'

    # A thread's unit is the post; everything else is judged on sentences, because the model
    # returns one block of prose whether or not it was asked for several.
    if form.get('per_segment') and form_key in ('x_thread', 'xiaohongshu', 'brief'):
        n, unit_name = len(segments), 'segments'
    else:
        n, unit_name = len(SENTENCE_END.findall(joined)), 'sentences'
    lo, hi = form['units']
    if not (lo <= n <= hi):
        f.append({'code': 'unit_count', 'severity': 'blocking',
                  'detail': f'{n} {unit_name}, expected {lo}-{hi}'})

    if form.get('max_segments') and len(segments) > form['max_segments']:
        f.append({'code': 'too_many_segments', 'severity': 'blocking',
                  'detail': (f"{len(segments)} segments; this form is a single post and takes "
                             f"{form['max_segments']}")})

    if form.get('per_segment'):
        over = [(s['segment_id'], measure(s['text'])) for s in segments
                if measure(s['text']) > form['limit']]
        if over:
            f.append({'code': 'segment_too_long', 'severity': 'blocking',
                      'detail': f"over {form['limit']} {unit}: {over}"})
    elif measure(joined) > form['limit']:
        f.append({'code': 'too_long', 'severity': 'blocking',
                  'detail': f"{measure(joined)} {unit}, limit {form['limit']}"})
    if measure(joined) < form['floor']:
        f.append({'code': 'too_short', 'severity': 'blocking',
                  'detail': f"{measure(joined)} {unit}, minimum {form['floor']}"})

    if form.get('needs_title'):
        if not (title or '').strip():
            f.append({'code': 'missing_title', 'severity': 'blocking',
                      'detail': 'title is required'})
        elif len(title) > 24:
            f.append({'code': 'title_too_long', 'severity': 'blocking',
                      'detail': f'{len(title)} chars, limit 24'})

    typed = [(s['segment_id'], s['model_written_digits']) for s in segments
             if s.get('model_written_digits')]
    if typed:
        f.append({'code': 'model_wrote_a_number', 'severity': 'blocking',
                  'detail': f'figures not in the fact table: {typed}'})
    mis = [s['segment_id'] for s in segments if s.get('misframed_values')]
    if mis:
        f.append({'code': 'direction_word_dropped', 'severity': 'blocking',
                  'detail': f'figures written without their direction word: {mis}'})
    # `kind` is the model's own label and it puts a 失效条件 inside a block it calls "fact", so
    # the condition is detected from the text.
    if not THRESHOLD_CLAUSE.search(joined):
        f.append({'code': 'no_invalidation_condition', 'severity': 'blocking',
                  'detail': 'every package must state what would make it wrong'})

    blocking = [x for x in f if x['severity'] == 'blocking']
    return {'findings': f, 'form_status': 'failed' if blocking else 'passed',
            'blocking_count': len(blocking), 'chars': len(joined),
            'measured': measure(joined), 'measure': unit,
            'units': n, 'unit_name': unit_name, 'segments': len(segments),
            'check_version': 'package-form-v2'}


def build(form_key, draft, packet, slots, raw):
    allowed = {f['id']: f for f in packet['facts']}
    used_ids = {fid for row in draft['sentence_to_source_ledger']
                for fid in (row.get('fact_ids') or [])}
    slots_used = [s for s in slots if s['fact_id'] in used_ids]

    pid = 'pkg-' + hashlib.sha256(
        (draft['id'] + form_key + datetime.datetime.now().isoformat()).encode()).hexdigest()[:12]
    rec = {'id': pid, 'form': form_key, 'form_name': FORMS[form_key]['name'],
           'draft_id': draft['id'], 'persona_id': draft['persona_id'],
           'persona_name': draft.get('persona_name') or draft.get('account_name'),
           'account_id': draft.get('account_id'),
           'origin': 'live' if draft.get('account_id') else 'curated',
           'entity': draft.get('entity'),
           'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'source_version': packet['version'],
           'roles': draft.get('roles') or {'language': draft.get('language_donor')},
           'profile_channel': draft.get('profile_channel'),
           'source_id': draft.get('source_id') or draft.get('packet_id'),
           'run_status': 'running', 'qa_status': 'not_run', 'content_status': 'blocked',
           'attempts': []}

    best, best_score, faults = None, -1, []
    for attempt in range(MAX_ATTEMPTS):
        # Retrying at the same temperature reproduced the previous failure token for token,
        # so later attempts get more room to move.
        r = local_call(prompt_for(form_key, draft, slots_used, faults), 'platform_package',
                       PACKAGE_TOKENS, temperature=.2 + .15 * attempt)
        rec['attempts'].append({'attempt': attempt + 1, 'run_id': r['run_id'],
                                'latency_s': r['_latency_s'], 'usage': r['usage']})
        try:
            o = parse_json(r['text'])
            segs = audit_segments(o.get('segments') or [], slots, allowed,
                                  generic=src.is_generic(packet))
            if not segs:
                raise ValueError('no segments')
        except Exception as e:
            rec['attempts'][-1]['error'] = type(e).__name__ + ': ' + str(e)[:200]
            continue
        title = o.get('title') or draft.get('title')
        fm = check_form(form_key, segs, title)
        ledger = [{'sentence_id': s['segment_id'], 'text': s['text'], 'kind': s.get('kind'),
                   'fact_ids': s['fact_ids'], 'slot_ids': s['slot_ids'],
                   'proposed_thresholds': s['proposed_thresholds'],
                   'misframed_values': s['misframed_values'],
                   'source_block_ids': sorted({b for fid in s['fact_ids']
                                               for b in allowed[fid]['source_block_ids']}),
                   'primary_url': packet['primary_url'],
                   'source_hash': packet['artifact_sha256']} for s in segs]
        # must_include is empty on purpose: a package selects for its platform, and the
        # mandatory-coverage rule belongs to the draft, which already satisfied it.
        qa = evaluate({'sentence_to_source_ledger': ledger}, packet, must_include=[])
        score = (10 - qa['status']['blocking_count'] * 3 - fm['blocking_count'] * 3)
        rec['attempts'][-1].update(qa_status=qa['status']['qa_status'],
                                   qa_blocking=qa['status']['blocking_count'],
                                   form_status=fm['form_status'], score=score,
                                   qa_codes=sorted({x['code'] for x in qa['findings']
                                                    if x['severity'] == 'blocking'}),
                                   form_codes=sorted({x['code'] for x in fm['findings']}))
        faults = package_faults(form_key, fm, qa)
        if score > best_score:
            best, best_score = (o, segs, title, fm, qa, ledger), score
            rec['best_attempt'] = attempt + 1
        if qa['status']['qa_status'] == 'passed' and fm['form_status'] == 'passed':
            break

    if best is None:
        rec.update(run_status='failed',
                   finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / (pid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return rec

    o, segs, title, fm, qa, ledger = best
    ok = qa['status']['qa_status'] == 'passed' and fm['form_status'] == 'passed'
    rec.update(title=title, segments=segs, sentence_to_source_ledger=ledger,
               source_pack=source_pack(draft, packet, raw),
               conditions=conditions_from(draft),
               qa=qa, form_check=fm, run_status='completed',
               qa_status=qa['status']['qa_status'], form_status=fm['form_status'],
               content_status='ready_for_pipeline' if ok else 'blocked',
               finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    rec['delivery'] = classify(rec)
    rec['human_review'] = 'none'
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (pid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    """Every ready draft from either pipeline, packaged against its own fact pack.

    This used to load one hardcoded packet and one directory, which is why the daily loop
    produced text that no downstream stage could consume.
    """
    rows, a = src.select(sys.argv[1:])
    if not rows:
        print('no ready drafts')
        return
    forms_arg = [a['raw']['form']] if a['raw'].get('form') else None
    acct_cfg = {}
    cfg_path = ROOT / 'live/accounts.json'
    if cfg_path.is_file():
        acct_cfg = {x['id']: x for x in json.loads(cfg_path.read_text())['accounts']}

    for r in rows:
        packet, draft = r['packet'], r['draft']
        raw_path = ROOT / packet['artifact_path']
        raw = raw_path.read_text() if raw_path.is_file() else packet.get('full_narrative', '')
        slots = src.build_slots(packet, r['lang'], limit=10)
        if len(slots) < 3:
            print(f"  SKIP {r['label']:18} {str(r['event'])[:12]:14} "
                  f"only {len(slots)} usable figures")
            continue
        # A Chinese account has no use for a Reddit thread and an English one none for a
        # 小红书 card. The account config already declares which forms it runs; a curated
        # draft has no account, so it gets everything.
        acct = acct_cfg.get(r['account_id'] or '')
        forms = forms_arg or (acct['formats'] if acct else list(FORMS))
        for fk in forms:
            out = build(fk, draft, packet, slots, raw)
            print(json.dumps({'id': out['id'], 'origin': r['origin'],
                              'who': r['label'], 'event': r['event'], 'form': fk,
                              'run': out['run_status'], 'qa': out.get('qa_status'),
                              'form_status': out.get('form_status'),
                              'content': out.get('content_status')},
                             ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
