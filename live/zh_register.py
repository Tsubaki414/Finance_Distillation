"""ZH register: keep Chinese drafts in the donors' spoken register, not 研报腔 (Oct 6 v5).

Root cause (measured v2-v4b, /workspace/x/ledger_p1_oct6/REPORT.md v5 section): ZH drafts used
formal research connectives (意味着 / 而非 / 以…为主 / 基准路径 / 结构性 / 实质性 / 显然 / 注定 /
生存空间 ...) at ~20-28 per 1k CJK chars vs ~1.5-1.7 in the ZH donor corpus, with fewer colloquial
markers. The pressure came from (1) thesis_lock: the stance account_view is written from research
units in research prose (39-45 CJK chars per sentence, 19-33 formal hits / 1k, zero colloquial
markers) and line 1 restates it; (2) English-only COMPOSE instructions plus research-prose units that
the model paraphrases sentence by sentence; (3) the only ZH style signal on judgment posts was
synthetic 'restraint' shapes (handle overnight_clean), not real donor lines.

This module supplies: a Chinese system addendum for ZH composes, real short donor lines as rotating
register anchors (never invented; read from live/donors/posts), a soft `zh_register` check
(research-connective density / AI template phrases / very long sentences) and a soft
`market_feeling` check (很多人认为 / 市场普遍认为 / 大家都觉得 ...). Both feed the one structure
regeneration in compose; neither ever hard-blocks.
"""
from __future__ import annotations

import random
import re
from hashlib import sha256

CJK = re.compile(r'[\u4e00-\u9fff]')
# Research-note register (研报腔). Content nouns that donors also use as plain words (溢价, 驱动 ...)
# are measured in reports but not flagged here.
FORMAL = ('意味着', '而非', r'以[^，。；！？\n]{1,8}为主', '基准路径', '基准情形', '结构性', '实质性', '显然', '注定',
          '生存空间', '从而', '进而', '由此可见', '鉴于', '与此同时', '本质上', '不容忽视', '值得注意的是', '显著',
          '层面', '叠加', '无疑', '势必', '难以为继', '备用选项', '定价(?:显然)?(?:不够|并不)?充分', '充分(?:定价|反映)',
          '削弱', '重构', '版图', '格局', '极端的', '估值溢价', '承压', '演绎', '共振', '核心变量', '关键变量')
# v7: 核心变量 came from the stance (thesis_lock) into the v6 zh_industry body.
# v5 live: 极端的 / 重构 / 版图 / 充分定价 slipped through (donor rate <= 0.06 per 1k CJK chars each).
FORMAL_RX = re.compile('|'.join(FORMAL))
# AI template phrasing Fiona flags (on top of the generic template_phrase list).
AI_TEMPLATE = re.compile(r'听起来(?:很|非常|十分)?(?:完美|合理|美好|有道理)|看似合理|不难发现|不可否认|归根结底|'
                         r'不是[^，。；！？\n]{1,14}[，,]\s*而是|与其说[^，。；！？\n]{1,14}不如说|死死[^，。；！？\n]{0,4}压')
# Market / crowd feeling attribution (ZH rule: commit your own call, never narrate what others feel).
MARKET_FEELING = re.compile(
    r'(?:很多人|不少人|多数人|大多数人|大部分人|一般人|散户们?|投资者们?|市场上?普遍|市场(?:都|一致)|大家(?:都)?|普遍|主流观点|'
    r'各方|人们)(?:都|也|还|据此|因此|纷纷|一度|仍然|已经)?(?:在)?(?:认为|觉得|以为|担心|相信|期待|预期|押注|在赌|看好|看空|默认|共识)')
# v8: crowd attention / action narration with a people subject (v7_zi 「大家都在盯着需求端那张诱人的大饼」).
# Flows (市场 / 资金 / 机构) are left out - those can carry unit evidence.
CROWD_ACTION = re.compile(r'(?:大家|所有人|很多人|不少人|多数人|大多数人|散户们?|投资者们?)(?:都|全都|也都|几乎都|还)?(?:在|还在|正在)?'
                          r'(?:盯着|紧盯|关注|讨论|追捧|追涨|抢|炒|喊|吹|担心|害怕|恐慌|狂欢|押注|赌|一窝蜂)')
# v8: question-form 「不是X而是Y」 (v7zh 「只是常规的财务招聘？人家这是…」); 0 of 3617 ZH donor posts.
QFORM_ZH = re.compile(r'(?:只是|仅仅是|不过是|难道是|真的是|是不是)[^？?\n。]{1,30}[？?]\s*(?:人家|其实|实际上|分明|明明|说白了|错了|并不|并非|不是|才不|真正|这是)'
                      r'|你以为[^？?\n。]{1,30}[？?]\s*(?:其实|错了|并不|并非|不是|才不|真正|人家)'
                      r'|[吗么][？?]\s*(?:不[，,]|并不|并非|才不|错了|当然不)')
