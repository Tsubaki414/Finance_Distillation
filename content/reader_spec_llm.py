"""The reader's six dislikes, judged by a model instead of by regex.

`content/reader_spec.py` encodes the list the reader wrote as regular expressions. It catches
what I thought to write down and nothing else, and the proof of that is in the list itself. Under
'抽象化普通意思' I listed 赋能, 闭环, 底层逻辑. A draft then produced

    我会把工资、参与率、行业广度和历史修订先当成数据层，把加息时点当成政策层

— 数据层 and 政策层, invented on the spot. The gate passed it. The reader read it and called it
狗屎句子. The pattern was on the list; the strings were not, and a regex only knows strings.

This is the same failure the dedup work just measured. Asked to judge whether two headlines
describe one event, a regex and a model disagreed 19 times on 60 pairs and the regex was wrong
all 19. A style judgement is further from a regex's reach than that one was.

**What stays deterministic, and why it is not timidity.** Numeric audit does not move. Every
figure must match the fact packet by value and unit, and that is verification, not judgement — a
deterministic check is *stronger* there precisely because it cannot be reasoned with. A model
asked whether 74% is close enough to 75% has an opinion. `live/write.audit` does not.

**What this is not.** CLAUDE.md rules out model self-assessment as acceptance, and this does not
touch that. The writer does not grade itself: a different family reads the finished text against
a list a human wrote, and the result is a gate, still not acceptance. `ml/human_review.py`
remains the only thing that decides whether the writing is good.

Run: .venv/bin/python -B content/reader_spec_llm.py --compare [--limit=22]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Not the writer. gpt-5.5 wrote most of the drafts under test and must not mark its own work.
JUDGE = 'relay2/claude-sonnet-5'

CODES = ('announcing_the_point', 'template_pivot', 'weighty_ending',
         'abstract_inflation', 'mechanical_roundness', 'slogan_short_sentences',
         'dense_figures_thin_links')

PROMPT = """你在替一位读者审稿。他读过这个系统写的稿子，两轮都一眼认出是机器写的，
然后写下了他不喜欢的表达类型：

  announcing_the_point      预告自己要说重点。「真正值得关注的是」「很多人不知道的是」
                            「我的判断是……」——花一句宣布判断要来了，而不是直接说。
  template_pivot            模板式转折。「不是……而是……」「问题不在于……而在于……」
  weighty_ending            假装有分量的结尾。「这值得深思」「时间会给出答案」
                            「这才是最重要的」——结尾写感慨而不是判断或失效条件。
  abstract_inflation        把普通意思抽象化。「实现价值重构」「形成深度协同」
                            「提供新的思考维度」。**现造的术语也算**，例如把几个
                            普通指标叫成「数据层」，把利率决定叫成「政策层」。
  mechanical_roundness      机械周全。每段都写优点、风险、建议，再补一句总结。
  slogan_short_sentences    把解释压缩成口号式短句。「费用在抬头。」「需求还在。」
                            ——四五个字的断言，代替了本该写出来的推理。
  dense_figures_thin_links  数字排得很密，关系交代得很少。

他同时要求：「写清一句判断是怎么从前面的事实推出来的。允许多写几句解释，
不要把解释压缩成术语、口号或刻意的短句。读者应该能顺着读懂，无须反复翻译作者的措辞。」

请逐篇判断。对每一类，只有真的出现才报，不要为了凑数而报。
每报一处，必须引用稿中的**原句**作为证据——引不出原句就不要报。

只输出 JSON：
{"results":[{"n":1,"findings":[{"code":"...","quote":"稿中原句","why":"一句话，不超过25字"}]}]}

下面是待判的稿件：

