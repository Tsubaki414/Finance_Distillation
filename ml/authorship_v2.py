"""Author attribution v2: strict time split, near-duplicate isolation, per-slice metrics.

Decides which donors are distinguishable enough to act as a language donor. A donor whose posts a
classifier cannot separate from the others cannot carry a persona voice, so this feeds directly
into role assignment rather than sitting in a report.

Differences from v1:
  - near duplicates isolated, not only exact text and thread duplicates
  - language-only and majority baselines reported alongside, so a headline number cannot hide
    that language alone explains much of the separation
  - per-donor and per-language slices
  - bootstrap CI on macro-F1
  - a minimum test support rule, below which a donor is reported as undetermined

Run: .venv/bin/python -B ml/authorship_v2.py
"""
from pathlib import Path
import sys, json, os, re, hashlib, datetime, unicodedata, collections, importlib.util
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ml_experiments'
SEED = 42
MIN_TRAIN, MIN_TEST = 40, 12
NEAR_DUP_COSINE = 0.92

sp = importlib.util.spec_from_file_location(
    'stylo', ROOT / '.agents/skills/financial-persona-distillation/scripts/stylometry.py')
stylo = importlib.util.module_from_spec(sp); sp.loader.exec_module(stylo)


def norm(t):
    t = unicodedata.normalize('NFKC', t or '')
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'@[\w_]+', '', t)
    return re.sub(r'[^\w一-鿿]', '', t).lower()


def mask(t):
    """Remove the giveaways that let a classifier cheat: cashtags, links, handles."""
    return re.sub(r'\$[A-Za-z]{1,6}\b|https?://\S+|@[\w_]+', ' ', t or '')


def embed(texts):
    os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(str(ROOT / '.runtime/models/embedding'), device='cpu',
                            local_files_only=True, trust_remote_code=False)
    return m.encode(texts, batch_size=64, show_progress_bar=False,
                    normalize_embeddings=True).astype(np.float32)


def macro_f1(y, p, labels):
    fs = []
    for c in labels:
        tp = sum(1 for a, b in zip(y, p) if a == c and b == c)
        fp = sum(1 for a, b in zip(y, p) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, p) if a == c and b != c)
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        fs.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    return float(np.mean(fs))


def _guess_lang(text):
    """Script-based, because the two corpora label language differently and the live collector
    often reports nothing. The script itself keys on `language`; the merged loader wrote `lang`,
    which silently collapsed the language-only baseline onto the majority baseline and made
    per-language slices report a single bucket called "None" — the exact leakage the contract
    asks these slices to expose."""
    cjk = sum(1 for c in (text or '') if '\u4e00' <= c <= '\u9fff')
    return 'zh' if cjk / max(len(text or ''), 1) > 0.12 else 'en'


def _naive(stamp):
    """UTC without a tzinfo. The archive stores naive timestamps and the live collector stores
    aware ones; sorting a merged list raised before either could be compared."""
    try:
        dt = datetime.datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def load_rows(which='merged'):
    """Posts in one shape, from the archive, the live store, or both.

    These two corpora had silently diverged. `live/style.py::corpus()` — which builds every style
    band and picks every exemplar — reads archive **plus** live, 5,081 posts. This file read the
    archive alone, 1,825 posts frozen on 6 September. So a thousand newly collected posts changed
    every style band and changed nothing here, and re-running this after a collection produced
    byte-identical numbers, which is how the divergence was finally noticed.

    Worse, only six donors ever cleared the support thresholds on the archive, so fifty accounts
    on the learning list have never been evaluated for separability at all — including every
    English candidate but one.

    Live rows go through live/clean.py first, for the same reason the style corpus does: the
    archive was cleaned of promotional furniture and the live store never was.
    """
    rows = []
    if which in ('archive', 'merged'):
        for line in (ROOT / 'data/clean_posts.jsonl').read_text().split('\n'):
            if not line.strip():
                continue
            r = json.loads(line)
            txt = (r.get('analysis_text') or r.get('text') or '').strip()
            if len(txt) >= 80 and _naive(r['created_at']) is not None:
                rows.append({'text': txt, 'created_at': r['created_at'],
                             'source_account_id': r['source_account_id'],
                             'thread_id': r.get('thread_id'),
                             'language': r.get('language') or r.get('lang')
                             or _guess_lang(txt),
                             'corpus': 'archive',
                             '_dt': _naive(r['created_at'])})
    if which in ('live', 'merged'):
        sys.path.insert(0, str(ROOT / 'live'))
        import clean as clean_mod
        for line in (ROOT / 'live/store/posts.jsonl').read_text().split('\n'):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('is_retweet'):
                continue
            c = clean_mod.clean_post(r)
            txt = (c.get('text') or '').strip()
            if len(txt) < 80 or c['cleaning']['excluded']:
                continue
            dt = _naive(r['created_at'])
            if dt is None:
                continue
            rows.append({'text': txt, 'created_at': r['created_at'],
                         'source_account_id': r['handle'],
                         'thread_id': r.get('conversation_id') or r.get('post_id'),
                         'language': (r.get('lang_reported')
                                      if r.get('lang_reported') in ('zh', 'en')
                                      else _guess_lang(txt)),
                         'corpus': 'live',
                         '_dt': dt})
    return rows


