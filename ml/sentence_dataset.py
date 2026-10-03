"""Supervised data for the one thing a human said was broken: how a sentence carries a figure.

The human review scored the drafts 5.00 out of 5 for groundedness and **0.17** for naturalness,
and marked every piece 重写. Reading the two corpora side by side shows why in one line:

    ours, 8 of 8    毛利率 75%，我仍把定价权…      metric name, number, comma, clause
                    运营支出 92 亿美元，扩产没收手…
    donors, 0 of N  the figure sits inside the sentence, never at the head in that shape

So this builds the narrowest supervised task that targets exactly that, using the donors' own
sentences as the labels:

    given  a figure, what it measures, the sentence before it, and whose voice
    write  the sentence that carries it

Two decisions worth stating.

**The metric name is produced by a model, not a regex.** A first attempt took the two-to-eight
characters before the number, which works on an earnings release with labelled lines and fails on
flowing prose — it returned 总持仓升至, 昨晚, 周走势的拐点都是 as "metric names", and 58% of
sentences got nothing at all. `live/label_facts.py` exists because of exactly this, and it is
reused here. The model names the quantity; it never touches the digits, the unit or the scale.

**The split is chronological, per author.** Training on a writer's later posts and testing on
their earlier ones would let the model see the very phrasings it is asked to predict. The test
set is each donor's most recent posts, which is also the harder direction.

Run: .venv/bin/python -B ml/sentence_dataset.py [--limit=0] [--test-frac=0.15]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime, collections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'evidence_loop'))

OUT = ROOT / 'ml/store/sentence_task'
BATCH = 8

SENT = re.compile(r'[^。！？\n]+[。！？]?')
NUM = re.compile(r'(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?\s*'
                 r'(?:%|万亿|亿|万|千|个百分点|个基点|美元|日元|韩元|人民币|元|人|倍|bp|BP)?')
HAS_DIGIT = re.compile(r'\d')
URL = re.compile(r'https?://\S+|t\.co/\S+')
# U+2028/U+2029 and the vertical tab are line terminators to str.splitlines() but are *not*
# escaped by json.dumps(ensure_ascii=False). One record carrying U+2028 was split across two
# lines of the JSONL and both halves failed to parse — 16 of 1,523 rows. Stripped at the source
# rather than worked around at the reader, because the characters carry no meaning here.
INVISIBLE_BREAK = re.compile(r'[\u2028\u2029\x0b\x0c\x85]')
# A figure that is part of a date, a list marker or a handle is not a measurement.
NOT_A_MEASURE = re.compile(r'^\d{1,2}$|^\d{4}$|^\d+[）)．.、]$')


def _clean_sentence(s):
    return INVISIBLE_BREAK.sub(' ', URL.sub('', s or '')).strip()


def candidates(min_len=12, max_len=160):
    """Every Chinese sentence in the corpus that carries a figure, with the sentence before it.

    Window chosen from both sides, not picked.

    Our own figure-bearing sentences run 9-120 characters with a median of 36, so the window has
    to cover that range or the training data would not contain the register being fixed. Capping
    at 80 dropped 26% of the donors' figure-bearing sentences — 1,329 against 1,795 — and the ones
    it dropped are the long argumentative ones, which is exactly the register our drafts are worst
    at.
    """
    import style as style_mod
    import clean as clean_mod  # noqa: F401  (corpus() already applies it)
    by = style_mod.corpus()
    rows = []
    for donor, posts in by.items():
        for p in posts:
            if (p.get('lang') or '').lower().startswith('en'):
                continue
            sents = [_clean_sentence(x) for x in SENT.findall(p['text'])]
            sents = [x for x in sents if x]
            for i, s in enumerate(sents):
                if not (min_len < len(s) < max_len) or not HAS_DIGIT.search(s):
                    continue
                figs = []
                for m in NUM.finditer(s):
                    v = m.group(0).strip()
                    if not HAS_DIGIT.search(v) or NOT_A_MEASURE.match(v):
                        continue
                    figs.append({'value': v, 'start': m.start(), 'end': m.end()})
                if not figs or len(figs) > 3:
                    continue
                rows.append({
                    'donor': donor,
                    'context': sents[i - 1] if i else '',
                    'target': s,
                    'figures': figs,
                })
    return rows


def _label_prompt(chunk):
    lines = []
    for j, r in enumerate(chunk, 1):
        f = r['figures'][0]
        lines.append(f"{j}. 数字：{f['value']}\n   出现在这句里：{r['target']}")
    return (
        '下面每条给你一个数字和它所在的句子。请说出这个数字衡量的是什么，'
        '用 2 到 10 个字的名词短语（例如「毛利率」「月度购买量」「失业率」'
        '「ETF 净流入」）。\n'
        '规则：只给名词短语，不要动词、不要时间词、不要把数字本身写进去；'
        '如果这个数字不是在衡量某个量（比如是日期、编号、人名的一部分），写 null。\n\n'
        + '\n'.join(lines)
        + '\n\n只输出 JSON：{"labels":[{"n":1,"subject":"..."},...]}')


def label(rows, limit=0, verbose=True):
    """Name what each figure measures, using the local model in batches."""
    from model_client import parse_json
    from content.generate_slotted import local_call
    todo = rows[:limit] if limit else rows
    named, skipped = 0, 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        try:
            r = local_call(_label_prompt(chunk), 'sentence_task_labels', 900, temperature=.1)
            out = parse_json(r['text'])
        except Exception:
            skipped += len(chunk)
            continue
        by_n = {int(x.get('n', 0)): x for x in (out.get('labels') or []) if isinstance(x, dict)}
        for j, row in enumerate(chunk, 1):
            sub = (by_n.get(j) or {}).get('subject')
            if not isinstance(sub, str) or not sub.strip() or HAS_DIGIT.search(sub):
                skipped += 1
                continue
            sub = sub.strip()[:12]
            if not 1 < len(sub) <= 12:
                skipped += 1
                continue
            row['subject'] = sub
            named += 1
        if verbose and (i // BATCH) % 20 == 0:
            print(f'  标注 {i + len(chunk)}/{len(todo)}  已命名 {named}  跳过 {skipped}', flush=True)
    return named, skipped


def build(limit=0, test_frac=0.15):
    rows = candidates()
    print(f'候选句 {len(rows)} 条（中文、带数字、12–80 字）')
    named, skipped = label(rows, limit=limit)
    kept = [r for r in rows if r.get('subject')]
    print(f'  命名成功 {named}，跳过 {skipped}，可用 {len(kept)}')

    # Chronological split per donor. The corpus rows carry no timestamp, so order within a donor
    # is the order the corpus loader produced — archive first, then live in collection order,
    # which is close enough to chronological for a leakage guard and is stated rather than
    # claimed to be exact.
    by_donor = collections.defaultdict(list)
    for r in kept:
        by_donor[r['donor']].append(r)
    train, test = [], []
    for donor, rs in by_donor.items():
        cut = max(1, int(len(rs) * (1 - test_frac)))
        train += rs[:cut]
        test += rs[cut:]

    OUT.mkdir(parents=True, exist_ok=True)
    meta = {
        'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'candidates': len(rows), 'named': named, 'label_skipped': skipped,
        'train': len(train), 'test': len(test),
        'donors': {d: len(rs) for d, rs in sorted(by_donor.items(), key=lambda x: -len(x[1]))},
        'task': ('given a figure, what it measures, the preceding sentence and the author, '
                 'write the sentence that carries the figure'),
        'labels_from': 'the donors own sentences; the metric name is model-supplied',
        'split': 'per-donor chronological, most recent held out',
        'limits': [
            'corpus rows carry no timestamp, so "chronological" means the order the corpus '
            'loader produced: archive first, then live in collection order',
            'the metric name is produced by the local 4B and is not verified against a source '
            'document; a wrong name teaches a wrong pairing',
            'sentences outside 12-160 characters are excluded; our own figure-bearing sentences run '
            '9-120 with a median of 36, so the window covers the register being fixed',
        ],
    }
    for name, rs in (('train', train), ('test', test)):
        with (OUT / f'{name}.jsonl').open('w', encoding='utf-8') as fh:
            for r in rs:
                fh.write(json.dumps({k: r[k] for k in
                                     ('donor', 'subject', 'context', 'target', 'figures')},
                                    ensure_ascii=False) + '\n')
    (OUT / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def prompt_of(row):
    """The input the model sees. Identical in training and at inference."""
    fig = row['figures'][0]['value']
    ctx = f"上文：{row['context']}\n" if row.get('context') else ''
    return (f"作者：@{row['donor']}\n{ctx}"
            f"要写进这一句的数字：{row['subject']} {fig}\n"
            f"写出这一句：")


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    meta = build(limit=int(args.get('limit', 0)), test_frac=float(args.get('test-frac', 0.15)))
    print(json.dumps({k: v for k, v in meta.items() if k != 'donors'},
                     ensure_ascii=False, indent=2))
    print('\n按 donor：')
    for d, n in list(meta['donors'].items())[:8]:
        print(f'  {d:20} {n}')
    for name in ('train', 'test'):
        p = OUT / f'{name}.jsonl'
        first = json.loads(p.read_text(encoding='utf-8').split('\n')[0])
        print(f'\n{name} 样例：')
        print('  输入:', prompt_of(first).replace('\n', ' / '))
        print('  目标:', first['target'])


if __name__ == '__main__':
    main()
