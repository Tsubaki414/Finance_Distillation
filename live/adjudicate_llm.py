"""The same duplicate/event judgement, made by a model instead of by regex.

Written after the user asked why this is not simply handed to a model, having watched the regex
version read `2026-09-23` as the figures -26, -23 and -9, and treat the word `Creation` — from
the SEC item heading 'Creation of a Direct Financial Obligation' — as a company identifier.

**The cost objection was wrong and it is worth saying why.** The argument for keeping the
adjudication deterministic was volume. That argument came from the wrong number. Embedding 271
items produces 36,585 possible pairs, and the candidate floor cuts those to **270** — a 135x
reduction — before anything is adjudicated. Judging 270 pairs is affordable; judging 36,585 was
never on the table. The expensive step had already been removed by the cheap one.

So the architecture does not change. Embeddings still propose, because a model cannot read
36,585 pairs cheaply and does not need to. What changes is who decides.

This is not the self-assessment CLAUDE.md rules out. That rule is about a model grading its own
writing. Here the model reads two external headlines and says whether they describe one event —
a perception task on other people's text, checkable by a human reading the same two headlines.

What has to be watched, recorded before running rather than after:

  * **non-determinism** — temperature 0 and the request cache make a re-run reproducible, but the
    same pair phrased differently could still land differently. The regex could not do that.
  * **plausible wrong reasons** — a regex fails visibly, with `-26` sitting in the output. A model
    fails fluently. Every verdict therefore carries the model's own one-line reason, and the
    comparison below prints every disagreement for a human rather than reporting an agreement rate.
  * **cost with scale** — 270 pairs in a 48-hour window at ten sources. More sources means more
    pairs, and the budget gate in `ml/budget.py` is what stops that quietly.

Run: .venv/bin/python -B live/adjudicate_llm.py --compare [--hours=48] [--limit=60]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

MODEL = 'relay2/gpt-5.5'
BATCH = 20
MAX_CHARS = 260

VERDICTS = ('duplicate', 'same_event', 'unrelated')

PROMPT = """下面每条给你两则金融新闻的标题与摘要，判断它们的关系。

三选一：
  duplicate   —— 同一件事的同一则报道，只是不同媒体或不同语言的版本。
                 跨语言的同一条新闻算 duplicate。
  same_event  —— 相关，但不是同一则。例如同一标的不同时点的行情快照、
                 同一事项的申报与其修正案、同一主题下不同机构的观点。
  unrelated   —— 不是同一件事。标题格式雷同但主体不同（比如两家不同公司的 8-K）属于这一类。

注意：
  · 数字不同往往意味着不是同一则（84000 和 85000 是两个时点）。
  · 8-K 与 8-K/A 是两份文件。
  · 不同公司、不同标的，哪怕措辞几乎一样，也是 unrelated。
  · 中英文表述完全不同但说的是同一件事、同一个数字，是 duplicate。

每条给出 verdict 和一句中文理由（不超过 30 字，说清依据）。

只输出 JSON：{"results":[{"n":1,"verdict":"...","why":"..."}]}

