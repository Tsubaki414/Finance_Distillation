"""Aggregate donor language habits for compose; donor text stays out of git.

Oct 6 donor clusters (Fiona 13:21): every account has a beat-fit cluster of >= 3 real donors
(roster.persona_clusters['acct_<account>'], scripts/build_account_clusters.py). The card is built from
the cluster's originals, sampled in proportion to the donor weights, and records only aggregates:
sentence-length distribution, post-length mix, common openers / closers (used by >= 2 donors),
connectives and particles with their rates, how reasons and implications are introduced, and each
donor's own catchphrases (distinctive n-grams, kept as do-not-overuse markers). Real example lines
(reason / implication sentences, rotating anchor posts) are read from the local corpus at compose
time by payload_card() and never written to the card.
"""
from __future__ import annotations

import collections
import json
import math
import random
import re
from hashlib import sha256
from pathlib import Path

from live.exemplars import load_posts

CARDS_DIR = Path(__file__).resolve().parent / 'personas' / 'language_habits'

ZH_JARGON = ('供需缺口', '议价权', '定价权能否', '基本面支撑', '投资假设', '产能扩张加速',
             '链路往下', '每一环', '催化', '中性偏多', '维持买入', '目标价', '核心看点',
             '值得注意的是', '综上所述', '总而言之', '具体来看', '拆解一下')
EN_JARGON = ('valuation-free', 'supply-discipline', 'multiple expansion', 're-rating',
             'as a reminder', 'key takeaway', 'in conclusion', 'net-net', 'our base case',
             'risk/reward', 'skewed to the upside', 'priced in', 'Calling a strong chance')
ZH_CONN = ('但是', '不过', '反而', '其实', '说白了', '分开看', '换句话说', '所以', '因此', '而且',
           '毕竟', '只是', '结果', '然后', '当然', '也就是说', '这意味着', '关键是', '问题是', '何况', '甚至', '至于')
EN_CONN = ('but', 'though', 'instead', 'still', 'so', 'and', 'while', 'yet', 'because',
           'which means', 'that means', 'in other words', 'meanwhile', 'even', 'actually')
ZH_PARTICLES = ('吧', '呢', '啊', '嘛', '呗', '了', '挺', '有点', '估计', '感觉', '真的', '就是', '反正', '还是', '这波', '其实')
# How donors introduce a reason / an implication (marker -> share of reason / implication sentences).
ZH_REASON = ('因为', '由于', '主要是', '毕竟', '原因是', '靠', '在于', '来自', '导致', '拖累', '撑着', '源于')
ZH_IMPL = ('所以', '结果', '后面', '接下来', '利好', '利空', '受益', '吃亏', '意味着', '就会', '等于', '影响',
           '对于', '那么', '说明')
EN_REASON = ('because', 'since', 'due to', 'driven by', 'thanks to', 'as a result of', 'on the back of')
EN_IMPL = ('so ', 'which means', 'that means', 'means', 'implies', 'bad for', 'good for', 'bullish', 'bearish',
           'expect', 'sets up', 'watch')
CJK = re.compile(r'[一-鿿]')
URL = re.compile(r'https?://\S+')
_SENT_ZH = re.compile(r'[。！？!?\n；;]+')
_SENT_EN = re.compile(r'(?<=[.!?])\s+|\n+')
_UNSAFE = re.compile(r'[@#$＄「」“”"『』《》]|https?://')
# The account never says 我们 nor talks about its own positions; example lines that do are not shown.
_SELF = re.compile(r'我们|咱们|我的仓|重仓|持仓|建仓|加仓|减仓|清仓|带带我|\b(?:we|our|my position|i bought|i sold|long here|short here)\b', re.I)
SAMPLE_TOTAL = 600   # posts drawn across the cluster, split by donor weight

GUIDANCE = ('Write like the donors: judgment-first, short beats, plain reasons. '
            'Avoid analyst-report cadence, Fiona-banned fillers and hedge-only lines.')

