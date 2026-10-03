"""Judge the blind set with the review relay, then score the judgements against the key.

The previous round of this test had no API key, so the judge was the assistant that had built the
pipeline and knew what its own output looked like. It reported 18/18. That number was never
trustworthy in either direction: the reader knew the generator.

Three things make this version a test rather than a demonstration.

  each item is judged alone   One request per item, no sibling items in the context and no
      statement of how many are machine-written. A judge shown a set will use the set — it will
      hunt for the half that must be artificial and grade on relative polish. A reader meeting a
      post in a feed has no such base rate, and that reader is who the content has to survive.

  the key is opened last   Judgements for every item are written to disk before `answers.json`
      is read. The scoring pass is a separate function that takes the recorded file, so no
      judgement can be quietly revised once its answer is visible.

  a human false-positive rate is reported next to the detection rate   A judge that calls
      everything machine-written scores 100% detection and is worthless. Real posts by the same
      donors, length-matched, go through the identical prompt, so the two rates are comparable.

Two judges from different vendors run the same items. Where they disagree, the item is worth
reading by hand; agreement on a wrong answer is more informative than either alone.

Run: .venv/bin/python -B ml/blind_judge.py [--judges=gpt-6-astra,gemini-3.1-pro] [--limit=N]
"""
from pathlib import Path
import sys, json, hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml import review_api

BLIND = ROOT / 'ml/blind'
OUT = BLIND / 'judgements.json'
SCORED = BLIND / 'scored.json'

PROMPT = {
    'zh': """你在读一条金融类社交账号发布的内容。判断它是真人写的，还是模型生成的。

只看这一条，不要假设任何比例。很多真人帖子也写得工整、也带很多数字。

返回 JSON，字段如下：
  p_machine      0-100 的整数，你认为是模型生成的概率
  verdict        "human" 或 "machine"
  strongest_tell 一句话，写出让你这样判断的最强的那一个具体特征；如果判断为真人，就写最像真人的那一点
  quote          正文里支撑你判断的一小段原文（不超过 25 字）

内容：
---
{text}
---""",
    'en': """You are reading one post from a finance account. Decide whether a person wrote it or
a model generated it.

Judge this item on its own. Assume nothing about how many posts in any batch are machine-written.
Plenty of real posts are tidy and dense with figures.

Return JSON with these fields:
  p_machine      integer 0-100, your probability that a model generated it
  verdict        "human" or "machine"
  strongest_tell one sentence naming the single strongest concrete feature behind your call; if
                 you judge it human, name what reads most human
  quote          a short span from the text supporting your call (25 words maximum)

Post:
---
{text}
---""",
}


def judge_all(judges, limit=None, seed=7):
    """Every item, every judge, one call each. Written to disk before any answer is looked at."""
    items = json.loads((BLIND / 'items.json').read_text())['items']
    if limit:
        items = items[:int(limit)]
    rows, failed = [], []
    for it in items:
        lang = 'en' if (it.get('lang') or 'zh').startswith('en') else 'zh'
        prompt = PROMPT[lang].format(text=it['text'])
        for m in judges:
            try:
                got, rec = review_api.ask_json(
                    [{'role': 'user', 'content': prompt}],
                    model=m, temperature=0.0, seed=seed, max_tokens=400,
                    purpose='blind_judge')
            except review_api.ReviewUnavailable as e:
                failed.append({'id': it['id'], 'judge': m, 'error': str(e)})
                continue
            p = got.get('p_machine')
            p = int(p) if isinstance(p, (int, float, str)) and str(p).strip().isdigit() else None
            rows.append({'id': it['id'], 'lang': lang, 'chars': it['chars'], 'judge': m,
                         'p_machine': p, 'verdict': str(got.get('verdict', '')).lower().strip(),
                         'strongest_tell': got.get('strongest_tell'),
                         'quote': got.get('quote'),
                         'cache': rec.get('cache')})
            print(f"  {it['id']} {lang} {m:16} p={p!s:>4} {str(got.get('verdict'))[:7]:8}"
                  f" {str(got.get('strongest_tell'))[:60]}")
    OUT.write_text(json.dumps({'judges': judges, 'seed': seed, 'n_items': len(items),
                               'judgements': rows, 'failed': failed},
                              ensure_ascii=False, indent=2))
    if failed:
        print(f"  {len(failed)} calls failed and are recorded, not retried silently")
    return rows


