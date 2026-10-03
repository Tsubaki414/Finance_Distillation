"""Seven-layer QA gates for evidence-backed financial drafts.

Every layer is mechanical. No layer asks a model whether its own output is fine, and no layer
depends on a human being available. The design target is an automated pipeline, so a defect that
only a reader would notice is not acceptable as a gate.

Layer 1  source -> fact pack fidelity
Layer 2  typed numeric semantics (scale, unit, period, level vs change)
Layer 3  atomic claim entailment and controlled relation terms
Layer 4  citation reference integrity, entailment and span precision
Layer 5  fact selection policy (must_include / plan_required / available)
Layer 6  clause attachment (subject, sector vs overall, period)
Layer 7  run_status / qa_status / content_status

A gate returns findings. Any finding with severity `blocking` forces content_status=blocked.
"""
from __future__ import annotations
import re, json, unicodedata
from pathlib import Path
from qa import comparison

ROOT = Path(__file__).resolve().parents[1]

BLOCKING = 'blocking'
WARNING = 'warning'

# ---------------------------------------------------------------- number parsing

CN_SCALE = {'万': 10_000, '萬': 10_000, '亿': 100_000_000, '億': 100_000_000, '千': 1_000, '百': 100}
EN_SCALE = {'thousand': 1_000, 'k': 1_000, 'million': 1_000_000, 'm': 1_000_000,
            'mn': 1_000_000, 'billion': 1_000_000_000, 'bn': 1_000_000_000,
            'b': 1_000_000_000, 'trillion': 1_000_000_000_000, 'tn': 1_000_000_000_000,
            't': 1_000_000_000_000}

NUM = re.compile(
    r'(?P<sign>[+-]?)(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'\s*(?P<scale>万|萬|亿|億|千|百|thousand|million|billion|trillion|tn|bn|mn|k|m|b|t)?'
    r'(?![A-Za-z])'
    r'\s*(?P<unit>%|％|个百分点|百分点|percentage points?|percent|pp|美元|美分|元|小时|hours?|人|persons?)?',
    re.I)

# "12 个月" is a duration, not a figure. Matching it against a fact whose value happens to be
# 12,000 produced seven identical false 1000x reports in the first full smoke run.
DURATION_AFTER = re.compile(r'^\s*(?:个月|个季度|个交易日|周|天|年|季度|次|位|名|家|月份?|'
                            r'months?|quarters?|weeks?|days?|years?)')

PERIOD_HINT = re.compile(r'(20\d{2})\s*年?\s*(\d{1,2})\s*月|(\d{1,2})\s*月|(20\d{2})[-/](\d{1,2})')


def parse_numbers(text: str):
    """Extract every number with its Chinese or English scale word and trailing unit."""
    out = []
    for m in NUM.finditer(text or ''):
        raw = m.group('num').replace(',', '')
        try:
            val = float(raw)
        except ValueError:
            continue
        if m.group('sign') == '-':
            val = -val
        scale_word = (m.group('scale') or '').lower()
        mult = CN_SCALE.get(m.group('scale') or '', EN_SCALE.get(scale_word, 1))
        unit = (m.group('unit') or '').strip()
        tail = (text or '')[m.end():m.end() + 6]
        is_duration = bool(DURATION_AFTER.match(tail)) and not m.group('scale')
        out.append({
            'is_duration': is_duration,
            'text': m.group(0).strip(), 'value': val * mult, 'base': val,
            'scale': m.group('scale'), 'unit': unit,
            'is_percent': unit in ('%', '％', 'percent'),
            'is_pp': unit in ('个百分点', '百分点', 'pp') or 'percentage point' in unit.lower(),
            'start': m.start(), 'end': m.end(),
        })
    return out


UNIT_TO_BASE = {
    # written unit -> multiplier that converts the written number into the fact's base unit
    ('美分', 'USD'): 0.01, ('cents', 'USD'): 0.01, ('cent', 'USD'): 0.01,
    ('美元', 'USD'): 1.0, ('元', 'USD'): 1.0,
    ('小时', 'hours'): 1.0, ('hours', 'hours'): 1.0, ('hour', 'hours'): 1.0,
    ('人', 'persons'): 1.0, ('persons', 'persons'): 1.0,
    ('人', 'persons_decline'): 1.0,
}


def converted(n, fact):
    """Return the written number expressed in the fact's unit, or None when not convertible.

    A draft saying 10 美分 against a fact of 0.1 USD is correct. Without this the magnitude
    check reports a 100x error on a sentence that is right.
    """
    fu = (fact.get('unit') or '').strip()
    wu = (n.get('unit') or '').strip().lower()
    if not wu:
        return None
    mult = UNIT_TO_BASE.get((wu, fu))
    if mult is None:
        for (a, b), m in UNIT_TO_BASE.items():
            if a.lower() == wu and b == fu:
                mult = m
                break
    return None if mult is None else n['value'] * mult


