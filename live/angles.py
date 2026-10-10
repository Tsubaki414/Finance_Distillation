"""Per-account writing angles, learned from the account's own donor cluster (Oct 7, fd20).

The same world event can be written many ways. Each account gets an angle distribution: the share of its
donors' original posts (mixed by donor weight, same corpus as posting_habits) that take each lens below.
Only aggregates are stored (live/compose_universes.json); donor text stays in the ignored corpus.

At compose time the daily runner gives every draft ONE angle: the account's most-used lens that the source
can support and that no other account already took on the same event that day. The angle goes into the
stance and compose payloads as a framing instruction (what question this account asks of the material),
never as facts.
"""
from __future__ import annotations

import collections
import re

# id -> (regex over zh + en text, en label, zh label)
ANGLES = {
    'macro_liquidity': (r'流动性|美联储|降息|加息|利率|美元|美债|宏观|liquidity|\bfed\b|rate cuts?|rates?\b|dollar|treasur|yields?|macro',
                        'macro liquidity: what rates, the dollar and liquidity mean for it', '宏观流动性：利率、美元和流动性对它意味着什么'),
    'flows_etf': (r'ETF|资金流|净流入|净流出|流入|流出|inflows?|outflows?|net flows?|fund flows?|AUM|申购|赎回',
                  'flows: who is actually buying or selling (ETF / fund / exchange flows)', '资金流：谁在真金白银地买或卖（ETF、基金、交易所流向）'),
    'onchain_holders': (r'链上|筹码|长期持有者|短期持有者|持币|巨鲸|交易所余额|成本价|已实现|MVRV|SOPR|LTH|STH|on-?chain|holders?|whales?|'
                        r'exchange (?:balance|reserve)s?|realized (?:price|cap)|cost basis|supply',
                        'holder behaviour: what long/short-term holders and cost bases show', '筹码结构：长短期持有者和成本区在说什么'),
    'derivatives_positioning': (r'合约|期货|资金费率|未平仓|持仓量|爆仓|清算|杠杆|期权|基差|funding|open interest|\bOI\b|liquidat|leverage|'
                                r'perps?\b|futures|options?|basis|gamma|skew',
                                'positioning: leverage, funding, open interest, who gets squeezed', '仓位与杠杆：资金费率、未平仓、谁会被挤出去'),
    'price_structure': (r'支撑|阻力|突破|跌破|回踩|K线|均线|结构|区间|新高|新低|support|resistance|breakout|breakdown|range|levels?\b|'
                        r'trend|moving average|higher lows?|lower highs?|structure',
                        'market structure: what the price structure says (no trade calls, no targets)', '价格结构：结构和区间在说什么（不喊单、不给点位）'),
    'trader_psychology': (r'心态|情绪|恐慌|贪婪|FOMO|止损|仓位管理|纪律|上头|扛单|fear|greed|fomo|psycholog|discipline|patience|stop loss|'
                          r'risk management|emotion|conviction|ego',
                          'trader psychology: how the crowd is likely to react and the risk-management lesson', '交易心理：人群会怎么反应、风险管理上该记住什么'),
    'cycle_position': (r'周期|减半|牛市|熊市|顶部|底部|四年|牛熊|cycle|halving|bull market|bear market|cycle top|cycle bottom|four[- ]year|'
                       r'mid-cycle|late cycle|early cycle',
                       'cycle position: where this sits in the multi-year cycle', '周期位置：这件事放在多年周期里处在哪'),
    'narrative_sector': (r'叙事|赛道|板块|山寨|轮动|meme|热点|生态|narratives?|sectors?|rotation|altcoins?|alts\b|ecosystem|memecoins?|'
                         r'\bL2s?\b|layer ?2|solana|base\b|AI agents?',
                         'narrative: which story is gaining or losing attention and whether money follows', '叙事轮动：哪个故事在升温或退潮，钱有没有跟上'),
    'tokenomics_yield': (r'代币经济|解锁|释放|通胀|收益率|收益|APY|APR|质押|借贷|手续费|协议收入|回购|TVL|tokenomics|unlocks?|emissions?|'
                         r'yield|staking|lending|fees|protocol revenue|buybacks?|\bTVL\b|dilution',
                         'tokenomics: where the value and the yield actually come from', '代币经济：价值和收益到底从哪来'),
    'regulation_institutional': (r'监管|SEC|CFTC|合规|牌照|立法|法案|机构|银行|券商|托管|贝莱德|regulat|\bSEC\b|CFTC|complian|licen[cs]e|'
                                 r'legislation|bill\b|institution|banks?\b|custod|blackrock|fidelity|wall street',
                                 'institutions and rules: what regulation or institutional adoption changes', '机构与监管：监管或机构进场改变了什么'),
    'stablecoin_rwa': (r'稳定币|USDT|USDC|RWA|代币化|美债代币|stablecoins?|tokeniz|real[- ]world assets?|\bRWA\b|USDT|USDC',
                       'stablecoins / tokenization: the plumbing and who it serves', '稳定币与代币化：底层管道、服务谁'),
    'fundamentals_valuation': (r'估值|营收|收入|利润|毛利|财报|现金流|市盈率|指引|valuation|revenue|earnings|margins?|cash flow|'
                               r'multiples?|P/E|guidance|EPS',
                               'fundamentals: revenue, margins, guidance and what the valuation assumes', '基本面：收入、利润率、指引，以及估值在假设什么'),
    'supply_chain_capacity': (r'产能|供应链|芯片|HBM|数据中心|电力|资本开支|capex|capacity|supply chain|chips?|HBM|data ?cent|power|'
                              r'hyperscaler|semis?',
                              'supply chain: capacity, bottlenecks and who has pricing power', '产业链：产能、瓶颈和谁有定价权'),
    'long_term_compounding': (r'长期|复利|定投|配置|组合|长期持有|拿住|long[- ]term|compound|\bDCA\b|allocation|portfolio|hold(?:ing)? for|'
                              r'decades?|stay(?:ing)? the course',
                              'long-term: what it means for a patient holder and a portfolio', '长期视角：对耐心持有者和组合意味着什么'),
    'retail_lesson': (r'新手|散户|普通人|踩坑|教训|亏钱|亏了|小白|避坑|lesson|mistakes?|beginners?|retail|newbies?|learned|regret',
                      'ordinary holder: what a normal person should take from it, and the trap to avoid', '普通人视角：普通持有者该怎么看、要避开哪个坑'),
    'contrarian_check': (r'共识|所有人|大家都|反直觉|没人|一致预期|拥挤|consensus|everyone|contrarian|nobody|crowded|unpopular|'
                         r'priced in|the market thinks',
                         'contrarian: what the consensus is missing or overpricing', '反共识：共识漏掉或高估了什么'),
    'data_history': (r'历史上|上一次|自从|纪录|统计|历史|分位|平均|since \d{4}|record|streak|historically|percentile|average|'
                     r'first time since|last time',
                     'history and data: how this compares with past episodes', '历史对照：和过去几次相比是什么位置'),
}
_RX = {k: re.compile(v[0], re.I) for k, v in ANGLES.items()}
TOP_N = 6


