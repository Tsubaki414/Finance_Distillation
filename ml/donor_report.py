"""One readable inventory of every donor in the corpus, written to docs/DONOR_INVENTORY.md.

Four separate measurements in this project each turned out to depend on how much material a
donor actually has, and each discovered it the hard way and in isolation:

  * `beth_kindig` has 113 posts but only 8 long enough to measure sentence-length variation, so
    her band could not be built and the pooled floor was used for her account instead.
  * Her `fragment_rate` and `first_person_rate` bands came out zero-width, which the style gate
    then enforced as "reproduce exactly zero" and blocked a draft for writing the short sentences
    a different gate had demanded.
  * `xingpt` has volume but the authorship classifier cannot separate him from two other Chinese
    donors — recall 0.250 — so the voice assigned to an account is one no measurement can confirm
    is distinct.
  * `globalmktobserv` and `beth_kindig` never entered the authorship evaluation at all, for want
    of test support.

None of that was visible in one place. This writes it in one place, so the question "can this
account's donor carry a voice" has an answer that does not require reading four JSON files and
remembering which threshold came from where.

Nothing here computes a new number. Every figure is read from the same functions the gates use —
`content.tells.sentence_variation`, `live.style.build_target`, `ml_experiments/authorship_v2.json`
— so the report cannot disagree with the pipeline about a donor's numbers.

Run: .venv/bin/python -B ml/donor_report.py
"""
from pathlib import Path
import sys, json, datetime, collections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

from content.tells import sentence_variation, cv_band, figure_density
import style as style_mod

OUT = ROOT / 'docs/DONOR_INVENTORY.md'
# Prefer the merged-corpus run. The archive-only run evaluates six donors; the merged one
# evaluates fourteen, and two donors this report had been calling "not evaluated" turn out to be
# among the most separable in the corpus (globalmktobserv recall 1.0, beth_kindig 0.929). A
# report that reads the narrower file states an absence of evidence as if it were evidence.
AUTHORSHIP_MERGED = ROOT / 'ml_experiments/authorship_merged.json'
AUTHORSHIP_ARCHIVE = ROOT / 'ml_experiments/authorship_v2.json'
AUTHORSHIP = AUTHORSHIP_MERGED if AUTHORSHIP_MERGED.is_file() else AUTHORSHIP_ARCHIVE
MIN_CV_POSTS = 30           # live/style.py MIN_POSTS_FOR_CV_BAND
MIN_STYLE_POSTS = 60        # live/style.py MIN_POSTS


def _lang_of(post):
    return 'en' if (post.get('lang') or '').lower().startswith('en') else 'zh'


def _pct(values, q):
    v = sorted(values)
    return round(v[max(0, min(len(v) - 1, int(q * len(v))))], 3) if v else None


def gather():
    by = style_mod.corpus()
    cfg = json.loads((ROOT / 'live/sources.json').read_text())
    accounts = json.loads((ROOT / 'live/accounts.json').read_text())['accounts']
    watched = {a['handle'] for a in cfg['x_accounts']}
    learning = {a['handle'] for a in (cfg.get('learning_accounts') or [])}
    assigned = {}
    for a in accounts:
        h = (a.get('language_donor') or {}).get('handle')
        if h:
            assigned.setdefault(h, []).append(a['id'])

    auth = json.loads(AUTHORSHIP.read_text()) if AUTHORSHIP.is_file() else {}
    usable = set(auth.get('usable_as_language_donor') or [])
    undet = set(auth.get('undetermined') or [])
    per = auth.get('per_author') or {}
    recall = per if isinstance(per, dict) else {}

    rows = []
    for donor, posts in by.items():
        langs = collections.Counter(_lang_of(p) for p in posts)
        lang = langs.most_common(1)[0][0] if langs else 'zh'
        cvs = [c for c, _ in (sentence_variation(p['text'], lang) for p in posts)
               if c is not None]
        dens = [d for d, n in (figure_density(p['text']) for p in posts)
                if d is not None and n >= 5]
        target = style_mod.build_target(donor, posts, lang=lang)
        # Only a zero-width band on a *gated* feature can block a draft. `conclusion_opener` is
        # zero-width for every donor in the corpus — real writers almost never open with a
        # conclusion label — and reporting that as a defect for all 62 authors would bury the two
        # cases that actually matter.
        zero_width, zero_width_ungated = [], []
        if target.get('usable'):
            for k, b in (target.get('targets') or {}).items():
                if b.get('p90', 0) - b.get('p10', 0) <= 0:
                    (zero_width if k in style_mod.GATED else zero_width_ungated).append(k)
        rows.append({
            'donor': donor, 'lang': lang, 'posts': len(posts),
            'langs': dict(langs),
            'cv_posts': len(cvs),
            'cv_p10': _pct(cvs, .10), 'cv_p50': _pct(cvs, .50), 'cv_p90': _pct(cvs, .90),
            'density_p50': _pct(dens, .50), 'density_p90': _pct(dens, .90),
            'style_target_usable': bool(target.get('usable')),
            'style_target_why': target.get('why'),
            'zero_width_features': zero_width,
            'zero_width_ungated': zero_width_ungated,
            'authorship': ('usable' if donor in usable else
                           'undetermined' if donor in undet else 'not evaluated'),
            'recall': (recall.get(donor) or {}).get('recall'),
            'watchlist': 'x_accounts' if donor in watched else (
                'learning' if donor in learning else 'not collected'),
            'assigned_to': assigned.get(donor) or [],
        })
    rows.sort(key=lambda r: (-len(r['assigned_to']), -r['posts']))
    return rows, accounts, auth