def close(a, b, rel=0.02):
    if a is None or b is None:
        return False
    if a == 0 or b == 0:
        return abs(a - b) < 1e-9
    return abs(a - b) / max(abs(a), abs(b)) <= rel


# ---------------------------------------------------------------- layer 1

def layer1_source_fidelity(packet: dict, source_text: str):
    """The fact pack must itself be faithful to the source before a draft can be judged against it."""
    f = []
    facts = packet.get('facts', [])
    blocks = {b['id'] for b in packet.get('blocks', [])}
    located = 0
    for fact in facts:
        span = fact.get('source_span') or {}
        quote = span.get('quote')
        s, e = span.get('start'), span.get('end')
        if quote is None or s is None:
            f.append({'layer': 1, 'code': 'fact_without_span', 'severity': BLOCKING,
                      'fact_id': fact.get('id'), 'detail': 'fact carries no source span'})
            continue
        if source_text[s:e] != quote:
            f.append({'layer': 1, 'code': 'span_does_not_match_source', 'severity': BLOCKING,
                      'fact_id': fact.get('id'),
                      'detail': f'source[{s}:{e}] does not equal the recorded quote'})
            continue
        located += 1
        missing = set(fact.get('source_block_ids') or []) - blocks
        if missing:
            f.append({'layer': 1, 'code': 'unknown_source_block', 'severity': BLOCKING,
                      'fact_id': fact.get('id'), 'detail': sorted(missing)})
        for k in ('value', 'unit', 'period'):
            if fact.get(k) in (None, ''):
                f.append({'layer': 1, 'code': 'incomplete_typed_fact', 'severity': BLOCKING,
                          'fact_id': fact.get('id'), 'detail': f'missing {k}'})
    metrics = {
        'facts': len(facts),
        'source_fact_accuracy': round(located / max(len(facts), 1), 4),
        'source_methodology_coverage': 1.0 if packet.get('methodology') else 0.0,
        'source_to_fact_lineage': round(
            sum(1 for x in facts if x.get('source_block_ids')) / max(len(facts), 1), 4),
    }
    return f, metrics


# ---------------------------------------------------------------- layer 2

def layer2_numeric(sentence: str, cited_facts: list):
    """Scale, unit, period and level-vs-change errors are zero tolerance."""
    f = []
    nums = parse_numbers(sentence)
    if not cited_facts or not nums:
        return f
    for n in nums:
        if n['is_pp'] or n['is_percent'] or n.get('is_duration'):
            continue
        matched = any(close(n['value'], fx.get('value'))
                      or close(converted(n, fx), fx.get('value'))
                      for fx in cited_facts)
        if matched:
            continue
        # a magnitude slip is the specific failure we must never miss
        for fx in cited_facts:
            v = fx.get('value')
            if v in (None, 0):
                continue
            if converted(n, fx) is not None and close(converted(n, fx), v):
                continue
            for factor, name in ((10, '10x'), (100, '100x'), (1000, '1000x'),
                                 (0.1, 'one tenth'), (0.01, 'one hundredth'), (0.001, 'one thousandth')):
                if close(n['value'] * (1 / factor if factor < 1 else factor), v) or \
                   close(n['value'], v * factor):
                    f.append({'layer': 2, 'code': 'numeric_magnitude', 'severity': BLOCKING,
                              'detail': f"draft wrote {n['text']} (={n['value']:,.0f}) against "
                                        f"{fx.get('id')}={v:,.0f}, off by {name}",
                              'fact_id': fx.get('id'), 'written': n['text'], 'expected': v})
                    break
            else:
                continue
            break
    return f


def layer2_percent_vs_pp(sentence: str, cited_facts: list):
    f = []
    nums = parse_numbers(sentence)
    for n in nums:
        if not (n['is_percent'] or n['is_pp']):
            continue
        for fx in cited_facts:
            if not close(n['base'], fx.get('value')):
                continue
            unit = (fx.get('unit') or '').lower()
            fact_is_pp = 'percentage' in unit and 'point' in unit
            if n['is_pp'] and unit == 'percent':
                f.append({'layer': 2, 'code': 'percent_vs_percentage_point', 'severity': BLOCKING,
                          'fact_id': fx.get('id'),
                          'detail': f"{fx.get('id')} is a percent level, the draft wrote it as percentage points"})
            if n['is_percent'] and fact_is_pp:
                f.append({'layer': 2, 'code': 'percent_vs_percentage_point', 'severity': BLOCKING,
                          'fact_id': fx.get('id'),
                          'detail': f"{fx.get('id')} is a percentage-point change, the draft wrote a percent level"})
    return f