INDUSTRY_CONSTRAINTS = {
    'zh': [
        'NEG: 研报腔 / analyst note tone — no 链路往下推, 每一环的议价权, 基本面支撑套话, 信息罗列收尾.',
        'NEG: do not end on 还早着呢 / 才是关键 filler.',
        'POS: open with a plain judgment sentence; name the one constraint that decides the call '
        '(capacity, pricing power, demand visibility) without a jargon chain.',
        'POS: short uneven lines; one concrete split (e.g. demand vs capacity) beats a full supply-chain parade.',
    ],
    'en': [
        'NEG: no valuation-free optimism, supply-discipline check filler, or sell-side re-rating talk.',
        'NEG: no Calling a strong chance / is a start / empty That said / door metaphor.',
        'POS: lead with the call; test demand visibility vs supply/capex with numbers from units only.',
        'POS: agreements ≠ margins — say which demand data the call rests on.',
    ],
}


def _originals(posts):
    return [p for p in posts if p.get('text') and not p.get('rt') and not p.get('reply') and not p.get('pinned')]


def _lang_ok(text, lang):
    n = len(CJK.findall(text))
    return n >= 15 if lang == 'zh' else (n == 0 and len(text) >= 40)


# Sponsor tails (TraderS18: 94 of 202 originals end on "@BITstocks_CN 买美股上BIT…"; qinbafrank "本条由@bitget_zh赞助")
# and other promo / @ lines are cut before any habit is measured or any line is shown.
_PROMO_LINE = re.compile(r'@\w+|赞助|买美股上|开户|入金|佣金|返佣|邀请码|注册|链接|课程|社群|进群|星球|付费|订阅|抽奖|福利|'
                         r'sponsored|subscribe|sign up|link in bio|promo code|use code|discount|referral', re.I)


def strip_promo(text):
    lines = [ln for ln in URL.sub('', str(text or '')).splitlines() if not _PROMO_LINE.search(ln)]
    return '\n'.join(lines).strip()


def cluster_posts(persona, posts_dir=None, total=SAMPLE_TOTAL):
    """[(handle, post)] of the persona's donors, up to weight * total recent originals per donor."""
    out = []
    for handle, weight in (getattr(persona, 'donor_weights', {}) or {}).items():
        try:
            posts = load_posts(handle, posts_dir)
        except Exception:
            continue
        posts = [dict(p, text=strip_promo(p['text'])) for p in _originals(posts)]
        posts = [p for p in posts if _lang_ok(p['text'], persona.lang)]
        posts.sort(key=lambda p: str(p.get('id')), reverse=True)
        quota = max(20, int(round(weight * total)))
        out.extend((handle, p) for p in posts[:quota])
    return out


def _sentences(text, lang):
    parts = _SENT_ZH.split(text) if lang == 'zh' else _SENT_EN.split(text)
    return [s.strip() for s in parts if s and s.strip()]


def _size(text, lang):
    return len(CJK.findall(text)) if lang == 'zh' else len(re.findall(r"[A-Za-z0-9$%'.-]+", text))


def _quantiles(xs):
    xs = sorted(xs)
    if not xs:
        return {}
    def q(p):
        return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]
    return {'p10': q(.1), 'p25': q(.25), 'median': q(.5), 'p75': q(.75), 'p90': q(.9)}


def _opener_gram(text, lang):
    first = (_sentences(text, lang) or [''])[0]
    if lang == 'zh':
        chars = ''.join(CJK.findall(first[:6]))
        return chars[:2] if len(chars) >= 2 else None
    words = re.findall(r"[A-Za-z']+", first.lower())
    return words[0] if words else None


def _closer(text, lang):
    last = text.rstrip()
    end = last[-1:] if last else ''
    if lang == 'zh':
        body = re.sub(r'[。！？!?…~～\s）)」”"]+$', '', last)
        tail = body[-1:] if body else ''
        punct = {'。': '。', '！': '！', '!': '！', '？': '？', '?': '？', '…': '…'}.get(end, 'none')
        return punct, tail if tail in '了吧呢啊嘛呗的' else 'other'
    punct = {'.': '.', '!': '!', '?': '?'}.get(end, 'none')
    return punct, None


def _grams(text, lang):
    if lang == 'zh':
        out = set()
        for seg in re.findall(r'[一-鿿]{4,}', text):
            out |= {seg[i:i + 4] for i in range(len(seg) - 3)}
        return out
    words = re.findall(r"[a-z']+", text.lower())
    return {' '.join(words[i:i + 3]) for i in range(len(words) - 2)}


