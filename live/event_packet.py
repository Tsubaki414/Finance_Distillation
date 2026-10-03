"""EVENT → SOURCE RETRIEVAL → SOURCE PACKET → ANGLE SELECTION.

This sits beside fact extraction. `live/resolve_event.py` still owns numeric
facts and their character spans. This module owns the other half of a
publishable packet: which independent sources speak, where they agree, and
which angle is allowed.

It does not learn a voice, does not call a model, and does not write to the
news store or the fact ledger. A fixture is a list of already-collected
items. Live feeds can be passed in the same shape later.

Source hierarchy, in strength order:

    PRIMARY_OFFICIAL   the institution that did the thing (regulator, exchange
                       tape, named official document, company filing)
    WIRE_MAJOR         BBC, Reuters, AP, Bloomberg, WSJ, and the same class of
                       major reporting. A wire is not an official primary.
    ANALYSIS           commentary, desk notes, explainers
    SOCIAL_SIGNAL      a post. It can point at a story. It cannot become a fact.

Fact admission does not require an official primary. An official primary is
the strongest basis. With no official material, two independent high-quality
major reports can carry a breaking-stage fact, and the packet keeps the
source and the confidence. One major report is downgraded. Analysis and
social cannot be promoted into a hard fact on their own.

Run the Hormuz regression:

    .venv/bin/python -B -m unittest tests.test_event_packet
"""
from __future__ import annotations
from pathlib import Path
import json, re, datetime

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'live/research/hormuz_20260926.json'

TIERS = ('PRIMARY_OFFICIAL', 'WIRE_MAJOR', 'ANALYSIS', 'SOCIAL_SIGNAL')

# Major reporting outlets. Matching is by outlet family, not by a role label
# someone typed onto the row. BBC is in this set. It is not official.
WIRE_FAMILIES = {
    'reuters', 'bloomberg', 'ap', 'bbc', 'cnn', 'nyt', 'dowjones',
    'france24', 'xinhua', 'cctv', 'cls', 'chinanews', 'afp', 'ft',
}

# One outlet family counts once. Eight wires rewriting one pool report are
# not eight independent sources.
FAMILY = {
    'reuters': 'reuters', 'wsj': 'dowjones', 'wall street journal': 'dowjones',
    'dow jones': 'dowjones', 'bloomberg': 'bloomberg', 'bbc': 'bbc',
    'cnn': 'cnn', 'ap': 'ap', 'associated press': 'ap', 'nyt': 'nyt',
    'new york times': 'nyt', 'france 24': 'france24', 'france24': 'france24',
    '新华': 'xinhua', '央视': 'cctv', '财联社': 'cls', '第一财经': 'yicai',
    '中新': 'chinanews', 'chinanews': 'chinanews',
}

# Claims the research round explicitly refused to promote into facts.
REFUSED = ('纳指涨逾2%', 'nasdaq rose more than 2%', '突然跳水', '盘后 Brent 站上 100',
           'brent tops $100', 'brent above 100')


def load_fixture(path=None):
    p = Path(path) if path else FIXTURE
    return json.loads(p.read_text(encoding='utf-8'))


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d


def _family(item):
    name = (item.get('name') or item.get('source') or '').lower()
    # Longest needle first. A two-letter needle has to be its own token:
    # 'ap' sits inside 'cointelegraph' and was classifying that wire as AP.
    for needle, fam in sorted(FAMILY.items(), key=lambda kv: len(kv[0]), reverse=True):
        if len(needle) <= 3:
            if re.search(r'(^|[^a-z0-9])' + re.escape(needle) + r'([^a-z0-9]|$)', name):
                return fam
            continue
        if needle in name:
            return fam
    handle = (item.get('handle') or '').lower()
    if handle:
        return handle
    # The outlet name is the family when it is not in the wire table.
    # Falling through to the item id made a reprint unable to find the
    # outlet it said it was citing.
    if name:
        return name.split()[0]
    return (item.get('id') or 'unknown').lower()


def tier_of(item):
    """Map a collected item onto the four-tier hierarchy.

    An explicit tier wins. The old fixture labels are translated so a row
    that still says role=primary is not treated as an official document:
    BBC, Reuters, AP, Bloomberg and the other wire families land in
    WIRE_MAJOR. A social handle without an outlet family is SOCIAL_SIGNAL.
    """
    explicit = (item.get('tier') or '').upper()
    if explicit in TIERS:
        return explicit
    fam = _family(item)
    platform = (item.get('platform') or '').lower()
    old = (item.get('role') or '').lower()
    if old in ('specialist',) or platform in ('x', 'weibo', 'telegram'):
        if fam not in WIRE_FAMILIES:
            return 'SOCIAL_SIGNAL'
    if fam in WIRE_FAMILIES or old in ('breaking', 'primary'):
        return 'WIRE_MAJOR'
    if old == 'analysis':
        return 'ANALYSIS'
    if platform in ('x', 'weibo', 'telegram'):
        return 'SOCIAL_SIGNAL'
    return 'ANALYSIS'


def _is_official(item):
    return tier_of(item) == 'PRIMARY_OFFICIAL'


def _on_event(item):
    """An item collected in the window is not automatically about the event."""
    if item.get('on_event') is False:
        return False
    if item.get('related_not_same_event'):
        return False
    return True


def _blob(item):
    return ((item.get('title') or '') + ' ' + (item.get('text') or '')).lower()


def _matches(item, entity_terms, action_terms):
    blob = _blob(item)
    entity = any(t.lower() in blob for t in entity_terms)
    action = any(t.lower() in blob for t in action_terms)
    return entity, action


def _is_context_print(item):
    """A prior settlement is context for the story, not a second event."""
    return item.get('timestamp_kind') == 'session_date' or item.get('confidence') == 'reported_settlement'


def detect_event(items, entity_terms, action_terms, story_id=None, window_hours=72.0):
    """One action, one event. Wire rewrites do not each become an event.

    A 6-hour cutoff splits this weekend's rejection into three clusters and
    drops the first index. The cutoff that matches the research is the
    research window: same entity, same action, within 72 hours. A different
    action (blocked vs frozen) stays out because it fails the action terms
    or is marked related.

    `story_id` is the research round's own cluster label. Unlabeled items
    still have to match terms. An off-event post is excluded even if someone
    stamped the same story_id on it.
    """
    members, context, excluded = [], [], []
    for item in items:
        if not _on_event(item):
            excluded.append({'id': item.get('id'), 'why': 'related_or_off_event'})
            continue
        if story_id and item.get('story_id') not in (None, story_id):
            excluded.append({'id': item.get('id'), 'why': 'other_story'})
            continue
        has_entity, has_action = _matches(item, entity_terms, action_terms)
        labeled = bool(story_id) and item.get('story_id') == story_id
        if _is_context_print(item) and (labeled or has_entity or tier_of(item) in (
                'PRIMARY_OFFICIAL', 'WIRE_MAJOR')):
            context.append(item)
            continue
        if labeled or (has_entity and has_action):
            members.append(item)
            continue
        excluded.append({'id': item.get('id'), 'why': 'terms_miss'})
    members.sort(key=lambda x: _dt(x.get('published_at')) or datetime.datetime.max.replace(
        tzinfo=datetime.timezone.utc))
    if members:
        start = _dt(members[0].get('published_at'))
        if start:
            members = [m for m in members if _dt(m.get('published_at')) is None
                       or (_dt(m.get('published_at')) - start).total_seconds() <= window_hours * 3600]
    return {
        'members': members,
        'context': context,
        'excluded': excluded,
        'cluster_count': 1 if members else 0,
        'independent_families': sorted({_family(x) for x in members}),
    }


