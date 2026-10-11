"""Cross-account story dedupe + per-account 7-day story memory (Oct 11 account audit fixes 1 + 4).

The audit (cc_jobs/account_audit_1011.md) found the network running one story on many accounts: Polygon x TRON USDT
16 drafts / 16 accounts in 4 days, Robinhood BTC 12/10, Tether freezes 9/9. FD_EVENT_PER_LANG dedupes shared *sources*;
this dedupes *stories* (the underlying event), whatever the source.

Story of an item = keys + label tokens:
  - 'ea:<entity>|<action>[|<object>]' and 'pair:<a>+<b>' from the cached LLM label (live/story_label.py),
  - 'motif:<id>' (FD_HOTSPOT 母题 of the day), and deterministic 'ent2:<a>+<b>' pairs of distinctive names
    (live/twins.entities) as the no-model fallback.
Two items are one story when they share a key, or their story labels share >= 2 content tokens covering >= 60% of the
shorter label.

Caps (FD_STORY_DEDUPE=0 turns all off):
  - <= FD_STORY_PER_LANG_DAY (2) accounts per story per language per Beijing day,
  - <= FD_STORY_72H (4) accounts per story network-wide over the last 3 Beijing days (rolling ~72 h),
  - zh/en twins (live/twins.PAIRS) never on one story the same day.
Memory: an account's own stories of the last FD_STORY_MEMORY_DAYS (7) Beijing days; selection demotes a repeat.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta

from live import story_label, twins

GENERIC = {'btc', 'eth', 'crypto', 'crypto market', 'market', 'markets', 'stocks', 'us stocks', 'fed', 'altcoins',
           'memecoins', 'defi', 'stablecoins', 'ai', 'sol', 'bitcoin etf', 'etf', 'etfs', 'us', 'china', 'trump', ''}
ALIAS = {'bitcoin': 'btc', 'ethereum': 'eth', 'ether': 'eth', 'usdt': 'tether', 'federal reserve': 'fed',
         'the fed': 'fed', 'solana': 'sol', 'tron': 'tron', 'trx': 'tron', 'matic': 'polygon', 'pol': 'polygon',
         'polymarket': 'polymarket', 'pump.fun': 'pumpfun', 'pump fun': 'pumpfun'}
_STOP = set('''a an the of for to in on at by with from and or its it is as into over after amid new says said
report reports via vs than more less up down its their his her week weekly daily today crypto market price'''.split())


# action / filler words never make two labels one story on their own (needs a shared name)
_VERBS = set('''btc eth buy sell launch list delist freeze hack sue approve file reject partner integrate acquire raise
invest pay drop rise jump fall surge plunge rally crash hit near break add cut hold move flow inflow outflow data record
high low million billion fund funds token tokens coin coins user users wallet wallets'''.split())


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_STORY_DEDUPE', '1') != '0'


def cap_lang_day():
    return max(1, int(os.environ.get('FD_STORY_PER_LANG_DAY', '2')))


def cap_72h():
    return max(1, int(os.environ.get('FD_STORY_72H', '4')))


def memory_days():
    return max(1, int(os.environ.get('FD_STORY_MEMORY_DAYS', '7')))


def canon(name):
    n = re.sub(r'[^a-z0-9 .]+', ' ', str(name or '').lower()).strip()
    n = re.sub(r'\s+', ' ', n)
    n = re.sub(r'^(?:the )', '', n)
    n = re.sub(r'\b(?:inc|corp|labs|foundation|network|protocol|exchange)\b\.?', '', n).strip()
    return ALIAS.get(n, n)


def _tok(w):
    w = canon(w)
    return w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w


def label_tokens(lab):
    if not lab:
        return frozenset()
    words = re.findall(r'[a-z0-9.]+', str(lab.get('k') or '').lower())
    return frozenset(t for t in (_tok(w) for w in words) if t and t not in _STOP and len(t) > 1)


def label_keys(lab):
    if not lab:
        return set()
    e, o, a = canon(lab.get('e')), canon(lab.get('o')), lab.get('a') or 'other'
    keys = set()
    if o and e and o != e:
        keys.add('pair:' + '+'.join(sorted((e, o))))
    if e and e not in GENERIC and a != 'other':
        keys.add(f'ea:{e}|{a}' + (f'|{o}' if o else ''))
        if o:
            keys.add(f'ea:{e}|{a}')
    return keys


def entity_keys(title, text=''):
    ents = sorted(twins.entities(title, text))[:6]
    return {f'ent2:{a}+{b}' for i, a in enumerate(ents) for b in ents[i + 1:]}


def story_of(text, title='', motif=None, label=None):
    """{'keys': sorted keys, 'tokens': sorted label tokens, 'label': k, 'bucket': b} for one item."""
    lab = label if label is not None else story_label.get(text)
    keys = label_keys(lab) | entity_keys(title, text)
    if motif:
        keys.add(f'motif:{motif}')
    return {'keys': sorted(keys), 'tokens': sorted(label_tokens(lab)), 'label': (lab or {}).get('k'),
            'bucket': (lab or {}).get('b') or story_label.keyword_bucket(' '.join([str(title or ''), str(text or '')]))}


def same_story(a, b):
    ka, kb = set(a.get('keys') or ()), set(b.get('keys') or ())
    if ka & kb:
        return True
    ta, tb = set(a.get('tokens') or ()), set(b.get('tokens') or ())
    common = ta & tb
    if len(common) >= 2 and len(common) >= 0.6 * min(len(ta), len(tb)) and common - GENERIC - _VERBS:
        return True
    return False


def _day(d):
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


class Ledger:
    """Stories taken so far: inbox history (last memory_days() Beijing days) + this run's picks."""

    def __init__(self, day, items=()):
        self.day = _day(day)
        self.items = list(items)

    def add(self, account, lang, story, day=None, kind=None):
        self.items.append({'account': account, 'lang': str(lang or '')[:2], 'day': _day(day or self.day),
                           'keys': list(story.get('keys') or ()), 'tokens': list(story.get('tokens') or ()),
                           'kind': kind})

    def matches(self, story, *, days=None):
        out = []
        for it in self.items:
            age = (self.day - it['day']).days
            if days is not None and not 0 <= age < days:
                continue
            if same_story(it, story):
                out.append(it)
        return out

    def check(self, account, lang, story):
        """None when the account may take the story, else the cap reason."""
        if not enabled() or not (story.get('keys') or story.get('tokens')):
            return None
        lang = str(lang or '')[:2]
        hits = [it for it in self.matches(story, days=3) if it['account'] != account]
        today = [it for it in hits if it['day'] == self.day]
        twin = twins.twin_of(account)
        if twin and twins.enabled() and any(it['account'] == twin for it in today):
            return f'story_twin: twin {twin} already has this story today'
        same_lang = {it['account'] for it in today if it['lang'] == lang}
        if len(same_lang) >= cap_lang_day():
            return f'story_cap_lang_day: {len(same_lang)} {lang} accounts on this story today ({",".join(sorted(same_lang)[:3])})'
        net = {it['account'] for it in hits}
        if len(net) >= cap_72h():
            return f'story_cap_72h: {len(net)} accounts on this story in 72h'
        return None

    def repeat(self, account, story):
        """True when the account itself ran this story in the last memory_days() days (incl. earlier today)."""
        if not enabled():
            return False
        return any(it['account'] == account for it in self.matches(story, days=memory_days()))


