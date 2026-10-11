"""Story + topic labels for packets and drafts (Oct 11 account audit fixes 1/2).

One cheap LLM pass (subrouter, OpenAI-compatible, FD_STORY_MODEL default gemini-3-flash; never the paid relay) labels
each text with
  b: one of the audit's 27 topic buckets (lane gate, live/lane_allow.py)
  e: the main entity (one canonical name), a: an action from a fixed list, o: optional second entity / asset,
  k: a 3-7 word English story label.
Story key = entity|action[|object] (+ label tokens for fuzzy matching, live/story_dedupe.py). Labels are cached by text
hash in live/store/story_labels/labels.jsonl (FD_STORY_STORE), so history rows, fill rounds and the next nights reuse
them. Without a key / with FD_STORY_LLM=0 / in --select-only, only cached labels and the keyword bucket fallback are
used. Never fatal.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUCKETS = ("btc_price_market", "eth_altcoins_price", "stablecoins_tether", "crypto_regulation_policy",
           "crypto_etf_institutions", "defi_protocols_yield", "memecoins_launchpads", "airdrops_points",
           "prediction_markets", "perp_dex_derivatives", "solana_base_ecosystem", "onchain_metrics_holders",
           "exchanges_cex", "security_hacks_scams", "crypto_industry_people_vc", "rwa_tokenization", "ai_tech",
           "us_stocks_earnings", "macro_fed_rates", "geopolitics_politics", "personal_finance_investing_philosophy",
           "trading_psychology_method", "personal_life", "culture_sports_other", "web3_social_nft_gaming",
           "china_hk_markets", "commodities_gold_fx")
ACTIONS = ('buys', 'sells', 'launches', 'lists', 'delists', 'freezes', 'hacked', 'sues', 'approves', 'files',
           'rejects', 'partners', 'integrates', 'acquires', 'raises', 'invests', 'pays', 'price_move', 'flows',
           'data', 'policy', 'statement', 'earnings', 'outage', 'other')
BATCH = 15   # 40 came back truncated (flash reasoning eats the token budget) on 10-11 13:30
_LOCK = threading.Lock()

PROMPT = """Label each post / news packet (finance, crypto, stocks). For each item return:
- b: one topic bucket from: {buckets}
- e: the MAIN entity the story is about, one canonical short name (company, protocol, coin, person, agency; e.g. "Tether", "Robinhood", "Polygon", "Fed", "Bitcoin"). Use the English name.
- a: what happened, one of: {actions}
- o: a second entity or asset if the story is a pairing (e.g. for "USDT launches on Polygon via TRON bridge" e=Tether a=integrates o=Polygon), else ""
- k: the underlying story in 3-7 English words, entity + event (e.g. "Tether freezes USDT wallets", "Robinhood buys BTC for treasury"). The same real-world event must get the same e/a/o and nearly the same k whatever the language or angle of the post.
Return ONLY one line per item, fields separated by " | ", no header, no JSON, no extra text:
<id> | <b> | <e> | <a> | <o or -> | <k>

