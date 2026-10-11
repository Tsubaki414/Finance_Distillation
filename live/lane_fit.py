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
        r'预测市场|盘口|赔率|押注|概率盘|prediction market|预测盘|博彩|押|概率|市场隐含', re.I),
    'crypto_perp': re.compile(
        r'\bperps?\b|perpetuals?|funding rates?|\bfunding\b|open interest|\bOI\b|liquidat\w*|leverag\w*|'
        r'hyperliquid|\bhype\b|\baster\b|\blighter\b|\bdydx\b|\bgmx\b|\bdrift\b|basis trade|long/short|'
        r'short squeeze|long squeeze|\bcvd\b|derivatives?|永续|合约|资金费率|持仓量|爆仓|清算|杠杆|多空比|插针|逼空|强平', re.I),
    'crypto_stable_yield': re.compile(
        r'yield-bearing|\busde\b|\bsusde\b|\bsdai\b|\bsusds\b|\busdy\b|\bsyrup|\busd0\b|ethena|pendle|'
        r'(?:stablecoins?|\busd[tc]\b|\bdai\b|\bpyusd\b|稳定币|U本位|泰达|USDT|USDC|USDS|USDe).{0,60}?'
        r'(?:yields?|apy|apr|savings|earn|vault|lending|interest|rate|收益|年化|理财|利率|生息|活期|定期|脱锚|depeg|sUSDS|sUSDe|RWA|rwas?|circulating supply|supply change)|'
        r'(?:yields?|apy|apr|savings|earn|vault|lending|interest|收益|年化|理财|利率|生息|脱锚|depeg|circulating supply|supply change).{0,60}?'
        r'(?:stablecoins?|\busd[tc]\b|\bdai\b|\bpyusd\b|稳定币|U本位|泰达|USDT|USDC|USDS|USDe)|'
        r'\bsusds\b|\bsusde\b|sky money|sUSDS|sUSDe|Ethena|ethena|稳定币收益|生息稳定币|稳定币年化|稳定币理财|RWA收益|tokenized treasury|tokenised treasury',
        re.I | re.S),
}

# Broad macro / BTC / ETF / big-brand news: allowed for a niche account only when the draft ties it to the lane.
BROAD_RX = re.compile(
    r'\bbitcoin\b|\bbtc\b|\bether(?:eum)?\b|\beth\b|\betfs?\b|\bfed\b|\bfomc\b|rate (?:cut|hike)s?|treasur(?:y|ies)|'
    r'\bcpi\b|payrolls?|jobs (?:data|report)|tariffs?|robinhood|el salvador|salvador|\bmstr\b|saylor|'
    r'microstrategy|\bstrategy\b|\bsec\b|\bcftc\b|nasdaq|s&p|\bstocks?\b|equities|\bgold\b|imf\b|'
    r'美联储|降息|加息|比特币|以太坊|ETF|美股|关税|非农|通胀|萨尔瓦多|黄金|美债|微策略', re.I)


# Oct 9 night (HOLD review): 10-09 #27 「$CRH … 市值竟然才刚刚突破 100 万美元 … 链上底池」 was held off_lane because
# "Robinhood" is a broad word; a $TICKER discussed by market cap / pool / liquidity / holders is the meme lane itself.
MEME_TIE = re.compile(r'\$[A-Za-z][A-Za-z0-9]{1,9}\b[^。！？!?\n]{0,120}?(市值|底池|流动性|筹码|换手|持币地址|market ?cap|mcap|'
                      r'liquidity|\bholders\b|\bLP\b)|(市值|底池|流动性|market ?cap|mcap|liquidity)[^。！？!?\n]{0,60}?\$[A-Za-z]{2,10}\b',
                      re.I | re.S)


