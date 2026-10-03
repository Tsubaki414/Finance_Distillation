"""Metric names written the way the donors write them.

The fact labeller is a model, and a model asked to name a metric in Chinese produces the textbook
form: 总消费者物价指数. Both blind judges named that single habit as their strongest evidence of
machine writing — one of them wrote that it "违背了中文金融圈社交媒体极度依赖简称的习惯". They
were right, and it is measurable rather than a matter of taste: across 1,236 Chinese posts by the
donors, 消费者物价指数 appears **zero** times and CPI appears 54.

Every entry below was checked against the donor corpus before being added, and an entry is kept
only where the short form actually wins. That test rejected one of my own guesses: Chinese donors
write 每股收益 (8) more often than EPS (5), so Chinese keeps the full form while English uses EPS.
Counts are from the corpus on 2026-09-18; `python -B live/terms.py --audit` recounts them.

This is notation, not paraphrase. It rewrites what a figure is *called*; it never touches a value,
a unit, a scale or a direction word.
"""
from __future__ import annotations
import re

# short form -> (pattern for the long form, donor count short, donor count long)
ZH = [
    ('CPI', r'(?:总|整体|核心)?消费者物价指数|消费者价格指数|居民消费价格指数', 54, 0),
    ('PCE', r'个人消费支出(?:物价)?指数?', 19, 0),
    ('PPI', r'生产者物价指数|工业生产者出厂价格指数', 7, 0),
    ('GDP', r'国内生产总值', 5, 0),
    ('非农', r'非农业就业人口|非农就业人数|非农业部门就业', 152, 0),
    ('FOMC', r'联邦公开市场委员会', 7, 1),
    ('美联储', r'联邦储备(?:系统|理事会|委员会)', 267, 0),
    ('失业率', r'失业比率', 25, 0),
    ('毛利率', r'毛利润率', 72, 0),
    ('资本开支', r'资本性支出', 159, 19),
    ('同比', r'与去年同期相比', 120, 0),
    ('环比', r'与上月相比', 97, 0),
]

EN = [
    ('CPI', r'consumer price index', 11, 1),
    ('PCE', r'personal consumption expenditures?(?: price index)?', 12, 0),
    ('GDP', r'gross domestic product', 15, 0),
    ('EPS', r'earnings per (?:diluted )?share', 45, 2),
    ('capex', r'capital expenditures?', 100, 1),
    ('YoY', r'year[- ]over[- ]year', 32, 3),
    ('QoQ', r'quarter[- ]o(?:n|ver)[- ]quarter', 32, 1),
    ('the Fed', r'the Federal Reserve', 67, 3),
    ('FOMC', r'Federal Open Market Committee', 12, 0),
]

# Rejected, and kept visible so the same guess is not made again:
#   zh EPS   每股收益 8 vs EPS 5 — the donors prefer the full form in Chinese.
REJECTED = {'zh:EPS': 'donors write 每股收益 (8) more often than EPS (5)'}

_COMPILED = {
    'zh': [(short, re.compile(pat)) for short, pat, _, _ in ZH],
    'en': [(short, re.compile(pat, re.I)) for short, pat, _, _ in EN],
}


def canonical(text, lang='zh'):
    """Rewrite textbook metric names to the form the donors use. Figures are never touched."""
    out = text or ''
    for short, pat in _COMPILED.get(lang, []):
        out = pat.sub(short, out)
    return out


def audit(corpus_zh, corpus_en):
    """Recount every entry against a corpus. Returns rows where the recorded evidence no longer holds."""
    bad = []
    for lang, table, texts in (('zh', ZH, corpus_zh), ('en', EN, corpus_en)):
        for short, pat, want_short, want_long in table:
            p = rf'\b{re.escape(short)}\b' if short.isascii() else re.escape(short)
            s = sum(len(re.findall(p, t, re.I)) for t in texts)
            f = sum(len(re.findall(pat, t, re.I)) for t in texts)
            if not (s > f and s >= 3):
                bad.append({'lang': lang, 'short': short, 'now_short': s, 'now_long': f,
                            'recorded': [want_short, want_long]})
    return bad


if __name__ == '__main__':
    import sys, json
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'live'))
    import style as style_mod
    by = style_mod.corpus()
    zh = [p['text'] for _, ps in by.items() for p in ps
          if not (p.get('lang') or '').lower().startswith('en')]
    en = [p['text'] for _, ps in by.items() for p in ps
          if (p.get('lang') or '').lower().startswith('en')]
    bad = audit(zh, en)
    print(json.dumps(bad, ensure_ascii=False, indent=2) if bad
          else f'all {len(ZH) + len(EN)} entries still hold in the corpus')