# A month can appear legitimately as a comparison baseline, inside a hypothetical, or because a
# revision refers to earlier months. Only an unqualified month is evidence of a period error.
BASELINE_CUE = re.compile(r'(?:较|相比|对比|自|比|since|compared\s+to|versus|vs\.?)\s*$')
REVISION_FACT = re.compile(r'revision|修订|上修|下修')


def _month_is_qualified(sentence, pos):
    """True when the month at this position is a baseline or sits in a hypothetical clause."""
    before = sentence[max(0, pos - 12):pos]
    if BASELINE_CUE.search(before):
        return True
    clause_start = max([sentence.rfind(c, 0, pos) for c in '，,。；;'] + [-1]) + 1
    return bool(CONDITIONAL.search(sentence[clause_start:pos + 6]))


def layer2_period(sentence: str, cited_facts: list):
    """A right number attached to the wrong month is still wrong."""
    f = []
    # Revisions legitimately name the months being revised.
    if any(REVISION_FACT.search(str(fx.get('id', '')) + str(fx.get('label', '')))
           for fx in cited_facts):
        return f
    hits = PERIOD_HINT.findall(sentence or '')
    months = set()
    for m in PERIOD_HINT.finditer(sentence or ''):
        if _month_is_qualified(sentence, m.start()):
            continue
        for g in m.groups()[1:]:
            if g:
                months.add(int(g))
                break
    if not months:
        return f
    for fx in cited_facts:
        p = str(fx.get('period') or '')
        mm = re.search(r'\d{4}-(\d{2})', p)
        if not mm:
            continue
        fact_month = int(mm.group(1))
        if months and fact_month not in months:
            f.append({'layer': 2, 'code': 'period_mismatch', 'severity': BLOCKING,
                      'fact_id': fx.get('id'),
                      'detail': f"sentence names month(s) {sorted(months)} but {fx.get('id')} covers {p}"})
    return f


# ---------------------------------------------------------------- layer 3

CONDITIONAL = re.compile(r'若|如果|假如|倘若|一旦|除非|\bif\b|should\s', re.I)
# A disclaimer names a relation in order to deny it. "并非因果机制的证明" asserts nothing.
NEGATED_RELATION = re.compile(r'(?:并非|不是|不能|不等于|无法|不构成|不足以|难以|不代表|不应)'
                              r'[^，。；]{0,18}$')

# Relations that assert a comparison the fact pack may not contain.
CONTROLLED = [
    # Any comparison against a consensus needs a consensus source, whichever verb carries it.
    # The first version listed 高于/低于/好于/差于/超出/不及, and a draft wrote "与市场预期出现
    # 显著背离" — the same unsourced claim in a verb the list did not have. Naming a market-wide
    # expectation is itself the claim, so the noun forms are caught directly. 预期收益 and its
    # kin are a different word and are excluded.
    ('consensus_comparison',
     r'(?:市场|一致|分析师|机构|华尔街|券商|普遍)预期(?!收益|回报|报酬|值|管理)'
     r'|(?:高于|低于|好于|差于|超出|不及|背离|偏离|吻合|相符)[^，。；\n]{0,6}(?:预期|预估|共识|一致预期)'
     r'|(?:预期|共识)[^，。；\n]{0,8}(?:背离|偏离|落差|差距|差异|吻合|相符|一致)'
     r'|超预期|不及预期|逊于预期|预期差'
     r'|beat(?:s|ing)?\s+(?:consensus|estimates?|expectations?)'
     r'|miss(?:es|ing)?\s+(?:consensus|estimates?|expectations?)'
     r'|(?:above|below|versus|vs\.?)\s+(?:consensus|expectations?|estimates?)'
     r'|diverge[sd]?\s+from\s+(?:consensus|expectations?)'),
    # "a record quarter" is a record claim; matching only "record high" let it through.
    ('record', r'创纪录|史上最高|历史新高|历史最高|record\s+(?:high|quarter|year|month|'
               r'revenue|results?|profit|sales|performance)|all-time high|highest ever'),
    ('acceleration', r'加速|减速|accelerat|decelerat'),
    ('causal', r'导致|因为.*所以|造成|caused by|because of'),
    ('proof', r'证明|表明.*必然|proves?\b'),
    ('priced_in', r'已经定价|market has priced|priced in'),
]
_CONTROLLED = [(k, re.compile(p, re.I)) for k, p in CONTROLLED]

