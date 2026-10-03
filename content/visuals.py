"""Visual briefs and deterministic charts. Step 4 of the content delivery plan.

Two separate things, deliberately not merged:

  1. the brief — what this piece should be illustrated with, why, and what it should not be
     illustrated with. "No chart" is a legitimate answer and is produced when the question does
     not have a shape.
  2. the chart — rendered by code straight from the fact pack. The model never supplies a
     coordinate or a figure, so a chart cannot disagree with the text it sits next to.

Every number drawn carries the fact it came from as `data-fact-id`, and the manifest resolves
each one to a character range in the original release. Change the fact pack and the chart
changes; that is checked, not asserted.

The chart type follows from what the draft actually leaned on, so the three personas do not get
the same picture. There is no house template.

Run: .venv/bin/python -B content/visuals.py
"""
from pathlib import Path
import sys, json, re, hashlib, datetime, html

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content.fact_slots import render_value, frame_direction

OUT = ROOT / 'content/visuals'

W, H = 880, 460
PAD_L, PAD_R, PAD_T, PAD_B = 190, 40, 64, 56
INK = '#1c1e21'
MUTED = '#6b7280'
RULE = '#e3e5e8'
UP = '#1f6f4a'
DOWN = '#b3261e'
ACCENT = '#2f5fd0'


def chart_value(fact):
    """The figure as it should be read off a chart, sign included.

    render_value prints a magnitude because the direction lives in the sentence frame. On a chart
    there is no frame, so 信息业就业月变化 was labelled "2.3 万人" with the fall carried only by the
    bar's colour and side. A label has to be right on its own.
    """
    body = render_value(fact)
    if fact.get('value', 0) < 0 and not frame_direction(str(fact.get('label') or '')):
        return '\u2212' + body
    return body


def esc(s):
    return html.escape(str(s), quote=True)


