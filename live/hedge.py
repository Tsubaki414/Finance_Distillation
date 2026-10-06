"""Hedge-only sentences (Fiona 2026-10-06 13:30): delete what only pre-empts criticism.

A sentence that exists only to protect the writer - a disclaimer (不构成投资建议 / not financial advice), a generic
caveat (当然也有可能… / 仍存在不确定性 / time will tell), generic caution advice (盲目追高容易吃亏 / 留足安全边际), or
a closing conditional that just restates the call in reverse (除非…否则…依然成立 / 如果…那就说明并没有真正…) - is
removed. A caveat stays when it carries a concrete new fact or condition: a number (level, date, data print) the
rest of the post does not use. Disclaimers never stay.

Oct 7 (donor_fill #5): a closing 反过来说… / 换句话说… / in other words… that only restates the call from the other
side (「…就能稳住；反过来说，现在的平稳完全依赖于这部分敞口」) is the same defensive move: `reverse_restate`, checked on
the last two sentences, deleted unless it carries a number the body has not used or a new condition (取决于 / 要看).

SOFT `hedge_only`: feeds the one structure regeneration in compose; never blocks.
"""
from __future__ import annotations

import re

CJK = re.compile(r'[一-鿿]')
_SENT = re.compile(r'(?<=[。！？!?；;])|\n+|(?<=[.!?])\s+')
_NUM = re.compile(r'\d+(?:[.,]\d+)?')

DISCLAIMER = re.compile(
    r'不构成(?:任何)?投资建议|非投资建议|仅供参考|投资有风险|入市需谨慎|以上(?:仅|只)?(?:为|是)个人观点|个人观点[，,]?仅供|'
    r'\bnot (?:financial|investment) advice\b|\bnfa\b|\bdyor\b|do your own research|for (?:informational|educational) purposes',
    re.I)
CAUTION = re.compile(
    r'盲目(?:追高|抄底|乐观|悲观|跟风)|留足安全边际|注意(?:控制)?风险|控制好?仓位|理性看待|保持谨慎|谨慎(?:对待|为上|一点)|'
    r'还需(?:要)?(?:继续)?观察|有待(?:观察|验证|确认)|仍(?:然)?存在不确定性|不确定性(?:仍然|依然)?(?:较大|很大|还在|犹存)|'
    r'未来充满不确定|走一步看一步|拭目以待|静观其变|'
    r'\btime will tell\b|\bremains to be seen\b|\bstay (?:cautious|careful|nimble)\b|\bmanage (?:your )?risk\b|'
    r'\brisks? remain\b|\buncertainty remains\b|\bnothing is guaranteed\b|\bcould go either way\b|\bwe(?:\'ll| will) see\b',
    re.I)
CONCESSION = re.compile(
    r'^(?:当然|诚然|不过也|也)[，,]?[^。！？]{0,6}(?:有可能|不排除|不代表|不是说|存在[^。！？]{0,6}(?:可能|风险))|'
    r'也不排除|不能排除|不排除[^。！？]{0,12}可能|也(?:有)?可能(?:只是|是|会)|'
    r'^(?:of course|that said|to be fair|granted|admittedly)\b|\bcould (?:also|still) (?:be|turn|go)\b|'
    r'\b(?:i|we) (?:could|might|may) be wrong\b',
    re.I)
_LEAD_ZH = r'^(?:但是?|不过|可是?|而|反之|相反)?[，,]?\s*'
FALSIFIER = re.compile(
    _LEAD_ZH + r'(?:如果|若|一旦|除非|要是|假如|倘若)[^。！？]*(?:就说明|那就说明|说明[^。！？]{0,8}(?:没有|并没有|不是)|否则|才算|'
    r'(?:逻辑|判断|结论)(?:就)?(?:依然|仍然|还是)?(?:成立|有效|错了|不成立)|就错了|就要改)|'
    + _LEAD_ZH + r'(?:除非)[^。！？]*$|'
    r'否则[^。！？]{0,30}(?:依然|仍然|还是|照样|都)(?:成立|有效|站得住)|'
    r'那就说明[^。！？]{0,30}(?:并)?(?:没有|不是|没)|'
    r'^(?:if|unless|should)\b[^.!?]*(?:i\'m wrong|i am wrong|(?:the )?(?:call|thesis|view) (?:is|was) wrong|thesis breaks|'
    r'would change (?:my|the) (?:mind|view|call)|invalidat|proves? (?:me|it|this|the call) wrong|still holds|holds up)',
    re.I)


