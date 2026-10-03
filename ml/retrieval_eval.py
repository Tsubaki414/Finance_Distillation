"""Retrieval evaluation harness: keyword/TF-IDF baseline against embedding retrieval.

The production retrieval has never been scored. It returns 18 exemplars with cosine values and no
relevance labels at all, so Recall@K and nDCG@K are currently undefined for this system.

This builds the harness and the judgment pack: 10 queries spanning macro, single name, positioning
and cross-language intent, Top-5 from each method, pooled and de-duplicated into judgments a person
fills in. Until those labels exist, the only numbers reported are method agreement and pool
overlap, both explicitly named as such.

One real defect this also checks: production retrieval runs over raw posts, not the cleaned set,
so rule-excluded posts can be returned.

Run: .venv/bin/python -B ml/retrieval_eval.py
"""
from pathlib import Path
import json, os, re, hashlib, datetime, unicodedata, collections
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ml_experiments'
SEED = 42
K = 5

# Ten queries chosen to span the lanes the product actually routes on, not just macro.
QUERIES = [
    ('q01', 'macro', '非农就业数据低于预期对利率路径意味着什么'),
    ('q02', 'macro', '劳动参与率下降是结构性还是周期性'),
    ('q03', 'rates', '美联储官员表态转变与降息概率'),
    ('q04', 'industry', 'AI 资本开支能否持续 云厂商支出'),
    ('q05', 'industry', '内存涨价对下游成本与毛利的传导'),
    ('q06', 'single_name', '英伟达财报与算力需求'),
    ('q07', 'trading', '数据公布前如何控制仓位与设定止损'),
    ('q08', 'trading', '空头仓位处于历史高位说明什么'),
    ('q09', 'flows', 'ETF 资金流向与市场风险偏好'),
    ('q10', 'cross_language', 'US labour market softening and recession odds'),
]


def norm(t):
    t = unicodedata.normalize('NFKC', t or '')
    t = re.sub(r'https?://\S+', '', t)
    return re.sub(r'[^\w一-鿿]', ' ', t).lower()


def load(which):
    p = ROOT / ('data/clean_posts.jsonl' if which == 'clean' else 'data/raw_posts.jsonl')
    rows = []
    for line in p.read_text().split('\n'):
        if line:
            r = json.loads(line)
            body = r.get('analysis_text') or r.get('text') or ''
            if len(body.strip()) >= 40:
                r['_body'] = body
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


