"""Language distillation: measured style targets, and a gate that checks they were met.

Pasting a donor's posts into a prompt is few-shot prompting, not distillation. What makes it
distillation is that the donor's observable writing behaviour is measured, handed over as an
explicit target, and then checked on the output — so "it writes like them" is a number rather
than an impression.

The features chosen here are the ones a writer can actually control and the ones that separated
generated text from human text most sharply in ml/style_eval.py:

    sentence_mean        the machine wrote 81-character sentences against a human 57
    sentence_p25         even its short sentences were twice a human's
    long_argument_rate   0.31 against 0.06 — everything was a long clause
    fragment_rate        0.0 against 0.17 — it never wrote a short line
    first_person_rate    it almost never said 我
    conclusion_opener    it opened with 核心判断 three times in ten; humans never do
    colon_rate, ticker_density, question_rate

A target is a band, p10 to p90 of what that donor actually does, not a single number. Writing
inside someone's range is imitation; hitting their mean exactly would be a different artifact.

Run: .venv/bin/python -B live/style.py [--donor=qinbafrank]
"""
from pathlib import Path
import sys, json, importlib.util, random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np

_sp = importlib.util.spec_from_file_location(
    'style_mod', ROOT / '.agents/skills/financial-persona-distillation/scripts/stylometry.py')
style = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(style)

STORE = ROOT / 'live/store'
MIN_POSTS = 25

# Controllable, and the ones that gave the classifier its separation.
TARGET_FEATURES = [
    'sentence_mean', 'sentence_p25', 'long_argument_rate', 'fragment_rate',
    'first_person_rate', 'conclusion_opener', 'colon_rate', 'question_rate',
    'sentence_std',
]
# Which of those the gate enforces. conclusion_opener is binary per piece and enforced as a
# hard rule instead of a band.
# sentence_std is measured and reported but NOT gated, for two reasons that both had to hold:
#   1. the local model would not vary sentence length across four attempts and three phrasings of
#      the instruction, including a countable mix ("two under 15 characters, one over 80"). It
#      returned ten sentences of 33-47 characters. That is a model limit, not a prompt problem.
#   2. it is a length feature, and length was deliberately excluded from the transfer metric
#      because it belongs to the format rather than the voice. Gating an analysis piece on the
#      length variance of an X post asks it to imitate the wrong thing.
# Removing it from the gate is stated here rather than done quietly; the number still appears in
# every style_check and in ml/style_eval.py.
GATED = ['sentence_mean', 'sentence_p25', 'long_argument_rate', 'fragment_rate']
REPORTED_NOT_GATED = ['sentence_std', 'first_person_rate', 'colon_rate', 'question_rate']


CJK_RANGE = ('\u4e00', '\u9fff')


def guess_lang(text):
    """The archive stores no language field, so the donor tables read lang=None."""
    cjk = sum(CJK_RANGE[0] <= c <= CJK_RANGE[1] for c in text)
    return 'zh' if cjk / max(len(text), 1) > 0.12 else 'en'


def corpus(min_chars=120):
    """Archive plus everything the live collector has pulled since."""
    by = {}
    arch = ROOT / 'data/clean_posts.jsonl'
    if arch.exists():
        for line in arch.read_text().split('\n'):
            if not line.strip():
                continue
            r = json.loads(line)
            t = (r.get('analysis_text') or r.get('text') or '').strip()
            if len(t) >= min_chars:
                by.setdefault(r['source_account_id'], []).append(
                    {'text': t, 'lang': r.get('lang') or guess_lang(t), 'source': 'archive'})
    # The archive half went through the promotional cleaning the skill's contract describes; the
    # live half never did, and it shows — promotional wording runs 2.6% there against 1.3% in the
    # archive. Exemplars are drawn from this function, exemplars go into the prompt, and a draft
    # came back carrying its donor's "TAP IMAGE TO SEE FULL INSIGHT👇" and short link. Cleaning it
    # here means the writer never sees the advertisement in the first place.
    #
    # Working copies only: `live/store/posts.jsonl` is untouched and every removal keeps its
    # offsets, so nothing is lost and any cut can be audited.
    import clean as clean_mod
    live = STORE / 'posts.jsonl'
    if live.exists():
        for line in live.read_text().split('\n'):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get('is_retweet'):
                continue
            c = clean_mod.clean_post(r)
            if c['cleaning']['excluded'] or len(c['text']) < min_chars:
                continue
            lg = r.get('lang_reported')
            by.setdefault(r['handle'], []).append(
                {'text': c['text'],
                 'lang': lg if lg in ('zh', 'en') else guess_lang(c['text']),
                 'source': 'live',
                 'cleaned': bool(c['cleaning']['removed'])})
    return by


