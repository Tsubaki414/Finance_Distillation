"""Observation dates and data-driven shelf lives; no store mutation."""
from __future__ import annotations
import calendar
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

POLICY = json.loads(Path(__file__).with_name('freshness_policy.json').read_text())
DATA_ADAPTERS = ('cftc', 'cboe', 'farside', 'defillama', 'nyfed', 'glassnode', 'bls_api', 'treasury_fiscaldata')
MONTHS = {name.casefold(): i for i in range(1,13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
MONTHS['sept'] = 9
MONTH_PATTERN = '|'.join(sorted(MONTHS, key=len, reverse=True))

def today():
    return datetime.now(timezone.utc).date()

def _day(value):
    if value is None:
        return today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)

def normalize_date(s):
    if not isinstance(s, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[T ][0-9:.,+Z-]+)?', s):
        return None
    try:
        d = datetime.fromisoformat(s.replace('Z', '+00:00')).date()
    except ValueError:
        return None
    return d.isoformat() if d <= today() + timedelta(days=2) else None

def parse_period(text, year=None):
    text = str(text or '')
    m = re.search(r'(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)|(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日', text)
    try:
        if m:
            y, mo, d = m.groups()[:3] if m[1] else (m[4] or year,m[5],m[6])
            return date(int(y),int(mo),int(d)).isoformat()
        m = re.search(r'\b('+MONTH_PATTERN+r')\.?\s+(\d{1,2}),?\s+(\d{4})\b',text,re.I)
        if m:
            return date(int(m[3]),MONTHS[m[1].casefold()],int(m[2])).isoformat()
        m = re.search(r'\bQ([1-4])\s+(\d{4})\b',text,re.I)
        if m:
            y, mo = int(m[2]),int(m[1])*3
        else:
            m = re.search(r'\b('+MONTH_PATTERN+r')\s+(\d{4})\b',text,re.I)
            if m:
                y, mo = int(m[2]),MONTHS[m[1].casefold()]
            else:
                m = re.search(r'(?<!\d)(\d{4})-(\d{2})(?![-\d])|(?:(\d{4})年)?(\d{1,2})月',text)
                if not m:
                    return None
                y, mo = (int(m[1]),int(m[2])) if m[1] else (int(m[3] or year),int(m[4]))
        return date(y,mo,calendar.monthrange(y,mo)[1]).isoformat()
    except (ValueError, TypeError):
        return None

def derive_dates(row):
    u, src = row.get('unit',row),row.get('source',{})
    flags=[]
    raw=u.get('published_at') or src.get('published_at')
    published=normalize_date(raw)
    if not raw or raw == 'T00:00:00Z':
        flags.append('missing_published_at')
    elif not published:
        try:
            future=date.fromisoformat(str(raw)[:10]) > today()+timedelta(days=2)
        except ValueError:
            future=False
        flags.append('future_published_at' if future else 'malformed_published_at')
    source_published=normalize_date(src.get('published_at'))
    published=published or source_published
    year=int(published[:4]) if published else None
    candidates=[]
    adapter=str(src.get('adapter') or u.get('adapter') or '')
    if adapter.startswith(DATA_ADAPTERS):
        for v in (src.get('record_date'),src.get('id'),src.get('source_id'),src.get('url')):
            candidates.append((parse_period(v,year),'adapter_record_date'))
    candidates += [(parse_period(n.get('period'),year),'number_period') for n in u.get('numbers',[])]
    candidates += [(parse_period(u.get('statement'),year),'statement_date'),(source_published or published,'source_published'),(parse_period(src.get('url'),year),'url_date')]
    as_of, origin=None,'unknown'
    for candidate,label in candidates:
        if candidate:
            if date.fromisoformat(candidate)>today()+timedelta(days=2):
                if 'forward_period_skipped' not in flags: flags.append('forward_period_skipped')
                continue
            as_of,origin=candidate,label
            break
    if as_of and published and as_of > (date.fromisoformat(published)+timedelta(days=1)).isoformat():
        as_of=(date.fromisoformat(published)+timedelta(days=1)).isoformat()
        flags.append('as_of_clamped')
    return dict(published_at=published,as_of=as_of,as_of_source=origin,date_unknown=as_of is None,freshness_flags=flags)

def shelf_days(row):
    u,src=row.get('unit',row),row.get('source',{})
    if u.get('kind') in ('mechanism','aphorism') or u.get('freshness_class')=='evergreen':
        return None
    ids=[str(src.get(k) or u.get(k) or '').casefold() for k in ('adapter','source_id','channel_id')]
    ids += [s.removeprefix('channel:') for s in ids if s.startswith('channel:')]
    days=14
    for name in ('evergreen','market_flow','macro_release','filings_research','commentary'):
        spec=POLICY[name]
        if spec.get('non_fact_only') and u.get('kind')=='fact': continue
        if any(s.startswith(tuple(spec['prefixes'])) or s in spec['channel_ids'] for s in ids):
            days=spec['shelf_days']; break
    return min(days,2) if days is not None and u.get('freshness_class')=='breaking' else days

def age_unit(row):
    """'business_days' for shelf classes whose policy says so (market data does not age over a weekend)."""
    u,src=row.get('unit',row),row.get('source',{})
    ids=[str(src.get(k) or u.get(k) or '').casefold() for k in ('adapter','source_id','channel_id')]
    ids += [s.removeprefix('channel:') for s in ids if s.startswith('channel:')]
    for name in ('evergreen','market_flow','macro_release','filings_research','commentary'):
        spec=POLICY[name]
        if spec.get('non_fact_only') and u.get('kind')=='fact': continue
        if any(s.startswith(tuple(spec['prefixes'])) or s in spec['channel_ids'] for s in ids):
            return spec.get('age_unit','calendar_days')
    return 'calendar_days'

def _business_days(start, end):
    if end<=start: return 0
    return sum(1 for i in range(1,(end-start).days+1) if (start+timedelta(days=i)).weekday()<5)

def status(row, now=None):
    u=row.get('unit',row)
    shelf=shelf_days(row)
    derived=u if 'date_unknown' in u and 'as_of' in u else derive_dates(row)
    d=derived.get('as_of')
    age=max(0,(_day(now)-date.fromisoformat(d)).days) if d else None
    eff=age
    if d and shelf is not None and age_unit(row)=='business_days':
        eff=_business_days(date.fromisoformat(d),_day(now))
    state=('evergreen' if shelf is None else 'unknown' if derived.get('date_unknown') or age is None else 'expired' if eff>2*shelf else 'stale' if eff>shelf else 'fresh')
    return dict(status=state,age_days=age,shelf_days=shelf,effective_age=eff)

def boost(value):
    if isinstance(value,str):
        return {'fresh':1.,'stale':.6,'expired':.3,'evergreen':.8,'unknown':.4}[value]
    if value['status']=='stale':
        return max(.3,1-.7*(value.get('effective_age',value['age_days'])/value['shelf_days']-1))
    return boost(value['status'])

def rank(units, now=None):
    return sorted(units,key=lambda u: boost(status(u,now)),reverse=True)
