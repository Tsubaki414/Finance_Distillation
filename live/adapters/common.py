"""Shared helpers for source adapters: HTTP, HTML -> text, source records."""
from __future__ import annotations

import html as htmllib
import re

import httpx

from live.distillation_source import digest, paragraphs

# Honest crawler identity (bot convention: 'compatible; <Name>Bot/<ver>; +contact'); never a browser impersonation.
DEFAULT_UA = 'Mozilla/5.0 (compatible; FinanceDistillationBot/1.0; +mailto:fd-research@example.com)'
BLOCK = re.compile(r'</?(?:p|div|br|li|h[1-6]|tr|table|section|article|blockquote|ul|ol)\b[^>]*>', re.I)
MAX_CHARS = 14000


def http_get(url, *, headers=None, timeout=30, transport=None, binary=False):
    """(status, body). binary selects bytes; transport(url, headers) is the test seam."""
    headers = {'User-Agent': DEFAULT_UA, **(headers or {})}
    if transport is not None:
        return transport(url, headers)
    r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    return r.status_code, r.content if binary else r.text


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
    published = (published_at if 'T' in published_at else published_at + 'T00:00:00Z') if published_at else None
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
                     'numbers': r.get('numbers') or [{'text': r['number'], 'metric': r['metric'], 'period': r['period'], 'span_ref': 0}]})
    units, dropped = cu.validate_units_partial(source, {'units': raws}, tier)
    return units


def make_sources_chunked(*, text, id, title, max_chars=MAX_CHARS, max_parts=3, **kwargs):
    """Pack paragraphs into bounded parts; explicitly record any omitted tail.

    A paragraph larger than the limit is split so every part remains bounded.
    """
    if max_chars < 1 or max_parts < 1:
        raise ValueError('max_chars and max_parts must be positive')
    chunks, current = [], ''
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        if not paragraph:
            continue
        if current and len(current) + 2 + len(paragraph) <= max_chars:
            current += '\n\n' + paragraph
            continue
        if current:
            chunks.append(current)
            current = ''
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        current = paragraph
    if current:
        chunks.append(current)
    kept = chunks[:max_parts]
    sources = []
    for k, chunk in enumerate(kept, 1):
        src = make_source(id=f'{id}-p{k}', title=f'{title} (part {k}/{len(kept)})',
                          text=chunk, max_chars=max_chars, **kwargs)
        src.update(part=k, parts=len(kept), total_parts=len(chunks))
        src['truncated'] = k == len(kept) and len(chunks) > max_parts
        sources.append(src)
    return sources


def structured_result(rows, *, id, source_id, publisher, title, url, published_at, adapter, tier='B', requests=1):
    """Build a small structured-data source and its validated deterministic units."""
    if not rows:
        return {'status': 'no_data', 'requests': requests, 'sources': [], 'units': []}
    src = make_source(id=id, source_id=source_id, publisher=publisher, title=title, url=url,
                      published_at=published_at, adapter=adapter, text='\n\n'.join(r['line'] for r in rows))
    return {'status': 'ok', 'requests': requests, 'sources': [src],
            'units': data_units(src, rows, speaker=publisher, tier=tier)}
