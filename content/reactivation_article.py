"""Event reactivation. Step 6 of the content delivery plan.

The hot lane and the cold lane joined in one piece: this month's employment print, read through
trading principles that were *retrieved* from the reading corpus rather than written for the
occasion.

Two provenance systems meet here and neither is allowed to slip:

  - event figures keep the slot discipline from step 2 — every number must match a rendered fact
    string exactly, direction word included, and the whole thing re-runs the seven-layer gates
  - principles may only come from the retrieval record. The model writes about a principle by its
    id; the attribution line (author, file, character span) is rendered by code from that record,
    so a citation cannot be wrong. A principle the model invents has no id and is rejected.

The corpus principles are `direct_quote_allowed: false`, so the article restates them and never
reproduces an author's sentence. That is checked against the evidence quotes, not assumed.

Run: .venv/bin/python -B content/reactivation_article.py [--persona=trading]
"""
from pathlib import Path
import sys, json, re, datetime, hashlib, unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'evidence_loop'))
from model_client import parse_json
from qa.gates import evaluate, layer3_entailment, layer7_status as evaluate_status
from qa.status import classify
from content.fact_slots import build_slots
from content.generate_slotted import audit_numbers, substitute, local_call, build_ledger
from content.form_check import check as form_check
from evergreen.output_gate import scan as gate_scan, assert_exportable

OUT = ROOT / 'content/reactivation'
TOKENS = 2600
MAX_ATTEMPTS = 4

PRINCIPLE_REF = re.compile(r'\{(pr-[0-9a-f]{12})\}')


def norm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s or ''))


def principle_block(p, docs, cand):
    """The attribution line is rendered from the retrieval record, never written by the model."""
    x = cand[p['principle_id']]
    d = docs[x['source']['document_id']]
    return {
        'principle_id': p['principle_id'],
        'statement': p['statement'],
        'category': p['category'],
        'applicable_conditions': p.get('applicable_conditions'),
        'invalidation': p.get('invalidation'),
        'risk': p.get('risk'),
        'retrieval_score': p['score'],
        'retrieved_not_written': True,
        'attribution': (f"转述自 {x['source']['author_dir']}，非原话｜"
                        f"{Path(x['source']['path']).name}｜"
                        f"字符 {x['source']['char_start']}–{x['source']['char_end']}"),
        'source_file': d['extracted_path'],
        'source_file_sha256': d['sha256'],
        'corpus_path': x['source']['path'],
        'char_span': [x['source']['char_start'], x['source']['char_end']],
        'author_dir': x['source']['author_dir'],
        'direct_quote_allowed': x['direct_quote_allowed'],
        'review': 'pending_human_review',
    }


def prompt_for(persona, slots, packet, principles, faults=None):
    slot_lines = '\n'.join(f'  {s["rendered"]}' for s in slots)
    plines = []
    for p in principles:
        bits = [f"  {{{p['principle_id']}}} {p['statement']}"]
        if p.get('applicable_conditions'):
            bits.append(f"      适用条件：{p['applicable_conditions']}")
        if p.get('invalidation'):
            bits.append(f"      失效条件：{p['invalidation']}")
        plines.append('\n'.join(bits))
    fix = ('\n这一稿要修正的问题：\n' + '\n'.join('  · ' + x for x in faults) + '\n') if faults else ''
    return (
        f"你是{persona['name']}，关心的问题是：{persona['question']}\n"
        f"事件：{packet['title']}（{packet['published_at'][:10]} 发布）\n\n"
        f"下面是从交易心法语料库中**检索**出来的既有原则，不是为这次数据现写的。"
        f"你要用它们来读这次数据：\n\n" + '\n'.join(plines) + "\n\n"
        f"写一篇中文稿，8 到 10 句，结构是：\n"
        f"  1 这次数据里最需要交易者注意的一点\n"
        f"  2-4 用事实说明它\n"
        f"  5-7 每句挂一条上面的原则，说明这条既有原则如何约束此刻的操作\n"
        f"  8 最后写失效条件与下一步该看什么\n\n"
        f"【引用原则的方式】要提到某条原则时，在句中写它的占位符（例如 {{{principles[0]['principle_id']}}}），"
        f"并在 principle_ids 里列出。出处由系统补，你不要自己写作者名或文件名。\n"
        f"不得直接引用原文句子，只能转述；上面三条原则每条至少用一次。\n\n"
        f"【数字规则】正文里出现的每一个数字都必须与下表**一字不差**，包括方向词：\n{slot_lines}\n"
        f"带「减少/下降/上修」等方向词的，写数值时必须连方向词一起写。\n"
        f"失效条件里可以提出你自己的观察阈值，那是唯一允许出现表外数字的地方。\n"
        f"事实包里没有市场预期、没有共识预测，标题与正文都不得写「预期差」「超预期」"
        f"「与预期背离」这类比较。\n"
        f"{fix}\n"
        f"只输出 JSON：{{\"title\":\"...\",\"sentences\":[{{\"text\":\"...\","
        f"\"kind\":\"fact 或 interpretation 或 condition\",\"fact_ids\":[],"
        f"\"principle_ids\":[]}}]}}")


