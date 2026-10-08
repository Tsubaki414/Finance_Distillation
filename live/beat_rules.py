"""Deterministic beat tags (no model call; Oct 7, fd20).

Two users:
  - account-scoped X posts (live/x_daily.py) are tagged here instead of by Jev: keyword beats over the unit
    statement / view subject / post text, plus the subscribing accounts' first beat as a floor;
  - crypto sub-beats (jev_front.SUB_BEATS) for any unit already tagged crypto_macro_*: Jev only knows the ten
    original beats, so the crypto lanes (meme / perp / DeFi / airdrop / on-chain) are added by keyword.

Tags use the persona_tags shape ({'verdict': 'relevant', 'confidence': c, 'rule': ...}); confidence >= 0.7 makes
the beat a tag_persona (content_store threshold). Rules only ever ADD beats; Jev verdicts are kept as they are.
"""
from __future__ import annotations

import re

from live.jev_front import JEV_BEATS, KEYWORD_LANES, KEYWORDS, SUB_BEATS

VERSION = 'beat-rules-v1'
KEYWORD_CONFIDENCE = 0.75
SUBSCRIBER_CONFIDENCE = 0.7
CRYPTO_BEATS = ('crypto_macro_zh', 'crypto_macro_en')

SUB_BEAT_KEYWORDS = {
    'crypto_meme': ('meme', 'memecoin', 'pump.fun', 'pumpfun', 'bonk', 'pepe', 'doge', 'shib', 'degen', 'launchpad',
                    'four.meme', 'letsbonk', 'bags.fm', 'zora', 'trenches', 'ct narrative',
                    '土狗', '金狗', '冲狗', 'meme币', '迷因', '发射台', '内盘', '外盘', '狗庄'),
    'crypto_perp': ('perp', 'perps', 'perpetual', 'funding rate', 'funding', 'open interest', 'liquidation',
                    'liquidated', 'leverage', 'long/short', 'basis trade', 'hyperliquid', 'aster', 'lighter', 'dydx',
                    'short squeeze', 'long squeeze', 'cvd', '合约', '永续', '资金费率', '持仓量', '爆仓', '清算', '杠杆',
                    '多空比', '做空', '做多', '插针', '逼空'),
    'crypto_defi': ('defi', 'tvl', 'lending', 'borrow', 'aave', 'uniswap', 'curve', 'pendle', 'ethena', 'morpho',
                    'eigen', 'restaking', 'liquid staking', 'lst', 'lrt', 'dex', 'amm', 'liquidity pool', 'yield',
                    'apy', 'apr', 'vault', 'tokenomics', 'buyback', 'fee switch', 'protocol revenue', 'rwa',
                    '借贷', '收益率', '流动性池', '质押', '再质押', '协议收入', '回购', '代币经济', '金库', '挖矿'),
    'crypto_airdrop': ('airdrop', 'points', 'farming', 'tge', 'snapshot', 'retroactive', 'testnet', 'claim',
                       'season 2', 'season 3', 'eligib', 'allocation', 'sybil',
                       '空投', '积分', '撸毛', '交互', '快照', '测试网', '领取', '女巫', '撸空投'),
    'crypto_onchain': ('on-chain', 'onchain', 'whale', 'wallet', 'address', 'exchange inflow', 'exchange outflow',
                       'netflow', 'inflow', 'outflow', 'mvrv', 'sopr', 'utxo', 'realized price', 'realized cap',
                       'long-term holder', 'short-term holder', 'lth', 'sth', 'holders', 'etf flow', 'etf flows',
                       'glassnode', 'cryptoquant', 'arkham', 'nansen', 'dune', 'reserve',
                       '链上', '巨鲸', '鲸鱼', '地址', '转入', '转出', '流入', '流出', '筹码', '长期持有者', '短期持有者',
                       '已实现价格', '交易所余额', '净流'),
    # Oct 8 (36 accounts). crypto_prediction: Polymarket / Kalshi count as the crypto word (LANE_SELF);
    # crypto_stable_yield also needs a stablecoin word (LANE_REQUIRES).
    'crypto_prediction': ('polymarket', 'kalshi', 'prediction market', 'prediction markets', 'implied probability',
                          'odds', 'limitless', 'myriad', '预测市场', '盘口', '赔率', '押注', '概率盘'),
    'crypto_stable_yield': ('yield', 'yield-bearing', 'apy', 'apr', 'savings rate', 'earn', 'vault', 'fixed rate',
                            'pendle', 'ethena', 'usde', 'susde', 'sdai', 'susds', 'usdy', 'depeg', 'de-peg',
                            'money market', 'tokenized treasur', 'lending rate', 'borrow rate',
                            '理财', '年化', '活期', '定期', '生息', '收益率', '收益', '脱锚', '赚币', '利率'),
}
# Oct 8: non-crypto keyword lanes (jev_front.KEYWORD_LANES); tagged on any unit by lane_tags
KEYWORD_LANE_WORDS = {
    'ipo': ('ipo', 'ipos', 'initial public offering', 's-1', 'f-1', 'oversubscribed', 'cornerstone', 'hkex',
            'listing debut', 'priced its ipo', 'prices ipo', 'go public', 'goes public', 'going public',
            '招股', '打新', '新股', '认购', '超购', '孖展', '中签', '暗盘', '基石投资', '上市首日', '港交所', '发行价', '递表'),
}
# a lane whose own requirement word is crypto enough (Polymarket, USDe) and is always required ('odds' alone is not a
# prediction-market post, 'yield' alone is not a stablecoin-yield post)
LANE_REQUIRES = {
    'crypto_prediction': re.compile(r'polymarket|kalshi|prediction markets?|预测市场', re.I),
    'crypto_stable_yield': re.compile(r'stablecoins?|\busd[tce]\b|\busde\b|\bsusde\b|\bdai\b|\busds\b|\bpyusd\b|'
                                      r'\busd1\b|稳定币|U本位', re.I),
    'ipo': re.compile(r'\bipos?\b|initial public offering|\b[SF]-1\b|打新|招股|新股|递表|go(?:es|ing)? public', re.I),
}
LANE_SELF = {b: LANE_REQUIRES[b] for b in ('crypto_prediction', 'crypto_stable_yield')}
CRYPTO_WORDS = re.compile(r'bitcoin|\bbtc\b|ethereum|\beth\b|crypto|stablecoin|\bsol\b|solana|altcoin|memecoin|'
                          r'blockchain|\bdefi\b|airdrop|on-?chain|\bperps?\b|hyperliquid|pump\.fun|\btvl\b|\bdex\b|'
                          r'比特币|以太坊|加密|稳定币|代币|币圈|币价|山寨|主流币|公链|链上|空投|土狗|meme币', re.I)


