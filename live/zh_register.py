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
          '层面', '叠加', '无疑', '势必', '难以为继', '备用选项', '定价(?:显然)?(?:不够|并不)?充分', '削弱')
FORMAL_RX = re.compile('|'.join(FORMAL))
# AI template phrasing Fiona flags (on top of the generic template_phrase list).
AI_TEMPLATE = re.compile(r'听起来(?:很|非常|十分)?(?:完美|合理|美好|有道理)|看似合理|不难发现|不可否认|归根结底|'
                         r'不是[^，。；！？\n]{1,14}[，,]\s*而是|与其说[^，。；！？\n]{1,14}不如说|死死[^，。；！？\n]{0,4}压')
# Market / crowd feeling attribution (ZH rule: commit your own call, never narrate what others feel).
MARKET_FEELING = re.compile(
    r'(?:很多人|不少人|多数人|大多数人|大部分人|一般人|散户们?|投资者们?|市场上?普遍|市场(?:都|一致)|大家(?:都)?|普遍|主流观点|'
    r'各方|人们)(?:都|也|还|据此|因此|纷纷|一度|仍然|已经)?(?:在)?(?:认为|觉得|以为|担心|相信|期待|预期|押注|在赌|看好|看空|默认|共识)')
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
    parts = []
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
1. 先想这个人会怎么跟懂行的朋友说这件事，再动笔。thesis_lock 和 units 只给你意思和事实：不要逐句改写它们的句子，用你自己的话重说一遍。
2. 英文材料按意思直译成中文，再轻改成口语；不要润色成更书面、更华丽的中文，不要加修辞。
3. 句子短。一句只说一件事，一般不超过 25 个字，能断就断。
4. 少用研报书面词：意味着、而非、以……为主、基准路径、结构性、实质性、显然、注定、生存空间、从而、进而、鉴于、与此同时、本质上、叠加、难以为继、备用选项。要连接就用 zh_register.donor_connectors 里这些账号常用的口语连接词。
5. 不替别人说话：不写「很多人认为」「市场普遍认为」「大家都觉得」「很多人据此认为」这类别人怎么想的句子（除非 units 里有这个证据），直接说自己的判断。
6. 不用 AI 套话：「不是X，而是Y」「与其说X不如说Y」「理由听起来很完美」「看似合理」「归根结底」「不难发现」都不要写。
7. zh_register.register_anchors 是这类账号参考的真实中文博主的原句，只用来对齐语气、句子长短和用词习惯。不要照抄其中任何词句，也不要借用里面的内容、数字或观点。
8. 口语不等于含糊：第一句照样是明确的判断。
""".rstrip()

RULES_ZH = ['用自己的口语重说判断，不逐句改写 thesis_lock / units 原句',
            '短句；一句一件事', '研报书面词尽量不用（见系统说明第 4 条）',
            '不写别人怎么想（很多人认为 / 市场普遍认为）', '英文材料：直译 + 轻改，不加工成书面语']

STANCE_RULE_ZH = ('account_view 写成这个中文账号会发的一句口语判断，35 字以内，一句话说完；不要用研报书面词'
                  '（意味着、而非、以……为主、基准路径、结构性、实质性、显然、注定、叠加、取决于……的进一步）；'
                  '条件放进 view.conditions，不写进 account_view。')


def payload_block(persona, seed='', posts_dir=None):
    return {'rules': RULES_ZH,
            'register_anchors': [{'handle': a['handle'], 'text': a['text']} for a in anchors(persona, seed, posts_dir=posts_dir)],
            'anchor_rule': '只学语气、句长和用词习惯；不抄词句，不借内容。每篇轮换不同的锚句。',
            'donor_connectors': connectors(persona)}
