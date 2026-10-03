"""Three author perspectives on one source packet.

These are ways of looking, not style donors. Nothing here is learned from
a handle, and nothing here is a checklist the draft must hit. A persona
reads the same admitted facts as the others and either names the point it
would actually write, or says it has nothing to add.

Fact admission, the source packet, and QA stay shared. A persona cannot
add a number, reverse an admitted direction, or promote a reprint into a
second witness.
"""
from __future__ import annotations
from pathlib import Path
import sys, json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

# Three test voices. Not templates, not a final account count, not donors.
VIEWS = (
    {
        'id': 'macro',
        'name': '宏观数据与资金流观察者',
        'background': (
            '看宏观数据和资金流。一件事值不值得写，看它改不改流动性、利率、'
            '美元、风险资产之间已经在跑的那条故事。一家公司的单季利润本身'
            '往往不是你的题目。'
        ),
    },
    {
        'id': 'industry',
        'name': '个股及产业链硬核研究者',
        'background': (
            '看公司和产业链。新闻进来先问谁赚钱、谁承担成本、这条链上什么'
            '被 headline 盖住了。不从一条总量数据直接推出某只股票的结论。'
        ),
    },
    {
        'id': 'trading',
        'name': '交易系统与市场心理教练',
        'background': (
            '看交易系统和市场心理，不喊单。更在意什么才是新信息，大家挤在'
            '哪个共识里，什么反应才算确认，什么证据会让这个判断作废。'
        ),
    },
)


def by_id(persona_id):
    for view in VIEWS:
        return_view = view['id'] == persona_id
        if return_view:
            return view
    raise KeyError(persona_id)


def packet_brief(packet):
    """What a persona is allowed to see: admitted claims, not a hidden brief."""
    rows = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        rows.append({
            'fact_id': fact.get('fact_id'),
            'admission': fact.get('admission'),
            'confidence': fact.get('confidence'),
            'source_id': fact.get('source_id'),
            'text': fact.get('text'),
        })
    return {
        'event_id': packet.get('event_id'),
        'basis': (packet.get('admission') or {}).get('basis') or packet.get('retrieval_basis'),
        'facts': rows,
        'unknown': packet.get('unknown') or [],
        'disagreement': packet.get('disagreement') or [],
        'tiers': packet.get('tiers') or [],
    }


def _prompt(view, packet):
    brief = packet_brief(packet)
    return (
        f"你是「{view['name']}」。这是你看事情的习惯，不是必须写进稿子的清单，"
        "也不是某个真人的口吻：\n"
        f"{view['background']}\n\n"
        "下面是已经确认可以拿来写的素材。不要再做一遍核实。"
        "数字、日期、价格、涨跌、法院结果、公司行动、原话，用这里有的。"
        "判断、含义、第二层推论，用你自己的话说，不需要素材里有原句。\n"
        f"{json.dumps(brief, ensure_ascii=False)}\n\n"
        "没东西可写就 interested=false。有东西可写就给一个角度和一段判断，"
        "用陈述句，不要把判断一律改成“如果……可能……”。\n"
        "fact_ids 从素材的 fact_id 里选，只是标明你主要靠哪几条，不是逐句对照。\n"
        "只返回一个 JSON 对象，键为 interested, fact_ids, angle, interpretation, why_not。"
        "interested 为 false 时，angle 和 interpretation 留空。"
    )


def validate_decision(raw, packet):
    """A persona decision that cites nothing admitted is not a decision to write."""
    allowed = {
        f.get('fact_id')
        for f in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or [])
        if f.get('fact_id') and f.get('admission') in (
            'official', 'two_independent_major', 'single_major_attributed', 'wire_beside_official')
    }
    interested = bool(raw.get('interested'))
    fact_ids = [fid for fid in (raw.get('fact_ids') or []) if fid in allowed]
    angle = (raw.get('angle') or '').strip()
    interpretation = (raw.get('interpretation') or '').strip()
    why_not = (raw.get('why_not') or '').strip()
    if interested and (not fact_ids or not angle):
        interested = False
        why_not = why_not or 'no admitted fact to hang the angle on'
    if not interested:
        fact_ids, angle, interpretation = [], '', ''
    return {
        'interested': interested,
        'fact_ids': fact_ids,
        'angle': angle,
        'interpretation': interpretation,
        'why_not': why_not,
        'persona_id': raw.get('persona_id'),
    }


def consider(packet, view, model_role='modern'):
    """Ask the writer model, as this persona, whether the packet is worth a piece.

    The model is not a donor and not a style target. If it cannot be reached,
    this persona does not write. Silence is not filled in with a template.
    """
    from model_client import call, parse_json
    try:
        record = call(_prompt(view, packet), task=f"persona-angle-{view['id']}",
                      max_tokens=500, temperature=0.3, model_role=model_role)
        parsed = parse_json(record.get('text') or '')
    except Exception as exc:
        return {
            'persona_id': view['id'],
            'name': view['name'],
            'interested': False,
            'fact_ids': [],
            'angle': '',
            'interpretation': '',
            'why_not': 'model unavailable: ' + type(exc).__name__,
            'model_error': str(exc)[:200],
        }
    if not isinstance(parsed, dict):
        parsed = {}
    parsed['persona_id'] = view['id']
    decision = validate_decision(parsed, packet)
    decision['name'] = view['name']
    decision['model_run_id'] = record.get('run_id')
    return decision


def revise(packet, view, decision, findings, model_role='modern'):
    """One rewrite after QA. The persona keeps its question and drops the extra subject.

    If the model cannot say the same thing without the blocked subject, it
    passes. A second failure is not drafted around.
    """
    from model_client import call, parse_json
    prompt = (
        f"上一稿有一处具体事实过不去。视角仍是「{view['name']}」。\n"
        f"过不去的地方：{json.dumps(findings, ensure_ascii=False)}\n"
        "只改这一处：拿掉素材里没有的数字、日期、价格、事件、原话或公司行动，"
        "或者改掉和素材相反的那句。判断留下来，不要整篇重写，"
        "也不要把判断改成“如果……可能……”。\n"
        "改完没剩下可说的，interested=false。\n"
        f"素材：{json.dumps(packet_brief(packet), ensure_ascii=False)}\n"
        "只返回 JSON：interested, fact_ids, angle, interpretation, why_not。"
    )
    try:
        record = call(prompt, task=f"persona-revise-{view['id']}",
                      max_tokens=400, temperature=0.2, model_role=model_role)
        parsed = parse_json(record.get('text') or '')
    except Exception as exc:
        decision = dict(decision)
        decision['interested'] = False
        decision['why_not'] = 'revise failed: ' + type(exc).__name__
        return decision
    if not isinstance(parsed, dict):
        parsed = {}
    parsed['persona_id'] = view['id']
    revised = validate_decision(parsed, packet)
    revised['name'] = view['name']
    revised['model_run_id'] = record.get('run_id')
    revised['revised_after'] = [f.get('code') for f in findings]
    return revised


def consider_all(packet, model_role='modern'):
    return [consider(packet, view, model_role=model_role) for view in VIEWS]