def _rx(word):
    w = re.escape(word.lower())
    if not word.isascii():
        return w
    # short ascii words need both boundaries ('lst' must not match 'list'); longer ones keep stem matching
    return (r'(?<![a-z0-9])' + w + r'(?![a-z0-9])') if len(word) <= 4 else r'(?<![a-z0-9])' + w


def _compile(words):
    return re.compile('|'.join(_rx(w) for w in sorted(set(words), key=len, reverse=True)), re.I) if words else None


def _beat_words():
    from live.reportgem_daily import THEMES
    out = {}
    for beat in JEV_BEATS:
        words = set(KEYWORDS.get(beat, ())) | set(THEMES[beat][2] if beat in THEMES else ())
        out[beat] = words
    out.update({b: set(w) for b, w in SUB_BEAT_KEYWORDS.items()})
    out.update({b: set(w) for b, w in KEYWORD_LANE_WORDS.items()})
    return out


_PATTERNS = None


def patterns():
    global _PATTERNS
    if _PATTERNS is None:
        _PATTERNS = {b: _compile(w) for b, w in _beat_words().items()}
    return _PATTERNS


def unit_text(unit, source=None):
    view = unit.get('view') or {}
    parts = [unit.get('statement'), view.get('subject'), ' '.join(view.get('reasoning') or [])]
    parts += [n.get('metric') for n in unit.get('numbers') or [] if isinstance(n, dict)]
    parts += [s.get('exact_text') for s in unit.get('source_spans') or [] if isinstance(s, dict)]
    if source:
        parts.append(source.get('title'))
    return ' '.join(str(p) for p in parts if p)