def main():
    rng = np.random.default_rng(SEED)
    which = next((a.split('=', 1)[1] for a in sys.argv[1:]
                  if a.startswith('--corpus=')), 'merged')
    rows = load_rows(which)
    print(f'corpus={which}  rows={len(rows)}  '
          f"authors={len({r['source_account_id'] for r in rows})}")

    # ---- near-duplicate isolation ------------------------------------------------------
    texts = [r['text'] for r in rows]
    vecs = embed(texts)
    parent = list(range(len(rows)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_hash = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_hash[norm(r['text'])].append(i)
        by_hash['thread:' + str(r.get('thread_id'))].append(i)
    for grp in by_hash.values():
        for j in grp[1:]:
            union(grp[0], j)
    # semantic near duplicates, checked in blocks to stay cheap
    for i in range(len(rows)):
        sims = vecs[i] @ vecs[i + 1:i + 60].T if i + 1 < len(rows) else np.array([])
        for off, s in enumerate(sims):
            if s >= NEAR_DUP_COSINE:
                union(i, i + 1 + off)
    for i in range(len(rows)):
        rows[i]['_group'] = find(i)

    # ---- per-author chronological split, groups never straddle the boundary -------------
    by_author = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_author[r['source_account_id']].append(i)

    train_idx, test_idx, detail = [], [], []
    for author, idxs in by_author.items():
        idxs.sort(key=lambda i: rows[i]['_dt'])
        cut = int(len(idxs) * 0.8)
        tr, te = idxs[:cut], idxs[cut:]
        tr_groups = {rows[i]['_group'] for i in tr}
        te = [i for i in te if rows[i]['_group'] not in tr_groups]   # leakage guard
        eligible = len(tr) >= MIN_TRAIN and len(te) >= MIN_TEST
        detail.append({'author': author, 'train': len(tr), 'test': len(te),
                       'eligible': eligible,
                       'dropped_for_group_leak': len(idxs) - cut - len(te),
                       'last_train': rows[tr[-1]]['_dt'].isoformat() if tr else None,
                       'first_test': rows[te[0]]['_dt'].isoformat() if te else None})
        if eligible:
            train_idx += tr
            test_idx += te

    classes = sorted({rows[i]['source_account_id'] for i in train_idx})
    ytr = [rows[i]['source_account_id'] for i in train_idx]
    yte = [rows[i]['source_account_id'] for i in test_idx]

    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    feats = {i: stylo.features(mask(rows[i]['text'])) for i in train_idx + test_idx}
    keys = sorted(feats[train_idx[0]])
    A = np.array([[feats[i][k] for k in keys] for i in train_idx + test_idx], dtype=float)
    A = np.nan_to_num(A)
    ntr = len(train_idx)

    preds = {}
    sty = make_pipeline(StandardScaler(), LogisticRegression(max_iter=800, class_weight='balanced',
                                                             random_state=SEED))
    sty.fit(A[:ntr], ytr)
    preds['stylometry'] = list(sty.predict(A[ntr:]))

    emb = LogisticRegression(max_iter=800, class_weight='balanced', random_state=SEED)
    emb.fit(vecs[train_idx], ytr)
    preds['embedding'] = list(emb.predict(vecs[test_idx]))

    comb = np.hstack([A, np.vstack([vecs[i] for i in train_idx + test_idx])])
    cmb = make_pipeline(StandardScaler(), LogisticRegression(max_iter=800, class_weight='balanced',
                                                             random_state=SEED))
    cmb.fit(comb[:ntr], ytr)
    preds['combined'] = list(cmb.predict(comb[ntr:]))

    # baselines that keep the headline honest
    major = collections.Counter(ytr).most_common(1)[0][0]
    preds['majority_baseline'] = [major] * len(yte)
    lang_map = {}
    for i in train_idx:
        lang_map.setdefault(rows[i].get('language'), collections.Counter())[rows[i]['source_account_id']] += 1
    preds['language_only_baseline'] = [
        lang_map.get(rows[i].get('language'), collections.Counter(ytr)).most_common(1)[0][0]
        for i in test_idx]

    def boot(y, p, B=1500):
        s = []
        for _ in range(B):
            k = rng.integers(0, len(y), len(y))
            s.append(macro_f1([y[i] for i in k], [p[i] for i in k], classes))
        lo, hi = np.quantile(s, [0.025, 0.975])
        return {'lower': round(float(lo), 4), 'upper': round(float(hi), 4)}

    models = {}
    for name, p in preds.items():
        acc = sum(1 for a, b in zip(yte, p) if a == b) / max(len(yte), 1)
        models[name] = {'accuracy': round(acc, 4),
                        'macro_f1': round(macro_f1(yte, p, classes), 4),
                        'bootstrap_macro_f1': boot(yte, p)}

    best = preds['combined']
    per_author = {}
    for c in classes:
        idx = [i for i, y in enumerate(yte) if y == c]
        per_author[c] = {'test_n': len(idx),
                         'recall': round(sum(1 for i in idx if best[i] == c) / max(len(idx), 1), 4),
                         'confused_with': collections.Counter(
                             best[i] for i in idx if best[i] != c).most_common(2)}
    per_lang = {}
    for lang in sorted({rows[i].get('language') for i in test_idx}):
        idx = [k for k, i in enumerate(test_idx) if rows[i].get('language') == lang]
        if len(idx) >= 10:
            per_lang[str(lang)] = {'test_n': len(idx),
                                   'accuracy': round(sum(1 for k in idx if best[k] == yte[k]) / len(idx), 4)}

    usable = [c for c in classes if per_author[c]['recall'] >= 0.5 and per_author[c]['test_n'] >= MIN_TEST]

    payload = {
        'run_id': 'auth2-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S'),
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'product_question': 'Which donors are distinguishable enough to carry a persona voice?',
        'corpus': which,
        'dataset': {'file': ('data/clean_posts.jsonl' if which == 'archive'
                             else 'data/clean_posts.jsonl + live/store/posts.jsonl (cleaned)'),
                    'sha256': hashlib.sha256((ROOT / 'data/clean_posts.jsonl').read_bytes()).hexdigest(),
                    'rows_used': len(rows)},
        'split': {'method': 'per-author chronological 80/20',
                  'leakage_guards': ['exact normalised text', 'thread id',
                                     f'semantic near duplicate cosine >= {NEAR_DUP_COSINE}'],
                  'group_units': len({r['_group'] for r in rows}),
                  'min_train': MIN_TRAIN, 'min_test': MIN_TEST,
                  'train_n': len(train_idx), 'test_n': len(test_idx)},
        'feature_masking': 'cashtags, links and handles removed before stylometry',
        'eligible_authors': classes, 'author_detail': detail,
        'models': models,
        'per_author': per_author, 'per_language': per_lang,
        'usable_as_language_donor': usable,
        'undetermined': [c for c in classes if c not in usable],
        'seed': SEED,
        'limits': [
            'Associational. Topic and time may still carry part of the signal.',
            'Bootstrap resamples test posts, so within-author dependence is not fully captured.',
            'This says donors are separable, not that a generated persona is recognisable.',
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    # The archive-only result stays where it is. A merged run writes beside it rather than over
    # it, so the two corpora remain comparable and the frozen number is never lost.
    name = 'authorship_v2.json' if which == 'archive' else f'authorship_{which}.json'
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f'wrote {OUT / name}')
    print(json.dumps({k: v for k, v in payload.items()
                      if k not in ('author_detail', 'per_author')}, ensure_ascii=False, indent=1))
    print('\nper author recall:')
    for c, v in per_author.items():
        print(f"  {c:18} n={v['test_n']:3} recall={v['recall']:.3f}  confused={v['confused_with']}")
    return payload


if __name__ == '__main__':
    main()
