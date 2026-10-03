"""What the reader actually objects to, in the reader's own words.

Every style measure in this project before this one was invented here: percentile bands over a
donor corpus, sentence-length variation, figure density. A human read the output twice and caught
100% of it both times, then wrote down what was wrong with it. That list is worth more than all
the invented metrics put together, because it is the person the writing has to survive.

Their list, verbatim:

    预告自己要说重点     「真正值得关注的是」「很多人不知道的是」
    模板式转折           「不是……而是……」「问题不在于……而在于……」
    假装有分量的结尾     「这值得深思」「时间会给出答案」「这才是最重要的」
    抽象化普通意思       「实现价值重构」「形成深度协同」「提供新的思考维度」
    机械周全             每段都写优点、风险、建议，再补一句总结
    数字排得很密，关系交代得很少

and the instruction that goes with it:

    写清一句判断是怎么从前面的事实推出来的。允许多写几句解释，不要把解释压缩成术语、
    口号或刻意的短句。读者应该能顺着读懂，无须反复翻译作者的措辞。

**That last sentence reverses something this project was actively optimising for.** The
sentence-length-variation gate rewarded short sentences and, measured over sixteen Chinese
drafts, produced 29 of them: 「费用在抬头。」「需求还在。」「电话会仍缺人头拆分。」 Those are
precisely the 刻意的短句 the reader rejected. The gate was manufacturing the defect it was
supposed to prevent, so it stops blocking (see content/tells.py) and this takes its place.

A note on what is and is not counted. A short sentence is not a defect by itself — donors write
them. What the reader objected to is a short sentence used *instead of* an explanation, so the
check looks at the share of sentences that are terse and free of any connective reasoning, not at
any single one.
"""
from __future__ import annotations
import re

BLOCKING = 'blocking'
WARNING = 'warning'

PATTERNS = {
    # Cut to the two strings that actually appear in our output. Measured per alternative over
    # 1,255 donor posts and 32 of our drafts:
    #
    #     值得注意的是    6 real / 0 ours        需要注意的是  2 / 0
    #     真正值得关注的是 1 real / 0 ours        很多人不知道  1 / 0
    #     重点在于        1 real / 0 ours        说白了就是    1 / 0
    #     ----------------------------------------------------------
    #     我的判断是      4 real / 2 ours        这组数据支持我的判断  0 / 1
    #
    # Six of the eight alternatives had caught nothing but real writing. They were written from
    # imagination — phrases that *sound* like announcing a point — and the model does not use
    # them. What it does use is the last two, so those stay and the rest go.
    'announcing_the_point': (
        r'我的判断是|这组?数据支持我的判断|我目前的判断是',
        '预告自己要说重点。直接说那件事，不要先宣布你要说它。'),
    'template_pivot': (
        r'不是[^，。！？]{1,16}而是[^，。！？]{1,16}|'
        r'问题不在于[^，。！？]{1,24}而在于|与其说[^，。！？]{1,16}不如说|'
        r'表面上[^，。！？]{1,20}实际上',
        '模板式转折（「不是……而是……」这类）。把两边分开说清楚。'),
    'weighty_ending': (
        r'值得深思|时间会给出答案|这才是最重要|拭目以待|才是真正的|意味深长|'
        r'留给市场的时间不多了',
        '假装有分量的结尾。结尾写你的判断或失效条件，不要写感慨。'),
}

# `abstract_inflation` had a regex here and it is gone, which is the clearest single lesson in
# this file.
#
# The word list — 价值重构 / 深度协同 / 赋能 / 闭环 / 底层逻辑 / 新范式 / 第二增长曲线 — was
# written from imagination. Measured, every entry fired on the donors' own posts and **not one
# fired on ours**:
#
#     闭环        15 real / 0 ours        底层逻辑   8 / 0
#     新范式       2 / 0                  第二增长曲线 2 / 0
#     价值重构     1 / 0                  赋能       1 / 0
#
# Twenty-six real posts blocked, zero of our defects caught. Meanwhile the abstraction the model
# actually produced was 「把工资、参与率当成数据层，把加息时点当成政策层」 — invented on the
# spot, and no fixed list could ever have contained it. The reader spotted it by reading.
#
# So the category stays in the spec and the judgement moves to the model half
# (content/reader_spec_llm.py), which caught exactly that sentence. A regex can only hold words
# somebody already thought of, and the failure mode here is inventing new ones.

# 「每段都写优点、风险、建议，再补一句总结」
MECHANICAL_ROUNDNESS = re.compile(
    r'(优点|利好|积极).{0,60}(风险|隐忧|不足).{0,60}(建议|应当|需要关注)', re.S)