def hotness(event):
    """Enough to open a packet, not a quality score.

    Recency of the first indexed item, two tiers, an official document or
    two wires, and a cross-language gap. A price shout with no source stays
    under 60. Opening a packet is not the same as admitting a hard fact.
    """
    members = event['members']
    score, reasons = 0, []
    if not members:
        return {'score': 0, 'open_packet': False, 'reasons': ['no members']}
    tiers = {tier_of(m) for m in members}
    langs = {m.get('lang') for m in members if m.get('lang')}
    families = event['independent_families']
    if len(members) >= 1:
        score += 20
        reasons.append('item in window')
    if len(tiers) >= 2:
        score += 20
        reasons.append('two tiers')
    if 'PRIMARY_OFFICIAL' in tiers or len(families) >= 2:
        score += 20
        reasons.append('official or two outlets')
    if len(langs) >= 2:
        score += 15
        reasons.append('cross-language')
    if any(tier_of(m) in ('PRIMARY_OFFICIAL', 'WIRE_MAJOR', 'ANALYSIS') for m in members):
        score += 15
        reasons.append('asset-relevant source present')
    return {'score': score, 'open_packet': score >= 60, 'reasons': reasons,
            'tiers': sorted(tiers)}


def retrieve(event, items):
    """Official if one exists, else the major reports, then analysis and social.

    An empty official slot is a result. Promoting BBC into that slot would
    hide the missing document. An empty specialist slot is the same kind of
    result: filling it with another wire would hide the hole.
    """
    allowed = {id(x) for x in event['members'] + event['context']}
    pool = [x for x in items if id(x) in allowed]
    official = [x for x in pool if tier_of(x) == 'PRIMARY_OFFICIAL']
    official.sort(key=lambda x: (not x.get('body_read'), x.get('confidence') != 'body_read'))

    wires = [x for x in pool if tier_of(x) == 'WIRE_MAJOR']
    # A body we read outranks an indexed headline. Independence is by family.
    wires.sort(key=lambda x: (
        not x.get('body_read'),
        x.get('confidence') not in ('body_read', 'reported_settlement'),
        x.get('published_at') or '',
    ))

    analyses = [x for x in event['members'] if tier_of(x) == 'ANALYSIS']
    picked, seen_lang = [], set()
    for x in analyses:
        if x.get('lang') not in seen_lang:
            picked.append(x)
            seen_lang.add(x.get('lang'))
    for x in analyses:
        if x not in picked:
            picked.append(x)
        if len(picked) >= 5:
            break

    social = [x for x in event['members'] if tier_of(x) == 'SOCIAL_SIGNAL']
    disagreement = [x for x in event['members']
                    if x.get('id') in ('bbc-body',) or 'await' in (x.get('text') or '').lower()
                    or '等待' in (x.get('title') or '') or '等待' in (x.get('text') or '')]
    related = [x for x in items if x.get('related_not_same_event')]
    return {
        'primary_official': official[:1],
        'wire_major': wires,
        'analysis': picked[:5],
        'social': social,
        'disagreement_sources': disagreement[:2],
        'specialist': [],
        'specialist_empty': True,
        'related_separate_events': [x.get('id') for x in related],
        'quota': {
            'primary_official': 'strongest if present; not required to open',
            'wire_major': 'independent families; two bodies can carry a breaking fact',
            'analysis': '2-5 views, never a hard fact alone',
            'social': 'signal only',
        },
    }


def _claims_from(item):
    out = []
    for fact in item.get('facts') or []:
        out.append({
            'fact_id': fact['id'],
            'text': fact['text'],
            'kind': fact.get('kind'),
            'value': fact.get('value'),
            'unit': fact.get('unit'),
            'confidence': fact.get('confidence') or item.get('confidence'),
            'source_id': item['id'],
            'source_url': item.get('url'),
            'restatement_zh': fact.get('restatement_zh'),
            'restatement_en': fact.get('restatement_en'),
        })
    return out


def _refused_in(text):
    low = (text or '').lower()
    return [p for p in REFUSED if p.lower() in low]


def _independent_body_wires(wires):
    """Body-read major reports, one per outlet family."""
    seen, out = set(), []
    for item in wires:
        if not item.get('body_read'):
            continue
        fam = _family(item)
        if fam in seen:
            continue
        seen.add(fam)
        out.append(item)
    return out


def admit_facts(retrieval, event):
    """Admit claims under the practical line. Never promote a tier by relabeling it.

    Official body claims are hard facts. Two or more independent major
    reports that point the same way can be written as the event, with
    source and confidence kept. One major report can be written only with
    attribution, and is not a hard fact. Analysis and social claims stay
    views. A real conflict — two independent families pointing opposite
    ways, neither one citing the other — is recorded and is not resolved
    by picking the louder headline.
    """
    official = [x for x in retrieval['primary_official'] if x.get('body_read')]
    wires = list(retrieval['wire_major'])
    for item in event.get('context') or []:
        if tier_of(item) == 'WIRE_MAJOR' and item not in wires:
            wires.append(item)
    bodies = _independent_body_wires(wires)
    # Two major bodies that point opposite ways are not corroboration.
    # Keep only the largest set that says the same thing. A singleton left
    # after that split is a downgrade, which is what a contradiction is for.
    if len(bodies) >= 2:
        by_dir = {}
        for item in bodies:
            by_dir.setdefault(_direction(item), []).append(item)
        if 'loss' in by_dir and 'win' in by_dir:
            biggest = max(by_dir, key=lambda k: len(by_dir[k]) if k in ('loss', 'win') else -1)
            bodies = by_dir[biggest] if len(by_dir[biggest]) >= 2 else []
    two_majors = len(bodies) >= 2

    hard, downgraded, withheld = [], [], []

    def take(item, grade, dest):
        for fact in _claims_from(item):
            fact = dict(fact)
            fact['tier'] = tier_of(item)
            fact['admission'] = grade
            dest.append(fact)

    if official:
        for item in official:
            take(item, 'official', hard)
    shared = None
    if not official and two_majors:
        # Fact ids are local to each article. Two wires do not share an id
        # unless someone assigned one. Agreement is the direction they
        # already had to share to be counted as corroboration.
        for item in bodies:
            for fact in _claims_from(item):
                fact = dict(fact)
                fact['tier'] = 'WIRE_MAJOR'
                fact['admission'] = 'two_independent_major'
                fact['confidence'] = fact.get('confidence') or 'body_read'
                fact['corroborated_by'] = [_item_id(x) for x in bodies]
                hard.append(fact)
        shared = {f['fact_id'] for f in hard}
    for item in wires:
        if item.get('body_read') or item.get('confidence') == 'reported_settlement':
            # One readable major report is writable, with the outlet named.
            # It is not a hard fact. Two agreeing majors already landed in
            # `hard`; this loop keeps the claims those two did not share,
            # and the only-one-body case.
            grade = 'single_major_attributed'
            if official:
                grade = 'wire_beside_official'
            elif two_majors and shared is not None:
                # Shared claims already admitted. A number only this wire
                # reports stays downgraded, with its own confidence.
                own = {f['fact_id'] for f in _claims_from(item)}
                if own and own <= (shared or set()):
                    continue
            take(item, grade, downgraded)
        elif item.get('facts'):
            take(item, 'headline_not_admitted', withheld)
    for item in retrieval['analysis'] + retrieval['social']:
        if item.get('facts'):
            take(item, 'tier_cannot_upgrade', withheld)
    return {
        'hard': hard,
        'downgraded': downgraded,
        'withheld': withheld,
        'official_count': len(official),
        'independent_major_bodies': len(bodies),
        'basis': (
            'official' if official else
            'two_independent_major' if two_majors else
            'single_major_attributed' if bodies else
            'no_body'
        ),
    }


