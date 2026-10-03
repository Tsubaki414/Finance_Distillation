"""Does the generated writing carry the donor's language, and how far is it from a real post?

Two questions, both answered by measurement rather than by looking at the output and deciding it
reads well:

  transfer         for each generated piece, rank the twelve donors by how close the piece's
                   stylometric profile sits to theirs. If the assigned language donor does not
                   rank near the top, the donor's language did not transfer and calling it
                   distillation would be false. Chance is 1/12.

  discriminability train a classifier to separate human posts from generated pieces under
                   cross-validation. High accuracy means a reader could tell too. Reported both
                   on all features and on length-controlled shape features only, because a
                   generated analysis and a one-line post differ in length for reasons that have
                   nothing to do with voice.

Run: .venv/bin/python -B ml/style_eval.py
"""
from pathlib import Path
import sys, json, glob, re, importlib.util, statistics, random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np

_sp = importlib.util.spec_from_file_location(
    'style', ROOT / '.agents/skills/financial-persona-distillation/scripts/stylometry.py')
style = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(style)

# Length and volume are properties of the format, not the voice. A 900-character analysis and a
# 40-character quip differ on these no matter who wrote them.
LENGTH_BOUND = {'char_count', 'sentence_count', 'paragraph_count', 'paragraph_mean',
                'sentence_mean', 'sentence_std', 'sentence_p25', 'sentence_p75'}


def human_posts(min_chars=120):
    """The same corpus the style targets are built from.

    Reading only the archive here while live/style.py reads archive plus the live store meant the
    two English donors had targets but could not appear in the ranking, and every English piece
    reported "assigned donor not found".
    """
    sys.path.insert(0, str(ROOT / 'live'))
    import style as style_mod
    by = {}
    for donor, posts in style_mod.corpus(min_chars).items():
        by[donor] = [p['text'] for p in posts]
    return by


def generated():
    out = []
    for p in sorted(glob.glob(str(ROOT / 'content/drafts/*.json'))):
        d = json.loads(Path(p).read_text())
        if d.get('text'):
            out.append({'id': d['id'], 'text': d['text'], 'origin': 'curated_pipeline',
                        'persona': d.get('persona_id'),
                        'language_donor': (d.get('roles') or {}).get('language')})
    for p in sorted(glob.glob(str(ROOT / 'live/store/drafts/*.json'))):
        d = json.loads(Path(p).read_text())
        if d.get('text'):
            out.append({'id': d['id'], 'text': d['text'], 'origin': 'live_pipeline',
                        'persona': d.get('persona_id'),
                        'account': d.get('account_id'),
                        'language_donor': d.get('language_donor'),
                        'style_status': d.get('style_status')})
    return out


# ---------------------------------------------------------------- Burrows' Delta
#
# The feature set above is hand-picked by me, which makes it hard to know whether a result is a
# property of the writing or of my choice of features. Burrows' Delta is the standard authorship
# measure and picks nothing: it takes the most frequent tokens in the corpus, z-scores their
# relative frequencies across authors, and calls the mean absolute difference the distance.
# Method borrowed from faststylometry (fastdatascience/faststylometry); the package itself is not
# installed because it pins numpy 1.26 and this environment is frozen at 2.x.
#
# Chinese has no whitespace tokens, so character bigrams stand in for words. That is the usual
# substitute and needs no segmenter.

CJK_CH = re.compile(r'[\u4e00-\u9fff]')
WORD_TOKEN = re.compile(r"[A-Za-z']+")


def tokens(text):
    t = re.sub(r'https?://\S+|@[\w_]+', ' ', text or '')
    cjk = CJK_CH.findall(t)
    if len(cjk) > 0.12 * max(len(t), 1):
        chars = [c for c in t if CJK_CH.match(c)]
        return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return [w.lower() for w in WORD_TOKEN.findall(t)]


def delta_space(corpus_by_author, top_n=220):
    """Return (vocabulary, per-author z-vectors, mean, std) over the most frequent tokens."""
    from collections import Counter
    total = Counter()
    per = {}
    for a, texts in corpus_by_author.items():
        c = Counter()
        for t in texts:
            c.update(tokens(t))
        per[a] = c
        total.update(c)
    vocab = [w for w, _ in total.most_common(top_n)]
    rows, names = [], []
    for a, c in per.items():
        n = max(sum(c.values()), 1)
        rows.append([c.get(w, 0) / n for w in vocab])
        names.append(a)
    M = np.array(rows)
    mu, sd = M.mean(0), M.std(0) + 1e-12
    return vocab, {a: (M[i] - mu) / sd for i, a in enumerate(names)}, mu, sd


def delta_vec(text, vocab, mu, sd):
    from collections import Counter
    c = Counter(tokens(text))
    n = max(sum(c.values()), 1)
    v = np.array([c.get(w, 0) / n for w in vocab])
    return (v - mu) / sd