QFORM_EN = re.compile(r"\b(?:just|only|merely|simply)\b[^?.!\n]{1,50}\?\s*(?:no|nope|not quite|hardly|think again|wrong|not even close)\b"
                      r"|\b(?:you think|think)\b[^?.!\n]{1,50}\?\s*(?:think again|wrong|no)\b"
                      r"|\?\s*(?:No|Nope)[,.!]\s*(?:it'?s|this is|that'?s|the real)"
                      # v9 imperative variant (v8 en_industry): "Forget X — Y is/are the actual/real ..."
                      r"|\b(?:forget|ignore|never mind)\b[^.!?\n]{1,140}?[—–:;-]\s*[^.!?\n]{1,180}?\b(?:is|are)\s+(?:the\s+)?(?:actual|real)\b", re.I)
# v8: intensifiers. Donors 0.11-0.16 per 1k CJK chars; v4-v7 drafts 1.56 (死死 / 死磕 / 拉满).
INTENSIFIER_STRONG = re.compile(r'死死|死磕|硬生生|彻彻底底|狠狠|血洗|核弹级|爆杀')
INTENSIFIER = re.compile(r'死死|死磕|硬生生|彻彻底底|狠狠|血洗|核弹级|爆杀|疯狂|暴力|炸裂|拉满')
OVERCLAIM_ZH = re.compile(r'彻底|注定|必然|必定|势必|板上钉钉|毫无疑问|毋庸置疑')
COLLOQ = re.compile(r'吧|呢|啊|吗|嘛|呗|啥|咋|挺|估计|感觉|反正|真的|这波|有点|就是|其实|得看|说实话|还行|靠谱|离谱|没戏')
_SENT = re.compile(r'[。！？!?\n；;]+')
_PROMO = re.compile(r'返佣|开户|邀请码|注册|链接|抽奖|空投|福利|私信|进群|关注|点赞|转发|评论区|课程|社群|直播|报名|优惠|广告|'
                    r'置顶|粉丝|合约|爆仓|带单|喊单')
_ABUSE = re.compile(r'猪狗|混账|日奸|叛徒|傻[逼比Bb]|蠢|狗|他妈|操|屌|婊|贱|滚|垃圾|恶心|废物|脑残|智障|去死')
_FINANCE = re.compile(r'市场|美联储|央行|利率|降息|加息|通胀|数据|美债|债|股|估值|资金|仓位|涨|跌|经济|政策|需求|供给|芯片|公司|'
                      r'业绩|利润|价格|油价|汇率|行业|产能|周期|AI|模型|算力|订单|收入|成本|财报|美元|人民币|就业|关税|半导体|存储|'
                      r'交易|定价|预期|做多|做空|牛市|熊市|行情|投资')
_TRAD = re.compile(r'[這們個說沒會對時為來還過與從經關點於後實當應發見裡問題將開長東動錢國際場價漲聯準債險議資產業報貨幣銀權爭預測]')
_MARKER = re.compile(r'其实|所以|但是|不过|反而|我(?!们)|觉得|估计|感觉|说实话|就是|还是|没|不会|别|吧|呢|嘛|挺|真的|有点|得看|先')
LONG_SENTENCE = 50     # CJK chars; donors median 18-22 per sentence
MIN_FORMAL_HITS = 2


def density(text):
    """{'formal_hits', 'formal_words', 'formal_per_1k', 'colloq_per_1k', 'max_sentence', 'cjk'}"""
    t = str(text or '')
    n = len(CJK.findall(t))
    words = FORMAL_RX.findall(t)
    sents = [len(CJK.findall(s)) for s in _SENT.split(t)]
    k = max(n, 1) / 1000
    return {'cjk': n, 'formal_hits': len(words), 'formal_words': list(dict.fromkeys(words)),
            'formal_per_1k': round(len(words) / k, 1), 'colloq_per_1k': round(len(COLLOQ.findall(t)) / k, 1),
            'max_sentence': max(sents or [0])}


