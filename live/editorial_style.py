"""Deterministic editorial-style checks (Oct 7, fix26; ported from Sirius x-account-operator).

Source: Sirius `deterministic_editorial_style_failures()` / `unauthorized_first_person_experience()` (app.py,
HEAD 7a16acf) plus Fiona's Oct 7 review of the 26 fd20 drafts. Every code rides compose's one targeted rewrite.
HARD_CODES still HOLD a draft that trips them after the rewrite; SOFT_CODES are warnings only (Oct 7 relax: Fiona
found the review too strict - mild research tone, the 50-char single-call cap, a question line and mild emphasis
are style, not a reason to hold; 阿粥 「暴力撸毛这种老叙事早就凉透了…最后还能剩下谁？」 is publishable).

Codes (HARD):
  editorial_cliche       ZH AI-template / translationese openers (本质上 / 值得注意的是 / 其实这就是 / 很显然 /
                         我觉得症结在于 / 不是X而是Y …) and Sirius' empty waiting lines (继续观察 / 有待观察 …)
  fabricated_experience  first-person trading / usage experience the account never had (我买了 / 我的账户 /
                         I bought / my position …)
  en_cliche              EN opener / ending clichés (Here's the thing / Let that sink in / Stay tuned / NFA …)
  trade_imperative       EN imperative telling the reader to trade (Buy the dip / Load up / Take profits …)
  jargon_unexplained     first-glance readability (live/draft_qa.readability_findings): legal section numbers
                         (Section 2(c)(2)(D)), statute / rule codes, internal jargon, insider acronyms without a
                         plain-words gloss (Oct 7 polish: Juno / Basil CFTC posts)
Codes (SOFT, warning only):
  rhetorical_opener      ZH 难道…？ / a first sentence that is a question
  overclaim              absolute certainty the sources cannot carry (基本被锁死 / 板上钉钉 / done deal …)
  research_tone          ZH research-note cadence: median sentence > 30 CJK chars (2+ sentences) or one sentence > 50
                         (Arlo). A single-sentence call only trips the 50 cap.
Misquotes, numbers that do not match the source and cross-account duplicates are judged elsewhere (QA, arbitration,
the human audit), not here.
"""
from __future__ import annotations

import re

VERSION = 'editorial-style-v5'   # v2: one-sentence calls only trip the 50-char cap; v3: ZH question opener,
                                 # ZH trade imperatives, 我一直坚持 track record; v4: jargon_unexplained;
                                 # v5: rhetorical_opener / overclaim / research_tone are SOFT warnings
HARD_CODES = ('editorial_cliche', 'fabricated_experience', 'en_cliche', 'trade_imperative', 'jargon_unexplained')
SOFT_CODES = ('rhetorical_opener', 'overclaim', 'research_tone')
CODES = HARD_CODES + SOFT_CODES
# ZH sentence caps for research_tone (CJK chars). zh_register.sentence_findings stays the SOFT 28 / 50 nudge.
ZH_MEDIAN_MAX, ZH_SENTENCE_MAX = 30, 50

# Sirius EMPTY_WAITING_PHRASES (verbatim)
EMPTY_WAITING_PHRASES = ('继续观察', '等后续材料', '等待更多信息', '等更多信息', '再看正式文本', '等正式文本', '再看后续',
                         '后续再看', '在那之前', '有待观察', '值得继续观察', '下一观察点', '还没有形成独立的交易条件',
                         '尚未形成独立的交易条件', '还没有形成可执行条件', '尚未形成可执行条件', '我会关注', '我会持续关注')
# Sirius boilerplate tuple (verbatim) + Fiona Oct 7
ZH_BOILERPLATE = ('结论很明确', '我的结论很简单', '我的结论很直白', '本质上', '值得注意的是', '核心逻辑', '一方面', '另一方面',
                  '显而易见', '大家都知道',
                  '其实这就是', '这其实就是', '很显然', '我觉得症结在于', '症结在于', '不难看出', '毋庸置疑', '众所周知',
                  '归根结底', '说到底')