def band(values, lo=10, hi=90):
    return {'p10': float(np.percentile(values, lo)), 'p50': float(np.median(values)),
            'p90': float(np.percentile(values, hi))}


MIN_POSTS_FOR_CV_BAND = 30


def _cv_band(texts, lang):
    """This donor's own sentence-length variation, measured but not yet enforced.

    `content/tells.py` gates on one floor per language, taken from all donors pooled. That is not
    what this project says a style feature should be: a feature is supposed to carry its own
    range, sample size and method per donor. Measured per donor, three of the four assigned
    donors turn out to sit *above* the pooled floor —

        qinbafrank       p10 0.433   (pooled zh floor 0.330)   n=341
        globalmktobserv  p10 0.460   (pooled en floor 0.371)   n=77
        xingpt           p10 0.362   (pooled zh floor 0.330)   n=82
        beth_kindig      p10 0.231   (pooled en floor 0.371)   n=7

    so switching the gate to personal bands would tighten it for three accounts, not loosen it.
    It is recorded here and left unenforced on purpose: changing the threshold in the middle of a
    before-and-after measurement would make the comparison meaningless. beth_kindig also shows why
    a minimum matters — seven measurable posts cannot define a band, and hers is the only one that
    would have loosened the gate.
    """
    from content.tells import sentence_variation
    key = 'en' if (lang or '').lower().startswith('en') else 'zh'
    cv = sorted(c for c, _ in (sentence_variation(t, key) for t in texts) if c is not None)
    if len(cv) < MIN_POSTS_FOR_CV_BAND:
        return {'measurable_posts': len(cv), 'usable': False,
                'why': f'{len(cv)} measurable posts; {MIN_POSTS_FOR_CV_BAND} needed for a band'}
    def q(p):
        return round(cv[max(0, min(len(cv) - 1, int(p * len(cv))))], 3)
    return {'measurable_posts': len(cv), 'usable': True, 'enforced': False,
            'p10': q(.10), 'p50': q(.50), 'p90': q(.90),
            'method': 'content.tells.sentence_variation over this donor\'s own posts of 5+ '
                      'sentences; the same function the gate uses'}


def build_target(donor, posts, lang=None):
    texts = [p['text'] for p in posts if not lang or p.get('lang') == lang]
    if len(texts) < MIN_POSTS:
        return {'donor': donor, 'usable': False, 'n': len(texts),
                'why': f'only {len(texts)} posts of at least 120 characters; '
                       f'{MIN_POSTS} needed for a percentile band'}
    rows = [style.features(t) for t in texts]
    tgt = {k: band([r.get(k, 0.0) for r in rows]) for k in TARGET_FEATURES}
    return {
        'donor': donor, 'usable': True, 'n': len(texts), 'lang': lang,
        'sources': {'archive': sum(1 for p in posts if p['source'] == 'archive'),
                    'live': sum(1 for p in posts if p['source'] == 'live')},
        'targets': tgt,
        'sentence_cv': _cv_band(texts, lang),
        'gated_features': GATED,
        'method': 'stylometry.py over the donor\'s own posts; band is p10-p90, not a point',
        'never_opens_with_a_conclusion_label': float(
            np.mean([r['conclusion_opener'] for r in rows])) < 0.02,
    }


