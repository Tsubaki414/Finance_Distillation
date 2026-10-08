"""Lane fit for the niche accounts (Oct 8 evening, Fiona's quality skim of the new-account drafts).

The meme / airdrop / prediction / stablecoin-yield / perp-DEX / Solana-Base accounts were writing generic BTC, ETF,
Robinhood and El Salvador news (their lane material is thin, so lane_first only *ordered* on-lane packets first and
then fell through to broad news). Rule now (FD_LANE_FIT, default 1):

  - selection: a niche account (fd row lane_first, or the id patterns below) takes a packet only when the packet text
    is on its primary lane (strong lane words, live/beat_rules LANE_REQUIRES where a lane has one), or it is one of
    the account's own X sources that is not broad macro / BTC / ETF news. Everything else is an off-lane reject
    (logged in plan.json `off_lane_rejects`). Fewer on-lane drafts beat off-lane fill.
  - after compose: a niche draft whose body talks broad macro / BTC / ETF without tying it to the lane (no lane word
    in the body) is HELD `off_lane` - e.g. liquidations are fine for the perp account because they are perp words.

Deterministic; no model call.
"""
from __future__ import annotations

import os
import re

VERSION = 'lane-fit-v1'
NICHE_ID = re.compile(r'^(?:crypto_meme_|crypto_airdrop_|crypto_prediction_|crypto_stable_yield_)|'
                      r'^(?:crypto_perp_dex_en|sol_base_alpha_en)$')

# Strong lane words per primary lane (narrower than beat_rules.SUB_BEAT_KEYWORDS: 'claim', 'points', 'allocation',
# 'leverage' alone or 'yield' alone are not enough to call a packet on-lane for a niche account).
LANE_RX = {
    'crypto_meme': re.compile(
        r'memecoins?|meme ?coins?|\bmemes?\b|pump\.?fun|four\.meme|letsbonk|\bbonk\b|\bpepe\b|\bdoge(?:coin)?\b|'
        r'\bshib\b|\bwif\b|\bpnut\b|trenches|launchpads?|bags\.fm|\bzora\b|\bdegen|\brug(?:s|ged|pull)?\b|'
        r'土狗|金狗|冲狗|meme ?币|迷因|发射台|内盘|外盘|狗庄|貔貅|跑路|打狗|meme', re.I),
    'crypto_airdrop': re.compile(
        r'airdrops?|\btge\b|points? (?:program|farming|season|campaign|system)|farming|retroactive|testnets?|'
        r'snapshot|sybil|eligib\w*|claim (?:page|window|portal|opens|is live)|season ?[1-9]\b|\bs[1-9] (?:points|rewards)|'
        r'空投|撸毛|积分|交互|快照|测试网|女巫|领取|撸空投|tge|打新', re.I),
    'crypto_prediction': re.compile(
        r'polymarket|kalshi|prediction markets?|limitless|myriad|implied (?:probability|odds)|betting odds|'
        r'预测市场|盘口|赔率|押注|概率盘', re.I),
    'crypto_perp': re.compile(
        r'\bperps?\b|perpetuals?|funding rates?|\bfunding\b|open interest|\bOI\b|liquidat\w*|leverag\w*|'
        r'hyperliquid|\bhype\b|\baster\b|\blighter\b|\bdydx\b|\bgmx\b|\bdrift\b|basis trade|long/short|'
        r'short squeeze|long squeeze|\bcvd\b|derivatives?|永续|合约|资金费率|持仓量|爆仓|清算|杠杆|多空比|插针|逼空|强平', re.I),
    'crypto_stable_yield': re.compile(
        r'yield-bearing|\busde\b|\bsusde\b|\bsdai\b|\bsusds\b|\busdy\b|\bsyrup|\busd0\b|ethena|pendle|'
        r'(?:stablecoins?|\busd[tc]\b|\bdai\b|\bpyusd\b|稳定币|U本位).{0,60}?'
        r'(?:yields?|apy|apr|savings|earn|vault|lending|interest|rate|收益|年化|理财|利率|生息|活期|定期|脱锚|depeg)|'
        r'(?:yields?|apy|apr|savings|earn|vault|lending|interest|收益|年化|理财|利率|生息|脱锚|depeg).{0,60}?'
        r'(?:stablecoins?|\busd[tc]\b|\bdai\b|\bpyusd\b|稳定币|U本位)', re.I | re.S),
}