def register_findings(body, lang='zh'):
    """SOFT zh_register: >= 2 research connectives or an AI template phrase (a very long sentence is
    reported in the detail). ~2% of donor posts of draft length (80-300 CJK chars) trip it."""
    if lang != 'zh' or not body:
        return []
    d = density(body)
    templates = list(dict.fromkeys(m.group(0) for m in AI_TEMPLATE.finditer(body)))
    templates += [m.group(0) for m in QFORM_ZH.finditer(body)]   # v8 question-form 不是X而是Y
    parts = []
    strong, allint = INTENSIFIER_STRONG.findall(body), INTENSIFIER.findall(body)
    over = OVERCLAIM_ZH.findall(body)
    if over:   # v9: 彻底 / 注定 / 必然 ... (v8zh 「彻底进入了尾声」)
        parts.append('绝对化副词 ' + '、'.join(dict.fromkeys(over)))
    if strong or len(allint) >= 2:
        parts.append('夸张强化词 ' + '、'.join(dict.fromkeys(allint)) + ' (donors ~0.1/千字)')
    if d['formal_hits'] >= MIN_FORMAL_HITS:
        parts.append('研报腔连接词 ' + '、'.join(d['formal_words']) + f" ({d['formal_per_1k']}/千字; donors ~1.6)")
    if templates:
        parts.append('AI 套话 ' + '、'.join(templates))
    if parts and d['max_sentence'] >= LONG_SENTENCE:
        parts.append(f"最长一句 {d['max_sentence']} 字")
    return [{'code': 'zh_register', 'detail': '; '.join(parts)}] if parts else []


def market_feeling_findings(body, lang='zh'):
    """SOFT market_feeling: the body narrates what the market / many people feel or believe."""
    if lang != 'zh' or not body:
        return []
    hits = list(dict.fromkeys(m.group(0) for m in MARKET_FEELING.finditer(body)))
    hits += [m.group(0) for m in CROWD_ACTION.finditer(body) if m.group(0) not in hits]
    return [{'code': 'market_feeling', 'detail': '替市场/别人说想法: ' + '、'.join(hits)}] if hits else []


# ---------------- real donor register anchors ----------------
_POOL = {}


def _segments(text):
    text = re.sub(r'https?://\S+', ' ', str(text or ''))
    for line in text.splitlines():
        for seg in re.split(r'(?<=[。！？!?])', line):
            yield seg.strip()


def anchor_pool(persona, posts_dir=None):
    """Short real donor lines in spoken register: 8-36 CJK chars, no digits/links/quotes/promo,
    zero research connectives, no crowd-feeling attribution, at least one spoken marker."""
    key = (persona.persona_id, str(posts_dir or ''))
    if key in _POOL:
        return _POOL[key]
    from live.exemplars import load_posts
    pool, seen = [], set()
    for handle in getattr(persona, 'donor_weights', {}) or {}:
        try:
            posts = load_posts(handle, posts_dir)
        except Exception:
            continue
        for p in posts:
            if not p.get('text') or p.get('rt') or p.get('reply'):
                continue
            for seg in _segments(p['text']):
                n = len(CJK.findall(seg))
                visible = len(re.sub(r'\s', '', seg))
                if not 8 <= n <= 36 or n / max(1, visible) < 0.75:
                    continue
                if re.search(r'[\d@#$＄「」“”"『』《》:：]', seg) or _PROMO.search(seg):
                    continue
                if FORMAL_RX.search(seg) or MARKET_FEELING.search(seg) or AI_TEMPLATE.search(seg):
                    continue
                if _ABUSE.search(seg) or not _FINANCE.search(seg) or re.search(r'不是|大家|很多人|人人', seg) or re.search(r'(?:\.\.\.|…|，|；|;|但是|不过|所以|而且|因为)$', seg) \
                        or _TRAD.search(seg):
                    continue
                if not _MARKER.search(seg) or seg in seen:
                    continue
                seen.add(seg)
                pool.append({'handle': handle, 'id': str(p.get('id')), 'text': seg})
    _POOL[key] = pool
    return pool


def anchors(persona, seed='', k=4, posts_dir=None):
    """k real donor lines, rotated by seed (different handles first); [] when donors are missing."""
    pool = anchor_pool(persona, posts_dir)
    if not pool:
        return []
    rng = random.Random(int(sha256(str(seed).encode()).hexdigest()[:12], 16))
    order = pool[:]
    rng.shuffle(order)
    out, handles = [], set()
    for e in order:
        if e['handle'] in handles:
            continue
        out.append(e)
        handles.add(e['handle'])
        if len(out) >= k:
            return out
    for e in order:
        if e not in out:
            out.append(e)
            if len(out) >= k:
                break
    return out


def connectors(persona):
    try:
        from live import language_habits
        rates = (language_habits.load_card(persona) or {}).get('connector_rates') or {}
    except Exception:
        rates = {}
    return [c for c, _ in sorted(rates.items(), key=lambda kv: -kv[1])][:6]


