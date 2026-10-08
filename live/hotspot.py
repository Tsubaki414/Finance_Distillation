"""Hotspot pool + 母题 (master-theme) clustering for the fd20 daily run (Oct 8, Sirius borrow).

Flow (behind FD_HOTSPOT, default 1; FD_HOTSPOT=0 = the selection is exactly the pre-hotspot order):

  materials   every source of the last WINDOW_H hours in the content store (all accounts' sources: flashes, feeds, X
              intake), grouped by source; tier A/B only; X promo openers dropped
  母题        cheap deterministic links first - same URL, same headline event (title lead word + numbers), shared
              news hook, shared significant number + shared entity, >= 2 shared rare entities, CJK headline overlap -
              union-find; then at most ONE flash call a day (relay, cost cap $0.30, cached per day) that may merge
              clusters on the same story across languages and writes a neutral zh / en title
  heat        breadth (distinct publishers, sources, accounts whose own pool holds a member) + public heat inputs
              (live/heat.py cache: Google Trends / 东方财富 / B站 / Reddit) + recency; pool = 'hotspot' when >= 2
              publishers (or 1 publisher with public heat), else 'discovery' (recorded, never written)
  decision    per account, for each top hotspot 母题: IGNORE when no member is in the account's own candidate pool
              (its retrieval beats, beat gate, own X handles, account-scoped sources) or the 母题 topic is outside the
              account's own topic spread (universe topic_mix from its donors); HOLD when on-beat but capped (2
              accounts per language per 母题, 1 hotspot per account per day, already led today) or no member is
              timely / passes prescreen; else WRITE. Heat only orders 母题 - it never moves an account off its beat.
  reality     for a WRITE pick: the latest price of the 母题's main ticker (live/charts.py fetchers, free) and the 2-3
              newest member sources (<= 24h, URLs; X posts only from the account's own handles) - attached to the
              compose payload so the draft does not state a stale fact; the lines join the grounding text.
              Optional X pulse (FD_HOTSPOT_X=1, twitter241, <= 40 calls/day): a 24h post count only, no text.

Stored: live/store/hotspot/<day>.json (pool, decisions) and <day>.merge.json (the flash merge, reused all day).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOW_H = 36
RECENT_H = 24
TOP_N = 12
FIT_MIN = 0.05            # topic share in the account's own donor topic mix below which a 母题 is off its spread
MAX_PER_LANG = max(1, int(os.environ.get('FD_EVENT_PER_LANG', '1')))   # = daily_compose.MAX_ACCOUNTS_PER_EVENT (Oct 8 eve: 2 -> 1)
PER_ACCOUNT = 1           # hotspot posts per account per day
MERGE_CAP_USD = 0.30
HUB_DEGREE = 6            # a material linked to this many others is a recap: it may join, not bridge
MERGE_MAX = 80            # clusters sent to the merge call
X_CAP = 40                # twitter241 calls per day for the X pulse
LANE_FIT_OVERRIDE = 0.2   # a 母题 outside a lane account's lanes still counts when its type has this topic share
X_ONLY_MIN_PUBLISHERS = 3  # distinct authors an X-only 母题 needs to enter the hotspot pool
VERSION = 'hotspot-v2'

STOP = set('''the a an and or of to in on for with from by at as is are was were be been it its this that these those
we our you your they their he she his her i my me us not no yes but if so do does did can will would should could
may might just now new today yesterday tomorrow here there what why how when who which all any some more most less
over after before into than then also about up down out off again still very per vs via amid says said report
reports breaking update live part week month year day daily weekly market markets price prices stock stocks crypto
news data chart thread rt gm one two three first last next top big high low jan feb mar apr may jun jul aug sep oct
nov dec monday tuesday wednesday thursday friday saturday sunday q1 q2 q3 q4 ceo cfo usd us u.s ai etf january february
march april june july august september october november december according financial private standard token tokens
global world million billion trillion bank banks fund funds ipo''' .split())
# morning digests / recaps list many stories: they may join a 母题 but never bridge two
DIGEST = re.compile(r'早餐|早报|晚报|要闻|导读|汇总|一览|速览|信息差|周报|周刊|recap|roundup|morning|briefing|outlook|weekly|'
                    r'what to watch|need to know', re.I)
# frequent zh -> en names, so a zh flash and an en headline on the same actor meet (subjects_in covers tickers)
ZH_ALIAS = {'罗宾汉': 'robinhood', '泰达': 'tether', '贝莱德': 'blackrock', '富达': 'fidelity', '微策略': 'strategy',
            '美联储': 'fed', '鲍威尔': 'powell', '特朗普': 'trump', '贝森特': 'bessent', '币安': 'binance',
            '灰度': 'grayscale', '摩根大通': 'jpmorgan', '高盛': 'goldman', '黄金': 'gold', '原油': 'oil',
            '美债': 'treasury', '非农': 'payrolls', '萨尔瓦多': 'salvador', '以太坊': 'ethereum', '稳定币': 'stablecoin',
            '亚马逊': 'amazon', '苹果': 'apple', '甲骨文': 'oracle', '博通': 'broadcom', '台积电': 'tsmc'}
_MULT = {'万亿': 1e12, '亿': 1e8, '万': 1e4, '千': 1e3, 'trillion': 1e12, 'billion': 1e9, 'bn': 1e9, 'b': 1e9,
         'million': 1e6, 'mn': 1e6, 'm': 1e6, 'thousand': 1e3, 'k': 1e3}
_NUM = re.compile(r'([$＄])?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*'
                  r'(万亿|亿|万|千|trillion|billion|million|thousand|bn|mn|[kKmMbB](?![a-zA-Z]))?\s*(%|％|美元|美金|usd|USD)?')


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_HOTSPOT', '1') != '0'


def store_dir():
    return Path(os.environ.get('FD_HOTSPOT_STORE') or ROOT / 'live' / 'store' / 'hotspot')


# ------------------------------------------------------------------ features

def _ts(value):
    try:
        t = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def clean_title(title):
    return re.sub(r'\s*\(part \d+/\d+\)\s*$', '', str(title or '')).strip()


def numbers(text):
    """Significant numbers as normalised strings: currency amounts, values >= 1000 (not years), decimal percents."""
    out = set()
    for m in _NUM.finditer(str(text or '')):
        cur, raw, mult, suffix = m.group(1), m.group(2), (m.group(3) or ''), (m.group(4) or '')
        try:
            v = float(raw.replace(',', ''))
        except ValueError:
            continue
        mult_v = _MULT.get(mult if mult in _MULT else mult.lower(), 1.0)
        money = bool(cur) or suffix.lower() in ('美元', '美金', 'usd')
        pct = suffix in ('%', '％')
        if pct:
            if '.' in raw and v > 0:
                out.add(f'{v:g}%')
            continue
        if not mult and not money and 1900 <= v <= 2100 and '.' not in raw and ',' not in raw:
            continue   # a year
        value = v * mult_v
        if money and value >= 100 or value >= 1000:
            out.add(f'{value:.3g}')
    return out


def entities(text):
    """Lower-case names: known tickers / coins (live/charts.subjects_in), $CASHTAGS, capitalised Latin words outside
    the stop list, and frequent zh names folded to their English form."""
    from live.charts import subjects_in
    text = str(text or '')
    out = {s.lower() for s in subjects_in(text)}
    out |= {m.lower() for m in re.findall(r'\$([A-Za-z]{2,10})\b', text)}
    for w in re.findall(r'(?<![\w@#$])([A-Z][A-Za-z0-9&.\-]{2,})', text):
        w = w.strip('.-')
        if w and w.lower() not in STOP and not w.isdigit() and not subjects_in(w):   # Solana -> SOL already counted
            out.add(w.lower())
    out |= {en for zh, en in ZH_ALIAS.items() if zh in text}
    return out


def cjk_bigrams(text):
    s = ''.join(re.findall(r'[一-鿿]', str(text or '')))
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def material(key, group, text):
    src = group[0]['source']
    title = clean_title(src.get('title'))
    head = f'{title}\n{text[:600]}'
    return {'key': list(key), 'title': title, 'publisher': src.get('publisher') or src.get('author_name') or '',
            'url': src.get('url') or '', 'published_at': src.get('published_at'), 'adapter': src.get('adapter') or '',
            'source_id': src.get('source_id') or src.get('id'), 'lang': 'zh' if re.search(r'[一-鿿]', title) else 'en',
            'tier': group[0].get('licence_tier'), 'unit_ids': [r['unit_id'] for r in group],
            'n_numbers': sum(len((r.get('unit') or {}).get('numbers') or []) for r in group),
            'tags': sorted({t for r in group for t in r.get('tag_personas') or []}),
            '_t': _ts(src.get('published_at')), '_text': head, '_ents': entities(head), '_nums': numbers(head),
            '_bi': cjk_bigrams(title), '_hooks': set(), '_event': None, 'accounts': []}


def gather(store, ref, window_h=WINDOW_H, promo=None):
    """{source key: material} for every A/B source published in (ref - window_h, ref]."""
    groups = {}
    lo = ref - timedelta(hours=window_h)
    for row in store.units():
        src = row.get('source') or {}
        t = _ts(src.get('published_at'))
        if t is None or not (lo < t <= ref) or row.get('licence_tier') not in ('A', 'B'):
            continue
        if promo is not None and str(src.get('adapter') or '').startswith('x:') and promo.search(str(src.get('title') or '')):
            continue
        groups.setdefault((src.get('source_hash'), src.get('id')), []).append(row)
    return groups


# ------------------------------------------------------------------ clustering

class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def _sig(n):
    """Significant digits of a normalised number ('8.4e+04' -> 2, '4e+10' -> 1, '0.31%' -> 2)."""
    mant = n.rstrip('%').split('e')[0].replace('.', '').lstrip('0')
    return len(mant.rstrip('0')) if '%' not in n else len(mant)


SNAPSHOT_SOURCES = ('polymarket_markets', 'defillama_yields')


def is_snapshot(m):
    """Structured lane snapshot material (live/adapters/lane_data, polymarket, defillama_yields): links by URL /
    headline / hook only."""
    return str(m.get('adapter') or '').startswith('lane_data:') or m.get('source_id') in SNAPSHOT_SOURCES


def link_reason(a, b, df, rare, loose=None):
    """Why two materials are the same story (deterministic), or None. rare: df ceiling for entity-only links;
    loose: df ceiling for an entity backing a round (1 significant digit) number."""
    loose = loose if loose is not None else 3 * rare
    if a['url'] and a['url'] == b['url']:
        return 'url'
    if a['_event'] and a['_event'] == b['_event']:
        return 'headline'
    if a['_hooks'] & b['_hooks']:
        return 'hook'
    if is_snapshot(a) or is_snapshot(b):
        return None   # a daily data table (DefiLlama / Polymarket / Hyperliquid snapshot) is not a story: a shared
        #               'DefiLlama' + a coincidental 7.5% chained every niche-lane table into one 母题 (Oct 8)
    ents = a['_ents'] & b['_ents']
    nums = a['_nums'] & b['_nums']
    if ents and any(_sig(n) >= 2 for n in nums):
        return 'number+entity'
    if nums and any(df.get(e, 0) <= loose for e in ents):
        return 'round_number+entity'
    rare_shared = {e for e in ents if df.get(e, 0) <= rare}
    if len(rare_shared) >= 2:
        return 'entities'
    jac = _jaccard(a['_bi'], b['_bi'])
    if rare_shared and jac >= 0.2:
        return 'entity+zh_headline'
    if jac >= 0.3 and len(ents) >= 2:
        return 'zh_headline+entities'
    if jac >= 0.45 and (ents or nums):
        return 'zh_headline'
    return None


def cluster(mats):
    """[[material index]] by deterministic links (union-find), largest first."""
    n = len(mats)
    df = {}
    for m in mats:
        for e in m['_ents']:
            df[e] = df.get(e, 0) + 1
    rare = max(3, int(0.01 * n))
    uf = _UF(n)
    links = {i: [] for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if link_reason(mats[i], mats[j], df, rare):
                links[i].append(j)
                links[j].append(i)
    hub = {i for i in range(n) if DIGEST.search(mats[i]['title']) or len(links[i]) >= HUB_DEGREE}
    for i in range(n):
        for j in links[i]:
            if i < j and i not in hub and j not in hub:
                uf.union(i, j)
    for i in sorted(hub):   # a hub joins the cluster it links to most, never bridges two
        roots = [uf.find(j) for j in links[i] if j not in hub]
        if roots:
            uf.union(i, max(set(roots), key=lambda r: (roots.count(r), -r)))
    out = {}
    for i in range(n):
        out.setdefault(uf.find(i), []).append(i)
    return sorted(out.values(), key=lambda c: (-len(c), c[0]))


def merge_candidates(clusters, mats, limit=MERGE_MAX):
    """Clusters the merge call sees: the core (multi-source, or in some account's own pool), then near misses -
    singletons that share a non-ubiquitous entity or a CJK headline bigram overlap with a core cluster (the cases the
    deterministic links could not settle, e.g. an X post on the same shutdown worded differently)."""
    df = {}
    for m in mats:
        for e in m['_ents']:
            df[e] = df.get(e, 0) + 1
    loose = max(6, int(0.03 * len(mats)))
    core = [c for c in clusters if len(c[1]) > 1 or any(mats[i]['accounts'] for i in c[1])]
    core.sort(key=lambda c: (-sum(len(mats[i]['accounts']) for i in c[1]), -len(c[1]), c[0]))
    core = core[:limit]
    ents = set().union(*[mats[i]['_ents'] for _c, idx in core for i in idx]) if core else set()
    ents = {e for e in ents if df.get(e, 0) <= loose}
    bis = [set().union(*[mats[i]['_bi'] for i in idx]) for _c, idx in core]
    near = []
    for c in clusters:
        if c in core:
            continue
        m = mats[c[1][0]]
        shared = len(m['_ents'] & ents)
        jac = max([_jaccard(m['_bi'], b) for b in bis if b] or [0.0])
        if shared or jac >= 0.15:
            near.append((-(shared + 4 * jac), c))
    near.sort(key=lambda x: (x[0], x[1][0]))
    return core + [c for _s, c in near][:max(0, limit - len(core))]


def merge_prompt(clusters, mats):
    lines = []
    for cid, idx in clusters:
        titles = [mats[i]['title'][:110] for i in sorted(idx, key=lambda i: mats[i]['_t'] or datetime.min.replace(tzinfo=timezone.utc))[:3]]
        lines.append({'id': cid, 'titles': titles})
    system = ('You group financial / crypto news items into stories. Two items are the same story only when they '
              'report the same event (same actor and same action / number), in any language. Same broad topic '
              '(e.g. "bitcoin price") is NOT enough unless they report the same move. Return JSON only: '
              '{"groups": [{"ids": ["c1", "c4"], "title_zh": "...", "title_en": "..."}]}. Every input id appears in '
              'exactly one group (singletons allowed). Titles: a neutral headline of the story, zh <= 24 characters, '
              'en <= 12 words, no opinion, no number that is not in the items.')
    return [{'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps({'clusters': lines}, ensure_ascii=False)}]


def apply_merge(clusters, merge):
    """clusters: [(cid, [idx])]; merge: parsed {'groups': [...]}. Returns ([(cid, idx)], {cid: titles}). Unknown ids
    are ignored, an id in two groups stays in the first, a group may not join more than 8 clusters."""
    by = dict(clusters)
    seen, out, titles = set(), [], {}
    for g in (merge or {}).get('groups') or []:
        ids = [i for i in g.get('ids') or [] if i in by and i not in seen][:8]
        if not ids:
            continue
        seen |= set(ids)
        idx = sorted({x for i in ids for x in by[i]})
        out.append((ids[0], idx))
        titles[ids[0]] = {'zh': str(g.get('title_zh') or '')[:40], 'en': str(g.get('title_en') or '')[:120],
                          'merged': ids}
    out += [(cid, idx) for cid, idx in clusters if cid not in seen]
    return out, titles


def run_merge(clusters, mats, day, client=None, cap_usd=MERGE_CAP_USD, store=None):
    """The one flash call of the day (cached). Returns parsed merge dict or None (no client / over cap / error)."""
    path = Path(store or store_dir()) / f'{day}.merge.json'
    try:
        cached = json.loads(path.read_text())
        if cached.get('merge') is not None:
            # cluster ids are positional (c0, c1 ...): a later run the same day (--fill after a new ingest) has other
            # materials, so cached ids are mapped back through their member keys; a cache without them is not reused
            return remap_merge(cached['merge'], cached.get('members'), clusters, mats)
    except (OSError, ValueError):
        pass
    if client is None:
        return None
    messages = merge_prompt(clusters, mats)
    est_in = len(json.dumps(messages, ensure_ascii=False)) / 2.5
    est = est_in / 1e6 * 0.5 + 24000 / 1e6 * 3.0     # flash list prices, the stage's max output (thinking counts)
    if est > cap_usd:
        return None
    from live.model_json import parse_object
    try:
        r = client('extract_flash', messages, 8000)
        if r.get('model_fallback') or not str(r.get('response_model') or '').startswith('gemini-'):
            raise RuntimeError(f"non-Gemini response {r.get('response_model')}")
        merge = parse_object(r['text'])
    except Exception as exc:   # noqa: BLE001 - deterministic clusters stand on their own
        record = {'day': day, 'merge': None, 'error': f'{type(exc).__name__}: {str(exc)[:200]}'}
        _write(path, record)
        return None
    cost = 0.0
    for c in getattr(client, 'calls', []) or []:
        try:
            cost += float(json.loads(Path(c['path']).read_text()).get('estimated_cost_usd') or 0)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    _write(path, {'day': day, 'merge': merge, 'model': r.get('response_model'), 'cost_usd': round(cost, 6),
                  'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'n_clusters': len(clusters),
                  'members': _members(clusters, mats)})
    return merge


def _members(clusters, mats):
    return {cid: [json.dumps(mats[i]['key']) for i in idx] for cid, idx in clusters}


def remap_merge(merge, members, clusters, mats):
    """A cached merge in terms of the current cluster ids (via member keys); None when the cache has no members."""
    if not members:
        return None
    now = {}
    for cid, keys in _members(clusters, mats).items():
        for k in keys:
            now.setdefault(k, cid)
    groups = []
    for g in (merge or {}).get('groups') or []:
        ids = []
        for old in g.get('ids') or []:
            cur = next((now[k] for k in members.get(old) or [] if k in now), None)
            if cur and cur not in ids:
                ids.append(cur)
        if ids:
            groups.append(dict(g, ids=ids))
    return {'groups': groups}


def merge_client(calls_dir):
    """Flash client on the extract_flash stage (FD_GEMINI_PROVIDER relay by default), Gemini only, no fallback."""
    import copy
    from live import erisedai_distillation_client as ec, stage_models
    os.environ['FD_GEMINI_ONLY'] = '1'
    table = stage_models.from_env(stage_models.load(), os.environ)
    route = stage_models.route(table, 'extract_flash')
    if not route or not stage_models.is_gemini_route(route['base_url']) or stage_models.model_fallback(table, 'extract_flash'):
        raise RuntimeError('extract_flash must run on Gemini without a model fallback')
    config = {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'unused-gemini-only',
              'configuration_source': 'gemini_only_hotspot_merge', 'model': ec.DEFAULT_MODEL,
              'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0, 'gemini_only': True,
              'stage_models': table}
    return ec.ErisedaiClient(calls_dir, configuration=copy.deepcopy(config))


# ------------------------------------------------------------------ 母题 + heat

def _heat_signals(day):
    """Cached public-heat signals only (never fetches here; daily_compose.apply_heat owns the fetch)."""
    from live import heat
    if not heat.enabled():
        return [], heat
    cached = heat.load(day)
    return (heat._signals(cached.get('items') or []) if cached else []), heat


def motif_topics(titles, crypto_flags=()):
    """Topics (live/posting_habits.TOPICS) hit by at least half the members' titles, most hits first; the first one
    is the 母题 type. Counting members, not regex order, keeps a price unit (美元) from typing a BTC story as fx.
    crypto_flags: per member, True when its units carry a crypto beat tag or editorial_style counts a crypto term
    (posting_habits has no L2 / token words, and a $CASHTAG alone reads as a stock)."""
    from live.posting_habits import _TOPIC_RX
    titles = [re.sub(r'\d[\d,.]*\s*(?:万|亿)?\s*美元(?:/\S+)?|[$＄]\s?\d[\d,.]*', ' ', t) for t in titles if t] or ['']
    counts = {k: sum(1 for t in titles if rx.search(t)) for k, rx in _TOPIC_RX}
    counts['crypto'] = max(counts['crypto'], sum(1 for f in crypto_flags if f))
    best = max(counts.values())
    if not best:
        return ['other']
    order = [k for k, _ in _TOPIC_RX]
    return sorted((k for k, n in counts.items() if n and n * 2 >= best), key=lambda k: (-counts[k], order.index(k)))


def reach_weight():
    """Weight of 'accounts whose pool holds a member' in breadth. FD_TOPIC_DIV (default on) sets it to 0: that count
    measured how many accounts share one news feed (10 crypto pools held the same ~15 items on 10-08), not heat."""
    from live import topic_div
    return 0.0 if topic_div.enabled() else 0.7


def hot_pool(ms, pubs, public_heat, accts):
    """Hotspot pool: >= 2 publishers (or public heat with an account source). A 母题 made only of X posts needs
    X_ONLY_MIN_PUBLISHERS distinct authors (Oct 8: $CLAUS = one author + one echo got a WRITE)."""
    if all(str(m.get('adapter') or '').startswith('x:') for m in ms):
        return len(pubs) >= X_ONLY_MIN_PUBLISHERS
    return len(pubs) >= 2 or (public_heat >= 1.0 and bool(accts))


def build_motifs(mats, groups_idx, ref, titles=None, day=None):
    signals, heat = _heat_signals(day or ref.date().isoformat())
    out = []
    for cid, idx in groups_idx:
        ms = sorted((mats[i] for i in idx), key=lambda m: m['_t'])
        text = '\n'.join(m['title'] for m in ms)
        pubs = {m['publisher'] for m in ms}
        accts = sorted({a for m in ms for a in m['accounts']})
        latest = max(m['_t'] for m in ms)
        h_in, terms = heat.score(text, signals) if signals else (0.0, [])
        h_in = min(3.0, h_in)
        breadth = math.log2(1 + len(pubs)) + 0.5 * math.log2(1 + len(ms)) + reach_weight() * math.log2(1 + len(accts))
        recency = math.exp(-max(0.0, (ref - latest).total_seconds()) / 3600 / 12)
        score = round(breadth + 0.5 * h_in + recency, 3)
        t = (titles or {}).get(cid) or {}
        lead = max(ms, key=lambda m: (not m['adapter'].startswith('x:'), len(m['accounts']), -(m['_t'].timestamp())))
        from live.editorial_style import crypto_hits
        topics = motif_topics([m['title'] for m in ms],
                              [bool(crypto_hits(m['title'])) or any(t.startswith('crypto_') for t in m['tags']) for m in ms])
        out.append({
            # id = the earliest member: stable through the day as later reports join the 母题
            'id': 'm-' + hashlib.sha1(json.dumps(ms[0]['key']).encode()).hexdigest()[:10],
            'title': t.get('zh') if lead['lang'] == 'zh' and t.get('zh') else (t.get('en') or lead['title'][:120]),
            'title_zh': t.get('zh') or '', 'title_en': t.get('en') or '', 'title_by': 'flash' if t else 'lead_source',
            'event_time': ms[0]['published_at'], 'latest_time': max(ms, key=lambda m: m['_t'])['published_at'],
            'source_count': len(ms), 'publisher_count': len(pubs), 'account_source_count': len(accts),
            'accounts': accts, 'type': topics[0], 'topics': topics,
            'heat': {'score': score, 'breadth': round(breadth, 3), 'public_heat': round(h_in, 3),
                     'public_terms': terms[:6], 'recency': round(recency, 3)},
            'pool': 'hotspot' if hot_pool(ms, pubs, h_in, accts) else 'discovery',
            'members': [{k: m[k] for k in ('key', 'title', 'publisher', 'url', 'published_at', 'adapter', 'lang',
                                           'tier', 'accounts', 'n_numbers', 'tags')} for m in ms]})
    out.sort(key=lambda m: (m['pool'] != 'hotspot', -m['heat']['score'], m['id']))
    return out


# ------------------------------------------------------------------ per-account decision

def topic_fit(universe, motif):
    mix = (universe or {}).get('topic_mix') or {}
    return round(max([mix.get(t, 0.0) for t in motif['topics'] if t != 'other'] or [0.0]), 4)


def decide(motifs, accounts, universes, pool_keys, ok, led=(), priors=None, top=TOP_N,
           per_lang=MAX_PER_LANG, seed_takers=None):
    """{motif id: {account: {'decision', 'reason', 'fit', 'key'}}}, {account: (motif id, member key)}.

    pool_keys {account: [source key tuples in pool order]}; ok(account, key) -> timely + prescreen ok;
    led: accounts that already have a hotspot draft today; seed_takers {motif id: [(account, lang)]} (fill runs)."""
    from live import feedback, twins
    lang = {a['id']: a['lang'] for a in accounts}
    table, assign = {}, {}
    taken = {a for a in led}
    for m in [m for m in motifs if m['pool'] == 'hotspot'][:top]:
        keys = {tuple(x['key']) for x in m['members']}
        row, cands = {}, []
        for a in accounts:
            aid = a['id']
            mine = [k for k in pool_keys.get(aid, []) if k in keys]
            fit = topic_fit(universes.get(aid), m)
            if not mine:
                row[aid] = {'decision': 'IGNORE', 'reason': 'off beat: no member in its own sources / beats', 'fit': fit}
                continue
            if fit < FIT_MIN:
                row[aid] = {'decision': 'IGNORE', 'reason': f'outside its topic spread ({m["type"]} {fit:.2f} < {FIT_MIN})',
                            'fit': fit}
                continue
            lanes = set((universes.get(aid) or {}).get('lanes') or [])
            if (lanes and fit < LANE_FIT_OVERRIDE
                    and not any(lanes & set(x.get('tags') or []) for x in m['members'] if tuple(x['key']) in mine)):
                # crypto accounts with own lanes (meme / defi / perp / on-chain ...): a 母题 outside them is off beat,
                # unless its type is a big part of the account's own topic mix (Oct 8: lane OR share >= 0.2 - Robinhood
                # in 14 pools got no WRITE)
                row[aid] = {'decision': 'IGNORE', 'reason': 'outside its own lanes (' + ', '.join(sorted(lanes)) + ')'
                            + f' and topic share {fit:.2f} < {LANE_FIT_OVERRIDE}', 'fit': fit}
                continue
            from live import angles
            lead = angles.top_angles((universes.get(aid) or {}).get('angle_lead') or {}, 4)
            lens = len(set(lead) & set(angles.angles_of('\n'.join(x['title'] for x in m['members']))))
            good = [k for k in mine if ok(aid, k)]
            if not good:
                row[aid] = {'decision': 'HOLD', 'reason': 'no member timely and passing prescreen', 'fit': fit}
            elif aid in taken:
                row[aid] = {'decision': 'HOLD', 'reason': 'already has its hotspot today', 'fit': fit}
            else:
                # topic share x (1 + 0.25 per own top lens the story supports) x review feedback on this 母题 type
                score = fit * (1 + 0.25 * lens) * feedback.motif_multiplier(priors or {}, aid, m['type'])
                cands.append((-score, aid, good[0], fit))
        takers = list((seed_takers or {}).get(m['id'], []))
        for _neg, aid, key, fit in sorted(cands):
            if sum(1 for _a, lg in takers if lg == lang[aid]) >= per_lang:
                row[aid] = {'decision': 'HOLD', 'reason': f'cap: {per_lang} {lang[aid]} accounts already on this 母题',
                            'fit': fit}
                continue
            twin = twins.twin_of(aid) if twins.enabled() else None
            if twin and any(a == twin for a, _lg in takers):   # FD_TWIN_RULE: zh/en twins never share a 母题 in a day
                row[aid] = {'decision': 'HOLD', 'reason': f'twin rule: {twin} already on this 母题', 'fit': fit}
                continue
            row[aid] = {'decision': 'WRITE', 'reason': 'on beat, in its topic spread', 'fit': fit, 'key': list(key)}
            takers.append((aid, lang[aid]))
            taken.add(aid)
            assign[aid] = (m['id'], key)
        table[m['id']] = row
    return table, assign


# ------------------------------------------------------------------ day plan

class DayPlan:
    """What daily_compose.select needs: alias {source key: motif id}, assign {account: (motif id, key)}, motifs."""

    def __init__(self, day, motifs, table, assign, meta):
        self.day, self.motifs, self.table, self.assign, self.meta = day, motifs, table, assign, meta
        self.by_id = {m['id']: m for m in motifs}
        self.alias = {tuple(x['key']): m['id'] for m in motifs if m['source_count'] > 1 for x in m['members']}

    def motif_of(self, key):
        return self.alias.get(tuple(key))

    def tag(self, motif_id):
        m = self.by_id[motif_id]
        return {'motif_id': m['id'], 'title': m['title'], 'title_zh': m['title_zh'], 'title_en': m['title_en'],
                'type': m['type'], 'heat': m['heat']['score'], 'source_count': m['source_count'],
                'publisher_count': m['publisher_count'], 'account_source_count': m['account_source_count'],
                'event_time': m['event_time'], 'decision': 'WRITE'}

    def record(self, account, motif_id, **kw):
        self.table.setdefault(motif_id, {}).setdefault(account, {}).update(kw)

    def summary(self, top=TOP_N):
        hot = [m for m in self.motifs if m['pool'] == 'hotspot'][:top]
        return {'version': VERSION, **self.meta,
                'top': [{k: m[k] for k in ('id', 'title', 'type', 'event_time', 'source_count', 'publisher_count',
                                           'account_source_count')} | {'heat': m['heat']['score']} for m in hot],
                'assign': {a: mid for a, (mid, _k) in self.assign.items()}}

    def save(self, store=None):
        path = Path(store or store_dir()) / f'{self.day}.json'
        _write(path, {'day': self.day, 'version': VERSION, **self.meta,
                      'motifs': self.motifs, 'decisions': self.table,
                      'assign': {a: {'motif_id': mid, 'key': list(k)} for a, (mid, k) in self.assign.items()}})
        return path


def plan_day(store, pools, accounts, universes, day, ref, *, text_of, key_of, ok, led=(), promo=None,
             merge_client_factory=None, priors=None, seed_takers=None):
    """Build the day's 母题 pool and per-account decisions. pools {account: [groups in pool order]}."""
    groups = gather(store, ref, promo=promo)
    from live import news_hook
    pool_keys = {a: [tuple(key_of(g)) for g in p] for a, p in pools.items()}
    for p in pools.values():                    # pool groups carry the same records; prefer them (same text)
        for g in p:
            groups.setdefault(tuple(key_of(g)), g)
    keys = sorted(groups, key=lambda k: str(k))
    mats = []
    in_window = ref - timedelta(hours=WINDOW_H)
    for k in keys:
        g = groups[k]
        m = material(k, g, text_of(g))
        if m['_t'] is None or not (in_window < m['_t'] <= ref):
            continue
        try:
            m['_hooks'] = set(news_hook.hooks(m['title']))
        except Exception:   # noqa: BLE001
            pass
        m['_event'] = _title_event(m['title'])
        m['accounts'] = sorted(a for a, ks in pool_keys.items() if k in set(ks))
        mats.append(m)
    raw = cluster(mats)
    clusters = [(f'c{i}', idx) for i, idx in enumerate(raw)]
    ranked = merge_candidates(clusters, mats)
    client = None
    if merge_client_factory is not None:
        try:
            client = merge_client_factory()
        except Exception as exc:   # noqa: BLE001 - no key / provider: deterministic only
            print(f'hotspot merge: no client ({type(exc).__name__}: {str(exc)[:120]})', flush=True)
    merge = run_merge(ranked, mats, day, client=client)
    titles = {}
    if merge:
        merged, titles = apply_merge(ranked, merge)
        rest = [c for c in clusters if c[0] not in {cid for cid, _ in ranked}]
        clusters = merged + rest
    motifs = build_motifs(mats, clusters, ref, titles=titles, day=day)
    ok_key = {a: {tuple(key_of(g)): g for g in p} for a, p in pools.items()}
    table, assign = decide(motifs, accounts, universes, pool_keys, lambda a, k: ok(a, ok_key[a][k]), led=led,
                           priors=priors, seed_takers=seed_takers)
    meta = {'ref': ref.isoformat(), 'window_h': WINDOW_H, 'materials': len(mats), 'clusters_deterministic': len(raw),
            'merge': 'flash' if merge else 'none', 'motifs': len(motifs),
            'hotspot_pool': sum(m['pool'] == 'hotspot' for m in motifs),
            'discovery_pool': sum(m['pool'] == 'discovery' for m in motifs)}
    return DayPlan(day, motifs, table, assign, meta)


def _title_event(title):
    toks = re.findall(r'[a-z0-9$.,]+|[一-鿿]{2,}', str(title or '').lower())
    toks = [t.strip('.,') for t in toks if t.strip('.,') and t.strip('.,') not in STOP]
    if len(toks) < 3:
        return None
    nums = sorted({t for t in toks if re.search(r'\d', t)})
    return ('title', toks[0], *nums) if nums else ('title', *toks[:3])


def hotspot_led(rows):
    return {r['account_id'] for r in rows if r.get('hotspot') and not r.get('superseded')}


# ------------------------------------------------------------------ reality payload

def _fmt(v):
    return f'{v:,.2f}' if v < 1000 else f'{v:,.0f}'


def price_line(text, fetch_crypto=None, fetch_stock=None, now=None):
    """Latest price of the 母题's main ticker from the free chart fetchers, or None."""
    from live import charts
    subj = charts.pick_subject(text)
    if not subj:
        return None
    try:
        if subj['asset'] == 'crypto':
            data = (fetch_crypto or charts.fetch_crypto)(subj['symbol'], '1h', 30)
            back = 24
        else:
            data = (fetch_stock or charts.fetch_stock)(subj['symbol'], '1d', 5)
            back = 1
    except Exception:   # noqa: BLE001
        return None
    rows = (data or {}).get('rows') or []
    if not rows:
        return None
    last = rows[-1]
    prev = rows[-1 - back] if len(rows) > back else rows[0]
    chg = (last[4] / prev[4] - 1) * 100 if prev[4] else None
    at = datetime.fromtimestamp(last[0], timezone.utc)
    # a 1h bar closes at the end of its hour, a US daily bar (stamped at the open) at 20:00 UTC; a bar still open
    # holds the latest trade, so the time is never later than now
    at = at + timedelta(hours=1) if subj['asset'] == 'crypto' else at.replace(hour=20, minute=0)
    at = min(at, now or datetime.now(timezone.utc))
    return {'symbol': subj['display'], 'last': round(last[4], 6), 'last_text': _fmt(last[4]),
            'change_pct': round(chg, 2) if chg is not None else None,
            'change_window': '24h' if subj['asset'] == 'crypto' else '1 trading day',
            'as_of': at.isoformat(timespec='minutes'), 'source': data.get('source'), 'url': data.get('url')}


def reality(plan, motif_id, account, ref, x_handles=(), price=True, fetchers=None, x_pulse=None):
    """Compact reality payload for one WRITE pick."""
    m = plan.by_id[motif_id]
    own = {h.lower() for h in x_handles or ()}
    recent = []
    for x in sorted(m['members'], key=lambda x: _ts(x['published_at']) or ref, reverse=True):
        t = _ts(x['published_at'])
        if t is None or ref - t > timedelta(hours=RECENT_H) or x['tier'] not in ('A', 'B'):
            continue
        if x['adapter'].startswith('x:') and x['adapter'][2:].lower() not in own:
            continue
        recent.append({k: x[k] for k in ('publisher', 'title', 'url', 'published_at')})
        if len(recent) == 3:
            break
    out = {'as_of': ref.isoformat(timespec='minutes'), 'motif': m['title'], 'recent_sources': recent}
    if price:
        p = price_line('\n'.join(x['title'] for x in m['members']), **(fetchers or {}))
        if p:
            out['price'] = p
    if x_pulse:
        try:
            out['x_pulse'] = x_pulse(m)
        except Exception as exc:   # noqa: BLE001
            out['x_pulse'] = {'error': f'{type(exc).__name__}: {str(exc)[:120]}'}
    return out


REALITY_RULE = ('Reality check, newer than or as new as the source: the latest price of the main ticker and the newest '
                'reports on the same story. Use it only so the post does not state a stale fact as current (e.g. a '
                'price or level the source gives that has since moved: say what it is now, with the time). Do not '
                'build the post around these lines, do not name these outlets, and write any number taken from here '
                'exactly as given.')


def reality_lines(r):
    """Plain-text lines of a reality payload (added to the grounding text of the draft's checks)."""
    out = []
    p = (r or {}).get('price')
    if p:
        chg = f", {p['change_window']} {p['change_pct']:+.2f}%" if p.get('change_pct') is not None else ''
        out.append(f"{p['symbol']} {p['last_text']} ({p['source']}, as of {p['as_of']}{chg})")
    for s in (r or {}).get('recent_sources') or []:
        out.append(f"{s['publisher']}: {s['title']} ({s['published_at']})")
    return out


def x_pulse_factory(day, store=None, key=None, cap=X_CAP):
    """twitter241 search used as a 24h post count (no text kept). Day-capped via the call log; None without a key."""
    key = key or os.environ.get('RAPID_X_API_KEY')
    if not key:
        return None
    from live.archive_lookback import SearchClient, _parse_created
    log = Path(store or store_dir()) / f'{day}.x_calls.jsonl'
    made = len(log.read_text().splitlines()) if log.exists() else 0
    client = SearchClient(key, max(0, cap - made), log)

    def pulse(m):
        ents = sorted({e for x in m['members'] for e in entities(x['title'])} - {'btc', 'eth', 'bitcoin'})[:3]
        query = ' '.join(ents) or m['title_en'] or m['title']
        data = client.search(query, account='hotspot', handle='', window='24h', count=20)
        times = [t for t in (_parse_created(v) for v in re.findall(r'"created_at":\s*"([^"]+)"', json.dumps(data))) if t]
        now = datetime.now(timezone.utc)
        return {'query': query, 'posts_24h_in_sample': sum(1 for t in times if now - t <= timedelta(hours=24)),
                'sample': len(times), 'newest_at': max(times).isoformat(timespec='minutes') if times else None}
    return pulse


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str) + '\n')
    tmp.replace(path)