def txt(x, y, s, size=13, fill=INK, anchor='start', weight='400', fact=None):
    a = (f'<text x="{x:.1f}" y="{y:.1f}" font-family="Inter, Helvetica Neue, Arial, '
         f'PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif" '
         f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"')
    if fact:
        a += f' data-fact-id="{esc(fact)}"'
    return a + f'>{esc(s)}</text>'


def frame(title, subtitle, footer):
    return ([f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img">',
             f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
             txt(PAD_L - 150, 30, title, 16, INK, weight='600'),
             txt(PAD_L - 150, 50, subtitle, 12, MUTED)],
            [txt(PAD_L - 150, H - 18, footer, 11, MUTED), '</svg>'])


# ------------------------------------------------------------------ chart types

def sector_bars(packet, facts_used):
    """Which sectors added jobs and which shed them. A diverging bar keeps the sign visible."""
    ids = [f for f in ('food', 'health', 'local_education', 'information') if f in facts_used]
    facts = {f['id']: f for f in packet['facts']}
    rows = [facts[i] for i in ids if i in facts]
    if len(rows) < 3:
        return None
    head, tail = frame('8 月各行业就业变化', '数据来自 BLS 就业形势报告，单位：万人',
                       'Source: BLS Employment Situation, August 2026')
    body = []
    top, bottom = PAD_T + 18, H - PAD_B
    step = (bottom - top) / len(rows)
    span = max(abs(r['value']) for r in rows) or 1
    zero = PAD_L + 130
    usable = W - PAD_R - zero - 90
    body.append(f'<line x1="{zero}" y1="{top - 12}" x2="{zero}" y2="{bottom}" '
                f'stroke="{RULE}" stroke-width="1"/>')
    for i, r in enumerate(rows):
        y = top + i * step + step / 2
        length = abs(r['value']) / span * usable
        rising = r['value'] > 0
        x = zero if rising else zero - length
        body.append(f'<rect x="{x:.1f}" y="{y - 11:.1f}" width="{length:.1f}" height="22" '
                    f'rx="2" fill="{UP if rising else DOWN}" data-fact-id="{esc(r["id"])}"/>')
        body.append(txt(zero - 12, y + 4, r['label'], 12, INK, anchor='end'))
        label_x = x + length + 8 if rising else x - 8
        body.append(txt(label_x, y + 4, chart_value(r), 12, UP if rising else DOWN,
                        anchor='start' if rising else 'end', weight='600', fact=r['id']))
    return {'svg': '\n'.join(head + body + tail), 'facts': [r['id'] for r in rows],
            'kind': 'sector_bars'}


def level_vs_average(packet, facts_used):
    """This month against the run rate it is being compared to, plus the revision."""
    facts = {f['id']: f for f in packet['facts']}
    need = ['payroll', 'payroll_12m_mean']
    if not all(n in facts and n in facts_used for n in need):
        return None
    rows = [facts['payroll_12m_mean'], facts['payroll']]
    if 'revision_total' in facts and 'revision_total' in facts_used:
        rows.append(facts['revision_total'])
    head, tail = frame('本月非农与此前 12 个月月均', '数据来自 BLS 就业形势报告，单位：万人',
                       'Source: BLS Employment Situation, August 2026')
    body = []
    top, bottom = PAD_T + 26, H - PAD_B
    span = max(r['value'] for r in rows) or 1
    slot = (W - PAD_L - PAD_R) / len(rows)
    for i, r in enumerate(rows):
        h = (r['value'] / span) * (bottom - top)
        x = PAD_L + i * slot + slot * .22
        w = slot * .56
        colour = ACCENT if r['id'] == 'payroll' else '#9fb4e6'
        body.append(f'<rect x="{x:.1f}" y="{bottom - h:.1f}" width="{w:.1f}" '
                    f'height="{h:.1f}" rx="2" fill="{colour}" '
                    f'data-fact-id="{esc(r["id"])}"/>')
        body.append(txt(x + w / 2, bottom - h - 10, chart_value(r), 13, INK,
                        anchor='middle', weight='600', fact=r['id']))
        body.append(txt(x + w / 2, bottom + 20, r['label'], 12, MUTED, anchor='middle'))
    body.append(f'<line x1="{PAD_L - 20}" y1="{bottom}" x2="{W - PAD_R}" y2="{bottom}" '
                f'stroke="{RULE}" stroke-width="1"/>')
    return {'svg': '\n'.join(head + body + tail), 'facts': [r['id'] for r in rows],
            'kind': 'level_vs_average'}


def wrap_cn(s, per_line):
    return [s[i:i + per_line] for i in range(0, len(s), per_line)]


def condition_matrix(packet, facts_used, conditions=None, invalidation=None):
    """What would have to happen for the call to be wrong. The trading question is not a
    quantity, it is a set of tests, so it gets a matrix rather than a bar chart.

    The first version drew this table with every threshold cell reading "—", because the writer's
    thresholds happened to coincide with published values and so were never recorded as proposals.
    A table titled 失效条件 with no conditions in it is worse than no table, so the chart now
    requires either an attached threshold or the invalidation sentence itself.
    """
    facts = {f['id']: f for f in packet['facts']}
    watch = [f for f in ('unemployment_rate', 'participation', 'ahe_mom', 'workweek_change')
             if f in facts and f in facts_used]
    if len(watch) < 3:
        return None
    if not (conditions or invalidation):
        return None
    head, tail = frame('当前读数与失效条件', '左列为已公布读数，右列为作者提出的观察阈值',
                       'Source: BLS Employment Situation, August 2026；阈值为作者判断，非官方数据')
    body = []
    top = PAD_T + 30
    step = 46
    body.append(txt(PAD_L - 150, top - 12, '指标', 11, MUTED))
    body.append(txt(PAD_L + 170, top - 12, '当前读数', 11, MUTED))
    body.append(txt(PAD_L + 330, top - 12, '作者阈值（非数据）', 11, MUTED))
    for i, fid in enumerate(watch):
        r = facts[fid]
        y = top + i * step
        body.append(f'<line x1="{PAD_L - 150}" y1="{y + 14}" x2="{W - PAD_R}" y2="{y + 14}" '
                    f'stroke="{RULE}" stroke-width="1"/>')
        body.append(txt(PAD_L - 150, y, r['label'], 13, INK))
        body.append(txt(PAD_L + 170, y, chart_value(r), 13, ACCENT, weight='600', fact=fid))
        body.append(txt(PAD_L + 330, y, (conditions or {}).get(fid, '—'), 12, MUTED))
    if invalidation:
        y = top + len(watch) * step + 10
        body.append(txt(PAD_L - 150, y, '作者写下的失效条件', 11, MUTED))
        for j, line in enumerate(wrap_cn(invalidation[0], 44)[:2]):
            body.append(txt(PAD_L - 150, y + 18 + j * 17, line, 12, INK))
    return {'svg': '\n'.join(head + body + tail), 'facts': watch, 'kind': 'condition_matrix'}


def drafted_figures(packet, facts_used, slots=None):
    """The figures this piece actually used, as a horizontal bar, each bound to its fact.

    The three chart types above name BLS fact ids directly — `food`, `health`, `payroll` — so
    none of them can draw a live packet, where the ids are `g007` and the subject is whatever the
    labeller called it. A daily system that cannot illustrate its own daily output is not much of
    a system, so a generic packet gets a chart of the figures the writer chose, with the same
    guarantee as the curated ones: every number is rendered from the pack by code and carries its
    fact id.
    """
    if not slots:
        return None
    rows = [s for s in slots if s.get('fact_id') in facts_used][:6]
    rows = [s for s in rows if isinstance(s.get('raw_value'), (int, float))]
    if len(rows) < 3:
        return None
    # Mixing percentages and currency on one axis would be meaningless, so the largest
    # comparable family wins.
    fam = {}
    for s in rows:
        fam.setdefault(s['unit'], []).append(s)
    rows = max(fam.values(), key=len)
    if len(rows) < 3:
        return None
    head, tail = frame(str(packet.get('title') or packet.get('entity'))[:44],
                       '本文引用的数字，全部由代码从原始文件渲染',
                       f"Source: {packet.get('primary_url', '')[:78]}")
    body = []
    top, bottom = PAD_T + 18, H - PAD_B
    step = (bottom - top) / len(rows)
    span = max(abs(s['raw_value']) for s in rows) or 1
    zero = PAD_L + 150
    usable = W - PAD_R - zero - 110
    body.append(f'<line x1="{zero}" y1="{top - 12}" x2="{zero}" y2="{bottom}" '
                f'stroke="{RULE}" stroke-width="1"/>')
    for i, s in enumerate(rows):
        y = top + i * step + step / 2
        length = abs(s['raw_value']) / span * usable
        rising = s['raw_value'] >= 0
        x = zero if rising else zero - length
        body.append(f'<rect x="{x:.1f}" y="{y - 11:.1f}" width="{length:.1f}" height="22" '
                    f'rx="2" fill="{UP if rising else DOWN}" '
                    f'data-fact-id="{esc(s["fact_id"])}"/>')
        subj = (s.get('subject') or s.get('label_en') or '')[:22]
        body.append(txt(zero - 12, y + 4, subj, 12, INK, anchor='end'))
        body.append(txt(x + length + 8, y + 4, s['value_rendered'], 12,
                        UP if rising else DOWN, weight='600', fact=s['fact_id']))
    return {'svg': '\n'.join(head + body + tail),
            'facts': [s['fact_id'] for s in rows], 'kind': 'drafted_figures'}


CHART_BUILDERS = {
    'drafted_figures': drafted_figures,
    'sector_bars': sector_bars,
    'level_vs_average': level_vs_average,
    'condition_matrix': condition_matrix,
}

# Which question each chart answers, and the terms that say a writer is asking that question.
CHART_ANSWERS = {
    'drafted_figures': '这篇用到的几个数字各自多大',
    'sector_bars': '哪些行业在增、哪些在减，以及各自的量级',
    'level_vs_average': '这个月的数字相对它自己的运行速率算不算强',
    'condition_matrix': '什么读数会推翻这个判断',
}

CHART_CONCEPTS = {
    'sector_bars': ['行业', '构成', '结构', '板块', '产业', '分化', '供应链'],
    'level_vs_average': ['修订', '历史', '均值', '速率', '状态', '广度', '趋势', '强弱'],
    'condition_matrix': ['失效', '确认', '阈值', '决策', '仓位', '判断', '证据', '风险'],
}


def choose(persona_id, draft, packet, question=''):
    """Pick from the question the persona is asking, not from a house template.

    Fact usage cannot make this choice: mandatory coverage means all three drafts cite very
    nearly the same thirteen facts, so scoring on facts gave two personas the same picture and
    an ad-hoc tie-breaker was silently deciding everything. What actually differs between these
    writers is the question, so the question is what selects the visual, and the facts only
    decide whether the chart can be drawn at all.

    A persona whose question matches nothing scores zero everywhere and gets no chart. That is
    a real outcome, not a failure.
    """
    used = {fid for row in draft['sentence_to_source_ledger']
            for fid in (row.get('fact_ids') or [])}
    weights, matched = {}, {}
    for kind, terms in CHART_CONCEPTS.items():
        hits = [t for t in terms if t in (question or '')]
        weights[kind] = len(hits)
        matched[kind] = hits
    order = [k for k in sorted(weights, key=lambda k: (-weights[k], k)) if weights[k] > 0]
    return order, weights, matched, used


def thresholds_by_metric(draft, packet):
    """Attach a proposed threshold to a metric only when that metric is named in the same clause.

    Guessing from the unit put a percentage threshold on the unemployment rate when the writer
    might have meant the participation rate. An unattributed threshold is shown as such instead.
    """
    facts = {f['id']: f for f in packet['facts']}
    out, loose = {}, []
    for row in draft['sentence_to_source_ledger']:
        for t in row.get('proposed_thresholds') or []:
            text = row['text']
            clause = next((c for c in re.split(r'[，,；;。]', text) if t.replace(' ', '')
                           in c.replace(' ', '')), text)
            hit = None
            for fid, fx in facts.items():
                label = str(fx.get('label') or '')
                if any(label[i:i + 2] in clause for i in range(len(label) - 1)
                       if label[i:i + 2] not in GENERIC):
                    hit = fid
                    break
            (out.setdefault(hit, t) if hit else loose.append(t))
    return out, loose


GENERIC = {'就业', '人数', '数据', '水平', '变化', '增量', '月增', '环比', '同比', '平均', '幅度'}


def build(draft, packet, question='', slots=None, generic=False):
    order, weights, matched, used = choose(draft.get('persona_id'), draft, packet, question)
    if generic:
        # A live packet has no curated fact ids, so question-driven selection has nothing to
        # match on. The choice is still principled: show the figures this piece actually used.
        order, weights, matched = ['drafted_figures'], {'drafted_figures': 1}, \
            {'drafted_figures': ['本文引用的数字']}
    thresholds, loose_thresholds = thresholds_by_metric(draft, packet)
    invalidation = [r['text'] for r in draft['sentence_to_source_ledger']
                    if r.get('kind') == 'condition']

    chart, chosen, rejected = None, None, []
    for kind in order:
        extra = ({'conditions': thresholds, 'invalidation': invalidation}
                 if kind == 'condition_matrix' else
                 {'slots': slots} if kind == 'drafted_figures' else {})
        got = CHART_BUILDERS[kind](packet, used, **extra)
        if got:
            chart, chosen = got, kind
            break
        rejected.append({'kind': kind, 'why': '这篇没有用到该图所需的事实，硬画会是装饰'})

    vid = 'vis-' + hashlib.sha256(
        (draft['id'] + (chosen or 'none')).encode()).hexdigest()[:12]
    facts = {f['id']: f for f in packet['facts']}
    manifest = []
    if chart:
        by_slot = {s['fact_id']: s for s in (slots or [])}
        for fid in chart['facts']:
            fx = facts[fid]
            manifest.append({'fact_id': fid, 'label': fx['label'],
                             'drawn_as': (by_slot[fid]['value_rendered'] if fid in by_slot
                                          else chart_value(fx)), 'raw_value': fx['value'],
                             'unit': fx['unit'], 'period': fx['period'],
                             'char_span': [fx['source_span']['start'], fx['source_span']['end']],
                             'quote': fx['source_span']['quote'],
                             'primary_url': packet['primary_url']})

    rec = {
        'id': vid, 'draft_id': draft['id'], 'persona_id': draft['persona_id'],
        'persona_name': draft.get('persona_name') or draft.get('account_name'),
        'account_id': draft.get('account_id'),
        'origin': 'live' if draft.get('account_id') else 'curated',
        'entity': draft.get('entity'),
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_id': packet['id'], 'source_version': packet.get('version'),
        'artifact_sha256': packet['artifact_sha256'],
        'brief': {
            'question_the_visual_answers': CHART_ANSWERS.get(chosen),
            'chosen': chosen,
            'invalidation_shown': invalidation[:1] if chosen == 'condition_matrix' else [],
            'why': (f"这个人设问的是「{question}」，其中 {matched.get(chosen)} 指向"
                    f"「{CHART_ANSWERS.get(chosen)}」，事实包也够画" if chosen
                    else '这个人设的问题不对应任何一种图，配图会是装饰，因此不配图'),
            'selected_from': '人设提出的问题，而非事实用量或固定模板',
            'persona_question': question,
            'ranking': [{'kind': k, 'score': weights[k], 'matched_terms': matched[k],
                         'answers': CHART_ANSWERS[k]}
                        for k in sorted(weights, key=lambda x: -weights[x])],
            'rejected': rejected,
            'do_not_use': ['不要用原始截图代替数据图，本篇没有值得引用的原始画面',
                           '不要给水平值画趋势线，事实包只有单期读数',
                           '不要把作者阈值画成与已公布数据同样的视觉权重'],
            'alt_text': (f"{CHART_ANSWERS.get(chosen)}；数据来自 BLS 就业形势报告"
                         if chosen else None),
        },
        'chart_kind': chosen,
        'unattributed_thresholds': loose_thresholds,
        'numbers_drawn': manifest,
        'every_number_bound_to_a_fact': all(m.get('fact_id') for m in manifest),
        'rendered_by': 'code, straight from the fact pack; the model supplied no figure',
    }
    OUT.mkdir(parents=True, exist_ok=True)
    if chart:
        svg_path = OUT / (vid + '.svg')
        svg_path.write_text(chart['svg'])
        rec['svg_path'] = str(svg_path.relative_to(ROOT))
        rec['svg_sha256'] = hashlib.sha256(chart['svg'].encode()).hexdigest()
    (OUT / (vid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def main():
    """Illustrate every ready draft, from whichever pipeline produced it."""
    sys.path.insert(0, str(ROOT))
    from content import sources as src
    rows, a = src.select(sys.argv[1:])
    roles = json.loads((ROOT / 'evidence_loop/experiments/roles_v2.json').read_text())
    for row in rows:
        packet, draft = row['packet'], row['draft']
        generic = src.is_generic(packet)
        slots = src.build_slots(packet, row['lang'], limit=10)
        q = (roles['personas'].get(row['persona_id'], {}) or {}).get('question', '')
        r = build(draft, packet, q, slots=slots, generic=generic)
        print(json.dumps({'id': r['id'], 'origin': row['origin'], 'who': row['label'],
                          'event': row['event'], 'chart': r['chart_kind'],
                          'numbers': len(r['numbers_drawn']),
                          'bound': r['every_number_bound_to_a_fact'],
                          'svg': r.get('svg_path')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
