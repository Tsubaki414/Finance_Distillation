"""Bilingual (ZH<->EN) finance subject aliases for deterministic view-ledger matching.

`canonicalize(text)` finds high-frequency finance subjects in either language and returns
(concepts, residual_segments): every alias hit becomes one or more language-neutral concept tokens
('@fed', '@rate_cut', ...) and is cut out of the text, so the residual segments are tokenized as
before (EN stems / ZH bigrams) without bigrams straddling a matched span. Same-language peers map
identically on both sides, so their scores barely move; cross-language true peers ("美联储降息路径"
vs "Fed rate cut path") now share concept tokens instead of nothing.

Purely a lookup table - no translation model in the hot path. Long-tail subjects are NOT covered.
Hierarchical concepts (降息 -> @rate_cut + @rates) keep "rate cut" vs "rates" peers overlapping.
Keep entities distinct (Fed vs ECB vs PBoC) so aliases never merge different issuers/assets.
Mutually exclusive ENTITY_FAMILIES (central banks, crypto majors, equity indices, commodities)
force non-match when both sides name different concrete entities in the same family, even if
they share framing tokens (@path/@outlook/@rates); same entity across ZH<->EN still matches.
"""
from __future__ import annotations

import re

# concept(s) -> (EN regex patterns [matched case-insensitively, letter-bounded], ZH literals)
_TABLE = [
    (('fed',), [r'fed', r'federal reserve', r'fomc', r'powell', r'the fed'], ['美联储', '联储', '联邦储备', '鲍威尔']),
    (('ecb',), [r'ecb', r'european central bank', r'lagarde'], ['欧洲央行', '欧央行']),
    (('boj',), [r'boj', r'bank of japan'], ['日本央行', '日银']),
    (('boe',), [r'boe', r'bank of england'], ['英格兰银行', '英央行']),
    (('pboc',), [r'pboc', r"people'?s bank of china", r'reserve requirement ratios?', r'rrr', r'loan prime rate',
                 r'lpr', r'mlf', r"china'?s? (?:interest |policy |benchmark )?rates?"],
     ['中国人民银行', '人民银行', '中国央行', '降准', '存款准备金率', '准备金率', '贷款市场报价利率', 'LPR', 'MLF']),
    (('central_bank',), [r'central banks?'], ['央行']),
    (('rate_cut', 'rates'), [r'rate cuts?', r'cut(?:ting)? rates', r'easing cycle', r'cuts'], ['降息', '减息']),
    (('rate_hike', 'rates'), [r'rate hikes?', r'hik(?:e|ing) rates', r'tightening cycle', r'hikes'], ['加息', '升息']),
    (('rates',), [r'interest rates?', r'policy rates?', r'rates?'], ['利率', '政策利率']),
    (('inflation',), [r'inflation', r'disinflation', r'consumer prices'], ['通胀', '通货膨胀', '物价', '通缩']),
    (('inflation', 'cpi'), [r'cpi', r'core cpi'], ['消费者物价指数', '居民消费价格', '核心cpi']),
    (('inflation', 'pce'), [r'pce', r'core pce'], ['个人消费支出物价']),
    (('ppi',), [r'ppi', r'producer prices'], ['生产者物价', '工业品出厂价格']),
    (('pmi',), [r'pmi', r'purchasing managers?(?:\'? index)?'], ['采购经理指数', '采购经理人指数']),
    (('pmi', 'manufacturing'), [r'manufacturing pmi', r'ism manufacturing'], [r'制造业pmi', '制造业 pmi']),
    (('pmi', 'services'), [r'services pmi', r'non-manufacturing pmi', r'ism services'],
     ['非制造业pmi', '服务业pmi', '非制造业 pmi', '服务业 pmi']),
    (('manufacturing',), [r'manufacturing', r'factory activity'], ['制造业', '工业生产']),
    (('services',), [r'services sector'], ['服务业']),
    (('gdp',), [r'gdp', r'economic growth'], ['国内生产总值', '经济增长', '经济增速']),
    (('recession',), [r'recession', r'hard landing'], ['衰退', '硬着陆']),
    (('soft_landing',), [r'soft landing'], ['软着陆']),
    (('employment',), [r'employment', r'jobs', r'payrolls', r'nonfarm payrolls', r'non-farm payrolls', r'nfp',
                       r'labou?r market'], ['就业', '非农', '劳动力市场', '劳动市场']),
    (('unemployment', 'employment'), [r'unemployment(?: rate)?', r'jobless(?: claims)?'], ['失业率', '失业']),
    (('ust',), [r'treasury', r'treasuries', r'us treasuries', r't-bills?', r'us government bonds'], ['美债', '美国国债']),
    (('yield',), [r'yields?', r'10-year yield', r'10y yield'], ['收益率']),
    (('yield_curve', 'yield'), [r'yield curve', r'curve steepening', r'curve inversion'], ['收益率曲线']),
    (('bonds',), [r'bonds?', r'bond market', r'fixed income'], ['债券', '债市']),
    (('credit',), [r'credit'], ['信贷', '信用']),
    (('credit', 'spread'), [r'credit spreads?'], ['信用利差']),
    (('liquidity',), [r'liquidity'], ['流动性']),
    (('qe',), [r'quantitative easing', r'qe'], ['量化宽松', '扩表']),
    (('qt',), [r'quantitative tightening', r'qt', r'balance sheet runoff'], ['量化紧缩', '缩表']),
    (('fiscal',), [r'fiscal', r'deficits?'], ['财政', '赤字']),
    (('stimulus',), [r'stimulus'], ['刺激政策', '刺激']),
    (('btc', 'crypto'), [r'bitcoin', r'btc'], ['比特币']),
    (('eth', 'crypto'), [r'ethereum', r'eth', r'ether'], ['以太坊']),
    (('crypto',), [r'crypto', r'cryptocurrenc(?:y|ies)', r'digital assets'], ['加密货币', '加密资产', '数字资产']),
    (('etf',), [r'etfs?', r'etf flows'], ['交易所交易基金']),
    (('vix', 'volatility'), [r'vix', r'volatility index'], ['恐慌指数', '波动率指数']),
    (('volatility',), [r'volatility', r'implied vol'], ['波动率', '波动性']),
    (('skew',), [r'skew'], ['偏度']),
    (('derisk',), [r'de-?risking', r'deleveraging'], ['去风险', '去杠杆']),
    (('gold',), [r'gold', r'bullion'], ['黄金', '金价']),
    (('oil',), [r'oil', r'crude', r'brent', r'wti'], ['原油', '油价', '石油']),
    (('usd',), [r'dollar', r'usd', r'dxy', r'greenback'], ['美元指数', '美元']),
    (('cny',), [r'yuan', r'rmb', r'cny', r'renminbi'], ['人民币']),
    (('fx',), [r'exchange rates?', r'fx'], ['汇率']),
    (('equities',), [r'stocks', r'equities', r'stock market'], ['股市', '股票']),
    (('spx', 'equities'), [r's&p 500', r's&p', r'spx', r'spy'], ['标普500', '标普']),
    (('nasdaq', 'equities'), [r'nasdaq'], ['纳斯达克', '纳指']),
    (('ashares', 'equities'), [r'a-shares', r'china stocks'], ['a股', '沪深']),
    (('property',), [r'property', r'real estate', r'housing'], ['房地产', '楼市', '地产']),
    (('earnings',), [r'earnings', r'profits'], ['盈利', '业绩', '财报']),
    (('tariffs',), [r'tariffs?', r'trade war'], ['关税', '贸易战']),
    (('exports',), [r'exports?'], ['出口']),
    (('imports',), [r'imports?'], ['进口']),
    (('consumption',), [r'consumption', r'retail sales', r'consumer spending'], ['消费', '零售']),
    (('memory', 'semis'), [r'memory', r'dram', r'nand', r'hbm'], ['存储', '内存']),
    (('semis',), [r'semiconductors?', r'chips?', r'semis'], ['半导体', '芯片']),
    (('ai',), [r'ai', r'artificial intelligence'], ['人工智能']),
    (('supply',), [r'supply'], ['供给', '供应']),
    (('demand',), [r'demand'], ['需求']),
    (('path',), [r'path', r'trajectory'], ['路径']),
    (('outlook',), [r'outlook'], ['前景', '展望']),
    (('expectations',), [r'expectations?'], ['预期']),
    (('midterms',), [r'mid-?terms?', r'midterm elections?'], ['中期选举']),
    (('election',), [r'elections?'], ['大选', '选举']),
]