def delta_rank(text, vocab, authors, mu, sd, restrict_lang=None, lang_of=None):
    v = delta_vec(text, vocab, mu, sd)
    rows = []
    for a, z in authors.items():
        if restrict_lang and lang_of and lang_of.get(a) != restrict_lang:
            continue
        rows.append((a, float(np.abs(v - z).mean())))
    rows.sort(key=lambda r: r[1])
    return rows


def vec(text, keys):
    f = style.features(text)
    return np.array([float(f.get(k, 0.0)) for k in keys])


def feature_keys():
    probe = style.features('这是一段用于确定特征顺序的示例文本。它包含数字 12.3% 与一个问句吗？')
    return sorted(probe.keys())


def donor_stats(by, keys):
    """Mean and spread per donor, plus how far that donor's own posts sit from their centre.

    A feature a donor never varies has zero spread, and `std + 1e-9` turned a one-unit difference
    into a z of 10^9 — the donor-distinctiveness table printed distances in the billions. The
    floor is now the feature's spread across everybody, so an unused feature contributes a
    normal-sized difference instead of dominating the metric.

    `self_dist` is what makes the result interpretable: a closed-set ranking punishes a piece for
    imitating a donor whose neighbours write almost identically, which says more about the donor
    than about the imitation. Knowing where a piece falls inside the donor's *own* spread answers
    "does this look like something they wrote" directly.
    """
    all_M = np.array([vec(t, keys) for texts in by.values() for t in texts])
    floor = all_M.std(0) * 0.05 + 1e-6
    out = {}
    for donor, texts in by.items():
        if len(texts) < 25:
            continue
        M = np.array([vec(t, keys) for t in texts])
        mean = M.mean(0)
        std = np.maximum(M.std(0), floor)
        z = (M - mean) / std
        self_dist = np.sqrt((z ** 2).mean(axis=1))
        out[donor] = {'mean': mean, 'std': std, 'n': len(texts),
                      'self_dist': self_dist}
    return out


def rank_donors(v, stats, keys, restrict=None):
    """Standardised distance to each donor, in that donor's own scale."""
    rows = []
    idx = [i for i, k in enumerate(keys) if not restrict or k in restrict]
    for donor, s in stats.items():
        z = (v[idx] - s['mean'][idx]) / s['std'][idx]
        rows.append((donor, float(np.sqrt((z ** 2).mean()))))
    rows.sort(key=lambda r: r[1])
    return rows