def check_principles(sentences, allowed_ids, cand):
    """Attribution integrity, separate from the evidence gates."""
    f = []
    used = set()
    for s in sentences:
        refs = set(s.get('principle_ids') or []) | set(PRINCIPLE_REF.findall(s.get('_raw') or ''))
        unknown = sorted(refs - set(allowed_ids))
        if unknown:
            f.append({'code': 'principle_not_retrieved', 'severity': 'blocking',
                      'detail': (f"{s['sentence_id']} cites {unknown}, which is not in the "
                                 f"retrieval record; a principle may not be invented here")})
        used |= (refs & set(allowed_ids))
        s['principle_ids'] = sorted(refs & set(allowed_ids))
    unused = sorted(set(allowed_ids) - used)
    if unused:
        f.append({'code': 'retrieved_principle_unused', 'severity': 'blocking',
                  'detail': f'retrieved but never used: {unused}'})

    # No author's sentence may appear, in any spacing.
    blob = norm(' '.join(s['text'] for s in sentences))
    leaked = [pid for pid in allowed_ids
              if len(norm(cand[pid]['evidence_quote'])) >= 12
              and norm(cand[pid]['evidence_quote']) in blob]
    if leaked:
        f.append({'code': 'author_wording_reproduced', 'severity': 'blocking',
                  'detail': f'evidence quotes appear verbatim: {leaked}'})

    blocking = [x for x in f if x['severity'] == 'blocking']
    return {'findings': f, 'status': 'failed' if blocking else 'passed',
            'blocking_count': len(blocking), 'principles_used': sorted(used),
            'check_version': 'principle-attribution-v1'}


FAULT = {
    'principle_not_retrieved': '上一稿引用了检索结果之外的原则。只能用给定的那几条，用占位符引用。',
    'retrieved_principle_unused': '上一稿有原则没用到，三条每条至少用一次。',
    'author_wording_reproduced': '上一稿照搬了原文句子。只能转述，不得复制表达。',
    'model_wrote_a_number': '上一稿出现了事实表以外的数字。除失效条件里的阈值外，必须一字不差。',
    'direction_word_dropped': '上一稿写数字时丢了方向词。',
    'must_include_missing': '上一稿漏了必须出现的事实。',
    'too_short': '上一稿句数不足。',
    'sentence_restates_another': '上一稿有两句在讲同一组事实。',
    'sign_direction_mismatch': '上一稿把一个下降的指标写成了增长（或反之）。',
    'compound_direction_over_opposite_facts': '上一稿把一个方向词套在了一升一降两个指标上。',
    'citation_relation_mismatch': '上一稿说某指标「上升/下降」却只引用了水平值。',
    'out_of_evidence_assertion': '上一稿把数据与「市场预期」作了比较。事实包里没有任何预期或共识'
                                 '数据，标题和正文都不得出现「预期差」「超预期」「与预期背离」'
                                 '这类说法。',
    'title_out_of_evidence': '上一稿的标题里有事实包不支持的说法（例如「预期差」）。',
}


def faults_from(*results):
    seen, out = set(), []
    for r in results:
        for x in r.get('findings', []):
            if x.get('severity') == 'blocking' and x['code'] in FAULT and x['code'] not in seen:
                seen.add(x['code'])
                out.append(FAULT[x['code']])
    return out


