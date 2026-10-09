"""Lexical draft checks for reader advice and inconsistent numeric claims."""
import re
from decimal import Decimal
from live.numeric_fidelity import NUMBER, RANGE, quantity, MONTH_PATTERN

_SENTENCES = re.compile(r'(?<!\d)[.!?。！？;；\n]|\.(?!\d)')
_ACTION = re.compile(r'\b(?:buy|sell|short|go long|consider|add(?:ing)? exposure|recommend|should|enter|purchase)\b|买入|卖出|做多|做空|加仓|建仓|可以关注|建议', re.I)
_INSTRUMENT = re.compile(r'(?<![A-Za-z])(?!(?:OTM|ITM|DTE|USD|PMI)(?![A-Za-z]))[A-Z]{2,6}(?![A-Za-z])|\$[A-Z]{1,6}\b|\b(?:bitcoin|treasuries|stocks|shares|options|ETF|gold|oil)\b|[\u4e00-\u9fff]+\d*(?:ETF|股票)|美债|黄金|原油', 0)
_SPECIFIC = re.compile(
    r'\b(?:at|entry|strike|stop|target|limit)\b[^.;。！？]*?\d|'
    r'\d+(?:\.\d+)?\s*(?:%\s*(?:OTM|ITM)|[- ]?cent|DTE|days?\b)|'
    r'\b(?:put|call)\s+(?:fly|spread|butterfly)|'
    r'\b(?:straddle|strangle|iron condor|covered call)\b|'
    r'\d+(?:\.\d+)?(?:点|元|万)|(?:止损|目标价|入场|行权价)[^。！？]*?\d|价差|蝶式|跨式', re.I)

_ATTRIBUTION = re.compile(r'^\s*(?:(?:according to\b|据|根据).*|[\w\s&.-]+\b(?:recommends?|recommended|says?|said|advises?)\b|[\u4e00-\u9fff]+(?:建议|推荐|表示|称))', re.I)


def trade_reco_findings(body, lang):
    findings = []
    for sentence in _SENTENCES.split(body):
        if not _ACTION.search(sentence) or _ATTRIBUTION.search(sentence):
            continue
        instruments = list(_INSTRUMENT.finditer(sentence))
        if not instruments:
            continue
        if not re.search(r'^\s*(?:buy|sell|short|go long|consider|add|enter|purchase)\b|\byou should\b|\btime to (?:buy|sell)\b|买入|卖出|做多|做空|可以关注|建议', sentence, re.I):
            continue
        specifics = sentence
        for instrument in reversed(instruments):
            specifics = specifics[:instrument.start()] + ' ' + specifics[instrument.end():]
        specific = instruments and _SPECIFIC.search(specifics)
        findings.append({'code': 'trade_reco_specific' if specific else 'trade_reco_soft',
                         'detail': sentence.strip()})
    return findings


_COMPARE = re.compile(r'\b(?:from|to|through|vs\.?|versus|compared with|compared to|previous|prior|year.over.year|month.over.month)\b|从|升至|降至|前值|同比|环比|相比', re.I)
_MOVEMENT = re.compile(r'\b(?:rose|rise|rising|fell|fall|falling|added|shed|built|unwound|before|after|then)\b|上升|下降|随后', re.I)
_TIME = re.compile(r'\b(?:Q[1-4]|H[12]|20\d{2}|'+MONTH_PATTERN+r'|today|yesterday|last|current|previous)\b|\d+年|\d+月|本季|上季|去年|今年', re.I)


def _phrase(text):
    text = re.sub(r'\b(?:of|at|is|was|were|the|a|an|stands?|stood|equals?)\b|为|达到|约|是', ' ', text, flags=re.I)
    words = re.findall(r'[a-z]+|[\u4e00-\u9fff]+', text.casefold())
    return ' '.join(words[-4:])


