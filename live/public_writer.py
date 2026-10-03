"""Rewrite from two layers, not from a news recap.

FACT PACK answers what happened. Numbers, dates, quotes and events stay
inside it.

REWRITE MATERIAL answers how people already read it. The writer selects,
drops repetition, and reorganizes those arguments. It does not invent the
thinking. A persona only decides which arguments to pick.

If rewrite material is empty, this is a short factual note, not an analysis.
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

import writer_backend as backend

# Test group, not three fixed templates and not a final account count.
PERSONA = {
    'macro': (
        '你是宏观数据与资金流观察者。'
        '你关心这件事改不改流动性、利率、美元和风险资产之间已经在跑的故事。'
        '一家公司的单季利润通常不是你的题目。'
    ),
    'industry': (
        '你是个股及产业链硬核研究者。'
        '你先问谁赚钱、谁承担成本、headline 盖住了链条上的哪一层。'
        '不从一条总量数据直接推出某只股票该怎么买。'
    ),
    'trading': (
        '你是交易系统与市场心理教练。'
        '你看什么才是新信息，大家挤在哪个共识里，什么反应才算数，'
        '什么证据会让这个判断作废。不喊单。'
    ),
}

SYSTEM = (
    '你在给一个金融账号写一篇能发出去的中文帖。'
    '主材料是别人已经写过的判断。你的工作是重组。'
    '可以重组：判断、推理、例子、论证顺序、第二层含义。'
    '不要连续复制独特原句。不要换几个词就算改完。'
    '事实包如果有内容，只用来核对帖子里已经出现的数字、日期、价格。'
    '帖子里已有的数字可以沿用。不要新造数字、日期、价格或公司行动。'
    '人设只决定挑哪一组判断。不要把人设说明里的问句写进正文。'
    '没有改写材料时，不要写。'
    '写法是直接陈述。像一个懂这件事的人把判断和依据写下来。'
    '有判断就直接写判断。不要先否定一个东西，再抛出真正观点。'
    '不要设计 hook、转折、解释、收束。不要追求金句。不要刻意制造反差。'
    '不要替读者总结。不需要结尾。一个具体判断说完可以直接停。'
    '默认写短。原材料很长，成稿也不要把所有内容重新讲一遍。'
    '优先保留一个最值得借的判断、两三个真正支撑它的具体细节、必要的推导。其余删掉。'
    '禁止对比句式，包括：不是X而是Y；重点不在X在Y；真正的问题是；核心不是；'
    '与其X不如Y；看似X实则Y；表面上实际上；X没变变的是Y。'
    '禁止这些转折：真正值得看的是；更有意思的是；问题在于；关键在于；核心是；'
    '换句话说；这意味着；落点是；说到底；反过来看；值得注意的是。'
    '不要为了生动新增比喻。公司员工经理、门票、护城河、方向盘、螺丝、通行证，'
    '以及谁掏钱、谁买单、吃掉、搬家、压住，都不要写。'
    '原材料里的比喻不要默认继承，改写成具体机制。'
    '不要用这些评价词：彻底、颠覆、巨变、重构、新周期、终极、爆发、史诗级、'
    '大时代、定心丸、结构性机会。用具体描述。'
    '不要写未来一定、接下来将、有望成为、会彻底改变、下一轮将由谁主导。'
    '除非材料本身给了时间表或预测，并且正文写明这是材料里的说法。'
    '不要问句。不要小标题。'
    '不要解释你怎么核对来源。不要出现这些词：已读报道、第二信源、packet、'
    '准入事实、原文未打开、该转述不计入、根据我们的 QA、要点是、事实包、改写材料。'
)


def _clip(text, limit=700):
    text = re.sub(r'\s+', ' ', (text or '')).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0]


def source_material(packet, cache, limit=6):
    """Up to six cleared bodies. The writer reads them as a library, not as claims to map."""
    views = {v.get('source_id'): v for v in (packet.get('source_views') or [])}
    facts_by_source = {}
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        if fact.get('admission') not in (
                'official', 'two_independent_major', 'single_major_attributed'):
            continue
        facts_by_source.setdefault(fact.get('source_id'), []).append(fact.get('text') or '')
    out = []
    for source_id, texts in facts_by_source.items():
        view = views.get(source_id) or {}
        cached = (cache or {}).get(source_id) or {}
        sentences = cached.get('sentences') or []
        body = '\n'.join(sentences[:4]) if sentences else '\n'.join(texts[:3])
        if not body.strip():
            continue
        out.append({
            'outlet': view.get('name') or source_id,
            'title': (view.get('claim') or '')[:180],
            'body': _clip(body),
        })
        if len(out) >= limit:
            break
    return out


def facts_block(packet):
    rows = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        if fact.get('admission') not in (
                'official', 'two_independent_major', 'single_major_attributed'):
            continue
        rows.append((fact.get('text') or '').strip())
    return [r for r in rows if r][:8]


def _rewrite_block(piece):
    """One human argument, with the excerpt the writer actually has to read."""
    lines = [
        f"来源：{piece.get('source') or ''}｜作者：{piece.get('author') or ''}",
        f"论点：{piece.get('main_thesis') or ''}",
    ]
    if piece.get('reasoning_chain'):
        lines.append('推理：' + piece['reasoning_chain'])
    if piece.get('interesting_angle'):
        lines.append('角度：' + piece['interesting_angle'])
    if piece.get('second_order_implication'):
        lines.append('第二层：' + piece['second_order_implication'])
    if piece.get('disagreement_with_others'):
        lines.append('和别人的分歧：' + piece['disagreement_with_others'])
    excerpt = (piece.get('original_text') or '').strip()
    if excerpt:
        lines.append('正文：\n' + excerpt)
    return '\n'.join(lines)


def messages_for(packet, persona_id, angle, cache, fact_pack=None, rewrite=None):
    """Two layers. `rewrite` is a list of human arguments, not wire claims.

    The old single-packet path stays for callers that have not split the
    input yet. A rewrite list, including an empty one, is the new path:
    empty means there is nothing to recombine, so the draft stays factual.
    """
    if rewrite is None and fact_pack is None:
        sources = source_material(packet, cache)
        facts = facts_block(packet)
        user = (
            f"{PERSONA.get(persona_id, persona_id)}\n"
            f"别人给过的角度，你可以改，也可以丢掉：{angle or '自己从素材里选一个值得发的点'}\n\n"
            "素材里已经有的事实，数字和时间以这里为准，不要另加：\n"
            + '\n'.join(f'- {row}' for row in facts)
            + '\n\n素材库，拿来重组，不要复述：\n'
            + '\n\n'.join(
                f"{i}. {row['outlet']}｜{row['title']}\n{row['body']}"
                for i, row in enumerate(sources, start=1)
            )
            + '\n\n直接写下判断和撑住它的两三个细节。说完就停。'
            '不要收束句，不要复述标题。'
        )
        return [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': user},
        ], sources
    facts = fact_pack if fact_pack is not None else facts_block(packet)
    pieces = list(rewrite or [])
    if pieces:
        task = (
            '\n\n这一层是主材料。从里面挑一个判断，丢掉重复的，'
            '用两三个具体细节和必要的推导把它写清楚。'
            '说完就停。不要把长材料重新讲一遍。'
            '帖子里已经写出的数字可以沿用。不要新造数字、日期、价格或公司行动。'
            '不要连续搬原句。'
        )
    else:
        task = (
            '\n\n这层是空的：没有可以重组的判断。不要写稿。'
        )
    user = (
        f"{PERSONA.get(persona_id, persona_id)}\n"
        f"人设可以从这些判断里挑，也可以丢掉别人给过的角度：{angle or '自己挑'}\n\n"
        "事实包，数字和时间以这里为准：\n"
        + '\n'.join(f'- {row}' for row in facts)
        + '\n\n改写材料：\n'
        + ('\n\n'.join(_rewrite_block(p) for p in pieces) if pieces else '（没有）')
        + task
    )
    return [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': user},
    ], pieces


def write_public(packet, persona_id, angle, cache, backend_name='relay',
                fact_pack=None, rewrite=None):
    messages, sources = messages_for(
        packet, persona_id, angle, cache, fact_pack=fact_pack, rewrite=rewrite)
    if backend_name == 'local':
        result = backend.complete_local(messages)
    elif backend_name == 'relay':
        result = backend.complete(messages)
    else:
        try:
            result = backend.complete(messages)
        except Exception:
            result = backend.complete_local(messages)
            result['fell_back'] = True
    return {
        'text': result.get('text') or '',
        'model': result.get('model'),
        'provider': result.get('provider'),
        'fell_back': bool(result.get('fell_back')),
        'persona': persona_id,
        'angle_in': angle,
        'sources_used': [
            (row.get('outlet') or row.get('source') or '') for row in sources
        ],
        'prompt': messages[1]['content'],
    }


def main():
    cfg = backend.writer_config()
    print(json.dumps({
        'configured': not cfg['missing'],
        'missing': cfg['missing'],
        'model': cfg['model'] or None,
        'host': (cfg['base_url'].split('://')[-1].split('/')[0] if cfg['base_url'] else None),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