# The issuer announcing its own record, and a sentence that says so rather than adopting it.
SOURCE_RECORD = re.compile(r'record[- ]breaking|record high|record quarter|all-time high|'
                           r'highest ever|创纪录|历史新高', re.I)
ATTRIBUTED_CLAIM = re.compile(r'公司(?:称|表示|宣布|披露)|财报(?:称|显示)|官方(?:称|表示)|'
                              r'原文(?:称|写道)|据(?:公司|财报|新闻稿)|新闻稿(?:称|显示)|'
                              r'the (?:company|release|report) (?:says?|calls?|describes?|'
                              r'announces?|reports?)|according to the (?:company|release|report)',
                              re.I)


def layer3_entailment(sentence: str, cited_facts: list, packet: dict, extra_sources=None):
    """Controlled relation terms need a source that actually supports the relation."""
    f = []
    methodology = ' '.join(packet.get('methodology') or [])
    has_consensus = bool(extra_sources and extra_sources.get('consensus'))
    declared_absent = re.search(r'does not contain consensus forecasts|不包含.*预期', methodology, re.I)
    for kind, rx in _CONTROLLED:
        m = rx.search(sentence or '')
        if not m:
            continue
        # A hypothesis governs the clauses that follow it, so scope runs from the sentence
        # boundary, not from the nearest comma.
        sent_start = max([(sentence or '').rfind(c, 0, m.start()) for c in '。！？!?'] + [-1]) + 1
        if CONDITIONAL.search((sentence or '')[sent_start:m.end()]):
            continue
        if NEGATED_RELATION.search((sentence or '')[sent_start:m.start()]):
            continue
        if kind == 'consensus_comparison':
            if not has_consensus:
                f.append({'layer': 3, 'code': 'out_of_evidence_assertion', 'severity': BLOCKING,
                          'term': m.group(0), 'relation': kind,
                          'detail': ('the evidence set contains no verified consensus source'
                                     + ('; the packet methodology states it does not contain consensus forecasts'
                                        if declared_absent else ''))})
            continue
        if kind == 'record':
            # No typed number tells you it is a record, so the claim stays blocked by default.
            # But when the source document itself announces one, relaying that with attribution
            # is reporting, not an unsupported assertion — the same allowance made for a
            # source's own methodology caveat. Unattributed, it is still the writer's claim.
            if SOURCE_RECORD.search(packet.get('full_narrative') or ''):
                if ATTRIBUTED_CLAIM.search(sentence or ''):
                    f.append({'layer': 3, 'code': 'record_relayed_from_source',
                              'severity': WARNING, 'term': m.group(0), 'relation': kind,
                              'detail': 'the source announces a record and the sentence '
                                        'attributes it'})
                    continue
                f.append({'layer': 3, 'code': 'unattributed_source_record', 'severity': BLOCKING,
                          'term': m.group(0), 'relation': kind,
                          'detail': ('the source announces a record; say whose claim it is '
                                     'rather than asserting it directly')})
                continue
        if kind in ('record', 'priced_in', 'proof'):
            f.append({'layer': 3, 'code': 'unsupported_relation', 'severity': BLOCKING,
                      'term': m.group(0), 'relation': kind,
                      'detail': f'"{m.group(0)}" asserts a relation no typed fact establishes'})
            continue
        if kind == 'acceleration' and not any(
                'change' in str(fx.get('id', '')) or 'mean' in str(fx.get('id', '')) or
                '_mom' in str(fx.get('id', '')) or '_yoy' in str(fx.get('id', ''))
                for fx in cited_facts):
            f.append({'layer': 3, 'code': 'unsupported_relation', 'severity': WARNING,
                      'term': m.group(0), 'relation': kind,
                      'detail': 'acceleration claimed without citing a change or mean fact'})
    return f


# ---------------------------------------------------------------- layer 4

LEVEL_WORDS = re.compile(r'达到|为|是|水平|录得|stands? at|level')
CHANGE_WORDS = re.compile(r'增|减|升|降|上修|下修|变化|微增|微降|回落|反弹|rose|fell|increase|decrease|revis|change')
# A fact is itself a change measure when its id or its label says so. payroll is
# "非农就业月增量", a monthly increment, so citing it for a change is correct.
CHANGE_FACT_ID = re.compile(r'change|_mom|_yoy|revision|decline|_12m_mean|_since_')
CHANGE_FACT_LABEL = re.compile(r'增量|变化|月增|环比|同比|减少|增加|上修|下修|修订|change|revision')