"""


def _fmt(pair, n):
    a, b = pair
    return (f"{n}.\n"
            f"  A[{a['lang']}] {a['title'][:120]}\n"
            f"     {(a.get('summary') or '')[:MAX_CHARS]}\n"
            f"  B[{b['lang']}] {b['title'][:120]}\n"
            f"     {(b.get('summary') or '')[:MAX_CHARS]}")


def judge(pairs, model=MODEL):
    """Verdicts for a list of (a, b) row pairs. Raises rather than guessing on failure."""
    from ml import review_api
    out = {}
    for i in range(0, len(pairs), BATCH):
        chunk = pairs[i:i + BATCH]
        body = PROMPT + '\n\n'.join(_fmt(p, j + 1) for j, p in enumerate(chunk))
        text, meta = review_api.ask(
            [{'role': 'user', 'content': body}], model=model, temperature=0.0,
            max_tokens=2400, purpose='cluster_adjudication', json_object=True,
            use_cache=True, timeout=300)
        try:
            data = json.loads(re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M))
        except Exception:
            raise RuntimeError(f'unparsable adjudication reply: {text[:200]}')
        for r in (data.get('results') or []):
            n = int(r.get('n', 0))
            v = str(r.get('verdict', '')).strip()
            if 1 <= n <= len(chunk) and v in VERDICTS:
                out[i + n - 1] = {'verdict': v, 'why': str(r.get('why', ''))[:80],
                                  'model': meta.get('model_reported') or model,
                                  'usd': meta.get('usd_charged'), 'cache': meta.get('cache')}
    return out


def compare(hours=48, limit=0, model=MODEL):
    """Both adjudicators on the same candidate pairs. Disagreements are the output."""
    import numpy as np
    import cluster as C

    rows = C.load(hours)
    boiler = C.template_terms(rows)
    E = C.embed(rows)
    S = E @ E.T
    np.fill_diagonal(S, -1)
    idx = [(int(i), int(j), float(S[i, j]))
           for i, j in zip(*np.where(np.triu(S, 1) >= C.CANDIDATE_FLOOR))]
    idx.sort(key=lambda p: -p[2])
    if limit:
        idx = idx[:limit]

    rule = [C.adjudicate(rows[i], rows[j], sim, boiler) for i, j, sim in idx]
    llm = judge([(rows[i], rows[j]) for i, j, _ in idx], model=model)

    agree, disagree, missing = 0, [], 0
    spend = 0.0
    seen_calls = set()
    for k, (i, j, sim) in enumerate(idx):
        m = llm.get(k)
        if not m:
            missing += 1
            continue
        if m.get('usd') and m.get('cache') != 'hit' and id(m) not in seen_calls:
            seen_calls.add(id(m))
        if m['verdict'] == rule[k][0]:
            agree += 1
        else:
            disagree.append({'sim': round(sim, 3),
                             'a': rows[i]['title'][:70], 'a_lang': rows[i]['lang'],
                             'b': rows[j]['title'][:70], 'b_lang': rows[j]['lang'],
                             'rule': rule[k][0], 'rule_why': rule[k][1][:70],
                             'llm': m['verdict'], 'llm_why': m['why']})
    judged = len(idx) - missing
    return {'pairs': len(idx), 'judged': judged, 'no_verdict': missing,
            'agree': agree, 'disagree': len(disagree),
            'agreement_rate': round(agree / judged, 3) if judged else None,
            'model': model,
            'disagreements': disagree,
            'note': ('an agreement rate says how often two judges match, not which is right; '
                     'the disagreements below are the only part worth reading')}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    from ml import budget
    before = budget.spent()
    r = compare(hours=int(args.get('hours', 48)), limit=int(args.get('limit', 0)))
    spent = budget.spent() - before
    print(f"{r['pairs']} 对  模型判定 {r['judged']}  无判定 {r['no_verdict']}  "
          f"一致 {r['agree']}  分歧 {r['disagree']}  一致率 {r['agreement_rate']}")
    print(f"本次花费 ${spent:.4f}（累计 ${budget.spent():.2f} / ${budget.cap():.2f}）\n")
    print('分歧逐条（一致率说明不了谁对，这些才要看）：')
    for d in r['disagreements'][:40]:
        print(f"\n  {d['sim']:.3f}  规则={d['rule']:11} 模型={d['llm']}")
        print(f"     A[{d['a_lang']}] {d['a']}")
        print(f"     B[{d['b_lang']}] {d['b']}")
        print(f"     规则理由: {d['rule_why']}")
        print(f"     模型理由: {d['llm_why']}")
    out = ROOT / 'live/store/adjudication_compare.json'
    out.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print(f"\n写入 {out}")


if __name__ == '__main__':
    main()