def angles_of(text):
    """Angle ids a text takes (a post may take several)."""
    return [k for k, rx in _RX.items() if rx.search(text or '')]


def donor_angle_mix(handles_weights, lang, posts_dir=None):
    """{angle: share} over the cluster's originals, each donor's own shares mixed by donor weight (cap 40%)."""
    from live import posting_habits as ph
    weights = ph.capped_weights(handles_weights)
    per, used = {}, {}
    for h in weights:
        rows = ph.donor_rows(h, lang, posts_dir)
        if not rows:
            continue
        c = collections.Counter()
        for _p, text, *_ in rows:
            for a in angles_of(text):
                c[a] += 1
        per[h] = {a: n / len(rows) for a, n in c.items()}
        used[h] = len(rows)
    weights = ph.capped_weights({h: weights[h] for h in per}) if per else {}
    mix = collections.Counter()
    for h, shares in per.items():
        for a, v in shares.items():
            mix[a] += weights.get(h, 0) * v
    total = sum(mix.values()) or 1.0
    return ({a: round(v / total, 4) for a, v in mix.most_common()}, used)


def distinctive(mixes, floor=0.02):
    """{account: {angle: score}}: share x lift over the 20-account mean, so each account leads with the lenses its
    own donors use MORE than the other accounts' donors (broad lenses like macro liquidity stop winning everywhere)."""
    angles_all = {a for m in mixes.values() for a in m}
    n = max(1, len(mixes))
    mean = {a: sum(m.get(a, 0) for m in mixes.values()) / n for a in angles_all}
    out = {}
    for acct, m in mixes.items():
        scores = {a: v * (v / mean[a]) for a, v in m.items() if v >= floor and mean.get(a)}
        tot = sum(scores.values()) or 1.0
        out[acct] = {a: round(v / tot, 4) for a, v in sorted(scores.items(), key=lambda kv: -kv[1])}
    return out


def top_angles(mix, n=TOP_N):
    return [a for a, _ in sorted((mix or {}).items(), key=lambda kv: -kv[1])[:n]]


def assign(account_mix, source_text, taken=(), boost=None):
    """The account's angle for one source: its most-used lens the source supports and nobody else took on this
    event; if the source supports none of its top lenses, its most-used lens not yet taken (a framing, not facts).
    boost {angle: multiplier} (FD_HOTSPOT soft priors: viral structure priors x review feedback) re-ranks the same
    top lenses by share x multiplier; it never adds a lens. None = the plain share order."""
    ranked = top_angles(account_mix)
    if boost:
        mix = account_mix or {}
        ranked = sorted(ranked, key=lambda a: (-(mix.get(a, 0) * boost.get(a, 1.0)), ranked.index(a)))
    fits = set(angles_of(source_text))
    for a in ranked:
        if a in fits and a not in taken:
            return a, 'source_fit'
    for a in ranked:
        if a not in taken:
            return a, 'account_habit'
    return (ranked[0] if ranked else None), 'shared'


def payload(angle_id, lang):
    if not angle_id or angle_id not in ANGLES:
        return None
    _rx, en, zh = ANGLES[angle_id]
    return {'id': angle_id, 'lens': zh if lang == 'zh' else en,
            'rule': ('Write this post through this lens: it is the question this account asks of the material. Other '
                     'accounts cover the same event from other lenses, so do not drift into a generic summary. The lens '
                     'only frames the judgment; every fact and number still comes from the units. Do not invent '
                     'experience, positions, credentials or trades. '
                     'IMPORTANT: use the lens to choose WHAT to say; never write the lens label words themselves '
                     '(流动性/宏观/筹码/底层/结构/structure/structural/liquidity/macro/capital flows) '
                     'unless the source units use those exact words for this specific fact.')}
