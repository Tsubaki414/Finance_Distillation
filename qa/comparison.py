"""Comparative claims judged against the figures they compare.

Two pieces shipped as `ready_for_queue` with the comparison written backwards, and an outside
judge found both on the first reading:

    "Non-GAAP earnings per diluted share of 2.22 dollars outpaced GAAP figures"
        — the same piece had just stated GAAP earnings at 2.46 dollars

    "8 月非农就业增加 16.2 万人……结合此前 12 个月月均 3.1 万人的背景，实际增速已显著放缓"
        — 16.2 is larger than 3.1, so that is an acceleration

Every existing layer passes both. The figures are real, cited, correctly scaled, attached to the
right metric and carrying the right sign; `layer6_sign_direction` checks a direction word against
the figure it is attached to, which is a different question. What is wrong is the *relation
asserted between two figures*, and nothing was looking at that.

Two rules, because the failures have two shapes:

  contradicted_comparison    Both figures are on the page and the comparative points the wrong
      way. Checked only when the two are actually comparable — same unit, both numeric — because a
      gate that compares a percentage to a dollar amount will fire on correct writing, and a gate
      that fires on correct writing gets switched off.

  comparison_without_baseline    The comparative names a baseline that is nowhere cited, as
      "outpaced GAAP figures" does. There is no reliable way to resolve that name to a fact: the
      pack holds both a GAAP and a non-GAAP earnings figure whose generic-extractor labels each
      contain the word "GAAP", so any match is a guess between them. Rather than guess, the claim
      is refused. A reader cannot check "X outpaced Y" without Y either, so requiring both operands
      is an editorial rule the piece should meet regardless of what a gate can verify.
"""
from __future__ import annotations
import re

BLOCKING = 'blocking'

# Words asserting a relation *between two quantities*. Deliberately narrow: "增长" and "rose"
# describe one figure's own movement and belong to the sign gate, so they are not here. Including
# them would fire on "revenue grew 18%", which states no comparison at all.
GREATER = re.compile(
    r'outpac\w*|outgr\w*|outperform\w*|exceed\w*|surpass\w*|overtak\w*|outstrip\w*'
    r'|beat\b|beats\b|topped\b|ahead of\b|higher than\b|above\b|more than\b|faster than\b'
    r'|高于|超过|超出|快于|强于|多于|大于|好于|优于|加速|提速|回暖', re.I)
LESS = re.compile(
    r'trail\w*|lagg?\w*|underperform\w*|undershot\b|fell short\b|falls short\b|short of\b'
    r'|lower than\b|below\b|less than\b|slower than\b|weaker than\b'
    r'|低于|不及|不如|少于|小于|弱于|差于|慢于|放缓|降温|回落至|收窄', re.I)

# A comparative needs a second quantity, but some phrasings carry their baseline in words that a
# figure would be wrong for. "higher than a year ago" is a comparison against a fact the pack may
# legitimately hold as a growth rate rather than a level.
BASELINE_IN_WORDS = re.compile(
    r'than (?:a year|last year|the prior year|the previous|a quarter|last quarter)'
    r'|较去年|较上年|较上季|同比|环比|较前值|与去年同期', re.I)


def _numeric(fx):
    v = fx.get('value')
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _comparable(a, b):
    """Two facts may only be ordered when they measure in the same unit."""
    if a is None or b is None or a.get('id') == b.get('id'):
        return False
    return _numeric(a) and _numeric(b) and (a.get('unit') or '') == (b.get('unit') or '')


# An invalidation condition compares a hypothetical future against the present: "I would be wrong
# if the 2 percent level falls below the 1.1 to 2.5 percent range" orders two figures the way the
# writer expects them *not* to be. Ordering them as an assertion reported that sentence backwards,
# which was this gate's own first false positive. Figures inside a condition are proposals
# throughout this pipeline, and they are proposals here too.
CONDITIONAL = re.compile(r'(?:若|如果|一旦|除非|失效条件|更新条件|\bif\b|\bunless\b|\bshould\b|'
                         r'would be wrong|invalidat\w+)(?:[^。！？.!?]|\.(?=\d))*', re.I)


def check_sentence(text, cited_facts, fact_positions, kind=None):
    """Findings for one sentence. `fact_positions` is [{'fact':…, 'start':…, 'end':…}] in order."""
    f = []
    t = text or ''
    if kind == 'condition':
        return f
    # A sentence may state a fact and then add a condition; only the conditional part is exempt.
    for m in CONDITIONAL.finditer(t):
        lo, hi = m.start(), m.end()
        if any(lo <= p['start'] < hi for p in fact_positions):
            fact_positions = [p for p in fact_positions if not lo <= p['start'] < hi]
            t = t[:lo] + ' ' * (hi - lo) + t[hi:]
    for pattern, expect_greater in ((GREATER, True), (LESS, False)):
        for m in pattern.finditer(t):
            before = [p for p in fact_positions if p['end'] <= m.start()]
            after = [p for p in fact_positions if p['start'] >= m.end()]

            if before and after:
                a, b = before[-1]['fact'], after[0]['fact']
            elif len(before) >= 2:
                # "16.2 万人……结合……3.1 万人的背景，增速已显著放缓": both operands precede the
                # verb, in the order subject then baseline.
                a, b = before[-2]['fact'], before[-1]['fact']
            else:
                if BASELINE_IN_WORDS.search(t) or not before:
                    continue
                f.append({'layer': 6, 'code': 'comparison_without_baseline',
                          'severity': BLOCKING,
                          'fact_id': before[-1]['fact'].get('id'),
                          'detail': (f'“{m.group(0)}” compares against a baseline the piece never '
                                     f'states, so the claim cannot be checked: '
                                     f'“{t.strip()[:70]}”')})
                continue

            if not _comparable(a, b):
                continue
            av, bv = a['value'], b['value']
            if av == bv:
                continue
            if (av > bv) != expect_greater:
                f.append({'layer': 6, 'code': 'contradicted_comparison', 'severity': BLOCKING,
                          'fact_id': a.get('id'),
                          'detail': (f'“{m.group(0)}” says {a.get("id")} ({av}) is '
                                     f'{"greater" if expect_greater else "less"} than '
                                     f'{b.get("id")} ({bv}), which is the wrong way round: '
                                     f'“{t.strip()[:70]}”')})
    return f


EXPLAIN = {
    'zh': {
        'contradicted_comparison': '上一稿的比较写反了：句子里两个数字的大小关系，和你用的比较词'
                                   '（如「高于」「放缓」）相反。照数字实际大小改写。',
        'comparison_without_baseline': '上一稿说了「超过／低于／放缓」这类比较，却没有写出被比较的'
                                       '那个数。把基准数字一并写进同一句，否则读者无法核对。',
    },
    'en': {
        'contradicted_comparison': 'The comparison runs the wrong way: the two figures in the '
                                   'sentence are ordered the opposite of what the comparative '
                                   'word claims. Rewrite it to match the figures.',
        'comparison_without_baseline': 'A comparative claim was made without stating the figure '
                                       'being compared against. Put both numbers in the sentence, '
                                       'or drop the comparison.',
    },
}