SYSTEM_ZH = """
【中文账号写法（ZH persona；本段优先于上文英文说明里关于语气的描述）】
你在用这个中文账号自己的口吻发帖。不是写研报摘要，也不是把英文材料加工成书面中文。
1. 先想这个人会怎么跟懂行的朋友说这件事，再动笔。thesis_lock 和 units 只给你意思和事实：不要逐句改写它们的句子，用你自己的话重说一遍。thesis_lock 里的书面词（核心变量、叠加、结构性、格局……）不要搬进正文，换成口语。
2. 英文材料按意思直译成中文，再轻改成口语；不要润色成更书面、更华丽的中文，不要加修辞，不要为了口语硬凑比喻（v6 反例：「企业盈利根本没有托底的资本」——说不通）。每句写完自问：这句话懂行的人听得懂吗？
3. 句子短。一句只说一件事；按 zh_register.sentence_length 的中位数写（真实账号大约 18-22 个字一句），最长别超过 35 个字，能断就断。
4. 少用研报书面词：意味着、而非、以……为主、基准路径、结构性、实质性、显然、注定、生存空间、从而、进而、鉴于、与此同时、本质上、叠加、核心变量、难以为继、备用选项。要连接就用 zh_register.donor_connectors 里这些账号常用的口语连接词；像锚句那样带一两个口语词（其实、所以、得看、说实话、吧）就够，别堆。
5. 不替别人说话：不写「很多人认为」「市场普遍认为」「大家都觉得」「很多人据此认为」这类别人怎么想的句子（除非 units 里有这个证据），直接说自己的判断。
6. 不用 AI 套话：「不是X，而是Y」及其问句版（「只是…？人家这是…」「你以为…？其实…」）、「与其说X不如说Y」「理由听起来很完美」「看似合理」「归根结底」「不难发现」都不要写；也别堆「死死」「死磕」「狠狠」「拉满」这类夸张词（真实账号很少用）；不用「彻底」「根本」「注定」「必然」「完全」这类绝对化副词，除非 units 原文就这么说。
7. zh_register.register_anchors 是这类账号参考的真实中文博主的原句，只用来对齐语气、句子长短和用词习惯。不要照抄其中任何词句，也不要借用里面的内容、数字或观点。
8. 开头：第一句照样是明确的判断，但用 zh_register.opening_move 指定的开头动作（没指定 question 就不要用反问开头；全文最多一个反问句）。不要用「别…/不要…/别指望/别被」这种祈使句开头（真实账号里不到 1% 这样开头）；情绪靠判断里的词带出来。也不要跟 zh_register.recent_openers 用同一种开头。
9. 时间：units 的 date_label 是数据所属的时间。标了 historical 的单元说清楚是哪个月/哪天的数据（如「8月的数据」「上周公布的」），但它仍是手上最新的一期，不要写成「回看历史」「当时」。时间和政策路径用平实词（之后、12月之后、下次会议前），不要写「随后就会直接停手」「接下来纯粹是走过场」「直接放话」「打没了」这类别扭说法。
10. 不当谜语人：判断帖要有三样——判断；一句为什么（因为/背后是/靠的是 + units 里的事实）；一句这意味着什么（对市场/读者：对…来说、说白了、换句话说、接下来要看…；不要用「意味着」这种研报腔）。句子照样短，但理由和含义不能省：短稿宁可多写一行，也不要只抛结论和数字。
""".rstrip()

RULES_ZH = ['用自己的口语重说判断，不逐句改写 thesis_lock / units 原句，不搬 thesis_lock 的书面词',
            '短句；一句一件事（中位数见 sentence_length）', '研报书面词尽量不用（见系统说明第 4 条）',
            '不写别人怎么想（很多人认为 / 市场普遍认为）', '英文材料：直译 + 轻改，不加工成书面语',
            '开头按 opening_move；不用「别…」祈使句开头',
            '判断 + 一句为什么 + 一句这意味着什么（对市场/读者）；句子短但理由不能省；不要谜语式只抛结论；时间说法用平实词（之后/12月之后/下次会议前）']

STANCE_MAX_CJK = 35
STANCE_RULE_ZH = ('account_view 写成这个中文账号会发的一句口语判断，35 字以内，一句话说完；不要用研报书面词'
                  '（意味着、而非、以……为主、基准路径、结构性、实质性、显然、注定、叠加、核心变量、格局、取决于……的进一步）；'
                  '不要用「别…/不要…」祈使句；条件放进 view.conditions，不写进 account_view。')


