"""Machine tells: the vocabulary and moves that mark writing as LLM-generated.

The English rules are adapted from skyf0xx/hedgehog-core-copywriting-prose-engineering
(`rules/tells.mjs`), which in turn credits Wikipedia's "Signs of AI writing" and
conorbronsdon/avoid-ai-writing. Borrowed: the word and phrase lists, the negation formula, the
rule of three, hedge stacks, copula avoidance, and the design principle that matters most —

    frequency, not presence

One rule-of-three in a long piece is ordinary prose; four is a tic. Structural tells are counted
per 1000 words against a threshold. Vocabulary is flagged on sight, because a banned word has no
legitimate floor.

Two things are added here that the source could not do:

  1. **Chinese.** Half this system's output is Chinese and the tells are different — 「值得注意的
     是」, 「综上所述」, 「为…提供了有力支撑」, 「彰显」, 「赋能」. That list is drawn from this
     project's own generated drafts, not guessed.

  2. **Validation against a human corpus.** A rule that fires as often on the donors' real posts
     as on generated text is not detecting a machine, it is detecting finance writing. Every rule
     here is checked against 2,500 real posts by `ml/tell_validate.py`, and one that does not
     separate the two is not enabled.
"""
from __future__ import annotations
import re

BLOCKING = 'blocking'
WARNING = 'warning'

# --- English vocabulary, from the borrowed list ------------------------------------------
BANNED_WORDS_EN = [
    'delve', 'tapestry', 'elevate', 'unleash', 'robust', 'seamless', 'leverage', 'moreover',
    'furthermore', 'crucial', 'pivotal', 'garner', 'bolster', 'underscore', 'showcase',
    'showcasing', 'foster', 'fostering', 'intricate', 'intricacies', 'meticulous', 'testament',
    'vibrant', 'interplay', 'myriad', 'synergy', 'holistic', 'multifaceted', 'cutting-edge',
    'transformative', 'groundbreaking', 'game-changer', 'harness', 'revolutionize',
    'facilitate', 'empower', 'streamline', 'realm', 'resonate', 'paramount', 'mosaic',
    'symphony', 'labyrinth', 'beacon', 'cornerstone', 'bedrock', 'kaleidoscope', 'odyssey',
]
BANNED_PHRASES_EN = [
    "it's important to note that", 'it is important to note that', 'it is worth noting that',
    "it's worth noting that", 'at its core', 'in the realm of', 'plays a vital role in',
    "in today's fast-paced world", 'unlock the potential of', 'in conclusion', 'in summary',
    'to summarize', 'studies show', 'experts agree', 'research suggests',
    'the future looks bright', 'only time will tell', 'a testament to',
]

# --- Chinese, observed in this project's own output --------------------------------------
BANNED_WORDS_ZH = [
    '彰显', '赋能', '助力', '抓手', '闭环', '生态位', '维度上', '强有力地',
    '深刻地', '有力支撑', '重要意义', '不容忽视', '至关重要', '显著提升',
]
BANNED_PHRASES_ZH = [
    '值得注意的是', '综上所述', '总而言之', '总的来说', '由此可见', '不难看出',
    '在…的背景下', '为…提供了有力支撑', '具有重要意义', '需要指出的是',
    '从某种意义上说', '归根结底', '一方面…另一方面',
]

# --- structural moves ---------------------------------------------------------------------
RULE_OF_THREE = re.compile(r'\b(\w+),\s+(\w+),\s+(?:and|or)\s+(\w+)\b', re.I)
RULE_OF_THREE_ZH = re.compile(r'[一-鿿]{2,6}、[一-鿿]{2,6}、[一-鿿]{2,6}')
NEGATION_FORMULA = re.compile(
    r"\b(?:is|are|it'?s)\s+not\s+(?:just|only)\s+[^.;]{2,60}[,—-]\s*(?:it'?s|they'?re)\s+", re.I)
NEGATION_FORMULA_ZH = re.compile(r'不仅(?:仅)?是?[^，。；]{2,30}[，,]\s*(?:更|而且|还)是?')
HEDGE_STACK = re.compile(r'\b(?:could|may|might)\s+(?:potentially|possibly|eventually|ultimately)\b',
                         re.I)
