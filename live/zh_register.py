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
FORMAL = ('而非', r'以[^，。；！？\n]{1,8}为主', '基准路径', '基准情形', '结构性', '实质性', '显然', '注定',
          '生存空间', '从而', '进而', '由此可见', '鉴于', '与此同时', '本质上', '不容忽视', '值得注意的是', '显著',
          '层面', '叠加', '无疑', '势必', '难以为继', '备用选项', '定价(?:显然)?(?:不够|并不)?充分', '充分(?:定价|反映)',
          '削弱', '重构', '版图', '格局', '极端的', '估值溢价', '承压', '演绎', '共振', '核心变量', '关键变量')
# v7: 核心变量 came from the stance (thesis_lock) into the v6 zh_industry body.
# v11: 意味着 removed - a plain 这意味着 is how a post says what the call means (root cause #3/#4: banning
# it with 从而 / 进而 left the model no consequence connector and only attitude words).
# 从而 / 进而 / 鉴于 stay: research words.
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


BANNED_CONNECTORS = ('说白了', '说到底')


def connectors(persona):
    try:
        from live import language_habits
        rates = (language_habits.load_card(persona) or {}).get('connector_rates') or {}
    except Exception:
        rates = {}
    # v11: never recommend a connector the compose prompt bans (说白了 is in avoid_patterns).
    return [c for c, _ in sorted(rates.items(), key=lambda kv: -kv[1]) if c not in BANNED_CONNECTORS][:6]


from live.hedge import RULE_ZH as _HEDGE_RULE_ZH

SYSTEM_ZH = """
【中文账号写法（ZH persona；本段优先于上文英文说明里关于语气的描述）】
你在用这个中文账号自己的口吻发帖。不是写研报摘要，也不是翻译：不要把英文材料加工成书面中文。
1. 先想这个人会怎么跟懂行的朋友说这件事，再动笔。thesis_lock 和 units 只给你意思和事实：不要逐句改写它们的句子，用你自己的话重说一遍。thesis_lock 里的书面词（核心变量、叠加、结构性、格局……）不要搬进正文，换成口语。
2. 不要翻译，照中文博主说话的方式写：先弄懂意思，再像 zh_register.register_anchors 和 style_exemplars 里这些真实中文博主平时那样说——他们怎么起句、怎么断句、用什么词，你就怎么写。不按英文语序搬：不写一长串定语（一个分句里「的」不超过两个）；不写名词化的翻译词（「进行调整」「存在……的风险」「……的改善」「表外租赁负债」这类英文名词串），换成主谓短句（「价差收窄了」「这些租约没上报表」）；少用「被」字句。不要加修辞，不要为了口语硬凑比喻（v6 反例：「企业盈利根本没有托底的资本」——说不通）。每句写完自问：中文博主会这么说吗？
3. 句子短。一句只说一件事；按 zh_register.sentence_length 的中位数写（真实账号大约 18-22 个字一句），最长别超过 35 个字，能断就断。例外：第一行的判断句可以带一个短理由，最长约 50 个字（本条优先于上文英文说明里第一行的字数限制）。
4. 少用研报书面词：而非、以……为主、基准路径、结构性、实质性、显然、注定、生存空间、从而、进而、鉴于、与此同时、本质上、叠加、核心变量、难以为继、备用选项。没有哪个连接词是必须的：影响和后果换着说法自然带出来（后果是…、所以…、接下来…、影响到…、谁吃亏…，或者直接把结果说出来），不要每篇都用同一个词。一篇里同一个连接词或副词（其实、这意味着、本质上、换句话说、也就是说……）最多出现一次；zh_register.recent_connectives 是这个账号最近几篇已经用过的，这篇换别的说法或干脆不用。zh_register.donor_connectors 只是这些账号会用的词，不要求用。
5. 不替别人说话：不写「很多人认为」「市场普遍认为」「大家都觉得」「很多人据此认为」这类别人怎么想的句子（除非 units 里有这个证据），直接说自己的判断。
6. 不用 AI 套话：「不是X，而是Y」及其问句版（「只是…？人家这是…」「你以为…？其实…」）、「与其说X不如说Y」「理由听起来很完美」「看似合理」「归根结底」「不难发现」都不要写；也别堆「死死」「死磕」「狠狠」「拉满」这类夸张词（真实账号很少用）；不用「彻底」「根本」「注定」「必然」「完全」这类绝对化副词，除非 units 原文就这么说。态度词、强化词、反讽都不能顶替理由：该解释的地方给一句有事实的理由（units 里的数字/事件），不给态度。emotion_brief 里有 zh_rule 时照它收着写（情绪靠判断动词，不用夸张、反讽或强化词）。
7. zh_register.register_anchors 是这类账号参考的真实中文博主的原句，只用来对齐语气、句子长短和用词习惯。不要照抄其中任何词句，也不要借用里面的内容、数字或观点。
8. 开头：第一句照样是明确的判断，但用 zh_register.opening_move 指定的开头动作（没指定 question 就不要用反问开头；全文最多一个反问句）。不要用「别…/不要…/别指望/别被」这种祈使句开头（真实账号里不到 1% 这样开头）；情绪靠判断里的词带出来。也不要跟 zh_register.recent_openers 用同一种开头。
9. 时间：units 的 date_label 是数据所属的时间。标了 historical 的单元说清楚是哪个月/哪天的数据（如「8月的数据」「上周公布的」），但它仍是手上最新的一期，不要写成「回看历史」「当时」。时间和政策路径用平实词（之后、12月之后、下次会议前），不要写「随后就会直接停手」「接下来纯粹是走过场」「直接放话」「打没了」这类别扭说法。
10. 不当谜语人：判断帖正文必须有三样——判断；一句说清原因：哪个事实/数字/事件导致了这个判断（用你自己的话说 why_line 或 pack_roles.why 那条单元；某人「表态/表示/放话」不算原因）；一句说清影响：对市场/读者有什么后果、谁受益谁吃亏、在什么条件下会变、接下来该盯什么（用自己的话说 so_what_line 或 pack_roles.so_what 那条单元）。不要用「市场还没充分定价」「定价还不够充分」「尚未反映在估值里」「后知后觉的资金」这类话收尾，收在一个具体后果、条件或要盯的东西上。「直接」一篇最多用一次（直接导致 / 直接削弱 / 直接限制……换成说清怎么影响的）。why_line / so_what_line 只给意思，不要原样照抄；原因句和影响句用自己的话起头，不要每篇套同一个引子。句子照样短，但原因和影响不能省：短稿宁可多写一行，也不要只抛结论和数字。
11. units 里 statement_origin 为 source_zh 的单元：statement 就是中文原文里的句子（statement_en 只是英文提要），意思和说法以它为准，但要用自己的话说，不要整句照抄（连续十几个字照搬就算抄）。带 statement_en、没有这个标记的单元：statement 是从英文材料整理出的中文事实要点，只是事实，不是让你润色的句子，照第 2 条重新说。数字、名字和时间以 numbers / source_spans 为准。
12. 别人的观点：单元的 speaker 是具体的官员、分析师或机构人士（比如美联储理事鲍曼）时，只有两种写法：用第三人称转述（「鲍曼的意思是…」「她认为…」，可以写这个人的名字，never_name 里的名字除外），或者把观点当成本账号自己的判断，用本账号的口吻说。绝不能用这个人的第一人称写：source_spans 里的 We can see / I think / our 不能写成「我们能看到」「我认为」；本账号自己也从不说「我们」。
""" + _HEDGE_RULE_ZH + """
14. persona.language_habits 是这个账号几位真实中文博主（donor cluster）合起来的说话习惯：句长分布、常见开头和结尾、连接词和语气词的频率、他们怎么交代原因（reason_markers / reason_examples）和怎么说影响（implication_markers / implication_examples）。anchor_posts 是其中两位的整条原帖，每篇轮换。照这些习惯写，但不抄任何句子、事实、数字或观点。catchphrase_cap.phrases 是个别博主的口头禅：一篇最多用一个，used_recently 里的这篇不用。
""".rstrip()