# Oct 11: the stablecoin account's positioning covers 脱锚和对手方风险 - a stablecoin issuer freezing / blacklisting /
# seizing funds, a depeg or a reserve / redemption problem is on its lane without a yield word (10-11: the Tether freeze
# lawsuit off 墨川.eth's BTC/ETH macro lane belongs here)
STABLE_RISK_TIE = re.compile(
    r'(?:stablecoins?|\busd[tc]\b|\btether\b|\bcircle\b|\bpyusd\b|稳定币|泰达)[^。！？!?\n]{0,160}?'
    r'(?:froze|freez\w*|frozen|blacklist\w*|seiz\w*|depeg\w*|reserves?|redemptions?|counterparty|attestation|'
    r'冻结|拉黑|黑名单|罚没|没收|脱锚|储备|赎回|对手方|兑付)|'
    r'(?:froze|freez\w*|frozen|blacklist\w*|seiz\w*|depeg\w*|冻结|拉黑|黑名单|罚没|脱锚|赎回|兑付)[^。！？!?\n]{0,160}?'
    r'(?:stablecoins?|\busd[tc]\b|\btether\b|\bcircle\b|稳定币|泰达)', re.I | re.S)


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
    hits = {m.group(0).lower()[:40] for m in rx.finditer(text)}
    if lane == 'crypto_meme':   # Oct 9 night: a small $TICKER talked about by market cap / pool / holders is a meme coin
        hits |= {'$ticker+' + m.group(1).lower()[:12] for m in MEME_TIE.finditer(text)}
    if lane == 'crypto_stable_yield':   # Oct 11: issuer / counterparty risk of a stablecoin (freeze, depeg, reserves)
        hits |= {'issuer_risk+' + m.group(0).lower()[:20] for m in STABLE_RISK_TIE.finditer(text)}
    return sorted(hits)


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


# ---------------------------------------------------------------- BTC/ETH macro lane + reassign (Oct 11)
# 10-11 墨川.eth (crypto_macro_zh, 加密宏观 · BTC/ETH 大势判断) got a Tether wallet-freeze lawsuit (stablecoin compliance,
# no BTC / ETH / macro link) because the beat gate lets the macro crypto accounts take any crypto packet. Rule now
# (FD_MACRO_LANE, default 1): a BTC/ETH macro account (editorial_style.CRYPTO_MACRO_OK) takes a packet / archive pick /
# draft only when it names BTC / ETH / the crypto market as a whole or a macro driver (rates, liquidity, dollar,
# flows, cycle ...). Off-lane material is not dropped: reassign_target() names the same-language account whose own
# lane fits it (a stablecoin compliance item -> crypto_stable_yield_<lang>), and the caller hands it over.

MACRO_LANE_RX = re.compile(
    r'\bbitcoin\b|\bbtc\b|\$btc|\bether(?:eum)?\b|\beth\b|\$eth|比特币|大饼|以太坊|以太|姨太|\bcrypto (?:market|prices?|cycle)|'
    r'total (?:crypto )?market cap|加密(?:市场|大盘|总市值)|大盘|\betfs?\b|现货 ?etf|'
    r'\bfed\b|\bfomc\b|federal reserve|rate (?:cut|hike)s?|interest rates?|\byields?\b|treasur(?:y|ies)|\bbonds?\b|'
    r'liquidity|\bm2\b|\bdollar (?:index|strength|weakness|liquidity)|\b(?:strong|weak|us|u\.s\.) dollar\b|\bdxy\b|inflation|\bcpi\b|\bpce\b|payrolls?|recession|risk[- ](?:on|off|assets?)|'
    r'macro|halving|(?:4|four)-year cycle|\bcycles?\b|\bbull (?:market|run)|\bbear market|\bnasdaq\b|s&p ?500|\bgold\b|'
    r'美联储|降息|加息|利率|美债|国债|收益率|流动性|美元指数|(?<![\d万亿千百\s])美元|通胀|非农|衰退|风险资产|宏观|减半|周期|纳指|标普|黄金|资金面|'
    r'资金流|净流入|净流出', re.I)

# topic -> lane, for reassigning off-lane material (stablecoin issuer / compliance first: no yield word needed)
STABLE_TOPIC_RX = re.compile(r'stablecoins?|\busd[tce]\b|\btether\b|\bcircle\b|\bpyusd\b|\busd1\b|\brlusd\b|\bdai\b|'
                             r'genius act|\bmica\b|depeg|稳定币|泰达|脱锚|U本位', re.I)
