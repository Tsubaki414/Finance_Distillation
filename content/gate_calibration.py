"""每道闸门在真人语料上的误伤率。没有这个数字，闸门就是凭空发明的规则。

这个文件存在的理由是一次实测：把当时全部闸门拿去跑 1,255 条 donor 自己写的中文帖，
**19.8% 被拦下**。每五条我们正在模仿的人写的东西，就有一条过不了我们自己的关。

单看每道闸误伤率都不高（0.2%–7.5%），问题在于要**同时**通过七道。
稿子必须落进「真人只有 80% 能达到的洁净度」那个区间里，
而提示词同时强制一种真人只占 5.2% 的形状（判断+数字+相反读法+失效条件四件齐备）。
两个约束交出来的空间，是真实写作里一个极小且不自然的角落。

具体错例，都是真人写的、被我们拦下的：

    template_pivot     「所以问题不在于这个点位该不该抄底，而是为什么就非盯着存储一个板块」
    abstract_inflation  真人也会说赋能、闭环、底层逻辑
    announcing_the_point 真人也会先说「我的判断是」

## 误伤预算

每道闸门声明一个 `budget`：允许它在真人语料上误伤的比例上限。
这不是「越低越好」——有些闸门按设计就该误伤一定比例：

  * `every_sentence_carries_a_figure` 的上限取 donor 自己的 p90，
    所以它在真人身上触发约 10% 是**定义使然**，不是缺陷。
  * 纯字符串匹配类（套话、提示词泄漏）本来就该接近 0，
    因为它们匹配的是我们自己的产物，不是人类语言现象。

超预算的闸门要么调阈值，要么降级为 warning，要么删掉。
**不许在不知道误伤率的情况下新增闸门。**

Run: .venv/bin/python -B content/gate_calibration.py [--lang=zh] [--min-chars=150]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, collections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

OUT = ROOT / 'live/store/gate_calibration.json'

# 每道闸门允许的误伤上限，以及这个数字的来源。
# 没有来源的预算等于又一个拍出来的阈值，所以每条都要写清楚为什么是这个数。
BUDGET = {
    'every_sentence_carries_a_figure': (0.12, '上限取 donor 自己的 p90，按定义就该触发约 10%'),
    'hedged_attribution': (0.02, '上限取 donor 的 p99'),
    'slogan_short_sentences': (0.02, '读者列的缺陷，不是人类语言现象，应当接近 0'),
    'abstract_inflation': (0.01, '同上'),
    'announcing_the_point': (0.01, '同上'),
    'template_pivot': (0.01, '同上'),
    'weighty_ending': (0.01, '同上'),
    'mechanical_roundness': (0.01, '同上'),
    'dense_figures_thin_links': (0.02, '同上'),
    'machine_vocabulary': (0.005, '词表匹配，命中真人即为词表选错'),
    'machine_phrase': (0.005, '同上'),
    'watchlist_stated_as_market': (0.005, '口径错误，真人不会犯'),
    'overused_rule_of_three': (0.02, '结构性，取 donor 分布尾部'),
    'overused_negation_formula': (0.02, '同上'),
    'overused_hedge_stack': (0.02, '同上'),
    'overused_copula_avoidance': (0.02, '同上'),
    'sentences_all_the_same_length': (1.00, '已降级为 warning，不拦截'),
}
DEFAULT_BUDGET = (0.01, '未声明预算的闸门按最严处理')


def corpus(lang='zh', min_chars=150):
    import style as style_mod
    by = style_mod.corpus()
    out = []
    for donor, ps in by.items():
        for p in ps:
            is_en = str(p.get('lang') or '').startswith('en')
            if (lang == 'en') != is_en:
                continue
            if len(p['text']) >= min_chars:
                out.append((donor, p['text']))
    return out


def run(lang='zh', min_chars=150):
    from content.reader_spec import check as reader_check
    from content.tells import check as tell_check
    from content.leak_check import check as leak_check
    import opinions as op_mod

    posts = corpus(lang, min_chars)
    hits = collections.Counter()
    by_donor = collections.defaultdict(collections.Counter)
    blocked = 0

    for donor, text in posts:
        codes = []
        for res in (reader_check(text, lang), tell_check(text, lang),
                    leak_check(text), op_mod.overclaim_check(text, lang)):
            codes += [f['code'] for f in res.get('findings', [])
                      if f.get('severity') == 'blocking']
        if codes:
            blocked += 1
        hits.update(set(codes))
        for c in set(codes):
            by_donor[c][donor] += 1

    n = max(len(posts), 1)
    rows = []
    for code, count in hits.most_common():
        budget, why = BUDGET.get(code, DEFAULT_BUDGET)
        rate = count / n
        rows.append({
            'code': code, 'false_positives': count, 'rate': round(rate, 4),
            'budget': budget, 'budget_rationale': why,
            'over_budget': rate > budget,
            'worst_donor': by_donor[code].most_common(1)[0][0] if by_donor[code] else None,
        })
    return {
        'lang': lang, 'posts': len(posts), 'min_chars': min_chars,
        'blocked_any': blocked, 'blocked_rate': round(blocked / n, 4),
        'gates': rows,
        'over_budget': [r['code'] for r in rows if r['over_budget']],
        'note': ('误伤率 = 被拦下的真人帖占比。这些帖子由我们正在模仿的作者写成，'
                 '拦下它们说明闸门在执行一条 donor 自己不遵守的规则'),
    }


def examples(code, lang='zh', min_chars=150, k=3):
    """某道闸门误伤的真人帖原文。争论一个阈值之前先读它拦下了什么。"""
    from content.reader_spec import check as reader_check
    from content.tells import check as tell_check
    out = []
    for donor, text in corpus(lang, min_chars):
        for res in (reader_check(text, lang), tell_check(text, lang)):
            for f in res.get('findings', []):
                if f.get('code') == code and f.get('severity') == 'blocking':
                    out.append((donor, f.get('detail', '')[:90], text[:160]))
                    break
        if len(out) >= k:
            break
    return out


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    lang = args.get('lang') if isinstance(args.get('lang'), str) else 'zh'
    r = run(lang, int(args.get('min-chars', 150)))
    print(f"真人{lang}帖 {r['posts']} 条  被任一闸门拦下 {r['blocked_any']} "
          f"= {r['blocked_rate']:.1%}\n")
    print(f"{'闸门':36}{'误伤':>6}{'占比':>8}{'预算':>8}  ")
    for g in r['gates']:
        flag = '  ← 超预算' if g['over_budget'] else ''
        print(f"  {g['code']:34}{g['false_positives']:>6}{g['rate']:>8.1%}"
              f"{g['budget']:>8.1%}{flag}")
    if r['over_budget']:
        print(f"\n超预算的闸门：{r['over_budget']}")
        for code in r['over_budget'][:2]:
            print(f"\n  {code} 误伤的真人帖：")
            for donor, detail, text in examples(code, lang):
                print(f"    @{donor}: {text[:110]}")
                print(f"       判定理由: {detail}")
    OUT.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print(f"\n写入 {OUT}")


if __name__ == '__main__':
    main()