RULES_ZH = ['用自己的口语重说判断，不逐句改写 thesis_lock / units 原句，不搬 thesis_lock 的书面词',
            '短句；一句一件事（中位数见 sentence_length）', '研报书面词尽量不用（见系统说明第 4 条）',
            '不写别人怎么想（很多人认为 / 市场普遍认为）',
            '不要翻译：照 register_anchors / style_exemplars 里博主说话的方式写；不写「的的的」长定语、英文名词串和「被」字句',
            '中文来源（statement_origin=source_zh）：以原文意思为准，用自己的话说，不整句照抄',
            '别人的观点：第三人称转述（鲍曼的意思是…）或当成本账号自己的判断；绝不用对方的第一人称（我们/我认为）',
            '开头按 opening_move；不用「别…」祈使句开头',
            '没有必须用的连接词；同一个连接词/副词一篇最多一次，recent_connectives 里的这篇换说法',
            '判断 + 一句为什么（哪个事实/数字导致了这个判断）+ 一句影响（对市场/读者的后果：谁受益谁吃亏、什么条件下会变、接下来盯什么），说法每篇不同；不用「还没充分定价」类收尾；「直接」一篇最多一次；'
            '句子短但理由不能省；不要谜语式只抛结论；时间说法用平实词（之后/12月之后/下次会议前）',
            '只为防质疑的句子删掉（免责、当然也有可能…、盲目追高容易吃亏、除非…否则…依然成立）；只有带具体新数据/新条件、推进论证的才留',
            '照 persona.language_habits 的句长、开头结尾、原因/影响的说法写；口头禅（catchphrase_cap）一篇最多一个，最近用过的不用']

# v11: 35 -> 50. At 35 the reason was cut out of the call (v7+ median 23.5 CJK chars, 1 of 6 with a reason;
# EN account_view median 28 words, 14/17 carry because / but / enough that) and line 1 repeats the call.
STANCE_MAX_CJK = 50
STANCE_RULE_ZH = ('account_view 写成这个中文账号会发的一句口语判断：判断 + 几个字的理由（因为…/靠…/被…拖累），'
                  '50 字以内，一句话说完；不要用研报书面词（而非、以……为主、基准路径、结构性、实质性、显然、注定、叠加、'
                  '核心变量、格局）；不要用「别…/不要…」祈使句；条件放进 view.conditions，不写进 account_view。'
                  '不要按英文语序翻译（不写「AI发行人的表外租赁负债」这类名词串）；unit / context_units 带 source_zh 的，'
                  '那是中文原文，照原文的中文说法来，不要从英文 statement 翻回去。')
# Reason clause of a ZH call (v11): a rewrite that drops it is rejected.
REASON_CLAUSE = re.compile(r'因为|由于|使得?|让|导致|靠|拖累|压低|推高|拉低|拉高|带动|受[^，。；！？\n]{1,10}(?:影响|拖累|压制|推动)|'
                           r'随着|源于|来自|在于|撑着|托着')


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
    used = recent_connectives(recent_bodies)
    if used:   # zh_native: the persona's last drafts already used these; this post says it differently
        block['recent_connectives'] = used
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


