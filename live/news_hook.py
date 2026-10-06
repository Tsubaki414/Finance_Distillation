"""News-hook (event) detection for selection dedupe (Oct 6 v10).

Fiona, Oct 6: "怎么选题还在非农数据上，这过去几天了？" - en_macro wrote the September payrolls release
(10/2) from a Cboe recap, then the next batch picked an Employ America "Labor Market Recap" of the
same release. theme_repeat compares view subjects ("fed hike probability" vs "wage growth") and missed
it. A news hook is the *event* a packet hangs on (one payroll release, one CPI print, one FOMC
decision ...). If the persona already wrote on that event in its recent history, packets on the same
event rank after packets on other events (soft: they are never dropped).

Keyword-only, no model call. Monthly / per-meeting releases recur at most once inside the window,
so event type + a 7-day history window identifies one release.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

HOOK_WINDOW_DAYS = 7
# ASCII word boundaries: '9月CPI同比' must match \bCPI\b (in Unicode mode 月/同 are word chars).
_FLAGS = re.I | re.A

EVENTS = {
    'us_payrolls': re.compile(
        r'non-?farm|payrolls?\b|jobs report|jobs data|employment (?:situation|report)|labou?r market recap|'
        r'average hourly earnings|\bAHE\b|\d[\d,.]*\s*(?:k|thousand)?\s+(?:new )?jobs\b|jobs? (?:growth|gains?) (?:of|slow|cool)|'
        r'非农|就业报告|新增就业|平均时薪|失业率', _FLAGS),
    'cpi': re.compile(r'\bCPI\b|consumer price index|消费者物价指数', _FLAGS),
    'us_pce': re.compile(r'\bPCE\b|personal consumption expenditure|个人消费支出', _FLAGS),
    'fomc_decision': re.compile(
        r'\bFOMC\b|fed(?:eral reserve)? (?:rate|policy) decision|dot plot|议息|点阵图|FOMC声明', _FLAGS),
    'us_gdp': re.compile(r'GDP (?:report|release|print|estimate|data)|(?:advance|second|third) estimate of GDP|GDP初值|GDP数据', _FLAGS),
    'china_pmi': re.compile(r'\bPMI\b|purchasing managers|采购经理指数', _FLAGS),
    'china_industrial_profits': re.compile(r'industrial (?:enterprise )?profits|工业企业利润', _FLAGS),
    'china_credit_data': re.compile(r'\bTSF\b|total social financing|社融|新增贷款|\bM2\b', _FLAGS),
    'ecb_decision': re.compile(r'\bECB\b.{0,40}(?:decision|hike|cut|hold|meeting)|欧洲央行.{0,10}(?:加息|降息|议息|决议)', _FLAGS),
    'boj_decision': re.compile(r'\bBoJ\b.{0,40}(?:decision|hike|cut|hold|meeting)|日本央行.{0,10}(?:加息|降息|议息|决议)', _FLAGS),
    'boe_decision': re.compile(r'\bBoE\b.{0,40}(?:decision|hike|cut|hold|meeting)|英国央行.{0,10}(?:加息|降息|议息|决议)', _FLAGS),
}


def hooks(text):
    """Event ids mentioned in text."""
    text = str(text or '')
    return {name for name, pattern in EVENTS.items() if pattern.search(text)}


def packet_hooks(group):
    """Events a packet hangs on: named in the source title or a view subject, or mentioned by >= 2 units
    (one passing mention in a long recap is not the packet's hook)."""
    if not group:
        return set()
    found = hooks((group[0].get('source') or {}).get('title'))
    counts = {}
    for record in group:
        unit = record.get('unit') or {}
        view = unit.get('view') if isinstance(unit.get('view'), dict) else {}
        found |= hooks(view.get('subject'))
        for name in hooks(' '.join(str(x or '') for x in (unit.get('statement'), view.get('claim')))):
            counts[name] = counts.get(name, 0) + 1
    return found | {name for name, n in counts.items() if n >= 2}


def _ts(row):
    try:
        ts = datetime.fromisoformat(str(row.get('ts')).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def history_hooks(rows, now=None, days=HOOK_WINDOW_DAYS):
    """{event: latest draft subject} for the persona's drafts inside the window (a row without a timestamp
    counts: unknown age is treated as recent). Uses draft text, subject, source title and any
    recorded `news_hooks`."""
    now = now or datetime.now(timezone.utc)
    earliest = now - timedelta(days=days)
    out = {}
    for row in rows or []:
        ts = _ts(row)
        if ts is not None and ts < earliest:
            continue
        found = hooks(' '.join(str(row.get(k) or '') for k in ('text', 'subject', 'source_title')))
        found |= set(row.get('news_hooks') or [])
        for name in found:
            out[name] = row.get('subject') or str(row.get('text') or '')[:40]
    return out


def repeated(group, rows, now=None, days=HOOK_WINDOW_DAYS):
    """Sorted events of this packet the persona already wrote on inside the window."""
    seen = history_hooks(rows, now, days)
    return sorted(packet_hooks(group) & set(seen))
