"""Live ingest. Polls the KOL watchlist on X and records what it finds, append-only.

This is the heartbeat of the system. It is not a corpus import: each run reaches the network,
and running it twice produces two engagement snapshots of the same post, which is what makes
acceleration measurable rather than asserted.

Two stores, both append-only:

  live/store/posts.jsonl        one row the first time a post is seen; never rewritten
  live/store/engagement.jsonl   one row per post per poll, so velocity has something to measure

Keyword search on X returns 404 — the CLI documents the endpoint as unstable — so discovery is
per-account rather than per-query. For this project that is the better shape anyway: the whole
system is built on a known set of authors, and polling them answers "what is this KOL database
saying right now" directly.

Run: .venv/bin/python -B live/collect.py [--accounts=8] [--per=10] [--dry-run]
"""
from pathlib import Path
import sys, json, subprocess, time, datetime, hashlib

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
SOURCES = ROOT / 'live/sources.json'

# X throttles a rapid loop. Requests are spaced, and a failure on one account never ends the run.
GAP_SECONDS = 4.0
TIMEOUT = 90


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def fetch_account(handle, n):
    """One account, via the twitter-cli backend agent-reach reports as active."""
    cmd = ['twitter', 'user-posts', f'@{handle}', '-n', str(n), '--json']
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'timeout', 'cmd': ' '.join(cmd),
                'latency_s': round(time.monotonic() - t0, 2)}
    out = (r.stdout or '').strip()
    if not out:
        return {'ok': False, 'error': 'empty stdout', 'stderr': (r.stderr or '')[-300:],
                'cmd': ' '.join(cmd), 'latency_s': round(time.monotonic() - t0, 2)}
    try:
        d = json.loads(out)
    except json.JSONDecodeError as e:
        return {'ok': False, 'error': f'not json: {e}', 'head': out[:200],
                'cmd': ' '.join(cmd), 'latency_s': round(time.monotonic() - t0, 2)}
    if not d.get('ok'):
        return {'ok': False, 'error': d.get('error'), 'cmd': ' '.join(cmd),
                'latency_s': round(time.monotonic() - t0, 2)}
    return {'ok': True, 'posts': d.get('data') or [], 'cmd': ' '.join(cmd),
            'latency_s': round(time.monotonic() - t0, 2)}


def known_ids():
    p = STORE / 'posts.jsonl'
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text().split('\n'):
        if line.strip():
            try:
                out.add(json.loads(line)['post_id'])
            except Exception:
                continue
    return out


def append(name, rows):
    if not rows:
        return
    STORE.mkdir(parents=True, exist_ok=True)
    with (STORE / name).open('a') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def normalise(post, src, run_id, seen_at):
    a = post.get('author') or {}
    m = post.get('metrics') or {}
    text = post.get('text') or ''
    return {
        'post_id': str(post.get('id')),
        'platform': 'x',
        'handle': src['handle'],
        'author_screen_name': a.get('screenName'),
        'author_id': a.get('id'),
        'author_verified': a.get('verified'),
        'watchlist_lang': src.get('lang'),
        'lang_reported': post.get('lang'),
        'beat': src.get('beat'),
        'in_corpus': src.get('in_corpus'),
        'text': text,
        'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'chars': len(text),
        'created_at': post.get('createdAtISO'),
        'is_retweet': post.get('isRetweet'),
        'retweeted_by': post.get('retweetedBy'),
        'urls': post.get('urls') or [],
        'media': [x.get('type') for x in (post.get('media') or [])],
        'first_seen_at': seen_at,
        'first_seen_run': run_id,
        'metrics_at_first_sight': m,
        'source': 'agent-reach / twitter-cli / user-posts',
    }


def snapshot(post, run_id, seen_at):
    m = post.get('metrics') or {}
    created = post.get('createdAtISO')
    age_h = None
    if created:
        try:
            t = datetime.datetime.fromisoformat(created)
            age_h = round((datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600, 3)
        except Exception:
            pass
    return {'post_id': str(post.get('id')), 'run_id': run_id, 'observed_at': seen_at,
            'age_hours': age_h, **{k: m.get(k) for k in
                                   ('likes', 'retweets', 'replies', 'quotes', 'views', 'bookmarks')}}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    cfg = json.loads(SOURCES.read_text())
    # `learning_accounts` are the English KOL sheet: polled for their writing, not treated as
    # corpus donors until a style band has been built and looked at.
    pool = list(cfg['x_accounts'])
    if args.get('learning'):
        pool = list(cfg.get('learning_accounts') or [])
    elif args.get('all'):
        pool += list(cfg.get('learning_accounts') or [])
    start = int(args.get('from', 0))
    accounts = pool[start:start + int(args.get('accounts', 99))]
    per = int(args.get('per', 10))
    run_id = 'ing-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    seen = known_ids()

    new_posts, snaps, failures, ok_accounts = [], [], [], 0
    for i, src in enumerate(accounts):
        got = fetch_account(src['handle'], per)
        stamp = now()
        if not got['ok']:
            failures.append({'handle': src['handle'], **{k: got[k] for k in got if k != 'ok'}})
        else:
            ok_accounts += 1
            for p in got['posts']:
                pid = str(p.get('id'))
                if not pid:
                    continue
                snaps.append(snapshot(p, run_id, stamp))
                if pid not in seen:
                    seen.add(pid)
                    new_posts.append(normalise(p, src, run_id, stamp))
        if i < len(accounts) - 1:
            time.sleep(GAP_SECONDS)

    if not args.get('dry-run'):
        append('posts.jsonl', new_posts)
        append('engagement.jsonl', snaps)

    report = {
        'run_id': run_id, 'started_from': SOURCES.name, 'finished_at': now(),
        'pool': ('learning' if args.get('learning') else 'all' if args.get('all') else 'core'),
        'pool_slice': [start, start + len(accounts)],
        'accounts_polled': len(accounts), 'accounts_ok': ok_accounts,
        'accounts_failed': len(failures), 'failures': failures,
        'new_posts': len(new_posts), 'engagement_snapshots': len(snaps),
        'store_total_posts': len(seen),
        'backend': 'agent-reach / twitter-cli',
        'dry_run': bool(args.get('dry-run')),
        'note': ('every figure here is what the network returned this run; a failed account is '
                 'reported, never silently skipped'),
    }
    if not args.get('dry-run'):
        (STORE / 'runs.jsonl').open('a').write(json.dumps(report, ensure_ascii=False) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    main()
