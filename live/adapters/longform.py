"""Public long-form research, tier B: paraphrase with publisher attribution."""
from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from live.adapters import common, feeds

OAKTREE = 'https://www.oaktreecapital.com/insights/memos'
BERKSHIRE = 'https://www.berkshirehathaway.com/letters/letters.html'
GLASSNODE = 'https://research.glassnode.com/rss/'


def parse_oaktree_index(body):
    soup = BeautifulSoup(body, 'html.parser')
    items = {}
    for link in soup.select('a[href*="/insights/memo/"]'):
        parent = link.parent
        stamp = None
        while parent is not None:
            stamp = parent.find('time')
            if stamp is not None:
                break
            parent = parent.parent
        match = re.search(r'\d{4}-\d{2}-\d{2}', str(stamp)) if stamp else None
        if match:
            url = urljoin(OAKTREE, link['href'])
            items[url] = {'url': url, 'title': link.get_text(' ', strip=True), 'published_at': match[0]}
    return sorted(items.values(), key=lambda it: (it['published_at'], it['url']), reverse=True)


def memo_text(body):
    soup = BeautifulSoup(body, 'html.parser')
    article = soup.select_one('.memo-content, .article-content, article, main')
    if article is None:
        return ''
    for node in article.select('nav, footer, script, style, .modal, .ac-left-sidebar, .ac-right-sidebar, .insight-actions, .social-links-wrapper-test'):
        node.decompose()
    text = common.html_text(str(article))
    return re.split(r'Legal Information and Disclosures|Disclaimer', text, maxsplit=1)[0].strip()


def fetch_oaktree(*, limit=3, transport=None):
    st, body = common.http_get(OAKTREE, transport=transport)
    requests, sources, failures = 1, [], []
    if st != 200:
        return {'status': f'http_{st}', 'requests': requests, 'sources': sources}
    for item in parse_oaktree_index(body)[:max(0, limit)]:
        st, body = common.http_get(item['url'], transport=transport)
        requests += 1
        if st != 200:
            failures.append(st)
            continue
        text = memo_text(body)
        sources += common.make_sources_chunked(id='oaktree-' + item['url'].rsplit('/', 1)[-1],
                                               source_id='oaktree_memos', publisher='Oaktree Capital (Howard Marks)',
                                               author_name='Howard Marks', adapter='oaktree', text=text, **item)
    return {'status': ('partial' if failures else 'ok') if sources else 'no_data',
            'requests': requests, 'sources': sources}


def pdf_text(body):
    """Convert PDF bytes locally; no shell interpolation or network subprocess."""
    result = subprocess.run(['pdftotext', '-', '-'], input=body, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=True, timeout=60)
    return result.stdout.decode('utf-8')


def fetch_berkshire(*, converter=None, transport=None, as_of=None):
    st, body = common.http_get(BERKSHIRE, transport=transport)
    index_status = 'ok' if st == 200 else f'http_{st}'
    # The index can sit behind a bot challenge; the letter PDFs remain directly public.
    years = [int(y) for y in re.findall(r'(\d{4})ltr\.pdf', body or '', re.I)] if st == 200 else []
    if st == 200 and not years:
        return {'status': 'no_letters', 'requests': 1, 'sources': []}
    today = as_of or date.today()
    # The Buffett letters archive can lag the current CEO's annual letter.
    # Probe the latest completed fiscal year; only fall back on an absent PDF.
    current_year = today.year - (2 if today.month < 2 else 1)
    candidates = sorted(set(years + [current_year]), reverse=True)
    requests = 1
    for year in candidates[:2]:
        url = f'https://www.berkshirehathaway.com/letters/{year}ltr.pdf'
        st, pdf = common.http_get(url, transport=transport, binary=True)
        requests += 1
        if st == 200:
            break
        if st != 404:
            return {'status': f'http_{st}', 'requests': requests, 'sources': []}
    if st != 200:
        return {'status': f'http_{st}', 'requests': requests, 'sources': []}
    try:
        text = (converter or pdf_text)(pdf)
    except (subprocess.SubprocessError, OSError, UnicodeError) as exc:
        return {'status': 'conversion_failed', 'requests': requests, 'sources': [], 'error': str(exc)[:200]}
    text = text.replace('\f', '\n\n')
    sources = common.make_sources_chunked(id=f'berkshire-{year}', source_id='berkshire_letters', text=text,
                                          publisher='Berkshire Hathaway', title=f'{year} shareholder letter', url=url,
                                          published_at=f'{year + 1}-02-01', adapter='berkshire',
                                          extra={'published_at_approximate': True, 'published_at_basis': 'February of year after letter year; day unknown', 'letter_year_from_index': year in years})
    return {'status': 'ok' if sources else 'no_data', 'requests': requests, 'sources': sources,
            'index_status': index_status}


def fetch_glassnode(*, limit=3, transport=None):
    st, body = common.http_get(GLASSNODE, transport=transport)
    if st != 200:
        return {'status': f'http_{st}', 'requests': 1, 'sources': []}
    root = ET.fromstring(body)
    items = sorted(root.findall('./channel/item'), key=lambda it: feeds._iso(it.findtext('pubDate')), reverse=True)
    sources = []
    for item in items[:max(0, limit)]:
        text = common.html_text(item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or '')
        url = (item.findtext('link') or '').strip()
        sources += common.make_sources_chunked(id='glassnode-' + common.digest(url or text)[:12],
                                               source_id='glassnode_research', publisher='Glassnode',
                                               title=item.findtext('title') or '', text=text, url=url,
                                               published_at=feeds._iso(item.findtext('pubDate')), adapter='glassnode')
    return {'status': 'ok' if sources else 'no_data', 'requests': 1, 'sources': sources}
