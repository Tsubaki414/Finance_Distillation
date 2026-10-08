"""Cross-language twin rule (Oct 8 eve, Fiona's gap list step 4).

Accounts 27-36 come in zh/en pairs on one lane (meme 27/32, airdrop 28/33, prediction 29/34, stable yield 30/36).
The per-event cap is per language (daily_compose.MAX_ACCOUNTS_PER_EVENT / hotspot.MAX_PER_LANG), so both halves of a
pair could take the same story on the same Beijing day and read as one account posting twice. A twin may not take an
event its twin already took today:
  - any shared event key (source key / source id / headline key / news hook / 母题), as daily_compose builds them, or
  - >= ENTITY_MIN shared distinctive names (cashtag, ALL-CAPS ticker, or Capitalised word of >= 5 letters in the
    headline + packet head) that are not generic words, majors, data publishers, dates, or the lane platforms both
    twins always mention. zh packets carry project names in Latin script, so two shared names are one story.
    Measured on the Oct 9 select-only plan: twin rule off, 5 of 15 twin picks were the very same source as the twin's.
FD_TWIN_RULE=0 turns the rule off. Keyword-only, no model call.
"""
from __future__ import annotations

import os
import re

PAIRS = (('crypto_meme_zh', 'crypto_meme_en'), ('crypto_airdrop_zh', 'crypto_airdrop_en'),
         ('crypto_prediction_zh', 'crypto_prediction_en'), ('crypto_stable_yield_zh', 'crypto_stable_yield_en'))
TWIN = {a: b for p in PAIRS for a, b in (p, p[::-1])}
HEAD_CHARS = 400
# generic words / majors / the platforms a lane always names: sharing these is not sharing a story
_STOP = set('''
the this that these those and for with from into over after before amid as at by of on in to is are was were be will
new top why how what who when where here there just now today week weekly daily breaking update report thread alpha
says said sees eyes hits nears tops falls rises drops jumps surges slides gains loses data price prices market markets
btc eth sol bnb xrp bitcoin ethereum solana crypto cryptocurrency token tokens coin coins usd usdt usdc dai stablecoin
stablecoins defi nft nfts web3 dex cex tvl apy apr yield yields ai etf etfs sec ceo cto x twitter gm wagmi ngmi kol
airdrop airdrops points meme memes memecoin memecoins onchain on-chain chain l1 l2 layer mainnet testnet season tge
polymarket kalshi pump pumpfun pump.fun gmgn dexscreener binance okx bybit coinbase base hyperliquid aave ethena galxe
layer3 kaito jupiter raydium uniswap curve pendle sky maker lido eigenlayer trump us usa china fed
january february march april may june july august september october november december monday tuesday wednesday
thursday friday saturday sunday yes no
defillama coingecko coinmarketcap coinglass dune artemis nansen arkham lookonchain glassnode cryptoquant cointelegraph
coindesk theblock decrypt blockworks odaily panews blockbeats foresight chaincatcher jinse techflow wublock bloomberg
reuters cnbc wsj
tokenless protocol protocols venue venues pool pools international opinion prediction predictions decision election
presidential derivatives interface collateral lending borrowing bonding dynamic tokenized yield-bearing perps perp
futures options trading traders volume liquidity fees revenue launchpad launchpads stable stables treasury vault vaults
'''.split())
ENTITY_MIN = 2
_TOK = re.compile(r'\$[A-Za-z][A-Za-z0-9]{1,11}|[A-Za-z][A-Za-z0-9.\-]*[A-Za-z0-9]')


def enabled(env=None):
    return str((os.environ if env is None else env).get('FD_TWIN_RULE', '1')).strip().lower() not in ('0', 'false', 'off', 'no')


def twin_of(account_id):
    return TWIN.get(account_id)


def entities(title, text=''):
    """Distinctive names of a packet: cashtags, ALL-CAPS tickers (>= 3) and Capitalised words (>= 5 letters)."""
    out = set()
    for raw in _TOK.findall(' '.join([str(title or ''), str(text or '')[:HEAD_CHARS]])):
        tok = raw.lstrip('$')
        low = tok.lower().strip('.-')
        if len(low) < 3 or low in _STOP or low.isdigit():
            continue
        if raw.startswith('$') or (tok.isupper() and tok.isalpha()) or (tok[0].isupper() and len(low) >= 5):
            out.add(low)
    return out


def clash(account, events, ents, event_takers, ent_takers):
    """Reason string when the account's twin already took one of these events today, else None.

    events: the candidate's event keys; event_takers {event: [(account, angle, lang)]};
    ent_takers {account: set(entities of its picks today)}."""
    twin = twin_of(account)
    if not twin or not enabled():
        return None
    shared = [e for e in events if any(t[0] == twin for t in event_takers.get(e, []))]
    if shared:
        return f'twin {twin} already took this event today ({shared[0][0]})'
    common = set(ents or ()) & set(ent_takers.get(twin) or ())
    if len(common) >= ENTITY_MIN:
        return f'twin {twin} already wrote on {", ".join(sorted(common)[:3])} today'
    return None
