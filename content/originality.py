"""Did this piece write its own sentences, or reproduce someone else's?

CLAUDE.md forbids it in as many words — 「除短句且明确署名引用，禁止复制表达、近义词洗稿、固定推广
/导流/订阅/邀请码」 — and until now nothing in the pipeline checked. The rule lived in a document
and the code enforced a privacy gate, a numeric gate, a citation gate and a style gate, none of
which look at whether the prose is the writer's own.

It was not hypothetical. One English draft reproduced two of its donor's posts nearly whole:

    "...is preparing to hike again, but the bigger story is what comes next: The BOJ is reportedly
     leaning toward a 25-basis-point rate hike at its Sept 18 meeting, with inflation risks
     remaining. TAP IMAGE TO SEE FULL INSIGHT👇 https://t.co/owfU77w9pg"

43 consecutive tokens, the donor's own call to action, and the donor's own short link — under our
account. The draft was blocked, but for unrelated reasons; every copy-specific defect in it passed
unnoticed. Style exemplars are the strongest quality lever this project has, and a small local
model will sometimes paste them instead of learning from them. The exemplars stay; the output is
checked.

Thresholds are the donors' own numbers, not a judgement call. Two different posts by the same real
author overlap like this:

                    longest shared run          n-gram overlap
    zh   median 0   p90 0   p99 16              median 0.000   p99 0.026   (n=296 pairs)
    en   median 0   p90 0   p99  8              median 0.000   p99 0.105   (n=1734 pairs)

A person writing two pieces about the same beat repeats essentially nothing verbatim. The limits
below sit above each language's p99 with margin, so a draft has to be doing something no real
author does before it is blocked.

Two things are refused outright, at any rate:

  a link that is not the source        A t.co link belongs to whoever posted it. Republishing it
                                       sends our readers through someone else's tracking.
  promotional boilerplate              "TAP IMAGE TO SEE FULL INSIGHT", subscribe prompts, invite
                                       codes. These are the donor's business model, not a style.
"""
from __future__ import annotations
import re

BLOCKING = 'blocking'

# Above each language's p99 for a real author's self-overlap, with margin.
MAX_RUN = {'zh': 20, 'en': 12}
MAX_OVERLAP = {'zh': 0.08, 'en': 0.15}
NGRAM = {'zh': 8, 'en': 5}

URL = re.compile(r'https?://[^\s一-鿿)\]>"\']+|\bt\.co/\S+', re.I)

PROMO = re.compile(
    r'tap image|see full insight|full insight|link in bio|subscribe|sign up|join (?:my|our)\b'
    r'|free trial|promo code|invite code|referral|use code\b|dm me\b|follow me\b'
    r'|点击(?:图片|链接)|查看全文|关注我|订阅|邀请码|优惠码|私信我|加群|扫码', re.I)


def _tokens(text, lang):
    t = text or ''
    if lang == 'zh':
        return list(re.sub(r'[^一-鿿]', '', t))
    return re.findall(r'[a-z0-9$%.]+', t.lower())


def _ngrams(xs, n):
    return {tuple(xs[i:i + n]) for i in range(len(xs) - n + 1)}


def longest_shared_run(draft_tokens, other_tokens, n=6):
    """Length of the longest token sequence the draft shares with `other`."""
    if len(draft_tokens) < n or len(other_tokens) < n:
        return 0
    seen = _ngrams(other_tokens, n)
    best = run = 0
    for i in range(len(draft_tokens) - n + 1):
        if tuple(draft_tokens[i:i + n]) in seen:
            run += 1
            best = max(best, run + n - 1)
        else:
            run = 0
    return best


def _overlap(draft_tokens, other_tokens, n):
    a = _ngrams(draft_tokens, n)
    if not a:
        return 0.0
    return len(a & _ngrams(other_tokens, n)) / len(a)


def _language_of(text):
    """Which side of the language boundary a text sits on, by script."""
    t = text or ''
    cjk = len(re.findall(r'[一-鿿]', t))
    return 'zh' if cjk / max(len(t), 1) > 0.12 else 'en'