# Broad macro / BTC / ETF / big-brand news: allowed for a niche account only when the draft ties it to the lane.
BROAD_RX = re.compile(
    r'\bbitcoin\b|\bbtc\b|\bether(?:eum)?\b|\beth\b|\betfs?\b|\bfed\b|\bfomc\b|rate (?:cut|hike)s?|treasur(?:y|ies)|'
    r'\bcpi\b|payrolls?|jobs (?:data|report)|tariffs?|robinhood|el salvador|salvador|\bmstr\b|saylor|'
    r'microstrategy|\bstrategy\b|\bsec\b|\bcftc\b|nasdaq|s&p|\bstocks?\b|equities|\bgold\b|imf\b|'
    r'美联储|降息|加息|比特币|以太坊|ETF|美股|关税|非农|通胀|萨尔瓦多|黄金|美债|微策略', re.I)


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_LANE_FIT', '1') != '0'


def is_niche(account_cfg):
    aid = (account_cfg or {}).get('id') or ''
    return bool((account_cfg or {}).get('lane_first')) or bool(NICHE_ID.search(aid))


def primary_lane(account_cfg):
    """The account's own lane: its first retrieval beat that is a deterministic lane (jev_front.LANE_BEATS)."""
    from live.jev_front import LANE_BEATS
    for b in (account_cfg or {}).get('retrieval_beats') or ():
        if b in LANE_BEATS:
            return b
    return None


def lane_hits(lane, text):
    """Lane words found in text (lower-cased, sorted). Solana / Base uses beat_rules.LANE_REQUIRES (names)."""
    text = str(text or '')
    if lane == 'crypto_ecosystem_sol_base':
        from live.beat_rules import LANE_REQUIRES
        rx = LANE_REQUIRES[lane]
        extra = re.compile(r'\bjupiter\b|\bjito\b|raydium|kamino|meteora|helius|phantom|pump\.?fun|aerodrome|'
                           r'farcaster|base app|\bx402\b|firedancer|alpenglow|\bbonk\b', re.I)
        return sorted({m.group(0).lower() for r in (rx, extra) for m in r.finditer(text)})
    rx = LANE_RX.get(lane)
    if rx is None:
        return []
    return sorted({m.group(0).lower()[:40] for m in rx.finditer(text)})


def is_broad(text):
    return bool(BROAD_RX.search(str(text or '')))


def packet_check(account_cfg, text, own_x=False):
    """{'ok', 'why', 'lane', 'hits'} for one candidate packet of a niche account (ok for every other account)."""
    if not enabled() or not is_niche(account_cfg):
        return {'ok': True, 'why': 'not_niche'}
    lane = primary_lane(account_cfg)
    if not lane:
        return {'ok': True, 'why': 'no_lane'}
    hits = lane_hits(lane, text)
    if hits:
        return {'ok': True, 'why': 'on_lane', 'lane': lane, 'hits': hits[:5]}
    if own_x and not is_broad(text):
        return {'ok': True, 'why': 'own_x_not_broad', 'lane': lane, 'hits': []}
    return {'ok': False, 'why': 'off_lane', 'lane': lane, 'hits': [], 'broad': is_broad(text)}


def draft_check(account_cfg, body):
    """{'ok', 'why', 'lane', 'hits'} for a composed niche draft: broad news in the body needs a lane word too."""
    if not enabled() or not is_niche(account_cfg):
        return {'ok': True, 'why': 'not_niche'}
    lane = primary_lane(account_cfg)
    if not lane:
        return {'ok': True, 'why': 'no_lane'}
    hits = lane_hits(lane, body)
    if hits:
        return {'ok': True, 'why': 'ties_to_lane', 'lane': lane, 'hits': hits[:5]}
    if not is_broad(body):
        return {'ok': True, 'why': 'not_broad', 'lane': lane, 'hits': []}
    return {'ok': False, 'why': 'off_lane', 'lane': lane, 'hits': [],
            'detail': f'broad macro / BTC / ETF draft without a {lane} tie-in'}