ZH_NOT_BUT = re.compile(r'不是[^。！？!?\n]{1,30}?而是')
ZH_RHETORICAL = re.compile(r'难道[^。！？!?\n]{0,40}[？?]')
# fix26 follow-up: any ZH post whose first sentence is a question (就因为跌了一下…就断了？ / 换成稳定币就能搞定IMF？)
ZH_FIRST_QUESTION = re.compile(r'^[^。！!\n]{2,60}[？?]')
# ZH reader instructions to trade (少在短线里来回折腾 / 不如耐住性子 / 赶紧上车)
ZH_IMPERATIVE = re.compile(r'(?:别|不要|少|千万别|切忌)(?:在[^，。！？\n]{0,8})?(?:追高|追涨|抄底|割肉|来回折腾|折腾|接盘|满仓|梭哈|上车|下车|乱操作)|'
                           r'不如耐住性子|赶紧(?:上车|买|卖|跑|抄底)|(?:该|可以)(?:上车|抄底|加仓|减仓)了')
ZH_OVERCLAIM = re.compile(r'(?:基本|已经|已|彻底|完全)上?(?:被)?锁死|'
                          r'死死(?:压|按|卡|摁)|板上钉钉|毫无悬念|毫无疑问|注定|必然会|百分之百|稳赚|只是多头的幻觉')
EN_OVERCLAIM = re.compile(r"\b(?:done deal|guaranteed|no doubt about it|without a doubt|inevitabl[ey]|"
                          r"can(?:not|'t) (?:possibly )?fail|100% (?:sure|certain))\b", re.I)

# Sirius SAFE_FIRST_PERSON_OPINION_LEADS + UNAUTHORIZED_FIRST_PERSON_EXPERIENCE_RE (verbatim) + EN equivalent
SAFE_FIRST_PERSON_OPINION_LEADS = ('我认为', '我觉得', '我的判断是', '我的判断', '我的理解是', '我的理解', '我倾向于', '我倾向',
                                   '我更关心', '在我看来')
ZH_FIRST_PERSON_EXPERIENCE = re.compile(
    r'(?:我|本人)(?:上周|上个月|昨天|今天|最近|今年|这个月|一直|已经|刚|曾|现在|目前)?'
    r'(?:抄底|买了|买入|卖了|卖出|做空|做多|持有|赚了|亏了)|'
    r'(?:我|本人)(?:的)?(?:账户|手里)|'
    r'(?:我|本人)[，、 ]?(?:用|使用|在用).{0,12}(?:天|周|月|年)|'
    r'(?:我|本人)[一-龥，、 ]{0,5}(?:跑单|开车|上班|任职|见过|参与(?:了)?|试(?:了)?|实测|跑(?:了)?)|'
    r'我们(?:之前|多次|一直|早就|上个月|1个月前|一个月前)(?:就)?(?:说|提醒|喊|提示)|'
    r'(?:我|本人)(?:一直|早就|之前|多次)(?:都)?(?:坚持|说|强调|提醒|喊|看好|看空|提示)|'   # fix26: invented track record
    r'(?:我|我们)的(?:直播|仓位|持仓|组合|单子)')
EN_FIRST_PERSON_EXPERIENCE = re.compile(
    r"\b(?:I|we)(?:'ve| have)?(?: just| already| recently| finally)? (?:bought|sold|shorted|longed|went long|went short|"
    r"aped|loaded up|added to|trimmed|took profits?|closed my|opened (?:a|my)|got liquidated|"
    r"(?:am|are|'m|'re) (?:long|short|holding|buying|selling))\b|"
    r"\bmy (?:position|positions|portfolio|bags?|stack|account|longs?|shorts?|entry|book)\b|"
    r"\b(?:I|we) (?:told you|called (?:it|this))\b", re.I)

EN_OPENER = re.compile(r"^\s*(?:here's the thing|here is the thing|let's talk about|let me be clear|hot take|"
                       r"unpopular opinion|make no mistake|plot twist|buckle up|breaking|the truth is|"
                       r"here's why|here is why|let that sink in|in today's market|ladies and gentlemen|"
                       r"it's no secret|you won't believe)\b", re.I)