def payload_block(persona, seed='', posts_dir=None, recent_bodies=()):
    block = {'rules': RULES_ZH,
             'register_anchors': [{'handle': a['handle'], 'text': a['text']} for a in anchors(persona, seed, posts_dir=posts_dir)],
             'anchor_rule': '只学语气、句长和用词习惯；不抄词句，不借内容。每篇轮换不同的锚句。',
             'donor_connectors': connectors(persona)}
    # v7: donor sentence length measured the same way as the soft check (CJK chars per sentence);
    # the voice card's band (median 32 / 28 incl. punctuation and Latin) pushed long sentences.
    band = donor_sentence_band(persona, posts_dir)
    if band:
        block['sentence_length'] = dict(band, rule=f"一句大约 {band['median']} 个字（真实账号中位数），最长别超过 35 字")
    move = choose_opening_move(persona, seed, recent_bodies, posts_dir)
    if move:
        block['opening_move'] = {'move': move['move'], 'how': MOVE_HOW.get(move['move'], move['label']),
                                 'donor_share': move['donor_share'],
                                 'donor_examples': move['examples'],
                                 'rule': '只学开头动作，不抄 donor_examples 的词句和内容。'}
    lay = donor_long_layout(persona, posts_dir)
    if lay:
        block['long_layout'] = {'line_len_median': lay['line_len_median'], 'lines_per_100_median': lay['lines_per_100_median'],
                                'rule': f"长帖（200 字以上）按段落写：每段两三句连写，一行约 {int(lay['line_len_median'])} 字，"
                                        '句末带标点，段与段之间空一行；不要一句一行、不要省掉标点。'}
    openers = [_first_sentence(b)[:30] for b in list(recent_bodies)[-3:] if b]
    if openers:
        block['recent_openers'] = openers
    return block


# ---------------- opening moves (Oct 6 v7) ----------------
# v5-v6: 4 of 5 ZH drafts opened with a negation imperative (别指望 / 别看 / 别把 / 别被). Not from the
# anchors (none opened that way): the skeptical emotion brief asks for "one clear reaction" in line 1
# and the spoken-register rules ask for colloquial Chinese; 别… is the model's cheapest way to do
# both. Fix: assign one opening move per post, sampled from the ZH donor opener distribution
# (negation imperative gets the donor share, ~1-2%), avoiding the persona's recent moves, with real
# donor openers of that move as examples.
MOVES = {
    'neg_imperative': ('否定祈使开头（别…/不要…）', re.compile(r'^(?:千万别|先别|别|不要|不必|没必要)')),
    'conditional': ('条件开头（如果/只要…）', re.compile(r'^(?:如果|若|只要|一旦|假如|要是)')),
    'question': ('问句开头', re.compile(r'^[^。！!\n]{0,40}[？?]|^(?:为什么|为啥|怎么|凭什么|谁)')),
    'news_led': ('先交代刚发生的事，再给判断', re.compile(r'^(?:今天|今晚|昨晚|昨天|刚刚|刚|本周|上周|这周|周[一二三四五六日末]|最新|突发|重磅|【|据|消息|\d{1,2}月\d{1,2}日)')),
    'first_person': ('第一人称开头（我…/说实话…）', re.compile(r'^(?:我|个人|说实话|老实说|讲真|坦白)')),
    'number_led': ('数字开头', re.compile(r'^\W{0,2}[\d$￥]')),
    'concession': ('先让一步再转（虽然/其实…）', re.compile(r'^(?:虽然|尽管|其实|说白了|当然|诚然)')),
    'exclaim': ('一句感叹/定性', re.compile(r'^[^。？?\n]{0,30}(?:[！!]|太[^。，\n]{1,8}了)')),
}
MOVE_ORDER = ('neg_imperative', 'conditional', 'question', 'news_led', 'first_person', 'number_led', 'concession', 'exclaim')
STATEMENT = ('statement', '直接一句判断（陈述句）')


def _first_sentence(text):
    first = next((ln.strip() for ln in str(text or '').splitlines() if ln.strip()), '')
    first = re.sub(r'https?://\S+', '', first).strip()
    m = re.match(r'[^。！？!?]*[。！？!?]?', first)
    return (m.group(0) if m else first).strip()


def opener_move(text):
    s = _first_sentence(text)
    for key in MOVE_ORDER:
        if MOVES[key][1].search(s):
            return key
    return STATEMENT[0]


_DIST = {}


def opener_distribution(persona, posts_dir=None):
    """{move: share} over the persona's ZH donor posts plus up to 12 short real example openers per move."""
    key = (persona.persona_id, str(posts_dir or ''))
    if key in _DIST:
        return _DIST[key]
    from live.exemplars import load_posts
    counts, examples = {}, {}
    for handle in getattr(persona, 'donor_weights', {}) or {}:
        try:
            posts = load_posts(handle, posts_dir)
        except Exception:
            continue
        for p in posts:
            t = p.get('text') or ''
            if p.get('rt') or p.get('reply') or len(CJK.findall(t)) / max(1, len(t)) < 0.3:
                continue
            move = opener_move(t)
            counts[move] = counts.get(move, 0) + 1
            s = _first_sentence(t)
            n = len(CJK.findall(s))
            if (6 <= n <= 30 and len(s) <= 40 and _FINANCE.search(s) and not re.search(r'币|链上|[@#「」“”"『』]|http', s)
                    and not _PROMO.search(s)
                    and not _ABUSE.search(s) and not FORMAL_RX.search(s) and not _TRAD.search(s)
                    and not MARKET_FEELING.search(s)):
                bucket = examples.setdefault(move, [])
                if len(bucket) < 40 and s not in bucket:
                    bucket.append(s)
    total = sum(counts.values()) or 1
    dist = {'shares': {k: round(v / total, 3) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])},
            'n': total, 'examples': examples}
    _DIST[key] = dist
    return dist