def _clause_subject_facts(clause, known):
    """Facts whose label shares a substantive term with this clause.

    Lets the gate tell "周工时微增" (workweek) apart from "时薪环比" (ahe_mom) inside one sentence.
    """
    hits = []
    for fx in known:
        label = str(fx.get('label') or '')
        terms = [t for t in re.findall(r'[\u4e00-\u9fff]{2,}', label) if len(t) >= 2]
        for t in terms:
            for i in range(len(t) - 1):
                if t[i:i + 2] in clause:
                    hits.append(fx)
                    break
            else:
                continue
            break
    return hits


def _is_change_fact(fx):
    return bool(CHANGE_FACT_ID.search(str(fx.get('id') or ''))
                or CHANGE_FACT_LABEL.search(str(fx.get('label') or '')))


def layer4_citation(sentence: str, cited_ids: list, allowed: dict):
    """ID validity is necessary but far from sufficient. Match the relation too."""
    f = []
    unknown = [i for i in cited_ids if i not in allowed]
    if unknown:
        f.append({'layer': 4, 'code': 'unknown_fact_id', 'severity': BLOCKING,
                  'detail': sorted(unknown)})
    known = [allowed[i] for i in cited_ids if i in allowed]
    if not known:
        return f
    # Check per clause. A sentence can carry several claims, and one correct change citation
    # must not excuse a second clause that cites a level for a change.
    pos = 0
    for clause in re.split(r'[，,；;。]', sentence or ''):
        start = (sentence or '').find(clause, pos)
        pos = start + len(clause) if start >= 0 else pos
        clause = clause.strip()
        if not clause or not CHANGE_WORDS.search(clause):
            continue
        # A conditional governs the clauses after it, so scope runs from the sentence boundary.
        sent_start = max([(sentence or '').rfind(c, 0, max(start, 0)) for c in '。！？!?'] + [-1]) + 1
        if CONDITIONAL.search((sentence or '')[sent_start:max(start, 0) + len(clause)]):
            continue
        subject = _clause_subject_facts(clause, known)
        if not subject:
            # No cited fact is the subject of this clause, so the change word belongs to
            # something else in the sentence. "工资增长受到制约" says nothing about participation.
            continue
        pool = subject
        change_like = [fx for fx in pool if _is_change_fact(fx)]
        if change_like:
            continue
        level_like = [fx for fx in pool if not _is_change_fact(fx)]
        if not level_like:
            continue
        sibling = None
        for fx in level_like:
            for cand in (str(fx.get('id')) + '_change', str(fx.get('id')) + '_mom'):
                if cand in allowed:
                    sibling = cand
        f.append({'layer': 4, 'code': 'citation_relation_mismatch', 'severity': BLOCKING,
                  'clause': clause[:40],
                  'detail': ('clause asserts a change but cites only level facts '
                             + ', '.join(str(x.get('id')) for x in level_like)
                             + (f'; {sibling} exists and states the change' if sibling else '')),
                  'cited': [x.get('id') for x in level_like], 'should_cite': sibling})
    return f


def layer4_support_coverage(ledger: list):
    """A factual sentence must point at something. What counts as something has two forms.

    Most factual sentences cite a fact in the packet, traceable to a character span in the source
    document. A cross-language piece also states figures counted from our own collection — how
    many authors on each side posted, how many hours one side led by — which have no span in any
    filing because they are not in one. They are still evidence, and still traceable: to
    live/store/crosslang/ and the post ids behind it.

    So `collection_slot_ids` supports a factual sentence in the same way a fact id does. It is
    recorded separately rather than merged, because the two have different standing and a reader
    checking the piece needs to know which kind they are looking at.
    """
    cited = sum(1 for s in ledger if s.get('fact_ids') or s.get('collection_slot_ids'))
    factual = [s for s in ledger if s.get('kind') == 'fact']
    uncited_factual = [s['sentence_id'] for s in factual
                       if not s.get('fact_ids') and not s.get('collection_slot_ids')]
    f = []
    if uncited_factual:
        f.append({'layer': 4, 'code': 'unsupported_claim', 'severity': BLOCKING,
                  'detail': f'factual sentences without any citation: {uncited_factual}'})
    return f, {
        'claim_support_coverage': round(cited / max(len(ledger), 1), 4),
        'unsupported_claim_rate': round(len(uncited_factual) / max(len(factual), 1), 4),
        'collection_supported_sentences': sum(
            1 for s in ledger if s.get('collection_slot_ids') and not s.get('fact_ids')),
    }


# ---------------------------------------------------------------- layer 5

