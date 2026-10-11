"""Old event without a look-back frame (Oct 11, Fiona: 墨川.eth 10-11 22:37).

The draft 「稳定币随时面临单边切断的风险… 我看到 2025年9月24日 他们仅凭名单… 冻结了 276万美元」 was a standalone
judgment_take from a fresh source (Unchained, 2026-10-06, a lawsuit filed 2026-10-05). The news hook (the lawsuit) never
reached the units, so the post presented a year-old freeze as if it were the news, with no 回看 frame and no "why now".

Rule (deterministic, HARD `stale_event_unframed`): a draft that names an explicit date more than `MAX_AGE_DAYS` (30)
before the drafting day must carry
  - a look-back frame (回看 / 去年 / 一年前 / 当时 / 早在 / 回头看 / 历史上 / 此前 / look back / a year ago / last year /
    back in / at the time / previously ...), and
  - for archive (回看 / 常青) drafts also a today comparison (今天 / 现在 / 如今 / 眼下 / 目前 / 本周 / now / today / as of ...).
Range starts (「2026 年以来」 / 「自2020年起」 / since 2021 / year-to-date) and year-over-year comparisons (同期 / 同比 / YoY)
are reference periods, not events, and are skipped. Dates up to 30 days old pass.

Used by compose QA (one targeted rewrite, then HOLD), the humanize post-step (a rewrite that drops the frame reverts),
both archive variants (回看 / 常青) and `scripts/apply_inbox_audit.py --recheck` for stored drafts. FD_STALE_FRAME=0
turns it off.
"""
from __future__ import annotations

import calendar
import os
import re
from datetime import date, datetime, timedelta, timezone

VERSION = 'stale-frame-v1'
CODE = 'stale_event_unframed'
HARD_CODES = (CODE,)
MAX_AGE_DAYS = 30
BJT = timezone(timedelta(hours=8))

