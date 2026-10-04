"""SEC EDGAR (tier A): submissions JSON -> recent 8-K (earnings items, EX-99.x
press release / prepared remarks preferred), 10-Q, 10-K -> text source.

SEC fair access: a declared User-Agent with a real contact is required and at
most 10 requests/second. SEC_USER_AGENT must be set to Fiona's contact; the
placeholder is flagged in every run report.
"""
from __future__ import annotations

import os
import re
import time

from live.adapters import common

PLACEHOLDER = 'FinanceDistillation research fd-research@example.com'
EARNINGS_ITEMS = ('2.02',)
TITLE_FIX = {'INC': '', 'CORP': '', 'CORPORATION': '', 'CO': '', 'LTD': '', 'PLC': '', 'HOLDINGS': '', 'INC.': ''}
# A small persona-relevant watchlist (CIKs from EDGAR company tickers).
WATCHLIST = {'AAPL': '0000320193', 'TSLA': '0001318605', 'ORCL': '0001341439', 'NVDA': '0001045810', 'MU': '0000723125', 'AMD': '0000002488', 'MSFT': '0000789019',
             'GOOGL': '0001652044', 'AMZN': '0001018724', 'META': '0001326801', 'TSM': '0001046179',
             'AVGO': '0001730168', 'MSTR': '0001050446', 'COIN': '0001679788', 'JPM': '0000019617'}


def user_agent():
    ua = os.environ.get('SEC_USER_AGENT', '').strip()
    return (ua, False) if ua else (PLACEHOLDER, True)


def company_name(raw):
    words = [w for w in re.split(r'\s+', raw.strip()) if w.upper().strip(',.') not in TITLE_FIX]
    return ' '.join(w.capitalize() if w.isupper() else w for w in words)


def recent_filings(submissions, *, forms=('8-K', '10-Q', '10-K'), earnings_only=False, limit=5):
    r = submissions['filings']['recent']
    out = []
    for i, form in enumerate(r['form']):
        if form not in forms:
            continue
        items = (r.get('items') or [''] * len(r['form']))[i] or ''
        if earnings_only and not (form == '8-K' and any(x in items.split(',') for x in EARNINGS_ITEMS)):
            continue
        out.append({'company': submissions['name'], 'cik': str(submissions.get('cik', '')).lstrip('0'),
                    'form': form, 'date': r['filingDate'][i], 'accession': r['accessionNumber'][i],
                    'document': r['primaryDocument'][i], 'items': items})
        if len(out) >= limit:
            break
    return out


def pick_document(index, primary, form):
    names = [x['name'] for x in index['directory']['item']]
    if form == '8-K':
        ex = sorted(n for n in names if re.search(r'ex-?99', n, re.I) and n.endswith(('.htm', '.html', '.txt')))
        if ex:
            return ex[0]
    return primary


def to_source(filing, text):
    company = company_name(filing['company'])
    acc = filing['accession'].replace('-', '')
    url = f'https://www.sec.gov/Archives/edgar/data/{filing["cik"]}/{acc}/{filing["document"]}'
    return common.make_source(id=f'edgar-{filing["accession"]}', source_id='sec_edgar', text=text, publisher=company,
                              title=f'{company} {filing["form"]} ({filing["date"]})', url=url,
                              published_at=filing['date'], adapter='edgar',
                              extra={'form': filing['form'], 'accession': filing['accession']})


def fetch(ticker_or_cik, *, forms=('8-K',), earnings_only=True, limit=1, transport=None, max_age_days=None, as_of=None):
    import json
    ua, placeholder = user_agent()
    cik = WATCHLIST.get(ticker_or_cik, ticker_or_cik).zfill(10)
    headers = {'User-Agent': ua}
    status, body = common.http_get(f'https://data.sec.gov/submissions/CIK{cik}.json', headers=headers, transport=transport)
    if status != 200:
        return {'status': f'http_{status}', 'sources': [], 'ua_placeholder': placeholder}
    filings = recent_filings(json.loads(body), forms=forms, earnings_only=earnings_only, limit=limit)
    if max_age_days is not None:
        from datetime import date
        today = as_of or date.today()
        filings = [f for f in filings if 0 <= (today - date.fromisoformat(f['date'])).days <= max_age_days]
    sources, requests = [], 1
    for f in filings:
        time.sleep(0.15)  # well under 10 req/s
        acc = f['accession'].replace('-', '')
        st, idx = common.http_get(f'https://www.sec.gov/Archives/edgar/data/{f["cik"]}/{acc}/index.json',
                                  headers=headers, transport=transport)
        requests += 1
        doc = pick_document(json.loads(idx), f['document'], f['form']) if st == 200 else f['document']
        st, html = common.http_get(f'https://www.sec.gov/Archives/edgar/data/{f["cik"]}/{acc}/{doc}',
                                   headers=headers, transport=transport)
        requests += 1
        if st == 200:
            sources.append(to_source({**f, 'document': doc}, common.html_text(html)))
    return {'status': 'ok', 'sources': sources, 'requests': requests, 'ua_placeholder': placeholder}
