"""Engagement layer: ride big accounts' traffic with quote / reply drafts (Fiona, Oct 8 2026).

Fiona's feedback: in the growth stage the smartest move is to reply to (or quote) big accounts' newest high-traffic
posts. On 10-08 墨川.eth (crypto_macro_zh) had quote drafts on @off_thetarget (9 likes, 1.3k views, 27h old when it
went out) and @lianyanshe (8 likes, 4.0k views, ~22h old at its slot): the quote path ranked X sources by freshness
only and the stored X source carried no likes / views (ContentStore dropped x_metrics), so "no metrics" = "hot".

FD_ENGAGE (default 1; 0 = the old cold_start / post_mode behaviour). Config: live/engagement.json (DEFAULTS below).

1. Target scoring (`assess`): an X post is a quote / reply target only when
   - the author has >= min_followers (50k), OR the post shows velocity (<= velocity_window_h old at capture and
     >= velocity_likes_per_h likes/h or >= velocity_views_per_h views/h);
   - it is not older than reply_max_age_h (6h, reply) / quote_max_age_h (12h, quote) AT THE SCHEDULED POST TIME;
   - it has >= min_likes (100) likes, unless the author is huge (>= huge_followers); velocity only waives the follower floor;
   - metrics are known (no metrics = not a target, unless the author is huge); not one of our own handles.
   Score = followers + likes + views + reposts/replies (log scale) + velocity bonus - age + own-lane / own-language
   bonus. Replies also need the account's own language.
2. Mode mix (`plan_day`): an account in its first cold_days (30) gets per day 1 reply + 1 quote (or 2 replies) on
   the best targets in its picks instead of standalone posts; other picks stay standalone (never quote a target that
   fails the scoring). Global greedy by score: no two of our accounts take the same target post; one engagement per
   big author per account per day; earlier inbox rows of the day count.
3. Timing (`next_slot`): an engagement draft gets the earliest slot after selection inside 08:00-22:59 Beijing,
   >= min_gap_min (30) from the account's other slots, and only while the target is still inside its age window.
4. Safety: drafts only (publishing stays manual); `findings` adds HARD codes for engagement drafts on top of the
   usual risk rules: engage_generic (great post / 说得好 / 学到了 ...), engage_too_long (reply > 2 sentences),
   engage_mentions (> 1 @mention); engage_no_payload (no number / counter-point / concrete observation) is SOFT but
   gets compose's one targeted rewrite.
5. Targets log (`write_log`): live/store/engagement/<day>.json - chosen target, author followers, likes / views at
   selection, age, score, why chosen, and the accounts that passed over it. The ops dashboard shows it.
6. Discovery (`subscriptions`, `prefilter`): big same-language donors of each account's clusters (live/donors/
   roster.json: handle + followers only, >= min_followers, not promo-heavy) join the X intake as ENGAGE sources,
   fetched by the same RapidAPI batched search as the breadth sources (own daily call cap); only posts that already
   pass the scoring at capture time go on to extraction.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, time as _time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'live' / 'engagement.json'
ROSTER = ROOT / 'live' / 'donors' / 'roster.json'
BJT = ZoneInfo('Asia/Shanghai')
LONDON = ZoneInfo('Europe/London')
VERSION = 'engage-v1'

DEFAULTS = {
    'min_followers': 50000, 'huge_followers': 300000, 'min_likes': 100,
    'velocity_window_h': 3, 'velocity_likes_per_h': 40, 'velocity_views_per_h': 8000,
    'reply_max_age_h': 6, 'quote_max_age_h': 12,
    'cold_days': 30, 'quotes_per_day': 1, 'replies_per_day': 1, 'max_replies_per_day': 2,
    'window_bjt': ['08:00', '22:59'], 'min_gap_min': 30, 'lead_min': 10,
    'other_language_penalty': 1.5, 'lane_bonus': 0.5,
    'targets_per_account': 8, 'engage_daily_call_cap': 16, 'engage_pages_per_batch': 1,
    'engage_posts_per_handle': 2,
    # Oct 9 (perf / pool review): a huge author still needs some traction (10-09: @fxtrader 406k, 7 likes was picked);
    # the watchlist ranks donors by their typical likes (local donor posts) and drops known low-traffic ones; the
    # batched search only returns posts that already have search_min_faves likes (0 = no filter).
    'huge_min_likes': 20, 'min_median_likes': 20, 'search_min_faves': 30,
    # Oct 9 (Fiona, perf review): slot rule - every account (not only cold ones) gets one engagement slot a day next
    # to its one standalone post; cold-start quotas still cap the modes.
    'engage_slots_per_day': 1,
}
HARD_CODES = frozenset({'engage_generic', 'engage_too_long', 'engage_mentions'})
SOFT_CODES = frozenset({'engage_no_payload'})
REPAIR_TRIGGER = frozenset({'engage_no_payload'})
FIXES = {
    'engage_generic': ('This is a reply / quote under a big account: drop the generic praise or agreement '
                       '(great post / interesting take / 说得好 / 学到了 / 感谢分享); say the one thing the post is missing.'),
    'engage_too_long': 'A reply is at most 2 sentences: keep the number or counter-point, cut the rest.',
    'engage_mentions': 'At most one @mention (X adds the replied-to handle itself); remove the others.',
    'engage_no_payload': ('Add one concrete thing the target post does not say: a number from the units, a '
                          'counter-point, or a specific observation - not agreement.'),
}
PROMPT_RULE = {
    'reply': ('This draft is a REPLY under {who}\'s post (the source). At most 2 sentences. Add exactly one thing the '
              'post does not say: a number from the units, a counter-point, or a concrete observation. No praise, '
              'thanks or agreement filler ("great post", "说得好", "学到了"), no @mentions (X adds the handle), no '
              'links, no hashtags, no buy / sell call.'),
    'quote': ('This draft QUOTES {who}\'s post (the source, shown as the quoted card). 1-3 short lines that add a '
              'number from the units, a counter-point or a concrete observation; do not restate the post. No praise '
              'filler, at most one @mention, no links, no buy / sell call.'),
}
_CFG = None
_ROSTER = None


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_ENGAGE', '1') != '0'


def slot_rule(env=None):
    """Oct 9: 1 standalone + 1 engagement slot per account and day (FD_SLOT_RULE=0: the old 2-standalone mix)."""
    e = env if env is not None else os.environ
    return enabled(e) and e.get('FD_SLOT_RULE', '1') != '0'


def fetch_enabled(env=None):
    e = env if env is not None else os.environ
    return enabled(e) and e.get('FD_ENGAGE_FETCH', '1') != '0'


def config():
    global _CFG
    if _CFG is None:
        try:
            raw = json.loads(CONFIG.read_text())
        except (OSError, ValueError):
            raw = {}
        _CFG = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    return _CFG


def _ts(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _int(v):
    try:
        return None if v is None or v == '' else int(v)
    except (TypeError, ValueError):
        return None


def roster_followers():
    """{handle_lower: followers} from the donor roster (handles + counts only)."""
    global _ROSTER
    if _ROSTER is None:
        try:
            donors = json.loads(ROSTER.read_text()).get('donors') or {}
            _ROSTER = {str(d.get('handle') or k).lower(): int(d.get('followers') or 0)
                       for k, d in (donors.items() if isinstance(donors, dict) else enumerate(donors))}
        except (OSError, ValueError, AttributeError):
            _ROSTER = {}
    return _ROSTER


def metrics(source):
    """Normalised x_metrics of a stored X source (likes / views / reposts / replies / followers / capture time)."""
    m = (source or {}).get('x_metrics') or {}
    return {'likes': _int(m.get('likes')), 'views': _int(m.get('views')), 'reposts': _int(m.get('reposts')),
            'replies': _int(m.get('replies')), 'followers': _int(m.get('followers')), 'at': _ts(m.get('at'))}


def _target(source):
    from live.post_mode import x_target
    return x_target(source)


def followers_of(handle, source=None):
    f = metrics(source)['followers'] if source else None
    return f if f is not None else roster_followers().get(str(handle or '').lower().lstrip('@'))


def assess(source, at, *, account_lang=None, on_lane=False, own_handles=(), cfg=None):
    """Score one X post as a quote / reply target for a draft posted at `at`. Pure; never raises on bad input."""
    cfg = cfg or config()
    out = {'quote_ok': False, 'reply_ok': False, 'score': 0.0, 'reject': None}
    t = _target(source)
    if not t:
        return dict(out, reject='not_x')
    url, handle, pid = t
    out.update(url=url, handle=handle, post_id=pid)
    if handle.lower() in {str(h).lower().lstrip('@') for h in own_handles if h}:
        return dict(out, reject='own_account')
    pub, at = _ts((source or {}).get('published_at')), _ts(at)
    if pub is None or at is None:
        return dict(out, reject='no_time')
    m = metrics(source)
    followers = followers_of(handle, source)
    age = (at - pub).total_seconds() / 3600
    cap_age = max(0.25, ((m['at'] - pub).total_seconds() / 3600) if m['at'] and m['at'] >= pub else max(age, 0.25))
    likes, views = m['likes'], m['views']
    have = likes is not None or views is not None
    lph = (likes or 0) / cap_age
    vph = (views or 0) / cap_age
    hot = have and cap_age <= cfg['velocity_window_h'] and (lph >= cfg['velocity_likes_per_h']
                                                            or vph >= cfg['velocity_views_per_h'])
    big = (followers or 0) >= cfg['min_followers']
    huge = (followers or 0) >= cfg['huge_followers']
    lang = (source or {}).get('source_language')
    lang_match = not account_lang or not lang or str(lang)[:2] == str(account_lang)[:2]
    out.update(followers=followers, likes=likes, views=views, reposts=m['reposts'], replies=m['replies'],
               age_h=round(age, 2), likes_per_h=round(lph, 1), views_per_h=round(vph, 1), hot=bool(hot),
               big=big, huge=huge, lang_match=lang_match)
    reject = None
    if age < -0.05:
        reject = 'not_yet_posted'
    elif age > cfg['quote_max_age_h']:
        reject = 'too_old'
    elif not have and not huge:
        reject = 'no_metrics'
    elif not (big or hot):
        reject = 'small_author'
    elif have and (likes or 0) < cfg['min_likes'] and not huge:   # velocity waives the follower floor, not this
        reject = 'low_engagement'
    elif have and huge and likes is not None and likes < cfg['huge_min_likes']:   # Oct 9: 7-like posts are pointless
        reject = 'low_engagement'
    score = (math.log10(max(followers or 1, 1)) + 1.5 * math.log10(1 + (likes or 0)) + 0.5 * math.log10(1 + (views or 0))
             + 0.5 * math.log10(1 + (m['reposts'] or 0) + (m['replies'] or 0)) + (1.0 if hot else 0.0)
             - 0.15 * max(age, 0) + (cfg['lane_bonus'] if on_lane else 0.0)
             - (0.0 if lang_match else cfg['other_language_penalty']))
    out.update(score=round(score, 3), reject=reject, quote_ok=reject is None,
               reply_ok=reject is None and age <= cfg['reply_max_age_h'] and lang_match)
    out['why'] = why(out)
    return out


def _k(n):
    return '-' if n is None else f'{n / 1000:.1f}k' if n >= 1000 else str(n)


def why(a):
    """Short human line: '@x 82.6k粉 · 8赞 · 4.0k阅 · 22.5h' + the deciding signal."""
    bits = [f"@{a.get('handle')}", f"{_k(a.get('followers'))} followers", f"{_k(a.get('likes'))} likes",
            f"{_k(a.get('views'))} views", f"{a.get('age_h')}h old"]
    sig = ['huge author' if a.get('huge') else 'big author' if a.get('big') else '',
           f"velocity {a.get('likes_per_h')} likes/h" if a.get('hot') else '']
    return ' · '.join(bits + [x for x in sig if x] + ([f"rejected: {a['reject']}"] if a.get('reject') else []))


# ------------------------------------------------------------------ cold window + timing

def is_cold(account_id, day, cfg=None):
    """Engagement mix applies in the account's first cold_days (first day from live/cold_start.json)."""
    from live import cold_start
    cfg = cfg or config()
    day = date.fromisoformat(day) if isinstance(day, str) else day
    start = cold_start.first_day(account_id)
    return start is None or day < start + timedelta(days=int(cfg['cold_days']))


