"""Does each tell actually separate machine writing from these authors?

The borrowed rule set was written for English marketing copy. Dropping it in unexamined would
gate finance writing on somebody else's corpus. A rule that fires as often on the donors' real
posts as on generated text is not detecting a machine — it is detecting the subject matter, and
enabling it would reject the humans we are trying to imitate.

So every rule is measured on both sides before it is allowed to block:

  rate_human      per 1000 words across the real corpus
  rate_machine    per 1000 words across the generated pieces
  separation      machine rate divided by human rate

A structural threshold is then set from the human distribution (p95), not from a guess.

Run: .venv/bin/python -B ml/tell_validate.py
"""
from pathlib import Path
import sys, json, glob, statistics

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
import numpy as np
from content import tells
import style as style_mod

STRUCTURAL = list(tells.STRUCTURAL_LIMIT)


def machine_texts():
    out = []
    for p in sorted(glob.glob(str(ROOT / 'live/store/drafts/*.json'))):
        d = json.loads(Path(p).read_text())
        if d.get('text'):
            out.append((d['text'], d.get('lang') or ('zh' if tells.is_zh(d['text']) else 'en')))
    for p in sorted(glob.glob(str(ROOT / 'content/drafts/*.json'))):
        d = json.loads(Path(p).read_text())
        if d.get('text'):
            out.append((d['text'], 'zh'))
    return out


def main():
    human = [(p['text'], p.get('lang') or ('zh' if tells.is_zh(p['text']) else 'en'))
             for texts in style_mod.corpus().values() for p in texts]
    machine = machine_texts()

    def rates(rows, lang):
        per = {k: [] for k in STRUCTURAL}
        vocab = phrase = n = 0
        for t, lg in rows:
            if lg != lang:
                continue
            s = tells.scan(t, lang)
            n += 1
            vocab += bool(s['banned_words'])
            phrase += bool(s['banned_phrases'])
            for k in STRUCTURAL:
                per[k].append(s['structural_per_1000w'][k])
        return n, vocab, phrase, per

    out = {'computed_at': __import__('datetime').datetime.now(
        __import__('datetime').timezone.utc).isoformat(), 'languages': {}}

    for lang in ('zh', 'en'):
        hn, hv, hp, hper = rates(human, lang)
        mn, mv, mp, mper = rates(machine, lang)
        if not hn or not mn:
            continue
        rules = {}
        for k in STRUCTURAL:
            h = hper[k] or [0]
            m = mper[k] or [0]
            hm, mm = float(np.mean(h)), float(np.mean(m))
            p95 = float(np.percentile(h, 95))
            rules[k] = {
                'human_mean_per_1000w': round(hm, 2),
                'machine_mean_per_1000w': round(mm, 2),
                'human_p95': round(p95, 2),
                'separation': round(mm / hm, 2) if hm > 0 else None,
                'suggested_threshold': round(max(p95, 1.0), 2),
                'useful': mm > hm * 1.3 or (hm == 0 and mm > 0),
            }
        out['languages'][lang] = {
            'human_docs': hn, 'machine_docs': mn,
            'banned_vocabulary_hit_rate': {'human': round(hv / hn, 4),
                                           'machine': round(mv / mn, 4)},
            'banned_phrase_hit_rate': {'human': round(hp / hn, 4),
                                       'machine': round(mp / mn, 4)},
            'structural': rules,
        }

    (ROOT / 'ml/tell_validation.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))

    for lang, blk in out['languages'].items():
        print(f"\n=== {lang}  真人 {blk['human_docs']} 篇 · 机器 {blk['machine_docs']} 篇 ===")
        v, p = blk['banned_vocabulary_hit_rate'], blk['banned_phrase_hit_rate']
        print(f"  禁用词命中率   人 {v['human']:.1%}  机 {v['machine']:.1%}")
        print(f"  套话命中率     人 {p['human']:.1%}  机 {p['machine']:.1%}")
        print(f"  {'规则':22}{'人/千词':>9}{'机/千词':>9}{'倍数':>7}{'建议阈值':>9}  有用")
        for k, r in blk['structural'].items():
            print(f"  {k:22}{r['human_mean_per_1000w']:>9}{r['machine_mean_per_1000w']:>9}"
                  f"{str(r['separation']):>7}{r['suggested_threshold']:>9}  "
                  f"{'是' if r['useful'] else '否 ← 不该启用'}")
    return out


if __name__ == '__main__':
    main()