# Oct 7: reverse / restating lead-ins on a closing sentence (反过来说 / 换句话说 / in other words …).
RESTATE = re.compile(
    r'^(?:反过来说|反过来讲|反过来看|反过来|换句话说|换言之|也就是说|说到底|归根到底|总之|总而言之)[，,：:]?|'
    r'^(?:put (?:it )?differently|in other words|conversely|flip(?:ped)? (?:it )?around|the flip side(?: is)?|'
    r'said (?:another|differently)|to put it another way)\b',
    re.I)
RESTATE_TAIL = 2   # only the last two sentences: an ending move, not every 换句话说 in the middle
# a restating lead-in that introduces a new condition (取决于 / 要看 / what to watch) is not a restatement
NEW_CONDITION = re.compile(r'取决于|要看|就看|前提是|关键在于?|盯(?:住|着|紧)?|看(?:的是|点在)|'
                           r'\bdepends? on\b|\bhinges? on\b|\bwatch\b|\bthe test is\b', re.I)


def _sentences(body):
    return [s.strip() for s in _SENT.split(body or '') if s and s.strip()]


def _new_fact(sentence, earlier):
    """True when the sentence brings a number (level, date, print) the rest of the post does not use."""
    nums = set(_NUM.findall(sentence))
    prior_nums = set(_NUM.findall(' '.join(earlier)))
    return bool(nums - prior_nums)


def hedge_sentences(body):
    """[(sentence, kind)] of hedge-only sentences in the body."""
    sents = _sentences(body)
    out = []
    for i, s in enumerate(sents):
        earlier = sents[:i] + sents[i + 1:]
        if DISCLAIMER.search(s):
            out.append((s, 'disclaimer'))
        elif CAUTION.search(s) and not _new_fact(s, earlier):
            out.append((s, 'generic_caution'))
        elif CONCESSION.search(s) and not _new_fact(s, earlier):
            out.append((s, 'concession'))
        elif FALSIFIER.search(s) and not _new_fact(s, sents[:i]):
            out.append((s, 'falsifier_restate'))
        elif (i >= len(sents) - RESTATE_TAIL and RESTATE.search(s) and not _new_fact(s, sents[:i])
              and not NEW_CONDITION.search(s)):
            out.append((s, 'reverse_restate'))
    return out


def hedge_findings(body, lang=None):
    """SOFT hedge_only: sentences that only pre-empt criticism; the regen deletes them."""
    hits = hedge_sentences(body)
    if not hits:
        return []
    detail = '; '.join(f'{kind}: 「{s[:60]}」' for s, kind in hits)
    return [{'code': 'hedge_only', 'detail': detail}]


RULE_EN = ('No hedge-only sentences. A sentence that exists only to pre-empt criticism gets deleted: disclaimers '
           '("not investment advice" / 不构成投资建议 / 仅供参考), generic caveats ("of course it could also…", '
           '"time will tell", "risks remain" / 当然也有可能… / 仍存在不确定性), generic caution advice (盲目追高容易吃亏 / '
           '留足安全边际), and a closing "unless X / if X then it was never real" line that only restates the call in '
           'reverse (including a closing "put differently / conversely" restatement). Keep a caveat only when it carries a concrete new fact or condition (a level, date or data print '
           'from the units that is not already in the post) that advances the argument.')
RULE_ZH = ('13. 删掉只为防止被质疑而存在的句子：免责声明（不构成投资建议、仅供参考）、空泛的对冲（当然也有可能…、'
           '也不排除…、仍存在不确定性、还有待观察）、泛泛的劝诫（盲目追高容易吃亏、留足安全边际、注意风险）、'
           '以及只把判断反过来重说一遍的收尾（除非…否则…依然成立、如果…那就说明并没有真正…、反过来说…、换句话说…）。'
           '只有当这句话带出一个具体的新事实或新条件（units 里有、正文还没用过的数据/时间点/价位），而且推进了论证，才保留。'
           '删掉后不要换成另一句对冲，直接用判断或后果收尾。')