REASSIGN_LANES = ('crypto_stable_yield', 'crypto_prediction', 'crypto_meme', 'crypto_airdrop', 'crypto_perp',
                  'crypto_ecosystem_sol_base')


def macro_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_MACRO_LANE', '1') != '0' and enabled(env)


def is_macro_account(account_cfg):
    from live.editorial_style import CRYPTO_MACRO_OK
    return ((account_cfg or {}).get('id') or '') in CRYPTO_MACRO_OK


def macro_hits(text):
    return sorted({m.group(0).lower()[:30] for m in MACRO_LANE_RX.finditer(str(text or ''))})


def topic_lane(text):
    """(lane, hits) of the niche lane the text is most about, or (None, [])."""
    best, best_hits = None, []
    for lane in REASSIGN_LANES:
        hits = lane_hits(lane, text)
        if lane == 'crypto_stable_yield':
            hits = sorted(set(hits) | {m.group(0).lower() for m in STABLE_TOPIC_RX.finditer(str(text or ''))})
        if len(hits) > len(best_hits):
            best, best_hits = lane, hits
    return best, best_hits


def reassign_target(text, lang, accounts=None, exclude=()):
    """Same-language account whose primary lane fits the text, or None. accounts default: the gated roster."""
    lane, hits = topic_lane(text)
    if not lane:
        return None
    if accounts is None:
        from live import fd_accounts
        accounts = fd_accounts.rows()
    for a in accounts:
        if a.get('id') in exclude or str(a.get('lang') or '')[:2] != str(lang or '')[:2]:
            continue
        if primary_lane(a) == lane:
            return {'account': a['id'], 'lane': lane, 'hits': hits[:5]}
    return None


def macro_check(account_cfg, text, accounts=None):
    """{'ok', 'why', 'hits', 'reassign'} for one packet / archive pick / draft of a BTC/ETH macro account (ok for
    every other account)."""
    if not macro_enabled() or not is_macro_account(account_cfg):
        return {'ok': True, 'why': 'not_macro'}
    hits = macro_hits(text)
    if hits:
        return {'ok': True, 'why': 'on_macro_lane', 'hits': hits[:5]}
    target = reassign_target(text, account_cfg.get('lang'), accounts, exclude=(account_cfg.get('id'),))
    return {'ok': False, 'why': 'off_lane', 'lane': 'btc_eth_macro', 'hits': [], 'reassign': target,
            'detail': 'no BTC / ETH / crypto-market / macro driver for a BTC/ETH macro account'
                      + (f" -> reassign to {target['account']} ({target['lane']})" if target else '')}


def macro_draft_check(account_cfg, body, accounts=None):
    return macro_check(account_cfg, body, accounts)


def archive_check(account_cfg, text, accounts=None):
    """Lane check of an archive (回看 / 常青) pick or draft (Oct 11): BTC/ETH macro accounts via macro_check; niche
    accounts via packet_check (the pick comes from the account's own donors / X sources, so a non-broad pick passes)
    with a reassign target - the fitting niche account, or the same-language BTC/ETH macro account for broad BTC /
    ETH / macro material."""
    chk = macro_check(account_cfg, text, accounts)
    if not chk['ok'] or not is_niche(account_cfg):
        return chk
    chk = packet_check(account_cfg, text, own_x=True)
    if chk['ok']:
        return chk
    lang = (account_cfg or {}).get('lang')
    target = reassign_target(text, lang, accounts, exclude=(account_cfg.get('id'),))
    if not target and is_broad(text):
        if accounts is None:
            from live import fd_accounts
            accounts = fd_accounts.rows()
        macro = next((a for a in accounts if is_macro_account(a) and str(a.get('lang'))[:2] == str(lang)[:2]
                      and a.get('id') != account_cfg.get('id')), None)
        target = {'account': macro['id'], 'lane': 'btc_eth_macro', 'hits': []} if macro else None
    return {**chk, 'reassign': target,
            'detail': f"archive pick off the {chk.get('lane')} lane" + (f" -> reassign to {target['account']}" if target else '')}
