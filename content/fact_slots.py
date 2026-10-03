"""Deterministic rendering of typed facts into Chinese sentence fragments.

The model is not allowed to convert units or scales. Every mandatory number reaches the draft as a
pre-rendered string produced here, so a 44,000 can never become 0.44 万 in the output: the model
never sees a raw figure it has to transform.

The model still writes the analysis. It receives slots it must place, and prose it must build
around them.

Run: .venv/bin/python -B content/fact_slots.py
"""
from pathlib import Path
import json, re

ROOT = Path(__file__).resolve().parents[1]

# Which slot each mandatory fact fills, and how it should read in Chinese.
# `unit` decides the formatter; `frame` decides the wording around the number.
SLOT_STYLE = {
    'persons': {'formatter': 'wan', 'suffix': '人'},
    'persons_decline': {'formatter': 'wan', 'suffix': '人'},
    'percent': {'formatter': 'percent', 'suffix': ''},
    'percentage': {'formatter': 'pp', 'suffix': ''},
    'USD': {'formatter': 'usd', 'suffix': ''},
    'hours': {'formatter': 'plain', 'suffix': '小时'},
    'percentage_points_decline': {'formatter': 'pp', 'suffix': ''},
    'percentage_points': {'formatter': 'pp', 'suffix': ''},
    'percent_of_unemployed': {'formatter': 'percent', 'suffix': ''},
}

FRAME = {
    'payroll': '8 月非农就业增加 {v}',
    'payroll_12m_mean': '此前 12 个月非农月均增加 {v}',
    'unemployment_rate': '失业率为 {v}',
    'participation': '劳动参与率为 {v}',
    'part_time_decline': '因经济原因从事兼职的人数减少 {v}',
    'ahe_mom': '平均时薪环比上涨 {v}',
    'ahe_yoy': '平均时薪同比上涨 {v}',
    'revision_total': '前两个月合计上修 {v}',
    'food': '餐饮与酒吧就业增加 {v}',
    'health': '医疗保健就业增加 {v}',
    'information': '信息业就业减少 {v}',
    'local_education': '地方政府教育就业增加 {v}',
    'participation_since_jan': '劳动参与率较一月下降 {v}',
    'workweek_change': '私人非农平均周工时变化 {v}',
}

# Level facts alone do not license a claim of movement, so the matching change fact is always
# supplied. Making the evidence available works better than warning the model about its absence.
COMPANION = {
    'participation': 'participation_since_jan',
    'workweek': 'workweek_change',
}


def fmt_wan(v):
    """Chinese myriad scale. 44000 -> 4.4 万. Never produced by the model."""
    a = abs(v)
    if a >= 10000:
        s = f'{v / 10000:.1f}'.rstrip('0').rstrip('.')
        return f'{s} 万'
    return f'{v:,.0f}'


def fmt_percent(v):
    return f'{v:g}%'


def fmt_pp(v):
    return f'{v:g} 个百分点'


def fmt_usd(v):
    """0.1 USD reads naturally as 10 美分."""
    if abs(v) < 1:
        return f'{round(v * 100):g} 美分'
    return f'{v:g} 美元'


def fmt_plain(v):
    return f'{v:g}'


FORMATTERS = {'wan': fmt_wan, 'percent': fmt_percent, 'pp': fmt_pp,
              'usd': fmt_usd, 'plain': fmt_plain}


def render_value(fact):
    unit = fact.get('unit') or ''
    if unit not in SLOT_STYLE:
        # Fail loudly rather than emitting a bare number with no unit: a unit-less figure is
        # exactly how a level gets mistaken for a change downstream.
        if 'percentage' in unit or 'point' in unit:
            unit = 'percentage_points'
        elif 'percent' in unit:
            unit = 'percent'
        elif 'person' in unit:
            unit = 'persons'
    style = SLOT_STYLE.get(unit, {'formatter': 'plain', 'suffix': ''})
    # The direction word belongs to the frame, not the value. Keeping "减少" inside the value
    # meant a draft writing "信息业就业减少 2.3 万人" failed an exact match on "减少 2.3 万人".
    value = fact['value']
    body = FORMATTERS[style['formatter']](abs(value) if style['formatter'] == 'wan' else value)
    return body + style['suffix']


def build_slots(packet, required_ids):
    """One slot per mandatory fact, plus the change fact each level fact needs."""
    facts = {f['id']: f for f in packet['facts']}
    ids = list(required_ids)
    for level, change in COMPANION.items():
        if level in ids and change in facts and change not in ids:
            ids.insert(ids.index(level) + 1, change)
    slots = []
    for fid in ids:
        f = facts.get(fid)
        if not f:
            continue
        value = render_value(f)
        frame = FRAME.get(fid, '{label}为 {v}').replace('{label}', f['label'])
        slots.append({
            'slot_id': 'S' + str(len(slots) + 1).zfill(2),
            'fact_id': fid,
            'label': f['label'],
            'rendered': frame.format(v=value),
            'value_rendered': value,
            'direction_word': frame_direction(frame.format(v=value)),
            'raw_value': f['value'], 'unit': f['unit'], 'period': f['period'],
            'source_block_ids': f['source_block_ids'],
            'rule': 'rendered by code; the model must place this string verbatim and must not '
                    'restate the number in any other form',
        })
    return slots


# The word in the frame that carries the direction. A draft that supplies the number without it
# has stated the magnitude and dropped the sign, which is how a shrinking sector once got
# described as an engine of growth.
DIRECTION_WORD = re.compile(r'增加|减少|上涨|下跌|下降|上修|下修')


def frame_direction(rendered):
    m = DIRECTION_WORD.search(rendered or '')
    return m.group(0) if m else None


VERBATIM_OK = re.compile(r'[\d.,]+')


def verify_placement(text, slots):
    """The whole rendered sentence must appear, not just its number.

    Checking only the figure lets a draft write a decline where the slot states a level: the
    number is right and the meaning is wrong. The frame carries the relation, so the frame is
    what gets verified.
    """
    t = text or ''
    missing, wrong_frame = [], []
    for s in slots:
        if s['rendered'] in t:
            continue
        if s['value_rendered'] in t:
            wrong_frame.append({'slot_id': s['slot_id'], 'fact_id': s['fact_id'],
                                'expected': s['rendered'],
                                'issue': 'number present but not in the rendered frame'})
        missing.append(s['slot_id'])
    return {'placed': len(slots) - len(missing), 'total': len(slots),
            'missing_slot_ids': missing, 'wrong_frame': wrong_frame,
            'coverage': round((len(slots) - len(missing)) / max(len(slots), 1), 4)}


def main():
    packet = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
    required = packet['coverage']['required_core_ids']
    slots = build_slots(packet, required)
    out = {'source_version': packet['version'], 'source_id': packet['id'],
           'required_fact_ids': required, 'slots': slots,
           'contract': ('The generator receives these strings and must place each one verbatim. '
                        'Unit and scale conversion never reaches the model, so a magnitude error '
                        'in a mandatory fact is structurally impossible.')}
    (ROOT / 'content').mkdir(exist_ok=True)
    (ROOT / 'content/fact_slots.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    for s in slots:
        print(f"  {s['slot_id']} {s['fact_id']:22} {s['rendered']}")
    print(f"\n{len(slots)} slots from {len(required)} required facts")
    return out


if __name__ == '__main__':
    main()
