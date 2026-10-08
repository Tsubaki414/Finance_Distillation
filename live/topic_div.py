"""Topic diversity for daily selection (FD_TOPIC_DIV, default 1; =0 restores the previous selection exactly).

Fiona, Oct 8: the 10-08 batch drew 40 picks from a handful of shared news items (4x Polygon/TRON, 4x Glassnode "A
Rally Running Light", 4x Wells Fargo/Kraken) while each account's donors post on many different stories every day.
An account's day should mirror what its own donors talk about, from its own sources first.

- `theme_of` / `themes_of`: a fine theme taxonomy (crypto split into lanes such as stablecoin / L2 / perp / meme /
  regulation / institutional; the non-crypto topics of live/posting_habits.TOPICS) by keyword hits.
- `donor_profile`: per account, the last 7 days of its donor cluster's original posts (live/donors/posts) ->
  theme mix (smoothed), post count, distinct themes, distinct stories, and the entities they named in the last 72 h.
  Aggregates only; cached in live/store/topic_div/<day>.json (local, gitignored), no donor text is kept.
- `source_tier`: 0 own X source, 1 donor-adjacent (names something the account's donors named in the last 72 h, or a
  theme the donors spent >= 15% on) and not a widely shared item, 2 other, 3 shared news (in >= SHARED_POOLS pools).
- `pick_key`: the dynamic order used at pick time (see scripts/daily_compose.select).
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / 'live' / 'donors' / 'posts'
ROSTER = ROOT / 'live' / 'donors' / 'roster.json'
VERSION = 'topic-div-v1'
DONOR_DAYS = 7
ADJ_HOURS = 72
SHARED_POOLS = 4          # a source in this many accounts' pools is shared news (tier 3)
ADJ_THEME_SHARE = 0.15    # a theme the donors spent this share on makes a candidate donor-adjacent
OFF_SPREAD = 0.03         # a theme below this share of the donor mix is off the account's spread (soft)
MAX_TOTAL_PER_EVENT = 3   # same story: at most 2 accounts per language (daily_compose) and 3 in all


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_TOPIC_DIV', '1') != '0'


# ------------------------------------------------------------------ themes

_C = re.IGNORECASE
CRYPTO_THEMES = (
    ('c_stablecoin', r'稳定币|USDT|USDC|tether|泰达|stablecoin|circle|\bRWA\b|代币化|tokeni[sz]|支付|payments?\b'),
    ('c_regulation', r'\bSEC\b|CFTC|监管|法案|clarity act|genius act|regulat|立法|合规|牌照|licen[cs]e|ANPRM|congress|国会'),
    ('c_institutional', r'\bETFs?\b|贝莱德|blackrock|fidelity|富达|microstrategy|\bstrategy\b|saylor|treasury compan|'
                        r'机构|robinhood|罗宾汉|wells fargo|富国|银行|\bbanks?\b|grayscale|灰度|华尔街|wall street|IPO|上市'),
    ('c_security', r'黑客|被盗|hack|exploit|漏洞|冻结|froze|freez|scam|骗局|\brug\b|跑路|钓鱼|phish'),
    ('c_perp', r'合约|永续|\bperps?\b|funding rate|资金费率|爆仓|liquidat|杠杆|leverage|open interest|持仓量|hyperliquid|'
               r'期权|options?\b|call skew|做空|做多|空单|多单|\bshorts?\b|\blongs?\b'),
    ('c_meme', r'\bmemes?\b|土狗|金狗|pump\.?fun|狗币|doge|pepe|bonk|wif\b|meme ?coin|冲狗'),
    ('c_airdrop', r'空投|airdrop|积分|\bpoints\b|撸毛|交互|\bTGE\b|测试网|testnet|kaito|\byap|签到'),
    ('c_defi', r'\bdefi\b|借贷|lending|borrow|\bDEX\b|\bAMM\b|yield|收益率?池|流动性池|\bLP\b|aave|uniswap|pendle|morpho|'
               r'ethena|restak|质押|staking|vault|金库|scallop'),
    ('c_eth_l2', r'以太坊|\bETH\b|ethereum|\bL2s?\b|layer ?2|rollup|二层|arbitrum|optimism|\bbase\b链?|fusaka|glamsterdam|'
                 r'vitalik|V神|polygon|abstract|blast|zksync|starknet'),
    ('c_alt_l1', r'solana|\bSOL\b|\bsui\b|aptos|\bTON\b|\btron\b|波场|avax|avalanche|\bBNB\b|公链|\bL1s?\b|monad|berachain|'
                 r'cardano|\bADA\b|\bXRP\b|ripple|zcash|\bZEC\b'),
    ('c_cex', r'币安|binance|\bOKX\b|欧易|coinbase|kraken|bybit|bitget|上币|listing|交易所|exchange'),
    ('c_ai_crypto', r'ai ?agents?|virtuals|ai16z|x402|agent ?token|代理'),
    ('c_project', r'融资|raises?\b|funding round|估值|收购|合并|merger|acqui|关闭|shut ?down|主网|mainnet|tokenomics|'
                  r'代币经济|解锁|unlock|回购|buyback|launch'),
    ('c_onchain', r'链上|on-?chain|巨鲸|whales?|glassnode|地址|holders?|筹码|\bLTH\b|\bSTH\b|MVRV|inflows?|outflows?|'
                  r'cohort|realized'),
    ('c_cycle_mood', r'牛市|熊市|周期|cycle|山寨季|altseason|情绪|sentiment|恐慌|贪婪|fomo|行情|大饼|比特币|bitcoin|\bBTC\b|rally|回调'),
    # Oct 8 (36 accounts): prediction-market lane (appended: earlier themes keep winning ties)
    ('c_prediction', r'polymarket|kalshi|预测市场|prediction markets?|盘口|赔率|\bodds\b'),
)
CRYPTO_MARK = re.compile(r'比特币|\bBTC\b|\bETH\b|以太坊|币圈|链上|稳定币|山寨|bitcoin|crypto|ethereum|stablecoin|altcoin|'
                         r'on-?chain|token|代币|加密|defi|空投|airdrop|memecoin|solana|\$[A-Z]{2,6}\b|web3|polymarket|预测市场', _C)
MARKET_THEMES = (
    ('rates_fed', r'美联储|联储|降息|加息|利率|点阵图|FOMC|鲍威尔|\bfed\b|rate cuts?|rate hikes?|powell|treasur|yields?|'
                  r'bonds?|美债|国债|收益率'),
    ('macro_data', r'通胀|CPI|PCE|非农|就业|失业|GDP|PMI|零售|衰退|inflation|payrolls?|\bjobs\b|unemployment|recession|'
                   r'retail sales|economy|经济'),
    ('fx', r'美元指数|日元|人民币|欧元|汇率|DXY|\byen\b|yuan|\beuro\b|\bfx\b|currenc'),
    ('commodities', r'原油|石油|油价|黄金|白银|铜|天然气|\boil\b|crude|\bgold\b|silver|copper|opec|natgas|commodit|fuel'),
    ('ai_semis', r'英伟达|芯片|半导体|算力|\bAI\b|人工智能|台积电|光模块|HBM|数据中心|nvidia|nvda|semis?\b|semiconductor|'
                 r'chips?\b|tsmc|gpu|data ?center|hyperscaler|capex|photonic|openai|anthropic|claude|llm|大模型'),
    ('earnings_stocks', r'财报|营收|利润|EPS|指引|估值|个股|earnings|revenue|guidance|margins?|valuation|\$[A-Z]{2,5}\b'),
    ('index_breadth', r'标普|纳指|道指|大盘|美股|A股|港股|恒指|恒生|S&P|SPX|SPY|Nasdaq|QQQ|Dow\b|Russell|breadth|new highs|'
                      r'all-time high|\bindex'),
    ('positioning_tech', r'期权|波动率|VIX|支撑|阻力|均线|options?\b|gamma|volatility|support|resistance|moving average|'
                         r'positioning|hedg|put\b|call skew|oversold|overbought|technical'),
    ('policy_politics', r'关税|特朗普|川普|选举|政府|财政|赤字|债务|制裁|tariffs?|trump|election|congress|deficit|debt|sanction|'
                        r'white house|shutdown|musk|马斯克|geopolit|地缘|战争|\bwar\b'),
    ('china', r'中国|国内|央行|人民银行|房地产|china|chinese|pboc|beijing|北京'),
    ('biotech_health', r'医药|制药|生物|biotech|pharma|drug|临床|trial|FDA|健康|health'),
    ('investing_principles', r'长期|复利|纪律|心态|风险管理|分散|耐心|投资者|交易系统|止损|复盘|long[- ]term|compounding|'
                             r'discipline|behavio|diversif|patience|investors? should|lesson|mistake|risk management'),
)
_CRYPTO_RX = [(k, re.compile(v, _C)) for k, v in CRYPTO_THEMES]
_MARKET_RX = [(k, re.compile(v, _C)) for k, v in MARKET_THEMES]
THEMES = tuple(k for k, _ in CRYPTO_THEMES) + tuple(k for k, _ in MARKET_THEMES) + ('other',)


def themes_of(text):
    """Themes ranked by the number of distinct keyword hits (taxonomy order breaks ties). A crypto text is typed by
    the crypto lanes first; market themes only when no crypto lane is hit."""
    text = str(text or '')
    out = []
    # crypto lanes only for a text with a crypto mark (a bank / treasury story is not c_institutional)
    for rx_list in ((_CRYPTO_RX, _MARKET_RX) if CRYPTO_MARK.search(text) else (_MARKET_RX,)):
        scored = []
        for i, (k, rx) in enumerate(rx_list):
            n = len({m.group(0).lower() for m in rx.finditer(text)})
            if n:
                scored.append((-n, i, k))
        out += [k for _, _, k in sorted(scored)]
        if out:
            break
    return out or ['other']


def theme_of(text):
    return themes_of(text)[0]


# ------------------------------------------------------------------ donors

def _created(post):
    raw = post.get('created') or post.get('created_at') or ''
    for fmt in ('%a %b %d %H:%M:%S %z %Y',):
        try:
            return datetime.strptime(str(raw), fmt)
        except ValueError:
            pass
    try:
        t = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def donor_handles(account_id, roster=None):
    roster = roster if roster is not None else json.loads(ROSTER.read_text())
    cluster = (roster.get('persona_clusters') or {}).get(f'acct_{account_id}') or {}
    return [d['handle'] for d in cluster.get('donors') or []]


_PROMO = re.compile(r'返佣|邀请码|注册链接|抽奖|giveaway|use code|promo code|link in bio', _C)


def donor_posts(handles, ref, days=DONOR_DAYS, posts_dir=None):
    """Original donor posts (no reposts / replies / promo) published in (ref - days, ref]."""
    posts_dir = Path(posts_dir or POSTS)
    lo = ref - timedelta(days=days)
    out = []
    for h in handles:
        path = posts_dir / f'{h.lower()}.jsonl'
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            try:
                p = json.loads(line)
            except ValueError:
                continue
            if p.get('rt') or p.get('reply') or not str(p.get('text') or '').strip():
                continue
            t = _created(p)
            if t is None or not (lo < t <= ref) or _PROMO.search(p['text']):
                continue
            out.append({'handle': h, 't': t, 'text': p['text']})
    return out


def _stories(posts):
    """Distinct stories among posts: the 母题 clustering of live/hotspot on the post text."""
    from live import hotspot
    mats = []
    for i, p in enumerate(posts):
        head = p['text'][:400]
        title = head.split('\n')[0][:160]
        mats.append({'key': [i], 'title': title, 'url': '', '_ents': hotspot.entities(head), '_nums': hotspot.numbers(head),
                     '_bi': hotspot.cjk_bigrams(title), '_hooks': set(), '_event': hotspot._title_event(title)})
    return len(hotspot.cluster(mats)) if mats else 0


def donor_profile(account_id, ref, roster=None, posts_dir=None, days=DONOR_DAYS):
    """Aggregates of the account's donors' last `days` days (no text): n, theme counts / mix (add-one smoothed over
    themes seen), distinct themes and stories, per-day posts, entities named in the last ADJ_HOURS."""
    from live import hotspot
    handles = donor_handles(account_id, roster)
    posts = donor_posts(handles, ref, days, posts_dir)
    counts = Counter(theme_of(p['text']) for p in posts)
    seen = [t for t in THEMES if counts.get(t)]
    total = sum(counts.values()) + 0.5 * len(seen)
    mix = {t: round((counts[t] + 0.5) / total, 4) for t in seen} if posts else {}
    recent = [p for p in posts if ref - p['t'] <= timedelta(hours=ADJ_HOURS)]
    ents = Counter(e for p in recent for e in hotspot.entities(p['text'][:600]))
    days_active = len({p['t'].date() for p in posts}) or 1
    return {'account': account_id, 'donors': len(handles), 'posts': len(posts), 'posts_per_day': round(len(posts) / days, 1),
            'themes': dict(counts.most_common()), 'mix': mix, 'distinct_themes': len(seen),
            'stories': _stories(posts), 'stories_per_day': round(_stories(posts) / days_active, 1) if posts else 0,
            'entities_72h': dict(ents.most_common(80))}


def store_dir():
    return Path(os.environ.get('FD_TOPIC_DIV_STORE') or ROOT / 'live' / 'store' / 'topic_div')


def profiles(account_ids, ref, day, roster=None, posts_dir=None, cache=True):
    """{account: donor_profile}; cached per drafting day (aggregates only)."""
    path = store_dir() / f'{day}.json'
    if cache:
        try:
            got = json.loads(path.read_text())
            if got.get('version') == VERSION and set(account_ids) <= set(got['profiles']):
                return got['profiles']
        except (OSError, ValueError, KeyError):
            pass
    roster = roster if roster is not None else json.loads(ROSTER.read_text())
    out = {a: donor_profile(a, ref, roster, posts_dir) for a in account_ids}
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'version': VERSION, 'day': day, 'ref': ref.isoformat(), 'profiles': out},
                                   ensure_ascii=False, indent=1) + '\n')
    return out


def common_entities(profs, frac=0.5):
    """Entities named by the donors of >= frac of the accounts (btc, ai ...): too common to mark adjacency."""
    df = Counter(e for p in profs.values() for e in p.get('entities_72h') or {})
    n = max(1, len(profs))
    return {e for e, c in df.items() if c >= frac * n}


# ------------------------------------------------------------------ tiers and pick order

def adjacency(text, prof, common=frozenset()):
    """(shared entities, theme share): how close a candidate is to what the donors posted lately."""
    from live import hotspot
    ents = hotspot.entities(str(text or '')[:1500]) - set(common)
    shared = sorted(ents & set((prof or {}).get('entities_72h') or {}))
    share = max([((prof or {}).get('mix') or {}).get(t, 0.0) for t in themes_of(text)[:2]] or [0.0])
    return shared, share


def source_tier(own_x, shared_count, adj):
    shared, share = adj
    if own_x:
        return 0
    if shared_count >= SHARED_POOLS:
        return 3
    if shared or share >= ADJ_THEME_SHARE:
        return 1
    return 2


def off_spread(theme, prof):
    mix = (prof or {}).get('mix') or {}
    return bool(mix) and mix.get(theme, 0.0) < OFF_SPREAD


def entropy(counts):
    n = sum(counts.values())
    return round(-sum(c / n * math.log2(c / n) for c in counts.values() if c), 3) if n else 0.0