EN_ENDING = re.compile(r"(?:stay tuned|buckle up|let that sink in|time will tell|only time will tell|\bdyor\b|\bnfa\b|"
                       r"not financial advice|thoughts\?|what do you think\?|carry on|you've been warned|"
                       r"watch this space|the rest is history|mark my words)[\s.!?)\]]*$", re.I)
# EN "This isn't just X. It's Y" contrast template (Weekly Tape, Oct 7)
EN_NOT_JUST = re.compile(r"\b(?:is|isn't|is not|it's not|this isn't)\s+(?:just|only|merely)\b[^.!?\n]{0,80}[.;:—-]+\s*"
                         r"(?:it's|it is|this is)\b", re.I)
EN_IMPERATIVE = re.compile(r"(?:^|(?<=[.!?\n]))\s*(?:buy|sell|go long|go short|load up|stack|accumulate|take profits?|trim|"
                           r"add (?:more|exposure|to)|get out|stay (?:long|short)|ape|fade|"
                           r"don'?t (?:buy|sell|chase|short|fade|panic sell)|do not (?:buy|sell|chase|short))"
                           r"\b(?![-'])(?! (?:side|signal|pressure|order|wall|volume|-side)s?\b)", re.I | re.M)


def _sentences(body):
    return [s.strip() for s in re.split(r'(?<=[。！？!?\n])', body) if s.strip()]


def hard(found):
    """The findings among `found` that still HOLD a draft (HARD_CODES)."""
    return [f for f in found if f.get('code') in HARD_CODES]