def instructions(target, lang='zh'):
    """The target in words a writer can act on."""
    if not target.get('usable'):
        return ''
    t = target['targets']
    sm, p25 = t['sentence_mean'], t['sentence_p25']
    frag, lng = t['fragment_rate'], t['long_argument_rate']
    fp = t['first_person_rate']
    if lang == 'zh':
        out = [f"句子平均长度落在 {sm['p10']:.0f}–{sm['p90']:.0f} 字之间（这位作者的中位数是 "
               f"{sm['p50']:.0f} 字）；不要每句都写得一样长。",
               f"**至少写 2 句在 20 字以内的短句**（例如「流动性没那么松。」这种长度）。"
               f"这位作者约 {max(frag['p50'], 0.15) * 100:.0f}% 的句子是这样的短句，"
               f"最短的四分之一句子平均只有 {p25['p50']:.0f} 字。",
               f"超过 120 字的长论述句占比不要超过 {max(lng['p90'], 0.02) * 100:.0f}%。"]
        # "vary your sentence length" produced six sentences within six characters of each
        # other, four attempts running. A countable mix is something the model can actually
        # execute.
        out.append(f"长短必须真的错开，按这个配比写："
                   f"**至少 2 句不超过 15 字**，**至少 1 句超过 {max(sm['p90'] * 1.6, 80):.0f} 字**，"
                   f"其余在 {sm['p10']:.0f}–{sm['p90']:.0f} 字之间。"
                   f"不要写出六句都差不多长的段落。")
        if fp['p50'] > 0.001:
            out.append("会用第一人称（我、我们）表达判断，不要通篇无人称。")
        if target.get('never_opens_with_a_conclusion_label'):
            out.append("**不要以「核心判断」「结论」「总的来说」这类标签开头**——这位作者从不这样写。")
        if t['question_rate']['p50'] > 0.0005:
            out.append("偶尔用一个反问推进论证。")
        return '这位作者的写作习惯（来自其真实帖子的实测区间）：\n' + '\n'.join('  · ' + x for x in out)
    out = [f"Mix the lengths for real: **at least two sentences of 15 characters or fewer**, "
           f"**at least one over {max(sm['p90'] * 1.6, 80):.0f}**, the rest between "
           f"{sm['p10']:.0f} and {sm['p90']:.0f}. Do not write six sentences of the same length.",
           f"Sentence length should sit between {sm['p10']:.0f} and {sm['p90']:.0f} characters "
           f"(this author's median is {sm['p50']:.0f}); vary it, do not write every sentence the "
           f"same length.",
           f"**Write at least two sentences under 20 characters** (\"Liquidity is tighter than "
           f"it looks.\" is that length). About {max(frag['p50'], 0.15) * 100:.0f}% of this "
           f"author's sentences are that short, and their shortest quarter average "
           f"{p25['p50']:.0f} characters.",
           f"Keep sentences over 120 characters below {max(lng['p90'], 0.02) * 100:.0f}%."]
    if fp['p50'] > 0.001:
        out.append("Use the first person for judgements.")
    if target.get('never_opens_with_a_conclusion_label'):
        out.append("**Do not open with a label like \"Core call:\" or \"Bottom line:\"** — this "
                   "author never does.")
    return ("How this author actually writes, measured from their own posts:\n"
            + '\n'.join('  - ' + x for x in out))