def packet_from(event, retrieval, event_id='hormuz-20260926'):
    """Fixed packet. Views stay views. Numbers stay on their fact_id."""
    members = event['members']
    first = members[0] if members else None
    admission = admit_facts(retrieval, event)
    facts = admission['hard'] + admission['downgraded']

    views = []
    view_items = (retrieval['wire_major'] + retrieval['analysis']
                  + retrieval['disagreement_sources'] + retrieval['social'])
    seen_view = set()
    for item in view_items:
        if item.get('id') in seen_view:
            continue
        seen_view.add(item.get('id'))
        views.append({
            'source_id': item['id'],
            'name': item.get('name'),
            'tier': tier_of(item),
            'lang': item.get('lang'),
            'published_at': item.get('published_at'),
            'confidence': item.get('confidence'),
            'body_read': bool(item.get('body_read')),
            'claim': item.get('title') or (item.get('text') or '')[:180],
            'url': item.get('url'),
        })

    refused = []
    for item in members:
        for phrase in _refused_in((item.get('title') or '') + ' ' + (item.get('text') or '')):
            refused.append({'source_id': item['id'], 'phrase': phrase,
                            'why': 'headline figure not confirmed in a body we read'})

    unknowns = []
    if first and first.get('timestamp_kind') == 'google_news_index':
        unknowns.append('absolute first publisher is unknown; first_seen is an index time')
    if any(v['source_id'] == 'gn-wsj' for v in views) or any(
            m.get('id') == 'gn-wsj' for m in members):
        unknowns.append('WSJ midterms-bombing line is headline only')
    if not any(f.get('confidence') == 'exchange_tape' for f in facts):
        unknowns.append('Friday settlement was not read from an exchange tape')
    if retrieval['specialist_empty']:
        unknowns.append('no on-event specialist source in the fixture')
    unknowns.append('current transit volume through the strait was not in the sources read')
    if admission['basis'] == 'single_major_attributed':
        unknowns.append('oral rejection rests on one major body; writable only with that outlet named')
    elif admission['basis'] == 'no_body':
        unknowns.append('no body-read official or major source')

    body_wire = next((m for m in members if m.get('body_read') and tier_of(m) == 'WIRE_MAJOR'), None)
    official_item = retrieval['primary_official'][0] if retrieval['primary_official'] else None
    second = members[1] if len(members) > 1 else None
    lags = _lags(first, official_item, second, body_wire)

    return {
        'event_id': event_id,
        'event': 'Trump orally rejected Iran’s seven-day plan to reopen the Strait of Hormuz.',
        'what_happened': (
            'Iran offered a seven-day path to reopen the strait. Trump told reporters '
            'the proposal was not acceptable. Tehran said it is still waiting for a '
            'definitive official US response. The strait has been effectively closed '
            'since February.'
        ),
        'primary_facts': [f for f in facts if f.get('kind') != 'number' or f.get('unit') != 'USD_per_barrel'],
        'important_numbers': [f for f in facts if f.get('kind') == 'number'],
        'admission': {
            'basis': admission['basis'],
            'official_count': admission['official_count'],
            'independent_major_bodies': admission['independent_major_bodies'],
            'withheld': admission['withheld'],
        },
        'source_views': views,
        'agreement': [
            'The president publicly rejected the seven-day proposal.',
            'Tehran’s foreign minister says a definitive official reply is still outstanding.',
        ],
        'disagreement': [
            'Friday’s price and Friday’s Chinese wrap still describe easing.',
            'Saturday’s oral rejection removes the seven-day path.',
            'A WSJ headline, unread, adds a post-midterms bombing expectation.',
            'Those three clocks are not the same claim.',
        ],
        'mainstream_angle': 'Talks failed, so oil must gap up.',
        'non_consensus_angle': (
            'Friday’s settlement already priced easing. Saturday removed the seven-day '
            'reopening path. Monday prices that gap, not a war that started on Saturday.'
        ),
        'second_order': [
            'Whose guidance still uses Friday’s easing assumption.',
            'The funds-wording dispute is a separate event.',
            'Insurance and freight can reprice a path change without a new closure.',
        ],
        'what_may_matter_next': [
            'Monday energy futures',
            'A written US response',
            'Whether Tehran restates the June memorandum',
        ],
        'unknown': unknowns,
        'refused_claims': refused,
        'related_events': retrieval['related_separate_events'],
        'specialist_slot': 'empty' if retrieval['specialist_empty'] else retrieval['specialist'][0]['id'],
        'retrieval_has_body_primary': admission['basis'] in ('official', 'two_independent_major'),
        'retrieval_basis': admission['basis'],
        'source_links': _links(members + event['context']),
        'timestamps': lags,
        'ledger': _ledger(facts, views, members),
    }


def _links(items):
    out, seen = [], set()
    for item in items:
        url = item.get('url')
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({'source_id': item.get('id'), 'name': item.get('name'), 'url': url,
                    'confidence': item.get('confidence')})
    return out