def findings(body, lang, *, first_person_allowed=False, post_format=None):
    """Style findings (HARD and SOFT codes, see hard()) for a draft body. `lang` is the account language
    ('zh' / 'en'); post_format 'question' may open on its question."""
    text = str(body or '').strip()
    if not text:
        return []
    out = []
    zh = lang == 'zh'
    if zh:
        hits = [p for p in EMPTY_WAITING_PHRASES + ZH_BOILERPLATE if p in text]
        hits += [m.group(0) for m in ZH_NOT_BUT.finditer(text)]
        if hits:
            out.append({'code': 'editorial_cliche', 'detail': '、'.join(dict.fromkeys(hits))})
        m = ZH_RHETORICAL.search(text) or (post_format != 'question' and ZH_FIRST_QUESTION.search(text))
        if m:
            out.append({'code': 'rhetorical_opener', 'detail': m.group(0)})
        imps = [m.group(0) for m in ZH_IMPERATIVE.finditer(text)]
        if imps:
            out.append({'code': 'trade_imperative', 'detail': '、'.join(dict.fromkeys(imps))})
        over = [m.group(0) for m in ZH_OVERCLAIM.finditer(text)]
    else:
        over = []
        first = _sentences(text)[0] if _sentences(text) else ''
        last = text.rstrip().splitlines()[-1] if text.strip() else ''
        hits = [m.group(0).strip() for m in (EN_OPENER.search(first), EN_ENDING.search(last), EN_NOT_JUST.search(text))
                if m]
        if hits:
            out.append({'code': 'en_cliche', 'detail': ' | '.join(hits)})
        imps = [m.group(0).strip() for m in EN_IMPERATIVE.finditer(text)]
        if imps:
            out.append({'code': 'trade_imperative', 'detail': ' | '.join(dict.fromkeys(imps))})
    over += [m.group(0) for m in EN_OVERCLAIM.finditer(text)]
    if over:
        out.append({'code': 'overclaim', 'detail': '、'.join(dict.fromkeys(over))})
    if zh:
        from live.zh_register import sentence_lengths
        lens = sorted(sentence_lengths(text))
        # a one-sentence call (one_liner) is only held past ZH_SENTENCE_MAX: its commas are its clauses
        if lens and ((len(lens) >= 2 and lens[len(lens) // 2] > ZH_MEDIAN_MAX) or lens[-1] > ZH_SENTENCE_MAX):
            out.append({'code': 'research_tone',
                        'detail': f'句长中位数 {lens[len(lens) // 2]} 字，最长 {lens[-1]} 字（上限 {ZH_MEDIAN_MAX} / {ZH_SENTENCE_MAX}）'})
    if not first_person_allowed:
        remaining = text
        for phrase in SAFE_FIRST_PERSON_OPINION_LEADS:
            remaining = remaining.replace(phrase, '')
        m = ZH_FIRST_PERSON_EXPERIENCE.search(remaining) or EN_FIRST_PERSON_EXPERIENCE.search(remaining)
        if m:
            out.append({'code': 'fabricated_experience', 'detail': m.group(0)})
    from live.draft_qa import readability_findings
    out += readability_findings(text, lang)
    return out


FIXES = {
    'editorial_cliche': ('删掉这些 AI 套话/翻译腔（本质上 / 值得注意的是 / 其实这就是 / 很显然 / 我觉得症结在于 / 不是X而是Y / '
                         '继续观察 …），直接说判断：判断一句 + 一句为什么 + 一句意味着什么，短句。'),
    'rhetorical_opener': '不要用问句开头（难道…？ / …就断了？），第一句直接说判断。',
    'overclaim': ('把绝对化的说法（基本被锁死 / 板上钉钉 / 注定 / done deal …）改成材料撑得住的力度：说清条件或可能性，'
                  '不要宣布结局。'),
    'fabricated_experience': ('删掉本账号没有过的第一人称经历/持仓/操作（我买了 / 我的账户 / 我们之前就说 / I bought / my position）；'
                              '判断可以用「我觉得」，经历不能编。源作者的经历用第三人称转述或不写。'),
    'en_cliche': ('Drop the opener / ending cliché (Here\'s the thing / Let that sink in / Stay tuned / Time will tell / '
                  'NFA …): open on the call, end on a concrete consequence.'),
    'research_tone': ('研报腔太重：拆成短句，每句一个意思（中位数 ≤30 字，单句 ≤50 字）；判断一句 + 一句为什么 + 一句意味着什么，'
                      '删掉铺垫和第二层论证。'),
    'jargon_unexplained': ('First-glance readability: replace the codes / jargon in the detail with what they mean in plain '
                           'words a general crypto / finance reader gets at once (Section 2(c)(2)(D) -> "an old '
                           'retail-leverage rule"; Tether 的 T3 部门 -> Tether 的冻结执法团队). No statute or rule numbers; '
                           'an uncommon acronym only with a short gloss. 用大白话说清楚是什么，不写法条编号和圈内缩写。'),
    'trade_imperative': ('No trading imperatives to the reader (Buy / Sell / Load up / Take profits / Don\'t chase / '
                         '少折腾 / 别追高 / 赶紧上车 …): state the view and what it implies, not an order.'),
}


# compose prompt block: the same list the HARD checks enforce, so the first pass avoids most of them
PROMPT_RULE = (
    'Editorial style (checked in code; the "never" items below hold a draft that still trips one after one rewrite, '
    'the "prefer" items are warnings): '
    'ZH posts = the judgment, one line of why, one line of what it means; prefer short sentences (median <= 30 '
    'chars, none > 50); crypto accounts may sound emotional, macro / industry / long-term accounts stay restrained. '
    'Prefer opening on the call, not a question (难道…？ / …就断了？). '
    'Never tell the reader to trade (少折腾 / 别追高 / 不如耐住性子 / 赶紧上车) or claim a track record (我一直坚持 / 我早就说). '
    'Never write: ' + ' / '.join(ZH_BOILERPLATE) + ' / 不是X而是Y / 难道…？ / '
    + ' / '.join(EMPTY_WAITING_PHRASES[:4]) + '. Prefer no absolute certainty the units cannot carry (基本被锁死 / '
    '死死压住 / 板上钉钉 / 注定 / done deal / guaranteed): say the condition or the odds. No first-person experience, holdings, '
    'trades or usage (我买了 / 我的仓位 / 我们之前就说 / I bought / my position / I told you). EN: no opener or '
    "ending clichés (Here's the thing / Let that sink in / Stay tuned / Time will tell / NFA / Thoughts?), no "
    '"This isn\'t just X. It\'s Y", no imperatives telling the reader to trade (Buy / Sell / Load up / Take profits '
    "/ Don't chase). First-glance readability: no legal section numbers (Section 2(c)(2)(D)), statute or rule codes "
    '(Rule 10b-5 / SAB 121), internal jargon or insider acronyms (T3, PMF) unless glossed in plain words; say what the '
    'rule does ("an old retail-leverage rule" / 一条管散户杠杆交易的老规定).')


# ---------------------------------------------------------------- beat gate (account <-> crypto content)

# Generic words (token = LLM tokens, wallet = Alipay) are left out: AI / payments packets must reach non-crypto accounts.
CRYPTO_CONTENT = re.compile(
    r'bitcoin|\bbtc\b|ethereum|\beth\b|crypto|stablecoin|\bsol\b|solana|altcoin|memecoin|blockchain|\bdefi\b|'
    r'airdrop|on-?chain|\bperps?\b|hyperliquid|pump\.fun|\btvl\b|\bdex\b|web3|\bl[12]s?\b|layer[- ]?2|rollup|'
    r'staking|\blido\b|tether|\busdt\b|\busdc\b|\bnfts?\b|\btge\b|tokenomics|token (?:unlock|launch|sale)|\bdao\b|'
    r'比特币|以太坊|加密|稳定币|代币|币圈|币价|山寨|主流币|公链|链上|空投|土狗|meme币|质押|撸毛|上币|'
    r'二层|L2|铭文|合约地址|币安|OKX|欧易|'
    # Oct 8: prediction-market accounts (Polymarket settles on-chain in USDC; Kalshi is their direct comparison)
    r'polymarket|kalshi|预测市场', re.I)
# crypto content routed from a source that is mainly about something else (a bank note that mentions bitcoin once)
CRYPTO_ONLY_MIN_HITS = 2
MACRO_CONTENT = re.compile(r'\bfed\b|fomc|yield|treasur|rates?\b|inflation|cpi|payroll|liquidity|dollar|\bdxy\b|'
                           r'美联储|美债|收益率|利率|通胀|非农|流动性|美元|降息|加息', re.I)
# crypto accounts that also cover macro (rates / liquidity) without a crypto keyword in the packet
CRYPTO_MACRO_OK = frozenset({'crypto_macro_zh', 'crypto_macro_en', 'crypto_btc_cycle_zh', 'btc_cycles_en'})
# Oct 8: crypto accounts whose row says ai_crossover (Tango 探戈: AI x crypto x US stocks) also get AI packets
AI_CONTENT = re.compile(r'\bAI\b|人工智能|大模型|算力|\bLLMs?\b|openai|anthropic|nvidia|英伟达|\bGPUs?\b|data ?cent(?:er|re)|'
                        r'数据中心|ai agents?|智能体', re.I)


def is_crypto_account(account):
    """account: an fd20_accounts.json row. Crypto accounts carry a crypto_* retrieval beat."""
    return any(str(b).startswith('crypto_') for b in account.get('retrieval_beats') or ())


def crypto_hits(text):
    return len(CRYPTO_CONTENT.findall(str(text or '')))


def beat_gate(account, text):
    """(ok, reason) for routing a packet whose text is `text` to `account` (Fiona Oct 7: Momo 美股札记 wrote GenLayer).
    Non-crypto accounts never get crypto-only packets; crypto accounts get crypto packets, macro crypto accounts
    also get rates / liquidity packets."""
    hits = crypto_hits(text)
    if is_crypto_account(account):
        if hits:
            return True, 'crypto'
        if account['id'] in CRYPTO_MACRO_OK and MACRO_CONTENT.search(str(text or '')):
            return True, 'macro_for_crypto_macro'
        if account.get('ai_crossover') and AI_CONTENT.search(str(text or '')):
            return True, 'ai_for_crossover'
        return False, 'off_beat: crypto account, packet has no crypto content'
    if hits >= CRYPTO_ONLY_MIN_HITS:
        return False, f'off_beat: non-crypto account, crypto packet ({hits} crypto terms)'
    return True, 'non_crypto'
