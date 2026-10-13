"""Oct 13: bounded article-page fetch for summary-only feeds and HTML listings (FREEZE.md 2026-10-13 09:16).

A registry row opts in with `page_fetch`: {"allowed_hosts": [...], "body_selector": "<css>" (optional),
"listing_url": "...", "link_patterns": ["<path regex>"] (listing sites only), "max_pages": n}.
Rules: HTTPS + allow-listed hosts only (redirects re-checked), robots.txt honoured for our UA and '*', short
timeouts, a page that answers with a login/access/challenge page is skipped (never worked around), and the
caller only registers tier A/B sources. Extraction reuses source_recovery.extract_page (article/main or the
configured selector)."""
from __future__ import annotations

import re
import urllib.robotparser
from urllib.parse import urljoin, urlsplit

from live.adapters import common

UA = 'ContentLocalization/1.0 public-source-reader'
BLOCK = re.compile(r'request access|access denied|are you a robot|captcha|one moment, please|just a moment|'
                   r'enable javascript|sign in to continue|subscribe to (?:read|continue)', re.I)
_ROBOTS = {}


def _host_ok(url, hosts):
    p = urlsplit(url)
    return p.scheme == 'https' and not p.username and p.port in (None, 443) and p.hostname in set(hosts)


def robots_allowed(url, *, transport=None, timeout=10):
    p = urlsplit(url)
    base = f'{p.scheme}://{p.hostname}'
    rp = _ROBOTS.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            st, body = common.http_get(base + '/robots.txt', headers={'User-Agent': UA}, timeout=timeout, transport=transport)
        except Exception:
            st, body = 0, ''
        if st == 200:
            rp.parse(body.splitlines())
        elif st in (401, 403):
            rp.disallow_all = True
        else:
            rp.allow_all = True
        _ROBOTS[base] = rp
    return rp.can_fetch(UA, url)


def fetch_html(url, hosts, *, transport=None, timeout=20):
    if not _host_ok(url, hosts):
        return None, 'host_not_allowed'
    if not robots_allowed(url, transport=transport):
        return None, 'robots_disallow'
    if transport is not None:
        st, body = transport(url, {'User-Agent': UA})
        final = url
    else:
        import httpx
        r = httpx.get(url, headers={'User-Agent': UA}, timeout=timeout, follow_redirects=True)
        st, body, final = r.status_code, r.text, str(r.url)
        if not _host_ok(final, hosts):
            return None, 'redirect_off_host'
    if st != 200:
        return None, f'http_{st}'
    head = body[:4000]
    if BLOCK.search(re.sub(r'<[^>]+>', ' ', head)) and len(body) < 30000:
        return None, 'access_block'
    return {'url': final, 'raw': body, 'content_type': 'text/html', 'fetched_at': common_now()}, None


def common_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def article_text(url, cfg, *, transport=None):
    """(text, error). text is the full public article body or None."""
    from bs4 import BeautifulSoup
    from live.source_recovery import extract_page
    doc, err = fetch_html(url, cfg.get('allowed_hosts') or [], transport=transport)
    if err:
        return None, err
    sel = cfg.get('body_selector')
    if sel:
        root = BeautifulSoup(doc['raw'], 'html.parser').select_one(sel)
        if root is None:
            return None, 'body_selector_missing'
        doc = {**doc, 'raw': '<article>' + str(root) + '</article>'}
    try:
        out = extract_page(doc)
    except ValueError as exc:
        return None, 'extract_failed:' + str(exc)[:60]
    if not out.get('content_complete'):
        return None, 'teaser_or_partial'
    return out['text'], None


def listing_links(cfg, *, transport=None, limit=5):
    """[{url, title}] from an HTML listing page (link_patterns are full-path regexes)."""
    from bs4 import BeautifulSoup
    doc, err = fetch_html(cfg['listing_url'], cfg.get('allowed_hosts') or [], transport=transport)
    if err:
        return [], err
    out, seen = [], set()
    for a in BeautifulSoup(doc['raw'], 'html.parser').find_all('a', href=True):
        u = urljoin(doc['url'], a['href']).split('#')[0]
        if u in seen or not any(re.fullmatch(p, urlsplit(u).path) for p in cfg.get('link_patterns') or []):
            continue
        seen.add(u)
        out.append({'url': u, 'title': a.get_text(' ', strip=True)})
        if len(out) >= limit:
            break
    return out, None
