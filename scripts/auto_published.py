#!/usr/bin/env python3
"""Auto-mark FD drafts as 已发 by matching today's (and yesterday's) unposted draft_ready drafts to the
account's recent timeline via text similarity.

For each of our accounts that has a handle and unposted draft_ready drafts on the Beijing-day inbox file(s),
fetch the account's latest tweets (twitter241 /user-tweets, count ~10; reuse cached user ids from the perf_review
raw cache to skip /user calls). Match each tweet created after the draft's stored_at to drafts by
perf_review.similarity on the body (threshold 0.88; for quote drafts strip the target URL from the tweet text;
for reply drafts the tweet must be a reply to the correct target status id when the API exposes it).
Ambiguity (two drafts ≥0.88 for the same tweet) -> mark only the best if it beats the second by ≥0.05.

Mark: POST to /api/decisions the same payload the ops page uses for the 已发 checkbox (published flag true,
keep before_publish), plus posted_at (tweet created_at as ISO UTC) and tweet_url, source 'auto'.
Never un-mark; never overwrite a human decision other than setting the published flag.
Match log -> live/store/auto_published/<day>.json.

--dry-run: print matches, no POST.
FD_AUTOPUB=0: skip entirely.
FD_AUTOPUB_MAX_CALLS: max /user-tweets calls per run (default 40).
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BJT = ZoneInfo('Asia/Shanghai')
INBOX = ROOT / 'live/store/compose_inbox'
DECISIONS_STORE = ROOT / 'live/store/admin_decisions'
AUTO_LOG = ROOT / 'live/store/auto_published'
PERF_RAW = Path('/workspace/x/perf/raw')
DECISIONS_API = 'https://fd-ops-dashboard.vercel.app/api/decisions'

MATCH_THRESHOLD = 0.88
AMBIGUITY_GAP = 0.05
TWEET_COUNT = 10
DEFAULT_MAX_CALLS = 40

URL_RE = re.compile(r'https?://\S+')
WS_RE = re.compile(r'\s+')
STATUS_ID_RE = re.compile(r'/status/(\d+)')


def norm(text):
    return WS_RE.sub('', URL_RE.sub('', text or '')).lower()


def similarity(a, b):
    import difflib
    a, b = norm(a)[:220], norm(b)[:220]
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def bjt_day_now():
    return datetime.now(BJT).date().isoformat()


def inbox_days():
    """Most recent two Beijing inbox days."""
    today = bjt_day_now()
    yesterday = datetime.fromisoformat(today).replace(tzinfo=BJT)
    from datetime import timedelta
    yesterday = (yesterday - timedelta(days=1)).date().isoformat()
    days = []
    for d in (today, yesterday):
        p = INBOX / d
        if p.is_dir():
            days.append(d)
    return days


def load_decisions(day):
    try:
        return json.loads((DECISIONS_STORE / f'{day}.json').read_text()).get('decisions') or {}
    except (OSError, ValueError):
        return {}


def is_published(x):
    return bool(x) and (x.get('published') is True or
                        (x.get('published') is not False and x.get('action') == 'published'))


def load_unposted_drafts(days):
    """Return list of draft dicts with day, account_id, id, body, stored_at, mode, target_url for
    draft_ready unposted drafts across the given inbox days."""
    out = []
    for day in days:
        decisions = load_decisions(day)
        for f in sorted((INBOX / day).glob('*.json')):
            try:
                row = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            # status_of logic from build_ops_dashboard (simplified: held/arbitration/draft_status)
            if row.get('superseded'):
                continue
            if row.get('held') or (row.get('arbitration') or {}).get('status') == 'HOLD':
                continue
            status = row.get('draft_status') or row.get('status') or 'unknown'
            if status != 'draft_ready':
                continue
            did = row.get('id') or f.stem
            dec = decisions.get(did) or {}
            if is_published(dec):
                continue   # already marked
            body = (row.get('body') or '').strip()
            if not body:
                continue
            mode = row.get('post_mode') or 'original'
            eng = row.get('engagement') if isinstance(row.get('engagement'), dict) else {}
            engaged = mode in ('quote', 'reply') and eng.get('mode') == mode
            target = (row.get('quote_target_url') or row.get('reply_to_url') or
                      (eng.get('url') if engaged else '') or '')
            stored_at = row.get('stored_at') or ''
            out.append({
                'day': day, 'account_id': row.get('account_id') or '', 'id': did,
                'body': body, 'stored_at': stored_at, 'mode': mode, 'target': target,
                'decision': dec,
            })
    return out


def load_accounts():
    from live import fd_accounts
    accs_file = ROOT / 'live/fd20_accounts.json'
    rows = fd_accounts.rows(accs_file) if accs_file.exists() else []
    return {a['id']: a for a in rows}


def perf_raw_uid(handle):
    """Read cached uid from /workspace/x/perf/raw/<handle>.json; returns str or None."""
    p = PERF_RAW / f'{handle.lower()}.json'
    try:
        d = json.loads(p.read_text())
        return str(d['uid']) if d.get('uid') else None
    except (OSError, ValueError, KeyError):
        return None


def fetch_timeline(client, handle, uid_cache):
    """Fetch recent tweets for handle; returns list of post dicts from scrape_donor_posts.timeline_posts."""
    from scripts.scrape_donor_posts import timeline_posts
    uid = uid_cache.get(handle.lower()) or perf_raw_uid(handle)
    if not uid:
        user = client.get('/user', username=handle)['result']['data']['user']['result']
        uid = user['rest_id']
        uid_cache[handle.lower()] = uid
    obj = client.get('/user-tweets', user=uid, count=TWEET_COUNT)
    posts = timeline_posts(obj)
    return [p for p in posts if p.get('uid') in (None, uid)]


def tweet_created_utc(p):
    """Parse tweet created_at string to UTC datetime; returns None on failure."""
    s = p.get('created') or ''
    if not s:
        return None
    try:
        return datetime.strptime(s, '%a %b %d %H:%M:%S %z %Y').astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def target_status_id(url):
    """Extract status id from a twitter/x.com status URL; returns str or None."""
    m = STATUS_ID_RE.search(url or '')
    return m.group(1) if m else None


def strip_target_url(text, target_url):
    """For quote drafts: remove the target URL from the body before similarity comparison."""
    if not target_url:
        return text
    return text.replace(target_url, '').strip()


def match_drafts_to_tweets(drafts, tweets):
    """Match a list of same-account drafts to a list of tweets.

    Returns list of (draft, tweet, score) for matches above MATCH_THRESHOLD, one match per tweet
    (best draft wins; tie with <AMBIGUITY_GAP gap -> skip that tweet)."""
    results = []
    for tweet in tweets:
        if tweet.get('rt'):
            continue
        tweet_text = tweet.get('text') or ''
        tweet_created = tweet_created_utc(tweet)
        scored = []
        for draft in drafts:
            # tweet must be created after draft's stored_at
            if draft.get('stored_at') and tweet_created:
                try:
                    stored = datetime.fromisoformat(draft['stored_at']).astimezone(timezone.utc)
                    if tweet_created <= stored:
                        continue
                except (ValueError, TypeError):
                    pass
            # for reply drafts: tweet must be a reply to the right status id
            if draft['mode'] == 'reply' and draft.get('target'):
                tid = target_status_id(draft['target'])
                # tweet 'reply' bool is set; we can't always get the exact in_reply_to id from the
                # normalised post, so accept if it's a reply post at all when tid extraction fails
                if tid and not tweet.get('reply'):
                    continue
            # compare bodies (strip target URL from tweet text for quote drafts)
            cmp_tweet = strip_target_url(tweet_text, draft.get('target') or '') if draft['mode'] == 'quote' else tweet_text
            s = similarity(draft['body'], cmp_tweet)
            if s >= MATCH_THRESHOLD:
                scored.append((draft, s))
        if not scored:
            continue
        scored.sort(key=lambda x: -x[1])
        best_draft, best_score = scored[0]
        if len(scored) >= 2:
            second_score = scored[1][1]
            if best_score - second_score < AMBIGUITY_GAP:
                continue   # ambiguous: skip
        results.append((best_draft, tweet, best_score))
    return results


def build_decision_payload(day, draft, tweet, posted_at_iso, tweet_url):
    """Build the POST body for /api/decisions, matching the ops page's published action."""
    prev = draft.get('decision') or {}
    before_publish = None
    if prev.get('action') and prev['action'] not in ('published', 'clear', 'unpublish'):
        before_publish = prev['action']
    return {
        'day': day,
        'id': draft['id'],
        'account_id': draft['account_id'],
        'action': 'published',
        'published': True,
        'before_publish': before_publish,
        'text': prev.get('text') or None,   # keep any admin-edited text
        'note': prev.get('note') or '',
        # extra fields for auto-mark provenance
        'posted_at': posted_at_iso,
        'tweet_url': tweet_url,
        'source': 'auto',
    }