def window(day, cfg=None):
    cfg = cfg or config()
    day = date.fromisoformat(day) if isinstance(day, str) else day
    (h1, m1), (h2, m2) = (map(int, s.split(':')) for s in cfg['window_bjt'])
    return (datetime.combine(day, _time(h1, m1), tzinfo=BJT), datetime.combine(day, _time(h2, m2), tzinfo=BJT))


def next_slot(day, after, taken=(), cfg=None, not_after=None):
    """Earliest Beijing slot >= `after` (+lead) inside the day's window, >= min_gap_min from every `taken` time,
    and <= not_after when given (the target's age limit). None when nothing fits."""
    cfg = cfg or config()
    lo, hi = window(day, cfg)
    after = _ts(after) or lo
    t = max(lo, after + timedelta(minutes=cfg['lead_min']))
    t = t.astimezone(BJT).replace(second=0, microsecond=0)
    gap = timedelta(minutes=cfg['min_gap_min'])
    taken = [_ts(x) for x in taken if _ts(x)]
    limit = min(hi, not_after) if not_after else hi
    while t <= limit:
        clash = [x for x in taken if abs((t - x).total_seconds()) < gap.total_seconds()]
        if not clash:
            return t
        t = max(clash) + gap
    return None


# ------------------------------------------------------------------ planning