def layer5_fact_selection(ledger: list, must_include: list, plan_required: list, available: dict):
    f = []
    used = {i for s in ledger for i in s.get('fact_ids', [])}
    missing_must = sorted(set(must_include) - used)
    missing_plan = sorted(set(plan_required) - used)
    if missing_must:
        f.append({'layer': 5, 'code': 'must_include_missing', 'severity': BLOCKING,
                  'detail': missing_must})
    if missing_plan:
        f.append({'layer': 5, 'code': 'plan_required_missing', 'severity': BLOCKING,
                  'detail': missing_plan})
    outside = sorted(used - set(available))
    if outside:
        f.append({'layer': 5, 'code': 'fact_outside_evidence_set', 'severity': BLOCKING,
                  'detail': outside})
    return f, {
        'must_include_coverage': round(1 - len(missing_must) / max(len(must_include), 1), 4),
        'plan_required_coverage': round(1 - len(missing_plan) / max(len(plan_required), 1), 4),
        'all_fact_coverage': round(len(used & set(available)) / max(len(available), 1), 4),
    }


# ---------------------------------------------------------------- layer 6

SECTOR_RE = re.compile(r'(信息业|制造业|医疗保健|医疗|餐饮|建筑业|零售|教育|采矿|运输|金融业|批发)')
OVERALL_RE = re.compile(r'(非农|整体|总体|全部行业|总就业|payroll|nonfarm|overall)')


def layer6_clause_attachment(sentence: str, cited_ids: list, allowed: dict):
    """A number belongs to the nearest subject. Overall means attached to a sector reads as sector data."""
    f = []
    sectors = [(m.start(), m.group(1)) for m in SECTOR_RE.finditer(sentence or '')]
    if not sectors:
        return f
    nums = parse_numbers(sentence)
    for fid in cited_ids:
        fx = allowed.get(fid)
        if not fx:
            continue
        is_overall = bool(OVERALL_RE.search(str(fx.get('label', '')) + ' ' + str(fid))) and \
            not SECTOR_RE.search(str(fx.get('label', '')))
        if not is_overall:
            continue
        # find where this fact's value appears in the sentence
        for n in nums:
            if not close(n['value'], fx.get('value')):
                continue
            preceding = [s for s in sectors if s[0] < n['start']]
            if not preceding:
                continue
            nearest = preceding[-1]
            gap = n['start'] - nearest[0]
            if gap <= 30:
                f.append({'layer': 6, 'code': 'clause_attribution', 'severity': BLOCKING,
                          'fact_id': fid,
                          'detail': (f"{fid} is an overall measure but the number {n['text']} sits "
                                     f"{gap} characters after “{nearest[1]}”, so it reads as "
                                     f"that sector's figure")})
    return f


# ---------------------------------------------------------------- layer 6b

FLOW = re.compile(r'从(?P<src>[^，。；]{2,12}?)(?:部门|业|行业)?\s*(?:向|流向|转向|转移到|转入)'
                  r'\s*(?P<dst>[^，。；]{2,12}?)(?:部门|业|行业)?\s*(?:转移|流动|迁移|转入|流入)')
SECTOR_ALIAS = {
    'information': ['信息业', '科技', '信息技术', 'IT'],
    'food': ['餐饮', '酒吧', '服务业', '传统服务'],
    'health': ['医疗', '医疗保健', '卫生'],
    'local_education': ['教育', '地方政府教育', '公共部门'],
    'manufacturing': ['制造业', '制造'],
    'construction': ['建筑', '建筑业'],
}


def _sector_fact_for(phrase, cited):
    for fid, names in SECTOR_ALIAS.items():
        if any(nm in phrase for nm in names):
            for fx in cited:
                if fx.get('id') == fid:
                    return fx
    return None


def layer6_flow_direction(sentence: str, cited_facts: list):
    """"Labour is moving from A to B" requires B to have grown and A to have shrunk.

    A draft passed both the evidence and form gates while stating the direction backwards, so the
    signs are checked directly against the cited sector facts.
    """
    f = []
    m = FLOW.search(sentence or '')
    if not m:
        return f
    src = _sector_fact_for(m.group('src'), cited_facts)
    dst = _sector_fact_for(m.group('dst'), cited_facts)
    if not src or not dst:
        return f
    sv, dv = src.get('value'), dst.get('value')
    if sv is None or dv is None:
        return f
    if not (sv < 0 < dv):
        f.append({'layer': 6, 'code': 'flow_direction_reversed', 'severity': BLOCKING,
                  'detail': (f"sentence says labour moves from {m.group('src')} to {m.group('dst')}, "
                             f"but {src['id']}={sv:,.0f} and {dst['id']}={dv:,.0f}; "
                             f"the source sector must fall and the destination must rise"),
                  'from_fact': src['id'], 'to_fact': dst['id']})
    return f


