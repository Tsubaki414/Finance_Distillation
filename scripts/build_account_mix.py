#!/usr/bin/env python3
"""Build live/personas/posting_habits/account_mix.json (local only, gitignored like the habit cards) (Oct 11 account audit fixes) from the audit's aggregate outputs.

Inputs (outside git, read-only): the audit dir (cls_out.json = per-post blind LLM type / topic bucket, acct_samples.json =
donor post ids per account) and the audit report (Appendix B weekly kind targets + off-lane quota). Output: per account
aggregate numbers only (bucket shares, kind targets, allow / off-lane bucket lists) - no donor text, no post ids.

  python scripts/build_account_mix.py --audit /workspace/x/audit1011 --report /workspace/x/cc_jobs/account_audit_1011.md
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'live' / 'personas' / 'posting_habits' / 'account_mix.json'   # local only (gitignored)

CRYPTO = {"btc_price_market", "eth_altcoins_price", "stablecoins_tether", "crypto_regulation_policy",
          "crypto_etf_institutions", "defi_protocols_yield", "memecoins_launchpads", "airdrops_points",
          "prediction_markets", "perp_dex_derivatives", "solana_base_ecosystem", "onchain_metrics_holders",
          "exchanges_cex", "security_hacks_scams", "crypto_industry_people_vc", "rwa_tokenization",
          "web3_social_nft_gaming"}
NEUTRAL = {"personal_life", "culture_sports_other"}   # scored as post kind (diary / meme), never as a topic
# the lane's own buckets (from each account's beat line); always allowed whatever the donor sample says
CORE = {
    'crypto_macro_zh': ['btc_price_market', 'macro_fed_rates', 'crypto_etf_institutions'],
    'crypto_onchain_zh': ['onchain_metrics_holders', 'crypto_etf_institutions', 'btc_price_market'],
    'crypto_research_zh': ['defi_protocols_yield', 'rwa_tokenization', 'solana_base_ecosystem',
                           'crypto_industry_people_vc', 'eth_altcoins_price'],
    'crypto_trader_zh': ['btc_price_market', 'eth_altcoins_price', 'trading_psychology_method', 'perp_dex_derivatives'],
    'crypto_diary_zh': ['btc_price_market', 'memecoins_launchpads', 'personal_finance_investing_philosophy',
                        'trading_psychology_method'],
    'crypto_altcoin_zh': ['eth_altcoins_price', 'defi_protocols_yield', 'memecoins_launchpads'],
    'crypto_btc_cycle_zh': ['btc_price_market', 'onchain_metrics_holders'],
    'zh_industry': ['ai_tech', 'us_stocks_earnings'],
    'zh_us_stocks': ['us_stocks_earnings', 'ai_tech'],
    'zh_longterm_investing': ['personal_finance_investing_philosophy', 'us_stocks_earnings'],
    'crypto_macro_en': ['btc_price_market', 'macro_fed_rates', 'crypto_etf_institutions'],
    'crypto_onchain_en': ['onchain_metrics_holders', 'btc_price_market', 'perp_dex_derivatives'],
    'crypto_trader_en': ['btc_price_market', 'eth_altcoins_price', 'trading_psychology_method'],
    'defi_narratives_en': ['defi_protocols_yield', 'eth_altcoins_price'],
    'btc_cycles_en': ['btc_price_market', 'onchain_metrics_holders'],
    'crypto_thesis_en': ['btc_price_market', 'eth_altcoins_price', 'defi_protocols_yield', 'crypto_industry_people_vc'],
    'crypto_research_en': ['rwa_tokenization', 'crypto_etf_institutions', 'stablecoins_tether', 'defi_protocols_yield'],
    'investing_philosophy': ['personal_finance_investing_philosophy', 'us_stocks_earnings'],
    'single_stock_deepdive_en': ['us_stocks_earnings'],
    'market_data_charts': ['us_stocks_earnings', 'macro_fed_rates', 'commodities_gold_fx'],
    'zh_macro': ['macro_fed_rates', 'commodities_gold_fx', 'china_hk_markets'],
    'crypto_ai_crossover_zh': ['ai_tech'],
    'crypto_newbie_zh': ['btc_price_market', 'security_hacks_scams', 'exchanges_cex'],
    'crypto_alt_trader_en': ['eth_altcoins_price', 'solana_base_ecosystem', 'memecoins_launchpads'],
    'longterm_investing_en': ['personal_finance_investing_philosophy'],
    'crypto_etf_flows_en': ['crypto_etf_institutions', 'btc_price_market'],
    'crypto_meme_zh': ['memecoins_launchpads'], 'crypto_meme_en': ['memecoins_launchpads'],
    'crypto_airdrop_zh': ['airdrops_points'], 'crypto_airdrop_en': ['airdrops_points'],
    'crypto_prediction_zh': ['prediction_markets'], 'crypto_prediction_en': ['prediction_markets'],
    'crypto_stable_yield_zh': ['stablecoins_tether', 'defi_protocols_yield'],
    'crypto_stable_yield_en': ['stablecoins_tether', 'defi_protocols_yield'],
    'sol_base_alpha_en': ['solana_base_ecosystem'],
    'crypto_perp_dex_en': ['perp_dex_derivatives'],
}
STOCKS = {"us_stocks_earnings", "china_hk_markets", "ai_tech"}
MACRO = {"macro_fed_rates", "commodities_gold_fx", "geopolitics_politics"}
INV = {"personal_finance_investing_philosophy", "trading_psychology_method"}
ALLOW_MIN = 0.06       # a donor bucket at >= 6% of the account's donor topic posts is on-lane (inside the lane family)
OFFLANE_MIN = 0.025    # >= 2.5%: persona-consistent off-lane aside (quota-limited)
DIARY_SLOT = ('crypto_diary_zh',)
MEME_LANES = ('crypto_meme_zh', 'crypto_meme_en')


def family(aid, kind):
    """The audit's lane family (analyze.py) - donor buckets outside it are off-lane even when frequent."""
    s = set(CRYPTO) | INV
    if aid in ('crypto_macro_zh', 'crypto_macro_en'):
        s |= MACRO
    if aid == 'crypto_ai_crossover_zh':
        s |= {'ai_tech', 'us_stocks_earnings'}
    if aid in ('crypto_prediction_zh', 'crypto_prediction_en'):
        s |= {'geopolitics_politics'}
    if kind == 'stocks':
        s = STOCKS | INV | {'macro_fed_rates'}
    if aid == 'market_data_charts':
        s = STOCKS | MACRO | INV
    if kind == 'investing':
        s = STOCKS | INV | MACRO
    if aid == 'zh_macro':
        s = MACRO | STOCKS | CRYPTO | INV
    return s


