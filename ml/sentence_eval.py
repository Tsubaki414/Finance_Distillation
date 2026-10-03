"""Does a figure-bearing sentence look like the donors' or like ours?

One number decides whether the LoRA run was worth anything, and it was chosen before training so
it cannot be picked afterwards to suit the result:

    label-before-number     指标名 + 数字 + 逗号 + 从句, counted per 1000 characters

    donors      5.03      counted over 1,344 of their own Chinese posts
    local 4B   22.44      4.5x
    grok-4.5   12.90      2.6x
    grok-4.6   12.74      2.5x

Every draft this system produced opened its figure-bearing sentences that way — eight of eight —
and the donors never do. A human rated the result 0.17 out of 5 for naturalness and marked every
piece 重写.

This also reports the construction distribution: where in the sentence the figure lands, and what
grammatical role it plays. Two texts can share a label-before-number rate and still read
differently, so the rate is the headline and the distribution is what makes a change legible.

**This is a diagnostic, not an acceptance test.** The evaluation contract is explicit that
AI-pattern flags 「do not establish machine authorship」, and this one is the same kind of number:
it says how closely a construction habit matches a corpus. Whether the writing reads naturally is
a human's call, and `ml/human_review.py` is where that gets answered.

Run: .venv/bin/python -B ml/sentence_eval.py [--text-file=...] [--adapter=...]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, collections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

SENT = re.compile(r'[^。！？\n]+[。！？]?')
HAS_DIGIT = re.compile(r'\d')
NUM = re.compile(r'[-+]?\d[\d,]*(?:\.\d+)?\s*'
                 r'(?:%|万亿|亿|万|个百分点|个基点|美元|日元|韩元|元|人|倍)?')

# The shape under test: a metric name, its figure, then a comma and the rest of the sentence.
LABEL_BEFORE_NUMBER = re.compile(
    r'[一-鿿]{2,8}\s?[-+]?\d[\d,.]*\s?(?:%|万亿|亿|万|个百分点|个基点|美元|日元|韩元|元|人)')

DONOR_BASELINE = {'label_before_number_per_1k': 5.03, 'n_posts': 1344,
                  'measured': '2026-09-22 over the donors own Chinese posts'}


def _figure_positions(sentence):
    """Where each figure sits, as a fraction of the sentence, and what precedes it."""
    out = []
    n = len(sentence) or 1
    for m in NUM.finditer(sentence):
        if not HAS_DIGIT.search(m.group(0)):
            continue
        head = sentence[:m.start()]
        out.append({
            'position': round(m.start() / n, 2),
            'chars_before': m.start(),
            # A figure that opens the sentence, or follows only a short noun, is the shape that
            # makes our drafts recognisable.
            'opens_sentence': m.start() <= 8,
            'follows_verb': bool(re.search(r'(?:至|到|为|是|达|升|降|砍|减|增|涨|跌)\s*$', head)),
        })
    return out


def profile(texts, label='text'):
    chars = sum(len(t) for t in texts) or 1
    sents, with_fig, opens, verbs, positions = 0, 0, 0, 0, []
    lbn = 0
    for t in texts:
        lbn += len(LABEL_BEFORE_NUMBER.findall(t))
        for s in SENT.findall(t):
            s = s.strip()
            if len(s) < 6:
                continue
            sents += 1
            figs = _figure_positions(s)
            if not figs:
                continue
            with_fig += 1
            opens += any(f['opens_sentence'] for f in figs)
            verbs += any(f['follows_verb'] for f in figs)
            positions += [f['position'] for f in figs]
    med = sorted(positions)[len(positions) // 2] if positions else None
    return {
        'label': label,
        'chars': chars, 'sentences': sents, 'figure_sentences': with_fig,
        'label_before_number_per_1k': round(lbn / chars * 1000, 2),
        'vs_donors': (round(lbn / chars * 1000 / DONOR_BASELINE['label_before_number_per_1k'], 2)
                      if chars else None),
        'figure_opens_sentence_share': round(opens / max(with_fig, 1), 3),
        'figure_follows_verb_share': round(verbs / max(with_fig, 1), 3),
        'median_figure_position': med,
        'note': ('a diagnostic of construction habit against a corpus; it does not establish '
                 'machine authorship and is not an acceptance test'),
    }


def donors():
    import style as style_mod
    by = style_mod.corpus()
    return [p['text'] for _, ps in by.items() for p in ps
            if not (p.get('lang') or '').lower().startswith('en')]


def our_drafts(status='ready_for_queue'):
    out = []
    for f in sorted((ROOT / 'live/store/drafts').glob('*.json')):
        d = json.loads(f.read_text())
        if d.get('status') == status and (d.get('lang') or 'zh') == 'zh' and d.get('text'):
            out.append(d['text'])
    return out


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    rows = [profile(donors(), 'donors 真人'), profile(our_drafts(), 'ours 当前稿件')]
    if isinstance(args.get('text-file'), str):
        p = Path(args['text-file'])
        rows.append(profile([x for x in p.read_text(encoding='utf-8').split('\n---\n') if x.strip()],
                            p.name))
    print(f"{'来源':18}{'label前置/千字':>14}{'相对真人':>9}{'数字开头占比':>13}"
          f"{'数字跟动词':>11}{'数字中位位置':>13}")
    for r in rows:
        print(f"  {r['label']:16}{r['label_before_number_per_1k']:>14}{str(r['vs_donors'])+'x':>9}"
              f"{r['figure_opens_sentence_share']:>13}{r['figure_follows_verb_share']:>11}"
              f"{str(r['median_figure_position']):>13}")
    print(f"\n  真人基线 {DONOR_BASELINE['label_before_number_per_1k']} /千字"
          f"（{DONOR_BASELINE['n_posts']} 帖，{DONOR_BASELINE['measured']}）")
    print('  这是诊断，不是验收。验收在 ml/human_review.py。')
    out = ROOT / 'ml_experiments/sentence_eval.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'rows': rows, 'donor_baseline': DONOR_BASELINE},
                              ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