# ---------------------------------------------------------------- layer 6c

RISE_WORD = re.compile(r'增加|增长|增量|上升|上涨|扩张|走强|回升|引擎|拉动|贡献|支撑|吸纳|新增')
FALL_WORD = re.compile(r'减少|下降|下滑|收缩|走弱|回落|流失|萎缩|裁员|拖累|拖后腿')
# A fact whose sign the reader cannot recover from the number alone. The renderer prints the
# magnitude and puts the direction in the frame, so a draft that supplies its own wording can
# silently reverse the sign.
SIGNED_UNIT = re.compile(r'_decline$')
# Terms that nearly every label in a jobs report shares. Matching on them made "制造业就业增长"
# read as a claim about 信息业就业月变化, so the subject has to be identified by what
# distinguishes a fact, not by what every fact has in common.
GENERIC_TERM = {'就业', '人数', '数据', '水平', '变化', '增量', '月增', '环比', '同比', '平均',
                '市场', '经济', '合计', '总量', '幅度', '月变', '业就', '业月', '数减'}


def _fact_positions(clause, facts):
    """Where each cited fact's own magnitude sits in the clause.

    The renderer prints magnitudes, so -23,000 reaches the page as "2.3 万人" and the sign has to
    be recovered from position, not from the digits.
    """
    out = []
    for n in parse_numbers(clause):
        if n.get('is_duration'):
            continue
        for fx in facts:
            v = fx.get('value')
            if v is None or not isinstance(v, (int, float)):
                continue
            conv = converted(n, fx)
            if any(close(abs(x), abs(v)) for x in (n['value'], conv) if x is not None):
                out.append({'fact': fx, 'start': n['start'], 'end': n['end']})
                break
    return sorted(out, key=lambda x: x['start'])


FRAME_LEAD = 12


def _owner_of(pos, positions):
    """Which fact a direction word at `pos` is talking about.

    The renderer writes the direction ahead of the number — "参与率较一月下降 0.5 个百分点" — so a
    word immediately preceding a figure belongs to that figure. Otherwise it attaches to the
    nearest figure before it. Without this, "上修 5.5 万人及参与率较一月下降 0.5 个百分点" charged
    the revision with the participation rate's fall.
    """
    after = [p for p in positions if 0 <= p['start'] - pos <= FRAME_LEAD]
    if after:
        return after[0]['fact']
    before = [p for p in positions if p['end'] <= pos]
    return before[-1]['fact'] if before else None


def layer6_sign_direction(sentence: str, cited_facts: list):
    """The direction word attached to a figure has to match that figure's sign.

    The renderer prints 23,000 for a fact worth -23,000 and carries "减少" in the frame. When a
    draft writes its own label instead — "信息业就业月变化 2.3 万人" — the magnitude is right, the
    sign is gone, and the sentence went on to call a shrinking sector an engine of growth. Nothing
    in the numeric layers catches that, because the number itself is correct.

    Scope, stated so it is not overclaimed: a direction word is judged against the figure it is
    attached to. It does not resolve a compound subject ("A and B together drove growth" where A
    fell), because attributing a verb across a conjunction is not something this can do reliably,
    and a gate that guesses is worse than a gate with a stated boundary.
    """
    f = []
    for clause in re.split(r'[，,；;。]', sentence or ''):
        if not clause.strip():
            continue
        positions = _fact_positions(clause, cited_facts)
        if not positions:
            continue
        charged = set()
        for pattern, rising in ((RISE_WORD, True), (FALL_WORD, False)):
            for m in pattern.finditer(clause):
                fx = _owner_of(m.start(), positions)
                if fx is None:
                    continue
                v = fx.get('value')
                declining = v < 0 or bool(SIGNED_UNIT.search(str(fx.get('unit') or '')))
                # A level has no direction. 劳动参与率 61.6% is not "growth", so a clause about
                # the market shrinking is not contradicted by that figure being positive.
                if not declining and not _is_change_fact(fx):
                    continue
                if declining == rising and fx.get('id') not in charged:
                    # one finding per fact per clause; 增长 and 引擎 are the same defect
                    charged.add(fx.get('id'))
                    f.append({'layer': 6, 'code': 'sign_direction_mismatch', 'severity': BLOCKING,
                              'fact_id': fx.get('id'),
                              'detail': (f"“{m.group(0)}” in “{clause.strip()[:40]}” is attached to "
                                         f"{fx.get('id')}, which moves the other way "
                                         f"({fx.get('label')}, value={v})")})
        f += _compound_direction(clause, positions)
    return f