def appendix_b(report_text):
    out = {}
    sec = report_text.split('## Appendix B', 1)[-1].split('## Appendix C', 1)[0]
    for line in sec.splitlines():
        m = re.match(r'\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*([\d /]+)\|\s*(\d+)/wk', line)
        if m:
            nums = [int(x) for x in m.group(3).split('/')]
            out[m.group(2)] = {'weekly_14': dict(zip('abcdefgh', nums)), 'offlane_per_week_audit': int(m.group(4))}
    return out


def build(audit, report):
    cls = json.loads((Path(audit) / 'cls_out.json').read_text())
    samples = json.loads((Path(audit) / 'acct_samples.json').read_text())
    targets = appendix_b(Path(report).read_text())
    import sys
    sys.path.insert(0, str(ROOT))
    from live import fd_accounts
    rows = {a['id']: a for a in fd_accounts.rows()}
    out = {'version': 'account-mix-v1', 'source': 'account_audit_1011 (blind LLM classification of donor posts, 30d)',
           'allow_min_share': ALLOW_MIN, 'offlane_min_share': OFFLANE_MIN, 'accounts': {}}
    for aid, ids in samples.items():
        posts = [cls['D' + i] for i in ids if 'D' + i in cls]
        c = collections.Counter(p.get('b') for p in posts if p.get('b') not in NEUTRAL)
        n = max(1, sum(c.values()))
        shares = {b: round(v / n, 3) for b, v in c.most_common()}
        fam = family(aid, (rows.get(aid) or {}).get('kind'))
        allow = list(dict.fromkeys(CORE.get(aid, []) + [b for b, s in shares.items() if s >= ALLOW_MIN and b in fam]))
        offlane = [b for b, s in shares.items() if s >= OFFLANE_MIN and b not in allow]
        t = targets.get(aid) or {'weekly_14': dict(zip('abcdefgh', (3, 1, 5, 1, 2, 1, 1, 0))), 'offlane_per_week_audit': 1}
        out['accounts'][aid] = {
            'lang': (rows.get(aid) or {}).get('lang'), 'core': CORE.get(aid, []), 'allow': allow, 'offlane_ok': offlane,
            'donor_bucket_share': shares, 'weekly_14': t['weekly_14'],
            'offlane_per_week': max(1, min(3, t['offlane_per_week_audit'])),
            'diary_slot': aid in DIARY_SLOT, 'meme_lane': aid in MEME_LANES,
            # PENDING Fiona's approval: fixed, harmless persona life facts (city / routine / hobby) for diary posts.
            # Empty = diary / personal posts carry no biographical facts at all. Used only with FD_PERSONA_LIFE=1.
            'persona_life_details': [],
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audit', default='/workspace/x/audit1011')
    ap.add_argument('--report', default='/workspace/x/cc_jobs/account_audit_1011.md')
    ap.add_argument('--out', type=Path, default=OUT)
    a = ap.parse_args()
    data = build(a.audit, a.report)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    print(a.out, len(data['accounts']), 'accounts')


if __name__ == '__main__':
    main()