HEDGE_STACK_ZH = re.compile(r'(?:可能|或许)(?:会)?(?:在一定程度上|某种程度上|potentially)')
COPULA_AVOIDANCE = re.compile(r'\b(?:serves as|stands as|marks a|functions as|represents a)\b', re.I)
COPULA_AVOIDANCE_ZH = re.compile(r'(?:构成了|标志着|体现了|反映出|彰显了)(?:一(?:个|种))?')

# Measured, not guessed — and most of the borrowed set did not survive the measurement.
# ml/tell_validate.py over 3,322 real posts and the generated pieces:
#
#   rule (zh)             human/1000w   machine/1000w   verdict
#   rule_of_three              1.76          0.00       humans do it MORE — enabling it would
#                                                       reject the writers being imitated
#   negation_formula           0.07          0.00       never fires on this output
#   hedge_stack                0.00          0.00       never fires either way
#   copula_avoidance           0.07          0.57       7.8x separation — enabled
#
#   banned vocabulary (en)   2.6% of docs  25% of docs   enabled
#   banned vocabulary (zh)   1.7%          0.0%          humans use these more — not enabled
#   stock phrases (zh)       2.8%          0.0%          same
#
# The list was written for English marketing copy. Two of eight rules transfer to Chinese finance
# writing and to slot-constrained drafting. The rest are kept in the file, measured on every run,
# and left disabled with the number that disabled them.
STRUCTURAL_LIMIT = {
    'copula_avoidance': 1.0,
}
DISABLED_RULES = {
    'rule_of_three': 'human corpus runs 1.76/1000w against 0.00 in generated text',
    'negation_formula': 'never observed in generated text (0.00 both sides)',
    'hedge_stack': 'never observed on either side',
}
# Vocabulary lists are language-gated for the same reason.
VOCAB_ENABLED = {'en': True, 'zh': False}
PHRASE_ENABLED = {'en': True, 'zh': False}
VOCAB_NOTE = ('the Chinese word and phrase lists fire on 1.7% and 2.8% of real posts and 0% of '
              'generated ones, so they measure the donors rather than the machine')


# The clearest structural tell, and the one a blind reader named first: "every sentence carries
# one fact, with no argument between them". Measured over 3,322 real posts and the generated
# pieces:
#
#            median share of sentences containing a figure
#   zh       human 0.42      machine 0.82
#   en       human 0.33      machine 0.86
#
# The slot mechanism causes it: each slot becomes a sentence, so the pipeline rewards packing.
# The ceiling is the human p90, so a piece may be as dense as the densest real posts and no
# denser. Staying below is never penalised — humans write plenty of figure-free paragraphs.
FIGURE_DENSITY_CEILING = {'zh': 0.78, 'en': 0.67}

