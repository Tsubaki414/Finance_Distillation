"""X keyword search, via Apify. The one thing account polling cannot do.

`twitter user-posts` answers "what are these twelve handles saying". It cannot answer "who is
talking about this" — `twitter search` returns HTTP 404 and still did when retested on
2026-09-24. That gap is why drafts kept describing twelve accounts as 「英文社区」: the system had
no way to look outside its own watchlist, so the watchlist got written up as if it were the world.

Authorised 2026-09-24, user's words: 「我刚刚附上了apify_token，你看看，这个尽管调用」.

Measured cost, not quoted: one run of `apidojo/tweet-scraper` for 10 results billed **$0.004**,
so $0.0004 per tweet. A thousand tweets is forty cents against a $500 monthly plan with $445
left. Every run records its own `usageTotalUsd` from Apify's run record rather than estimating,
the same discipline `ml/budget.py` applies to model calls.

**What this does not fix.** A keyword search is still a sample: it is whatever the actor's
upstream returns for that query at that moment, ranked by recency. It is much wider than twelve
handles and it is not 「全网」. Rows carry `sample: 'x_keyword_search'` so a writer downstream
cannot quietly promote it into a claim about a community — `live/opinions.overclaim_check` blocks
that wording regardless of where the posts came from.

Run: .venv/bin/python -B live/xsearch.py --query='$NVDA' [--max=25] [--lang=zh]
"""
from __future__ import annotations
from pathlib import Path
import sys, os, json, time, datetime, hashlib, copy, re, urllib.request, urllib.error

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
OUT = STORE / 'xsearch.jsonl'
RUNS = STORE / 'xsearch_runs.jsonl'

ACTOR = 'apidojo~tweet-scraper'
API = 'https://api.apify.com/v2'
# A ceiling per call, so a typo in a query cannot become a large bill. Raise deliberately.
MAX_ITEMS_CAP = 200
# Above this, say so before spending. $0.0004/item means this is about 12,500 items.
ANNOUNCE_ABOVE_USD = 5.0


class ApifyUnavailable(RuntimeError):
    """Raised rather than returning [], so an empty result is never mistaken for silence."""


def _token():
    f = ROOT / '.env'
    if f.is_file():
        for line in f.read_text(encoding='utf-8').split('\n'):
            line = line.strip()
            if line.startswith('APIFY_TOKEN=') and not line.startswith('#'):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    t = os.environ.get('APIFY_TOKEN')
    if t:
        return t
    raise ApifyUnavailable('APIFY_TOKEN not in .env or environment')


def _call(path, payload=None, timeout=300):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode('utf-8') if payload is not None else None,
        headers={'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        raise ApifyUnavailable(f'HTTP {e.code} on {path}: {e.read()[:200]!r}') from None


def remaining_usd():
    d = _call('/users/me/limits')['data']
    return round(float(d['limits']['maxMonthlyUsageUsd'])
                 - float(d['current']['monthlyUsageUsd']), 4)


def _settle_cost(run_id, tries=6, gap=4.0):
    """Apify's billed total lands a few seconds after the run ends. Wait for it.

    The first version slept 1.5s and read `usageTotalUsd`, which came back **0**. Reading that
    same run a minute later gave **0.008**. A cost ledger that records 0 for every call is worse
    than having no ledger: it accrues a real bill while reporting the spend is free, which is how
    the Grok charges arrived unnoticed. So this polls until a non-zero figure appears and, if one
    never does, returns None — unknown, and visibly so — rather than 0.
    """
    last = None
    for i in range(tries):
        time.sleep(gap)
        try:
            last = _call(f'/actor-runs/{run_id}')['data'].get('usageTotalUsd')
        except ApifyUnavailable:
            continue
        if last:
            return last
    return None if not last else last


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


TCO_TAIL = re.compile(r'\s*https?://t\.co/\w+\s*$')
ELLIPSIS_TAIL = re.compile(r'\s*(?:…|\.\.\.)\s*$')
LEADING_MENTIONS = re.compile(r'^(?:@\w{1,15}\s*)+')
COMPLETE_BASES = {'explicit_provider_completeness', 'note_tweet_body', 'variants_identical',
                  'truncated_variant_extended'}
PLATFORM_LIMIT = (270, 280)  # X weighted characters; CJK counts double


def _core(text):
    previous = None
    while previous != text:
        previous, text = text, TCO_TAIL.sub('', text)
    return text.rstrip()


_WEIGHT_ONE = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))  # twitter-text v3