def choose_opening_move(persona, seed='', recent_bodies=(), posts_dir=None):
    """Sample one opening move from the donor distribution; damp moves used by recent drafts.
    Returns {'move', 'label', 'donor_share', 'examples'} or None when donors are missing."""
    dist = opener_distribution(persona, posts_dir)
    shares = {k: v for k, v in dist['shares'].items() if k in ASSIGNABLE}
    if not shares:
        return None
    recent = [opener_move(b) for b in list(recent_bodies)[-3:] if b]
    weights = {}
    for move, share in shares.items():
        w = max(share, 0.0)
        # v7 live: damping 'statement' (the donor default, ~70%) pushed 3 of 4 live picks to 'question'
        # (~6% in donors). Only the minority moves are damped when recent drafts used them.
        if move in recent and move != STATEMENT[0]:
            w *= 0.15 if move == recent[-1] else 0.4
        if move == 'question' and 'question' in recent:   # v8 rolling cap: <= 1 question opener per 4
            w = 0.0
        weights[move] = w
    rng = random.Random(int(sha256(f'{seed}|opening'.encode()).hexdigest()[:12], 16))
    total = sum(weights.values()) or 1.0
    x, acc, pick = rng.random() * total, 0.0, None
    for move, w in sorted(weights.items()):
        acc += w
        if x <= acc:
            pick = move
            break
    pick = pick or max(weights, key=weights.get)
    label = MOVES[pick][0] if pick in MOVES else STATEMENT[1]
    pool = dist['examples'].get(pick) or []
    ex = rng.sample(pool, min(2, len(pool))) if pool else []
    return {'move': pick, 'label': label, 'donor_share': shares.get(pick), 'examples': ex}


def opening_findings(body, assigned=None, recent_bodies=()):
    """SOFT opener_move: a negation-imperative opener (别…) when it was not the assigned move, or the
    same opening move as 2+ of the last 3 drafts (c26d3a4's family rule, now in the shared regen)."""
    move = opener_move(body)
    out = []
    recent = [opener_move(b) for b in list(recent_bodies)[-3:] if b]
    if move == 'neg_imperative' and (assigned or {}).get('move') != 'neg_imperative':
        out.append({'code': 'opener_move', 'detail': '「别…/不要…」祈使开头（donor 约 1-2%）；按 opening_move 换一种开头'})
    elif move == 'question' and ((assigned or {}).get('move') not in (None, 'question') or 'question' in recent):
        # Oct 6 v8: v8zh zh_macro opened 「…，难道还要硬加？」 right after v7's question openers; donors
        # open with a question ~6% of the time. Rolling cap: at most 1 question opener per 4 drafts.
        out.append({'code': 'opener_move', 'detail': '反问开头（donor 约 6%，最近 3 篇已有 / 未被指定）；第一句直接陈述判断'})
    else:
        if move != STATEMENT[0] and recent.count(move) >= 2:
            out.append({'code': 'opener_move', 'detail': f'开头动作 {move} 与最近 3 篇中的 2 篇相同'})
    return out


# Assignable opening moves. conditional / number_led are excluded: the shape's line1_rule forbids a
# conditional line 1 and the signature forbids a number-led opening outside data_take.
ASSIGNABLE = ('statement', 'news_led', 'question', 'first_person', 'exclaim', 'concession', 'neg_imperative')
MOVE_HOW = {
    'statement': '直接一句陈述判断（主语 + 判断），不用祈使句',
    'news_led': '第一句先点出刚出的事或数据，同一句里就给判断',
    'question': '用一句反问带出判断，下一句马上给自己的答案',
    'first_person': '用「我」直接表态开头（不要「我个人觉得」这种软开头）',
    'exclaim': '一句短的感叹或定性开头，再展开',
    'concession': '先认一点（其实 / 虽然……），马上转到判断',
    'neg_imperative': '否定祈使开头（别… / 不要…）',
}


def sentence_lengths(text):
    """CJK chars per sentence (split on 。！？!? and newlines; same as the REPORT metrics)."""
    return [n for n in (len(CJK.findall(x)) for x in re.split(r'[。！？!?\n]+', str(text or ''))) if n >= 2]


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


SENTENCE_MEDIAN_MAX = 28   # soft regen above this; donors 18-22
_BAND = {}