_STOP_EN = {'the', 'a', 'an', 'of', 'to', 'in', 'and', 'is', 'for', 'on', 'that', 'this', 'it', 'at', 'with', 'are', 'be'}


def catchphrases(rows, lang, per_donor=5, min_share=0.06, max_other=0.01):
    """{handle: [phrase]}: n-grams frequent in one donor's posts and rare in the other donors'."""
    by = collections.defaultdict(list)
    for h, p in rows:
        by[h].append(_grams(p['text'], lang))
    df = {h: collections.Counter(g for gs in grams for g in gs) for h, grams in by.items()}
    out = {}
    for h, counts in df.items():
        n = len(by[h])
        others = sum(len(by[o]) for o in by if o != h) or 1
        cands = []
        for g, c in counts.items():
            if c < 3 or c / n < min_share or re.search(r'\d', g):
                continue
            if lang == 'en' and sum(w in _STOP_EN for w in g.split()) >= 2:
                continue
            other = sum(df[o].get(g, 0) for o in df if o != h) / others
            if other <= max_other:
                cands.append((c / n, g))
        cands.sort(reverse=True)
        picked = []
        for _, g in cands:   # drop overlapping 4-grams of one longer phrase
            if any(g[1:] in q or q[1:] in g for q in picked) if lang == 'zh' else False:
                continue
            picked.append(g)
            if len(picked) >= per_donor:
                break
        if picked:
            out[h] = picked
    return out