SENT = re.compile(r'[^。！？\n]+[。！？]?')
# A connective is what turns a claim into a step of reasoning: because, so, which means, if.
CONNECTIVE = re.compile(r'因为|所以|因此|由于|意味着|说明|导致|才|若|如果|一旦|除非|'
                        r'这|那|其|前提|反过来|换句话|也就是')
HAS_DIGIT = re.compile(r'\d')

TERSE_CHARS = 12
# Measured on the donors' own Chinese posts: the share of sentences under 12 characters that
# carry no connective. Ours ran far above this while the sentence-variation gate was blocking.
TERSE_SHARE_CEILING = 0.18


def _terse_sloganish(sentences):
    """Short sentences that carry no reasoning — the ones used instead of an explanation."""
    out = []
    for s in sentences:
        s = s.strip().rstrip('。！？')
        if 1 < len(s) <= TERSE_CHARS and not CONNECTIVE.search(s) and not HAS_DIGIT.search(s):
            out.append(s)
    return out


def _reasoning_density(sentences):
    """Share of sentences that connect to something — the thing the reader asked to see more of."""
    if not sentences:
        return None
    return round(sum(1 for s in sentences if CONNECTIVE.search(s)) / len(sentences), 3)


def check(text, lang='zh'):
    t = text or ''
    f = []
    if not str(lang).startswith('zh'):
        # The list was written about Chinese output. Applying these exact strings to English
        # would be inventing a spec the reader never gave.
        return {'findings': [], 'blocking_count': 0, 'status': 'passed',
                'note': 'the reader wrote this list about Chinese output',
                'check_version': 'reader-v1'}

    for code, (pat, why) in PATTERNS.items():
        hits = [m.group(0) for m in re.finditer(pat, t)]
        if hits:
            f.append({'code': code, 'severity': BLOCKING,
                      'detail': f'{sorted(set(hits))[:3]} — {why}'})

    if MECHANICAL_ROUNDNESS.search(t):
        f.append({'code': 'mechanical_roundness', 'severity': BLOCKING,
                  'detail': '优点—风险—建议—总结的机械周全。只写你真正要说的那一条。'})

    sents = [s.strip() for s in SENT.findall(t) if len(s.strip()) > 1]
    terse = _terse_sloganish(sents)
    share = round(len(terse) / max(len(sents), 1), 3)
    if share > TERSE_SHARE_CEILING:
        # Warning in the regex, blocking in the model half of content/reader_spec_llm.py.
        #
        # Calibration against the donors own posts put this at 7.5%, and reading what it caught
        # shows the rule conflates two different things:
        #
        #   「费用在抬头。」「需求还在。」     a compressed explanation — what the reader rejected
        #   「未必」「我不信的」「想多了」      a conversational beat — phyrexni's actual voice
        #
        # Both are short, neither carries a connective or a digit, and a regex cannot tell them
        # apart: the difference is whether the sentence answers something just said. The model
        # half does distinguish them — it flagged 「量先收。」 and 「生产端还烫。」 on our drafts
        # and left the rhetorical beats alone — so the judgement moves there and this stays as a
        # reported number.
        f.append({'code': 'slogan_short_sentences', 'severity': WARNING,
                  'detail': (f'{len(terse)}/{len(sents)} 句是不带任何推理的短句：{terse[:4]}。'
                             f'读者要求的是「不要把解释压缩成术语、口号或刻意的短句」，'
                             f'把它们展开成说明。')})

    blocking = [x for x in f if x['severity'] == BLOCKING]
    return {'findings': f, 'blocking_count': len(blocking),
            'status': 'failed' if blocking else 'passed',
            'terse_share': share, 'terse_examples': terse[:6],
            'reasoning_density': _reasoning_density(sents),
            'source': "the reader's own list, 2026-09-24",
            'check_version': 'reader-v1'}


FAULTS = {
    'announcing_the_point': '不要预告自己要说重点（「真正值得关注的是」这类）。直接说。',
    'template_pivot': '不要用「不是……而是……」这种模板式转折。两边分开说清楚。',
    'weighty_ending': '结尾不要写感慨。写你的判断，或写什么情况会证明你错。',
    'abstract_inflation': '不要把普通意思抽象化（赋能、闭环、底层逻辑这类）。用普通说法。',
    'mechanical_roundness': '不要每段都写优点、风险、建议再加总结。只写你真正要说的那条。',
    'slogan_short_sentences': ('上一稿有太多不带推理的短句，像口号。'
                              '把它们展开：写清这句判断是怎么从前面的事实推出来的，'
                              '允许多写几句，读者要能顺着读懂。'),
}


def faults(result, lang='zh'):
    out, seen = [], set()
    for x in result.get('findings', []):
        c = x['code']
        if c in FAULTS and c not in seen:
            seen.add(c)
            out.append(FAULTS[c])
    return out