# --- fuzzy: paraphrase rather than verbatim ------------------------------------------------
#
# The evaluation contract asks for exact and fuzzy copied spans to be checked *separately*, and
# separately is the point: they can do different amounts of work, and only one of them is much
# use here.
#
# Measured on the donors' own posts, sentence-level cosine against the frozen multilingual
# embedder this project already runs:
#
#                              unrelated posts        two authors, same entity      our clean
#                              p99 / max              p99 / max                     drafts, max
#     zh                       0.607 / 0.618          0.733 / 0.794                 0.756
#     en                       0.654 / 0.842          0.576 / 0.940                 0.773
#
# The draft that reproduced 43 tokens of a donor post scores 1.0.
#
# So for Chinese there is usable headroom between what two people writing about the same event
# reach (0.794) and copying (1.0), and a line at 0.85 sits above every real pair measured.
#
# **For English there is almost none.** Two humans quoting the same press release reach 0.94, so
# a threshold low enough to catch paraphrase would also catch honest reporting of a shared
# source. The English line is therefore set at 0.95, which in practice only fires on near-verbatim
# text the exact check already catches. That is the honest state of this measure on English, not
# a gap to be closed by choosing a friendlier number — and it is why this check warns rather than
# blocks in either language.
FUZZY_WARN = {'zh': 0.85, 'en': 0.95}
FUZZY_NOTE = {
    'zh': 'above every same-event human pair measured (max 0.794)',
    'en': ('barely above the human same-source maximum of 0.940, so this can only catch '
           'near-verbatim text; English paraphrase is not separable by this measure'),
}


def _sentences(text, lang):
    import re as _re
    pat = _re.compile(r'[^。！？\n]+' if lang == 'zh' else r'[^.!?\n]+')
    return [s.strip() for s in pat.findall(text or '') if len(s.strip()) > 12][:20]


def fuzzy_max(text, others, lang):
    """Highest cosine any draft sentence reaches against any sentence in `others`.

    Returns None when the embedder is unavailable; a check that cannot run says so rather than
    returning a reassuring zero.
    """
    a = _sentences(text, lang)
    b = []
    for o in others:
        b.extend(_sentences(o, lang)[:8])
    b = b[:600]
    if not a or not b:
        return None
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parents[1] / 'live'))
        import style as _style
        m = _style._embedder()
        va = m.encode(a, normalize_embeddings=True, show_progress_bar=False)
        vb = m.encode(b, normalize_embeddings=True, show_progress_bar=False)
        return round(float((va @ vb.T).max()), 3)
    except Exception:
        return None