def _weighted(text):
    return sum(1 if any(lo <= ord(ch) <= hi for lo, hi in _WEIGHT_ONE) else 2 for ch in text)


def body_completeness(variants):
    """Deterministic body choice and completeness basis from one capture (P0-3a).

    Returns (chosen_field, conflict, basis). The basis describes internal
    consistency of the capture; it is not independent full-text verification.
    """
    order = ['note_text', 'text', 'fullText', 'full_text']
    keys = sorted(variants, key=lambda k: order.index(k) if k in order else len(order))
    if 'note_text' in variants:
        chosen = 'note_text'
    else:
        chosen = max(keys, key=lambda k: len(LEADING_MENTIONS.sub('', _core(variants[k]))))  # first longest wins
    body = _core(variants[chosen])
    lead = lambda t: LEADING_MENTIONS.sub('', t)  # reply @mentions are display-only
    conflict = any(not lead(body).startswith(lead(ELLIPSIS_TAIL.sub('', _core(v)).rstrip()))
                   for v in variants.values())
    if conflict:
        return chosen, True, 'conflicting_text_variants'
    if chosen == 'note_text':
        return chosen, False, 'note_tweet_body'
    if ELLIPSIS_TAIL.search(body):
        return chosen, False, 'ellipsis_tail'
    if len(variants) < 2:
        return chosen, False, 'single_variant_unverified'
    if all(_core(v) == body for v in variants.values()):
        low, high = PLATFORM_LIMIT
        if low <= _weighted(body) <= high:
            return chosen, False, 'at_platform_limit_unverified'
        return chosen, False, 'variants_identical'
    return chosen, False, 'truncated_variant_extended'