JUDGMENT_LINE_MAX = 50   # v11: the call on line 1 may carry a short reason (= STANCE_MAX_CJK)


def sentence_findings(body, lang='zh'):
    """SOFT zh_sentence_length: median sentence > 28 CJK chars (donors 18-22), or the judgment sentence
    (line 1) > 50 CJK chars. v11: the call may carry a short reason, so a judgment sentence of up to 50
    chars counts as at most the median cap - it never pushes the donor-median rule over by itself."""
    if lang != 'zh' or not body:
        return []
    lens = sentence_lengths(body)
    if not lens:
        return []
    first = lens[0]
    med = _median([min(first, SENTENCE_MEDIAN_MAX) if first <= JUDGMENT_LINE_MAX else first] + lens[1:])
    out = []
    if len(lens) >= 2 and med > SENTENCE_MEDIAN_MAX:
        out.append(f'句子中位数 {med} 字 (donors 18-22)；最长 {max(lens)} 字')
    if first > JUDGMENT_LINE_MAX:
        out.append(f'第一句判断 {first} 字 > {JUDGMENT_LINE_MAX}')
    return [{'code': 'zh_sentence_length', 'detail': '; '.join(out)}] if out else []


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
#   missing_implication - no consequence marker (对…来说 / 换句话说 / 所以 / 接下来要看 / 利好 / 意味着 …).
# v11: these regexes DETECT the function; prompts and repair notes describe the function, never these
# words (66e7aad's literal 背后是 / 对…来说 / 说白了 became the new template: 背后是 3/3 in the
# experiment). 说白了 is banned (avoid_patterns) and no longer counts as an implication.
WHY_RX = re.compile(r'因为|由于|原因|背后|靠的是|靠着|在于|毕竟|主要是|一是|源于|来自|撑着|既然|'
                    r'受[^，。；！？\n]{1,12}(?:拖累|影响|拉动|压制)|导致|带动|拖累|推着|根子')
IMPLICATION_RX = re.compile(r'对[^，。；！？\n]{1,12}(?:来说|而言)|这对|换句话说|落到|所以|因此|也就是说|'
                            r'接下来要看|下一步要看|要盯|得盯|得看|利好|利空|压力会|意味着|值得警惕|风险在于|'
                            r'机会在于|受益|吃亏|还没定价|没被定价|这样一来|后果|影响到|影响的是|结果就是|接下来(?:会|要|得|可能)')
# Awkward colloquial time / policy-path phrases (v9 #1 / #3). Small and explicit on purpose.
AWKWARD_TIME = ('随后就会直接', '随后就直接', '接下来纯粹是', '直接停手', '走过场', '直接放话', '打没了')


# v11 (root cause #4/#7): a keyword is not a reason. The head experiment wrote 「背后是哪怕核心PCE通胀还在
# 3.0%，纽约联储主席Williams也明确表态没有紧迫性」 and passed. The why sentence (any sentence with a causal
# marker, plus the sentence after line 1 closest to stance.why_line) is classified by reason_support: backed
# by a fact / mechanism unit (claim_ledger row on such a unit, a number from one, or a name / phrase only a
# fact unit carries), or a view (somebody's statement 表态 / 表示 / 放话 / 称 …, or a ledger row on a view
# unit), or unknown. missing_why when no why sentence is fact-backed and one is a view. Unknown passes: a
# Chinese paraphrase of an English unit has no lexical overlap (zh_units translations narrow that gap).
SAID_ZH = re.compile(r'表态|表示|放话|声称|宣称|(?<![名简堪号职])称(?!为|得|作|之)|说过|直言|喊话|暗示|口风|发话')
FACT_KINDS = ('fact', 'mechanism')
_LATIN = re.compile(r'[A-Za-z][A-Za-z&.-]{1,}')


def _sentences(text):
    return [x.strip() for x in re.split(r'[。！？!?\n；;]+', str(text or '')) if x.strip()]


def _bigrams(text):
    t = ''.join(CJK.findall(str(text or '')))
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _unit_texts(unit, zh_units=None):
    parts = [str(unit.get('statement') or ''), str(unit.get('statement_en') or '')]
    parts += [str(n.get('text') or '') for n in unit.get('numbers') or []]
    parts += [str(sp.get('exact_text') if isinstance(sp, dict) else sp or '') for sp in unit.get('source_spans') or []]
    if zh_units and isinstance(zh_units.get(unit.get('unit_id')), str):
        parts.append(zh_units[unit['unit_id']])
    return [p for p in parts if p]