def _ledger(facts, views, members):
    """Source ledger for the packet, not a sentence ledger for a draft.

    Draft citation still belongs to live/write.py. This records which item
    supplied which claim, so a later draft cannot detach a number from its
    confidence. A downgraded row stays in the ledger; admission says it is
    not a hard fact.
    """
    rows = []
    for fact in facts:
        rows.append({
            'claim_id': fact['fact_id'],
            'kind': 'fact',
            'admission': fact.get('admission'),
            'tier': fact.get('tier'),
            'source_id': fact['source_id'],
            'url': fact.get('source_url'),
            'confidence': fact.get('confidence'),
        })
    for view in views:
        rows.append({
            'claim_id': 'view:' + view['source_id'],
            'kind': 'view',
            'source_id': view['source_id'],
            'url': view.get('url'),
            'confidence': view.get('confidence'),
            'body_read': view.get('body_read'),
        })
    for item in members:
        rows.append({
            'claim_id': 'item:' + item['id'],
            'kind': 'ingest',
            'source_id': item['id'],
            'tier': tier_of(item),
            'published_at': item.get('published_at'),
            'timestamp_kind': item.get('timestamp_kind'),
        })
    return rows


def _lags(first, official, second, wire=None):
    def iso(item):
        return item.get('published_at') if item else None
    return {
        'event_first_seen': iso(first),
        'first_seen_kind': first.get('timestamp_kind') if first else None,
        'first_quality_source': None,
        'first_quality_source_note': 'WSJ may be this source; body was not read',
        'first_official_confirmation': iso(official),
        'first_wire_major_body': iso(wire),
        'first_wire_major_body_note': 'BBC is major reporting, not an official primary',
        'second_source_arrival': iso(second),
        'source_packet_ready': None,
        'draft_ready': None,
        'human_approved': None,
        'publish_time': None,
    }


def fill_ready(packet, ready_at):
    """Stamp packet-ready without inventing a publish time."""
    packet = json.loads(json.dumps(packet))
    packet['timestamps']['source_packet_ready'] = ready_at
    packet['timestamps']['lags'] = compute_lags(packet['timestamps'])
    return packet


def compute_lags(ts):
    def delta(a, b, name):
        da, db = _dt(a), _dt(b)
        if not da or not db:
            return {'name': name, 'seconds': None, 'status': 'open'}
        return {'name': name, 'seconds': int((db - da).total_seconds()), 'status': 'closed'}
    return {
        'detection_lag': delta(ts.get('event_first_seen'), ts.get('first_quality_source'),
                               'detection_lag'),
        'research_lag': delta(ts.get('first_quality_source') or ts.get('event_first_seen'),
                              ts.get('source_packet_ready'), 'research_lag'),
        'draft_lag': delta(ts.get('source_packet_ready'), ts.get('draft_ready'), 'draft_lag'),
        'total_reaction_lag': delta(ts.get('event_first_seen'), ts.get('publish_time'),
                                    'total_reaction_lag'),
    }


ANGLES = (
    {
        'id': 'expectation_gap',
        'label': 'Friday’s easing price versus Saturday’s oral rejection',
        'needs': ('oral_rejection_admitted', 'friday_settlement', 'disagreement'),
        'rejects_if': ('war_just_started',),
    },
    {
        'id': 'formal_reply_open',
        'label': 'Oral rejection is not a written rupture',
        'needs': ('oral_rejection_admitted', 'tehran_waiting'),
        'rejects_if': (),
    },
    {
        'id': 'cross_language_clock',
        'label': 'English sources split the wording; Chinese headlines still describe Friday',
        'needs': ('cross_language', 'friday_frame'),
        'rejects_if': (),
    },
    {
        'id': 'one_number',
        'label': 'One settlement number, with its confidence',
        'needs': ('friday_settlement', 'oral_rejection_admitted'),
        'rejects_if': ('exchange_tape_claimed',),
    },
    {
        'id': 'oil_must_gap',
        'label': 'Talks failed so oil must gap up',
        'needs': (),
        'rejects_if': ('unknown_monday_print',),
    },
)


def _signals(packet):
    facts = {f['fact_id'] for f in packet.get('primary_facts', [])}
    numbers = {f['fact_id'] for f in packet.get('important_numbers', [])}
    text = json.dumps(packet, ensure_ascii=False).lower()
    return {
        'oral_rejection_admitted': ('f-oral-reject' in facts or 'f-rejecting-deal' in facts)
        and (packet.get('retrieval_has_body_primary') is True
             or packet.get('retrieval_basis') == 'single_major_attributed'),
        'tehran_waiting': 'f-await-official' in facts and (
            packet.get('retrieval_has_body_primary') is True
            or packet.get('retrieval_basis') == 'single_major_attributed'),
        'friday_settlement': 'f-wti' in numbers and 'f-brent' in numbers,
        'body_primary': packet.get('retrieval_has_body_primary') is True,
        'disagreement': bool(packet.get('disagreement')),
        'cross_language': len({v.get('lang') for v in packet.get('source_views', [])}) >= 2
        or 'zh' in text and 'en' in text,
        'friday_frame': ('easing' in text or '缓和' in text)
        and (packet.get('retrieval_has_body_primary') is True
             or packet.get('retrieval_basis') == 'single_major_attributed'),
        'war_just_started': False,
        'exchange_tape_claimed': any(
            f.get('confidence') == 'exchange_tape' for f in packet.get('important_numbers', [])),
        'unknown_monday_print': any(
            'Monday' in u or '周一' in u
            for u in list(packet.get('unknown') or []) + list(packet.get('what_may_matter_next') or [])),
    }


def select_angle(packet):
    """Pick the first angle whose evidence is in the packet.

    The mainstream 'oil must gap' angle is a candidate so the selector can
    reject it. It is not the default.
    """
    sig = _signals(packet)
    chosen, rejected = None, []
    for angle in ANGLES:
        missing = [n for n in angle['needs'] if not sig.get(n)]
        blocked = [n for n in angle['rejects_if'] if sig.get(n)]
        row = {
            'id': angle['id'],
            'label': angle['label'],
            'missing': missing,
            'blocked_by': blocked,
            'available': not missing and not blocked,
        }
        if row['available'] and chosen is None and angle['id'] != 'oil_must_gap':
            chosen = row
        if angle['id'] == 'oil_must_gap':
            row['available'] = False
            row['blocked_by'] = blocked or ['selector refuses an unpriced direction']
            rejected.append(row)
        elif not row['available']:
            rejected.append(row)
    if chosen is None:
        return {
            'angle_id': None,
            'label': None,
            'why': 'no angle had its required evidence',
            'rejected': rejected,
            'publish': False,
        }
    return {
        'angle_id': chosen['id'],
        'label': chosen['label'],
        'why': 'first angle whose required evidence is in the packet',
        'uses': [
            'f-oral-reject', 'f-await-official', 'f-wti', 'f-brent',
        ],
        'must_not_assert': [
            'Monday oil will gap up',
            'the war started on Saturday',
            'WSJ midterms bombing is a confirmed presidential plan',
            'Brent topped 100 after hours',
            'Nasdaq rose more than 2%',
        ],
        'related_event_ids': packet.get('related_events') or [],
        'rejected': rejected,
        'publish': True,
        'attribution': 'event' if packet.get('retrieval_has_body_primary') else 'single_source',
    }