def normalize_item(item, *, query, run_id, dataset_id, fetched_at, raw_import_ref):
    """Preserve the capture, separating a post's body from other speakers/context.

    Apify sometimes returns a *shorter*, conflicting fullText. A field name, length
    or successful request is not evidence of body completeness. Ambiguous captures
    remain held for source recovery/verification at account intake.
    """
    x = copy.deepcopy(item)
    if x.get('noResults') or not (x.get('id') or x.get('tweetId')):
        return None  # Preserve retrieval sentinels in the raw dataset, not as posts.
    a = x.get('author') or {}
    variants = {k: x[k] for k in ('text', 'fullText', 'full_text') if isinstance(x.get(k), str) and x[k].strip()}
    note = x.get('noteTweet') or x.get('note_tweet') or {}
    if isinstance(note, dict):
        note_text = note.get('text') or (note.get('note_tweet_results') or {}).get('result', {}).get('text')
        if isinstance(note_text, str) and note_text.strip():
            variants['note_text'] = note_text
    if not variants:
        return None
    chosen, conflict, basis = body_completeness(variants)
    text = variants[chosen]
    truncated = any(x.get(k) is True for k in ('truncated', 'isTruncated', 'is_truncated'))
    explicit_complete = x.get('content_complete') is True or any(x.get(k) is False for k in ('truncated', 'isTruncated', 'is_truncated'))
    if truncated:
        basis = 'provider_truncated'
    elif explicit_complete and not conflict:
        basis = 'explicit_provider_completeness'
    complete = basis in COMPLETE_BASES
    handle = a.get('userName') or a.get('username') or x.get('handle')
    post_id = str(x.get('id') or x.get('tweetId') or '')
    quote = copy.deepcopy(x.get('quote') or x.get('quotedTweet') or x.get('quoted_status'))
    quote_id = x.get('quoteId') or (quote.get('id') if isinstance(quote, dict) else None)
    reply_id = x.get('inReplyToId') or x.get('inReplyToStatusId') or x.get('in_reply_to_status_id_str')
    reply = ({'post_id': str(reply_id), 'author_id': x.get('inReplyToUserId'),
              'author_handle': x.get('inReplyToUsername'), 'status': 'not_retrieved'} if reply_id else None)
    quoted = ({**quote, 'post_id': str(quote_id or ''), 'status': 'captured_nested_context'} if isinstance(quote, dict)
              else {'post_id': str(quote_id), 'status': 'not_retrieved'} if quote_id else None)
    media = copy.deepcopy(x.get('media') or (x.get('extendedEntities') or {}).get('media') or [])
    entities = copy.deepcopy(x.get('entities') or {})
    external_links = [u.get('expanded_url') or u.get('expandedUrl') or u.get('url') for u in entities.get('urls', []) if isinstance(u, dict)]
    metadata = {'kind': 'x_capture_metadata', 'author': a, 'text_variants': variants,
                'selected_text_field': chosen, 'text_variants_conflict': conflict,
                'entities': entities, 'extendedEntities': x.get('extendedEntities'), 'card': x.get('card'),
                'isReply': x.get('isReply'), 'isQuote': x.get('isQuote'), 'isRetweet': x.get('isRetweet'),
                'quoteId': x.get('quoteId'), 'conversationId': x.get('conversationId'),
                'reply_fields': {k: v for k, v in x.items() if k.startswith('inReplyTo')},
                'thread_completeness': 'unknown', 'raw_import_ref': raw_import_ref, 'raw_import_hash': _hash(item)}
    return {'post_id': post_id, 'source_id': 'x_' + handle if handle else None,
            'handle': handle, 'author_handle': handle, 'author_name': a.get('name') or handle, 'author_id': a.get('id'),
            'followers': a.get('followers'), 'verified': a.get('isVerified') or a.get('isBlueVerified'),
            'text': text, 'original_text': text, 'lang': x.get('lang'),
            'source_language': x.get('lang') if x.get('lang') in ('en', 'zh') else None,
            'created_at': x.get('createdAt'), 'published_at': x.get('createdAt'),
            'url': x.get('url') or x.get('twitterUrl') or (f'https://x.com/{handle}/status/{post_id}' if handle and post_id else None),
            'source_type': 'x', 'platform': 'x', 'content_complete': complete, 'extraction_status': basis,
            'completeness_basis': basis, 'extractor_version': 'apify-preserved-capture-v3', 'truncated': truncated,
            'completeness_evidence': ('provider_flag' if basis == 'explicit_provider_completeness'
                                      else 'capture_internal_consistency' if complete else None),
            'post_type': ('repost' if x.get('isRetweet') else 'reply' if x.get('isReply') or reply else
                          'quote' if x.get('isQuote') or quoted else 'original' if x.get('isRetweet') is False and x.get('isReply') is False and x.get('isQuote') is False else 'unknown'),
            'reply_to': reply, 'quoted_post': quoted, 'thread_id': x.get('conversationId'),
            'media': media, 'external_links': [u for u in external_links if u], 'context_items': [metadata],
            'likes': x.get('likeCount'), 'retweets': x.get('retweetCount'), 'replies': x.get('replyCount'), 'views': x.get('viewCount'),
            'query': query, 'sample': 'x_keyword_search',
            'sample_note': 'Bounded upstream search sample; not the whole platform or a complete thread/archive.',
            'source': 'apify:' + ACTOR, 'apify_run_id': run_id, 'apify_dataset_id': dataset_id,
            'collected_at': fetched_at, 'fetched_at': fetched_at,
            'raw_import_ref': raw_import_ref, 'raw_import_hash': _hash(item)}


