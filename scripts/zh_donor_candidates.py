#!/usr/bin/env python3
"""Rank existing Chinese corpus authors as language-donor candidates for zh_macro / zh_industry (read-only).

Only real handles from live/donors/roster.json (lang zh, donor_fit != exclude, not promo_heavy) with posts in
live/donors/posts. Per author: originals (no RT / reply / pinned), beat fit = share of originals hitting the
account's beat keywords minus the crypto share, authorship recall from ml_experiments/authorship_merged.json
(only 14 authors were evaluable there; others are n/a), and one short real sample line on the beat.
score = max(fit, 0) * log10(1 + originals) * (recall if known else 0.7). Donors are NOT changed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEATS = {
    'zh_macro': re.compile(r'美联储|联储|加息|降息|利率|通胀|CPI|PCE|非农|就业|失业|美债|收益率|国债|美元|日元|汇率|关税|'
                           r'央行|流动性|油价|衰退|GDP|财政|缩表|FOMC|鲍威尔|降准|人民币', re.I),
    'zh_industry': re.compile(r'财报|营收|毛利|产能|芯片|半导体|算力|供应链|HBM|存储|DRAM|NAND|英伟达|台积电|订单|capex|'
                              r'资本开支|数据中心|光模块|指引|晶圆|封装|GPU|AI服务器|云厂|博通|美光|AMD', re.I),
}
CRYPTO = re.compile(r'比特币|BTC|ETH|以太坊|币圈|链上|稳定币|山寨|空投|meme币|Solana|SOL\b', re.I)
CJK = re.compile(r'[一-鿿]')


def originals(handle):
    path = ROOT / 'live' / 'donors' / 'posts' / (handle.lower() + '.jsonl')
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            p = json.loads(line)
        except ValueError:
            continue
        if p.get('rt') or p.get('reply') or p.get('pinned') or not isinstance(p.get('text'), str):
            continue
        if len(CJK.findall(p['text'])) >= 15:
            out.append(p['text'])
    return out


def sample(texts, rx):
    for t in texts:
        for s in re.split(r'[。！？!?\n]+', t):
            s = s.strip()
            n = len(CJK.findall(s))
            if (14 <= n <= 38 and rx.search(s) and not re.search(r'https?://|@|#|\$|[“”"「」>《]|我们', s)
                    and not CRYPTO.search(s)):   # the author's own words, not a quote
                return s
    return ''


def rank(account, top=5):
    roster = json.loads((ROOT / 'live/donors/roster.json').read_text())['donors']
    auth = json.loads((ROOT / 'ml_experiments/authorship_merged.json').read_text())
    recall = {k.lower(): v for k, v in auth['per_author'].items()}
    rx = BEATS[account]
    rows = []
    for key, d in roster.items():
        if d.get('lang') != 'zh' or d.get('donor_fit') == 'exclude' or d.get('promo_heavy'):
            continue
        texts = originals(d['handle'])
        if len(texts) < 20:
            continue
        beat = sum(bool(rx.search(t)) for t in texts) / len(texts)
        crypto = sum(bool(CRYPTO.search(t)) for t in texts) / len(texts)
        r = recall.get(key)
        fit = beat - crypto
        rows.append({'handle': d['handle'], 'category': d.get('category'), 'current_cluster': d.get('persona_cluster'),
                     'originals': len(texts), 'beat_share': round(beat, 3), 'crypto_share': round(crypto, 3),
                     'authorship_recall': r['recall'] if r else None,
                     'authorship_test_n': r['test_n'] if r else None,
                     'score': round(max(fit, 0) * math.log10(1 + len(texts)) * (r['recall'] if r else 0.7), 3),
                     'sample': sample(texts, rx)})
    rows.sort(key=lambda x: -x['score'])
    return rows[:top]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--top', type=int, default=5)
    a = ap.parse_args()
    result = {acc: rank(acc, a.top) for acc in BEATS}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text)
    print(text)


if __name__ == '__main__':
    main()