def contradiction_findings(body):
    """Compare repeated local metric phrases, retaining units and time anchors.

    Comparison/change sentences and ranges are excluded rather than interpreted
    as simultaneous observations. Unrecognised subjects use adjacent noun words.
    """
    seen = {}; findings = []
    for sentence in _SENTENCES.split(body):
        if _COMPARE.search(sentence) or RANGE.search(sentence) or _MOVEMENT.search(sentence):
            continue
        time = tuple(m.group().casefold() for m in _TIME.finditer(sentence))
        matches = list(NUMBER.finditer(sentence))
        for i, match in enumerate(matches):
            # Dates are anchors, not metric values ('2026年9月', '7月', '15日', 'in 2026').
            if re.match(r'\s*(?:年|月|日|号)', sentence[match.end():]) or re.fullmatch(r'(?:19|20)\d{2}', match.group().strip()):
                continue
            before = sentence[matches[i-1].end() if i else 0:match.start()]
            after = sentence[match.end():matches[i+1].start() if i+1 < len(matches) else len(sentence)]
            # Strip period anchors before extracting the adjacent subject.
            before = _TIME.sub('', before)
            after = _TIME.sub('', after)
            phrase = _phrase(before) or _phrase(after)
            if not phrase:
                continue
            q = quantity(match['n'], match['s'], match['u'], match['c'])
            key = (phrase, q[1], time)
            value = Decimal(q[0])
            if key in seen:
                old = seen[key]
                denominator = max(abs(old), abs(value))
                if denominator and abs(old-value) / denominator > Decimal('0.005'):
                    findings.append({'code': 'self_contradiction', 'detail': {'metric': phrase,
                                     'values': [str(old), str(value)], 'unit': q[1]}})
            else:
                seen[key] = value
    return findings


def stale_time_findings(body, units, now=None, lang=None):
    """Conservative clause-local date/number binding for supplied cited units."""
    from live import freshness
    from datetime import date
    stale = [u for u in units if freshness.status(u, now)['status'] in ('stale', 'expired')]
    findings = []
    if stale and re.search(r"\b(?:today(?:'s)?|this week|just|latest)\b|今天|今日|本周|刚刚|最新|昨日", body, re.I):
        findings.append({'code': 'stale_time_word', 'detail': 'Current-time wording cites aged material'})
    clauses = re.split(r'[。！？!?;；\n]|\.(?:\s|$)', body)
    def number_in(clause, unit):
        unit=unit.get('unit',unit)
        values=[]
        for n in unit.get('numbers',[]):
            values += re.findall(r'\d[\d,]*(?:\.\d+)?',str(n.get('text') or ''))
        return any(re.search(r'(?<!\d)'+re.escape(v)+r'(?!\d)',clause) for v in values)
    date_pattern = r'\d{4}-\d{2}-\d{2}|(?:\d{4}年)?\d{1,2}月\d{1,2}日|\b(?:'+freshness.MONTH_PATTERN+r')\.?\s+\d{1,2}(?:,?\s+\d{4})?\b'
    for clause in clauses:
        if re.search(r'\b(?:now|currently|current)\b|目前|当前|现在',clause,re.I) and any(number_in(clause,u) for u in stale):
            if not any(f['code']=='stale_number_as_current' for f in findings):
                findings.append({'code':'stale_number_as_current','detail':clause.strip()})
        dates = re.findall(date_pattern, clause, re.I)
        event_text = re.sub(date_pattern, '', clause, flags=re.I).casefold()
        bound = []
        for row in units:
            unit = row.get('unit', row)
            statement = str(unit.get('statement') or '').strip().rstrip('.。!?！？').casefold()
            if number_in(event_text, row) or (len(statement) >= 12 and statement in event_text):
                bound.append(row)
        for stated in dates:
            comparisons=[]
            for row in bound:
                u=row.get('unit',row)
                derived=u if 'as_of' in u else freshness.derive_dates(row)
                # Normalise every candidate to YYYY-MM-DD: raw values may be ISO datetimes ending in 'Z'.
                raw=(derived.get('as_of'),u.get('published_at_norm'),u.get('published_at'),derived.get('published_at'))
                known=list(dict.fromkeys(d for d in (freshness.normalize_date(str(v)) if v else None for v in raw) if d))
                if not known: continue
                year=int(known[0][:4])
                text=stated
                if re.match(r'[A-Za-z]',text) and not re.search(r'\d{4}',text): text+=f', {year}'
                parsed=freshness.parse_period(text,year)
                if parsed:
                    comparisons.append(any(abs((date.fromisoformat(parsed)-date.fromisoformat(k)).days)<=1 for k in known))
            if comparisons and not any(comparisons):
                findings.append({'code':'wrong_date_fact','detail':clause.strip()})
    return findings


# ---------------------------------------------------------------- first-glance readability (Oct 7, polish)
# A general crypto / finance X reader must get the post on first read: no statute sections, rule codes, internal
# pipeline jargon or insider acronyms unless the same post says what they mean in plain words.