def search(query, max_items=25, lang=None, sort='Latest', since_hours=None, raw_directory=None):
    """One keyword search. Returns rows plus the run's actual billed cost."""
    max_items = min(int(max_items), MAX_ITEMS_CAP)
    if max_items < 1:
        raise ValueError('max_items must be positive')
    payload = {'searchTerms': [query], 'maxItems': max_items, 'sort': sort}
    if lang:
        payload['tweetLanguage'] = lang
    if since_hours:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=since_hours)
        payload['start'] = since.strftime('%Y-%m-%d')

    left = remaining_usd()
    run = _call(f'/acts/{ACTOR}/runs?waitForFinish=180', payload)['data']
    if run['status'] != 'SUCCEEDED':
        raise ApifyUnavailable(f"run {run['id']} ended {run['status']}")

    billed = _settle_cost(run['id'])

    ds = _call(f"/datasets/{run['defaultDatasetId']}/items?limit={max_items}")
    fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    raw_record = {'actor': ACTOR, 'actor_input': payload, 'run_id': run['id'],
                  'dataset_id': run['defaultDatasetId'], 'fetched_at': fetched_at,
                  'dataset_hash': _hash(ds), 'items': ds,
                  'item_hashes': [_hash(x) for x in ds] if isinstance(ds, list) else []}
    directory = Path(raw_directory) if raw_directory else STORE / 'xsearch_raw'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (_hash(raw_record) + '.json')
    if not path.exists():
        with path.open('x', encoding='utf-8') as fh:
            json.dump(raw_record, fh, ensure_ascii=False, indent=2)
    rows = [row for index, x in enumerate(ds if isinstance(ds, list) else []) if isinstance(x, dict)
            if (row := normalize_item(x, query=query, run_id=run['id'], dataset_id=run['defaultDatasetId'],
                                      fetched_at=fetched_at, raw_import_ref=str(path) + f'#items/{index}'))]
    return {'query': query, 'rows': rows, 'requested': max_items,
            'billed_usd': billed, 'apify_run_id': run['id'],
            'monthly_remaining_before': left, 'raw_snapshot': str(path), 'apify_dataset_id': run['defaultDatasetId'],
            'retrieval_diagnostics': {'dataset_items': len(ds) if isinstance(ds, list) else 0,
                                      'normalized_posts': len(rows),
                                      'excluded_non_posts': len(ds) - len(rows) if isinstance(ds, list) else 0},
            'per_item_usd': round(billed / max(len(rows), 1), 6) if billed else None}


def _seen():
    s = set()
    if OUT.is_file():
        for line in OUT.read_text(encoding='utf-8').split('\n'):
            if line.strip():
                try:
                    s.add(json.loads(line)['post_id'])
                except Exception:
                    continue
    return s


def run_and_store(query, max_items=25, lang=None, since_hours=None):
    r = search(query, max_items=max_items, lang=lang, since_hours=since_hours)
    seen = _seen()
    fresh = [x for x in r['rows'] if x['post_id'] and x['post_id'] not in seen]
    if fresh:
        STORE.mkdir(parents=True, exist_ok=True)
        with OUT.open('a', encoding='utf-8') as fh:
            for x in fresh:
                fh.write(json.dumps(x, ensure_ascii=False) + '\n')
    rec = {k: v for k, v in r.items() if k != 'rows'}
    rec.update(returned=len(r['rows']), new=len(fresh),
               at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    STORE.mkdir(parents=True, exist_ok=True)
    with RUNS.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return {**rec, 'rows': fresh}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    q = args.get('query')
    if not isinstance(q, str):
        raise SystemExit("用法: python -B live/xsearch.py --query='$NVDA' [--max=25] [--lang=zh]")
    r = run_and_store(q, max_items=int(args.get('max', 25)),
                      lang=args.get('lang') if isinstance(args.get('lang'), str) else None,
                      since_hours=int(args['since-hours']) if 'since-hours' in args else None)
    print(f"「{q}」返回 {r['returned']} 条，新增 {r['new']}  "
          f"实际计费 ${r['billed_usd']}（${r['per_item_usd']}/条）")
    print(f"  月额度剩余（调用前）${r['monthly_remaining_before']}  run {r['apify_run_id']}")
    for x in r['rows'][:6]:
        print(f"  @{x['handle']} [{x['lang']}] {str(x['created_at'])[:16]}  {x['text'][:100]}")


if __name__ == '__main__':
    main()