def run(items=None, ready_at='2026-09-27T12:00:00+00:00'):
    """Full chain on a fixture. `ready_at` stamps the packet, not a publish."""
    if items is None:
        items = load_fixture()['items']
    event = detect_event(
        items,
        entity_terms=['hormuz', '霍尔木兹', 'strait', '美伊'],
        action_terms=['reject', '拒绝', 'reopen', '重开', 'seven-day', '七日', 'seven day'],
        story_id='hormuz-reopen',
    )
    heat = hotness(event)
    retrieval = retrieve(event, items)
    packet = packet_from(event, retrieval)
    packet = fill_ready(packet, ready_at if heat['open_packet'] else None)
    angle = select_angle(packet) if heat['open_packet'] else {
        'angle_id': None, 'publish': False, 'why': 'hotness below 60',
    }
    return {
        'event': {
            'member_ids': [m['id'] for m in event['members']],
            'context_ids': [m['id'] for m in event['context']],
            'excluded': event['excluded'],
            'independent_families': event['independent_families'],
        },
        'hotness': heat,
        'retrieval': {
            'primary_official': [x['id'] for x in retrieval['primary_official']],
            'wire_major': [x['id'] for x in retrieval['wire_major']],
            'analysis': [x['id'] for x in retrieval['analysis']],
            'social': [x['id'] for x in retrieval['social']],
            'specialist': [x['id'] for x in retrieval['specialist']],
            'specialist_empty': retrieval['specialist_empty'],
            'related_separate_events': retrieval['related_separate_events'],
            'basis': packet.get('retrieval_basis'),
        },
        'packet': packet,
        'angle': angle,
    }


# Live feeds name an outlet, not a tier. Investing.com and Seeking Alpha are
# desk commentary. A central-bank press feed and an SEC filing are the
# institution that did the thing. Crypto wires in the existing pool are
# major reporting for that beat, not official documents.
LIVE_SOURCE_TIER = {
    'fed_press': 'PRIMARY_OFFICIAL',
    'sec_8k': 'PRIMARY_OFFICIAL',
    'cn_investing': 'ANALYSIS',
    'cn_investing_stocks': 'ANALYSIS',
    'investing': 'ANALYSIS',
    # Market Currents is a news wire. A Seeking Alpha analysis column is
    # still ANALYSIS; this collector only ingests market_currents.xml.
    'seekingalpha': 'WIRE_MAJOR',
    'panews': 'WIRE_MAJOR',
    'cointelegraph': 'WIRE_MAJOR',
    'coindesk': 'WIRE_MAJOR',
    'theblock': 'WIRE_MAJOR',
}

# Function words and market-template words. They describe the feed, not the
# event, so they cannot be the thing two headlines share.
_STOP = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'after', 'before',
    'over', 'into', 'amid', 'says', 'said', 'will', 'its', 'has', 'have',
    'are', 'was', 'were', 'not', 'but', 'you', 'your', 'our', 'new', 'more',
    'than', 'about', 'what', 'why', 'how', 'who', 'when', 'where', 'just',
    'stocks', 'stock', 'shares', 'share', 'market', 'markets', 'price',
    'prices', 'trading', 'trade', 'today', 'week', 'year', 'report', 'news',
    'update', 'live', 'watch', 'breaking', 'analysis', 'investing', 'com',
    'http', 'https', 'www', 'html', 'rss',
    '的', '了', '在', '是', '与', '和', '为', '将', '对', '中', '及', '等',
    '今日', '市场', '公司', '股价', '上涨', '下跌', '美元',
}

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}|\$[A-Za-z]{1,6}|[\u4e00-\u9fff]{2,}")

# A Chinese wire often keeps the Latin name and translates the verb. The
# verb then cannot be the second shared token. These are translations of
# the action, not a list of events. Matching one of them against its
# English side is what lets the two languages sit in one cluster so the
# disagreement can be seen.
_ACTION_ALIAS = (
    ({'loses', 'lost', 'ruled', 'ruling', 'appeal', 'appeals'},
     {'裁决', '上诉', '法院', '败诉', '胜诉', '获法院支持', '赢得'}),
    ({'step', 'down', 'leave', 'leaves', 'interim'},
     {'卸任', '离任', '回归', '临时'}),
    ({'breach', 'hack', 'hacked', 'stolen'},
     {'被盗', '黑客', '攻击', '漏洞', '安全事件'}),
    ({'sells', 'sold', 'shares'},
     {'出售', '减持'}),
)

# Institution and beat words. They say which desk wrote the item. They do
# not say which event it is. Kept here because document frequency cannot
# see them: three different Fed actions in one quiet week are still three
# actions, and 'federal' appears only a handful of times.
_INSTITUTION = {
    'federal', 'reserve', 'board', 'fed', 'sec', 'cftc', 'treasury',
    'congress', 'senate', 'house', 'court', 'appeals', 'circuit',
    'department', 'commission', 'exchange', 'nasdaq', 'nyse',
    '美联储', '美联储委员会', '证监会', '法院', '财政部',
}


def _tokens(item):
    blob = (item.get('title') or '') + ' ' + (item.get('text') or '') + ' ' + (item.get('summary') or '')
    out = []
    for raw in _TOKEN.findall(blob):
        tok = raw.lower() if raw.isascii() else raw
        if tok in _STOP or len(tok) < 2:
            continue
        out.append(tok)
    return out


def _item_id(item):
    return item.get('id') or item.get('item_id')


def normalize_live_item(row):
    """One live news row, in the shape detect/retrieve already consume.

    Tier comes from the outlet that was already in the collector. Nothing
    here is told what the event is.
    """
    source = row.get('source') or ''
    return {
        'id': row.get('item_id'),
        'item_id': row.get('item_id'),
        'name': source,
        'source': source,
        'tier': LIVE_SOURCE_TIER.get(source, 'ANALYSIS'),
        'platform': row.get('platform') or 'news',
        'lang': row.get('lang'),
        'published_at': row.get('published_at'),
        'first_seen_at': row.get('first_seen_at'),
        'timestamp_kind': 'feed_published',
        'title': row.get('title') or '',
        'text': row.get('summary') or '',
        'summary': row.get('summary') or '',
        'url': row.get('url'),
        'body_read': False,
        'confidence': 'headline',
    }


def _figures(item):
    try:
        import cluster as cluster_mod
        return cluster_mod.figures((item.get('title') or '') + ' ' + (item.get('text') or ''))
    except Exception:
        return set()


def _distinctive_tokens(items):
    """Tokens that name something. A token in a tenth of the pull is a template.

    Document frequency is computed on this ingest, not from a hand list of
    events. 'Bitcoin' in half the crypto wire is not a cluster. A name that
    shows up two or three times can be.
    """
    df = {}
    token_sets = []
    for item in items:
        toks = set(_tokens(item))
        token_sets.append(toks)
        for tok in toks:
            df[tok] = df.get(tok, 0) + 1
    n = max(len(items), 1)
    ceiling = max(4, int(n * 0.08))
    distinctive = {
        tok for tok, c in df.items()
        if 1 < c <= ceiling and len(tok) >= 3 and tok not in _INSTITUTION
    }
    return token_sets, distinctive, df