# The second structural tell, and one that had to be measured twice before it meant anything.
#
# A blind judge named "单句成段的机械拼接". The donors write one-sentence paragraphs 69.6% of the
# time themselves, so that habit is not the tell, and acting on the judge's wording would have
# changed the wrong thing. What separates the pieces is that every sentence is the same *length*.
#
# The first attempt at a threshold was invalid: the human percentiles were computed with an ad-hoc
# splitter while the gate measured with `_SENT_SPLIT`, which skips decimal points. The two
# disagreed by a factor of three on the same English piece — 0.533 against 0.378 — and on the
# strength of that mismatch English looked healthy. A band and the gate that enforces it have to
# come from the same measurement, so both sides now call sentence_variation() below:
#
#            sentence-length CV per post (posts of 5+ sentences), donors' own posts
#   zh       n=1021   p10 0.330   median 0.521   p90 0.701
#   en       n=1170   p10 0.371   median 0.626   p90 0.982
#
# Nine of ten generated pieces sit below their language's p10, English included. The floor is that
# p10: a piece may be as uniform as the most uniform tenth of real posts and no more.
# Short-sentence share is deliberately not gated — the human p10 for it is 0.0, so plenty of real
# posts have none, and a gate there would be inventing a rule the donors do not follow.
#
# The floor is stratified by length, because a p10 pooled over all posts answers a different
# question from the one being asked of a seven-sentence piece. Longer posts vary more: a real
# author's p10 climbs from 0.291 at 5-6 sentences to 0.438 above 16. Pooling made the gate
# slightly strict for English at our own length — 0.371 against the length-matched 0.343 — and
# slightly lenient for long Chinese pieces. Each figure is that band's own p10:
#
#            5-6      7-10     11-15    16+        n per band
#   zh       0.291    0.318    0.362    0.438      334 / 254 / 144 / 311
#   en       0.364    0.343    0.381    0.413      528 / 334 / 153 / 182
# Two tiers, because this number is a *diagnostic* and the project's own evaluation contract
# says so: `financial-persona-distillation/references/evaluation-contract.md` lists uniform
# sentence length among "AI-pattern flags — surface diagnostics" that "do not establish machine
# authorship, deception or detector evasion success".
#
# Running it as a single hard gate overstated what it can carry. What it does measure, honestly,
# is conformance to a band the donors themselves occupy, so it may gate our own output — it may
# not be cited as evidence that a text was machine-written. That distinction is the point of
# NOT_AN_AUTHORSHIP_CLAIM below, which is returned with every result so a later reader cannot
# quietly promote the number into a conclusion it does not support.
#
#   below p10   blocked   more uniform than 90% of the donors' own posts at this length
#   p10 - p25   warning   inside the band but at its uniform quarter
#   above p25   silent
#
# The warning tier fires on a quarter of the donors' own posts by construction — that is what p25
# means, and a five-sentence English sample that reads perfectly naturally lands in it. So a
# warning here says "at the uniform end of normal", never "defective", and the finding text says
# so. A reviewer who reads it as a defect will start rejecting real writing.
#
#            5-6            7-10           11-15          16+          n per band
#   zh       .291 / .373    .318 / .394    .362 / .423    .438 / .496   334/254/144/314
#   en       .364 / .558    .343 / .447    .381 / .440    .413 / .477   528/334/153/182
SENTENCE_CV_BANDS = {
    'zh': ((7, 0.291, 0.373), (11, 0.318, 0.394), (16, 0.362, 0.423),
           (10 ** 9, 0.438, 0.496)),
    'en': ((7, 0.364, 0.558), (11, 0.343, 0.447), (16, 0.381, 0.440),
           (10 ** 9, 0.413, 0.477)),
}
NOT_AN_AUTHORSHIP_CLAIM = ('sentence-length uniformity is a style-conformance diagnostic measured '
                           'against these donors\' own posts; it is not evidence of machine '
                           'authorship and must not be reported as such')
# One number per language, for callers that want a headline; the gate uses the table above.
SENTENCE_CV_FLOOR = {'zh': 0.330, 'en': 0.371}

# **This gate no longer blocks, and the reason is that it was caught manufacturing a defect.**
#
# CV is std/mean. The cheapest way for a model to raise it is not to write with natural rhythm —
# it is to drop a very short sentence between two long ones. That is what happened. Sixteen
# Chinese drafts written under this gate contain 29 sentences of the form
#
#     费用在抬头。    需求还在。    电话会仍缺人头拆分。
#
# and when the reader was asked what was wrong with the output, 刻意的短句 was on the list, with
# the instruction 「允许多写几句解释，不要把解释压缩成术语、口号或刻意的短句」. The gate was
# pushing the writing toward the thing the reader rejects.
#
# The measurement itself was not wrong: the donors' p10 is real, and a piece below it genuinely is
# more uniform than 90% of their posts. What was wrong was treating a distributional statistic as
# something a generator should optimise against. Conformance to a band does not imply the route
# taken to get there was natural, and here the route was slogans.
#
# So it stays measured and reported — a piece of uniform prose is still worth a reviewer seeing —
# and content/reader_spec.py blocks instead, on the list the reader actually wrote.
CV_SEVERITY = WARNING
CV_DEMOTED = ('demoted from blocking 2026-09-24: enforcing it produced 29 slogan-length sentences '
              'across 16 drafts, which is the defect the reader named. See content/reader_spec.py')


