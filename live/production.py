"""Production defaults to localization_v1: source → account/language → exact
passages → translation → light localization → fidelity QA → human review queue.

Legacy event/packet helpers remain for retrieval and historical tests. --events
cannot generate legacy rewrites; --prepare may still prepare source material.
Nothing is posted. Legacy Evergreen is not part of the new main path.
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, time, datetime, hashlib, subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
sys.path.insert(0, str(ROOT / 'scripts'))

import news
import event_packet as ep
import draft_from_packet as dw
import persona_views as pv
import queue_store as qs
import public_writer
import analysis_corpus as ac

REPORTS = ROOT / 'live/store/reviews'
EVERGREEN_MD = ROOT / 'evergreen/lane/2026-09-27-ten.md'
CANDIDATES = ROOT / 'evergreen/principles/candidates.json'

# Hours after which a hot event is not written again unless new bodies arrive.
HOT_STALE_HOURS = 36
# Hours before the same evergreen theme may be written again, from a new angle.
THEME_COOLDOWN_HOURS = 24 * 7
# Hours before another theme in the same family (stop / position) may be written.
FAMILY_COOLDOWN_HOURS = 18
HOT_PER_RUN = 2
EVERGREEN_PER_RUN = 2
BODY_CHARS = 6000

# Stop, exit and position are one family. Do not write them back to back.
THEMES = (
    {'id': 'payoff', 'title': '先算错了亏多少', 'family': 'risk',
     'keywords': ('赔率', '止损', '止盈', '盈亏比', '风险收益')},
    {'id': 'stop', 'title': '止损是开仓的一部分', 'family': 'risk',
     'keywords': ('止损', '退出', '认错')},
    {'id': 'sizing', 'title': '仓位跟着判断走，不跟着情绪走', 'family': 'risk',
     'keywords': ('仓位', '回撤', '轻仓', '重仓')},
    {'id': 'regime', 'title': '趋势和震荡不要用同一套手', 'family': 'regime',
     'keywords': ('趋势', '震荡', '盘整')},
    {'id': 'sample', 'title': '对错要放到足够长的样本里看', 'family': 'probability',
     'keywords': ('样本', '胜率', '期望', '概率')},
    {'id': 'discipline', 'title': '交易是手段，不是日程', 'family': 'psychology',
     'keywords': ('纪律', '空仓', '在场', '心理')},
    {'id': 'confirm', 'title': '确认发生在动作里，不发生在预测里', 'family': 'execution',
     'keywords': ('确认', '进场', '条件')},
    {'id': 'edge', 'title': '别人的观点不是你的信息优势', 'family': 'information',
     'keywords': ('跟单', '信息', '优势', '观点')},
    {'id': 'environment', 'title': '先判断环境，再判断这笔单', 'family': 'regime',
     'keywords': ('环境', '单边', '轮动')},
    {'id': 'review', 'title': '复盘看计划还在不在，不看这一笔赚没赚', 'family': 'review',
     'keywords': ('复盘', '计划', '系统')},
)

# A reprint that names its source is not a second witness. Same table the
# packet already uses, kept here so a fetched body can be marked before
# admission. Not a new source list.
_CITE_NEEDLES = (
    ('citing cointelegraph', 'cointelegraph'),
    ('据 cointelegraph', 'cointelegraph'),
    ('据cointelegraph', 'cointelegraph'),
    ('citing seeking alpha', 'seekingalpha'),
    ('citing the block', 'theblock'),
    ('据 the block', 'theblock'),
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat()


def _parse(s):
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d


def _hours_since(s, now=None):
    d = _parse(s)
    if not d:
        return None
    return ((now or _now()) - d).total_seconds() / 3600


def load_rows():
    path = news.OUT
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding='utf-8').split('\n'):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _event_key(event):
    """Stable id for one event across runs.

    One proper name is not enough: OpenAI shows up in a hearing and in a
    training pause. The key is the name plus the other support tokens, so
    those stay two events, and a later ingest of the same pair still hits
    the same key.
    """
    support = sorted(t for t in (event.get('support') or []) if not str(t).startswith('alias:'))
    names = [t for t in support if t[:1].isascii() and t.isalpha() and len(t) >= 4]
    if names:
        return 'name:' + '+'.join(names[:3])
    if support:
        return 'tok:' + '+'.join(support[:3])
    ids = event.get('member_ids') or []
    return 'id:' + (ids[0] if ids else 'none')


def _body_cache_path():
    return ROOT / 'live/store/body_cache.json'


def load_body_cache():
    path = _body_cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def save_body_cache(cache):
    path = _body_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')


def fetch_body(url):
    """Public page text via the reader proxy already used in resolve_event.

    A short or empty reply is a failed read. The caller records that and
    does not invent the body.
    """
    if not url:
        return None
    cmd = ['curl', '-fsS', '--max-time', '40', 'https://r.jina.ai/' + url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
    except (subprocess.TimeoutExpired, OSError):
        return None
    text = (r.stdout or '').strip()
    if r.returncode != 0 or len(text) < 400:
        return None
    return text[:BODY_CHARS]


_NAV = re.compile(
    r'cointelegraph\.com/|image \d|advertisement|markets\]|category/|'
    r'doge\$|btc\$|eth\$|sol\$|xrp\$|bnb\$|utm_|subscribe|newsletter|'
    r'cookie|sign in|related articles|share this|follow us|'
    r'edited by|published time|min read|share on',
    re.I,
)
_PRICE_TICKER = re.compile(r'\b[A-Z]{2,6}\$\d')


def _article_blob(text):
    """Article body, not the reader header and not the site chrome.

    The proxy returns the whole page. Ticker strips and nav links were
    landing in claims, and the fact gate then treated those prices as
    invented numbers. The article is the paragraphs after the chrome.
    """
    blob = text or ''
    at = blob.find('Markdown Content:')
    if at >= 0:
        blob = blob[at + len('Markdown Content:'):]
    lines = []
    for line in blob.split('\n'):
        s = line.strip()
        if not s or s.startswith(('#', '[', '!', '|', '*')):
            continue
        if _NAV.search(s) or _PRICE_TICKER.search(s):
            continue
        if s.lower().startswith(('title:', 'url source:', 'published time:', 'warning:')):
            continue
        if len(s) < 40:
            continue
        lines.append(s)
    return '\n'.join(lines)


def _sentences(text, n=4):
    blob = _article_blob(text)
    parts = re.split(r'(?<=[.!?。！？])\s+', re.sub(r'\s+', ' ', blob))
    out = []
    for part in parts:
        part = part.strip(' #\n')
        if len(part) < 40 or _NAV.search(part) or _PRICE_TICKER.search(part):
            continue
        part = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', part)
        part = re.sub(r'https?://\S+', '', part)
        part = re.sub(r'\s+', ' ', part).strip()
        if len(part) < 40:
            continue
        out.append(part[:500])
        if len(out) >= n:
            break
    return out


def body_reads_for(members, cache, fetch=True):
    """Read bodies the cluster does not already have. Cache by item id.

    Facts are the article's own sentences. Direction and reprint checks
    read title + those sentences, which is the same surface the packet
    already uses. A failed fetch stays unread.
    """
    reads = []
    changed = False
    for member in members:
        iid = member.get('item_id') or member.get('id')
        url = member.get('url')
        cached = cache.get(iid) if iid else None
        if cached and cached.get('body'):
            body = cached['body']
            note = cached.get('note') or 'cache'
        elif fetch and url:
            body = fetch_body(url)
            note = 'fetched' if body else 'fetch_failed'
            if iid:
                cache[iid] = {'url': url, 'body': body, 'note': note, 'at': _iso()}
                changed = True
            time.sleep(0.4)
        else:
            body = None
            note = 'not_fetched'
        facts = []
        sentences = (cached or {}).get('sentences') if cached else None
        if sentences is None and body:
            sentences = _sentences(body)
        if sentences:
            cited = ''
            low = (body or '').lower()
            for needle, fam in _CITE_NEEDLES:
                if needle in low:
                    cited = ' 据 ' + fam + ' 报道。'
                    break
            for i, sent in enumerate(sentences, start=1):
                facts.append({
                    'id': f'f-{iid}-{i}',
                    'text': sent + cited,
                    'confidence': 'body_read',
                })
        reads.append({
            'id': iid,
            'read': bool(facts),
            'facts': facts,
            'note': note if facts else (note or 'unread'),
        })
    if changed:
        save_body_cache(cache)
    return reads


def rank_events(rows, ready_at, body_reads=None):
    """Every cluster that clears the hotness line, strongest first.

    run_live returns one packet. The loop needs the others too, so it
    ranks here and opens each one through the same packet builder.
    """
    items = [ep.normalize_live_item(r) if 'item_id' in r and 'tier' not in r else r for r in rows]
    if body_reads:
        ep.attach_body_reads(items, body_reads)
    found = ep.detect_live_events(items, window_hours=72.0)
    scored = []
    for event in found:
        heat = ep.live_hotness(event)
        read_n = sum(1 for m in event['members'] if m.get('body_read'))
        scored.append({
            'heat': heat,
            'event': event,
            'bodies_read': read_n,
            'n': len(event['members']),
        })
    scored.sort(key=lambda x: (x['heat']['score'], x['bodies_read'], x['n']), reverse=True)
    return scored, items


def _ordered_open(opened, queue):
    """Unwritten events first. A repeat run should meet a new story."""
    fresh, seen = [], []
    for row in opened:
        event = row['event']
        key = _event_key({
            'support': event.get('support'),
            'member_ids': [ep._item_id(m) for m in event['members']],
        })
        if (queue.get('events') or {}).get(key, {}).get('wrote'):
            seen.append(row)
        else:
            fresh.append(row)
    return fresh + seen


def open_packet(event, ready_at):
    retrieval = ep.retrieve(event, event['members'])
    packet = ep.packet_from_live(event, retrieval, ready_at)
    heat = ep.live_hotness(event)
    angle = ep.select_live_angle(packet, heat)
    return packet, angle, heat


def _fingerprint(packet):
    ids = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        if fact.get('admission') in ('official', 'two_independent_major', 'single_major_attributed'):
            ids.append(fact.get('fact_id') or fact.get('text', '')[:40])
    ids.sort()
    return hashlib.sha256('|'.join(ids).encode('utf-8')).hexdigest()[:16]


def _freshness(event, prior, now):
    """Stale means we have held it too long, not that the wire is old.

    A story published yesterday and first seen on this run is still news.
    The clock starts at first_seen. A story we already opened and then
    left for HOT_STALE_HOURS is the one that stops.
    """
    seen = (prior or {}).get('first_seen_at') or event.get('first_seen_at')
    age = _hours_since(seen, now)
    if age is not None and age > HOT_STALE_HOURS and (prior or {}).get('last_seen_at'):
        return 'stale'
    if prior and prior.get('last_draft_at'):
        return 'seen'
    return 'fresh'


def _major_new_info(packet, prior):
    if not prior:
        return True
    return _fingerprint(packet) != prior.get('fingerprint')


def _near_duplicate(text, others):
    """Same-language run against drafts already in the queue. No new model."""
    if not text or not others:
        return None
    # Evergreen themes are compared to evergreen drafts. Hot drafts are
    # compared to hot drafts. A shared word like 止损 is not a hot event.
    try:
        from content.originality import longest_shared_run, _tokens, _language_of
    except Exception:
        return None
    lang = _language_of(text)
    mine = _tokens(text, lang)
    # Caller passes the comparison set. Hot passes hot drafts. Evergreen
    # passes earlier drafts of the same theme.
    best_id, best = None, 0
    for other in others:
        body = other.get('text') or ''
        if not body:
            continue
        if _language_of(body) != lang:
            continue
        run = longest_shared_run(mine, _tokens(body, lang))
        if run > best:
            best, best_id = run, other.get('opportunity_id')
    # Near-duplicate is a long shared run, the same bar originality uses
    # to call a paste. Shorter overlap is two pieces about one event.
    ceiling = 20 if lang == 'zh' else 12
    if best >= ceiling:
        return best_id
    return None


def _qa_public(result):
    facts = result.get('fact_qa') or {}
    original = result.get('originality_qa') or {}
    if result.get('content_status') == 'passed_by_persona':
        return 'skip'
    if result.get('content_status') == 'not_drafted':
        return 'skip'
    if facts.get('status') == 'passed' and original.get('status') == 'passed':
        return 'passed'
    return 'failed'


def _failure_kind(result, note):
    if note and note != 'fetched' and note != 'cache':
        return None
    status = result.get('content_status')
    if status in ('draft_ready', 'passed_by_persona'):
        return None
    why = ((result.get('draft') or {}).get('why') or '')
    if 'model unavailable' in why or 'revise failed' in why:
        return 'writer'
    findings = (result.get('fact_qa') or {}).get('findings') or []
    codes = {f.get('code') for f in findings}
    if codes & {'new_concrete_fact', 'direct_fact_conflict', 'obvious_source_copy'}:
        return 'writer'
    if status == 'blocked':
        return 'writer'
    return None


def hot_pass(queue, rows, ready_at, fetch_bodies=True, write=True, limit=HOT_PER_RUN):
    """Detect, open, and write. Returns the events this run looked at."""
    now = _parse(ready_at) or _now()
    cache = load_body_cache()
    scored, _items = rank_events(rows, ready_at)
    opened = _ordered_open([row for row in scored if row['heat'].get('open_packet')], queue)
    looked = []
    written = 0
    for row in opened:
        if written >= limit:
            break
        event = row['event']
        key = _event_key({
            'support': event.get('support'),
            'member_ids': [ep._item_id(m) for m in event['members']],
        })
        prior = queue['events'].get(key) or {}
        members = event['members']
        # Do not pay for another body read when this event is already
        # written and nothing in the cluster is new.
        member_ids = [ep._item_id(m) for m in members]
        known_ids = set(prior.get('member_ids') or [])
        new_members = [i for i in member_ids if i not in known_ids]
        # Body fetches happen in prepare(). A run that writes does not
        # open the network for every remaining cluster.
        reads = body_reads_for(members, cache, fetch=fetch_bodies)
        ep.attach_body_reads(members, reads)
        packet, angle, heat = open_packet(event, ready_at)
        freshness = _freshness({
            'first_published_at': event.get('first_published_at'),
            'first_seen_at': event.get('first_seen_at'),
        }, prior, now)
        new_info = _major_new_info(packet, prior)
        record = {
            'event_key': key,
            'title': packet.get('event') or ' '.join((event.get('support') or [])[:4]),
            'decision': angle.get('decision'),
            'why': angle.get('why'),
            'hotness': heat.get('score'),
            'freshness': freshness,
            'new_info': new_info,
            'personas': {},
            'support': event.get('support'),
            'first_seen_at': event.get('first_seen_at'),
            'first_published_at': event.get('first_published_at'),
            'member_n': len(event['members']),
            'bodies_read': sum(1 for m in event['members'] if m.get('body_read')),
            'basis': packet.get('retrieval_basis'),
        }
        skip_reason = None
        if freshness == 'stale' and not new_info:
            skip_reason = 'stale'
        elif prior.get('wrote'):
            skip_reason = 'already_written'
        if skip_reason or not write or angle.get('decision') != 'POST':
            for view in pv.VIEWS:
                record['personas'][view['id']] = 'skip' if angle.get('decision') != 'POST' else skip_reason
            if angle.get('decision') != 'POST':
                _record_skip(queue, key, packet, angle, freshness, ready_at, record)
            looked.append(record)
            queue['events'][key] = {
                **prior,
                'fingerprint': _fingerprint(packet),
                'last_seen_at': ready_at,
                'first_seen_at': prior.get('first_seen_at') or event.get('first_seen_at'),
                'member_ids': member_ids,
                'decision': angle.get('decision'),
                'title': record['title'],
            }
            qs.save(queue)
            continue
        # Persona picks from the rewrite material. It does not call the
        # local model, and it does not invent an angle before the writer
        # has seen the analysts. A persona with nothing admitted still
        # skips only when the packet itself has no facts.
        decisions = []
        admitted = fact_lines(packet)
        for view in pv.VIEWS:
            if not admitted:
                decisions.append({
                    'persona_id': view['id'], 'name': view['name'],
                    'interested': False, 'why_not': 'no admitted facts',
                })
                continue
            decisions.append({
                'persona_id': view['id'], 'name': view['name'],
                'interested': True,
                'angle': None,
                'interpretation': '',
            })
        matches = ac.match_event({
            'support': event.get('support'),
            'title': record.get('title'),
            'source_views': packet.get('source_views'),
        })
        if not matches:
            # Corpus first. A directed search only when the recent window
            # has nobody on this event.
            try:
                extra = ac.search_event({
                    'support': event.get('support'),
                    'title': record.get('title'),
                    'source_views': packet.get('source_views'),
                })
            except Exception:
                extra = []
            if extra:
                ac.save(ac.load() + extra)
                matches = ac.match_event({
                    'support': event.get('support'),
                    'title': record.get('title'),
                    'source_views': packet.get('source_views'),
                })
        rewrite = ac.rewrite_from_matches(matches)
        record['analysis_found'] = [
            {'author': m.get('author'), 'source': m.get('source')} for m in matches
        ]
        wrote_any = False
        for dec in decisions:
            pid = dec.get('persona_id')
            if not dec.get('interested'):
                record['personas'][pid] = 'skip'
                _push(queue, _opportunity(
                    kind='hot', persona=pid, topic=record['title'],
                    packet_ref=key, angle=None, status='skipped',
                    qa='skip', freshness=freshness, text='',
                    created_at=ready_at, why=dec.get('why_not'),
                    event_id=packet.get('event_id'),
                    failure_kind='writer' if 'model unavailable' in (dec.get('why_not') or '') else None,
                ))
                continue
            if prior.get('personas', {}).get(pid) and not new_info:
                record['personas'][pid] = 'skip'
                continue
            if prior.get('blocked_personas', {}).get(pid) and not new_info:
                record['personas'][pid] = 'skip'
                continue
            draft_at = _iso()
            try:
                result = write_hot_draft(packet, pid, dec.get('angle'), rewrite)
            except Exception as exc:
                result = {
                    'text': '',
                    'fact_qa': None,
                    'originality_qa': None,
                    'content_status': 'blocked',
                    'draft_ready': None,
                    'why': 'writer unavailable: ' + type(exc).__name__,
                }
            text = result.get('text') or ''
            # Same event, same analysis. Shared fact lines are not a duplicate:
            # three personas may cite the same wire and still say different things.
            dup = _near_duplicate(dec.get('interpretation') or '', [
                {
                    'opportunity_id': o.get('opportunity_id'),
                    'text': (o.get('audit') or {}).get('interpretation') or '',
                }
                for o in queue['opportunities']
                if o.get('type') == 'hot' and o.get('event_id') == packet.get('event_id')
            ])
            qa = _qa_public(result)
            status = result.get('content_status') or 'not_drafted'
            if dup:
                status = 'duplicate'
                qa = 'skip'
            first_seen = event.get('first_seen_at') or event.get('first_published_at')
            lag = None
            if result.get('draft_ready') and first_seen:
                a, b = _parse(first_seen), _parse(result['draft_ready'])
                if a and b:
                    lag = round((b - a).total_seconds())
            unread_notes = [m.get('read_note') or m.get('confidence')
                            for m in event['members'] if not m.get('body_read')]
            failure = _failure_kind(result, None)
            if status != 'draft_ready' and not any(m.get('body_read') for m in event['members']):
                failure = 'source'
            opp = _opportunity(
                kind='hot', persona=pid, topic=record['title'],
                packet_ref=key, angle=dec.get('angle'), status=status,
                qa=qa, freshness=freshness, text=text if status == 'draft_ready' else '',
                created_at=ready_at, why=dec.get('why_not') or (result.get('draft') or {}).get('why'),
                event_id=packet.get('event_id'),
                generated_at=result.get('draft_ready'),
                lag=lag, duplicate_of=dup, failure_kind=failure,
                findings=(result.get('fact_qa') or {}).get('findings'),
            )
            opp['audit'] = {
                'fact_qa': result.get('fact_qa'),
                'originality': (result.get('originality_qa') or {}).get('status'),
                'unread': unread_notes,
                'basis': packet.get('retrieval_basis'),
                'interpretation': dec.get('interpretation'),
                'fact_sources': fact_sources(packet),
                'analysis_sources': [
                    {'author': m.get('author'), 'source': m.get('source'), 'url': m.get('url')}
                    for m in matches
                ],
                'writer': result.get('model'),
            }
            _push(queue, opp)
            record['personas'][pid] = 'draft' if status == 'draft_ready' else status
            prior.setdefault('personas', {})[pid] = opp['opportunity_id']
            if status == 'draft_ready':
                wrote_any = True
            elif status == 'blocked':
                prior.setdefault('blocked_personas', {})[pid] = opp['opportunity_id']
            qs.save(queue)
        if wrote_any:
            written += 1
            prior['wrote'] = True
            prior['last_draft_at'] = ready_at
        prior['fingerprint'] = _fingerprint(packet)
        prior['last_seen_at'] = ready_at
        prior['first_seen_at'] = prior.get('first_seen_at') or event.get('first_seen_at')
        prior['member_ids'] = member_ids
        prior['decision'] = angle.get('decision')
        prior['title'] = record['title']
        queue['events'][key] = prior
        looked.append(record)
        qs.save(queue)
    return {
        'clusters': len(scored),
        'opened': len(opened),
        'looked': looked,
    }


def _record_skip(queue, key, packet, angle, freshness, ready_at, record):
    """A NO POST still enters the queue, so the review report can show it."""
    existing = [o for o in queue['opportunities']
                if o.get('event_id') == packet.get('event_id') and o.get('draft_status') == 'no_post']
    if existing:
        return
    _push(queue, _opportunity(
        kind='hot', persona=None, topic=record['title'],
        packet_ref=key, angle=None, status='no_post',
        qa='skip', freshness=freshness, text='',
        created_at=ready_at, why=angle.get('why'),
        event_id=packet.get('event_id'),
        failure_kind='source' if 'body' in (angle.get('why') or '') or 'hotness' in (angle.get('why') or '') else None,
    ))


def _source_packet(item, peers, checks):
    """A packet the existing QA can read.

    The approved post is the writing library. A checked figure, when one
    exists, is the only admitted fact. News is not invited in as material.
    """
    views = [{
        'source_id': item.get('source'),
        'name': item.get('author'),
        'claim': (item.get('text') or '')[:1800],
        'url': item.get('url'),
        'tier': 'ANALYSIS',
    }]
    for peer in peers:
        views.append({
            'source_id': peer.get('source'),
            'name': peer.get('author'),
            'claim': (peer.get('text') or '')[:1800],
            'url': peer.get('url'),
            'tier': 'ANALYSIS',
        })
    facts = []
    for row in checks:
        if not row.get('supported'):
            continue
        facts.append({
            'fact_id': 'check-' + str(len(facts) + 1),
            'source_id': row.get('news_source') or 'news',
            'admission': 'single_major_attributed',
            'text': row.get('news_text') or row.get('span') or '',
            'url': row.get('news_url'),
        })
    author = item.get('author') or item.get('source')
    return {
        'event_id': 'src-' + (item.get('id') or ''),
        'event': (item.get('title') or (item.get('text') or '')[:48] or author),
        'primary_facts': facts,
        'downgraded_claims': [],
        'source_views': views,
        'retrieval_basis': 'source-first ' + (item.get('action') or ''),
    }


def _news_rows(limit=400):
    path = news.OUT
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding='utf-8').split('\n'):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def verify_cited_facts(text, news_rows=None):
    """Check a concrete figure the post already stated.

    A miss is a note for the writer, not a second essay. No number in the
    post means there is nothing to check.
    """
    spans = ac.cited_fact_queries(text)
    if not spans:
        return []
    rows = news_rows if news_rows is not None else _news_rows()
    out = []
    for span in spans:
        needle = re.sub(r'\s+', '', span).lower()
        # "$235 billion" and "2350亿美元" will not share a needle. Match the
        # digits the post used, against a news line that also has them.
        digits = re.sub(r'\D', '', span)
        hit = None
        if len(digits) >= 2:
            for row in rows:
                blob = (row.get('title') or '') + ' ' + (row.get('summary') or '')
                compact = re.sub(r'\s+', '', blob).lower()
                if needle and needle in compact:
                    hit = row
                    break
                if digits and digits in re.sub(r'\D', '', blob):
                    hit = row
                    break
        out.append({
            'span': span,
            'supported': bool(hit),
            'news_source': None if not hit else hit.get('source'),
            'news_url': None if not hit else hit.get('url'),
            'news_text': None if not hit else ((hit.get('title') or '') + ' ' + (hit.get('summary') or ''))[:240],
        })
    return out


def source_first_pass(queue, ready_at, limit=20, write=True, rows=None,
                      per_source=2, hours=24, pipeline=None, persist=True):
    """Source → route → exact passages → translation → localization → fidelity QA.

    Filter completed versions BEFORE source quotas/limit. No writer or Evergreen
    calls occur in dry runs. The old REWRITE/MERGE classifier is bypassed.
    """
    from live.distillation import Pipeline, export
    from live.distillation_source import source_record
    pipeline = pipeline or Pipeline()
    all_rows = list(rows if rows is not None else ac.load())
    pending = []
    for row in all_rows:
        source = pipeline.normalize_source(row)
        key = 'loc:' + pipeline.key(source)
        prior = queue.get('events', {}).get(key) or {}
        if prior.get('terminal'):
            continue
        pending.append(row)
    window = ac.intake(pending, per_source=per_source, hours=hours, now=_parse(ready_at))[:limit]
    looked = []
    for row in window:
        title = (row.get('author') or '') + ' · ' + (row.get('title') or row.get('text') or '')[:80]
        if not write:
            looked.append({'title': title, 'action': 'NOT_RUN', 'reason': 'dry run', 'personas': {}})
            continue
        result = pipeline.run(row)
        source = result['source']
        key = 'loc:' + pipeline.key(source)
        route = result.get('route') or {}
        pid = result.get('persona')
        status = result['draft_status']
        # Replayed attempts repair a missing queue row but cannot append duplicates.
        existing = next((o for o in queue['opportunities']
                         if o.get('attempt_ref') == result['attempt_ref'] or
                         (result.get('draft_id') and o.get('draft_id') == result['draft_id'])), None)
        if not existing:
            opp = _opportunity(kind='hot', persona=pid, topic=title, packet_ref=key,
                               angle=None, status=status, qa=result['qa_status'], freshness='fresh',
                               text=result['text'], created_at=ready_at, why=result['why'],
                               generated_at=result['finished_at'] if status == 'draft_ready' else None,
                               findings=(result.get('qa') or {}).get('findings'))
            for field in ('pipeline_mode', 'pipeline_version', 'run_id', 'draft_id', 'account_id',
                          'account_profile_version', 'source_language', 'target_language',
                          'source_ref', 'attempt_ref', 'draft_version'):
                opp[field] = result.get(field)
            opp['source_hash'] = source['source_hash']
            opp['selection_id'] = (result.get('selection') or {}).get('selection_id')
            opp['translation_id'] = (result.get('translation') or {}).get('translation_id')
            opp['audit'] = {'basis': 'localization_v1', 'url': source.get('url'),
                            'analysis_sources': [{'author': source.get('author_name'), 'url': source.get('url')}],
                            'route': route, 'provenance_ref': result['source_ref']}
            existing = _push(queue, opp)
            export(result, pipeline.store / 'exports' / result['run_id'])
        queue.setdefault('events', {})[key] = {
            # A failed version remains inspectable; retries are explicit, never a paid loop.
            'terminal': True,
            'wrote': status == 'draft_ready', 'last_seen_at': ready_at,
            'decision': route.get('decision'), 'attempt_ref': result['attempt_ref']}
        looked.append({'title': title, 'action': route.get('decision') or status.upper(),
                       'decision': 'POST' if status == 'draft_ready' else 'NO_POST',
                       'reason': result['why'], 'persona': pid, 'account_id': result.get('account_id'),
                       'target_language': result.get('target_language'), 'draft': result['text'],
                       'personas': {pid: status} if pid else {}, 'opportunity_id': existing['opportunity_id']})
        if persist:
            qs.save(queue)
    return {'clusters': len(window), 'opened': len(looked), 'looked': looked}


def fact_lines(packet):
    """What happened, from admitted claims. Not an interpretation."""
    rows = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        if fact.get('admission') not in (
                'official', 'two_independent_major', 'single_major_attributed',
                'wire_beside_official'):
            continue
        text = (fact.get('text') or '').strip()
        if text and text not in rows:
            rows.append(text)
    return rows[:8]


def fact_sources(packet):
    names = []
    for view in packet.get('source_views') or []:
        if view.get('tier') not in ('PRIMARY_OFFICIAL', 'WIRE_MAJOR'):
            continue
        name = view.get('name') or view.get('source_id')
        if name and name not in names:
            names.append(name)
    return names


def write_hot_draft(packet, persona_id, angle, rewrite):
    """Public copy from the two layers. QA stays the existing gate.

    No rewrite material means a short factual note, which the writer is
    already told to produce. It does not mean the local model fills in
    an analysis.
    """
    draft = public_writer.write_public(
        packet, persona_id, angle, cache={}, backend_name='relay',
        fact_pack=fact_lines(packet), rewrite=rewrite,
    )
    text = (draft.get('text') or '').strip()
    wrapped = {
        'text': text,
        'lang': 'zh',
        'attribution': 'event',
        'sentences': [],
        'source_views': packet.get('source_views') or [],
    }
    # The fact gate compares the draft with the packet. Analyst excerpts
    # are not admitted facts, so a number that exists only in a rewrite
    # still fails. That is the boundary.
    facts = dw.fact_qa(wrapped, packet)
    original = dw.originality_qa(wrapped, packet)
    blocked = not text or facts['status'] != 'passed' or original['status'] != 'passed'
    return {
        'text': text,
        'model': draft.get('model'),
        'provider': draft.get('provider'),
        'fell_back': draft.get('fell_back'),
        'sources_used': draft.get('sources_used'),
        'fact_qa': facts,
        'originality_qa': original,
        'content_status': 'blocked' if blocked else 'draft_ready',
        'draft_ready': _iso() if text else None,
    }


def _opportunity(**kw):
    return {
        'opportunity_id': None,
        'type': kw['kind'],
        'created_at': kw['created_at'],
        'priority': 1 if kw.get('status') == 'draft_ready' else 0,
        'persona': kw.get('persona'),
        'topic': kw.get('topic'),
        'source_packet': kw.get('packet_ref'),
        'evergreen_topic': kw.get('theme_id'),
        'selected_angle': kw.get('angle'),
        'draft_status': kw.get('status'),
        'qa_status': kw.get('qa'),
        'review_status': 'pending',
        'freshness': kw.get('freshness'),
        'duplicate_of': kw.get('duplicate_of'),
        'text': kw.get('text') or '',
        'generated_at': kw.get('generated_at'),
        'reaction_lag_seconds': kw.get('lag'),
        'event_id': kw.get('event_id'),
        'theme_id': kw.get('theme_id'),
        'family': kw.get('family'),
        'version': 1,
        'failure_kind': kw.get('failure_kind'),
        'why': kw.get('why'),
        'qa_findings': kw.get('findings') or [],
    }


def _push(queue, opp):
    n = len(queue['opportunities']) + 1
    opp['opportunity_id'] = qs.new_id('opp', n)
    queue['opportunities'].append(opp)
    return opp


def _theme_sections():
    text = EVERGREEN_MD.read_text(encoding='utf-8') if EVERGREEN_MD.is_file() else ''
    sections = {}
    current = None
    buf = []
    for line in text.split('\n'):
        m = re.match(r'^## \d+\. (.+)$', line)
        if m:
            if current:
                sections[current] = '\n'.join(buf).strip()
            current = m.group(1).strip()
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current:
        sections[current] = '\n'.join(buf).strip()
    return sections


def _candidate_lines(theme, limit=4):
    """Statements already in the candidate bank. Not a new extraction."""
    if not CANDIDATES.is_file():
        return []
    try:
        data = json.loads(CANDIDATES.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return []
    rows = data if isinstance(data, list) else data.get('items') or data.get('candidates') or []
    if not isinstance(rows, list):
        return []
    keys = theme['keywords']
    hits = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        blob = ' '.join(str(row.get(k) or '') for k in ('statement', 'principle', 'text', 'summary'))
        if any(k in blob for k in keys):
            line = (row.get('statement') or row.get('principle') or row.get('text') or '').strip()
            if line and line not in hits:
                hits.append(line)
        if len(hits) >= limit:
            break
    return hits


def _pick_themes(queue, n, now):
    """Themes not used recently, and not in a family that just ran."""
    themes_state = queue.setdefault('themes', {})
    recent_families = {}
    for theme in THEMES:
        state = themes_state.get(theme['id']) or {}
        last = state.get('last_generated_at')
        age = _hours_since(last, now)
        if age is not None and age < FAMILY_COOLDOWN_HOURS:
            recent_families[theme['family']] = last
    picked = []
    # Rotate by oldest last-generated, then by list order.
    ordered = sorted(THEMES, key=lambda t: themes_state.get(t['id'], {}).get('last_generated_at') or '')
    for theme in ordered:
        state = themes_state.get(theme['id']) or {}
        age = _hours_since(state.get('last_generated_at'), now)
        if age is not None and age < THEME_COOLDOWN_HOURS:
            continue
        if theme['family'] in recent_families and theme['id'] not in {p['id'] for p in picked}:
            # A sibling just ran. Skip unless nothing else is available.
            continue
        picked.append(theme)
        recent_families[theme['family']] = _iso(now)
        if len(picked) >= n:
            break
    if len(picked) < n:
        for theme in ordered:
            if theme in picked:
                continue
            state = themes_state.get(theme['id']) or {}
            age = _hours_since(state.get('last_generated_at'), now)
            if age is not None and age < THEME_COOLDOWN_HOURS:
                continue
            picked.append(theme)
            if len(picked) >= n:
                break
    return picked


def _evergreen_draft(theme, section, lines):
    """Standalone piece. The section is the already-written theme text.

    Candidate statements are named as notes, not as quotes. No live event
    is attached. No model call: the ten pieces are the lane, and a run
    selects among them rather than regenerating the principle.
    """
    body = section.strip()
    # Drop the internal "可发主题" line from the public draft.
    public = '\n'.join(
        line for line in body.split('\n')
        if not line.startswith('可发主题')
    ).strip()
    note = ''
    if lines:
        note = '\n\n笔记里相近的说法还有：' + '；'.join(lines[:2]) + '。这些是转述，不是原话。'
    return public + note


def _evergreen_angle(theme, version, lines):
    """A later version has to be a different angle, not the same page again.

    Version 1 is the theme as already written. A later run, after cooldown,
    leads with a candidate statement the first version did not lead with.
    If the bank has nothing left to rotate, the theme waits.
    """
    if version <= 1 or not lines:
        return theme['title'], None
    idx = (version - 2) % len(lines)
    return lines[idx], lines[idx]


def evergreen_pass(queue, ready_at, n=EVERGREEN_PER_RUN):
    now = _parse(ready_at) or _now()
    sections = _theme_sections()
    picked = _pick_themes(queue, n, now)
    out = []
    for theme in picked:
        section = sections.get(theme['title']) or ''
        if not section:
            continue
        lines = _candidate_lines(theme)
        state = queue['themes'].get(theme['id']) or {}
        version = int(state.get('versions') or 0) + 1
        angle, lead = _evergreen_angle(theme, version, lines)
        if version > 1 and not lead:
            out.append({'theme': theme['title'], 'status': 'skip', 'opportunity_id': None,
                        'why': 'cooldown elapsed but no unused angle in the candidate bank'})
            continue
        text = _evergreen_draft(theme, section, lines)
        if lead:
            text = '另一个角度：' + lead + '\n\n' + text
        prior_text = [
            o for o in queue['opportunities']
            if o.get('type') == 'evergreen' and o.get('theme_id') == theme['id'] and o.get('text')
        ]
        dup = _near_duplicate(text, prior_text)
        status = 'duplicate' if dup else 'draft_ready'
        opp = _opportunity(
            kind='evergreen', persona=None, topic=theme['title'],
            packet_ref=None, angle=angle, status=status,
            qa='passed' if status == 'draft_ready' else 'skip',
            freshness='fresh', text=text if status == 'draft_ready' else '',
            created_at=ready_at, theme_id=theme['id'], family=theme['family'],
            generated_at=ready_at, duplicate_of=dup,
        )
        opp['version'] = version
        opp['evergreen_topic'] = theme['id']
        _push(queue, opp)
        queue['themes'][theme['id']] = {
            'title': theme['title'],
            'family': theme['family'],
            'last_generated_at': ready_at,
            'versions': version,
            'last_opportunity': opp['opportunity_id'],
        }
        qs.save(queue)
        out.append({'theme': theme['title'], 'status': 'draft' if status == 'draft_ready' else status,
                    'opportunity_id': opp['opportunity_id']})
    return out


def review_report(queue, hot, evergreen, run_id):
    """The public review package. Audit stays in the queue JSON."""
    lines = [f'# Review {run_id}', '']
    lines.append('HOT')
    lines.append('')
    if not hot.get('looked'):
        lines.append('（这一轮没有过线的 event）')
        lines.append('')
    for ev in hot.get('looked') or []:
        lines.append(ev['title'])
        for pid, label in (('macro', 'Macro'), ('industry', 'Industry'), ('trading', 'Trading')):
            state = (ev.get('personas') or {}).get(pid, 'skip')
            shown = 'draft' if state == 'draft' else 'skip'
            lines.append(f'{label}: {shown}')
        lines.append('')
    lines.append('EVERGREEN')
    lines.append('')
    if not evergreen:
        lines.append('（这一轮没有新的 evergreen）')
        lines.append('')
    for row in evergreen:
        lines.append(row['theme'])
        lines.append('draft' if row['status'] == 'draft' else row['status'])
        lines.append('')
    lines.append('---')
    lines.append('')
    # Drafts produced this run, public fields only.
    created = [o for o in queue['opportunities'] if o.get('created_at') == run_id or o.get('generated_at') == run_id]
    # run stamps created_at with ready_at, which is the run id's timestamp.
    lines.append('## 候选稿')
    lines.append('')
    drafts = [o for o in queue['opportunities']
              if o.get('draft_status') == 'draft_ready' and o.get('text')
              and o.get('created_at') == (hot.get('ready_at') or o.get('created_at'))]
    return '\n'.join(lines)


def render_backlog(queue):
    """Every draft still waiting for a human. This is the morning pile."""
    lines = ['待挑', '']
    drafts = [o for o in queue['opportunities']
              if o.get('draft_status') == 'draft_ready' and o.get('text')
              and o.get('review_status') == 'pending']
    if not drafts:
        lines.append('（队列里没有待挑的稿）')
        return '\n'.join(lines) + '\n'
    for opp in drafts:
        lines.append(f"### {opp['opportunity_id']}  {opp['type']}  {opp.get('topic')}")
        lines.append('')
        if opp.get('pipeline_mode') == 'localization_v1':
            from live.distillation import review_markdown
            attempt = Path(opp['attempt_ref'])
            if attempt.is_file():
                lines.append(review_markdown(json.loads(attempt.read_text())))
                continue
        lines.append(opp['text'].strip())
        lines.append('')
        lines.append(f"persona: {opp.get('persona') or '—'}")
        lines.append(f"angle: {opp.get('selected_angle') or '—'}")
        if opp['type'] == 'hot':
            audit = opp.get('audit') or {}
            facts = ', '.join(audit.get('fact_sources') or []) or '—'
            found = audit.get('analysis_sources') or []
            names = ', '.join(
                (a.get('author') or a.get('source') or '') for a in found
            ) or '无'
            lines.append(f"事实来源: {facts}")
            lines.append(f"分析来源: {names}")
            lag = opp.get('reaction_lag_seconds')
            lines.append(f"reaction lag: {lag}s" if lag is not None else 'reaction lag: —')
        else:
            lines.append(f"evergreen topic: {opp.get('topic')}")
        lines.append(f"QA: {opp.get('qa_status')}")
        lines.append(f"generated: {opp.get('generated_at')}")
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def render_review(queue, hot, evergreen, ready_at):
    lines = ['HOT', '']
    if not hot.get('looked'):
        lines.append('（这一轮没有新的订阅内容）')
        lines.append('')
    for ev in hot.get('looked') or []:
        lines.append(ev.get('title') or '(untitled)')
        action = ev.get('action')
        if action:
            lines.append(f"{action}: {ev.get('reason') or ''}")
            if ev.get('account_id'):
                lines.append(f"account: {ev['account_id']} | target_language: {ev.get('target_language')}")
            persona = ev.get('persona') or '—'
            state = (ev.get('personas') or {}).get(persona, 'skip')
            shown = 'draft' if state in ('draft', 'draft_ready') else 'skip'
            lines.append(f'{persona}: {shown}')
        else:
            for pid, label in (('macro', 'Macro'), ('industry', 'Industry'), ('trading', 'Trading')):
                state = (ev.get('personas') or {}).get(pid, 'skip')
                shown = 'draft' if state in ('draft', 'draft_ready') else 'skip'
                lines.append(f'{label}: {shown}')
        lines.append('')
    lines.append('EVERGREEN')
    lines.append('')
    if not evergreen:
        lines.append('（这一轮没有新的 evergreen）')
        lines.append('')
    for row in evergreen:
        lines.append(row['theme'])
        lines.append('draft' if row['status'] == 'draft' else 'skip')
        lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('候选稿')
    lines.append('')
    stamp = ready_at
    drafts = [o for o in queue['opportunities']
              if o.get('created_at') == stamp and o.get('draft_status') == 'draft_ready' and o.get('text')]
    if not drafts:
        lines.append('（这一轮没有通过 QA 的候选稿）')
    for opp in drafts:
        lines.append(f"### {opp['opportunity_id']}  {opp['type']}")
        lines.append('')
        lines.append(opp['text'].strip())
        lines.append('')
        lines.append(f"persona: {opp.get('persona') or '—'}")
        lines.append(f"angle: {opp.get('selected_angle') or '—'}")
        if opp['type'] == 'hot':
            audit = opp.get('audit') or {}
            facts = ', '.join(audit.get('fact_sources') or []) or '—'
            found = audit.get('analysis_sources') or []
            names = ', '.join(
                (a.get('author') or a.get('source') or '') for a in found
            ) or '无'
            lines.append(f"事实来源: {facts}")
            lines.append(f"分析来源: {names}")
            lag = opp.get('reaction_lag_seconds')
            lines.append(f"reaction lag: {lag}s" if lag is not None else 'reaction lag: —')
        else:
            lines.append(f"evergreen topic: {opp.get('topic')}")
        lines.append(f"QA: {opp.get('qa_status')}")
        lines.append(f"generated: {opp.get('generated_at')}")
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def prepare(ingest=True, fetch_bodies=True, limit=HOT_PER_RUN):
    """Ingest and read bodies for the events this run would open.

    Separated from writing so a slow fetch does not sit inside the model
    calls. The body cache is what the next run_once reads.
    """
    summary = news.collect() if ingest else None
    rows = load_rows()
    ready_at = _iso()
    scored, _items = rank_events(rows, ready_at)
    opened = [row for row in scored if row['heat'].get('open_packet')]
    cache = load_body_cache()
    fetched = 0
    for row in opened[:limit]:
        reads = body_reads_for(row['event']['members'], cache, fetch=fetch_bodies)
        fetched += sum(1 for r in reads if r.get('read'))
    return {
        'ingest': None if not summary else {
            'run_id': summary.get('run_id'),
            'new_items': summary.get('new_items'),
            'failing': summary.get('failing'),
        },
        'clusters': len(scored),
        'opened': len(opened),
        'bodies_ready': fetched,
    }


def run_once(fetch_bodies=True, write=True, ingest=False, evergreen_n=0,
             hot_limit=HOT_PER_RUN, collect_analysis=True, source_limit=20):
    """One source-first cycle.

    Ingest is off unless a caller asks. This loop never inserts prewritten
    Evergreen copy. Legacy evergreen_n is accepted for callers but ignored.
    """
    started = _now()
    ready_at = _iso(started)
    ingest_summary = None
    if ingest:
        ingest_summary = news.collect()
    analysis_summary = None
    if collect_analysis and write:
        try:
            analysis_summary = ac.collect()
        except Exception as exc:
            analysis_summary = {'error': type(exc).__name__}
    queue = qs.load()
    hot = source_first_pass(
        queue, ready_at, limit=source_limit, write=write, per_source=2, hours=24)
    hot['ready_at'] = ready_at
    evergreen = []  # localization_v1 never inserts legacy prewritten Evergreen copy
    report = render_review(queue, hot, evergreen, ready_at)
    qs.save(queue)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime('%Y%m%dT%H%M%S')
    report_path = REPORTS / f'{stamp}.md'
    report_path.write_text(report, encoding='utf-8')
    backlog = render_backlog(queue)
    (REPORTS / 'latest.md').write_text(backlog, encoding='utf-8')
    metrics = summarize(queue, hot, evergreen, ingest_summary, ready_at)
    metrics['analysis_corpus'] = analysis_summary
    metrics_path = REPORTS / f'{stamp}.json'
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    return {
        'ready_at': ready_at,
        'report_path': str(report_path.relative_to(ROOT)),
        'metrics': metrics,
        'report': report,
    }


def summarize(queue, hot, evergreen, ingest_summary, ready_at):
    looked = hot.get('looked') or []
    post = [e for e in looked if e.get('decision') == 'POST']
    no_post = [e for e in looked if e.get('decision') != 'POST']
    this = [o for o in queue['opportunities'] if o.get('created_at') == ready_at]
    drafts = [o for o in this if o.get('draft_status') == 'draft_ready']
    by_persona = {};by_account={}
    for opp in drafts:
        if opp.get('account_id'):by_account[opp['account_id']]=by_account.get(opp['account_id'],0)+1
        if opp.get('type') == 'hot' and opp.get('persona'):
            by_persona[opp['persona']] = by_persona.get(opp['persona'],0)+1
    evergreen_drafts = [o for o in drafts if o.get('type') == 'evergreen']
    dups = [o for o in this if o.get('duplicate_of') or o.get('draft_status') == 'duplicate']
    lags = [o.get('reaction_lag_seconds') for o in drafts
            if o.get('type') == 'hot' and o.get('reaction_lag_seconds') is not None]
    source_fail = [o for o in this if o.get('failure_kind') == 'source']
    writer_fail = [o for o in this if o.get('failure_kind') == 'writer']
    actions = {}
    for ev in looked:
        label = ev.get('action') or ev.get('decision') or 'other'
        actions[label] = actions.get(label, 0) + 1
    return {
        'ready_at': ready_at,
        'ingest': None if not ingest_summary else {
            'run_id': ingest_summary.get('run_id'),
            'new_items': ingest_summary.get('new_items'),
            'failing': ingest_summary.get('failing'),
        },
        'source_actions': actions,
        'events_found': hot.get('clusters'),
        'events_opened': hot.get('opened'),
        'events_this_run': len(looked),
        'post': len(post),
        'no_post': len(no_post),
        'drafts_by_persona': by_persona,
        'drafts_by_account': by_account,
        'evergreen_drafts': len(evergreen_drafts),
        'duplicates': [{'id': o.get('opportunity_id'), 'of': o.get('duplicate_of')} for o in dups],
        'reaction_lag_seconds': lags,
        'source_failures': len(source_fail),
        'writer_failures': len(writer_fail),
        'candidate_ids': [o.get('opportunity_id') for o in drafts],
    }


def main():
    args = sys.argv[1:]
    cycles = 1
    interval = 0
    hot_limit = HOT_PER_RUN
    source_limit = 20
    # Default is source-first and does not ingest. --events is the old
    # news-first path, kept as the auxiliary entry, not the daily run.
    ingest = '--ingest' in args
    events = '--events' in args
    if '--prepare' in args:
        print(json.dumps(prepare(ingest=ingest, limit=hot_limit), ensure_ascii=False, indent=2))
        return None
    for a in args:
        if a.startswith('--cycles='):
            cycles = int(a.split('=', 1)[1])
        elif a.startswith('--interval='):
            interval = int(a.split('=', 1)[1])
        elif a.startswith('--hot='):
            hot_limit = int(a.split('=', 1)[1])
        elif a.startswith('--limit='):
            source_limit = int(a.split('=', 1)[1])
    last = None
    for i in range(cycles):
        if events:
            raise RuntimeError('--events generation retired; use --prepare for retrieval or the source-first localization pipeline')
        else:
            last = run_once(ingest=ingest, hot_limit=hot_limit, source_limit=source_limit)
        print(last['report'])
        print(json.dumps(last['metrics'], ensure_ascii=False, indent=2))
        if i + 1 < cycles and interval:
            time.sleep(interval)
    return last


def _run_events(ingest=True, hot_limit=HOT_PER_RUN, evergreen_n=0):
    """Retired generation entry. Retrieval-only --prepare is still available."""
    raise RuntimeError('Legacy event rewrite generation retired; use source_first_pass')


if __name__ == '__main__':
    main()