class DayState:
    """What earlier runs of the day already used: target post ids (any account), (account, author) pairs and the
    per-account quote / reply counts."""

    def __init__(self):
        self.targets, self.authors, self.used, self.ready = {}, set(), {}, {}

    @classmethod
    def from_rows(cls, rows):
        st = cls()
        for r in rows or ():
            e = r.get('engagement') or {}
            mode = e.get('mode') or (r.get('post_mode') if r.get('post_mode') in ('quote', 'reply') else None)
            if not mode or r.get('superseded'):
                continue
            url = e.get('url') or r.get('quote_target_url') or r.get('reply_to_url')
            t = _target({'url': url})
            if not t:
                continue
            st.take(r.get('account_id'), t[2], t[1], mode)
            if r.get('draft_status') == 'draft_ready' and not r.get('held'):   # slot rule: ready ones fill the slot
                st.ready[r.get('account_id')] = st.ready.get(r.get('account_id'), 0) + 1
        return st

    def take(self, account, post_id, handle, mode):
        self.targets[str(post_id)] = account
        self.authors.add((account, str(handle).lower()))
        u = self.used.setdefault(account, {'quote': 0, 'reply': 0})
        u[mode] = u.get(mode, 0) + 1


def quotas(account, day, state, cfg=None):
    cfg = cfg or config()
    u = state.used.get(account) or {}
    q = max(0, int(cfg['quotes_per_day']) - u.get('quote', 0))
    r = max(0, int(cfg['replies_per_day']) - u.get('reply', 0))
    return q, r, max(0, int(cfg['max_replies_per_day']) - u.get('reply', 0))


