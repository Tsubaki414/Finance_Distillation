"""Aggregate donor language habits for compose; donor text stays out of git."""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from live.exemplars import load_posts

CARDS_DIR = Path(__file__).resolve().parent / 'personas' / 'language_habits'

ZH_JARGON = ('供需缺口', '议价权', '定价权能否', '基本面支撑', '投资假设', '产能扩张加速',
             '链路往下', '每一环', '催化', '中性偏多', '维持买入', '目标价', '核心看点',
             '值得注意的是', '综上所述', '总而言之', '具体来看', '拆解一下')
EN_JARGON = ('valuation-free', 'supply-discipline', 'multiple expansion', 're-rating',
             'as a reminder', 'key takeaway', 'in conclusion', 'net-net', 'our base case',
             'risk/reward', 'skewed to the upside', 'priced in', 'Calling a strong chance')
ZH_CONN = ('但是', '不过', '反而', '其实', '说白了', '分开看', '换句话说', '所以', '因此', '而且')
EN_CONN = ('but', 'though', 'instead', 'still', 'so', 'and', 'while', 'yet', 'because')

GUIDANCE = ('Write like the donors: judgment-first, short beats, concrete falsifiers. '
            'Avoid analyst-report cadence and Fiona-banned fillers.')

INDUSTRY_CONSTRAINTS = {
    'zh': [
        'NEG: 研报腔 / analyst note tone — no 链路往下推, 每一环的议价权, 基本面支撑套话, 信息罗列收尾.',
        'NEG: do not end on 还早着呢 / 才是关键 filler.',
        'POS: open with a plain judgment sentence; name the one constraint that can break the call '
        '(capacity, pricing power, demand visibility) without a jargon chain.',
        'POS: short uneven lines; one concrete split (e.g. demand vs capacity) beats a full supply-chain parade.',
    ],
    'en': [
        'NEG: no valuation-free optimism, supply-discipline check filler, or sell-side re-rating talk.',
        'NEG: no Calling a strong chance / is a start / empty That said / door metaphor.',
        'POS: lead with the call; test demand visibility vs supply/capex with numbers from units only.',
        'POS: agreements ≠ margins — say what would falsify the demand story.',
    ],
}


def _originals(posts):
    return [p for p in posts if p.get('text') and not p.get('rt') and not p.get('reply') and not p.get('pinned')]


def build_card(persona, posts_dir=None):
    posts = []
    for handle in getattr(persona, 'donor_weights', {}) or {}:
        posts.extend(_originals(load_posts(handle, posts_dir)))
    n = len(posts)
    lang = persona.lang
    jargon = ZH_JARGON if lang == 'zh' else EN_JARGON
    conns = ZH_CONN if lang == 'zh' else EN_CONN
    first_judgment = fragments = jargon_hits = 0
    conn_c = collections.Counter()
    for p in posts:
        text = p['text'].strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        first = lines[0] if lines else text[:40]
        if lang == 'zh':
            if not re.match(r'^[\d$￥%\.\s]+', first) and not first.startswith('http'):
                first_judgment += 1
            fragments += sum(1 for ln in lines if 2 <= len(ln) <= 18)
        else:
            if not re.match(r'^[\d$%.\s]+', first):
                first_judgment += 1
            fragments += sum(1 for ln in lines if 2 <= len(ln.split()) <= 6)
        low = text.casefold()
        if any(j.casefold() in low for j in jargon):
            jargon_hits += 1
        for c in conns:
            if c.casefold() in low:
                conn_c[c] += 1
    prefer = (['判断句开门，数字后置', '短句/断行，少用研报连接词', '点名约束或证伪条件，不堆术语链']
              if lang == 'zh' else
              ['Lead with the call, then 1–2 numbers', 'Plain verbs over sell-side jargon',
               'Name the falsifier (level/flow/condition), skip empty contrast'])
    avoid = (['研报腔：链路往下推/每一环的议价权/基本面支撑套话', '信息罗列而无判断', '还早着呢等口癖收尾']
             if lang == 'zh' else
             ['valuation-free optimism', 'Calling a strong chance / is a start',
              'Empty That said / door metaphor', 'supply-discipline check as filler'])
    return {
        'persona_id': persona.persona_id,
        'lang': lang,
        'basis': 'donor observations' if n else 'Fiona Oct 5 default; donor posts missing',
        'posts': n,
        'judgment_first_share': round(first_judgment / n, 3) if n else None,
        'short_fragment_lines_per_post': round(fragments / n, 2) if n else None,
        'sellside_jargon_post_share': round(jargon_hits / n, 3) if n else None,
        'connector_rates': {k: round(v / n, 3) for k, v in conn_c.most_common(8)} if n else {},
        'prefer': prefer,
        'avoid': avoid,
        'sample_ids': [str(p.get('id')) for p in posts[:12]],
        'guidance': GUIDANCE,
        **({'industry_constraints': INDUSTRY_CONSTRAINTS[lang]}
           if persona.persona_id in ('zh_industry', 'en_industry') else {}),
    }


def load_card(persona):
    path = CARDS_DIR / (persona.persona_id + '.json')
    try:
        card = json.loads(path.read_text())
    except (OSError, ValueError):
        card = build_card(persona)
    if persona.persona_id in ('zh_industry', 'en_industry'):
        card = dict(card)
        card.setdefault('industry_constraints', INDUSTRY_CONSTRAINTS[persona.lang])
    return card


def write_card(persona, posts_dir=None):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    card = build_card(persona, posts_dir=posts_dir)
    if persona.persona_id in ('zh_industry', 'en_industry'):
        card['industry_constraints'] = INDUSTRY_CONSTRAINTS[persona.lang]
    (CARDS_DIR / (persona.persona_id + '.json')).write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + '\n')
    return card
