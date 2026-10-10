"""Per-account donor rates for naturalness post-processing (nat3, Oct 10).

Measures from each account's donor cluster (roster acct_<id> donors, 20 most recent originals
per donor, same language) and stores only aggregates — no donor text — in
live/donors/donor_rates.json.

Rates computed per account:
  first_person, hedge, intensifier (zh/en), emoji, mention, ticker ($), particles (zh),
  slang (zh/en), lowercase_start / all_lower (en), short_post (zh <40 chars / en <12 words),
  precise_number, last_line_period, formula_closer, top5_emoji (list), shape_mix (dict).
  Length quantiles: p10 p25 p50 p75 p90.

Fallback: when an account has <30 donor posts, all rates use language-level averages computed
from the full set of accounts that cleared the floor.

FD_DONOR_RATES: path override (default live/donors/donor_rates.json).
"""
from __future__ import annotations

import collections
import json
import os
import re
import statistics as st
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JSON = ROOT / 'donors' / 'donor_rates.json'
POSTS_DIR = ROOT / 'donors' / 'posts'

MIN_POSTS = 30          # floor for per-account rates; below -> language fallback
DONOR_K = 20            # most recent originals per donor

_URL = re.compile(r'https?://\S+')
_CJK = re.compile(r'[一-鿿]')
_EMO = re.compile(r'[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]')

# intensifiers zh / en  (same lists as nat1010/metrics.py)
_INTENS_ZH = re.compile(r'简直|直接|根本|绝对|彻底|硬生生|死死|狠狠|疯狂|赤裸裸|纯粹|实打实|离谱|砸')
_INTENS_EN = re.compile(r'\b(absolute(?:ly)?|completely|entirely|massive(?:ly)?|violent(?:ly)?|'
                        r'aggressive(?:ly)?|brutal|wild(?:ly)?|insane|relentless(?:ly)?|'
                        r'severely|strictly|fundamental(?:ly)?|structural(?:ly)?|clearly|simply)\b', re.I)

# hedges
_HEDGE_ZH = re.compile(r'或许|可能|也许|大概|不一定|未必|恐怕|我觉得|我看|感觉|好像|应该')
_HEDGE_EN = re.compile(r'\b(might|may|could|perhaps|likely|arguably|probably|seems?|I think|I guess|'
                        r'ngl|imo|imho|tbh)\b', re.I)

# first person
_FP_ZH = re.compile(r'我|俺|咱')
_FP_EN = re.compile(r"\b(I|I'm|I've|I'd|I'll|my|me|mine)\b")

# particles zh
_PARTICLE_ZH = re.compile(r'[吧啊呢嘛咯啦哎呀哈嘿呗哦嗯]')

# slang
_SLANG_ZH = re.compile(r'大饼|二饼|姨太|\bU\b|撸毛|梭哈|上车|下车|韭菜|狗庄|拉盘|砸盘|土狗|抄底|接盘|冲了')
_SLANG_EN = re.compile(r"\b(gm|ngl|lol|lmao|imo|imho|tbh|fr\b|wagmi|ngmi|degen|cope|rekt|based|"
                        r"y'all|gonna|wanna|kinda|idk|rn\b|lfg|cooked|ape|bags?|jeets?|wen|haha|smh)\b", re.I)

# ticker / mention
_TICKER = re.compile(r'\$[A-Za-z]{2,10}\b')
_MENTION = re.compile(r'@[A-Za-z0-9_]{1,50}\b')

# precise number (>= 2 decimals, 1,234,567 style, x.0m, 4.872亿)
_PRECISE = re.compile(r'\d{1,3}(?:,\d{3}){2,}|\d+\.\d{2,}|\d+\.0\s?[mbkMBK%]|\d+\.\d+亿|\d{7,}')

# formula closer
_FORMULA_ZH = re.compile(r'接下来盯|关键看|后续要盯|值得关注|拭目以待|后续关注|盯好')
_FORMULA_EN = re.compile(r'\b(Watch\s+\w|Expect\s+\w|keep an eye|time will tell|The question is|'
                          r'worth watching)\b', re.I)

# line-end period
_CLOSERS = re.compile(r"""[)）」』""\''》】]\s*$""")
_PERIOD_END = re.compile(r'[。．.]\s*$')

# shape classifier (cheap regex, mirrors shapes_cls logic)
def _shape(text, lang):
    t = _URL.sub('', str(text or '')).strip()
    lines = [l for l in t.split('\n') if l.strip()]
    n = len(_CJK.findall(t)) if lang == 'zh' else len(t.split())
    if not lines:
        return 'other'
    if t.endswith('?') or t.endswith('？'):
        return 'question'
    if re.search(r'^\s*(?:\d+[.、)]|[-•·])\s', t, re.M) and len(lines) >= 3:
        return 'list'
    short_th = 40 if lang == 'zh' else 15
    if len(lines) == 1 or n <= short_th:
        if _FP_ZH.search(lines[0]) if lang == 'zh' else _FP_EN.search(lines[0]):
            return 'personal'
        return 'one_liner'
    if _FP_ZH.search(lines[0]) if lang == 'zh' else _FP_EN.search(lines[0]):
        return 'personal'
    return 'argument'