def keyword_beats(text, beats=None):
    """{beat: hits} for every beat whose keywords occur in text. Crypto sub-beats need a crypto word too
    ('funding' or 'yield' alone are not crypto)."""
    out = {}
    crypto = bool(CRYPTO_WORDS.search(text or ''))
    for beat, rx in patterns().items():
        if beats is not None and beat not in beats or rx is None:
            continue
        if beat in SUB_BEATS and not crypto and not (beat in LANE_SELF and LANE_SELF[beat].search(text or '')):
            continue
        if beat in LANE_REQUIRES and not LANE_REQUIRES[beat].search(text or ''):
            continue
        hits = {m.group(0).lower() for m in rx.finditer(text or '')}
        if hits:
            out[beat] = len(hits)
    # broad crypto beats: any crypto word counts (keywords list is narrow)
    if crypto and (beats is None or set(CRYPTO_BEATS) & set(beats)):
        for b in CRYPTO_BEATS:
            out.setdefault(b, 1)
    return out


def _tag(confidence, rule):
    return {'verdict': 'relevant', 'confidence': confidence, 'rule': f'{VERSION}:{rule}'}


def x_unit_tags(unit, source, subscriber_beats):
    """Tags for one X-post unit: keyword beats (0.75) + the subscribing accounts' first beats (0.7) when no
    keyword beat of those accounts matched (so a subscribed post always reaches the subscriber's lane)."""
    text = unit_text(unit, source)
    tags = {b: _tag(KEYWORD_CONFIDENCE, 'keyword') for b in keyword_beats(text)}
    for beats in subscriber_beats:
        if beats and not set(beats) & set(tags):
            tags.setdefault(beats[0], _tag(SUBSCRIBER_CONFIDENCE, 'subscriber'))
    return tags


def crypto_subbeat_tags(rows):
    """{unit_id: merged tags} adding crypto sub-beats to rows already tagged crypto_macro_* (and not yet carrying
    any sub-beat tag). Rows without a sub-beat keyword are left out."""
    out = {}
    for row in rows:
        tags = row.get('persona_tags') or {}
        if not set(row.get('tag_personas') or []) & set(CRYPTO_BEATS) or set(tags) & set(SUB_BEATS):
            continue
        hits = keyword_beats(unit_text(row.get('unit') or {}, row.get('source')), beats=SUB_BEATS)
        if hits:
            out[row['unit_id']] = {**tags, **{b: _tag(KEYWORD_CONFIDENCE, 'crypto_subbeat') for b in hits}}
    return out


# Oct 8 (36 accounts): the lanes added after units were tagged; crypto_subbeat_tags skips rows that already carry a
# sub-beat, so these are re-checked on every unit (any beat) until a rule tags them.
NEW_LANES = ('crypto_prediction', 'crypto_stable_yield', 'ipo')


def lane_tags(rows, lanes=NEW_LANES):
    """{unit_id: merged tags} adding the `lanes` (keyword hit, with each lane's crypto / requirement rule) to any row
    that does not carry them yet. Rules only add; rows without a hit are left out."""
    out = {}
    for row in rows:
        tags = row.get('persona_tags') or {}
        todo = [b for b in lanes if b not in tags]
        if not todo:
            continue
        hits = keyword_beats(unit_text(row.get('unit') or {}, row.get('source')), beats=todo)
        hits = {b: n for b, n in hits.items() if b in todo}
        if hits:
            out[row['unit_id']] = {**tags, **{b: _tag(KEYWORD_CONFIDENCE, 'lane') for b in hits}}
    return out