def _family(name):
    """Vendor family of a model or writer, for the judge-conflict check."""
    n = str(name or '').lower()
    for fam, marks in (('grok', ('grok',)), ('anthropic', ('claude',)),
                       ('openai', ('gpt',)), ('google', ('gemini',)),
                       ('local', ('local', 'qwen'))):
        if any(m in n for m in marks):
            return fam
    return 'other'


def _auc(pos, neg):
    """Probability a machine item is scored above a human one. Ties count half."""
    if not pos or not neg:
        return None
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def _dataset_id():
    """Hash of the exact items scored, so a number can be traced to the data behind it.

    The evaluation contract asks for a dataset hash and split IDs on every score. Without them a
    detection rate is a number with no referent: this project has already had two blind rounds
    whose item sets differed, and the only thing that distinguished them in the record was a seed.
    """
    items = json.loads((BLIND / 'items.json').read_text())
    payload = json.dumps([{'id': i['id'], 'lang': i.get('lang'), 'chars': i.get('chars')}
                          for i in items['items']], sort_keys=True, ensure_ascii=False)
    return {'dataset_sha256_16': hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16],
            'n_items': len(items['items']), 'seed': items.get('seed'),
            'item_ids': sorted(i['id'] for i in items['items'])}


def score():
    """Open the key and grade what was already recorded."""
    rec = json.loads(OUT.read_text())
    key = {k['id']: k for k in json.loads((BLIND / 'answers.json').read_text())['key']}
    out = {'judges': rec['judges'], 'seed': rec['seed'], 'by_judge': {}, 'items': [],
           'dataset': _dataset_id(),
           'reference_label_type': 'model_reviewed',
           # The contract is explicit: until a real person submits a judgement, human metrics are
           # null and the status is pending. An LLM verdict is a proxy for a human reader, and
           # recording it as anything else would let a proxy be read as the thing it stands in for.
           'human_review': {'status': 'pending', 'detection_rate': None,
                            'false_positive_rate': None, 'reviewers': 0,
                            'why': 'no human has submitted a judgement on this set'}}

    for m in rec['judges']:
        mine = [r for r in rec['judgements'] if r['judge'] == m and r['id'] in key]
        mach = [r for r in mine if key[r['id']]['origin'] == 'machine']
        hum = [r for r in mine if key[r['id']]['origin'] == 'human']
        det = sum(r['verdict'] == 'machine' for r in mach)
        fp = sum(r['verdict'] == 'machine' for r in hum)
        block = {
            'items_judged': len(mine),
            'machine_items': len(mach), 'detected_as_machine': det,
            'detection_rate': round(det / len(mach), 3) if mach else None,
            'human_items': len(hum), 'humans_called_machine': fp,
            'false_positive_rate': round(fp / len(hum), 3) if hum else None,
            'auc': _auc([r['p_machine'] for r in mach if r['p_machine'] is not None],
                        [r['p_machine'] for r in hum if r['p_machine'] is not None]),
            'mean_p_machine_on_machine': (
                round(sum(r['p_machine'] for r in mach if r['p_machine'] is not None)
                      / max(sum(r['p_machine'] is not None for r in mach), 1), 1) if mach else None),
            'mean_p_machine_on_human': (
                round(sum(r['p_machine'] for r in hum if r['p_machine'] is not None)
                      / max(sum(r['p_machine'] is not None for r in hum), 1), 1) if hum else None),
        }
        for lang in ('zh', 'en'):
            lm = [r for r in mach if r['lang'] == lang]
            lh = [r for r in hum if r['lang'] == lang]
            block[lang] = {
                'machine_items': len(lm),
                'detection_rate': (round(sum(r['verdict'] == 'machine' for r in lm) / len(lm), 3)
                                   if lm else None),
                'human_items': len(lh),
                'false_positive_rate': (round(sum(r['verdict'] == 'machine' for r in lh) / len(lh), 3)
                                        if lh else None),
            }
        # The curated set is a fixed audit sample that the live-pipeline work does not touch, so
        # mixing it into one detection rate hides whether anything changed. Round 2 made this
        # concrete: three of six Chinese machine items were unchanged September drafts, and the
        # judges named the same defects they had named in round 1 — correctly, because those
        # pieces were the same pieces.
        # Which model wrote it is the question this round exists to answer, so it is scored
        # apart. Pooling a 4B's output with a frontier model's would average away the only
        # comparison that matters.
        writers = sorted({key[r['id']].get('writer') for r in mach
                          if key[r['id']].get('writer')})
        block['by_writer'] = {}
        for w in writers:
            wm = [r for r in mach if key[r['id']].get('writer') == w]
            block['by_writer'][w] = {
                'items': len(wm),
                # A judge grading its own family's writing is the one bias this test cannot
                # absorb. It is recorded per writer rather than silently pooled, so a reading of
                # "grok output was harder to detect" can be checked against who was judging.
                'same_family_as_judge': _family(m) == _family(w),
                'detection_rate': (round(sum(r['verdict'] == 'machine' for r in wm) / len(wm), 3)
                                   if wm else None),
                'mean_p_machine': (round(sum(r['p_machine'] for r in wm
                                             if r['p_machine'] is not None)
                                         / max(sum(r['p_machine'] is not None for r in wm), 1), 1)
                                   if wm else None)}

        for origin in ('live', 'curated'):
            om = [r for r in mach if str(key[r['id']].get('detail', '')).startswith(origin)]
            block[f'machine_{origin}'] = {
                'items': len(om),
                'detection_rate': (round(sum(r['verdict'] == 'machine' for r in om) / len(om), 3)
                                   if om else None)}

        # A piece the gates already refused is not output; scoring it beside a queue-eligible one
        # would let English's held drafts stand in for what the system would actually publish.
        for gate in ('candidate', 'blocked'):  # noqa: E501
            gm = [r for r in mach if key[r['id']].get('gate') == gate]
            block[f'machine_{gate}'] = {
                'items': len(gm),
                'detection_rate': (round(sum(r['verdict'] == 'machine' for r in gm) / len(gm), 3)
                                   if gm else None),
                'mean_p_machine': (round(sum(r['p_machine'] for r in gm
                                             if r['p_machine'] is not None)
                                         / max(sum(r['p_machine'] is not None for r in gm), 1), 1)
                                   if gm else None),
            }
        out['by_judge'][m] = block

    for iid, k in key.items():
        js = [r for r in rec['judgements'] if r['id'] == iid]
        if not js:
            continue
        out['items'].append({
            'id': iid, 'truth': k['origin'], 'detail': k['detail'], 'donor': k.get('donor'),
            'lang': js[0]['lang'], 'chars': js[0]['chars'],
            'verdicts': {r['judge']: r['verdict'] for r in js},
            'p_machine': {r['judge']: r['p_machine'] for r in js},
            'agree': len({r['verdict'] for r in js}) == 1,
            'judge_conflict': sorted({r['judge'] for r in js
                                      if _family(r['judge']) == _family(k.get('writer'))}),
            'both_wrong': all(r['verdict'] != k['origin'] for r in js),
            'tells': {r['judge']: r['strongest_tell'] for r in js},
        })
    out['judges_agree'] = round(
        sum(i['agree'] for i in out['items']) / max(len(out['items']), 1), 3)
    out['coverage'] = coverage(rec, key)
    SCORED.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def coverage(rec, key):
    """Was every item actually judged, and was any of it judged fresh?

    Round 2 printed "detection 3/3 = 1.0" while the relay was refusing every new request with
    503. The eighteen answers that came back were all cache hits on items whose text was
    unchanged from round 1 — the six human posts and the three curated drafts — so the run
    reported round 1's verdicts as though they were round 2's, and every piece the work had
    actually changed was missing. A partial run is not a weaker result; it is a different sample,
    selected by which calls happened to succeed.
    """
    judged = {r['id'] for r in rec['judgements']}
    fresh = sum(1 for r in rec['judgements'] if r.get('cache') == 'miss')
    missing = [k for k in key if k not in judged]
    return {'items': len(key), 'judged': len(judged), 'missing': len(missing),
            'failed_calls': len(rec.get('failed') or []), 'fresh_answers': fresh,
            'valid': not missing,
            'why': ('' if not missing else
                    f'{len(missing)} of {len(key)} items were never judged; '
                    f'{len(rec.get("failed") or [])} calls failed')}


