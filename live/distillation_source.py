"""Immutable extracted-source contracts. Offsets are Python Unicode [start, end)."""
from __future__ import annotations
import datetime
import hashlib
import json
import re
from pathlib import Path
from live.language_support import DEFAULT as DEFAULT_LANGUAGES


def digest(value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def detect_language(text):
    """Conservative en/zh heuristic, NOT a general multilingual detector."""
    return DEFAULT_LANGUAGES.detect(text)


def paragraphs(text):
    spans = []
    for match in re.finditer(r'\S[\s\S]*?(?=\n[ \t]*\n|\Z)', text):
        end = match.end()
        while end > match.start() and text[end - 1].isspace():
            end -= 1
        spans.append({'paragraph_id': f'P{len(spans) + 1}', 'start': match.start(),
                      'end': end, 'exact_text': text[match.start():end]})
    return spans


def source_record(row,languages=DEFAULT_LANGUAGES):
    text = row.get('original_text', row.get('text', ''))
    if not isinstance(text, str):
        raise ValueError('source text must be a string')
    detected, confidence = languages.detect(text)
    declared = row.get('source_language')
    language = declared or detected
    if (declared is not None and declared not in languages.codes) or (detected != 'unknown' and declared and declared != detected):
        language, confidence = 'unknown', 0.0
    body_hash = digest(text)
    if row.get('source_hash') and row['source_hash'] != body_hash:
        raise ValueError('source_hash mismatch')
    out = {
        'id': row.get('id') or body_hash[:16], 'source_id': row.get('source_id'),
        'source_hash': body_hash, 'original_text': text,
        'normalized_text': re.sub(r'\s+', ' ', text).strip(),
        'author_name': row.get('author_name') or row.get('author'),
        'author_id': row.get('author_id'), 'url': row.get('url'),
        'title': row.get('title') or '', 'published_at': row.get('published_at'),
        'fetched_at': row.get('fetched_at'), 'snapshot_at': now(),
        'source_type': row.get('source_type'), 'platform': row.get('platform') or row.get('source_type'),
        'source_language': language, 'language_confidence': confidence,
        'language_method': languages.version,
        # Legacy 4,000-character rows are never silently treated as complete.
        'content_complete': row.get('content_complete') is True,
        'extraction_status': row.get('extraction_status') or 'legacy_completeness_unknown',
        'extractor_version': row.get('extractor_version') or 'unknown',
        'media_dependencies': row.get('media_dependencies') or [],
        'entity_glossary': row.get('entity_glossary') or {},
        'synthetic': bool(row.get('synthetic')),
    }
    # Context is evidence with its own ownership; it is never flattened into the
    # author's body. Missing relations/media remain visible to routing and QA.
    for key in ('post_type', 'reply_to', 'quoted_post', 'thread_id', 'thread_post_ids',
                'media', 'external_links', 'context_items', 'recovery', 'truncated',
                'required_context_urls','body_recovery','content_kind',
                'raw_import_ref', 'raw_import_hash', 'extraction_transformations', 'author_handle',
                'event_id', 'event_key', 'canonical_event_id'):
        if key in row:
            out[key] = row[key]
    from live.source_hygiene import annotate
    out['source_hygiene'] = annotate(out)
    out['source_version'] = digest({k: v for k, v in out.items() if k not in ('fetched_at', 'snapshot_at', 'recovery')})
    out['missing_fields'] = [k for k in ('author_id', 'author_name', 'url', 'published_at', 'fetched_at') if not out.get(k)]
    return out


def snapshot(source, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (source['source_version'] + '.json')
    if not path.exists():
        # Exclusive creation preserves the first observation of this version.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, ensure_ascii=False, indent=2)
    return str(path)