def _build():
    alts, concepts = [], {}
    for cs, en, zh in _TABLE:
        for pat in en:
            alts.append((len(pat), '(?<![a-z])' + pat.replace(' ', r'[\s-]+') + '(?![a-z])', cs))
        for lit in zh:
            alts.append((len(lit) * 3, re.escape(lit).replace(' ', r'\s*'), cs))
    alts.sort(key=lambda t: -t[0])          # longest alternative first at a given position
    parts = []
    for k, (_, pat, cs) in enumerate(alts):
        parts.append(f'(?P<a{k}>{pat})')
        concepts[f'a{k}'] = cs
    return re.compile('|'.join(parts), re.I), concepts


_RX, _CONCEPTS = _build()
ALIAS_COUNT = sum(len(en) + len(zh) for _, en, zh in _TABLE)
CONCEPT_COUNT = len({c for cs, _, _ in _TABLE for c in cs})


def canonicalize(text):
    """-> (set of '@concept' tokens, list of residual text segments between alias hits)."""
    concepts, segments, last = set(), [], 0
    for m in _RX.finditer(text or ''):
        segments.append(text[last:m.start()])
        concepts.update('@' + c for c in _CONCEPTS[m.lastgroup])
        last = m.end()
    segments.append((text or '')[last:])
    return concepts, segments