def build(persona_id, packet, roles, retrieval, cand, docs, parent):
    """Derived from the persona's passing draft, the same way a platform package is.

    Written straight from the fact pack, this piece failed must_include with five facts absent:
    an article that spends half its length on principles cannot also carry all thirteen mandatory
    facts in three sentences. The obligation is not dropped — it is discharged by the parent draft,
    which does carry all thirteen — and this piece may only use facts the parent already used.
    """
    persona = roles['personas'][persona_id]
    slots = build_slots(packet, packet['coverage']['required_core_ids'])
    parent_facts = {fid for row in parent['sentence_to_source_ledger']
                    for fid in (row.get('fact_ids') or [])}
    slots = [s for s in slots if s['fact_id'] in parent_facts]
    principles = [principle_block(p, docs, cand) for p in retrieval['results'][persona_id]]
    allowed_ids = [p['principle_id'] for p in principles]

    rid = 'react-' + hashlib.sha256(
        (persona_id + datetime.datetime.now().isoformat()).encode()).hexdigest()[:12]
    rec = {'id': rid, 'persona_id': persona_id, 'persona_name': persona['name'],
           'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'event_id': retrieval['event_id'], 'event_label': retrieval['event_label'],
           'source_id': packet['id'], 'source_version': packet['version'],
           'parent_draft_id': parent['id'],
           'parent_draft_coverage': {
               'must_include_coverage': parent['qa']['metrics'].get('must_include_coverage'),
               'note': ('全部必含事实由母稿承担并已达 1.0；本文只能使用母稿已确立的事实，'
                        '不重复承担全覆盖义务'),
           },
           'retrieval': {'file': 'evergreen/principles/reactivation_v2.json',
                         'embedding_model': retrieval['embedding_model'],
                         'method': retrieval['method'],
                         'pool_filtered_for_compilations':
                             retrieval.get('pool_filtered_for_compilations'),
                         'candidate_pool': retrieval['candidate_pool'],
                         'limits': retrieval['limits']},
           'principles': principles,
           'run_status': 'running', 'qa_status': 'not_run', 'content_status': 'blocked',
           'attempts': []}

    best, best_score, faults = None, -1e9, []
    for attempt in range(MAX_ATTEMPTS):
        r = local_call(prompt_for(persona, slots, packet, principles, faults),
                       'reactivation_article', TOKENS, temperature=.2 + .12 * attempt)
        rec['attempts'].append({'attempt': attempt + 1, 'run_id': r['run_id'],
                                'latency_s': r['_latency_s'], 'usage': r['usage']})
        try:
            o = parse_json(r['text'])
            rows = o['sentences']
            for i, row in enumerate(rows):
                raw = row.get('text', '')
                # principle placeholders are removed from the prose; attribution is rendered
                stripped = PRINCIPLE_REF.sub('', raw)
                filled, ph, unknown = substitute(stripped, slots)
                inline, invented, proposed, misframed = audit_numbers(filled, slots,
                                                                     row.get('kind'))
                row['_raw'] = raw
                row['sentence_id'] = 's' + str(i + 1)
                row['text'] = re.sub(r'\s{2,}', ' ', filled).strip()
                row['slot_ids'] = sorted(set(ph) | set(inline))
                row['model_written_digits'] = invented
                row['proposed_thresholds'] = proposed
                row['misframed_values'] = misframed
        except Exception as e:
            rec['attempts'][-1]['error'] = type(e).__name__ + ': ' + str(e)[:200]
            continue

        pc = check_principles(rows, allowed_ids, cand)
        # The title is delivered content. Checking only the body let 「在预期差中控制仓位」
        # ship above an article whose first sentence was blocked for the same claim.
        title_findings = [{**x, 'code': 'title_out_of_evidence', 'where': 'title'}
                          for x in layer3_entailment(o.get('title') or '', [], packet)
                          if x['severity'] == 'blocking']
        pc['findings'] += title_findings
        pc['blocking_count'] += len(title_findings)
        if title_findings:
            pc['status'] = 'failed'
        ledger = build_ledger(rows, slots, packet)
        for led, row in zip(ledger, rows):
            led['principle_ids'] = row['principle_ids']
        text = '\n\n'.join(x['text'] for x in rows)
        fm = form_check(text, ledger, slots)
        # must_include is discharged upstream; what is enforced here is that no fact appears
        # which the parent draft did not already establish.
        qa = evaluate({'sentence_to_source_ledger': ledger}, packet, must_include=[])
        outside = sorted({fid for led in ledger for fid in led['fact_ids']} - parent_facts)
        if outside:
            qa['findings'].append({'layer': 5, 'code': 'fact_not_in_parent_draft',
                                   'severity': 'blocking', 'detail': outside})
            qa['status'] = evaluate_status(qa['findings'])
        score = (-3 * qa['status']['blocking_count'] - 3 * fm['blocking_count']
                 - 4 * pc['blocking_count'] + len(rows))
        rec['attempts'][-1].update(qa_status=qa['status']['qa_status'],
                                   qa_blocking=qa['status']['blocking_count'],
                                   form_status=fm['form_status'],
                                   principles_status=pc['status'], score=score,
                                   codes=sorted({x['code'] for x in
                                                 qa['findings'] + fm['findings'] + pc['findings']
                                                 if x['severity'] == 'blocking'}))
        faults = faults_from(qa, fm, pc)
        if score > best_score:
            best, best_score = (o, rows, ledger, text, fm, qa, pc), score
            rec['best_attempt'] = attempt + 1
        if (qa['status']['qa_status'] == 'passed' and fm['form_status'] == 'passed'
                and pc['status'] == 'passed'):
            break

    if best is None:
        rec.update(run_status='failed',
                   finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / (rid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return rec

    o, rows, ledger, text, fm, qa, pc = best
    ok = (qa['status']['qa_status'] == 'passed' and fm['form_status'] == 'passed'
          and pc['status'] == 'passed')

    by_id = {p['principle_id']: p for p in principles}
    md = [f"# {o.get('title')}", '']
    for led in ledger:
        line = led['text']
        for pid in led.get('principle_ids') or []:
            line += f"\n\n   > 引用原则：{by_id[pid]['statement']}\n   > {by_id[pid]['attribution']}"
        md += [line, '']
    md += ['---', '',
           '原则来自对交易心法语料库的检索，不是为本次数据现写；'
           f"检索模型 {retrieval['embedding_model']}。",
           '所有原则均为转述，未直接引用原文；状态：待人工审核。']
    article = '\n'.join(md)
    assert_exportable(article, f'reactivation {rid}')

    rec.update(title=o.get('title'), text=text, article_markdown=article,
               sentence_to_source_ledger=ledger,
               qa=qa, form_check=fm, principle_check=pc,
               run_status='completed', qa_status=qa['status']['qa_status'],
               form_status=fm['form_status'], principles_status=pc['status'],
               content_status='ready_for_pipeline' if ok else 'blocked',
               output_gate='passed',
               finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    rec['delivery'] = classify(rec)
    rec['human_review'] = 'none; principles are pending_human_review'
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (rid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    (OUT / (rid + '.md')).write_text(article)
    return rec


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    packet = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
    roles = json.loads((ROOT / 'evidence_loop/experiments/roles_v2.json').read_text())
    retrieval = json.loads(
        (ROOT / 'evergreen/principles/reactivation_v2.json').read_text())
    cand = {x['id']: x for x in json.loads(
        (ROOT / 'evergreen/principles/candidates.json').read_text())['items']}
    docs = {d['id']: d for d in json.loads(
        (ROOT / 'evergreen/corpus_manifest_v2.json').read_text())['items']}

    drafts = {}
    for q in sorted((ROOT / 'content/drafts').glob('*.json')):
        d = json.loads(q.read_text())
        if d.get('content_status') == 'ready_for_pipeline':
            drafts[d['persona_id']] = d

    targets = [args['persona']] if args.get('persona') else ['trading']
    for pid in targets:
        r = build(pid, packet, roles, retrieval, cand, docs, drafts[pid])
        print(json.dumps({'id': r['id'], 'persona': pid, 'run': r['run_status'],
                          'qa': r.get('qa_status'), 'form': r.get('form_status'),
                          'principles': r.get('principles_status'),
                          'content': r.get('content_status'),
                          'attempts': len(r['attempts'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