ITEMS:
{items}"""


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_STORY_LLM', '1') != '0'


def store_path():
    return Path(os.environ.get('FD_STORY_STORE') or ROOT / 'live' / 'store' / 'story_labels') / 'labels.jsonl'


def norm_text(text):
    return re.sub(r'https?://\S+', '', re.sub(r'\s+', ' ', str(text or ''))).strip()[:600]


def text_key(text):
    return hashlib.sha1(norm_text(text).encode('utf-8')).hexdigest()[:20]


_CACHE = {}
_LOADED = {}


def _load(path=None):
    path = Path(path or store_path())
    if _LOADED.get(str(path)):
        return _CACHE.setdefault(str(path), {})
    cache = _CACHE.setdefault(str(path), {})
    try:
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
                cache[r['h']] = r['l']
            except (ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    _LOADED[str(path)] = True
    return cache


def _save(new, path=None):
    path = Path(path or store_path())
    if not new:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.open('a') as f:
        for h, lab in new.items():
            f.write(json.dumps({'h': h, 'l': lab}, ensure_ascii=False) + '\n')


def clean_label(lab):
    if not isinstance(lab, dict):
        return None
    b = str(lab.get('b') or '').strip()
    a = str(lab.get('a') or '').strip().lower()
    return {'b': b if b in BUCKETS else None, 'e': str(lab.get('e') or '').strip()[:40],
            'a': a if a in ACTIONS else 'other', 'o': str(lab.get('o') or '').strip()[:40],
            'k': str(lab.get('k') or '').strip()[:80]}


def parse_lines(t):
    out = {}
    for line in str(t or '').splitlines():
        parts = [x.strip() for x in line.strip().strip('`').split('|')]
        if len(parts) < 6 or not parts[0]:
            continue
        h = parts[0].strip('[]')
        o = parts[4] if parts[4] not in ('-', '""', "''", 'none', 'None') else ''
        out[h] = {'b': parts[1], 'e': parts[2], 'a': parts[3], 'o': o, 'k': ' | '.join(parts[5:])}
    return out


def get(text, path=None):
    return _load(path).get(text_key(text))


def _call(items, model, timeout=60):
    import requests
    key = os.environ.get('SUBROUTER_API_KEY')
    base = (os.environ.get('SUBROUTER_BASE_URL') or 'https://subrouter.ai/v1').rstrip('/')
    if not key:
        raise RuntimeError('SUBROUTER_API_KEY not set')
    ids = {str(n + 1): h for n, (h, _t) in enumerate(items)}   # short ids: the model mangles 20-hex ones
    body = '\n\n'.join(f'[{n + 1}]\n{t}' for n, (_h, t) in enumerate(items))
    msg = PROMPT.format(buckets=', '.join(BUCKETS), actions=', '.join(ACTIONS), items=body)
    last = None
    for _ in range(1):   # the halves retry in label_many covers a bad batch
        try:
            r = requests.post(base + '/chat/completions', headers={'Authorization': 'Bearer ' + key},
                              json={'model': model, 'messages': [{'role': 'user', 'content': msg}],
                                    'max_tokens': 12000, 'temperature': 0,
                                    'reasoning_effort': 'low'}, timeout=timeout)   # default: ~11.5k reasoning tokens, truncated
            t = r.json()['choices'][0]['message']['content'] or ''
            out = {ids[k]: v for k, v in parse_lines(t).items() if k in ids}
            if not out:
                raise ValueError(f'no label lines in {t[:80]!r}')
            return out
        except Exception as exc:   # noqa: BLE001
            last = exc
    raise RuntimeError(f'story label call failed: {type(last).__name__}: {str(last)[:160]}')


def label_many(texts, *, allow_model=True, path=None, workers=6, model=None, caller=None):
    """{text_key: label} for every text (cached or freshly labelled). caller(items) -> raw dict (tests)."""
    cache = _load(path)
    keys = {}
    for t in texts:
        if norm_text(t):
            keys.setdefault(text_key(t), norm_text(t))
    todo = [(h, t) for h, t in keys.items() if h not in cache]
    stats = {'texts': len(keys), 'cached': len(keys) - len(todo), 'labelled': 0, 'errors': 0}
    if todo and allow_model and (enabled() or caller is not None):
        model = model or os.environ.get('FD_STORY_MODEL', 'gemini-3-flash')
        batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
        call = caller or (lambda items: _call(items, model))

        def job(b):
            try:
                return b, call(b), None
            except Exception as exc:   # noqa: BLE001 - one retry as two halves (a truncated / bad JSON batch)
                if len(b) < 4 or caller is not None:
                    return b, {}, exc
                out, err = {}, exc
                for half in (b[:len(b) // 2], b[len(b) // 2:]):
                    try:
                        out.update(call(half))
                    except Exception as exc2:   # noqa: BLE001
                        err = exc2
                return b, out, (err if not out else None)
        new = {}
        with cf.ThreadPoolExecutor(max(1, workers)) as ex:
            for b, res, err in ex.map(job, batches):
                if err is not None:
                    stats['errors'] += 1
                for h, _t in b:
                    lab = clean_label((res or {}).get(h) or (res or {}).get(f'[{h}]'))
                    if lab and (lab['e'] or lab['k']):
                        new[h] = lab
        cache.update(new)
        _save(new, path)
        stats['labelled'] = len(new)
    return {h: cache[h] for h in keys if h in cache}, stats


# ---------------------------------------------------------------- deterministic fallback (no label)
_KW = [
    ('prediction_markets', r'polymarket|kalshi|prediction market|预测市场|盘口|赔率|\bodds\b'),
    ('airdrops_points', r'airdrop|\bpoints?\b farming|空投|撸毛|积分|\btge\b|白单'),
    ('memecoins_launchpads', r'memecoin|meme coin|pump\.?fun|launchpad|冲狗|土狗|\bmeme\b|bonk|\bwif\b'),
    ('perp_dex_derivatives', r'hyperliquid|perp(?:etual)?s?\b|open interest|\boi\b|funding rate|期权|合约|爆仓|liquidat'),
    ('stablecoins_tether', r'stablecoin|\busdt\b|\busdc\b|tether|circle|稳定币|泰达'),
    ('crypto_etf_institutions', r'\betfs?\b|blackrock|ibit|fidelity|grayscale|institution|机构|现货 ?etf'),
    ('security_hacks_scams', r'hack|exploit|drain|scam|phish|黑客|被盗|攻击|骗局'),
    ('ai_tech', r'\bai\b|nvidia|openai|anthropic|\bgpu|chip|semiconductor|英伟达|芯片|人工智能|大模型|算力'),
    ('macro_fed_rates', r'\bfed\b|fomc|rate (?:cut|hike)|treasur|yields?\b|inflation|\bcpi\b|美联储|降息|加息|美债|通胀'),
    ('us_stocks_earnings', r'earnings|s&p|nasdaq|\bstocks?\b|shares|财报|美股|纳指|标普'),
    ('solana_base_ecosystem', r'solana|\bsol\b|\bbase\b chain|coinbase.s base|aerodrome|jupiter'),
    ('defi_protocols_yield', r'defi|\btvl\b|\bapy\b|yield|lending|aave|pendle|ethena|收益|借贷'),
    ('crypto_regulation_policy', r'\bsec\b|regulat|congress|clarity act|genius act|lawsuit|监管|法案|合规'),
    ('btc_price_market', r'bitcoin|\bbtc\b|比特币|大饼'),
    ('eth_altcoins_price', r'ethereum|\beth\b|altcoin|以太坊|山寨'),
]
_KW = [(b, re.compile(rx, re.I)) for b, rx in _KW]


def keyword_bucket(text):
    """Best-effort bucket from keywords (None when nothing matches): first lane-specific match wins."""
    t = str(text or '')
    for b, rx in _KW:
        if rx.search(t):
            return b
    return None