def cv_band(lang, sentences):
    """(blocking floor, warning floor) for a piece of this length: that band's p10 and p25."""
    for upper, p10, p25 in SENTENCE_CV_BANDS.get(lang, ()):
        if sentences < upper:
            return p10, p25
    return SENTENCE_CV_FLOOR.get(lang, 0.0), SENTENCE_CV_FLOOR.get(lang, 0.0)


def cv_floor(lang, sentences):
    """The blocking floor alone. Kept for callers that only need the hard limit."""
    return cv_band(lang, sentences)[0]

# Hedged attribution: the construction that ties a figure to an inference without committing to
# it — "非农 16.2 万人表明劳动力市场仍有韧性". A real analyst writes what follows; this writes that
# something "shows" something.
#
# The aggregate measurement that first pointed here was wrong and is worth recording: a regex
# lumping 表明/显示出/意味着/进一步 together showed 22x over-use, but 意味着 (0.272 per 1000 chars
# in the donors' own writing) and 进一步 (0.350) are ordinary Chinese the donors use constantly.
# Banning them would have been banning the corpus. Per phrase, only three stand out:
#
#     表明   donors 0.026 / 1000 chars   ours 1.673   (64x)
#     显示出 donors 0.009               ours 0.669   (74x)
#     反映出 donors 0.007               ours 0.335   (48x)
#
# The ceiling is per piece rather than per 1000 words, because one use is ordinary and a habit is
# not. Counted over the donors' own posts:
#
#     zh   97.7% of 1159 posts contain none   p99 = 1   max = 2
#     en   99.5% of  826 posts contain none   p99 = 0   max = 1
#
# So the limit is each language's p99. This is far more conservative than the sentence-length
# floor above, which fires on 10% of real posts by construction; this fires on 0.1% and 0.5%.
HEDGED_ATTRIBUTION = {
    'zh': re.compile(r'表明|显示出|反映出'),
    'en': re.compile(r'\bis a key factor\b|\bhighlights\b|\bunderscores\b', re.I),
}
HEDGED_CEILING = {'zh': 1, 'en': 0}
MIN_SENTENCES_FOR_CV = 5
_SENT_SPLIT = re.compile(r'[。！？!?\n]+|(?<!\d)\.(?!\d)')
_HAS_DIGIT = re.compile(r'\d')


def figure_density(text):
    """Share of sentences carrying a figure, and the sentence count it is based on."""
    sents = [s.strip() for s in _SENT_SPLIT.split(text or '') if len(s.strip()) > 6]
    if not sents:
        return None, 0
    return sum(bool(_HAS_DIGIT.search(s)) for s in sents) / len(sents), len(sents)


def sentence_variation(text, lang):
    """Coefficient of variation of sentence length, and the count it rests on."""
    sents = [s.strip() for s in _SENT_SPLIT.split(text or '') if len(s.strip()) > 4]
    if len(sents) < MIN_SENTENCES_FOR_CV:
        return None, len(sents)
    lens = [len(s) if lang == 'zh' else len(s.split()) for s in sents]
    mean = sum(lens) / len(lens)
    if mean <= 0:
        return None, len(sents)
    var = sum((x - mean) ** 2 for x in lens) / len(lens)
    return (var ** 0.5) / mean, len(sents)


def _words(text, zh):
    return len(re.findall(r'[一-鿿]', text)) / 1.6 if zh else len(text.split())


def is_zh(text):
    cjk = len(re.findall(r'[一-鿿]', text or ''))
    return cjk / max(len(text or ''), 1) > 0.12