def _compound_direction(clause, positions):
    """One direction word covering two figures that move in opposite directions.

    "信息业就业减少 2.3 万人与医疗保健就业增加 1.3 万人共同构成了就业增长的主要引擎" attaches a
    single verb to a sector that fell and one that rose. Positional attribution alone reads the
    verb as belonging to the nearer figure and lets it through, but the sentence is wrong whichever
    figure the writer meant, so the construction itself is the defect.
    """
    signed = []
    for p in positions:
        fx = p['fact']
        v = fx.get('value')
        declining = v < 0 or bool(SIGNED_UNIT.search(str(fx.get('unit') or '')))
        if not declining and not _is_change_fact(fx):
            continue    # a level carries no direction
        signed.append((p, declining))
    if len({d for _, d in signed}) < 2:
        return []
    last = max(p['end'] for p, _ in signed)
    for pattern in (RISE_WORD, FALL_WORD):
        m = pattern.search(clause, last)
        if m:
            return [{'layer': 6, 'code': 'compound_direction_over_opposite_facts',
                     'severity': BLOCKING,
                     'fact_id': sorted(p['fact'].get('id') for p, _ in signed),
                     'detail': (f"“{m.group(0)}” follows both "
                                f"{' and '.join(sorted(p['fact'].get('id') for p, _ in signed))}, "
                                f"which move in opposite directions, so one of them is described "
                                f"backwards: “{clause.strip()[:52]}”")}]
    return []


# ---------------------------------------------------------------- layer 7

def layer7_status(findings: list, run_ok: bool = True):
    blocking = [x for x in findings if x.get('severity') == BLOCKING]
    return {
        'run_status': 'completed' if run_ok else 'failed',
        'qa_status': 'failed' if blocking else 'passed',
        'content_status': 'blocked' if blocking else 'ready_for_pipeline',
        'blocking_count': len(blocking),
        'warning_count': len([x for x in findings if x.get('severity') == WARNING]),
        'human_review': 'not_required_by_design; the target pipeline is automated',
    }


# ---------------------------------------------------------------- orchestrator

def evaluate(case: dict, packet: dict, source_text: str = None,
             must_include=None, plan_required=None, extra_sources=None):
    """Run all seven layers over one case. Returns findings, metrics and status."""
    allowed = {f['id']: f for f in packet.get('facts', [])}
    ledger = case.get('sentence_to_source_ledger') or []
    findings, metrics = [], {}

    if source_text is not None:
        f1, m1 = layer1_source_fidelity(packet, source_text)
        findings += f1
        metrics.update(m1)

    for s in ledger:
        text = s.get('text') or ''
        ids = s.get('fact_ids') or []
        cited = [allowed[i] for i in ids if i in allowed]
        for fn in (layer2_numeric, layer2_percent_vs_pp, layer2_period):
            for x in fn(text, cited):
                findings.append({**x, 'sentence_id': s.get('sentence_id')})
        for x in layer3_entailment(text, cited, packet, extra_sources):
            findings.append({**x, 'sentence_id': s.get('sentence_id')})
        for x in layer4_citation(text, ids, allowed):
            findings.append({**x, 'sentence_id': s.get('sentence_id')})
        for x in layer6_clause_attachment(text, ids, allowed):
            findings.append({**x, 'sentence_id': s.get('sentence_id')})
        for x in layer6_flow_direction(text, cited):
            findings.append({**x, 'sentence_id': s.get('sentence_id')})
        for x in layer6_sign_direction(text, cited):
            findings.append({**x, 'sentence_id': s.get('sentence_id')})
        # The relation asserted *between* two figures, which every other layer passes over: each
        # one checks a figure against its source, and a backwards comparison gets all of them right.
        for x in comparison.check_sentence(text, cited, _fact_positions(text, cited),
                                           kind=s.get('kind')):
            findings.append({**x, 'sentence_id': s.get('sentence_id')})

    f4b, m4 = layer4_support_coverage(ledger)
    findings += f4b
    metrics.update(m4)

    mi = must_include if must_include is not None else (
        packet.get('coverage', {}).get('required_core_ids') or [])
    pr = plan_required if plan_required is not None else []
    f5, m5 = layer5_fact_selection(ledger, mi, pr, allowed)
    findings += f5
    metrics.update(m5)

    status = layer7_status(findings)
    return {'findings': findings, 'metrics': metrics, 'status': status,
            'gate_version': 'qa-gates-v3',
            'layers_run': [1, 2, 3, 4, 5, 6, 7] if source_text is not None else [2, 3, 4, 5, 6, 7]}