# Mutually exclusive concrete entity tokens. Hierarchical parents (@crypto, @equities, @rates,
# @central_bank) are intentionally absent: only distinct primary entities veto each other.
ENTITY_FAMILIES = (
    frozenset({'fed', 'ecb', 'boj', 'boe', 'pboc'}),   # central banks
    frozenset({'btc', 'eth'}),                         # crypto majors
    frozenset({'spx', 'nasdaq', 'ashares'}),           # equity indices
    frozenset({'oil', 'gold'}),                        # commodities
)


def _bare(tokens):
    """Strip leading '@' from concept tokens; leave residual stems/bigrams alone."""
    return {t[1:] if isinstance(t, str) and t.startswith('@') else t for t in (tokens or ())}


def concrete_entities(tokens):
    """Map family -> frozenset of concrete entity tokens present in `tokens` (may be empty)."""
    bare = _bare(tokens)
    return {i: frozenset(bare & fam) for i, fam in enumerate(ENTITY_FAMILIES) if bare & fam}


def entity_conflict(tokens_a, tokens_b):
    """True when both sides name concrete entities in the same family but share none.

    Same entity (incl. ZH<->EN aliases of one concept) is fine. If either side has no concrete
    entity token in a family, that family does not veto - existing overlap behaviour stands.
    """
    a, b = _bare(tokens_a), _bare(tokens_b)
    for fam in ENTITY_FAMILIES:
        ae, be = a & fam, b & fam
        if ae and be and not (ae & be):
            return True
    return False


def entity_family_match(tokens_a, tokens_b):
    """Stricter than entity_conflict (Oct 6 v8, contradiction / revise gate): in every family where
    EITHER side names a concrete entity, the other side must name one too and share it. A Fed call
    no longer "flips" a China easing view just because both say rates (v7zh zh_macro)."""
    a, b = _bare(tokens_a), _bare(tokens_b)
    for fam in ENTITY_FAMILIES:
        ae, be = a & fam, b & fam
        if (ae or be) and not (ae & be):
            return False
    return True