def build_card(persona, posts_dir=None):
    rows = cluster_posts(persona, posts_dir)
    posts = [p for _, p in rows]
    n = len(posts)
    lang = persona.lang
    jargon = ZH_JARGON if lang == 'zh' else EN_JARGON
    conns = ZH_CONN if lang == 'zh' else EN_CONN
    first_judgment = fragments = jargon_hits = 0
    conn_c, conn_donors = collections.Counter(), collections.defaultdict(set)
    sent_sizes, post_sizes = [], []
    openers, opener_donors = collections.Counter(), collections.defaultdict(set)
    end_punct, end_particle = collections.Counter(), collections.Counter()
    particles = collections.Counter()
    reason_c, impl_c = collections.Counter(), collections.Counter()
    reason_n = impl_n = 0
    cjk_total = 0
    for handle, p in rows:
        text = p['text']
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        first = lines[0] if lines else text[:40]
        if lang == 'zh':
            if not re.match(r'^[\d$￥%\.\s]+', first):
                first_judgment += 1
            fragments += sum(1 for ln in lines if 2 <= len(ln) <= 18)
        else:
            if not re.match(r'^[\d$%.\s]+', first):
                first_judgment += 1
            fragments += sum(1 for ln in lines if 2 <= len(ln.split()) <= 6)
        low = text.casefold()
        if any(j.casefold() in low for j in jargon):
            jargon_hits += 1
        for c in conns:
            hit = (c in text) if lang == 'zh' else bool(re.search(r'\b' + re.escape(c) + r'\b', low))
            if hit:
                conn_c[c] += 1
                conn_donors[c].add(handle)
        sents = _sentences(text, lang)
        sent_sizes += [s for s in (_size(x, lang) for x in sents) if s >= 2]
        post_sizes.append(_size(text, lang))
        g = _opener_gram(text, lang)
        if g:
            openers[g] += 1
            opener_donors[g].add(handle)
        punct, tail = _closer(text, lang)
        end_punct[punct] += 1
        if tail:
            end_particle[tail] += 1
        if lang == 'zh':
            cjk_total += len(CJK.findall(text))
            for w in ZH_PARTICLES:
                particles[w] += text.count(w)
        for s in sents:
            sl = s.casefold()
            r = [m for m in (ZH_REASON if lang == 'zh' else EN_REASON) if m in (s if lang == 'zh' else sl)]
            i = [m for m in (ZH_IMPL if lang == 'zh' else EN_IMPL) if m in (s if lang == 'zh' else sl + ' ')]
            if r:
                reason_n += 1
                reason_c[r[0]] += 1
            if i:
                impl_n += 1
                impl_c[i[0]] += 1
    short_max, long_min = (80, 200) if lang == 'zh' else (25, 60)
    unit = 'CJK chars' if lang == 'zh' else 'words'
    prefer = (['判断句开门，数字后置', '短句/断行，少用研报连接词', '原因用一句有事实的话说清，不堆术语链']
              if lang == 'zh' else
              ['Lead with the call, then 1–2 numbers', 'Plain verbs over sell-side jargon',
               'Give the reason as a fact, skip empty contrast'])
    avoid = (['研报腔：链路往下推/每一环的议价权/基本面支撑套话', '信息罗列而无判断', '还早着呢等口癖收尾',
              '只为防质疑的对冲/免责句（当然也有可能…/不构成投资建议）']
             if lang == 'zh' else
             ['valuation-free optimism', 'Calling a strong chance / is a start',
              'Empty That said / door metaphor', 'supply-discipline check as filler',
              'hedge-only lines (of course it could also… / not financial advice)'])
    weights = getattr(persona, 'donor_weights', {}) or {}
    donors = collections.Counter(h for h, _ in rows)
    card = {
        'persona_id': persona.persona_id,
        'lang': lang,
        'basis': 'donor cluster observations' if n else 'Fiona Oct 5 default; donor posts missing',
        'cluster': (getattr(persona, 'raw', {}) or {}).get('donor_cluster'),
        'donors': {h: {'weight': weights.get(h), 'posts': donors.get(h, 0)} for h in weights},
        'posts': n,
        'method': (f'up to weight x {SAMPLE_TOTAL} recent originals per donor (min 20); sentences split on '
                   '。！？!?；/newlines (EN: . ! ? / newlines); openers = first 2 CJK chars / first word used by '
                   '>= 2 donors; catchphrases = 4-char / 3-word grams in >= 6% of one donor\'s posts, <= 1% of the others\''),
        'judgment_first_share': round(first_judgment / n, 3) if n else None,
        'short_fragment_lines_per_post': round(fragments / n, 2) if n else None,
        'sellside_jargon_post_share': round(jargon_hits / n, 3) if n else None,
        'connector_rates': {k: round(v / n, 3) for k, v in conn_c.most_common(8)} if n else {},
        'sentence_length': dict(_quantiles(sent_sizes), unit=unit) if sent_sizes else {},
        'post_length_mix': ({'unit': unit, 'median': _quantiles(post_sizes)['median'],
                             'short': round(sum(s < short_max for s in post_sizes) / n, 3),
                             'medium': round(sum(short_max <= s < long_min for s in post_sizes) / n, 3),
                             'long': round(sum(s >= long_min for s in post_sizes) / n, 3),
                             'bands': f'short < {short_max}, long >= {long_min} {unit}'} if n else {}),
        'openers': [{'gram': g, 'share': round(c / n, 3), 'donors': len(opener_donors[g])}
                    for g, c in openers.most_common(40) if len(opener_donors[g]) >= 2][:10] if n else [],
        'closers': ({'end_punct': {k: round(v / n, 3) for k, v in end_punct.most_common()},
                     **({'end_particle': {k: round(v / n, 3) for k, v in end_particle.most_common() if k != 'other'}}
                        if lang == 'zh' else {})} if n else {}),
        'connectives': {c: {'per_post': round(conn_c[c] / n, 3), 'donors': len(conn_donors[c])}
                        for c, _ in conn_c.most_common(14)} if n else {},
        **({'particles_per_1k_cjk': {w: round(particles[w] * 1000 / cjk_total, 2)
                                     for w, _ in particles.most_common(12)}} if lang == 'zh' and cjk_total else {}),
        'reason_markers': {m: round(c / reason_n, 3) for m, c in reason_c.most_common(8)} if reason_n else {},
        'implication_markers': {m: round(c / impl_n, 3) for m, c in impl_c.most_common(8)} if impl_n else {},
        'catchphrases': catchphrases(rows, lang) if n else {},
        'prefer': prefer,
        'avoid': avoid,
        'sample_ids': [str(p.get('id')) for p in posts[:12]],
        'guidance': GUIDANCE,
        **({'industry_constraints': INDUSTRY_CONSTRAINTS[lang]}
           if persona.persona_id in ('zh_industry', 'en_industry') else {}),
    }
    return card


def load_card(persona):
    path = CARDS_DIR / (persona.persona_id + '.json')
    try:
        card = json.loads(path.read_text())
    except (OSError, ValueError):
        card = build_card(persona)
    if persona.persona_id in ('zh_industry', 'en_industry'):
        card = dict(card)
        card.setdefault('industry_constraints', INDUSTRY_CONSTRAINTS[persona.lang])
    return card