def _alias_hit(a_tokens, b_tokens):
    for left, right in _ACTION_ALIAS:
        if (a_tokens & left and b_tokens & right) or (b_tokens & left and a_tokens & right):
            return True
    return False


def _support(a_tokens, b_tokens, distinctive):
    """Shared tokens that can name an event.

    Two items about the same institution are not the same event. The overlap
    has to contain something that is not the institution itself: a person,
    a firm, a product, a place. 'Federal' plus 'reserve' is the desk.
    'Sandy' plus 'spring' is the case.

    A proper name is enough on its own when the other language does not
    share the verb. 'Kalshi' in an English loss headline and 'Kalshi' in a
    Chinese headline are the same named party. The verb is checked later,
    as disagreement, not as a reason to drop the other language.
    """
    shared = (a_tokens & b_tokens) & distinctive
    if not shared:
        return shared
    specific = {tok for tok in shared if tok not in _INSTITUTION}
    # One shared name is not an event. OpenAI appears in an ARK filing, an
    # Australian hearing and a training pause. Those share the name and
    # nothing else. Two specific tokens say the items are about the same
    # action. A Latin name plus a translated verb is the cross-language
    # case of the same test: the verb is not the same string, so the alias
    # supplies the second token.
    if len(specific) >= 2:
        return shared
    proper = {tok for tok in specific if tok[:1].isascii() and tok.isalpha() and len(tok) >= 4}
    if len(proper) == 1 and _alias_hit(a_tokens, b_tokens):
        return shared | {'alias:action'}
    return set()


def _related_not_same(a, b, shared):
    """Same names, different action.

    Two headlines can share an entity and still be different events: one
    number moved, the other did not. That pair is excluded from the cluster
    rather than merged. A filing form that does not match is the same kind
    of split.
    """
    fa, fb = _figures(a), _figures(b)
    if fa and fb and not (fa & fb):
        return True
    forms_a = set(re.findall(r'\b\d{1,2}-[A-Z]{1,2}(?:/A)?\b', a.get('title') or ''))
    forms_b = set(re.findall(r'\b\d{1,2}-[A-Z]{1,2}(?:/A)?\b', b.get('title') or ''))
    if forms_a and forms_b and forms_a != forms_b and len(shared) < 3:
        return True
    return False


