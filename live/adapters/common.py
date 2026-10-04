"""Shared helpers for source adapters: HTTP, HTML -> text, source records."""
from __future__ import annotations

import html as htmllib
import re

import httpx

from live.distillation_source import digest, paragraphs

DEFAULT_UA = 'FinanceDistillation research (contact: fd-research@example.com)'
BLOCK = re.compile(r'</?(?:p|div|br|li|h[1-6]|tr|table|section|article|blockquote|ul|ol)\b[^>]*>', re.I)
MAX_CHARS = 14000


def http_get(url, *, headers=None, timeout=30, transport=None):
    """(status, text). transport(url, headers) -> (status, text) is the test seam."""
    headers = {'User-Agent': DEFAULT_UA, **(headers or {})}
    if transport is not None:
        return transport(url, headers)
    r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    return r.status_code, r.text


def html_text(html):
    html = re.sub(r'<(script|style|noscript)\b.*?</\1>', ' ', html or '', flags=re.S | re.I)
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.S)
    html = BLOCK.sub('\n\n', html)
    text = htmllib.unescape(re.sub(r'<[^>]+>', ' ', html)).replace('\u00a0', ' ')
    paras = [re.sub(r'[ \t\r\f\v\n]+', ' ', p).strip() for p in re.split(r'\n\s*\n', text)]
    return '\n\n'.join(p for p in paras if p)


def make_source(*, id, source_id, text, publisher, title, url, published_at, adapter, author_name=None,
                lang='en', max_chars=MAX_CHARS, extra=None):
    """EXTRACT-ready source. Long text is cut at a paragraph boundary (recorded)."""
    truncated = False
    if len(text) > max_chars:
        kept = [p for p in paragraphs(text) if p['end'] <= max_chars]
        text = text[:kept[-1]['end']] if kept else text[:max_chars]
        truncated = True
    published = published_at if 'T' in (published_at or '') else (published_at or '') + 'T00:00:00Z'
    return {'id': id, 'source_id': source_id, 'source_hash': digest(text), 'original_text': text,
            'author_name': author_name or publisher, 'publisher': publisher, 'title': title, 'url': url,
            'published_at': published, 'source_language': lang, 'source_version': adapter + '-v1',
            'adapter': adapter, 'truncated': truncated, **(extra or {})}


def data_units(source, rows, *, speaker, tier='A'):
    """Deterministic units for structured data: one paragraph per row, the row's
    number copied from that paragraph. Same contract as EXTRACT (validate_units_partial)."""
    from live import content_units as cu
    by_text = {p['exact_text']: p['paragraph_id'] for p in paragraphs(source['original_text'])}
    raws = []
    for r in rows:
        raws.append({'kind': 'fact', 'statement': r['line'], 'speaker': speaker, 'speaker_type': 'official',
                     'freshness_class': 'current',
                     'source_spans': [{'paragraph_id': by_text[r['line']], 'exact_text': r['line']}],
                     'numbers': [{'text': r['number'], 'metric': r['metric'], 'period': r['period'], 'span_ref': 0}]})
    units, dropped = cu.validate_units_partial(source, {'units': raws}, tier)
    return units