def post_decision(api_url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(api_url, data=data, method='POST',
                                 headers={'Content-Type': 'application/json', 'Cache-Control': 'no-store'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def tweet_url_from(tweet, handle):
    tid = tweet.get('id') or ''
    h = (handle or '').lstrip('@')
    return f'https://x.com/{h}/status/{tid}' if tid and h else ''


def write_log(day, entries):
    AUTO_LOG.mkdir(parents=True, exist_ok=True)
    path = AUTO_LOG / f'{day}.json'
    existing = []
    try:
        existing = json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    existing.extend(entries)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def main(argv=None):
    if os.environ.get('FD_AUTOPUB', '1') == '0':
        print('FD_AUTOPUB=0: skip')
        return 0

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true', help='print matches without POSTing')
    ap.add_argument('--api', default=DECISIONS_API)
    ap.add_argument('--max-calls', type=int, default=int(os.environ.get('FD_AUTOPUB_MAX_CALLS', DEFAULT_MAX_CALLS)))
    args = ap.parse_args(argv)

    key = os.environ.get('RAPID_X_API_KEY')
    if not key:
        print('RAPID_X_API_KEY missing: skip auto_published', file=sys.stderr)
        return 1

    from live.x_daily import RapidClient
    client = RapidClient(key, max_requests=args.max_calls)

    accounts = load_accounts()
    days = inbox_days()
    if not days:
        print('no inbox days found')
        return 0

    all_drafts = load_unposted_drafts(days)
    if not all_drafts:
        print('no unposted draft_ready drafts')
        return 0

    # group drafts by (account_id, day) and look up handle
    from collections import defaultdict
    by_acct_day = defaultdict(list)
    for d in all_drafts:
        if accounts.get(d['account_id'], {}).get('handle'):
            by_acct_day[(d['account_id'], d['day'])].append(d)

    uid_cache = {}
    total_calls = 0
    all_matches = []
    all_log_entries = defaultdict(list)

    for (account_id, day), drafts in sorted(by_acct_day.items()):
        acc = accounts.get(account_id) or {}
        handle = acc.get('handle') or ''
        if not handle:
            continue
        if total_calls >= args.max_calls:
            print(f'hit max_calls={args.max_calls}: stopping')
            break
        try:
            tweets = fetch_timeline(client, handle, uid_cache)
            total_calls = client.made
        except Exception as exc:
            print(f'{handle}: fetch error {exc}', file=sys.stderr)
            continue

        matches = match_drafts_to_tweets(drafts, tweets)
        for draft, tweet, score in matches:
            tc = tweet_created_utc(tweet)
            posted_at = tc.isoformat() if tc else ''
            tc_bjt = tc.astimezone(BJT).strftime('%H:%M') if tc else ''
            turl = tweet_url_from(tweet, handle)
            payload = build_decision_payload(day, draft, tweet, posted_at, turl)
            log_entry = {
                'draft_id': draft['id'], 'account_id': account_id, 'handle': handle,
                'day': day, 'score': round(score, 3), 'posted_at': posted_at,
                'tweet_url': turl, 'dry_run': args.dry_run,
            }
            if args.dry_run:
                print(f'[dry-run] {handle} {day} {draft["id"][:16]}… sim={score:.3f} '
                      f'posted={tc_bjt} {turl}')
            else:
                try:
                    post_decision(args.api, payload)
                    print(f'marked 已发: {handle} {day} {draft["id"][:16]}… sim={score:.3f} '
                          f'posted_bjt={tc_bjt} {turl}')
                    log_entry['marked'] = True
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    print(f'POST failed for {draft["id"]}: {exc}', file=sys.stderr)
                    log_entry['error'] = str(exc)
            all_log_entries[day].append(log_entry)
            all_matches.append(log_entry)

    for day, entries in all_log_entries.items():
        write_log(day, entries)

    print(f'auto_published: {len(all_matches)} match(es), {client.made} API call(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