def cross_val_accuracy(X, y, folds=5, seed=0):
    """Logistic regression, stratified, no sklearn dependency assumptions beyond what is present."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import roc_auc_score
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    accs, aucs = [], []
    for tr, te in skf.split(X, y):
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(max_iter=2000, class_weight='balanced'))
        m.fit(X[tr], y[tr])
        p = m.predict(X[te])
        accs.append(float((p == y[te]).mean()))
        try:
            aucs.append(float(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1])))
        except ValueError:
            pass
    return {'accuracy': round(float(np.mean(accs)), 4),
            'auc': round(float(np.mean(aucs)), 4) if aucs else None,
            'folds': folds}


def main():
    keys = feature_keys()
    by = human_posts()
    stats = donor_stats(by, keys)
    gen = generated()
    if not gen:
        print('no generated pieces found')
        return

    shape_keys = [k for k in keys if k not in LENGTH_BOUND]

    # ---- transfer: does a piece sit closest to the donor it was assigned?
    transfer = []
    for g in gen:
        v = vec(g['text'], keys)
        ranking = rank_donors(v, stats, keys, restrict=set(shape_keys))
        order = [d for d, _ in ranking]
        rec = {'id': g['id'], 'origin': g['origin'], 'persona': g['persona'],
               'assigned_language_donor': g['language_donor'],
               'nearest_donor': order[0], 'nearest_distance': round(ranking[0][1], 3)}
        if g['language_donor'] in order:
            rec['assigned_donor_rank'] = order.index(g['language_donor']) + 1
            dist = dict(ranking)[g['language_donor']]
            rec['assigned_donor_distance'] = round(dist, 3)
            # Where this piece falls inside the donor's own spread. 50 is as typical as their
            # median post; above 95 means it sits outside almost everything they write.
            own = stats[g['language_donor']]['self_dist']
            idx = [i for i, k in enumerate(keys) if k in set(shape_keys)]
            s = stats[g['language_donor']]
            zz = (vec(g['text'], keys)[idx] - s['mean'][idx]) / s['std'][idx]
            d_shape = float(np.sqrt((zz ** 2).mean()))
            own_shape = []
            for txt in by[g['language_donor']]:
                zq = (vec(txt, keys)[idx] - s['mean'][idx]) / s['std'][idx]
                own_shape.append(float(np.sqrt((zq ** 2).mean())))
            rec['percentile_within_donor'] = round(
                100.0 * float(np.mean([d_shape > x for x in own_shape])), 1)
            rec['inside_donor_range'] = rec['percentile_within_donor'] <= 95.0
        transfer.append(rec)

    ranked = [t for t in transfer if t.get('assigned_donor_rank')]
    top1 = sum(1 for t in ranked if t['assigned_donor_rank'] == 1)
    top3 = sum(1 for t in ranked if t['assigned_donor_rank'] <= 3)

    # ---- discriminability: human vs generated
    # 398 human posts against 10 generated pieces makes the majority-class baseline 0.975, so
    # accuracy carries no information. The classes are balanced instead and AUC is the headline.
    rnd = random.Random(11)
    pool = [(t, d) for d, texts in by.items() for t in texts]
    rnd.shuffle(pool)
    human_sample = pool[:max(len(gen), 8)]
    Xh = np.array([vec(t, keys) for t, _ in human_sample])
    Xg = np.array([vec(g['text'], keys) for g in gen])
    X = np.vstack([Xh, Xg])
    y = np.array([0] * len(Xh) + [1] * len(Xg))

    idx_shape = [i for i, k in enumerate(keys) if k in set(shape_keys)]
    folds = max(2, min(5, min(int((y == 0).sum()), int((y == 1).sum()))))
    disc_all = cross_val_accuracy(X, y, folds=folds)
    disc_shape = cross_val_accuracy(X[:, idx_shape], y, folds=folds)
    baseline = max(float((y == 0).mean()), float((y == 1).mean()))

    # ---- where the gap is widest, in the donors' own units
    # A feature no human ever uses has zero spread, and dividing by 1e-9 printed z = 3e8. Report
    # those as "human never does this" instead of a meaningless number.
    hm, hs = Xh.mean(0), Xh.std(0)
    never = [keys[i] for i in range(len(keys)) if hs[i] == 0 and Xg.mean(0)[i] != 0]
    hs = np.where(hs == 0, np.nan, hs)
    z_all = (Xg.mean(0) - hm) / hs
    gaps = sorted((z_all[i], keys[i]) for i in range(len(keys)) if np.isfinite(z_all[i]))
    widest = [{'feature': k, 'z_vs_human': round(float(z), 2),
               'human_mean': round(float(hm[keys.index(k)]), 5),
               'generated_mean': round(float(Xg.mean(0)[keys.index(k)]), 5)}
              for z, k in (gaps[:6] + gaps[-6:])]

    out = {
        'computed_at': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat(),
        'donors_profiled': {d: s['n'] for d, s in stats.items()},
        'generated_pieces': len(gen),
        'human_posts_sampled': len(human_sample),
        'features': len(keys), 'shape_features_used_for_transfer': len(shape_keys),
        'transfer': {
            'percentile_note': ('percentile_within_donor is where the piece sits inside that '
                                'donor\'s own spread: 50 is as typical as their median post, '
                                'above 95 is outside nearly everything they write. A closed-set '
                                'rank punishes imitating a donor whose neighbours write the same '
                                'way, which is a fact about the donor, not the imitation'),
            'note': ('closest donor is computed on shape features only; length and volume are '
                     'properties of the format, not the voice'),
            'pieces_with_an_assigned_language_donor': len(ranked),
            'assigned_donor_ranked_first': top1,
            'assigned_donor_in_top_3': top3,
            'chance_top1': round(1 / max(len(stats), 1), 4),
            'detail': transfer,
        },
        'discriminability': {
            'majority_class_baseline': round(baseline, 4),
            'all_features': disc_all,
            'shape_features_only': disc_shape,
            'balanced': True,
            'meaning': ('classes are balanced, so 0.5 is chance. Near 0.5 would mean generated '
                        'text is indistinguishable from a human post; near 1.0 means a classifier '
                        'separates them trivially'),
        },
        'widest_feature_gaps': widest,
        'human_never_does_this': never,
    }
    (ROOT / 'ml/style_eval.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"donors profiled: {len(stats)}  generated: {len(gen)}  human sampled: {len(human_sample)}")
    print(f"\n[语言迁移] 被指派 donor 排第 1: {top1}/{len(ranked)}  "
          f"进前 3: {top3}/{len(ranked)}  随机基线 {1/max(len(stats),1):.2f}")
    for t in transfer:
        a = t.get('assigned_language_donor') or '—'
        r = t.get('assigned_donor_rank')
        pc = t.get('percentile_within_donor')
        print(f"   {t['origin']:16} 指派={a:16} 排名={str(r) if r else '—':>3} "
              f"落在该作者自身分布的 {str(pc) + '%' if pc is not None else '—':>6} "
              f"{'（在其常写范围内）' if t.get('inside_donor_range') else ''}")
    print(f"\n[可分辨性] 多数类基线 {baseline:.3f}")
    print(f"   全部特征   accuracy {disc_all['accuracy']:.3f}  AUC {disc_all['auc']}")
    print(f"   仅形状特征 accuracy {disc_shape['accuracy']:.3f}  AUC {disc_shape['auc']}")
    if never:
        print(f"\n[真人从不这样、机器会] {never}")
    print("\n[差距最大的特征]")
    for w in widest:
        print(f"   {w['feature']:26} z={w['z_vs_human']:>6}  人={w['human_mean']:<10} 机={w['generated_mean']}")
    return out


if __name__ == '__main__':
    main()
