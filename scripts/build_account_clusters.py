#!/usr/bin/env python3
"""Per-account donor clusters (Fiona 2026-10-06 13:21: every account uses >= 3 real donors).

Only real handles from live/donors/roster.json with local posts in live/donors/posts: same language as the
account, donor_fit == voice, verified, not promo_heavy. Per candidate (originals only: no RT / reply / pinned):
  beat     share of originals hitting the account's beat keywords; non-crypto accounts subtract the crypto share
  n        originals (>= MIN_POSTS to qualify)
  distinct leave-out nearest-centroid recall inside the language pool (char 1-2grams ZH / word 1-grams EN,
           held-out 20% of each author's posts by id hash) - can the voice be told apart from the others?
  score    max(beat, 0) * log10(1 + n) * (0.5 + 0.5 * distinct)
Donors writing mostly Traditional Chinese (> MAX_TRAD_SHARE of originals) are not candidates for the Simplified
ZH accounts. Qualified: n >= MIN_POSTS, beat >= MIN_BEAT, distinct >= MIN_DISTINCT. The account's current donor (accounts.json
language_donor, else the top donor of the persona's current cluster) is always kept. A candidate whose centroid is
near-identical (cosine >= DUP_COS) to an already chosen donor is skipped (no second copy of one voice). Enabled
accounts of one language do not share donors (zh_macro and zh_industry must not sound alike): a donor goes to the
enabled account where it scores best; disabled accounts may reuse donors. Up to MAX_DONORS; weights ~ score, floor
WEIGHT_FLOOR, capped at registry.MAX_EXEMPLAR_WEIGHT. An account that cannot reach 3 qualified donors
gets the best available non-qualified candidates, each marked with a note.

Default prints the table; --write records roster.persona_clusters['acct_<account>'] (previous cluster kept as
previous_cluster), points live/personas/<account>.json donor_cluster at it (lineage keeps the old name) and adds
donor_cluster + language_donor_history to live/accounts.json. Morris (en_morris_archive) is excluded: its voice is
the source author's by product rule (aphorism_translation), not a donor imitation.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_POSTS, MIN_BEAT, MIN_DISTINCT, DUP_COS, MAX_DONORS, MIN_DONORS = 60, 0.2, 0.35, 0.985, 5, 3
WEIGHT_FLOOR = 0.08   # a kept member still shows up in anchor / exemplar rotation
CJK = re.compile(r'[一-鿿]')
URL = re.compile(r'https?://\S+')
CRYPTO = re.compile(r'比特币|BTC|ETH|以太坊|币圈|链上|稳定币|山寨|空投|meme|Solana|\bSOL\b|bitcoin|crypto|ethereum|'
                    r'stablecoin|on-?chain|altcoin|defi\b|token', re.I)
BEATS = {
    'zh_macro': re.compile(r'美联储|联储|加息|降息|利率|通胀|CPI|PCE|非农|就业|失业|美债|收益率|国债|美元|日元|汇率|关税|'
                           r'央行|流动性|油价|衰退|GDP|财政|缩表|FOMC|鲍威尔|降准|人民币', re.I),
    'zh_industry': re.compile(r'财报|营收|毛利|产能|芯片|半导体|算力|供应链|HBM|存储|DRAM|NAND|英伟达|台积电|订单|capex|'
                              r'资本开支|数据中心|光模块|指引|晶圆|封装|GPU|AI服务器|云厂|博通|美光|AMD', re.I),
    'crypto_macro_zh': CRYPTO,
    'en_macro': re.compile(r'\bfed\b|fomc|rate (?:cut|hike)s?|inflation|\bcpi\b|\bpce\b|payrolls?|jobs report|unemployment|'
                           r'treasur(?:y|ies)|yields?|\bdollar\b|\byen\b|\bfx\b|tariffs?|central bank|liquidity|\boil\b|'
                           r'recession|\bgdp\b|fiscal|powell|\becb\b|\bboj\b|curve|bond', re.I),
    'en_industry': re.compile(r'earnings|revenue|guidance|margins?|capex|semis?|semiconductor|chips?|gpus?|nvidia|\bnvda\b|'
                              r'tsmc|hbm|dram|nand|memory|data ?cent(?:er|re)s?|hyperscaler|supply chain|capacity|'
                              r'foundry|wafer|backlog|orders|broadcom|\bamd\b|micron|optic', re.I),
    'trading_shortterm': re.compile(r'gamma|dealer|options?|\bcalls?\b|\bputs?\b|\bvix\b|vol(?:atility)?\b|0dte|opex|'
                                    r'support|resistance|breakout|setup|chart|trend|positioning|flows?|squeeze|\bspx\b|'
                                    r'\bspy\b|\bqqq\b|hedg', re.I),
    'market_data_charts': re.compile(r'breadth|sentiment|flows?|inflows?|outflows?|\betfs?\b|percent(?:ile)?|since \d{4}|'
                                     r'record|historical|year-to-date|\bytd\b|survey|positioning|\baaii\b|s&p|chart|'
                                     r'average|median|highest|lowest', re.I),
    'investing_philosophy': re.compile(r'risk|behavio(?:u)?r|long[- ]term|compound|patien|discipline|process|mistake|'
                                       r'investor|investing|portfolio|diversif|returns?|psycholog|time horizon|fees?|'
                                       r'luck|wealth|lesson', re.I),
    'single_stock_deepdive_en': re.compile(r'earnings|revenue|eps|guidance|quarter|\bq[1-4]\b|10-?[kq]|filing|margins?|'
                                           r'free cash flow|\bfcf\b|buyback|valuation|multiple|\$[A-Z]{1,5}\b|beat|miss', re.I),
    'crypto_macro_en': CRYPTO,
}


def _cjk(text):
    return len(CJK.findall(text))


# Traditional-only characters (same set as live/zh_register._TRAD): the ZH accounts write Simplified Chinese.
TRAD = re.compile(r'[這們個說沒會對時為來還過與從經關點於後實當應發見裡問題將開長東動錢國際場價漲聯準債險議資產業報貨幣銀權爭預測]')
MAX_TRAD_SHARE = 0.3   # share of a donor's ZH originals with >= 2 traditional-only characters


def trad_share(posts):
    return sum(len(TRAD.findall(p['text'])) >= 2 for p in posts) / len(posts) if posts else 0.0


def originals(handle, lang, posts_dir):
    path = Path(posts_dir) / (handle.lower() + '.jsonl')
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            p = json.loads(line)
        except ValueError:
            continue
        text = URL.sub('', p.get('text') or '').strip() if isinstance(p.get('text'), str) else ''
        if p.get('rt') or p.get('reply') or p.get('pinned') or not text:
            continue
        if (lang == 'zh' and _cjk(text) >= 15) or (lang == 'en' and _cjk(text) == 0 and len(text) >= 60):
            out.append({'id': str(p.get('id')), 'text': text})
    return out


def features(text, lang):
    if lang == 'zh':
        chars = [c for c in text if not c.isspace()]
        grams = chars + [a + b for a, b in zip(chars, chars[1:])]
    else:
        grams = re.findall(r"[a-z']+|[.,!?;:$%—-]", text.lower())
    return collections.Counter(grams)


def _norm(c):
    s = math.sqrt(sum(v * v for v in c.values())) or 1.0
    return {k: v / s for k, v in c.items()}


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def _held_out(post_id):
    return int(hashlib.sha256(post_id.encode()).hexdigest()[:8], 16) % 5 == 0


def distinctness(pool, lang):
    """{handle: (recall, centroid)} by leave-out nearest centroid over the whole language pool."""
    train, test = {}, {}
    for h, posts in pool.items():
        c = collections.Counter()
        for p in posts:
            if not _held_out(p['id']):
                c.update(features(p['text'], lang))
        train[h] = _norm(c)
        test[h] = [_norm(features(p['text'], lang)) for p in posts if _held_out(p['id'])]
    out = {}
    for h, vecs in test.items():
        hits = sum(1 for v in vecs if max(train, key=lambda o: _cos(v, train[o])) == h)
        out[h] = (round(hits / len(vecs), 3) if vecs else None, train[h])
    return out


def current_donor(account, accounts, roster):
    acc = next((a for a in accounts['accounts'] if a['id'] == account), {})
    ld = (acc.get('language_donor') or {}).get('handle')
    if ld:
        return ld
    persona = json.loads((ROOT / 'live/personas' / (account + '.json')).read_text())
    name = persona.get('donor_cluster')
    if str(name).startswith('acct_'):   # re-run: the current donor comes from the cluster this one replaced
        name = (roster['persona_clusters'].get(name) or {}).get('previous_cluster')
    cl = roster['persona_clusters'].get(name) or {}
    donors = sorted(cl.get('donors') or [], key=lambda d: -d['weight'])
    return donors[0]['handle'] if donors else None


def cap_weights(raw, cap, floor=WEIGHT_FLOOR):
    total = sum(max(v, 1e-6) for v in raw.values())
    w = {h: max(v, 1e-6) / total for h, v in raw.items()}
    for _ in range(50):
        low = {h for h, v in w.items() if v < floor}
        high = {h for h, v in w.items() if v > cap}
        if not low and not high:
            break
        fixed = {h: (floor if h in low else cap) for h in low | high}
        free = {h: v for h, v in w.items() if h not in fixed}
        spare = 1 - sum(fixed.values())
        ftot = sum(free.values()) or 1.0
        w = {**fixed, **{h: v * spare / ftot for h, v in free.items()}}
    out = {h: round(v, 3) for h, v in w.items()}
    top = max(out, key=out.get)
    out[top] = round(out[top] + 1 - sum(out.values()), 3)
    return out


def build(posts_dir=None, roster_path=None, accounts_path=None):
    posts_dir = posts_dir or ROOT / 'live/donors/posts'
    roster = json.loads(Path(roster_path or ROOT / 'live/donors/roster.json').read_text())
    accounts = json.loads(Path(accounts_path or ROOT / 'live/accounts.json').read_text())
    from live.registry import MAX_EXEMPLAR_WEIGHT
    auth = json.loads((ROOT / 'ml_experiments/authorship_merged.json').read_text()).get('per_author', {}) \
        if (ROOT / 'ml_experiments/authorship_merged.json').exists() else {}
    auth = {k.lower(): v for k, v in auth.items()}
    pools = {}
    for lang in ('zh', 'en'):
        pool = {}
        for key, d in roster['donors'].items():
            if d.get('lang') != lang or d.get('donor_fit') != 'voice' or not d.get('verified') or d.get('promo_heavy'):
                continue
            posts = originals(d['handle'], lang, posts_dir)
            if len(posts) >= 20:
                pool[d['handle']] = posts
        pools[lang] = (pool, distinctness(pool, lang))
    owner = {}   # (lang, handle) -> enabled account where the donor fits best
    enabled = [a for a in accounts['accounts'] if a['id'] in BEATS and a.get('enabled')]
    for a in enabled:   # current donors stay with their own account
        cur = current_donor(a['id'], accounts, roster)
        if cur:
            owner[(a['lang'], cur.lower())] = a['id']
    for lang in ('zh', 'en'):
        pool, dist = pools[lang]
        for h, posts in pool.items():
            if (lang, h.lower()) in owner:
                continue
            best = None
            for a in enabled:
                if a['lang'] != lang:
                    continue
                rx = BEATS[a['id']]
                fit = sum(bool(rx.search(p['text'])) for p in posts) / len(posts)
                if not a['id'].startswith('crypto_'):
                    fit -= sum(bool(CRYPTO.search(p['text'])) for p in posts) / len(posts)
                if best is None or fit > best[0]:
                    best = (fit, a['id'])
            if best:
                owner[(lang, h.lower())] = best[1]
    result = {}
    for acc in accounts['accounts']:
        account = acc['id']
        if account not in BEATS:
            continue
        lang = acc['lang']
        pool, dist = pools[lang]
        rx, crypto_acc = BEATS[account], account.startswith('crypto_')
        rows = []
        for h, posts in pool.items():
            beat = sum(bool(rx.search(p['text'])) for p in posts) / len(posts)
            crypto = sum(bool(CRYPTO.search(p['text'])) for p in posts) / len(posts)
            fit = beat if crypto_acc else beat - crypto
            recall = dist[h][0] or 0.0
            score = max(fit, 0) * math.log10(1 + len(posts)) * (0.5 + 0.5 * recall)
            trad = trad_share(posts) if lang == 'zh' else 0.0
            if trad > MAX_TRAD_SHARE:
                continue   # Traditional-Chinese voice; the ZH accounts write Simplified
            qualified = len(posts) >= MIN_POSTS and fit >= MIN_BEAT and recall >= MIN_DISTINCT
            other = owner.get((lang, h.lower()))
            if acc.get('enabled') and other and other != account:
                continue   # belongs to another enabled account of this language
            rows.append({'handle': h, 'category': roster['donors'][h.lower()].get('category'), 'originals': len(posts),
                         'beat_share': round(beat, 3), 'crypto_share': round(crypto, 3), 'fit': round(fit, 3),
                         'distinct_recall': recall, 'authorship_recall': (auth.get(h.lower()) or {}).get('recall'),
                         'score': round(score, 3), 'qualified': qualified})
        rows.sort(key=lambda r: -r['score'])
        cur = current_donor(account, accounts, roster)
        by_handle = {r['handle'].lower(): r for r in rows}
        chosen, notes = [], []
        if cur and cur.lower() in by_handle:
            chosen.append(by_handle[cur.lower()])
            c = by_handle[cur.lower()]
            if not c['qualified']:
                notes.append(f"current donor {c['handle']} kept below the bar (fit {c['fit']}, distinct "
                             f"{c['distinct_recall']}) at the weight floor")
        elif cur:
            notes.append(f'current donor {cur} has no usable {lang} voice posts; not carried')

        def near_dup(r):
            return any(_cos(dist[r['handle']][1], dist[c['handle']][1]) >= DUP_COS for c in chosen)
        for r in rows:
            if len(chosen) >= MAX_DONORS:
                break
            if r in chosen or not r['qualified']:
                continue
            if near_dup(r):
                notes.append(f"{r['handle']} skipped: near-identical voice to a chosen donor")
                continue
            chosen.append(r)
        for r in rows:   # fewer than 3 qualified: best available, marked
            if len(chosen) >= MIN_DONORS:
                break
            if r not in chosen and r['fit'] > 0:
                chosen.append(r)
                notes.append(f"{r['handle']} below the bar (n {r['originals']}, fit {r['fit']}, distinct "
                             f"{r['distinct_recall']}); best available")
        raw = {c['handle']: max(c['score'], 0.05) for c in chosen}
        weights = cap_weights(raw, MAX_EXEMPLAR_WEIGHT) if len(raw) >= 3 else {h: round(1 / len(raw), 3) for h in raw}
        donors = []
        for c in chosen:
            why = (f"beat {c['fit']:.0%} of {c['originals']} originals"
                   + (f", crypto {c['crypto_share']:.0%}" if c['crypto_share'] >= 0.05 and not crypto_acc else '')
                   + f", voice distinct {c['distinct_recall']:.2f}"
                   + (' (current donor)' if cur and c['handle'].lower() == cur.lower() else '')
                   + ('' if c['qualified'] else ' [below bar]'))
            donors.append({'handle': c['handle'], 'weight': weights[c['handle']], 'why': why,
                           'stats': {k: c[k] for k in ('originals', 'beat_share', 'crypto_share', 'distinct_recall',
                                                        'authorship_recall', 'score', 'qualified')}})
        donors.sort(key=lambda d: -d['weight'])
        result[account] = {'lang': lang, 'current_donor': cur, 'donors': donors, 'notes': notes,
                           'qualified_count': sum(1 for c in chosen if c['qualified']),
                           'candidates': rows[:12]}
    return result


def write(result, roster_path=None, accounts_path=None, personas_dir=None):
    roster_path = Path(roster_path or ROOT / 'live/donors/roster.json')
    accounts_path = Path(accounts_path or ROOT / 'live/accounts.json')
    personas_dir = Path(personas_dir or ROOT / 'live/personas')
    roster = json.loads(roster_path.read_text())
    accounts = json.loads(accounts_path.read_text())
    today = dt.date.today().isoformat()
    method = ('scripts/build_account_clusters.py: beat fit x log10(1+originals) x (0.5+0.5*voice distinctness); '
              f'qualified n>={MIN_POSTS}, fit>={MIN_BEAT}, distinct>={MIN_DISTINCT}; current donor kept')
    for account, r in result.items():
        persona_path = personas_dir / (account + '.json')
        persona = json.loads(persona_path.read_text())
        name = 'acct_' + account
        prev = persona.get('donor_cluster')
        if prev == name:
            prev = roster['persona_clusters'].get(name, {}).get('previous_cluster')
        roster['persona_clusters'][name] = {
            'lang': r['lang'], 'account': account, 'created': today, 'method': method, 'previous_cluster': prev,
            'donors': [{'handle': d['handle'], 'weight': d['weight'], 'why': d['why']} for d in r['donors']],
            'bench': [c['handle'] for c in r['candidates'] if c['qualified']
                      and c['handle'] not in {d['handle'] for d in r['donors']}][:6],
            'notes': r['notes']}
        if persona.get('donor_cluster') != name:
            lineage = dict(persona.get('lineage') or {})
            lineage.setdefault('donor_cluster_history', []).append({'cluster': prev, 'until': today,
                                                                     'why': 'Fiona 10/06: per-account beat-fit multi-donor cluster'})
            persona['donor_cluster'] = name
            persona['lineage'] = lineage
            persona_path.write_text(json.dumps(persona, ensure_ascii=False, indent=2) + '\n')
        acc = next(a for a in accounts['accounts'] if a['id'] == account)
        acc['donor_cluster'] = {'cluster': name, 'min_donors': MIN_DONORS, 'decided': 'Fiona 2026-10-06 13:21',
                                'donors': [{'handle': d['handle'], 'weight': d['weight'], 'why': d['why']} for d in r['donors']],
                                'notes': r['notes'],
                                'rule': '语言 donor 只负责表达方式；知识与推理来自事实包与人设问题，不来自这些作者'}
        if acc.get('language_donor'):
            hist = acc.setdefault('language_donor_history', [])
            entry = dict(acc['language_donor'], replaced='2026-10-06 by donor_cluster ' + name + ' (kept as a member)')
            if not any(h.get('handle') == entry.get('handle') and 'donor_cluster' in str(h.get('replaced')) for h in hist):
                hist.append(entry)
    roster_path.write_text(json.dumps(roster, ensure_ascii=False, indent=1) + '\n')
    accounts_path.write_text(json.dumps(accounts, ensure_ascii=False, indent=2) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--out', type=Path)
    a = ap.parse_args(argv)
    result = build()
    for account, r in result.items():
        print(f"\n{account} ({r['lang']}) current={r['current_donor']} qualified={r['qualified_count']}")
        for d in r['donors']:
            print(f"  {d['handle']:<18} {d['weight']:.3f}  {d['why']}")
        for n in r['notes']:
            print('  note:', n)
    if a.out:
        a.out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    if a.write:
        write(result)
    return 0


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