def scan(text, lang=None):
    """Every tell found, with counts and per-1000-word rates."""
    t = text or ''
    zh = is_zh(t) if lang is None else (lang == 'zh')
    n = max(_words(t, zh), 1)
    low = t.lower()

    words = BANNED_WORDS_ZH if zh else BANNED_WORDS_EN
    phrases = BANNED_PHRASES_ZH if zh else BANNED_PHRASES_EN
    hits_w = [w for w in words if (w in t if zh else re.search(rf'\b{re.escape(w)}\b', low))]
    hits_p = [p for p in phrases if ('…' not in p) and (p in t if zh else p in low)]

    struct = {
        'rule_of_three': len((RULE_OF_THREE_ZH if zh else RULE_OF_THREE).findall(t)),
        'negation_formula': len((NEGATION_FORMULA_ZH if zh else NEGATION_FORMULA).findall(t)),
        'hedge_stack': len((HEDGE_STACK_ZH if zh else HEDGE_STACK).findall(t)),
        'copula_avoidance': len((COPULA_AVOIDANCE_ZH if zh else COPULA_AVOIDANCE).findall(t)),
    }
    rates = {k: round(v / n * 1000, 2) for k, v in struct.items()}
    dens, nsent = figure_density(t)
    cv, cv_sents = sentence_variation(t, 'zh' if zh else 'en')
    hedged = HEDGED_ATTRIBUTION['zh' if zh else 'en'].findall(t)
    return {'lang': 'zh' if zh else 'en', 'words': round(n, 1),
            'figure_density': round(dens, 3) if dens is not None else None,
            'sentence_length_cv': round(cv, 3) if cv is not None else None,
            'cv_sentences': cv_sents,
            'hedged_attribution': sorted(set(hedged)),
            'hedged_attribution_count': len(hedged),
            'sentences': nsent,
            'banned_words': hits_w, 'banned_phrases': hits_p,
            'structural_counts': struct, 'structural_per_1000w': rates}


def check(text, lang=None):
    s = scan(text, lang)
    f = []
    lang_key = s['lang']
    if s['banned_words'] and VOCAB_ENABLED.get(lang_key):
        f.append({'code': 'machine_vocabulary', 'severity': BLOCKING,
                  'detail': f"words that mark machine writing: {s['banned_words']}"})
    elif s['banned_words']:
        f.append({'code': 'machine_vocabulary_observed', 'severity': WARNING,
                  'detail': f"{s['banned_words']} — {VOCAB_NOTE}"})
    if s['banned_phrases'] and PHRASE_ENABLED.get(lang_key):
        f.append({'code': 'machine_phrase', 'severity': BLOCKING,
                  'detail': f"stock phrases: {s['banned_phrases']}"})
    ceiling = FIGURE_DENSITY_CEILING.get(s['lang'])
    # Needs enough sentences for the share to mean anything.
    if s['figure_density'] is not None and s['sentences'] >= 5 and s['figure_density'] > ceiling:
        f.append({'code': 'every_sentence_carries_a_figure', 'severity': BLOCKING,
                  'detail': (f"{s['figure_density']:.0%} of sentences contain a number; real "
                             f"posts by these authors run at a median of "
                             f"{'42' if s['lang'] == 'zh' else '33'}% and the ceiling here is "
                             f"{ceiling:.0%}. Put the argument between the figures.")})
    ceiling_h = HEDGED_CEILING[s['lang']]
    if s['hedged_attribution_count'] > ceiling_h:
        f.append({'code': 'hedged_attribution', 'severity': BLOCKING,
                  'detail': (f"{s['hedged_attribution_count']} uses of "
                             f"{s['hedged_attribution']}; "
                             f"{'97.7' if s['lang'] == 'zh' else '99.5'}% of these authors' own "
                             f"posts contain none and their p99 is {ceiling_h}. "
                             f"Say what follows from the figure, not that it shows something.")})

    floor, warn_at = cv_band(s['lang'], s.get('cv_sentences') or 0)
    cvv = s['sentence_length_cv']
    if cvv is not None and floor <= cvv < warn_at:
        f.append({'code': 'sentence_length_near_the_edge', 'severity': WARNING,
                  'detail': (f"sentence-length variation is {cvv:.3f}; inside these authors' own "
                             f"range for a piece of {s.get('cv_sentences')} sentences but below "
                             f"their p25 of {warn_at}. This tier fires on a quarter of their real "
                             f"posts by construction, so it means 'at the uniform end of normal', "
                             f"not 'defective'. {NOT_AN_AUTHORSHIP_CLAIM}")})
    if cvv is not None and cvv < floor:
        f.append({'code': 'sentences_all_the_same_length', 'severity': CV_SEVERITY,
                  'detail': (f"sentence-length variation is {s['sentence_length_cv']:.3f}; real "
                             f"posts by these authors run at a median of "
                             f"{'0.521' if s['lang'] == 'zh' else '0.626'} and the floor for a "
                             f"piece of {s.get('cv_sentences')} sentences is "
                             f"{floor} (their 10th percentile). Every sentence is the same size, "
                             f"which no one writes. {CV_DEMOTED}. {NOT_AN_AUTHORSHIP_CLAIM}")})
    for k, limit in STRUCTURAL_LIMIT.items():
        if s['structural_per_1000w'][k] > limit:
            f.append({'code': f'overused_{k}', 'severity': BLOCKING,
                      'detail': (f"{s['structural_counts'][k]} occurrences = "
                                 f"{s['structural_per_1000w'][k]} per 1000 words, "
                                 f"above the human ceiling of {limit}")})
    blocking = [x for x in f if x['severity'] == BLOCKING]
    return {**s, 'findings': f, 'blocking_count': len(blocking),
            'enabled_structural': list(STRUCTURAL_LIMIT),
            'disabled_structural': DISABLED_RULES,
            'status': 'failed' if blocking else 'passed', 'check_version': 'tells-v4',
            'diagnostic_note': NOT_AN_AUTHORSHIP_CLAIM}