FIX = ('The draft cites an event dated more than 30 days before today (detail) with no look-back frame. Either lead '
       "with today's news hook from the units (the new filing / data / statement and its date) and keep the old date "
       'only as background ("去年9月冻结的…，本周才起诉"), or frame it as a look-back: say it is an old event '
       '(回看 / 去年 / 当时 / a year ago / back in) and compare it with today (现在 / 如今 / now). Never present the old '
       'event as current news.')

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | \
          {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {'sept': 9}
_MON = r'(?:' + '|'.join(sorted(_MONTHS, key=len, reverse=True)) + r')'

ZH_YMD = re.compile(r'(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*[日号])?')
ZH_Y = re.compile(r'(?<!\d)(20\d{2})\s*年(?!\s*\d{1,2}\s*月)')
ISO = re.compile(r'(?<!\d)(20\d{2})-(\d{2})(?:-(\d{2}))?(?!\d)')
EN_MDY = re.compile(r'\b(' + _MON + r')\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b', re.I)
EN_MY = re.compile(r'\b(' + _MON + r')\.?,?\s+(20\d{2})\b', re.I)
EN_Y = re.compile(r'\b(?:in|since|during|back in|from)\s+(20\d{2})\b', re.I)
ZH_LAST_YEAR = re.compile(r'去年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*[日号])?')

# reference periods, not events: "2026 年以来", "自2020年起", "since 2021", "2025 年同期"
RANGE_AFTER = re.compile(r'^\s*(?:以来|至今|起|开始|到现在|同期|同比|全年|累计|以后)|^\s*(?:-|–|—|to|through)\s', re.I)
RANGE_BEFORE = re.compile(r'(?:自|从|since|from|year-over-year|yoy|versus|vs\.?|较|比)\s*$', re.I)

LOOKBACK = re.compile(r'回看|回头看|回顾|复盘|去年|一年前|两年前|几个月前|半年前|当时|那时|彼时|当年|早在|曾经|翻出|翻到|'
                      r'旧事|老帖|周年|历史上|历史|此前|过去|以往|早期|峰值|高点时|'
                      r'look(?:ing)? back|a year ago|years? ago|months ago|last year|back in|at the time|historically|'
                      r'previously|earlier|peaked|throwback|flashback|rewind|anniversary|remember when|then vs\.? now', re.I)
TODAY = re.compile(r'今天|今日|现在|如今|眼下|目前|当下|本周|这周|这个月|本月|最近|刚刚|这次|今年|截至|'
                   r'\btoday\b|\bnow\b|this week|this month|this year|currently|as of|latest|just\b|these days', re.I)


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_STALE_FRAME', '1') != '0'


def _end(y, m=None, d=None):
    """Latest date the mention can mean (year-only = 31 Dec, month = its last day): never over-age a mention."""
    if m is None:
        return date(y, 12, 31)
    m = max(1, min(12, m))
    if d is None:
        return date(y, m, calendar.monthrange(y, m)[1])
    try:
        return date(y, m, d)
    except ValueError:
        return date(y, m, calendar.monthrange(y, m)[1])


def _ref_day(day):
    if day is None:
        return datetime.now(BJT).date()
    if isinstance(day, datetime):
        return day.astimezone(BJT).date() if day.tzinfo else day.date()
    if isinstance(day, date):
        return day
    return date.fromisoformat(str(day)[:10])


def dated_mentions(text, day=None):
    """[(mention, date)] explicit dates in the text that are events (not range starts / YoY periods)."""
    text = str(text or '')
    ref = _ref_day(day)
    out, spans = [], []

    def add(m, d):
        if any(a <= m.start() < b for a, b in spans):
            return
        if RANGE_AFTER.search(text[m.end():m.end() + 6]) or RANGE_BEFORE.search(text[max(0, m.start() - 16):m.start()]):
            spans.append(m.span())
            return
        spans.append(m.span())
        out.append((m.group(0).strip(), d))

    for m in ZH_YMD.finditer(text):
        add(m, _end(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    for m in ZH_LAST_YEAR.finditer(text):
        add(m, _end(ref.year - 1, int(m.group(1)), int(m.group(2)) if m.group(2) else None))
    for m in ISO.finditer(text):
        add(m, _end(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    for m in EN_MDY.finditer(text):
        add(m, _end(int(m.group(3)), _MONTHS[m.group(1).lower().rstrip('.')], int(m.group(2))))
    for m in EN_MY.finditer(text):
        add(m, _end(int(m.group(2)), _MONTHS[m.group(1).lower().rstrip('.')]))
    for m in ZH_Y.finditer(text):
        add(m, _end(int(m.group(1))))
    for m in EN_Y.finditer(text):
        if m.group(0).lower().startswith(('since', 'from')):
            continue
        add(m, _end(int(m.group(1))))
    return out


def old_mentions(text, day=None, max_age_days=MAX_AGE_DAYS):
    ref = _ref_day(day)
    return [(s, d, (ref - d).days) for s, d in dated_mentions(text, ref) if (ref - d).days > max_age_days]


def framed(text):
    """(has look-back frame, has today comparison)."""
    t = str(text or '')
    return bool(LOOKBACK.search(t)), bool(TODAY.search(t))


def findings(body, lang=None, day=None, archive=False):
    """[{'code': 'stale_event_unframed', 'level': 'hard', 'detail'}] or [].

    Standalone drafts need the look-back frame (history wording counts: 历史上 / 此前 / 峰值 / previously ...); an
    archive (回看 / 常青) draft needs the frame AND the today comparison."""
    if not enabled():
        return []
    old = old_mentions(body, day)
    if not old:
        return []
    back, today = framed(body)
    if back and (today or not archive):
        return []
    missing = [x for x, ok in (('a look-back frame', back), ("a today comparison", today or not archive)) if not ok]
    s, d, age = max(old, key=lambda x: x[2])
    return [{'code': CODE, 'level': 'hard',
             'detail': f'{s} ({d.isoformat()}, {age} days before {_ref_day(day).isoformat()}) without ' + ' and '.join(missing)}]


def ok(body, day=None, archive=False):
    return not findings(body, day=day, archive=archive)