def _ledger_rows(sentence, ledger, by_id):
    """claim_ledger rows whose claim is this sentence (claim contained, or >= half its CJK bigrams)."""
    grams = _bigrams(sentence)
    for row in ledger or ():
        if not isinstance(row, dict) or row.get('unit_id') not in by_id:
            continue
        claim = str(row.get('claim') or '').strip()
        cg = _bigrams(claim)
        if claim and (claim in sentence or (cg and len(cg & grams) >= max(2, len(cg) // 2))):
            yield row, by_id[row['unit_id']]


def reason_support(sentence, units, ledger=None, zh_units=None):
    """('fact' | 'view' | 'unknown', how) for one why sentence.
    fact: a fact / mechanism unit backs it (number, claim_ledger row, a name or 3+ CJK bigrams only fact units
    carry). view: the reason is somebody's statement (表态 / 表示 / 放话 …) or its ledger row is a view unit.
    unknown: no evidence either way (a Chinese paraphrase of an English unit has no lexical overlap)."""
    if SAID_ZH.search(sentence):
        return 'view', 'said'
    facts = [u for u in units if u.get('kind') in FACT_KINDS]
    views = [u for u in units if u.get('kind') not in FACT_KINDS]
    fact_texts = [t for u in facts for t in _unit_texts(u, zh_units)]
    view_texts = ' '.join(t for u in views for t in _unit_texts(u, zh_units)).lower()
    if re.search(r'\d', sentence) and fact_texts and numbers_covered(sentence, fact_texts):
        return 'fact', 'number'
    rows = list(_ledger_rows(sentence, ledger, {u.get('unit_id'): u for u in units}))
    if any(u.get('kind') in FACT_KINDS for _, u in rows):
        return 'fact', 'ledger'
    fact_low = ' '.join(fact_texts).lower()
    if any(w.lower() in fact_low and w.lower() not in view_texts for w in _LATIN.findall(sentence)):
        return 'fact', 'name'
    fact_grams = set().union(*[_bigrams(t) for t in fact_texts]) if fact_texts else set()
    if len((_bigrams(sentence) & fact_grams) - _bigrams(view_texts)) >= 3:
        return 'fact', 'phrase'
    if rows:
        return 'view', 'ledger_view'
    return 'unknown', None


def why_sentences(body, why_line=None):
    """Sentences that carry the reason: any with a causal marker, plus the sentence after line 1 closest
    to why_line (CJK bigram overlap >= 0.3)."""
    sents = _sentences(body)
    out = [x for x in sents if WHY_RX.search(x)]
    if why_line and len(sents) > 1:
        wl = _bigrams(why_line)
        best = max(sents[1:], key=lambda x: len(_bigrams(x) & wl))
        if wl and len(_bigrams(best) & wl) / len(wl) >= 0.3 and best not in out:
            out.append(best)
    return out


def why_implication_findings(body, lang='zh', *, units=None, ledger=None, why_line=None, zh_units=None):
    """SOFT missing_why / missing_implication on a ZH judgment draft (see rules above).

    v11: a causal keyword is not enough - when no why sentence is backed by a fact / mechanism unit and
    one only reports somebody's statement (表态 / 表示 / 放话 …) or maps to a view unit in claim_ledger,
    missing_why fires (see reason_support). units / ledger / zh_units come from the draft."""
    if lang != 'zh' or not body or len(CJK.findall(str(body))) < 15:
        return []
    out = []
    whys = why_sentences(body, why_line)
    if not whys:
        out.append({'code': 'missing_why', 'detail': '只有判断和数字，没有一句说清为什么（哪个事实/数字导致了这个判断）'})
    else:
        support = [reason_support(x, units or [], ledger, zh_units) for x in whys]
        kinds = {k for k, _ in support}
        if 'fact' not in kinds and 'view' in kinds:
            said = any(how == 'said' for _, how in support)
            out.append({'code': 'missing_why',
                        'detail': '理由只是某人表态，没有事实' if said else
                                  '理由只引用了观点单元（claim_ledger），没有事实/数字'})
    if not IMPLICATION_RX.search(body):
        out.append({'code': 'missing_implication',
                    'detail': '没说这对市场/读者意味着什么（谁受益谁吃亏、什么条件下会变、接下来盯什么）'})
    return out


# v11 follow-up (Fiona): attitude words must not replace the reason on crypto accounts either. EN variant of
# the why-cites-a-fact check for the EN personas in emotion_tiers.json why_cites_fact_en_personas
# (crypto_macro_en); en_macro / en_industry are the control group and never run it. Only the "the reason is
# just somebody's statement" half: EN has no missing_why-without-marker / missing_implication checks.
WHY_RX_EN = re.compile(r"\b(?:because|since(?!\s+(?:\d|19|20|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
                       r"last|early|mid|late|then))|driven\s+by|thanks\s+to|due\s+to|owing\s+to|on\s+the\s+back\s+of|"
                       r"after|as\s+a\s+result\s+of|(?<!such\s)(?<!well\s)as(?!\s+(?:well|much|many|long|far|soon|if|"
                       r"though|of|for|to|a\s+result)\b))\b", re.I)
SAID_EN = re.compile(r"\b(?:said|says|say|told|tells|argued|argues|warned|warns|thinks|think|believes|claimed|claims|"
                     r"stated|according\s+to|signal(?:l)?ed|insisted|insists)\b", re.I)
_EN_STOP = frozenset('about after again against because been before being below between both could does doing down '
                     'during each from further have having here into itself more most once only other over same should '
                     'some such than that their them then there these they this those through under until very were '
                     'what when where which while will with would your year years week month still just also'.split())


def _en_sentences(text):
    return [x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+', str(text or '')) if x.strip()]


def _en_words(text):
    return {w for w in re.findall(r'[a-z][a-z-]{3,}', str(text or '').lower()) if w not in _EN_STOP}


def en_reason_support(sentence, units, ledger=None):
    """EN reason_support: ('fact' | 'view' | 'unknown', how). Same order as the ZH path: an 'X said' reason is a
    view; a number from a fact / mechanism unit, a claim_ledger row on one, or 3+ content words only fact units
    carry make it a fact."""
    if SAID_EN.search(sentence):
        return 'view', 'said'
    facts = [u for u in units if u.get('kind') in FACT_KINDS]
    views = [u for u in units if u.get('kind') not in FACT_KINDS]
    fact_texts = [t for u in facts for t in _unit_texts(u)]
    if re.search(r'\d', sentence) and fact_texts and numbers_covered(sentence, fact_texts):
        return 'fact', 'number'
    by_id = {u.get('unit_id'): u for u in units}
    words = _en_words(sentence)
    rows = [by_id[r['unit_id']] for r in ledger or () if isinstance(r, dict) and r.get('unit_id') in by_id
            and str(r.get('claim') or '').strip()
            and (str(r['claim']).strip().lower() in sentence.lower()
                 or len(_en_words(r['claim']) & words) >= max(2, len(_en_words(r['claim'])) // 2))]
    if any(u.get('kind') in FACT_KINDS for u in rows):
        return 'fact', 'ledger'
    view_words = set().union(*[_en_words(t) for u in views for t in _unit_texts(u)]) if views else set()
    fact_words = set().union(*[_en_words(t) for t in fact_texts]) if fact_texts else set()
    if len((words & fact_words) - view_words) >= 3:
        return 'fact', 'phrase'
    if rows:
        return 'view', 'ledger_view'
    return 'unknown', None


def en_why_sentences(body, why_line=None):
    """EN why sentences: any with a causal marker after line 1, plus the sentence after line 1 closest to
    why_line (content-word overlap >= 0.3)."""
    sents = _en_sentences(body)
    out = [x for x in sents[1:] if WHY_RX_EN.search(x)]
    if sents and WHY_RX_EN.search(sents[0]) and SAID_EN.search(sents[0]):
        out.insert(0, sents[0])   # a one-line call whose only reason is "because X said"
    if why_line and len(sents) > 1:
        wl = _en_words(why_line)
        best = max(sents[1:], key=lambda x: len(_en_words(x) & wl))
        if wl and len(_en_words(best) & wl) / len(wl) >= 0.3 and best not in out:
            out.append(best)
    return out


def en_why_findings(body, *, units=None, ledger=None, why_line=None):
    """SOFT missing_why on an EN judgment draft of a why_cites_fact_en persona: no why sentence is backed by
    a fact / mechanism unit and one only reports somebody's statement (said / told / argued / warned ...)."""
    if not body:
        return []
    support = [en_reason_support(x, units or [], ledger) for x in en_why_sentences(body, why_line)]
    kinds = {k for k, _ in support}
    if support and 'fact' not in kinds and 'view' in kinds:
        said = any(how == 'said' for _, how in support)
        return [{'code': 'missing_why',
                 'detail': ("the only reason is somebody's statement ('X said'), no fact" if said else
                            'the reason only cites a view unit (claim_ledger), no fact / number')}]
    return []


def awkward_time_findings(body, lang='zh'):
    """SOFT zh_awkward_time: colloquial time / policy-path slang (随后就会直接停手 / 走过场 ...)."""
    if lang != 'zh' or not body:
        return []
    hits = [w for w in AWKWARD_TIME if w in body]   # substring test: overlapping phrases all reported
    return [{'code': 'zh_awkward_time', 'detail': '别扭的时间/路径说法: ' + '、'.join(hits)}] if hits else []


# ---------------- intensifier density (Oct 6 v11) ----------------
# Root cause #3: attitude words stood in for the explanation. Per 1k CJK chars: donors 1.5, ZH drafts
# v2-v6 9.0, v7+ 19.6. Flag above 5 per 1k (at least 2 hits, so one 直接 in a 150-char post does not
# fire a regen on its own), or any of the slang ones.
INTENSIFIER_WORDS = ('直接', '纯粹', '根本', '完全', '彻底', '一点都不', '一点也不', '毫无')
INTENSIFIER_SLANG = ('走过场', '打没了', '砸到', '放话', '死死', '死磕', '狠狠')
INTENSIFIER_DENSITY_MAX = 5.0


def intensifier_findings(body, lang='zh', restrained=True):
    """SOFT zh_intensifier: attitude / intensifier words above donor density, or any slang one.
    v11 follow-up: only restrained personas (emotion_contract.restrained_devices: zh_macro, zh_industry);
    crypto / HIGH personas keep their intensity, so restrained=False never flags."""
    if lang != 'zh' or not body or not restrained:
        return []
    n = len(CJK.findall(str(body)))
    if not n:
        return []
    hits = [w for w in INTENSIFIER_WORDS + INTENSIFIER_SLANG for _ in range(str(body).count(w))]
    slang = [w for w in INTENSIFIER_SLANG if w in body]
    per_1k = round(len(hits) / (n / 1000), 1)
    if slang or (len(hits) >= 2 and per_1k > INTENSIFIER_DENSITY_MAX):
        return [{'code': 'zh_intensifier',
                 'detail': f"强化词/态度词 {'、'.join(dict.fromkeys(hits))}（{per_1k}/千字，donor 约 1.5）"
                           + (f"；俚语 {'、'.join(slang)}" if slang else '')}]
    return []


# ---------------- number coverage (Oct 6 v11) ----------------
# why_line / so_what_line (fix 2) may not add numbers beyond the units; a ZH unit translation (fix 6)
# must keep every number of the English statement. Small normaliser for the documented scale
# conversions: 29,000 = 2.9万 = 29000; $54.23 billion = 542.3亿; Q2 = 二季度; September = 9月; FY27 = 2027.
_NUM_SCALE = {'万亿': 1e12, '亿': 1e8, '万': 1e4, '千': 1e3, 'thousand': 1e3, 'k': 1e3, 'million': 1e6, 'mn': 1e6,
              'm': 1e6, 'billion': 1e9, 'bn': 1e9, 'b': 1e9, 'trillion': 1e12, 'tn': 1e12}
_NUM_RX = re.compile(r'(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(万亿|亿|万|千|thousand\b|million\b|billion\b|trillion\b|'
                     r'bn\b|mn\b|tn\b|[kmb]\b)?', re.I)
_MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
           'november', 'december')
_ZH_SMALL = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4}


def _sig(value):
    return float(f'{value:.9g}')


def _values(text, *, words=False):
    """Every reading of every digit-number in text: raw value and scaled value (and 2/4-digit year).
    words=True also reads month names / 一-四季度 / 上下半年 (reference side only)."""
    t = str(text or '')
    out = []
    for m in _NUM_RX.finditer(t):
        raw = float(m.group(1).replace(',', '') + (m.group(2) or ''))
        reads = {_sig(raw)}
        scale = (m.group(3) or '').lower()
        if scale:
            reads.add(_sig(raw * _NUM_SCALE[scale]))
        if raw.is_integer() and 1900 <= raw <= 2099:
            reads.add(raw % 100)
        if raw.is_integer() and raw < 100 and re.match(r'\s*E?\b', t[m.end():m.end() + 2]) and t[max(0, m.start() - 2):m.start()].upper() == 'FY':
            reads.add(2000 + raw)
        out.append(reads)
    if words:
        low = t.lower()
        extra = {float(i + 1) for i, name in enumerate(_MONTHS) if re.search(r'\b' + name + r'\b', low)}
        extra |= {float(i + 1) for i, name in enumerate(_MONTHS) if re.search(r'\b' + name[:3] + r'\b', low) and name != 'may'}
        extra |= {float(_ZH_SMALL[c]) for c in re.findall(r'第?([一二三四])季度', t)}
        extra |= {1.0} if '上半年' in t else set()
        extra |= {2.0} if '下半年' in t else set()
        out += [{v} for v in extra]
    return out


def numbers_covered(candidate, references):
    """True when every digit-number in candidate matches a number in the reference texts under the
    scale conversions above (or a month / quarter / year written in words there)."""
    ref = set()
    for text in references if not isinstance(references, str) else [references]:
        for reads in _values(text, words=True):
            ref |= reads
    return all(reads & ref for reads in _values(candidate))


# ---------------- why / so-what lead-in repeat (Oct 6 v11) ----------------
# 66e7aad's literal lead-ins became a template (背后是 3/3, 对市场来说 2/3 in the experiment). Soft
# structure_repeat when the same stock lead-in opens a sentence in this draft and in at least one of the
# previous two drafts of the persona (= 2 of the last 3). Plain 因为 / 所以 are not stock lead-ins.
_LEADIN = re.compile(r'^(?:因为|由于|而)?(背后(?:其实)?是?|靠的是|说白了|说到底|归根到底|换句话说|也就是说|这意味着|'
                     r'原因(?:是|在于)|对[^，,。！？\n]{1,10}(?:来说|而言)|接下来(?:要|得|就)?看|下一步(?:要|得)?看|这对)')


def _leadin_key(match):
    word = match.group(1)
    if word.startswith('背后'):
        return '背后是'
    if word.startswith('对') and word.endswith(('来说', '而言')):
        return '对…来说'
    if word.startswith(('接下来', '下一步')):
        return '接下来要看'
    return word


def leadins(text):
    """Stock why / so-what lead-ins that open a sentence or clause of text."""
    keys = []
    for part in re.split(r'[。！？!?\n；;]+', str(text or '')):
        m = _LEADIN.match(part.strip())
        if m and _leadin_key(m) not in keys:
            keys.append(_leadin_key(m))
    return keys


def leadin_repeat_findings(body, recent_bodies=()):
    """SOFT structure_repeat: the same why / so-what lead-in in 2 of the persona's last 3 drafts."""
    prior = [set(leadins(b)) for b in list(recent_bodies or ())[-2:] if b]
    hits = [k for k in leadins(body) if any(k in p for p in prior)]
    if not hits:
        return []
    return [{'code': 'structure_repeat',
             'detail': '原因/影响句又用「' + '」「'.join(hits) + '」起头（最近 3 篇里至少 2 篇）；用自己的话说原因和影响'}]


# ---------------- native Chinese composing (Oct 6 zh_native) ----------------
# Fiona on demo_matrix_oct6_zhfix2 drafts 2-5: 其实 / 这意味着 in nearly every draft (a new template), and
# 翻译腔 - 「AI发行人的表外租赁负债」, long nominal phrases, Bowman's speech written as 「我认为…我们能看到…」.
# Causes (calls/ of that batch): every unit statement is English even for Chinese sources (the Chinese
# sentence only sat in source_spans), fix 6 back-translated those English units into 直译 Chinese and
# SYSTEM_ZH told the model to 直译 + 轻改; rule 4 / RULES_ZH / the shapes named 其实 and 这意味着; first-person
# English spans of an official were translated as the account's own 我们 / 我认为. Fixes: Chinese sources
# give the original Chinese sentences (zh_original), English sources get plain-fact zh_units, and three
# soft checks below feed the one structure regen (never block).

def zh_original(unit):
    """The unit's Chinese source sentences (source_spans exact_text) when the source itself is Chinese, else ''."""
    texts = []
    for sp in (unit or {}).get('source_spans') or ():
        t = sp.get('exact_text') if isinstance(sp, dict) else sp
        if isinstance(t, str) and t.strip():
            texts.append(t.strip())
    text = ' '.join(texts)
    cjk = len(CJK.findall(text))
    return text if cjk >= 8 and cjk >= 0.4 * len(re.sub(r'\s', '', text)) else ''


_CLAUSE_ZH = re.compile(r'[，,。；;！？!?、：:\n]+')
_DE = re.compile(r'(?<![目有])的(?![确话])')
CALQUE = re.compile(r'进行了?[^，。；\n]{0,6}(?:分析|调整|评估|讨论|研究|干预|操作|修正|定价)|'
                    r'[作做]出了?[^，。；\n]{0,8}(?:决定|判断|调整)|具有[^，。；\n]{0,8}(?:意义|作用|价值)|'
                    r'存在[^，。；\n]{0,8}(?:风险|可能性|不确定性)|(?:可能性|方面)(?=[，。；\n]|$)|'
                    r'的(?:增加|减少|上升|下降|改善|恶化|收窄|走阔|放缓|提高|降低|提升)(?=[，。；、\n]|$|[会将对使让带])|'
                    r'基于|就[^，。；\n]{1,10}而言|在[^，。；\n]{1,10}的(?:背景|情况|前提)下')
_BEI = re.compile(r'被(?![子窝褥动告])')


def translationese_findings(body, lang='zh'):
    """SOFT zh_translationese: a clause with >= 3 的 (long attributive chain), nominalised English calques
    (进行调整 / 存在…风险 / …的改善 / 基于), or >= 2 被-passives. The 我们 / quoted-official first person is
    speaker_first_person. Feeds the one structure regen; never blocks."""
    if lang != 'zh' or not body:
        return []
    parts = []
    chains = [c.strip() for c in _CLAUSE_ZH.split(str(body)) if len(_DE.findall(c)) >= 3]
    if chains:
        parts.append('一个分句里 3 个以上「的」: ' + ' | '.join(c[:30] for c in chains[:2]))
    calques = list(dict.fromkeys(m.group(0) for m in CALQUE.finditer(str(body))))
    if calques:
        parts.append('翻译式名词化: ' + '、'.join(calques[:4]))
    bei = _BEI.findall(str(body))
    if len(bei) >= 2:
        parts.append(f'「被」字句 {len(bei)} 处')
    return [{'code': 'zh_translationese', 'detail': '; '.join(parts)}] if parts else []


SPEAKER_TYPES = ('official', 'sell_side', 'buy_side', 'analyst', 'executive', 'company', 'economist', 'expert',
                 'person', 'researcher', 'politician', 'regulator', 'central_bank')
_FP_SPAN = re.compile(r"\b(?:I|we|our|us|my)\b|\bI'm\b|\bwe're\b|我们|(?<!自)我(?![国司行])", re.I)
_FP_BODY = re.compile(r'我们|我认为|我觉得|我判断|我看到|我相信|在我看来|我的看法|我预计')


def speaker_voice_findings(body, units=(), ledger=None, lang='zh'):
    """SOFT speaker_first_person: the body says 我们 (the account never does), or an opinion-marker sentence
    (我认为 / 我们能看到 …) carries a named speaker's first-person source sentence - a quoted official's or
    analyst's view must be third person (鲍曼的意思是…) or the account's own judgment, never their 我."""
    if lang != 'zh' or not body:
        return []
    text = str(body)
    hits = []
    if '我们' in text:
        hits.append('「我们」')
    speakers = [u for u in units or () if (u.get('speaker_type') or '') in SPEAKER_TYPES
                or (u.get('speaker') and u.get('kind') == 'view')]
    fp_units = {u.get('unit_id') for u in speakers
                if any(_FP_SPAN.search(str(sp.get('exact_text') if isinstance(sp, dict) else sp or ''))
                       for sp in u.get('source_spans') or ())}
    if fp_units:
        for sent in _sentences(text):
            m = _FP_BODY.search(sent)
            if not m or m.group(0) == '我们':
                continue
            grams = _bigrams(sent)
            rows = [r for r in ledger or () if isinstance(r, dict) and isinstance(r.get('claim'), str)
                    and (sent in r['claim'] or r['claim'].strip() in sent
                         or (grams and len(grams & _bigrams(r['claim'])) >= max(2, len(grams) // 2)))]
            if (not ledger) or any(r.get('unit_id') in fp_units for r in rows):
                hits.append(f'「{m.group(0)}」写的是讲话人自己的第一人称: {sent[:24]}')
                break
    if not hits:
        return []
    return [{'code': 'speaker_first_person', 'detail': '; '.join(hits)}]


# Connectives / adverbs that became templates (其实 / 这意味着 in 4 of 4 zhfix2 drafts). Plain 因为 / 所以 /
# 但是 / 不过 are grammar, not a template, and are not counted.
CONNECTIVES = ('其实', '这意味着', '说白了', '本质上', '换句话说', '也就是说', '说到底', '归根结底', '事实上', '实际上',
               '显然', '可以说', '某种程度上', '说实话', '老实说', '坦白说', '简单说', '总之', '关键是', '问题是',
               '有意思的是', '不得不说', '值得一提', '更重要的是', '这说明')
CONNECTIVE_WINDOW = 5   # this draft + the persona's previous 4
# Oct 7: 直接 (直接导致 / 直接削弱 / 直接嵌进 / 直接限制) in 4 of 4 donor-cluster fill drafts. It is a per-draft tic,
# not a cross-post template: at most once per draft (twice flags), and the batch check flags it when more than
# two drafts of one batch use it. Never in the recent-window list. 直接融资 / 直接投资 … are finance terms.
PER_DRAFT_ONLY = ('直接',)
_ZHIJIE = re.compile(r'直接(?!融资|投资|税|成本|费用|标价|报价)')


def zhijie_count(text):
    """直接 used as an intensifier (finance compounds like 直接融资 not counted)."""
    return len(_ZHIJIE.findall(str(text or '')))


def _connective_key(word):
    return '这意味着' if word in ('这意味着', '意味着') else word


def connective_counts(text):
    t = str(text or '')
    counts = {w: t.count(w) for w in CONNECTIVES if w in t}
    bare = t.count('意味着') - t.count('这意味着')
    if bare > 0:
        counts['这意味着'] = counts.get('这意味着', 0) + bare
    n = zhijie_count(t)
    if n:
        counts['直接'] = n
    return counts


def recent_connectives(recent_bodies=(), window=CONNECTIVE_WINDOW):
    seen = []
    for b in list(recent_bodies or ())[-(window - 1):]:
        for w in connective_counts(b):
            if w not in seen and w not in PER_DRAFT_ONLY:
                seen.append(w)
    return seen


def connective_repeat_findings(body, recent_bodies=(), lang='zh', window=CONNECTIVE_WINDOW):
    """SOFT connective_repeat: a template connective / adverb used twice in this draft, or used here and
    in at least one of the persona's previous window-1 drafts (= more than 1 of the last 5)."""
    if lang != 'zh' or not body:
        return []
    counts = connective_counts(body)
    twice = [w for w, n in counts.items() if n > 1]
    prior = set(recent_connectives(recent_bodies, window))
    again = [w for w in counts if w in prior and w not in twice and w not in PER_DRAFT_ONLY]
    if not twice and not again:
        return []
    parts = []
    if twice:
        parts.append('同一篇用了两次以上: ' + '、'.join(twice))
    if again:
        parts.append(f'最近 {window} 篇里又用: ' + '、'.join(again))
    return [{'code': 'connective_repeat', 'detail': '; '.join(parts)}]


# ---------------- template endings (Oct 7) ----------------
# Fiona / donor_fill_REPORT: 「还没有充分定价」「定价还不够充分」「没有被充分计价」「尚未反映在估值里」「后知后觉的资金」
# closed 3 of 4 ZH drafts. Cause: the ending rules themselves asked for 「还没被定价的是什么」 / "what is not
# priced". The rules now ask for a concrete consequence, condition or what to watch; this SOFT check flags a
# pricing / valuation-gap closer (one regen, never blocks), and says so when the persona's recent window or another
# account's draft of the same day already ended that way (at most one such ending per window / per day).
PRICING_GAP = re.compile(
    r'(?:还|仍|仍然|尚)?(?:没有?|未|尚未)(?:被)?(?:市场|资金|二级市场)?(?:充分|完全|真正|足够)?(?:地)?(?:定价|计价|反映|体现|price ?in)|'
    r'定价(?:还|仍|仍然|显然|也|明显)?(?:不够|并不|没有|尚未|远未|远远不够)(?:充分|到位)?|'
    r'(?:定价|计价)(?:不足|不充分|滞后)|充分(?:定价|计价)|'
    r'(?:反映|体现)(?:在|到)(?:估值|价格|股价|定价)[^，。；！？\n]{0,4}(?:还|仍|尚)?(?:不够|不足|没有|有限)|'
    r'后知后觉的?资金|预期差|'
    r'市场(?:还|仍)?(?:没有?|未)(?:意识到|反应过来|看到|注意到)|'
    r"(?:\bnot\b|n't|\byet to be\b)[^.!?\n]{0,30}\bpric(?:ed|ing)\b(?: in)?|\bunder-?priced\b|\bmispriced\b|"
    r"\bnot (?:yet )?in the price\b|\b(?:the )?market (?:has(?:n't| not)|is(?:n't| not)) (?:yet )?(?:caught on|noticed|woken up)",
    re.I)
TEMPLATE_ENDING_WINDOW = CONNECTIVE_WINDOW   # this draft + the persona's previous 4


def _last_sentence_text(body):
    sents = [s for s in _sentences(str(body or '')) if s.strip()]
    return sents[-1].strip() if sents else ''


def pricing_gap_ending(body):
    """The last sentence when it closes on 'the market hasn't priced it' (pricing / valuation gap), else ''."""
    last = _last_sentence_text(body)
    return last if last and PRICING_GAP.search(last) else ''


def template_ending_findings(body, recent_bodies=(), same_day_bodies=(), window=TEMPLATE_ENDING_WINDOW):
    """SOFT template_ending: the draft ends on a pricing / valuation-gap line. The detail names a repeat when one of
    the persona's previous window-1 drafts, or any other account's draft of the same day, already ended that way."""
    last = pricing_gap_ending(body)
    if not last:
        return []
    detail = f'定价缺口式结尾「{last[:40]}」'
    if any(pricing_gap_ending(b) for b in list(recent_bodies or ())[-(window - 1):] if b):
        detail += f'；最近 {window} 篇里已有一篇这样收尾'
    if any(pricing_gap_ending(b) for b in same_day_bodies or () if b):
        detail += '；今天别的账号已有一篇这样收尾'
    return [{'code': 'template_ending', 'detail': detail}]


ZHIJIE_BATCH_MAX = 2


def batch_template_findings(results):
    """Batch side of the Oct 7 rules, {index: [findings]}: a pricing-gap ending in more than one draft of the batch
    (the first keeps it, later ones are flagged), 直接 in more than ZHIJIE_BATCH_MAX drafts (drafts after the
    second are flagged)."""
    out, gap_seen, zhijie_seen = {}, [], []
    for i, r in enumerate(results):
        body = (r or {}).get('body') or ''
        if not body:
            continue
        acct = r.get('account_id')
        if pricing_gap_ending(body):
            if gap_seen:
                out.setdefault(i, []).append({'code': 'template_ending', 'level': 'soft',
                                              'detail': 'batch: another pricing-gap ending (also ' + ', '.join(gap_seen) + ')'})
            gap_seen.append(str(acct))
        if zhijie_count(body):
            if len(zhijie_seen) >= ZHIJIE_BATCH_MAX:
                out.setdefault(i, []).append({'code': 'connective_repeat', 'level': 'soft',
                                              'detail': f'batch: 直接 already used in {len(zhijie_seen)} drafts (' +
                                                        ', '.join(zhijie_seen) + ')'})
            zhijie_seen.append(str(acct))
    return out