FAULT_ZH = {
    'machine_vocabulary': '用了机器味很重的词（{d}）。换成你自己会说的话。',
    'machine_phrase': '用了套话（{d}）。直接说事，不要起承转合的模板句。',
    'overused_rule_of_three': '连续的三项并列太多了，读起来像模板。拆开或只留一处。',
    'overused_negation_formula': '「不仅…更是…」这种强调句式用多了，是机器写作的典型痕迹。',
    'overused_hedge_stack': '模糊限定词叠用太多（「可能在一定程度上」这类）。要么下判断，要么说清条件。',
    'overused_copula_avoidance': '「构成了/体现了/反映出」这类词用太多，直接说是什么。',
    'hedged_attribution': '上一稿用了「表明／显示出／反映出」这种说法。这些作者自己几乎从不这么写'
                          '（97.7% 的帖子一次都没有）。直接写这个数字让你预期什么，'
                          '不要写它「表明」了什么。',
    'sentences_all_the_same_length': '每句话长度几乎一样，这是上一稿最像机器的地方。真人写作长短交替：'
                                     '有时一句话只有几个字，有时一口气写很长。不要为了凑长度而补字，'
                                     '该短就短。',
    'every_sentence_carries_a_figure': '几乎每句话都挂着一个数字，读起来像数据表。'
                                       '真人写作里只有四成左右的句子含数字，其余是推进论证的话。'
                                       '**少用两个数字，把省下来的句子用来说明它们之间的关系。**',
}
FAULT_EN = {
    'hedged_attribution': 'Phrases like "highlights" or "is a key factor" tie a figure to an '
                          'inference without committing to it. 99.5% of these authors\' own '
                          'posts contain none. Say what you expect to follow from the figure.',
    'sentences_all_the_same_length': 'Every sentence is nearly the same length, which is the clearest machine signature in the last draft. Real writing alternates: some sentences are a few words, others run long. Do not pad to reach a length.',
    'machine_vocabulary': 'Words that mark machine writing ({d}). Use what you would actually say.',
    'machine_phrase': 'Stock phrases ({d}). Say the thing without the scaffolding.',
    'overused_rule_of_three': 'Too many three-item lists; it reads as a template.',
    'overused_negation_formula': '"Not just X, it\'s Y" is one of the most recognisable LLM moves.',
    'overused_hedge_stack': 'Stacked hedges ("could potentially"). Commit or state the condition.',
    'overused_copula_avoidance': '"serves as" / "represents a" — say what it is.',
    'every_sentence_carries_a_figure': 'Almost every sentence carries a number, so it reads as a '
                                       'table. Real posts by these authors run about a third. '
                                       '**Use two fewer figures and spend those sentences on the '
                                       'argument between them.**',
}


def faults(result, lang='zh'):
    tbl = FAULT_ZH if lang == 'zh' else FAULT_EN
    out, seen = [], set()
    for x in result.get('findings', []):
        c = x['code']
        if c in tbl and c not in seen:
            seen.add(c)
            d = ', '.join((result.get('banned_words') or []) + (result.get('banned_phrases') or []))
            out.append(tbl[c].format(d=d[:80]))
    return out