def donor_sentence_band(persona, posts_dir=None):
    key = (persona.persona_id, str(posts_dir or ''))
    if key in _BAND:
        return _BAND[key]
    from live.exemplars import load_posts
    lens = []
    for handle in getattr(persona, 'donor_weights', {}) or {}:
        try:
            posts = load_posts(handle, posts_dir)
        except Exception:
            continue
        for p in posts:
            t = p.get('text') or ''
            if p.get('rt') or p.get('reply') or len(CJK.findall(t)) / max(1, len(t)) < 0.3:
                continue
            lens += sentence_lengths(re.sub(r'https?://\S+', '', t))
    band = None
    if lens:
        lens.sort()
        q = lambda f: lens[min(len(lens) - 1, int(f * len(lens)))]
        band = {'unit': '汉字/句', 'p25': q(.25), 'median': q(.5), 'p75': q(.75), 'n': len(lens)}
    _BAND[key] = band
    return band


def sentence_findings(body, lang='zh'):
    """SOFT zh_sentence_length: median sentence > 28 CJK chars (donors 18-22)."""
    if lang != 'zh' or not body:
        return []
    lens = sentence_lengths(body)
    med = _median(lens)
    if len(lens) >= 2 and med > SENTENCE_MEDIAN_MAX:
        return [{'code': 'zh_sentence_length', 'detail': f'句子中位数 {med} 字 (donors 18-22)；最长 {max(lens)} 字'}]
    return []


def _cjk_runs(text, n):
    t = ''.join(CJK.findall(str(text or '')))
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def stance_copy_findings(body, thesis, lang='zh', n=8):
    """SOFT stance_copy: an 8+ CJK-char run or a research word carried from thesis_lock into the body
    (v6 zh_industry: 「…是这个逻辑的核心变量」 / 叠加). Line-1 near-verbatim copies are verbatim_line1."""
    if lang != 'zh' or not body or not thesis:
        return []
    runs = _cjk_runs(thesis, n) & _cjk_runs(body, n)
    words = [w for w in dict.fromkeys(FORMAL_RX.findall(str(thesis))) if w in body]
    if not runs and not words:
        return []
    parts = []
    if runs:
        parts.append(f'{len(runs)} 处 {n}+ 字原样搬自 thesis_lock')
    if words:
        parts.append('书面词 ' + '、'.join(words))
    return [{'code': 'stance_copy', 'detail': '; '.join(parts)}]


def stance_view_findings(text):
    """ZH stance account_view: > 35 CJK chars, research words, or a 别… imperative -> one stance rewrite."""
    t = str(text or '')
    out = []
    n = len(CJK.findall(t))
    if n > STANCE_MAX_CJK:
        out.append(f'{n} 字 > {STANCE_MAX_CJK}')
    words = list(dict.fromkeys(FORMAL_RX.findall(t)))
    if words:
        out.append('书面词 ' + '、'.join(words))
    if opener_move(t) == 'neg_imperative':
        out.append('「别…」祈使句')
    if AI_TEMPLATE.search(t) or QFORM_ZH.search(t) or re.search(r'[，,]\s*(?:而)?不是[^，。！？]{1,16}[。！]?$', t):
        out.append('「不是X而是Y」句式')
    return out


def en_template_findings(body, lang='en'):
    """SOFT ai_template (EN): question-form "not X but Y" ("Just X? No, it's Y"); 0 of 3844 EN donor posts."""
    if lang == 'zh' or not body:
        return []
    hits = [m.group(0) for m in QFORM_EN.finditer(body)]
    return [{'code': 'ai_template', 'detail': 'question-form template: ' + ' | '.join(hits)}] if hits else []


# ---------------- long-post layout (Oct 6 v8) ----------------
# v7_zi (long, 365 chars) came back as 20 one-clause lines, 85% without end punctuation. ZH donor long
# posts (>= 250 chars; zh_macro 444, zh_industry 890) run a median ~51 chars per line (p10 25-27) and
# 1.7-1.8 lines per 100 chars (p90 ~3.0), i.e. two or three sentences per line/paragraph.
LONG_MIN_CHARS = 200
LINE_LEN_MIN = 22          # below the donor p10
LINES_PER_100_MAX = 3.2    # above the donor p90
_END_PUNCT = re.compile(r'[。！？!?…~～）)」”"：:，,；;.\]】]$')
_LAYOUT = {}


def _layout(text):
    lines = [ln.strip() for ln in str(text or '').splitlines() if ln.strip()]
    n = len(re.sub(r'\s', '', str(text or '')))
    if not lines or not n:
        return None
    lens = sorted(len(re.sub(r'\s', '', ln)) for ln in lines)
    return {'chars': n, 'lines': len(lines), 'per100': round(len(lines) / n * 100, 2),
            'line_len': _median(lens), 'no_punct': round(sum(1 for ln in lines if not _END_PUNCT.search(ln)) / len(lines), 2)}