def report(s):
    c = s.get('coverage') or {}
    if c and not c.get('valid'):
        print('THIS RUN IS NOT A RESULT.')
        print(f"  {c['why']}")
        print(f"  answers actually returned: {c['judged']}/{c['items']} items, "
              f"of which {c['fresh_answers']} were fresh and "
              f"{c['judged'] - c['fresh_answers']} came from cache.")
        print('  Rates are withheld: the items that returned are the ones whose calls '
              'succeeded, which is not a random sample.')
        for m, b in s['by_judge'].items():
            print(f"  {m}: judged {b['items_judged']} items "
                  f"({b['machine_items']} machine, {b['human_items']} human)")
        return
    for m, b in s['by_judge'].items():
        print(f"\n{m}")
        print(f"  detection on machine items   {b['detected_as_machine']}/{b['machine_items']}"
              f"  = {b['detection_rate']}")
        print(f"  false positives on real ones {b['humans_called_machine']}/{b['human_items']}"
              f"  = {b['false_positive_rate']}")
        print(f"  AUC {b['auc']}   mean p(machine): machine {b['mean_p_machine_on_machine']}"
              f" · human {b['mean_p_machine_on_human']}")
        for lang in ('zh', 'en'):
            d = b[lang]
            if d['machine_items'] or d['human_items']:
                print(f"    {lang}: detection {d['detection_rate']} on {d['machine_items']}"
                      f" · fp {d['false_positive_rate']} on {d['human_items']}")
        for gate in ('candidate', 'blocked'):
            d = b[f'machine_{gate}']
            if d['items']:
                print(f"    {gate:9} n={d['items']}  detection {d['detection_rate']}"
                      f"  mean p(machine) {d['mean_p_machine']}")
        for origin in ('live', 'curated'):
            d = b[f'machine_{origin}']
            if d['items']:
                print(f"    {origin:9} n={d['items']}  detection {d['detection_rate']}")
        for w, d in (b.get('by_writer') or {}).items():
            warn = '  ⚠ 同家族，此项不作为证据' if d.get('same_family_as_judge') else ''
            print(f"    writer {w:14} n={d['items']}  detection {d['detection_rate']}"
                  f"  mean p(machine) {d['mean_p_machine']}{warn}")
    d = s.get('dataset') or {}
    print(f"\ndataset {d.get('dataset_sha256_16')}  n={d.get('n_items')}  seed={d.get('seed')}")
    print(f"reference labels: {s.get('reference_label_type')}  ·  "
          f"human review: {(s.get('human_review') or {}).get('status')} "
          f"(human metrics are null until a person submits)")
    print(f"judges agree on {s['judges_agree']:.0%} of items")
    missed = [i for i in s['items'] if i['truth'] == 'machine' and not all(
        v == 'machine' for v in i['verdicts'].values())]
    print(f"machine items that fooled at least one judge: {len(missed)}")
    for i in missed:
        print(f"  {i['id']} {i['lang']} {i['detail']}  {i['verdicts']}")


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    if 'score-only' in args:
        report(score())
        return
    judges = (args.get('judges') or f'{review_api.JUDGE},{review_api.SECOND_JUDGE}').split(',')
    judge_all([j.strip() for j in judges], limit=args.get('limit'))
    report(score())


if __name__ == '__main__':
    main()