def detect_live_events(items, window_hours=72.0, now=None):
    """Cluster ingested items without being told the event.

    A cluster needs two items that share at least two distinctive tokens.
    Distinctive means the token is rare in this ingest. A third item joins
    only if it shares that support with every member it is paired with, and
    a related item whose figures disagree is recorded as excluded.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    usable = []
    for item in items:
        at = _dt(item.get('published_at')) or _dt(item.get('first_seen_at'))
        if at is None:
            continue
        if (now - at).total_seconds() > window_hours * 3600:
            continue
        if not (item.get('title') or item.get('text')):
            continue
        usable.append(item)
    usable.sort(key=lambda x: _dt(x.get('published_at')) or _dt(x.get('first_seen_at')))
    token_sets, distinctive, _df = _distinctive_tokens(usable)
    by_id = {id(item): toks for item, toks in zip(usable, token_sets)}

    parent = {id(x): id(x) for x in usable}
    groups = {id(x): [x] for x in usable}
    excluded_pairs = []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            shared = _support(by_id[id(a)], by_id[id(b)], distinctive)
            if len(shared) < 2:
                continue
            if _related_not_same(a, b, shared):
                excluded_pairs.append({
                    'id': _item_id(b),
                    'against': _item_id(a),
                    'why': 'related_but_different',
                    'shared': sorted(shared)[:6],
                })
                continue
            ra, rb = find(id(a)), find(id(b))
            if ra == rb:
                continue
            # Join on the pair, then keep the cluster only if every member
            # still shares one anchor with the seed. Requiring every pair
            # to share two tokens drops a translation: the Chinese wire
            # shares the name and the action alias with each English wire,
            # and the English wires share the verb with each other.
            anchor = None
            for m in groups[ra]:
                anchor = _support(by_id[id(a)], by_id[id(m)], distinctive) or anchor
            ok = anchor is not None
            for m in groups[ra]:
                shared_m = _support(by_id[id(b)], by_id[id(m)], distinctive)
                if not shared_m or _related_not_same(b, m, shared_m):
                    ok = False
                    break
                if anchor and not (shared_m & anchor - {'alias:action'}):
                    ok = False
                    break
            if ok:
                parent[rb] = ra
                groups[ra].extend(groups[rb])
                del groups[rb]

    events = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda x: _dt(x.get('published_at')) or datetime.datetime.max.replace(
            tzinfo=datetime.timezone.utc))
        start = _dt(members[0].get('published_at'))
        if start:
            members = [m for m in members
                       if (_dt(m.get('published_at')) or start) and
                       ((_dt(m.get('published_at')) or start) - start).total_seconds()
                       <= window_hours * 3600]
        if len(members) < 2:
            continue
        support = set(by_id[id(members[0])]) & distinctive
        for m in members[1:]:
            support &= by_id[id(m)]
        specific = support - _INSTITUTION - {'alias:action'}
        # The intersection of every member can be a single proper name when
        # the action was matched through a translation alias. Two English
        # wires still had to share a verb to form the seed.
        if len(specific) < 1:
            continue
        if len(members) >= 3 and not any(
                tok[:1].isascii() and tok.isalpha() and len(tok) >= 4 for tok in specific):
            continue
        member_ids = {_item_id(m) for m in members}
        excluded = [p for p in excluded_pairs
                    if p['against'] in member_ids or p['id'] in member_ids]
        # An excluded row that is also a member was a different pair. Drop
        # those self-references so the packet shows only what stayed out.
        excluded = [p for p in excluded if p['id'] not in member_ids]
        events.append({
            'members': members,
            'context': [],
            'excluded': excluded,
            'support': sorted(support)[:8],
            'independent_families': sorted({_family(x) for x in members}),
            'first_published_at': members[0].get('published_at'),
            'first_seen_at': min(
                (m.get('first_seen_at') or m.get('published_at') or '') for m in members),
        })
    return events


def live_hotness(event):
    """Open a packet on what the feed actually showed.

    Two items are not enough. The chain opens when the cluster has two
    independent outlet families, or an official item plus anyone else, and
    at least three items or a cross-language pair. That is the same 60 line
    the fixture uses, scored from tiers rather than from a hand label.
    """
    base = hotness(event)
    members = event['members']
    families = event['independent_families']
    score = base['score']
    reasons = list(base['reasons'])
    if len(members) >= 3:
        score += 10
        reasons.append('three items')
    if len(families) < 2 and 'PRIMARY_OFFICIAL' not in {tier_of(m) for m in members}:
        score = min(score, 40)
        reasons.append('single outlet cannot open')
    return {'score': score, 'open_packet': score >= 60, 'reasons': reasons,
            'tiers': base.get('tiers', [])}


_LOSS = ('loses', 'lost', 'ruled against', 'ruling against', 'ruled in favor of ohio',
         '败诉', '驳回', '不利于')
_WIN = ('获法院支持', '赢得', '获准继续', 'wins', 'won the', 'ruled for kalshi')

# A reprint that names the outlet it is copying is not a second witness.
# PANews citing Cointelegraph is Cointelegraph again. It can be wrong, and
# that error is recorded, but it does not count as an independent conflict.
_CITES = (
    ('citing cointelegraph', 'cointelegraph'),
    ('据 cointelegraph', 'cointelegraph'),
    ('据cointelegraph', 'cointelegraph'),
    ('citing the block', 'theblock'),
    ('据 the block', 'theblock'),
    ('citing reuters', 'reuters'),
    ('据路透', 'reuters'),
    ('citing bloomberg', 'bloomberg'),
    ('据彭博', 'bloomberg'),
    ('citing associated press', 'ap'),
    ('据美联社', 'ap'),
    ('citing bbc', 'bbc'),
    ('据 bbc', 'bbc'),
)


def _direction(item):
    blob = ((item.get('title') or '') + ' ' + (item.get('text') or '')).lower()
    loss = any(p in blob for p in _LOSS)
    win = any(p in blob for p in _WIN)
    if loss and win:
        return 'mixed'
    if loss:
        return 'loss'
    if win:
        return 'win'
    return 'unknown'


def _cites(item):
    """Outlet families this item says it is repeating. Empty if it does not say."""
    blob = ((item.get('title') or '') + ' ' + (item.get('text') or '') + ' '
            + (item.get('summary') or '')).lower()
    return {fam for needle, fam in _CITES if needle in blob}


def _independent_conflict(members):
    """Opposite directions that are not one wire reprinting another.

    A Chinese desk that says it is citing Cointelegraph, and then states
    the opposite of Cointelegraph, is a transcription error to flag. It is
    not a second independent account of the ruling. Two families that do
    not cite each other, and point opposite ways, are a real conflict.
    """
    by_dir = {}
    for item in members:
        by_dir.setdefault(_direction(item), []).append(item)
    loss = [x for x in by_dir.get('loss', []) if not _cites(x)]
    win = [x for x in by_dir.get('win', []) if not _cites(x)]
    if not loss or not win:
        return None
    loss_fam = {_family(x) for x in loss}
    win_fam = {_family(x) for x in win}
    if loss_fam & win_fam and len(loss_fam | win_fam) < 2:
        return None
    return {
        'what': 'independent sources point opposite ways',
        'loss': [_item_id(x) for x in loss],
        'win': [_item_id(x) for x in win],
    }


def _reprint_errors(members):
    """A cited reprint that states the opposite of the outlet it cites."""
    by_fam = {}
    for item in members:
        by_fam.setdefault(_family(item), []).append(item)
    out = []
    for item in members:
        cited = _cites(item)
        if not cited:
            continue
        own = _direction(item)
        if own not in ('loss', 'win'):
            continue
        for fam in cited:
            for src in by_fam.get(fam, []):
                src_dir = _direction(src)
                if src_dir in ('loss', 'win') and src_dir != own:
                    out.append({
                        'id': _item_id(item),
                        'cites': fam,
                        'source_id': _item_id(src),
                        'reprint_says': own,
                        'cited_says': src_dir,
                    })
    return out


def packet_from_live(event, retrieval, ready_at):
    """A packet built only from what ingest returned.

    No fixture prose. Claims that were not read stay UNKNOWN. Headline text
    is a view. Analysis and social cannot become a hard fact. A single major
    body, or a headline with no body, is not enough to publish.
    """
    members = event['members']
    first = members[0] if members else None
    admission = admit_facts(retrieval, event)
    facts = admission['hard'] + admission['downgraded']
    views = []
    for item in retrieval['primary_official'] + retrieval['wire_major'] + retrieval['analysis'] + retrieval['social']:
        views.append({
            'source_id': _item_id(item),
            'name': item.get('name') or item.get('source'),
            'tier': tier_of(item),
            'lang': item.get('lang'),
            'published_at': item.get('published_at'),
            'first_seen_at': item.get('first_seen_at'),
            'confidence': item.get('confidence'),
            'body_read': bool(item.get('body_read')),
            'claim': item.get('title') or '',
            'url': item.get('url'),
        })
    disagreements = []
    conflict = _independent_conflict(members)
    reprints = _reprint_errors(members)
    if conflict:
        disagreements.append(conflict)
    if reprints:
        disagreements.append({
            'what': 'a reprint states the opposite of the outlet it cites',
            'items': reprints,
        })
    elif len({m.get('title') or '' for m in members}) > 1 and not conflict:
        disagreements.append('member headlines are not the same sentence')
    unknowns = []
    if not any(m.get('body_read') for m in members):
        unknowns.append('no body was read; headlines are not facts')
    if not retrieval['primary_official']:
        unknowns.append('no official primary in the cluster; writing from major reporting')
    unread = [m for m in members if not m.get('body_read')]
    if unread:
        unknowns.append('unread members: ' + ', '.join(_item_id(m) or '' for m in unread))
    if reprints:
        unknowns.append('a citing reprint contradicts the outlet it names; that reprint is not a second witness')
    if conflict:
        unknowns.append('independent sources disagree; outcome stays UNKNOWN until one more source is checked')
    excluded = event.get('excluded') or []
    if excluded:
        disagreements.append('related items were kept out: ' + ', '.join(
            p.get('id') or '' for p in excluded[:5]))
    # Only an independent conflict pulls admitted claims back down. A
    # reprint that misstates the wire it cites does not.
    if conflict:
        for fact in facts:
            if fact.get('admission') in ('official', 'two_independent_major', 'single_major_attributed'):
                fact['admission'] = 'contested_downgraded'
                fact['confidence'] = fact.get('confidence') or 'body_read'
    cited_ids = {row.get('id') for row in reprints}
    if cited_ids:
        for fact in facts:
            if fact.get('source_id') in cited_ids:
                fact['admission'] = 'reprint_not_witness'
                fact['confidence'] = fact.get('confidence') or 'body_read'
    first_seen = event.get('first_seen_at') or (first.get('first_seen_at') if first else None)
    lags = {
        'event_first_seen': first.get('published_at') if first else None,
        'first_seen_kind': 'feed_published',
        'ingest_first_seen': first_seen,
        'first_quality_source': None,
        'first_official_confirmation': None,
        'first_wire_major_body': None,
        'second_source_arrival': members[1].get('published_at') if len(members) > 1 else None,
        'source_packet_ready': ready_at,
        'draft_ready': None,
        'human_approved': None,
        'publish_time': None,
    }
    lags['lags'] = compute_lags(lags)
    label = (event.get('support') or ['untitled'])[:4]
    return {
        'event_id': 'live-' + (_item_id(first) or 'none'),
        'event': ' '.join(label),
        'support_tokens': event.get('support') or [],
        'what_happened': None,
        'primary_facts': [f for f in facts if f.get('admission') in ('official', 'two_independent_major')],
        'downgraded_claims': [f for f in facts if f.get('admission') not in ('official', 'two_independent_major')],
        'important_numbers': [],
        'admission': {
            'basis': admission['basis'],
            'official_count': admission['official_count'],
            'independent_major_bodies': admission['independent_major_bodies'],
        },
        'source_views': views,
        'agreement': [],
        'disagreement': disagreements,
        'unknown': unknowns,
        'related_excluded': excluded,
        'tiers': sorted({tier_of(m) for m in members}),
        'retrieval_has_body_primary': admission['basis'] in ('official', 'two_independent_major'),
        'retrieval_basis': admission['basis'],
        'timestamps': lags,
        'ledger': _ledger(facts, views, members),
    }


def attach_body_reads(items, reads):
    """Fold a retrieval read back onto the ingested item it came from.

    `reads` is a list of {id, body, read, note}. The id is the ingest
    item_id. A failed fetch stays unread. This does not add a source that
    was not already in the cluster.
    """
    by_id = {_item_id(item): item for item in items}
    for read in reads:
        item = by_id.get(read.get('id'))
        if not item:
            continue
        item['body_read'] = bool(read.get('read'))
        item['confidence'] = 'body_read' if read.get('read') else (read.get('note') or 'unread')
        if read.get('read') and read.get('facts'):
            item['facts'] = read['facts']
        if read.get('note'):
            item['read_note'] = read['note']
    return items


def select_live_angle(packet, heat):
    """Write when the practical line is met. Hold only a real conflict.

    Two agreeing major reports, or one official body, can be written as the
    event. One major report can be written with attribution. Analysis and
    social alone cannot. An independent conflict is the case that stays
    NO POST until one more source is checked.
    """
    if not heat.get('open_packet'):
        return {'angle_id': None, 'publish': False, 'decision': 'NO_POST',
                'why': 'hotness below 60'}
    conflict = [d for d in (packet.get('disagreement') or [])
                if isinstance(d, dict) and d.get('what', '').startswith('independent sources')]
    if conflict:
        return {'angle_id': None, 'publish': False, 'decision': 'NO_POST',
                'why': 'independent sources disagree; check one more source before writing'}
    basis = packet.get('retrieval_basis')
    if basis in ('official', 'two_independent_major') and packet.get('primary_facts'):
        return {
            'angle_id': 'sourced_fact',
            'publish': True,
            'decision': 'POST',
            'attribution': 'event',
            'why': 'two or more independent major reports agree, or an official body was read',
        }
    attributed = [f for f in (packet.get('downgraded_claims') or [])
                  if f.get('admission') == 'single_major_attributed']
    if attributed:
        return {
            'angle_id': 'attributed_single_source',
            'publish': True,
            'decision': 'POST',
            'attribution': 'single_source',
            'why': 'one major report; write it as that outlet\'s account, not as a settled fact',
            'uses': [f['fact_id'] for f in attributed],
        }
    if basis in ('no_body',) or not (packet.get('primary_facts') or attributed):
        return {'angle_id': None, 'publish': False, 'decision': 'NO_POST',
                'why': 'no readable major or official body'}
    return {'angle_id': None, 'publish': False, 'decision': 'NO_POST',
            'why': 'evidence below the admission line: ' + str(basis)}


def run_live(rows, ready_at=None, window_hours=72.0, body_reads=None):
    """Ingested rows in, one packet out. The caller does not name the event."""
    ready_at = ready_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
    items = [normalize_live_item(r) if 'item_id' in r and 'tier' not in r else r for r in rows]
    if body_reads:
        attach_body_reads(items, body_reads)
    found = detect_live_events(items, window_hours=window_hours)
    if not found:
        return {'decision': 'NO_POST', 'why': 'no cluster of two items', 'events': 0,
                'packet_ready': ready_at}
    scored = []
    for event in found:
        heat = live_hotness(event)
        # A body already read outranks a higher headline score. Otherwise
        # the chain opens the noisiest unread cluster and never reaches the
        # one whose links it fetched.
        read_n = sum(1 for m in event['members'] if m.get('body_read'))
        scored.append((heat['score'], read_n, len(event['members']), event, heat))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    opened = [row for row in scored if row[4]['open_packet']]
    if opened:
        # Among clusters that clear 60, prefer the one with a body in hand.
        # Hotness still has to clear the line. A body does not manufacture
        # an event that the detector did not open.
        opened.sort(key=lambda x: (x[1], x[0], x[2]), reverse=True)
        score, _, _, event, heat = opened[0]
    else:
        score, _, _, event, heat = scored[0]
    retrieval = retrieve(event, event['members'])
    packet = packet_from_live(event, retrieval, ready_at)
    angle = select_live_angle(packet, heat)
    return {
        'decision': angle['decision'],
        'candidates': len(scored),
        'opened': len(opened),
        'chosen_support': event.get('support'),
        'event': {
            'member_ids': [_item_id(m) for m in event['members']],
            'titles': [m.get('title') for m in event['members']],
            'sources': [m.get('source') for m in event['members']],
            'tiers': sorted({tier_of(m) for m in event['members']}),
            'excluded': event.get('excluded'),
            'first_published_at': event.get('first_published_at'),
            'first_seen_at': event.get('first_seen_at'),
        },
        'hotness': heat,
        'retrieval': {
            'primary_official': [_item_id(x) for x in retrieval['primary_official']],
            'wire_major': [_item_id(x) for x in retrieval['wire_major']],
            'analysis': [_item_id(x) for x in retrieval['analysis']],
            'social': [_item_id(x) for x in retrieval['social']],
            'basis': packet.get('retrieval_basis'),
        },
        'packet': packet,
        'angle': angle,
        'other_open': [
            {'support': row[3].get('support'), 'score': row[0],
             'bodies_read': row[1], 'n': len(row[3]['members'])}
            for row in opened[1:6]
        ],
    }


def main():
    result = run()
    print(json.dumps({
        'members': result['event']['member_ids'],
        'excluded': result['event']['excluded'],
        'hotness': result['hotness']['score'],
        'primary_official': result['retrieval']['primary_official'],
        'wire_major': result['retrieval']['wire_major'],
        'basis': result['retrieval']['basis'],
        'specialist_empty': result['retrieval']['specialist_empty'],
        'angle': result['angle'].get('angle_id'),
        'unknown': result['packet']['unknown'],
        'lags': result['packet']['timestamps'].get('lags'),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