def check(text, target, tolerance=0.35):
    """Did the piece land inside the donor's own range?

    The band is widened by `tolerance` of its own width on each side: a writer working to someone
    else's habits should land in their range, not reproduce their median.
    """
    if not target.get('usable'):
        return {'checked': False, 'why': 'no usable target for this donor'}
    f = style.features(text)
    rows, misses = [], []
    observed = {k: round(float(f.get(k, 0.0)), 4) for k in REPORTED_NOT_GATED}
    for k in GATED:
        b = target['targets'][k]
        width = b['p90'] - b['p10']
        got = float(f.get(k, 0.0))
        # A band whose p10 and p90 are the same carries no information about how much this writer
        # varies on this feature — it collapses to "reproduce exactly this value", which is the
        # opposite of what the widening above is for. `globalmktobserv` has fragment_rate
        # p10 = p90 = 0, so the gate demanded literally zero fragments and blocked a draft for
        # writing the short sentences the sentence-length gate had asked it for: two gates in the
        # same system pulling against each other, one of them on no evidence at all. Reported,
        # not gated, on the same reasoning that left first_person_rate ungated when its p10 is 0.
        if width <= 0:
            rows.append({'feature': k, 'got': round(got, 4),
                         'band': [round(b['p10'], 4), round(b['p90'], 4)],
                         'allowed': None, 'ok': True, 'gated': False,
                         'why_not_gated': ('p10 equals p90: this donor shows no variation in this '
                                           'feature, so the band cannot say what variation is '
                                           'acceptable')})
            continue
        lo, hi = b['p10'] - tolerance * width, b['p90'] + tolerance * width
        ok = lo <= got <= hi
        rows.append({'feature': k, 'got': round(got, 4),
                     'band': [round(b['p10'], 4), round(b['p90'], 4)],
                     'allowed': [round(lo, 4), round(hi, 4)], 'ok': ok, 'gated': True})
        if not ok:
            misses.append({'feature': k, 'got': round(got, 4),
                           'want': [round(lo, 4), round(hi, 4)],
                           'direction': 'too high' if got > hi else 'too low'})
    if target.get('never_opens_with_a_conclusion_label') and f['conclusion_opener']:
        misses.append({'feature': 'conclusion_opener', 'got': 1.0, 'want': [0, 0],
                       'direction': 'this author never opens with a label'})
    return {'checked': True, 'donor': target['donor'], 'features': rows,
            'reported_not_gated': observed,
            'donor_bands_for_reported': {k: target['targets'][k] for k in REPORTED_NOT_GATED
                                         if k in target['targets']},
            'misses': misses, 'passed': not misses}


FAULT_ZH = {
    'sentence_mean': '句子平均长度{d}，目标 {lo:.0f}–{hi:.0f} 字。',
    'sentence_p25': '短句还不够短：最短的四分之一平均 {got:.0f} 字，目标 {lo:.0f}–{hi:.0f}。',
    'long_argument_rate': '超长句太多（{got:.0%}），目标不超过 {hi:.0%}。',
    'fragment_rate': '几乎没有短句（{got:.0%}），这位作者有 {lo:.0%}–{hi:.0%} 的句子在 20 字以内。',
    'sentence_std': '句子长度太{d}整齐（标准差 {got:.0f}，目标 {lo:.0f}–{hi:.0f}）。'
                    '真人写作是长短交错的：一句很短，下一句可以很长。',
    'conclusion_opener': '不要以「核心判断」「结论」这类标签开头，这位作者从不这样写。',
}
FAULT_EN = {
    'sentence_mean': 'Average sentence length is {d}; target {lo:.0f}-{hi:.0f} characters.',
    'sentence_p25': 'Short sentences are not short enough ({got:.0f}); target {lo:.0f}-{hi:.0f}.',
    'long_argument_rate': 'Too many very long sentences ({got:.0%}); keep under {hi:.0%}.',
    'fragment_rate': 'Almost no short lines ({got:.0%}); this author runs {lo:.0%}-{hi:.0%}.',
    'sentence_std': 'Sentence lengths are too even (sd {got:.0f}; target {lo:.0f}-{hi:.0f}). '
                    'Real writing alternates: one very short line, then a long one.',
    'conclusion_opener': 'Do not open with a label; this author never does.',
}


def faults(result, lang='zh'):
    tbl = FAULT_ZH if lang == 'zh' else FAULT_EN
    out = []
    for m in result.get('misses', []):
        t = tbl.get(m['feature'])
        if not t:
            continue
        lo, hi = m['want']
        d = ('偏长' if m['direction'] == 'too high' else '偏短') if lang == 'zh' else m['direction']
        out.append(t.format(d=d, got=m['got'], lo=lo, hi=hi))
    return out


_EMBED = None


def _embedder():
    """The frozen multilingual model this project already uses for retrieval."""
    global _EMBED
    if _EMBED is None:
        import os
        os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                          TOKENIZERS_PARALLELISM='false')
        from sentence_transformers import SentenceTransformer
        _EMBED = SentenceTransformer(str(ROOT / '.runtime/models/embedding'), device='cpu',
                                     local_files_only=True, trust_remote_code=False)
    return _EMBED