def plan_day(cands, *, day, ref, state=None, taken=None, own_handles=(), cfg=None, langs=None, cold=None):
    """Assign engagement modes for the day's picks.

    cands: {account: [{'key', 'source', 'on_lane'?}]} (the picks, in pick order). taken: {account: [times]}.
    Returns ({account: {key: decision}}, [log entries]); decision = {'mode': 'reply'|'quote'|None, 'slot': datetime
    | None, 'assess': {...}, 'why'}. Reply first to the best reply-eligible target, then quote the best remaining
    quote-eligible one, then a second reply when no quote target is left (Fiona: 1 quote + 1 reply, or 2 replies).
    Global greedy by score across accounts."""
    cfg = cfg or config()
    state = state or DayState()
    taken = {a: list(v) for a, v in (taken or {}).items()}
    langs = langs or {}
    slots = int(cfg['engage_slots_per_day']) if slot_rule() else None
    if slots is not None:   # slot rule: every account has its (one) engagement slot, cold-start or not
        cold = {a: True for a in cands}
    elif cold is None:
        cold = {a: is_cold(a, day, cfg) for a in cands}
    out = {a: {} for a in cands}
    first = {a: next_slot(day, ref, taken.get(a, ()), cfg) for a in cands}
    scored = []
    for a, items in cands.items():
        for c in items:
            at = first[a] or window(day, cfg)[1]
            s = assess(c['source'], at, account_lang=langs.get(a), on_lane=c.get('on_lane', False),
                       own_handles=own_handles, cfg=cfg)
            out[a][c['key']] = {'mode': None, 'slot': None, 'assess': s,
                                'why': 'not cold-start' if not cold.get(a) else s.get('why') or s.get('reject')}
            if cold.get(a) and s['quote_ok']:
                scored.append((s['score'], a, c))
    scored.sort(key=lambda x: (-x[0], x[1], x[2]['key']))
    left = {a: list(quotas(a, day, state, cfg)) for a in cands}
    slot_left = {a: (slots - state.ready.get(a, 0)) if slots is not None else 99 for a in cands}
    for phase in ('reply', 'quote', 'reply2'):
        for score, a, c in scored:
            d = out[a][c['key']]
            if d['mode']:
                continue
            s = d['assess']
            pid, handle = s.get('post_id'), str(s.get('handle')).lower()
            if pid in state.targets or (a, handle) in state.authors:
                continue
            q, r, rmax = left[a]
            if slot_left[a] <= 0:   # slot rule: the account's engagement slot is already filled today
                continue
            mode = ('reply' if phase == 'reply' and r > 0 else 'quote' if phase == 'quote' and q > 0 else
                    'reply' if phase == 'reply2' and rmax > 0 and q == 0 and not any(
                        x['mode'] == 'quote' for x in out[a].values()) else None)
            if mode is None or (mode == 'reply' and not s['reply_ok']):
                continue
            limit = _ts(c['source'].get('published_at')) + timedelta(
                hours=cfg['reply_max_age_h' if mode == 'reply' else 'quote_max_age_h'])
            slot = next_slot(day, ref, taken.get(a, ()), cfg, not_after=limit)
            if slot is None:
                continue
            s2 = assess(c['source'], slot, account_lang=langs.get(a), on_lane=c.get('on_lane', False),
                        own_handles=own_handles, cfg=cfg)
            if not (s2['reply_ok'] if mode == 'reply' else s2['quote_ok']):
                continue
            d.update(mode=mode, slot=slot, assess=s2, why=f'{mode}: {s2["why"]}')
            taken.setdefault(a, []).append(slot)
            state.take(a, pid, handle, mode)
            slot_left[a] -= 1
            if mode == 'quote':
                left[a][0] -= 1
            else:
                left[a][1] -= 1
                left[a][2] -= 1
    log = []
    for a, ds in out.items():
        for key, d in ds.items():
            if not d['mode']:
                continue
            s = d['assess']
            passed = sorted(b for b, bs in out.items() if b != a and any(
                x['assess'].get('post_id') == s.get('post_id') and not x['mode'] for x in bs.values()))
            log.append(entry(a, key, d, passed))
    return out, log