def _clean(text):
    return _URL.sub('', str(text or '')).strip()


def _lang_ok(text, lang):
    cjk = len(_CJK.findall(text))
    if lang == 'zh':
        return cjk >= 5
    return cjk == 0 and len(text) >= 20


def _is_original(post):
    return (bool(post.get('text')) and not post.get('rt')
            and not post.get('reply') and not post.get('reply_to')
            and not post.get('pinned'))


def _load_posts(handle):
    """Load up to DONOR_K recent originals for a donor handle."""
    p = POSTS_DIR / f'{handle.lower()}.jsonl'
    if not p.exists():
        # try case-insensitive by scanning
        if POSTS_DIR.exists():
            for f in POSTS_DIR.iterdir():
                if f.stem.lower() == handle.lower():
                    p = f
                    break
    if not p.exists():
        return []
    posts = []
    for raw in p.read_text(errors='replace').splitlines():
        try:
            posts.append(json.loads(raw))
        except ValueError:
            pass
    return posts


def _feats(text, lang):
    t = _clean(text)
    lines = [l for l in t.split('\n') if l.strip()]
    n = len(_CJK.findall(t)) if lang == 'zh' else len(t.split())
    feat = {
        'len': n,
        'first_person': 1 if (_FP_ZH if lang == 'zh' else _FP_EN).search(t) else 0,
        'hedge': 1 if (_HEDGE_ZH if lang == 'zh' else _HEDGE_EN).search(t) else 0,
        'intensifier': 1 if (_INTENS_ZH if lang == 'zh' else _INTENS_EN).search(t) else 0,
        'intensifier_count': len((_INTENS_ZH if lang == 'zh' else _INTENS_EN).findall(t)),
        'emoji': 1 if _EMO.search(t) else 0,
        'emoji_chars': _EMO.findall(t),
        'mention': 1 if _MENTION.search(t) else 0,
        'ticker': 1 if _TICKER.search(t) else 0,
        'slang': 1 if (_SLANG_ZH if lang == 'zh' else _SLANG_EN).search(t) else 0,
        'precise_number': 1 if _PRECISE.search(t) else 0,
        'formula_closer': 1 if (_FORMULA_ZH if lang == 'zh' else _FORMULA_EN).search(t) else 0,
        'shape': _shape(t, lang),
    }
    if lang == 'zh':
        feat['particle'] = 1 if _PARTICLE_ZH.search(t) else 0
        feat['short_post'] = 1 if n < 40 else 0
    else:
        feat['lowercase_start'] = 1 if t[:1].islower() else 0
        feat['all_lower'] = 1 if (t == t.lower() and re.search(r'[a-z]', t)) else 0
        feat['short_post'] = 1 if n < 12 else 0
    if lines:
        last = _CLOSERS.sub('', lines[-1]).rstrip()
        feat['last_line_period'] = 1 if _PERIOD_END.search(last) else 0
    else:
        feat['last_line_period'] = 0
    return feat


def _account_rates(persona, lang):
    """Compute rates dict for one account from its donor cluster."""
    from live import posting_habits as ph
    weights = ph.capped_weights(persona.donor_weights or {})
    all_posts = []
    for handle, _w in weights.items():
        raw = _load_posts(handle)
        posts = [p for p in raw if _is_original(p)]
        posts.sort(key=lambda p: str(p.get('id', '')), reverse=True)
        posts = posts[:DONOR_K]
        for p in posts:
            t = _clean(p.get('text', ''))
            if _lang_ok(t, lang):
                all_posts.append(t)

    if not all_posts:
        return None, 0

    feats = [_feats(t, lang) for t in all_posts]
    n = len(feats)

    def rate(key):
        return round(sum(f.get(key, 0) for f in feats) / n, 3)

    lengths = sorted(f['len'] for f in feats)

    def pct(q):
        i = int(q / 100 * (n - 1))
        return lengths[i]

    # top-5 emoji
    emoji_counter = collections.Counter()
    for f in feats:
        emoji_counter.update(f['emoji_chars'])
    top5 = [e for e, _ in emoji_counter.most_common(5)]

    # shape mix
    shape_counter = collections.Counter(f['shape'] for f in feats)
    total_shapes = sum(shape_counter.values())
    shape_mix = {s: round(v / total_shapes, 3) for s, v in shape_counter.most_common()}

    rates = {
        'n': n,
        'lang': lang,
        'first_person': rate('first_person'),
        'hedge': rate('hedge'),
        'intensifier': rate('intensifier'),
        'emoji': rate('emoji'),
        'mention': rate('mention'),
        'ticker': rate('ticker'),
        'slang': rate('slang'),
        'precise_number': rate('precise_number'),
        'last_line_period': rate('last_line_period'),
        'formula_closer': rate('formula_closer'),
        'short_post': rate('short_post'),
        'top5_emoji': top5,
        'shape_mix': shape_mix,
        'length_p10': pct(10),
        'length_p25': pct(25),
        'length_p50': pct(50),
        'length_p75': pct(75),
        'length_p90': pct(90),
    }
    if lang == 'zh':
        rates['particle'] = rate('particle')
    else:
        rates['lowercase_start'] = rate('lowercase_start')
        rates['all_lower'] = rate('all_lower')
    return rates, n