_LEGAL_SECTION = re.compile(
    r'\b(?:Section|Sec\.|Article|Art\.|Title|Rule|Regulation|Reg\.?)\s*\d+[A-Za-z]?(?:[-.]\d+[A-Za-z]?)*(?:\([0-9A-Za-z]{1,4}\))+|'
    r'§+\s*\d[\w.\-()]*|'
    r'(?<![\w(])\d+[A-Za-z]?(?:\([0-9A-Za-z]{1,4}\)){2,}|'          # bare 2(c)(2)(D)
    r'第\s*\d+[A-Za-z]?(?:\([0-9A-Za-z]{1,4}\))*\s*[条款项节章]', re.I)
_STATUTE_CODE = re.compile(
    r'\b\d+\s*(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\s*§*\s*\d*|'
    # the letter code is case-sensitive (Oct 7: "an old retail-leverage rule to ..." matched as "rule to")
    r'\b(?:Rule|Reg(?:ulation)?\.?)\s+(?:\d+[a-z]?-\d+[a-z]?|(?-i:[A-Z]{1,4}(?:-[A-Z0-9]+)?)|\d{2,4}[a-z]?)\b|'
    r'\b(?:SAB|ASC|ASU|IFRS|FAS|SFAS|FASB\s+ASC)\s*\d+(?:-\d+)*\b|'
    r'\bForm\s+(?:\d+-[A-Z]+|[A-Z]-\d+|N-\w+|ADV|13[DFG])\b|'
    r'\b(?:H\.\s?R\.|S\.)\s?\d{2,5}\b|'
    r'\bMiCA\s+Art(?:icle|\.)?\s*\d+|'
    r'\b(?:Basel\s+)?SCO\s?\d+\b', re.I)
# snake_case / pipeline vocabulary that must never reach a public post
_INTERNAL_JARGON = re.compile(
    r'\b[a-z]+(?:_[a-z0-9]+)+\b|'
    r'\b(?:thesis[ _]lock|post[ _]type|claim ledger|span[ _]ref|judgment[ _]take|quote[ _]comment|donor|'
    r'content unit|stance card|beat gate)\b|'
    r'论点锁|判断卡|素材单元|稿型', re.I)
# Acronyms a general crypto / finance X reader knows (plus common tickers / chains / venues). Anything else in caps
# needs a plain-words gloss in the same post.
KNOWN_ACRONYMS = frozenset('''
AI API APY APR ATH ATL AUM BTC ETH SOL XRP BNB USD USDT USDC DAI EUR GBP JPY CNY RMB HKD
ETF ETFs SEC CFTC FED FOMC CPI PPI PCE GDP PMI ISM NFP IPO IPOs CEO CFO CTO COO EPS PE ROE ROI YOY YoY QOQ
US USA UK EU UN IMF ECB BOJ BOE PBOC PBoC OPEC G7 G20 NYSE NASDAQ S&P SPX SPY QQQ DXY VIX OTC KYC AML
DEFI DeFi NFT NFTs DEX CEX DAO TVL L1 L2 L1s L2s EVM ZK DAT DATs RWA RWAs MEV LP LPs OI PnL P&L
FX QE QT HBM DRAM NAND GPU GPUs CPU CPUs TPU ASIC AWS TSMC NVDA AAPL MSFT TSLA AMZN META GOOGL AMD INTC AVGO MU
CN HK JP TW SG FTX OKX MSTR COIN IBIT GBTC LLM LLMs ARR SaaS M&A IRS DOJ FDIC OCC FBI GPT AGI EV EVs
AI PC Q1 Q2 Q3 Q4 H1 H2 FY OK CEOs VC VCs ATM YTD MTD WTI LNG CPI PCE OPEX CAPEX CapEx FCF EBITDA
TradFi CeFi BTCFi DeFi APAC EMEA PM PMs IR X TGE ICO ICOs IDO AMA FUD FOMO HODL DCA ETH2
H100 H200 B200 GB200 5G 3D
'''.split())
# Oct 8: chain / token / company names written in capitals are names, not insider acronyms ("TRON" held 4 crypto drafts
# on 10-08 and 9 hard-repair rounds that week; STG, HYPE too). Coins / stocks of live/charts.py plus widely traded
# tickers; a ticker outside this list still needs a gloss.
KNOWN_NAMES = frozenset('''
TRON TRX SUI APT TON HYPE ARB OP AVAX LINK DOT ADA ATOM NEAR TIA PEPE WIF BONK PUMP ENA ONDO JUP STX KAS FIL LTC BCH
ETC UNI AAVE MKR LDO CRV PENDLE EIGEN ZRO STG SEI INJ RUNE WLD TAO RNDR RENDER FET GRT IMX MATIC POL SHIB DOGE USDE
FDUSD PYUSD RLUSD BUIDL HBAR XLM ALGO ICP OKB BGB GMX DYDX SNX ETHFI MORPHO SKY BERA MNT BASE
'''.split())