def entry(account, key, d, passed_over=()):
    s = d['assess']
    return {'account': account, 'key': key, 'mode': d['mode'], 'target_url': s.get('url'), 'author': s.get('handle'),
            'author_followers': s.get('followers'), 'likes_at_selection': s.get('likes'),
            'views_at_selection': s.get('views'), 'age_h_at_post': s.get('age_h'), 'score': s.get('score'),
            'velocity_likes_per_h': s.get('likes_per_h'), 'hot': s.get('hot'),
            'slot_bjt': d['slot'].astimezone(BJT).isoformat() if d.get('slot') else None,
            'why': d.get('why'), 'passed_over': list(passed_over)}


def pick_record(d):
    """The `engagement` block stored on a plan pick / inbox row (post_mode reads `mode` and `url`)."""
    s = d.get('assess') or {}
    return {'mode': d.get('mode'), 'url': s.get('url'), 'author': s.get('handle'), 'followers': s.get('followers'),
            'likes': s.get('likes'), 'views': s.get('views'), 'age_h': s.get('age_h'), 'score': s.get('score'),
            'reject': s.get('reject'), 'why': d.get('why'), 'version': VERSION}


# ------------------------------------------------------------------ draft checks

GENERIC_EN = re.compile(r'\b(great (post|thread|point|take)|interesting take|so true|well said|thanks for sharing|'
                        r'nice (post|thread)|love this|this is (huge|big)|couldn\'?t agree more|100% agree|'
                        r'curious to see how it unfolds)\b', re.I)