def verdict(r):
    """Can this donor carry a voice? Stated as what is missing, never as a bare yes."""
    missing = []
    if r['posts'] < MIN_STYLE_POSTS:
        missing.append(f"帖数 {r['posts']} < {MIN_STYLE_POSTS}")
    if r['cv_posts'] < MIN_CV_POSTS:
        missing.append(f"可测句长 {r['cv_posts']} < {MIN_CV_POSTS}")
    if r['zero_width_features']:
        missing.append('闸门特征零宽区间: ' + ', '.join(r['zero_width_features']))
    if r['authorship'] == 'undetermined':
        missing.append(f"可分辨性 undetermined (recall {r['recall']})")
    elif r['authorship'] == 'not evaluated':
        missing.append('未进入可分辨性评估')
    return missing


def markdown(rows, accounts, auth):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    total = sum(r['posts'] for r in rows)
    out = [
        '# Donor 样本清单',
        '',
        f'生成于 {now}。共 {len(rows)} 位作者、{total} 条帖子。',
        '',
        '本文件由 `ml/donor_report.py` 生成，**不要手改**。',
        '每个数字都来自闸门本身使用的同一批函数（`content.tells.sentence_variation`、',
        '`live.style.build_target`、`ml_experiments/authorship_v2.json`），',
        '所以这份报告不会和管线对同一位 donor 给出不同的数。',
        '',
        '## 四个账号的语言 donor',
        '',
        '| 账号 | donor | 帖数 | 可测句长 | 可分辨性 | 缺什么 |',
        '| --- | --- | --- | --- | --- | --- |',
    ]
    for a in accounts:
        h = (a.get('language_donor') or {}).get('handle')
        r = next((x for x in rows if x['donor'] == h), None)
        if not r:
            out.append(f"| {a['id']} | {h} | — | — | — | 语料中没有这位作者 |")
            continue
        m = verdict(r)
        out.append(f"| {a['id']} | {h} | {r['posts']} | {r['cv_posts']} | "
                   f"{r['authorship']} | {'；'.join(m) if m else '—' } |")
    out += [
        '',
        '判定门槛：帖数 ≥ 60（`live/style.py MIN_POSTS`）、可测句长帖 ≥ 30',
        '（`MIN_POSTS_FOR_CV_BAND`）、可分辨性来自 authorship 五组基线。',
        '',
        '## 全部作者',
        '',
        '| 作者 | 语种 | 帖数 | 可测句长 | CV p10/中位/p90 | 数字密度 中位/p90 | 风格区间 | 可分辨性 | 采集列表 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for r in rows:
        cv = (f"{r['cv_p10']}/{r['cv_p50']}/{r['cv_p90']}"
              if r['cv_p10'] is not None else '—')
        de = (f"{r['density_p50']}/{r['density_p90']}"
              if r['density_p50'] is not None else '—')
        st = '可用' if r['style_target_usable'] else '不可用'
        if r['zero_width_features']:
            st += f" ⚠闸门零宽:{','.join(r['zero_width_features'])}"
        mark = ' ★' if r['assigned_to'] else ''
        out.append(f"| {r['donor']}{mark} | {r['lang']} | {r['posts']} | {r['cv_posts']} | "
                   f"{cv} | {de} | {st} | {r['authorship']} | {r['watchlist']} |")
    out += [
        '',
        '★ = 已指派给某个账号作为语言 donor。',
        '',
        '## 可替换的候选',
        '',
        '可分辨性评估判定为 usable、且尚未被指派的作者：',
        '',
    ]
    free = [r for r in rows if r['authorship'] == 'usable' and not r['assigned_to']]
    if free:
        for r in free:
            out.append(f"- **{r['donor']}**（{r['lang']}，{r['posts']} 帖，"
                       f"可测句长 {r['cv_posts']}，recall {r['recall']}）")
    else:
        out.append('- 无。所有通过可分辨性评估的作者都已被指派。')
    out += [
        '',
        '## 这份清单的局限',
        '',
        '- 可分辨性只说明**这些作者彼此之间**能否区分，不说明某个生成出来的人设是否可辨认。',
        '- 样本量门槛是本项目自己设的，不是统计学意义上的充分性证明。',
        '- 未进入评估的作者是**证据缺失**，不是证据表明不可用；补足样本后需重跑。',
        '- 所有数字随语料增长而变化，采集之后应重新生成本文件。',
        '- 只有**被闸门使用的**特征零宽才会挡稿；`conclusion_opener` 对全部 62 位作者都是零宽，',
        '  那是因为真人几乎不用结论式开头，不是缺陷，故不计入「缺什么」。',
        '',
    ]
    return '\n'.join(out)


def main():
    rows, accounts, auth = gather()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(markdown(rows, accounts, auth), encoding='utf-8')
    print(f'写入 {OUT}')
    print(f'  {len(rows)} 位作者，{sum(r["posts"] for r in rows)} 条帖子')
    for a in accounts:
        h = (a.get('language_donor') or {}).get('handle')
        r = next((x for x in rows if x['donor'] == h), None)
        m = verdict(r) if r else ['语料中没有这位作者']
        print(f"  {a['id']:12} {str(h):18} {'✅' if not m else '⚠ ' + '；'.join(m)}")


if __name__ == '__main__':
    main()