def _known_name(word):
    w = word.rstrip('s') if word.endswith('s') and len(word) > 3 else word
    if w.upper() in KNOWN_NAMES:
        return True
    try:
        from live import charts
    except Exception:   # noqa: BLE001
        return False
    names = {k.upper() for k in charts.CRYPTO} | {n.upper() for v in charts.CRYPTO.values() for n in v[0]}
    names |= {k.upper() for k in charts.STOCKS} | {v[0].upper() for v in charts.STOCKS.values()}
    names |= {n.upper() for v in charts.STOCKS.values() for n in v[1]}
    return w.upper() in names


_ACRONYM = re.compile(r'(?<![A-Za-z0-9_$#@.])(?:[A-Z][A-Z0-9]{1,5}s?|[A-Z][a-z]?[A-Z]{1,4})(?![A-Za-z0-9_])')   # ASCII edges: 的T3部门
# Oct 9 night (HOLD review): a capitalised name followed by what it is - "SK Group", "QFEX perp venue", "XYZ Labs",
# "ABC 交易所" - is a name the reader can place, not insider jargon (10-09: #19 SK Group, #33 QFEX held).
_NAME_AFTER = re.compile(r'\s*(?:Group|Holdings?|Hynix|Inc\.?|Corp\.?|Co\.|Ltd\.?|Labs?|Capital|Bank|Securities|Telecom|'
                         r'Energy|Motors?|Electronics|Pharma|Technologies|Systems|Partners|Ventures|Research|Foundation|'
                         r'Protocol|Network|Finance|Exchange|Markets?|'
                         r'(?:perp(?:etual)?s?\s+)?(?:venue|exchange|DEX|protocol|platform|chain|L1|L2|app|wallet|token|coin|'
                         r'stablecoin|project|fund|ETF|stock|shares|index|lender|bridge|rollup|network|marketplace)s?)\b'
                         r'|\s*(?:交易所|协议|公司|集团|平台|项目|公链|代币|基金|钱包|指数|银行|证券)')
_GLOSS_AFTER = re.compile(r'\s*[（(][^)）]{2,}[)）]|\s*(?:—|-|,|，|：|:)?\s*(?:i\.e\.|meaning|which is|也就是|即|就是)')


def readability_findings(body, lang=None):
    """HARD first-glance readability: legal section numbers, statute / rule codes, internal jargon and insider
    acronyms without a plain-words gloss in the same post. One finding per kind, detail lists the hits."""
    text = str(body or '')
    hits = []
    hits += [m.group(0).strip() for m in _LEGAL_SECTION.finditer(text)]
    hits += [m.group(0).strip() for m in _STATUTE_CODE.finditer(text)]
    hits += [m.group(0).strip() for m in _INTERNAL_JARGON.finditer(text)]
    for m in _ACRONYM.finditer(text):
        word = m.group(0)
        if (not re.search(r'[A-Z].*[A-Z]|[A-Z]\d', word) or word in KNOWN_ACRONYMS
                or word.upper() in KNOWN_ACRONYMS or word.rstrip('s') in KNOWN_ACRONYMS or _known_name(word)):
            continue
        if any(word in h for h in hits):          # already reported inside a rule / statute code
            continue
        if _GLOSS_AFTER.match(text, m.end()) or _NAME_AFTER.match(text, m.end()):
            continue
        if not text[:m.start()].strip() and text[m.end():m.end() + 1] == ':':   # 'RPM: ...' stock headline ticker
            continue
        before = text[max(0, m.start() - 2):m.start()]
        if before.endswith(('(', '（')):        # "Digital Asset Treasury (DAT)": the full name precedes it
            continue
        hits.append(word)
    hits = list(dict.fromkeys(h for h in hits if h))
    return [{'code': 'jargon_unexplained', 'detail': ' | '.join(hits)}] if hits else []