def donor_long_layout(persona, posts_dir=None):
    key = (persona.persona_id, str(posts_dir or ''))
    if key in _LAYOUT:
        return _LAYOUT[key]
    from live.exemplars import load_posts
    rows = []
    for handle in getattr(persona, 'donor_weights', {}) or {}:
        try:
            posts = load_posts(handle, posts_dir)
        except Exception:
            continue
        for p in posts:
            t = p.get('text') or ''
            if p.get('rt') or p.get('reply') or len(CJK.findall(t)) / max(1, len(t)) < 0.3:
                continue
            if len(re.sub(r'\s', '', t)) >= 250:
                lay = _layout(t)
                if lay:
                    rows.append(lay)
    out = None
    if rows:
        out = {'posts': len(rows), 'line_len_median': _median([r['line_len'] for r in rows]),
               'lines_per_100_median': _median([r['per100'] for r in rows])}
    _LAYOUT[key] = out
    return out


def line_break_findings(body, lang='zh'):
    """SOFT zh_line_breaks: a long ZH draft broken into one-clause lines (donor long posts: ~51 chars/line)."""
    if lang != 'zh' or not body:
        return []
    lay = _layout(body)
    if not lay or lay['chars'] < LONG_MIN_CHARS:
        return []
    if lay['line_len'] < LINE_LEN_MIN or lay['per100'] > LINES_PER_100_MAX:
        return [{'code': 'zh_line_breaks',
                 'detail': f"{lay['lines']} 行，每行中位 {lay['line_len']} 字，{int(lay['no_punct'] * 100)}% 行尾无标点"
                           f"（donor 长帖每行约 51 字，每百字 1.7 行）"}]
    return []


# ---------------- why / implication / time phrasing (Oct 6 v10) ----------------
# Fiona on the v9 pack (ZH 0/4 publishable): 「像谜语人，缺少解释」「可以加 - 这意味着什么」. The
# rejected drafts state a call and a number but never say WHY (no causal link) or WHAT IT MEANS for
# markets/readers. Rule (keyword based, judgment drafts only):
#   missing_why         - no causal marker anywhere (因为 / 背后 / 靠的是 / 受…拖累 / …导致 …). A number
#                         line after the call, or 说明 / 可见, is NOT a reason on its own: it must be
#                         linked by a causal marker.
#   missing_implication - no consequence marker (对…来说 / 说白了 / 换句话说 / 所以 / 接下来要看 /
#                         利好 …). 意味着 counts (a single one does not trip zh_register) but the
#                         repair asks for colloquial forms so the two checks never fight.
WHY_RX = re.compile(r'因为|由于|原因|背后|靠的是|靠着|在于|毕竟|主要是|一是|源于|来自|撑着|既然|'
                    r'受[^，。；！？\n]{1,12}(?:拖累|影响|拉动|压制)|导致|带动|拖累|推着|根子')
IMPLICATION_RX = re.compile(r'对[^，。；！？\n]{1,12}(?:来说|而言)|这对|换句话说|说白了|落到|所以|因此|也就是说|'
                            r'接下来要看|下一步要看|要盯|得盯|得看|利好|利空|压力会|意味着|值得警惕|风险在于|'
                            r'机会在于|受益|吃亏|还没定价|没被定价|这样一来')
# Awkward colloquial time / policy-path phrases (v9 #1 / #3). Small and explicit on purpose.
AWKWARD_TIME = ('随后就会直接', '随后就直接', '接下来纯粹是', '直接停手', '走过场', '直接放话', '打没了')


def why_implication_findings(body, lang='zh'):
    """SOFT missing_why / missing_implication on a ZH judgment draft (see rule above)."""
    if lang != 'zh' or not body or len(CJK.findall(str(body))) < 15:
        return []
    out = []
    if not WHY_RX.search(body):
        out.append({'code': 'missing_why', 'detail': '只有判断和数字，没有一句说清为什么（因为/背后是/靠的是…）'})
    if not IMPLICATION_RX.search(body):
        out.append({'code': 'missing_implication',
                    'detail': '没说这对市场/读者意味着什么（对…来说/说白了/接下来要看…）'})
    return out


def awkward_time_findings(body, lang='zh'):
    """SOFT zh_awkward_time: colloquial time / policy-path slang (随后就会直接停手 / 走过场 ...)."""
    if lang != 'zh' or not body:
        return []
    hits = [w for w in AWKWARD_TIME if w in body]   # substring test: overlapping phrases all reported
    return [{'code': 'zh_awkward_time', 'detail': '别扭的时间/路径说法: ' + '、'.join(hits)}] if hits else []