def dcg(gains):
    return sum(g / np.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(gains, ideal):
    d, i = dcg(gains), dcg(sorted(ideal, reverse=True)[:len(gains)])
    return round(float(d / i), 4) if i else None


def main():
    rows = load('clean')
    texts = [r['_body'] for r in rows]
    vecs = embed(texts)
    qvecs = embed([q[2] for q in QUERIES])

    from sklearn.feature_extraction.text import TfidfVectorizer
    tf = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), min_df=2,
                         max_features=80000, sublinear_tf=True)
    T = tf.fit_transform([norm(t) for t in texts])
    QT = tf.transform([norm(q[2]) for q in QUERIES])

    results, pool = {}, {}
    for qi, (qid, lane, qtext) in enumerate(QUERIES):
        esims = vecs @ qvecs[qi]
        etop = np.argsort(-esims)[:K]
        tsims = np.asarray((QT[qi] @ T.T).todense()).ravel()
        ttop = np.argsort(-tsims)[:K]

        def pack(idx, score):
            return [{'rank': r + 1, 'post_id': rows[int(i)]['post_id'],
                     'author': rows[int(i)]['source_account_id'],
                     'lang': rows[int(i)].get('language'),
                     'score': round(float(score[int(i)]), 4),
                     'text': rows[int(i)]['_body'][:200]} for r, i in enumerate(idx)]

        results[qid] = {'lane': lane, 'query': qtext,
                        'embedding': pack(etop, esims), 'tfidf': pack(ttop, tsims),
                        'overlap_at_k': len(set(int(i) for i in etop) & set(int(i) for i in ttop))}
        for i in list(etop) + list(ttop):
            key = (qid, rows[int(i)]['post_id'])
            if key not in pool:
                pool[key] = {
                    'judgment_id': hashlib.sha256(f'{qid}|{rows[int(i)]["post_id"]}'.encode()).hexdigest()[:12],
                    'query_id': qid, 'lane': lane, 'query': qtext,
                    'post_id': rows[int(i)]['post_id'],
                    'author': rows[int(i)]['source_account_id'],
                    'lang': rows[int(i)].get('language'),
                    'text': rows[int(i)]['_body'][:300],
                    'retrieved_by': [],
                    'human_relevance': None,
                    'scale': {'0': '不相关', '1': '沾边但无用', '2': '相关可用', '3': '高度相关，直接可引'},
                }
            pool[key]['retrieved_by'] = sorted(set(pool[key]['retrieved_by'] +
                                                   (['embedding'] if i in etop else []) +
                                                   (['tfidf'] if i in ttop else [])))

    judgments = sorted(pool.values(), key=lambda x: (x['query_id'], x['post_id']))

    # the production retrieval defect: it indexes raw, not clean
    prod = json.loads((ROOT / 'evidence_loop/experiments/retrieval.json').read_text())
    clean_ids = {r['post_id'] for r in load('clean')}
    prod_ids = [e['post_id'] for items in prod['results'].values() for e in items]
    outside_clean = [p for p in prod_ids if p not in clean_ids]

    payload = {
        'run_id': 'retr-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S'),
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'product_question': 'Does embedding retrieval beat a keyword baseline at finding usable KOL posts for an event?',
        'dataset': {'file': 'data/clean_posts.jsonl',
                    'sha256': hashlib.sha256((ROOT / 'data/clean_posts.jsonl').read_bytes()).hexdigest(),
                    'rows_indexed': len(rows)},
        'queries': len(QUERIES), 'k': K,
        'query_document_judgments': len(judgments),
        'judgments_labelled_by_human': 0,
        'metrics_status': ('Recall@K and nDCG@K are UNDEFINED until the judgment pack is labelled. '
                           'Nothing here may be reported as retrieval quality.'),
        'method_agreement': {
            'mean_overlap_at_k': round(
                float(np.mean([results[q[0]]['overlap_at_k'] for q in QUERIES])), 3),
            'per_query': {q[0]: results[q[0]]['overlap_at_k'] for q in QUERIES},
            'interpretation': ('Low overlap means the two methods surface different documents, so '
                               'the judgment pack covers a wider pool and the comparison is worth '
                               'running once labels exist.'),
        },
        'lane_coverage': dict(collections.Counter(q[1] for q in QUERIES)),
        'language_mix_retrieved': dict(collections.Counter(j['lang'] for j in judgments)),
        'production_retrieval_defect': {
            'issue': 'production retrieval indexes data/raw_posts.jsonl, not the cleaned set',
            'exemplars_checked': len(prod_ids),
            'exemplars_outside_clean_corpus': len(outside_clean),
            'ids_outside_clean': outside_clean,
            'severity': 'blocking' if outside_clean else 'clear',
            'note': ('If any exemplar is outside the cleaned set, a rule-excluded post can be fed '
                     'to generation as a style example.'),
        },
        'harness_ready': True,
        'annotation_pack': 'ml_experiments/retrieval_judgment_pack.json',
        'next_metric_when_labelled': ['Recall@5', 'nDCG@5', 'per-lane slice', 'bootstrap CI'],
        'results': results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'retrieval_eval.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    (OUT / 'retrieval_judgment_pack.json').write_text(json.dumps({
        'created_at': payload['created_at'], 'seed': SEED, 'k': K,
        'instructions': {
            'task': '对每条 (query, post) 判定相关性 0 到 3，填入 human_relevance',
            'do_not': '不要参考 retrieved_by 字段，那会泄漏方法归属',
            'scale': {'0': '不相关', '1': '沾边但无用', '2': '相关可用', '3': '高度相关，直接可引'},
        },
        'judgments': judgments}, ensure_ascii=False, indent=2))

    print(json.dumps({k: v for k, v in payload.items() if k != 'results'},
                     ensure_ascii=False, indent=1))
    return payload


if __name__ == '__main__':
    main()