def check(text, lang='zh', exemplars=(), source_text='', allowed_urls=(), fuzzy=False):
    """Findings for one finished piece.

    `exemplars` are the donor posts this draft was shown — the ones it can copy by accident.
    `source_text` is the primary document, which it may cite but not reproduce.

    Carrying is allowed across a boundary and forbidden within one, which is the rule CLAUDE.md
    now states: 「搬运只能跨语言或跨平台，同语言同平台一律不准搬」. So the wording comparisons below
    run only when the draft and the other text are in the same language. An English release read
    for a Chinese piece is the Cross-language Information Gap lane doing its job — the facts move,
    the sentences are written here — and comparing token overlap across scripts would measure
    nothing anyway.

    What does not depend on the boundary, and is checked either way: someone else's promotional
    wording and someone else's links. Those are theirs whichever language they were in.

    Not implemented, and stated rather than implied: a literal sentence-by-sentence translation
    passed off as original would clear everything here. Catching it needs translation-aware
    comparison, and an unvalidated threshold on an embedding score would be a gate that reports
    confidence it has not earned. `cross_language_pairs` below records where that risk exists so
    it is visible to a human reviewer in the meantime.
    """
    t = text or ''
    lang = 'en' if str(lang).startswith('en') else 'zh'
    f = []
    dt = _tokens(t, lang)
    n = NGRAM[lang]
    cross = 0

    for label, others in (('donor exemplar', list(exemplars)),
                          ('source document', [source_text] if source_text else [])):
        for other in others:
            if _language_of(other) != lang:
                cross += 1
                continue
            ot = _tokens(other, lang)
            run = longest_shared_run(dt, ot)
            rate = _overlap(dt, ot, n)
            if run > MAX_RUN[lang]:
                f.append({'code': 'verbatim_from_' + label.split()[0], 'severity': BLOCKING,
                          'detail': (f'{run} consecutive tokens are identical to a {label}; '
                                     f'a real author repeats at most {MAX_RUN[lang]} '
                                     f'(their own p99 is {8 if lang == "en" else 16})')})
                break
            if rate > MAX_OVERLAP[lang]:
                f.append({'code': 'overlap_with_' + label.split()[0], 'severity': BLOCKING,
                          'detail': (f'{rate:.0%} of the piece\'s {n}-grams appear in a {label}; '
                                     f'the ceiling is {MAX_OVERLAP[lang]:.0%}')})
                break

    allowed = {u.rstrip('/') for u in allowed_urls if u}
    foreign = [m.group(0) for m in URL.finditer(t)
               if m.group(0).rstrip('/') not in allowed]
    if foreign:
        f.append({'code': 'link_that_is_not_the_source', 'severity': BLOCKING,
                  'detail': (f'links that belong to someone else: {sorted(set(foreign))[:4]}. '
                             f'Only the source document may be linked.')})

    promo = [m.group(0) for m in PROMO.finditer(t)]
    if promo:
        f.append({'code': 'promotional_boilerplate', 'severity': BLOCKING,
                  'detail': (f'the donor\'s promotional wording was copied: '
                             f'{sorted(set(x.lower() for x in promo))[:4]}')})

    fuzzy_score = None
    if fuzzy:
        same = [o for o in list(exemplars) + ([source_text] if source_text else [])
                if o and _language_of(o) == lang]
        fuzzy_score = fuzzy_max(text, same, lang)
        if fuzzy_score is not None and fuzzy_score >= FUZZY_WARN[lang]:
            f.append({'code': 'paraphrase_candidate', 'severity': 'warning',
                      'detail': (f'a sentence reaches {fuzzy_score} cosine against a same-language '
                                 f'source; the line is {FUZZY_WARN[lang]}, {FUZZY_NOTE[lang]}. '
                                 f'Surfaced for a human to read, not refused.')})

    blocking = [x for x in f if x['severity'] == BLOCKING]
    same_lang = [o for o in list(exemplars) + ([source_text] if source_text else [])
                 if o and _language_of(o) == lang]
    return {'findings': f, 'blocking_count': len(blocking),
            'status': 'failed' if blocking else 'passed',
            'longest_shared_run': max(
                [longest_shared_run(dt, _tokens(o, lang)) for o in same_lang] or [0]),
            'same_language_sources_compared': len(same_lang),
            'cross_language_pairs': cross,
            'fuzzy_max_cosine': fuzzy_score,
            'fuzzy_limits': FUZZY_NOTE[lang] if fuzzy else 'not run',
            'policy': ('carrying is allowed across a language or platform boundary and never '
                       'within one; wording is compared only against same-language sources'),
            'check_version': 'originality-v3'}


FAULT_ZH = {
    'verbatim_from_donor': '上一稿有整段照抄示范帖。那些帖子是给你看写法的，不是素材，'
                           '一个字都不要搬。用你自己的话重写。',
    'verbatim_from_source': '上一稿有整段照抄原始文件。数字照抄，句子要自己写。',
    'overlap_with_donor': '上一稿与示范帖用词重合过多，像是换词改写。请重新组织，按你自己的判断写。',
    'overlap_with_source': '上一稿与原始文件用词重合过多。事实来自原文，表达必须是你的。',
    'link_that_is_not_the_source': '上一稿出现了别人的链接。除原始文件外不要放任何链接。',
    'promotional_boilerplate': '上一稿抄了示范帖里的推广语（「点击图片」「关注我」这类）。'
                               '那是对方的生意，不是写作风格，一律删掉。',
}
FAULT_EN = {
    'verbatim_from_donor': 'A passage was copied from the example posts. Those show you how the '
                           'author writes; they are not material. Write the sentence yourself.',
    'verbatim_from_source': 'A passage was copied from the source document. Take the figures, '
                            'write your own sentences.',
    'overlap_with_donor': 'Too much wording is shared with the example posts. Rework it in your '
                          'own words rather than swapping synonyms.',
    'overlap_with_source': 'Too much wording is shared with the source document. The facts are '
                           'theirs; the phrasing has to be yours.',
    'link_that_is_not_the_source': 'A link belonging to someone else appeared. Link nothing but '
                                   'the source document.',
    'promotional_boilerplate': 'Promotional wording was copied from the example posts '
                               '("TAP IMAGE", "subscribe"). That is their business, not a '
                               'style. Remove it.',
}


def faults(result, lang='zh'):
    tbl = FAULT_ZH if lang == 'zh' else FAULT_EN
    out, seen = [], set()
    for x in result.get('findings', []):
        c = x['code']
        if c in tbl and c not in seen:
            seen.add(c)
            out.append(tbl[c])
    return out