GENERIC_ZH = re.compile(r'(说得好|说得对|太对了|学到了|感谢分享|谢谢分享|好文|干货|有道理|同意楼主|赞同|支持一下|mark一下|'
                        r'受教了|顶一下|牛逼|太强了)')
COUNTER = re.compile(r'\b(but|though|however|yet|unless|instead|actually|except)\b|不过|但是|但|其实|反而|恰恰|除非|'
                     r'而是|不是|未必|问题是|别忘了|[?？]', re.I)
DIGIT = re.compile(r'\d')
MENTION = re.compile(r'@[A-Za-z0-9_]{1,15}')
TICKER = re.compile(r'\$[A-Za-z]{2,10}\b')


def sentences(text):
    parts = re.split(r'[。！？!?]+|(?<!\d)\.(?!\d)|\n+', str(text or ''))
    return [p for p in (x.strip() for x in parts) if len(p) > 1]


def findings(body, mode, lang='en'):
    """Engagement-draft checks (HARD: engage_generic / engage_too_long / engage_mentions; SOFT: engage_no_payload)."""
    if not mode or not enabled():
        return []
    body = str(body or '')
    out = []
    m = (GENERIC_ZH if lang == 'zh' else GENERIC_EN).search(body) or GENERIC_EN.search(body)
    if m:
        out.append({'code': 'engage_generic', 'detail': f'generic filler "{m.group(0)}"'})
    if mode == 'reply' and len(sentences(body)) > 2:
        out.append({'code': 'engage_too_long', 'detail': f'{len(sentences(body))} sentences (reply max 2)'})
    if len(MENTION.findall(body)) > 1:
        out.append({'code': 'engage_mentions', 'detail': f'{len(MENTION.findall(body))} @mentions (max 1)'})
    if not (DIGIT.search(body) or COUNTER.search(body) or TICKER.search(body)):
        out.append({'code': 'engage_no_payload', 'detail': 'no number, counter-point or concrete observation'})
    return out


def prompt_rule(mode, who):
    return PROMPT_RULE[mode].format(who='@' + str(who).lstrip('@') if who else 'the author') if mode in PROMPT_RULE else None


# ------------------------------------------------------------------ discovery + log

def _clusters(account):
    beats = account.get('retrieval_beats') or []
    if isinstance(beats, str):
        beats = re.findall(r"[A-Za-z0-9_]+", beats)
    return {'acct_' + account['id'], account['id'], *beats}


_TRAFFIC = None


