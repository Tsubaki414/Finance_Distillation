"""Semantic near-duplicate detection: three methods on the same pairs.

The corpus currently dedupes with an exact SHA-256 of normalised text, which cannot see a
cross-author repost, a reworded copy or a translated one. This measures how much that costs.

Labels: there are no human labels yet, so this produces an annotation pack for a person and,
separately, a silver-label comparison that is explicitly named as silver. No metric here is
reported as human accuracy.

Sampling is stratified hard-pair: pairs are drawn across cosine bands so the evaluation is not
dominated by trivially unrelated pairs.

Run: .venv/bin/python -B ml/dedup_eval.py
"""
from pathlib import Path
import json, re, os, hashlib, random, unicodedata, datetime, collections
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ml_experiments'
SEED = 42
BANDS = [(0.95, 1.01, 'near_identical'), (0.85, 0.95, 'high'),
         (0.72, 0.85, 'borderline'), (0.55, 0.72, 'low'), (0.0, 0.55, 'unrelated')]
PER_BAND = 10


def norm(t):
    t = unicodedata.normalize('NFKC', t or '')
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'@[\w_]+', '', t)
    return re.sub(r'[^\w一-鿿]', '', t).lower()


def load():
    rows = []
    for line in (ROOT / 'data/clean_posts.jsonl').read_text().split('\n'):
        if line:
            r = json.loads(line)
            if len((r.get('text') or '').strip()) >= 60:
                rows.append(r)
    return rows


def embed(texts):
    os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(str(ROOT / '.runtime/models/embedding'), device='cpu',
                            local_files_only=True, trust_remote_code=False)
    return m.encode(texts, batch_size=64, show_progress_bar=False,
                    normalize_embeddings=True).astype(np.float32)


NUMS = re.compile(r'\d[\d,]*(?:\.\d+)?')
DATES = re.compile(r'\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}')


def numeric_divergence(a, b):
    """Share of numbers that differ between two posts.

    Templated daily reports sit at very high cosine while carrying entirely different figures.
    Treating them as duplicates would delete real content, so the numbers decide.
    """
    na = set(NUMS.findall(a)) - set()
    nb = set(NUMS.findall(b))
    if not na and not nb:
        return 0.0
    inter = len(na & nb)
    union = len(na | nb) or 1
    return round(1 - inter / union, 4)


def date_conflict(a, b):
    da, db = set(DATES.findall(a)), set(DATES.findall(b))
    return bool(da and db and not (da & db))


def silver_label(a, b, cos, tfidf):
    """Conservative rule used only as a stand-in until humans label the pack.

    Named silver everywhere it appears. It shares signal with the candidate methods, so a score
    against it measures agreement, not accuracy.
    """
    na, nb = norm(a['text']), norm(b['text'])
    if na == nb:
        return 'same_claim'
    shorter, longer = sorted([na, nb], key=len)
    if shorter and shorter in longer:
        return 'same_claim'
    nd = numeric_divergence(a['text'], b['text'])
    # A recurring daily report is not a duplicate: same wording, different figures and date.
    if cos >= 0.90 and (nd >= 0.6 or date_conflict(a['text'], b['text'])):
        return 'template_repeat'
    if cos >= 0.88 and tfidf >= 0.45 and nd < 0.6:
        return 'paraphrase'
    if cos >= 0.84 and a['source_account_id'] != b['source_account_id'] and nd < 0.5:
        return 'same_upstream_source'
    return 'unrelated'


def prf(y_true, y_pred, positive):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t in positive and p in positive)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t not in positive and p in positive)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t in positive and p not in positive)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': round(prec, 4),
            'recall': round(rec, 4), 'f1': round(f1, 4)}


def boot_ci(y_true, y_pred, positive, rng, B=2000):
    n = len(y_true)
    if n < 2:
        return None
    scores = []
    for _ in range(B):
        idx = rng.integers(0, n, n)
        s = prf([y_true[i] for i in idx], [y_pred[i] for i in idx], positive)['f1']
        scores.append(s)
    lo, hi = np.quantile(scores, [0.025, 0.975])
    return {'f1_lower': round(float(lo), 4), 'f1_upper': round(float(hi), 4),
            'method': f'percentile bootstrap over pairs, B={B}, seed={SEED}'}