def build_all(personas=None, posts_dir=None):
    """Build and return the full donor_rates dict. Does NOT write to disk."""
    global POSTS_DIR
    if posts_dir:
        POSTS_DIR = Path(posts_dir)

    from live import registry
    if personas is None:
        personas = registry.load_personas()
    items = personas.values() if isinstance(personas, dict) else list(personas)

    per_account = {}
    lang_pools = {'zh': [], 'en': []}

    for p in sorted(items, key=lambda x: x.persona_id):
        lang = p.lang
        rates, n = _account_rates(p, lang)
        if rates is not None and n > 0:
            per_account[p.persona_id] = rates
            if n >= MIN_POSTS:
                lang_pools[lang].append(rates)

    # language-level averages for fallback
    fallback = {}
    for lang, pool in lang_pools.items():
        if not pool:
            continue
        keys = set().union(*[r.keys() for r in pool]) - {'n', 'lang', 'top5_emoji', 'shape_mix',
                                                          'length_p10', 'length_p25', 'length_p50',
                                                          'length_p75', 'length_p90'}
        avg = {k: round(sum(r[k] for r in pool if k in r) / len([r for r in pool if k in r]), 3)
               for k in keys}
        # length quantiles: average of each
        for q in ('length_p10', 'length_p25', 'length_p50', 'length_p75', 'length_p90'):
            vals = [r[q] for r in pool if q in r]
            if vals:
                avg[q] = round(sum(vals) / len(vals), 1)
        # top5_emoji: union of all top5s, keep top-5 by frequency
        emo_all = collections.Counter()
        for r in pool:
            emo_all.update(r.get('top5_emoji') or [])
        avg['top5_emoji'] = [e for e, _ in emo_all.most_common(5)]
        # shape_mix: average
        shapes_all = set().union(*[set(r.get('shape_mix', {}).keys()) for r in pool])
        avg['shape_mix'] = {s: round(sum(r.get('shape_mix', {}).get(s, 0) for r in pool) / len(pool), 3)
                            for s in shapes_all}
        avg['lang'] = lang
        avg['n'] = int(sum(r['n'] for r in pool) / max(1, len(pool)))
        fallback[lang] = avg

    # apply fallback for accounts below MIN_POSTS
    for pid, r in per_account.items():
        if r['n'] < MIN_POSTS and r['lang'] in fallback:
            fb = dict(fallback[r['lang']])
            fb['fallback'] = True
            fb['actual_n'] = r['n']
            per_account[pid] = fb

    return {'version': '1', 'built_by': 'live/donor_rates.py (nat3 2026-10-10)',
            'method': ('originals only (no RT/reply/pinned), same language, 20 most recent per donor, '
                       'weighted cluster sample. Fallback to language average when account has <30 posts. '
                       'Aggregates only — no donor text.'),
            'use': 'naturalness post-processor rates; per-account only',
            'accounts': per_account,
            'fallback': fallback}


_CACHE = {}


def load(path=None):
    """Load (and cache by mtime) the donor_rates.json."""
    p = Path(os.environ.get('FD_DONOR_RATES') or path or JSON)
    key = (str(p), p.stat().st_mtime if p.exists() else 0)
    if _CACHE.get('key') != key:
        try:
            _CACHE.update(key=key, data=json.loads(p.read_text()))
        except (OSError, ValueError):
            _CACHE.update(key=key, data={})
    return _CACHE.get('data') or {}


def account_rates(persona_id, path=None):
    """The rates dict for one account, or None if not found."""
    return load(path).get('accounts', {}).get(persona_id)


def fallback_rates(lang, path=None):
    return load(path).get('fallback', {}).get(lang)


if __name__ == '__main__':
    import sys
    data = build_all()
    out = Path(os.environ.get('FD_DONOR_RATES') or JSON)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    print(f'accounts={len(data["accounts"])} fallback_langs={list(data["fallback"].keys())}',
          file=sys.stderr)
