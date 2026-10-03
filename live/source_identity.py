"""Strong, account-scoped duplicate identities; never merge on a broad topic."""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from live.distillation_source import digest


def canonical_url(value):
    p = urlsplit(value or '')
    host = (p.hostname or '').lower().removeprefix('www.')
    if host in {'twitter.com', 'mobile.twitter.com', 'm.twitter.com', 'x.com'}:
        match = re.search(r'/status/(\d+)', p.path)
        if match:
            return 'https://x.com/i/status/' + match.group(1)
    # Generic query keys such as t/s/source/ref may identify a document. Only
    # known tracking keys are removed; false duplicate merges silently lose work.
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith('utm_')
             and k.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit(('https', host, p.path.rstrip('/'), urlencode(sorted(query)), '')) if host else ''


def aliases(row):
    keys = set()
    url = canonical_url(row.get('url'))
    if url:
        keys.add('url:' + url)
    text = row.get('original_text', row.get('text', ''))
    if isinstance(text, str) and text.strip():
        keys.add('text:' + digest(re.sub(r'\s+', ' ', text).strip()))
    # Event IDs must come from source metadata; no ticker/topic similarity is
    # promoted to a same-event claim. thread_id is NOT an identity (P0-3e2):
    # posts in one conversation are independent items; thread_id only groups
    # context for aggregation.
    for name in ('event_id', 'event_key', 'canonical_event_id'):
        if row.get(name):
            keys.add('event:' + str(row[name]))
    return sorted(keys)


def duplicate_run(store, account_id, source):
    wanted = set(aliases(source))
    if not wanted:
        return None
    for run in reversed(store.rows('runs')):
        if run.get('pipeline') != 'account_source' or run.get('account_id') != account_id:
            continue
        if not run.get('candidates') and run.get('status') != 'ignore':
            continue
        for key in run.get('event', {}).get('source_ids', []):
            if wanted.intersection(aliases(store.get('sources', key))):
                return run
    return None