def write_card(persona, posts_dir=None):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    card = build_card(persona, posts_dir=posts_dir)
    if persona.persona_id in ('zh_industry', 'en_industry'):
        card['industry_constraints'] = INDUSTRY_CONSTRAINTS[persona.lang]
    (CARDS_DIR / (persona.persona_id + '.json')).write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + '\n')
    return card


# ---------------- compose-time payload: real lines, rotated, never stored ----------------
_PROMO = re.compile(r'返佣|开户|邀请码|注册|抽奖|空投|福利|私信|进群|关注|点赞|转发|评论区|课程|社群|直播|报名|优惠|广告|'
                    r'giveaway|subscribe|sign up|link in bio|discount|promo code|join my|newsletter', re.I)
_FIN = re.compile(r'市场|美联储|央行|利率|降息|加息|通胀|数据|美债|债|股|估值|资金|仓位|涨|跌|经济|政策|需求|供给|芯片|公司|'
                  r'财报|营收|利润|产能|订单|币|美元|油|AI|fed|rates?|inflation|yield|market|stocks?|earnings|revenue|'
                  r'demand|supply|capex|bitcoin|dollar|bonds?|growth|margin', re.I)
_CRYPTO = re.compile(r'比特币|BTC|ETH|以太坊|币圈|链上|稳定币|山寨|空投|meme|MEME|OKB|OKX|Solana|bitcoin|crypto|ethereum|'
                     r'stablecoin|altcoin|defi\b|token', re.I)
# Example lines must not re-teach what other checks remove: banned connectives / templates, 研报腔, hedges.
_TEMPLATE = re.compile(r'意味着|说白了|说到底|本质上|不是[^，。]{1,12}[，,]?而是|仅供参考|投资建议|not (?:financial|investment) advice|'
                       r'of course|that said|time will tell', re.I)
_CACHE = {}


def _formal():
    from live.zh_register import FORMAL_RX, _TRAD
    return FORMAL_RX, _TRAD


_FORMAL, _TRAD = _formal()


def _rng(seed):
    return random.Random(int(sha256(str(seed).encode()).hexdigest()[:12], 16))


def _pools(persona, posts_dir=None):
    key = (persona.persona_id, tuple(sorted((getattr(persona, 'donor_weights', {}) or {}).items())), str(posts_dir or ''))
    if key in _CACHE:
        return _CACHE[key]
    lang = persona.lang
    crypto_ok = persona.persona_id.startswith('crypto_')

    def off_beat(text):   # crypto lines stay out of non-crypto accounts; Traditional out of Simplified ZH
        return (not crypto_ok and _CRYPTO.search(text)) or (lang == 'zh' and _TRAD.search(text))
    reasons, impls, anchors = [], [], []
    seen = set()
    for handle, p in cluster_posts(persona, posts_dir):
        text = p['text']
        if _PROMO.search(text):
            continue
        size = _size(text, lang)
        lo, hi = (60, 220) if lang == 'zh' else (25, 80)
        if off_beat(text):
            continue
        if lo <= size <= hi and _FIN.search(text) and not _UNSAFE.search(text) and not _SELF.search(text) \
                and len(_FORMAL.findall(text)) <= 1:
            anchors.append({'handle': handle, 'id': str(p.get('id')), 'text': text})
        for s in _sentences(text, lang):
            n = _size(s, lang)
            if not ((8 <= n <= 40) if lang == 'zh' else (6 <= n <= 30)) or _UNSAFE.search(s) or s in seen:
                continue
            if not _FIN.search(s) or _FORMAL.search(s) or _TEMPLATE.search(s) or _SELF.search(s):
                continue
            sl = s.casefold()
            if any(m in (s if lang == 'zh' else sl) for m in (ZH_REASON[:8] if lang == 'zh' else EN_REASON)):
                reasons.append({'handle': handle, 'text': s})
                seen.add(s)
            elif any(m in (s if lang == 'zh' else sl + ' ') for m in (ZH_IMPL[:9] if lang == 'zh' else EN_IMPL)):
                impls.append({'handle': handle, 'text': s})
                seen.add(s)
    _CACHE[key] = (reasons, impls, anchors)
    return _CACHE[key]