"""


def _extract_json(text):
    """The first balanced JSON object in the reply.

    `json_object=True` is sent and this relay does not enforce it: the judge returned valid JSON
    and then several sentences of Chinese commentary explaining its reasoning. Treating the whole
    reply as JSON raised on character 0 of a response that was actually fine. Worth keeping the
    commentary in mind as a property of this path — a model may add prose whenever it feels the
    structured answer is incomplete.
    """
    s = re.sub(r'```(?:json)?|```', '', text or '').strip()
    start = s.find('{')
    if start < 0:
        raise RuntimeError(f'no JSON object in reply: {s[:160]}')
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(s[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return json.loads(s[start:i + 1])
    raise RuntimeError(f'unbalanced JSON in reply: {s[:160]}')


def judge(texts, model=JUDGE):
    from ml import review_api
    body = PROMPT + '\n\n'.join(
        f'=== 第 {i + 1} 篇 ===\n{t[:2200]}' for i, t in enumerate(texts))
    text, meta = review_api.ask(
        [{'role': 'user', 'content': body}], model=model, temperature=0.0,
        max_tokens=4000, purpose='reader_spec_judge', json_object=True,
        use_cache=True, timeout=400)
    data = _extract_json(text)
    out = {}
    for r in (data.get('results') or []):
        n = int(r.get('n', 0))
        if 1 <= n <= len(texts):
            found = []
            for f in (r.get('findings') or []):
                code, quote = f.get('code'), (f.get('quote') or '').strip()
                # A finding without a quote that actually appears in the text is an assertion,
                # not evidence. The regex could not hallucinate a match; this one can.
                if code in CODES and quote and quote[:12] in texts[n - 1]:
                    found.append({'code': code, 'quote': quote[:60],
                                  'why': (f.get('why') or '')[:40]})
            out[n - 1] = found
    return out, meta


BATCH = 6


def check(text, lang='zh', model=JUDGE):
    """Both judges, unioned. Measured on 22 drafts, neither one subsumes the other.

        model found, regex missed   13   including 「把…当成数据层，把加息时点当成政策层」,
                                         the sentence the reader singled out as 狗屎句子, and
                                         「这不是纯声量问题。」 — patterns the list describes and
                                         no string I wrote down would match
        regex found, model missed    2   「我的判断是」 and 「这组数据支持我的判断」, both added
                                         to the pattern after a reader saw them in a draft

    So this is not the dedup result, where the regex lost every disagreement. Here each judge
    covers what the other does not: the regex knows exactly the strings we have already been
    burned by, and the model recognises the shapes nobody wrote down. Taking the union costs
    $0.002 a draft and loses neither.

    A model failure degrades to regex-only and says so on the result, rather than quietly
    returning a pass built from half the evidence.
    """
    from content.reader_spec import check as rule_check, BLOCKING
    base = rule_check(text, lang)
    if not str(lang).startswith('zh'):
        return {**base, 'judged_by': 'rule', 'llm_error': 'list is about Chinese output'}

    try:
        found, meta = judge([text], model=model)
        extra = found.get(0, [])
        err = None
    except Exception as e:
        extra, meta, err = [], {}, type(e).__name__ + ': ' + str(e)[:140]

    seen = {x['code'] for x in base['findings']}
    merged = list(base['findings'])
    for x in extra:
        if x['code'] not in seen:
            seen.add(x['code'])
            merged.append({'code': x['code'], 'severity': BLOCKING,
                           'detail': f"「{x['quote']}」 — {x['why']}",
                           'found_by': 'model'})
    blocking = [x for x in merged if x['severity'] == BLOCKING]
    return {**base, 'findings': merged, 'blocking_count': len(blocking),
            'status': 'failed' if blocking else 'passed',
            'judged_by': 'rule' if err else 'rule+model',
            'llm_error': err,
            'llm_model': meta.get('model_reported') if meta else None,
            'check_version': 'reader-v2'}


def faults(result, lang='zh'):
    from content.reader_spec import faults as rule_faults
    out = rule_faults(result, lang)
    for x in result.get('findings', []):
        if x.get('found_by') == 'model':
            out.append(f"上一稿有这个问题：{x['detail']} 改掉它。")
    return out


def compare(limit=0, model=JUDGE):
    from content.reader_spec import check as rule_check
    D = ROOT / 'live/store/drafts'
    drafts = []
    for f in sorted(D.glob('*.json')):
        d = json.loads(f.read_text())
        if (d.get('lang') or 'zh') == 'zh' and d.get('text') \
                and d.get('status') == 'ready_for_queue':
            drafts.append(d)
    if limit:
        drafts = drafts[:limit]
    texts = [d['text'] for d in drafts]

    llm = {}
    for i in range(0, len(texts), BATCH):
        part, _ = judge(texts[i:i + BATCH], model=model)
        for k, v in part.items():
            llm[i + k] = v

    rows, only_rule, only_llm, both = [], 0, 0, 0
    for i, d in enumerate(drafts):
        r = rule_check(d['text'], 'zh')
        rc = {x['code'] for x in r['findings']}
        lc = {x['code'] for x in llm.get(i, [])}
        only_rule += len(rc - lc)
        only_llm += len(lc - rc)
        both += len(rc & lc)
        rows.append({'writer': d.get('writer_model') or 'local',
                     'entity': d.get('entity'),
                     'rule': sorted(rc), 'llm': sorted(lc),
                     'llm_evidence': llm.get(i, [])})
    return {'drafts': len(drafts), 'judge': model,
            'both': both, 'only_rule': only_rule, 'only_llm': only_llm,
            'rule_blocked': sum(1 for r in rows if r['rule']),
            'llm_blocked': sum(1 for r in rows if r['llm']),
            'rows': rows,
            'note': ('every model finding carries a quote that was verified to appear in the '
                     'draft; findings without a locatable quote were dropped')}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    from ml import budget
    before = budget.spent()
    r = compare(limit=int(args.get('limit', 0)))
    print(f"{r['drafts']} 篇  判官 {r['judge']}")
    print(f"规则拦下 {r['rule_blocked']} 篇 / 模型拦下 {r['llm_blocked']} 篇")
    print(f"同时命中 {r['both']} 处 · 只有规则 {r['only_rule']} 处 · 只有模型 {r['only_llm']} 处")
    print(f"花费 ${budget.spent() - before:.4f}（累计 ${budget.spent():.2f} / ${budget.cap():.0f}）\n")
    print('模型抓到而规则漏掉的（带原句，才算证据）：')
    shown = 0
    for row in r['rows']:
        extra = [x for x in row['llm_evidence'] if x['code'] not in row['rule']]
        for x in extra:
            print(f"  [{x['code']}] 「{x['quote']}」 — {x['why']}")
            shown += 1
            if shown >= 25:
                break
        if shown >= 25:
            break
    out = ROOT / 'live/store/reader_spec_compare.json'
    out.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print(f"\n写入 {out}")


if __name__ == '__main__':
    main()