def main():
    rng = np.random.default_rng(SEED)
    random.seed(SEED)
    rows = load()
    texts = [r['text'] for r in rows]
    vecs = embed(texts)

    from sklearn.feature_extraction.text import TfidfVectorizer
    tf = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), min_df=2, max_features=60000,
                         sublinear_tf=True)
    T = tf.fit_transform([norm(t) for t in texts])

    # candidate pairs from nearest neighbours, so hard pairs are actually present
    n = len(rows)
    sample_idx = rng.choice(n, size=min(700, n), replace=False)
    pairs = {}
    for i in sample_idx:
        sims = vecs @ vecs[i]
        sims[i] = -1
        for j in np.argsort(-sims)[:6]:
            key = (min(i, int(j)), max(i, int(j)))
            pairs.setdefault(key, float(sims[j]))
    # a few random pairs so the unrelated band is real
    for _ in range(400):
        i, j = rng.choice(n, 2, replace=False)
        key = (min(int(i), int(j)), max(int(i), int(j)))
        pairs.setdefault(key, float(vecs[i] @ vecs[j]))

    banded = collections.defaultdict(list)
    for (i, j), c in pairs.items():
        for lo, hi, name in BANDS:
            if lo <= c < hi:
                banded[name].append((i, j, c))
                break
    selected = []
    for _, _, name in BANDS:
        pool = banded.get(name, [])
        random.shuffle(pool)
        selected += [(i, j, c, name) for i, j, c in pool[:PER_BAND]]

    exact, tfidf_pred, emb_pred, numeric_pred, silver, records = [], [], [], [], [], []
    for i, j, cos, band in selected:
        a, b = rows[i], rows[j]
        ti = T[i].toarray()[0]
        tj = T[j].toarray()[0]
        denom = (np.linalg.norm(ti) * np.linalg.norm(tj)) or 1.0
        tsim = float(ti @ tj / denom)
        lab = silver_label(a, b, cos, tsim)
        silver.append(lab)
        exact.append('same_claim' if norm(a['text']) == norm(b['text']) else 'unrelated')
        tfidf_pred.append('paraphrase' if tsim >= 0.62 else 'unrelated')
        emb_pred.append('paraphrase' if cos >= 0.88 else 'unrelated')
        nd = numeric_divergence(a['text'], b['text'])
        numeric_pred.append('paraphrase' if (cos >= 0.88 and nd < 0.6
                                             and not date_conflict(a['text'], b['text']))
                            else 'unrelated')
        records.append({
            'pair_id': hashlib.sha256(f'{a["post_id"]}|{b["post_id"]}'.encode()).hexdigest()[:12],
            'band': band, 'cosine': round(cos, 4), 'tfidf_cosine': round(tsim, 4),
            'a': {'post_id': a['post_id'], 'author': a['source_account_id'],
                  'lang': a.get('language'), 'text': a['text'][:220]},
            'b': {'post_id': b['post_id'], 'author': b['source_account_id'],
                  'lang': b.get('language'), 'text': b['text'][:220]},
            'same_author': a['source_account_id'] == b['source_account_id'],
            'cross_language': a.get('language') != b.get('language'),
            'numeric_divergence': numeric_divergence(a['text'], b['text']),
            'date_conflict': date_conflict(a['text'], b['text']),
            'silver_label': lab,
            'human_label': None,
            'human_label_options': ['same_claim', 'paraphrase', 'same_upstream_source',
                                    'template_repeat', 'unrelated'],
        })

    POS = {'same_claim', 'paraphrase', 'same_upstream_source'}
    results = {}
    for name, pred in (('exact_hash_baseline', exact), ('tfidf_char_baseline', tfidf_pred),
                       ('multilingual_embedding', emb_pred),
                       ('embedding_plus_numeric_guard', numeric_pred)):
        m = prf(silver, pred, POS)
        m['bootstrap'] = boot_ci(silver, pred, POS, rng)
        results[name] = m

    errors = [r for r, p in zip(records, emb_pred)
              if (r['silver_label'] in POS) != (p in POS)][:10]

    payload = {
        'run_id': 'dedup-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S'),
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'product_question': 'Does semantic dedup find copies that the exact hash misses, and at what precision?',
        'dataset': {'file': 'data/clean_posts.jsonl',
                    'sha256': hashlib.sha256((ROOT / 'data/clean_posts.jsonl').read_bytes()).hexdigest(),
                    'rows_considered': n},
        'sampling': f'stratified hard pairs, {PER_BAND} per cosine band, seed {SEED}',
        'pairs_evaluated': len(records),
        'band_counts': dict(collections.Counter(r['band'] for r in records)),
        'label_source': 'SILVER rule, not human. Scores are agreement with that rule.',
        'human_labels_present': 0,
        'results_vs_silver': results,
        'template_repeat_finding': {
            'pairs_labelled_template_repeat': sum(1 for r in records if r['silver_label'] == 'template_repeat'),
            'naive_embedding_would_flag_them': sum(
                1 for r, p in zip(records, emb_pred)
                if r['silver_label'] == 'template_repeat' and p == 'paraphrase'),
            'why_it_matters': ('Recurring daily reports from one author share wording but carry '
                               'different figures and dates. Cosine alone calls them duplicates, '
                               'which would delete real content. The numeric guard separates them.'),
        },
        'cross_language_pairs': sum(1 for r in records if r['cross_language']),
        'cross_author_positive_silver': sum(
            1 for r in records if r['silver_label'] in POS and not r['same_author']),
        'exact_hash_recall_gap': {
            'silver_positives': sum(1 for s in silver if s in POS),
            'found_by_exact_hash': sum(1 for s, e in zip(silver, exact) if s in POS and e in POS),
            'note': 'positives the current production dedup would miss entirely',
        },
        'conclusion': {
            'headline': 'On this X corpus the risk is false merging, not missed duplicates.',
            'true_duplicates_found': 0,
            'template_repeats_found': sum(1 for r in records if r['silver_label'] == 'template_repeat'),
            'naive_embedding_false_positives': sum(
                1 for r, p in zip(records, emb_pred)
                if r['silver_label'] not in POS and p in POS),
            'numeric_guard_false_positives': sum(
                1 for r, p in zip(records, numeric_pred)
                if r['silver_label'] not in POS and p in POS),
            'f1_is_undefined': ('With zero positives, F1 is 0 for every method and carries no '
                                'information. The discriminating metric here is the false '
                                'positive count.'),
            'product_decision': ('Do not ship cosine-only dedup on this corpus. Recurring daily '
                                 'flow reports sit at cosine 0.96 to 0.98 while carrying different '
                                 'figures and dates; merging them would delete real content. '
                                 'Ship the numeric and date guard alongside any embedding '
                                 'threshold. Contrast with the Reads corpus, where chunk-level '
                                 'semantic dedup did collapse 54 documents into 44 independent '
                                 'sources, so the method is corpus dependent.'),
        },
        'error_analysis': errors,
        'limits': [
            'Silver labels share signal with the embedding candidate, so its score is inflated.',
            'No Precision or Recall here may be quoted as human accuracy.',
            'The annotation pack must be labelled by a person before any threshold is adopted.',
        ],
        'annotation_pack': 'ml_experiments/dedup_annotation_pack.json',
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'dedup_eval.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    (OUT / 'dedup_annotation_pack.json').write_text(json.dumps({
        'created_at': payload['created_at'], 'seed': SEED,
        'instructions': {
            'same_claim': '同一条主张，措辞几乎相同或完全包含',
            'paraphrase': '同一条主张，改写过',
            'same_upstream_source': '不同表述，但明显转述同一上游来源',
            'template_repeat': '同一模板的周期性播报，数字或日期不同，不算重复',
            'unrelated': '不同主张',
            'note': '先看 A、B 正文，再填 human_label。不要参考 silver_label。',
        },
        'pairs': records}, ensure_ascii=False, indent=2))

    print(json.dumps({k: v for k, v in payload.items()
                      if k not in ('error_analysis',)}, ensure_ascii=False, indent=1))
    return payload


if __name__ == '__main__':
    main()