def _rotate(pool, seed, k, weights):
    """k items from distinct donors, donor order drawn by weight from the seed."""
    if not pool:
        return []
    rng = _rng(seed)
    by = collections.defaultdict(list)
    for e in pool:
        by[e['handle']].append(e)
    handles = sorted(by)
    order = []
    while handles and len(order) < k:
        w = [max(weights.get(h, 0.05), 0.05) for h in handles]
        h = rng.choices(handles, weights=w)[0]
        order.append(h)
        handles.remove(h)
    return [rng.choice(by[h]) for h in order]


def used_catchphrases(card, bodies, extra=()):
    phrases = [p for ps in (card.get('catchphrases') or {}).values() for p in ps] + list(extra)
    used = []
    for b in bodies or ():
        low = str(b or '').casefold()
        for p in phrases:
            if p.casefold() in low and p not in used:
                used.append(p)
    return used


def payload_card(persona, seed='', recent_bodies=(), posts_dir=None, extra_phrases=()):
    """language_habits block for the compose payload: card aggregates + rotating real examples."""
    card = dict(load_card(persona))
    weights = getattr(persona, 'donor_weights', {}) or {}
    reasons, impls, anchors = _pools(persona, posts_dir)
    out = {k: v for k, v in card.items() if k not in ('sample_ids', 'method', 'donors', 'catchphrases')}
    out['reason_examples'] = [{'handle': e['handle'], 'text': e['text']} for e in _rotate(reasons, str(seed) + ':r', 3, weights)]
    out['implication_examples'] = [{'handle': e['handle'], 'text': e['text']} for e in _rotate(impls, str(seed) + ':i', 3, weights)]
    out['anchor_posts'] = [{'handle': e['handle'], 'text': e['text']} for e in _rotate(anchors, str(seed) + ':a', 2, weights)]
    phrases = [p for ps in (card.get('catchphrases') or {}).values() for p in ps]
    recent_used = used_catchphrases(card, list(recent_bodies)[-(CATCHPHRASE_WINDOW - 1):], extra_phrases)
    out['catchphrase_cap'] = {
        'phrases': phrases,
        'used_recently': recent_used,
        'rule': (f'这些是个别 donor 的口头禅：每篇最多一个，最近 {CATCHPHRASE_WINDOW} 篇里同一个最多出现一次；used_recently 里的这篇不用。'
                 if persona.lang == 'zh' else
                 f'Single-donor catchphrases: at most one per post, each at most once in {CATCHPHRASE_WINDOW} posts; '
                 'skip anything in used_recently.')}
    out['use'] = ('Imitate how these real accounts phrase things: sentence_length, openers, closers, connectives, '
                  'particles, reason_markers / implication_markers and the rotating examples. Style only - never copy '
                  'a sentence, a fact, a number or an opinion from the examples or anchor_posts.')
    return out


CATCHPHRASE_WINDOW = 5   # this draft + the persona's previous 4 (same window as connective_repeat)


def catchphrase_findings(body, persona, recent_bodies=(), extra_phrases=()):
    """SOFT catchphrase_repeat: a single donor's catchphrase used twice in this draft, or used here and in one of
    the persona's previous CATCHPHRASE_WINDOW-1 drafts, or more than one donor catchphrase in one draft."""
    if not body:
        return []
    card = load_card(persona)
    phrases = [p for ps in (card.get('catchphrases') or {}).values() for p in ps] + list(extra_phrases)
    low = body.casefold()
    hits = [p for p in dict.fromkeys(phrases) if p.casefold() in low]
    if not hits:
        return []
    twice = [p for p in hits if low.count(p.casefold()) > 1]
    prior = set(used_catchphrases(card, list(recent_bodies)[-(CATCHPHRASE_WINDOW - 1):], extra_phrases))
    again = [p for p in hits if p in prior and p not in twice]
    parts = []
    if twice:
        parts.append('same catchphrase twice: ' + ', '.join(twice))
    if again:
        parts.append(f'used again within {CATCHPHRASE_WINDOW} drafts: ' + ', '.join(again))
    if len(hits) > 1 and not twice and not again:
        parts.append('more than one donor catchphrase: ' + ', '.join(hits))
    return [{'code': 'catchphrase_repeat', 'detail': '; '.join(parts)}] if parts else []