def exemplars(posts, k=3, seed=0, lang=None, topic=None, vary=True):
    """The donor's own posts, chosen for closeness to what is being written about — and, among
    those, for the rhythm the writer has to learn.

    Thickening the exemplars moved discriminability more than the numeric bands did, which says
    the examples are the strongest lever here. Drawing them at random wastes it: six posts about
    unrelated names teach the rhythm but give the writer nothing to pattern the argument on.
    Retrieval uses the frozen embedding this project already runs, so nothing new is introduced.

    Ranking on topic alone wastes the lever a second way. The sentence-length floor is the one
    gate the local writer keeps failing — it needed seven attempts to clear it once and never
    cleared it twice — while the prompt around it was showing six real posts that happened to be
    evenly paced. Telling a model to vary its sentence length and then handing it uniform examples
    asks it to ignore what it can see in favour of what it is told.

    So the topical shortlist is widened to 3k and the k with the most varied pacing are taken from
    it. These are the donor's own posts either way; nothing is synthesised and no post is edited.
    Topical closeness still decides which posts are eligible, which is what it was measured to be
    good for.
    """
    pool = [p['text'] for p in posts if (not lang or p.get('lang') == lang)
            and 200 <= len(p['text']) <= 1600]
    if len(pool) < k:
        pool = [p['text'] for p in posts if not lang or p.get('lang') == lang]
    if not pool:
        return []
    if not topic or len(pool) <= k:
        return random.Random(seed).sample(pool, min(k, len(pool)))
    try:
        import numpy as np
        m = _embedder()
        pv = m.encode(pool, batch_size=32, show_progress_bar=False,
                      normalize_embeddings=True)
        qv = m.encode([topic], show_progress_bar=False, normalize_embeddings=True)[0]
        order = [int(i) for i in np.argsort(-(pv @ qv))]
        if not vary:
            return [pool[i] for i in order[:k]]
        shortlist = [pool[i] for i in order[:min(3 * k, len(order))]]
        scored = sorted(shortlist, key=lambda t: -_pacing(t, lang))
        return scored[:k]
    except Exception:
        return random.Random(seed).sample(pool, min(k, len(pool)))


def _pacing(text, lang=None):
    """Coefficient of variation of sentence length — the same measure the gate enforces.

    Imported from the gate rather than reimplemented, because a band and the thing that selects
    for it drifting apart is exactly how the first sentence-length threshold came out invalid.
    """
    from content.tells import sentence_variation
    zh = not (lang or '').lower().startswith('en')
    cv, _ = sentence_variation(text, 'zh' if zh else 'en')
    return cv or 0.0


def load_all(min_posts=MIN_POSTS):
    by = corpus()
    out = {}
    for donor, posts in by.items():
        langs = {}
        for p in posts:
            langs[p.get('lang')] = langs.get(p.get('lang'), 0) + 1
        main_lang = max(langs, key=langs.get) if langs else None
        out[donor] = build_target(donor, posts, lang=main_lang)
        out[donor]['dominant_lang'] = main_lang
        out[donor]['all_posts'] = len(posts)
    return out


def main():
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    tg = load_all()
    (STORE / 'style_targets.json').write_text(json.dumps(tg, ensure_ascii=False, indent=2))
    print(f"{'donor':20} {'lang':5} {'n':>5}  {'句长中位':>8} {'短句率':>7} {'长句率':>7}  可用")
    for d, t in sorted(tg.items(), key=lambda kv: -kv[1].get('n', 0)):
        if not t.get('usable'):
            print(f"  {d:18} {str(t.get('dominant_lang')):5} {t['n']:>5}  {'—':>8} {'—':>7} {'—':>7}  否 · {t['why'][:38]}")
            continue
        s = t['targets']
        print(f"  {d:18} {str(t.get('lang')):5} {t['n']:>5}  "
              f"{s['sentence_mean']['p50']:>8.0f} {s['fragment_rate']['p50']:>7.2f} "
              f"{s['long_argument_rate']['p50']:>7.2f}  是")
    if args.get('donor') and tg.get(args['donor'], {}).get('usable'):
        print()
        print(instructions(tg[args['donor']],
                          'zh' if tg[args['donor']].get('lang') == 'zh' else 'en'))
    return tg


if __name__ == '__main__':
    main()