def row_text(row):
    return ' '.join([str((row.get('source') or {}).get('title') or ''), str(row.get('body') or row.get('text') or '')])


def counts(row):
    """An inbox row that is (or will be) on the timeline: ready, not held / superseded / expired, with text."""
    return (bool(str(row.get('text') or row.get('body') or '').strip()) and not row.get('held')
            and not row.get('superseded') and row.get('draft_status') == 'draft_ready')


def history_rows(day, days=None, base=None):
    from live import compose_inbox
    day = _day(day)
    out = []
    for i in range(days or memory_days()):
        d = (day - timedelta(days=i)).isoformat()
        try:
            out += [r for r in compose_inbox.rows(d, base=base) if counts(r)]
        except Exception:   # noqa: BLE001
            continue
    return out


def row_story(row):
    st = row.get('story')
    if isinstance(st, dict) and (st.get('keys') or st.get('tokens')):
        return st
    motif = (row.get('hotspot') or {}).get('motif_id')
    return story_of(row_text(row), (row.get('source') or {}).get('title') or '', motif=None if not motif else
                    f"{row.get('day')}:{motif}")


def ledger_for(day, rows=None, base=None, label_model=False):
    """Ledger from the inbox history (labels cached / labelled now when label_model)."""
    rows = history_rows(day, base=base) if rows is None else rows
    need = [row_text(r) for r in rows if not (r.get('story') or {}).get('keys')]
    if need:
        try:
            story_label.label_many(need, allow_model=label_model)
        except Exception:   # noqa: BLE001
            pass
    led = Ledger(day)
    for r in rows:
        led.add(r.get('account_id'), r.get('lang'), row_story(r), day=r.get('day') or day,
                kind=r.get('kind') or (r.get('post_format') or {}).get('kind'))
    return led


# ---------------------------------------------------------------- archive (回看 / 常青) path
_ARCH = {}


def archive_ledger(day, refresh=False):
    key = str(day)
    if refresh or key not in _ARCH:
        try:
            _ARCH[key] = ledger_for(day)
        except Exception:   # noqa: BLE001
            _ARCH[key] = Ledger(day)
    return _ARCH[key]


def archive_gate(account_cfg, text, day, *, title='', label_model=False, off_lane_prefix='off_lane -> '):
    """(reason | None, story) for an archive pick / draft: the story caps against the day's ledger and the account's
    topic allowlist (an off-lane pick is handed to a fitting same-language account: reason 'off_lane -> <id>')."""
    from live import lane_allow
    aid = (account_cfg or {}).get('id')
    lang = str((account_cfg or {}).get('lang') or '')[:2]
    if label_model:
        try:
            story_label.label_many([text], allow_model=True)
        except Exception:   # noqa: BLE001
            pass
    st = story_of(text, title)
    led = archive_ledger(day)
    why = led.check(aid, lang, st)
    if why:
        return why, st
    v = lane_allow.verdict(aid, st.get('bucket'))
    if v == 'off':
        fit = lane_allow.fit_accounts(st['bucket'], lang, exclude={aid})
        return off_lane_prefix + (fit[0] if fit else 'none'), st
    return None, st


def archive_taken(account_cfg, story, day):
    archive_ledger(day).add((account_cfg or {}).get('id'), (account_cfg or {}).get('lang'), story, day=day)
