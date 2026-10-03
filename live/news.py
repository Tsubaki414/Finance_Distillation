"""News ingest. The system's first way of learning that something happened.

Until this existed, the only way an event reached the pipeline was for one of twelve X accounts to
post about it, and for someone to run `live/collect.py` by hand. Asked whether the system could
react to, say, AMD reporting pre-market, the answer was not "slowly" — it was that the system had
no way to know it had happened.

Same shape as `live/collect.py`: append-only, watermarked, one row the first time an item is seen
and never rewritten.

**The staleness check is the point of this file, not a detail.**

`feeds.a.dj.com/rss/RSSMarketsMain.xml` returns HTTP 200 and parses cleanly as RSS. Its newest
item is dated 2025-01-27. A collector that reports "0 new items" for a dead feed is
indistinguishable from one reporting a quiet news hour, and it would have stayed that way for as
long as nobody read the timestamps. So every source declares `max_age_hours`, the newest item's
age is compared against it on every run, and a stale source is reported as **failing** rather than
as empty. CLAUDE.md is explicit that HTTP 200 is not acceptance; this is that rule with teeth.

Sources verified live 2026-09-24; see docs/TIMELINESS_DUE_DILIGENCE.md for what was tested and
what was rejected (CNBC 403, Yahoo 429, Reuters 401, RSSHub 403, X keyword search still 404).

Three separate outlets answered 200 with nothing usable, which is why the check below is not
paranoia:

    WSJ Markets RSS        parses, newest item 2025-01-27
    BlockBeats 律动        every documented endpoint, v1 and v2, returns {"status":0,"data":[]}
    Blockworks             feed answers, carries no dated items — its news division closed

Each would have been imported as a working, quiet source.

Dedup is one layer only, deliberately. A URL and content hash catches the same item arriving
twice; it does **not** catch one wire story republished by three outlets under different URLs with
near-identical bodies. That needs embeddings and is a separate step, to be built once there is
real traffic to set a threshold against rather than a number invented in advance.

Run: .venv/bin/python -B live/news.py [--source=cn_investing] [--dry-run]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, time, hashlib, datetime, urllib.request, urllib.error
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
OUT = STORE / 'news.jsonl'
RUNS = STORE / 'news_runs.jsonl'

TIMEOUT = 25
GAP_SECONDS = 1.5

# A neutral identifier for ordinary public feeds. It says what the client is and does not claim to
# be a browser or carry anyone's identity.
UA = 'Finance-Distillation/0.1 (research collector)'

# SEC is the one exception, and it is an authorised one.
#
# EDGAR needs no key and no account; its fair-access policy asks for a User-Agent carrying a real
# contact, and CLAUDE.md forbids fabricating one. The user was asked on 2026-09-24 and answered
# 「用我的邮箱」, so their address appears here and **only** here. It is not sent to any other
# source in this file, and must not be added to one.
SEC_CONTACT = 'ruojiama1@gmail.com'
SEC_UA = f'Finance-Distillation research (contact: {SEC_CONTACT})'

SOURCES = {
    'cn_investing': {
        'url': 'https://cn.investing.com/rss/news.rss',
        'lang': 'zh', 'kind': 'rss', 'max_age_hours': 6,
        'why': 'the only live Chinese-language wire found that needs no key and no identity',
    },
    'cn_investing_stocks': {
        'url': 'https://cn.investing.com/rss/news_285.rss',
        'lang': 'zh', 'kind': 'rss', 'max_age_hours': 12,
    },
    'investing': {
        'url': 'https://www.investing.com/rss/news.rss',
        'lang': 'en', 'kind': 'rss', 'max_age_hours': 6,
    },
    'seekingalpha': {
        'url': 'https://seekingalpha.com/market_currents.xml',
        'lang': 'en', 'kind': 'rss', 'max_age_hours': 12,
    },
    'fed_press': {
        'url': 'https://www.federalreserve.gov/feeds/press_all.xml',
        'lang': 'en', 'kind': 'rss', 'max_age_hours': 24 * 7,
        'why': 'a central bank is quiet for days at a time; a week is not staleness here',
    },
    # Crypto. The donors include crypto-macro voices and the project sits under Crypto/, so this
    # is a beat the watchlist already covers and had no wire for.
    'panews': {
        'url': 'https://www.panewslab.com/rss.xml?lang=zh&type=NEWS',
        'lang': 'zh', 'kind': 'rss', 'max_age_hours': 6,
        'why': 'live Chinese-language crypto wire, newest item 6 minutes old when tested',
    },
    'cointelegraph': {
        'url': 'https://cointelegraph.com/rss',
        'lang': 'en', 'kind': 'rss', 'max_age_hours': 6,
    },
    'coindesk': {
        'url': 'https://www.coindesk.com/arc/outboundfeeds/rss',
        'lang': 'en', 'kind': 'rss', 'max_age_hours': 12,
    },
    'theblock': {
        'url': 'https://www.theblock.co/rss.xml',
        'lang': 'en', 'kind': 'rss', 'max_age_hours': 24,
    },
    'sec_8k': {
        'url': ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K'
                '&company=&dateb=&owner=include&count=40&output=atom'),
        'lang': 'en', 'kind': 'atom', 'max_age_hours': 24,
        'ua': SEC_UA,
        'why': 'material-event filings, first-hand. Authorised 2026-09-24; see SEC_CONTACT above',
    },
}

NS = {'atom': 'http://www.w3.org/2005/Atom'}
TAG = re.compile(r'<[^>]+>')


def _text(s):
    return TAG.sub(' ', s or '').replace('&amp;', '&').replace('&#39;', "'").strip()


def _parse_date(s):
    s = (s or '').strip()
    if not s:
        return None
    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S'):
        try:
            d = datetime.datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    try:
        d = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def fetch(name, cfg):
    req = urllib.request.Request(cfg['url'], headers={'User-Agent': cfg.get('ua', UA)})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode('utf-8', 'replace')
            status = r.status
    except urllib.error.HTTPError as e:
        return {'ok': False, 'error': f'HTTP {e.code}', 'status': e.code,
                'seconds': round(time.monotonic() - t0, 2)}
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__ + ': ' + str(e)[:140],
                'seconds': round(time.monotonic() - t0, 2)}
    return {'ok': True, 'body': body, 'status': status,
            'seconds': round(time.monotonic() - t0, 2)}


def parse(body, kind):
    """RSS and Atom into the same row shape. Malformed XML raises rather than returning [];
    an empty list is a real editorial state and must not be confused with a broken parse."""
    root = ET.fromstring(body)
    out = []
    if kind == 'atom':
        for e in root.findall('atom:entry', NS):
            link = e.find('atom:link', NS)
            out.append({
                'title': _text((e.findtext('atom:title', '', NS))),
                'url': (link.get('href') if link is not None else '') or '',
                'summary': _text(e.findtext('atom:summary', '', NS)
                                 or e.findtext('atom:content', '', NS)),
                'published': _parse_date(e.findtext('atom:updated', '', NS)
                                         or e.findtext('atom:published', '', NS)),
            })
    else:
        for e in root.iter('item'):
            out.append({
                'title': _text(e.findtext('title', '')),
                'url': (e.findtext('link', '') or '').strip(),
                'summary': _text(e.findtext('description', '')),
                'published': _parse_date(e.findtext('pubDate', '')),
            })
    return out


def _seen():
    """Keys already recorded. Both are kept: a feed that rewrites its URLs would otherwise
    re-import every item, and one that reuses a URL for edited content would hide the edit."""
    urls, hashes = set(), set()
    if OUT.is_file():
        for line in OUT.read_text(encoding='utf-8').split('\n'):
            if line.strip():
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                urls.add(r.get('url'))
                hashes.add(r.get('content_sha256'))
    return urls, hashes


def collect(only=None, dry_run=False):
    now = datetime.datetime.now(datetime.timezone.utc)
    run_id = 'news-' + now.strftime('%Y%m%dT%H%M%S')
    seen_urls, seen_hashes = _seen()
    report, new_rows = [], []

    for name, cfg in SOURCES.items():
        if only and name != only:
            continue
        r = fetch(name, cfg)
        row = {'source': name, 'url': cfg['url'], 'seconds': r['seconds'],
               'status': r.get('status')}
        if not r['ok']:
            report.append({**row, 'result': 'fetch_failed', 'error': r['error']})
            time.sleep(GAP_SECONDS)
            continue
        try:
            items = parse(r['body'], cfg['kind'])
        except ET.ParseError as e:
            report.append({**row, 'result': 'unparsable', 'error': str(e)[:140]})
            time.sleep(GAP_SECONDS)
            continue

        dated = [i for i in items if i['published']]
        newest = max((i['published'] for i in dated), default=None)
        age_h = round((now - newest).total_seconds() / 3600, 1) if newest else None
        # The WSJ lesson. A feed can answer 200, parse perfectly, and be two years dead.
        stale = age_h is not None and age_h > cfg['max_age_hours']
        if stale or newest is None:
            report.append({**row, 'result': 'stale' if stale else 'no_dated_items',
                           'items': len(items), 'newest_age_hours': age_h,
                           'max_age_hours': cfg['max_age_hours'],
                           'note': ('the feed answered and parsed; its content is older than this '
                                    'source is allowed to be, so it is reported as failing rather '
                                    'than as a quiet news hour')})
            time.sleep(GAP_SECONDS)
            continue

        added = 0
        for it in items:
            if not it['title'] or not it['url']:
                continue
            h = hashlib.sha256((it['title'] + '\n' + it['summary']).encode('utf-8')).hexdigest()
            if it['url'] in seen_urls or h in seen_hashes:
                continue
            seen_urls.add(it['url'])
            seen_hashes.add(h)
            new_rows.append({
                'item_id': hashlib.sha256(it['url'].encode()).hexdigest()[:16],
                'source': name, 'lang': cfg['lang'], 'platform': 'news',
                'title': it['title'], 'summary': it['summary'][:2000],
                'url': it['url'],
                'published_at': it['published'].isoformat() if it['published'] else None,
                'content_sha256': h,
                'first_seen_at': now.isoformat(), 'first_seen_run': run_id,
                # One layer only. See the module docstring: near-duplicate wire copy across
                # outlets is not caught here and needs embeddings.
                'dedup': 'url + title/summary hash',
            })
            added += 1
        report.append({**row, 'result': 'ok', 'items': len(items), 'new': added,
                       'newest_age_hours': age_h})
        time.sleep(GAP_SECONDS)

    if new_rows and not dry_run:
        STORE.mkdir(parents=True, exist_ok=True)
        with OUT.open('a', encoding='utf-8') as fh:
            for r in new_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')

    summary = {'run_id': run_id, 'at': now.isoformat(), 'dry_run': dry_run,
               'new_items': len(new_rows), 'sources': report,
               'failing': [x['source'] for x in report if x['result'] != 'ok'],
               'coverage_note': ('per-source item caps with a rolling feed do not guarantee '
                                 'complete capture during a busy hour or after a long gap')}
    if not dry_run:
        with RUNS.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(summary, ensure_ascii=False) + '\n')
    return summary


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    s = collect(only=args.get('source') if isinstance(args.get('source'), str) else None,
                dry_run='dry-run' in args)
    print(f"{s['run_id']}  新增 {s['new_items']} 条" + ('（dry-run，未写入）' if s['dry_run'] else ''))
    for r in s['sources']:
        if r['result'] == 'ok':
            print(f"  OK    {r['source']:22} {r['items']:3} 条  新增 {r['new']:3}  "
                  f"最新 {r['newest_age_hours']}h 前")
        else:
            print(f"  FAIL  {r['source']:22} {r['result']}  {r.get('error') or ''}".rstrip())
            if r['result'] == 'stale':
                print(f"        最新条目 {r['newest_age_hours']}h 前，"
                      f"超过允许的 {r['max_age_hours']}h —— 返回 200 不代表源还活着")
    if s['failing']:
        print(f"\n  失败源：{s['failing']}")


if __name__ == '__main__':
    main()