def donor_traffic(base=None):
    """{handle_lower: median likes} of each donor's newest (<= 60) original posts in live/donors/posts (local, not in
    git; counts only). Donors with < 5 originals there are unknown (absent)."""
    global _TRAFFIC
    if _TRAFFIC is not None and base is None:
        return _TRAFFIC
    out = {}
    d = Path(base or ROOT / 'live' / 'donors' / 'posts')
    for f in sorted(d.glob('*.jsonl')) if d.exists() else []:
        likes = []
        try:
            with open(f) as fh:
                for line in fh:
                    if len(likes) >= 60:
                        break
                    try:
                        p = json.loads(line)
                    except ValueError:
                        continue
                    if p.get('rt') or p.get('reply'):
                        continue
                    likes.append(_int(p.get('likes')) or 0)
        except OSError:
            continue
        if len(likes) >= 5:
            likes.sort()
            n = len(likes)
            out[f.stem.lower()] = likes[n // 2] if n % 2 else (likes[n // 2 - 1] + likes[n // 2]) / 2
    if base is None:
        _TRAFFIC = out
    return out


def subscriptions(accounts=None, cfg=None, exclude=(), traffic=None):
    """x_daily-shaped ENGAGE rows: per account the top targets_per_account same-language donors of its clusters with
    >= min_followers (live/donors/roster.json; handles and follower counts only), not promo-heavy, active in the last
    10 days. Handles in `exclude` (already fetched as X sources) are left out.
    Oct 9: high-traffic first - donors whose typical post (median likes, `donor_traffic`) is below min_median_likes
    are dropped; the rest rank by median likes, donors with no local posts after them by followers."""
    cfg = cfg or config()
    if accounts is None:
        from live import fd_accounts
        accounts = fd_accounts.rows()
    try:
        donors = list((json.loads(ROSTER.read_text()).get('donors') or {}).values())
    except (OSError, ValueError, AttributeError):
        return []
    skip = {str(h).lower() for h in exclude}
    traffic = donor_traffic() if traffic is None else traffic
    floor = float(cfg.get('min_median_likes') or 0)
    by = {}
    for a in accounts:
        cl = _clusters(a)
        pool = [d for d in donors if d.get('persona_cluster') in cl and d.get('lang') == a.get('lang')
                and (d.get('followers') or 0) >= cfg['min_followers'] and not d.get('promo_heavy')
                and str(d.get('handle') or '').lower() not in skip
                and (not d.get('latest_post') or str(d['latest_post']) >= '2026-09-28')
                and traffic.get(str(d.get('handle') or '').lower(), floor) >= floor]
        pool.sort(key=lambda d: (str(d.get('handle') or '').lower() not in traffic,
                                 -(traffic.get(str(d.get('handle') or '').lower()) or 0), -(d.get('followers') or 0)))
        for d in pool[:int(cfg['targets_per_account'])]:
            row = by.setdefault(d['handle'].lower(), {'handle': d['handle'], 'source_id': 'x_' + d['handle'],
                                                      'accounts': [], 'roles': ['ENGAGE'], 'tier': 'B',
                                                      'core': False, 'breadth': True, 'engage': True,
                                                      'followers': d.get('followers'),
                                                      'median_likes': traffic.get(d['handle'].lower())})
            row['accounts'].append(a['id'])
    return sorted(by.values(), key=lambda r: r['handle'].lower())


def prefilter(post, now, cfg=None):
    """(ok, reason) for a normalised fetched post of an ENGAGE source: worth extracting only when it already passes
    the target scoring at capture time (saves extraction on stale / small posts)."""
    cfg = cfg or config()
    src = {'url': post.get('url') or f"https://x.com/{post.get('handle') or 'x'}/status/{post.get('id')}",
           'published_at': (_ts(post.get('created_iso')) or _parse(post.get('created')) or now).isoformat(),
           'x_metrics': {k: post.get(k) for k in ('likes', 'views', 'reposts', 'replies', 'followers')}}
    a = assess(src, now, cfg=cfg)
    return (a['quote_ok'], a['reject'])


def _parse(value):
    try:
        from live.x_daily import _parse_created
        return _parse_created(value)
    except Exception:   # noqa: BLE001
        return None


def log_dir():
    return Path(os.environ.get('FD_ENGAGE_LOG') or ROOT / 'live' / 'store' / 'engagement')


def write_log(day, entries, run_id=None, base=None):
    """Merge today's chosen targets into live/store/engagement/<day>.json (one row per account + target)."""
    d = Path(base or log_dir())
    d.mkdir(parents=True, exist_ok=True)
    path = d / f'{day}.json'
    try:
        cur = json.loads(path.read_text())
    except (OSError, ValueError):
        cur = {'day': str(day), 'version': VERSION, 'targets': []}
    seen = {(t['account'], t.get('target_url')): i for i, t in enumerate(cur['targets'])}
    for e in entries:
        e = dict(e, run_id=run_id)
        k = (e['account'], e.get('target_url'))
        if k in seen:
            cur['targets'][seen[k]] = e
        else:
            seen[k] = len(cur['targets'])
            cur['targets'].append(e)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1, default=str) + '\n')
    tmp.replace(path)
    return path


def read_log(day, base=None):
    try:
        return json.loads((Path(base or log_dir()) / f'{day}.json').read_text())
    except (OSError, ValueError):
        return {'day': str(day), 'targets': []}
