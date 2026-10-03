"""Hotspot to primary document to fact pack.

The line this file exists to hold: a KOL post is a *signal that something happened*, never the
source of a fact. Tweets point at events; facts come from the document the event is about. If no
primary document can be found, or nothing numeric can be extracted from it with an exact offset,
the opportunity is marked not writable and the system writes nothing. It does not fall back to
paraphrasing the tweets.

Two tiers, and the difference is declared in the pack rather than hidden:

  curated  a recurring official release with a hand-written extractor (BLS employment, CPI).
           Fully typed facts, mandatory-coverage list, the pack the existing gates were built for.
  generic  anything else. The document is fetched and every figure is extracted with its exact
           character span and surrounding sentence, but the labels come from the sentence rather
           than from a curated schema, and nothing is marked mandatory. Weaker, and says so.

Source ranking prefers the issuer over commentary: a company's own release outranks a news story
about it, which outranks an aggregator.

Run: .venv/bin/python -B live/resolve_event.py --entity='$SKHY'
"""
from pathlib import Path
import sys, json, re, subprocess, hashlib, datetime, urllib.parse

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
SRC = STORE / 'sources'

# Higher is more primary. Matching these as substrings ranked a newsletter at
# globalmarketsinvestor.beehiiv.com as an investor-relations page (2.6) while eni.com, the company
# actually issuing the release, scored 0.3. The host is parsed instead.
GOV = ('sec.gov', 'bls.gov', 'federalreserve.gov', 'treasury.gov', 'ecb.europa.eu',
       'boj.or.jp', 'imf.org', 'bea.gov', 'census.gov', 'eia.gov', 'opec.org', 'cbo.gov')
IR_PREFIX = ('investor', 'investors', 'ir', 'newsroom', 'press', 'media')
WIRES = ('businesswire.com', 'prnewswire.com', 'globenewswire.com', 'nasdaq.com', 'nyse.com')
NEWS = ('reuters.com', 'bloomberg.com', 'ft.com', 'wsj.com', 'cnbc.com', 'nikkei.com',
        'apnews.com', 'economist.com')
WEAK = ('seekingalpha.com', 'barrons.com', 'marketwatch.com', 'yahoo.com', 'fool.com')
# Self-published newsletters are commentary regardless of what the subdomain is called.
NEWSLETTER = ('beehiiv.com', 'substack.com', 'medium.com', 'ghost.io', 'wordpress.com',
              'blogspot.com')
BLOCKED = ('twitter.com', 'x.com', 't.co', 'youtube.com', 'reddit.com')
IR_PATH = re.compile(r'/(?:investor|investors|news-?release|press-?release|newsroom|media)'
                     r'(?:s|/|-|$)', re.I)


def rank_url(u):
    """Rank by who is speaking: the issuer, a wire carrying the issuer, a newsroom, or a commentator."""
    try:
        parts = urllib.parse.urlsplit(u if '//' in (u or '') else '//' + (u or ''))
    except ValueError:
        return -1.0
    host = (parts.hostname or '').lower().lstrip('.')
    path = parts.path or ''
    if not host or any(host == b or host.endswith('.' + b) for b in BLOCKED):
        return -1.0
    if any(host == g or host.endswith('.' + g) for g in GOV):
        return 3.0
    if any(host == n or host.endswith('.' + n) for n in NEWSLETTER):
        return 0.5
    labels = host.split('.')
    if labels and labels[0] in IR_PREFIX:
        return 2.6
    if any(host == w or host.endswith('.' + w) for w in WIRES):
        return 2.2
    if any(host == n or host.endswith('.' + n) for n in NEWS):
        return 1.4
    if any(host == w or host.endswith('.' + w) for w in WEAK):
        return 0.8
    # A company's own site announcing itself outranks a commentator writing about it.
    if IR_PATH.search(path):
        return 2.0
    return 0.3


NUM = re.compile(
    r'(?<![\w.])([+-]?\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\$?\d+(?:\.\d+)?)\s*'
    r'(billion|trillion|million|bn|mn)?\s*'
    r'(%|percent|percentage points?|bps|basis points|'
    r'won|yuan|renminbi|yen|euros?|dollars?|cents?|USD|KRW|CNY|JPY|EUR|'
    r'units?|shares?|jobs?|wafers?|tons?)?', re.I)

SCALE = {'billion': 1e9, 'bn': 1e9, 'million': 1e6, 'mn': 1e6, 'trillion': 1e12}
UNITS = {'%': 'percent', 'percent': 'percent', 'percentage point': 'percentage_points',
         'percentage points': 'percentage_points', 'bps': 'basis_points',
         'basis points': 'basis_points', 'dollars': 'USD', 'dollar': 'USD', 'cents': 'USD',
         'usd': 'USD', 'won': 'KRW', 'krw': 'KRW', 'yuan': 'CNY', 'renminbi': 'CNY',
         'cny': 'CNY', 'yen': 'JPY', 'jpy': 'JPY', 'euro': 'EUR', 'euros': 'EUR', 'eur': 'EUR',
         'jobs': 'persons', 'shares': 'shares', 'units': 'units', 'unit': 'units',
         'wafers': 'wafers', 'wafer': 'wafers', 'tons': 'tons', 'ton': 'tons'}

# `[^.!?]` treats a decimal point as a sentence end, so "revenues of 79.3187 trillion won" was
# cut after "79." and every label built from it was a fragment. Same defect as the English
# threshold clause in content/crosslang.py.
# A period ends a sentence far less often than it looks. The decimal exception `\.(?=\d)` was
# added when "0.3" split a figure in half; abbreviations then did the same thing to words, and the
# result shipped: a draft read "a sharp 1% spike in the yen against the U." because the source
# sentence had been cut at "U.S.", and "Amazon.com Inc. reported net sales" silently lost its
# company name. The abbreviation forms are matched forward — Python lookbehind must be fixed width
# — so each is consumed as an ordinary character of the sentence.
ABBREV = (r'Inc|Corp|Ltd|Co|Mr|Mrs|Ms|Dr|Prof|Sen|Rep|Gov|No|vs|etc|al|approx|est'
          r'|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec|Fig|St|Ave|Dept')
SENT_CHAR = (r'(?:'
             rf'\b(?:{ABBREV})\.'   # Inc.  Sept.  No.
             r'|\b[A-Z]\.'          # U.S.  E.U.  J.P., one letter at a time
             r'|\.(?=\d)'           # 3.5
             r'|\.(?=[a-z])'        # e.g.  i.e.  a.m.
             r'|[^.!?\n]'
             r')')
SENT = re.compile(rf'{SENT_CHAR}{{10,400}}[.!?]')

# Jina prefixes the document with Title / URL Source / Published Time lines. Those carry the
# provenance and are kept in the stored artifact, but scanning them yielded the URL's own id and
# the timestamp's digits as "facts".
BODY_MARKER = re.compile(r'Markdown Content:\s*', re.I)
# "between 16 percent and 17 percent" produced a single 16-percent fact, and a draft shipped
# "expected to be between 16 percent" — a sentence with no second bound. A range is one fact.
RANGE = re.compile(
    r'(?:between\s+)?(?<![\d.])(?P<lo>[+-]?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*'
    r'(?P<loscale>billion|trillion|million|bn|mn)?\s*(?P<lounit>%|percent|percentage points?|'
    r'bps|basis points|won|yuan|yen|euros?|dollars?|cents?)?\s*'
    r'(?:\s*(?:and|to|–|—|-|~|至|到)\s*)'
    r'(?P<hi>[+-]?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*'
    r'(?P<hiscale>billion|trillion|million|bn|mn)?\s*(?P<hiunit>%|percent|percentage points?|'
    r'bps|basis points|won|yuan|yen|euros?|dollars?|cents?)?', re.I)
URL_RUN = re.compile(r'https?://\S+|www\.\S+')
# "Chart 8", "Table 3", "Note 2" are furniture. One reached a draft as a trade-surplus figure.
FURNITURE = re.compile(r'(?:chart|figure|fig\.|table|exhibit|note|appendix|panel|page|p\.|'
                       r'section|footnote|图|表|附注)\s*$', re.I)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def candidate_urls(entity, posts):
    """Links the watched authors pointed at, plus what a search turns up. The posts supply leads,
    not evidence."""
    out = {}
    for p in posts:
        for u in p.get('urls') or []:
            out.setdefault(u, {'url': u, 'via': 'kol_post', 'post_id': p['post_id'],
                               'rank': rank_url(u)})
    return list(out.values())


def exa_search(query, n=6):
    cmd = ['mcporter', 'call',
           f'exa.web_search_exa(query: "{query}", numResults: {n})']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return []
    urls = re.findall(r'URL:\s*(\S+)', r.stdout or '')
    return [{'url': u, 'via': 'exa_search', 'rank': rank_url(u)} for u in urls]


def jina_fetch(url):
    cmd = ['curl', '-s', '--max-time', '90', f'https://r.jina.ai/{url}']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    t = (r.stdout or '').strip()
    if len(t) < 400 or t.lower().startswith('<!doctype'):
        return None
    return t


def blocks_of(raw):
    out = []
    for m in re.finditer(r'\S[\s\S]*?(?=\n\s*\n|\Z)', raw):
        t = m.group()
        out.append({'id': 'B' + str(len(out) + 1).zfill(4), 'start': m.start(), 'end': m.end(),
                    'text': t, 'sha256': sha(t),
                    'numeric_tokens': re.findall(r'(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?%?', t)})
    return out


def sentence_at(raw, pos):
    for m in SENT.finditer(raw):
        if m.start() <= pos < m.end():
            return m.group().strip(), m.start(), m.end()
    lo, hi = max(0, pos - 160), min(len(raw), pos + 160)
    return raw[lo:hi].strip(), lo, hi


def label_from(sentence, num_text):
    """The subject the figure belongs to, taken from the words before it.

    This is not a curated label and the pack says so. Calling it one would let a generic pack
    pose as the hand-built kind the mandatory-coverage rules were written for.
    """
    idx = sentence.find(num_text)
    lead = sentence[:idx].strip() if idx > 0 else sentence
    lead = re.sub(r'^[^A-Za-z一-鿿]+', '', lead)
    words = lead.split()
    return ' '.join(words[-9:]) if words else sentence[:60]


def body_offset(raw):
    m = BODY_MARKER.search(raw)
    return m.end() if m else 0


def inside_url(raw, pos):
    for u in URL_RUN.finditer(raw):
        if u.start() <= pos < u.end():
            return True
    return False


def _num(txt, scale_word, unit_word):
    try:
        v = float(txt.replace(',', '').replace('$', ''))
    except ValueError:
        return None, None
    unit = UNITS.get((unit_word or '').lower().rstrip('s')) or UNITS.get((unit_word or '').lower())
    if unit is None and txt.strip().startswith('$'):
        unit = 'USD'
    return v * SCALE.get((scale_word or '').lower(), 1), unit


def extract_ranges(raw, event_id, blocks, start_at):
    """Both bounds, as one fact, so a draft cannot ship half a range."""
    out, spans = [], []
    for m in RANGE.finditer(raw, start_at):
        if inside_url(raw, m.start()) or FURNITURE.search(raw[max(0, m.start() - 14):m.start()]):
            continue
        unit_hi = m.group('hiunit') or m.group('lounit')
        unit_lo = m.group('lounit') or m.group('hiunit')
        lo, u_lo = _num(m.group('lo'), m.group('loscale') or m.group('hiscale'), unit_lo)
        hi, u_hi = _num(m.group('hi'), m.group('hiscale'), unit_hi)
        if lo is None or hi is None or u_lo is None or u_lo != u_hi or hi <= lo:
            continue
        # A year pair ("2025 to 2026") is a period, not a quantity.
        if u_lo in ('count', 'units') and 1900 <= lo <= 2100:
            continue
        s, e = m.start(), m.end()
        sentence, s0, s1 = sentence_at(raw, s)
        out.append({
            'id': f'r{len(out) + 1:03d}',
            'label': label_from(sentence, m.group('lo')),
            'label_source': 'sentence lead, not a curated label',
            'kind': 'range',
            'value': lo, 'value_low': lo, 'value_high': hi,
            'unit': u_lo, 'period': None, 'survey': None,
            'source_id': event_id,
            'source_block_ids': [b['id'] for b in blocks if b['start'] < e and b['end'] > s],
            'source_span': {'start': s, 'end': e, 'quote': raw[s:e].strip()},
            'context_sentence': sentence, 'context_span': [s0, s1],
            'extraction': 'paired range scan with exact raw-text offsets',
            'verification': 'offset re-read from the stored document; no human certification',
        })
        spans.append((s, e))
    return out, spans


def extract_facts(raw, event_id, blocks, limit=40):
    facts, seen = [], set()
    start_at = body_offset(raw)
    # Ranges first; a bound already claimed by a range is not also a standalone fact.
    ranges, taken = extract_ranges(raw, event_id, blocks, start_at)
    facts.extend(ranges)
    for m in NUM.finditer(raw, start_at):
        raw_num = m.group(1)
        scale_word = (m.group(2) or '').lower()
        unit_word = (m.group(3) or '').lower()
        span_s, span_e = m.start(), m.end()
        if inside_url(raw, span_s):
            continue
        if FURNITURE.search(raw[max(0, span_s - 14):span_s]):
            continue
        if any(a <= span_s < b for a, b in taken):
            continue
        quote = raw[span_s:span_e].strip()
        if quote in seen:
            continue
        txt = raw_num.replace(',', '').replace('$', '')
        try:
            val = float(txt)
        except ValueError:
            continue
        mult = SCALE.get(scale_word, 1)
        unit = UNITS.get(unit_word.rstrip('s')) or UNITS.get(unit_word)
        if unit is None and raw_num.strip().startswith('$'):
            unit = 'USD'
        # A number with no unit and no currency is a list index, a date part or a section
        # number far more often than it is a fact. Extracting it anyway is what produced
        # "302837085" and "07" from the document header.
        if unit is None:
            continue
        val *= mult
        sentence, s0, s1 = sentence_at(raw, span_s)
        # "August 2, 2026" produced a 2,026-dollar fact, and a draft closed with "the embargoed
        # release date of August 2,026 dollars". A four-digit year is not a quantity.
        if 1900 <= val <= 2100 and not raw_num.strip().startswith('$') \
                and unit in ('USD', 'count', 'units'):
            near = raw[max(0, span_s - 30):span_s]
            if re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{0,2},?\s*$'
                         r'|年\s*$|\b(?:in|since|during|by)\s*$', near, re.I):
                continue
        seen.add(quote)
        facts.append({
            'id': f'g{len(facts) + 1:03d}',
            'kind': 'point',
            'label': label_from(sentence, raw_num),
            'label_source': 'sentence lead, not a curated label',
            'value': int(val) if float(val).is_integer() else val,
            'unit': unit,
            'period': None,
            'survey': None,
            'source_id': event_id,
            'source_block_ids': [b['id'] for b in blocks if b['start'] < span_e and b['end'] > span_s],
            'scale_word': scale_word or None,
            'source_span': {'start': span_s, 'end': span_e, 'quote': quote},
            'context_sentence': sentence,
            'context_span': [s0, s1],
            'extraction': 'generic numeric scan with exact raw-text offsets',
            'verification': 'offset re-read from the stored document; no human certification',
        })
        if len(facts) >= limit:
            break
    return facts


ROLE = {
    'revenue': re.compile(r'\brevenue|\bsales\b|\bturnover\b', re.I),
    'operating_profit': re.compile(r'operating (?:profit|income)', re.I),
    'net_profit': re.compile(r'net (?:profit|income|earnings)', re.I),
}


def plausibility(facts):
    """Internal contradictions a daily pipeline must not walk past.

    The first live pack read "revenues of 79.3187 trillion won ... net profit of 93.9226 trillion
    won" — faithfully, because the release says exactly that. Faithful is not the same as safe to
    publish, so the combination is surfaced rather than left for a reader to notice.
    """
    flags = []
    by_sentence = {}
    for f in facts:
        by_sentence.setdefault(tuple(f['context_span']), []).append(f)
    for _, group in by_sentence.items():
        roles = {}
        for f in group:
            lead = f['context_sentence'][:f['context_sentence'].find(f['source_span']['quote'])] \
                if f['source_span']['quote'] in f['context_sentence'] else f['label']
            for role, pat in ROLE.items():
                if pat.search(lead[-70:] if lead else ''):
                    roles.setdefault(role, f)
        rev = roles.get('revenue')
        for role in ('net_profit', 'operating_profit'):
            other = roles.get(role)
            if rev and other and other['unit'] == rev['unit'] and other['value'] > rev['value']:
                flags.append({
                    'kind': 'profit_exceeds_revenue',
                    'detail': (f"{role} {other['value']:,.0f} {other['unit']} is larger than "
                               f"revenue {rev['value']:,.0f} {rev['unit']} in the same sentence"),
                    'fact_ids': [rev['id'], other['id']],
                    'sentence': rev['context_sentence'][:220],
                    'severity': 'review',
                    'meaning': ('the extraction matches the document; the document itself is odd. '
                                'Do not write from these two figures without checking the source'),
                })
    # A margin above 100% is the same contradiction expressed as a percentage. Flagging only the
    # currency pair left "net margin 118%" in the slot table, and a writer used it.
    for f in facts:
        if f['unit'] != 'percent' or f['value'] <= 100:
            continue
        near = (f.get('context_sentence') or '').lower()
        if re.search(r'margin|利润率|净利率', near):
            flags.append({
                'kind': 'margin_above_100_percent',
                'detail': f"{f['value']:g} percent margin",
                'fact_ids': [f['id']],
                'sentence': (f.get('context_sentence') or '')[:220],
                'severity': 'review',
                'meaning': ('possible with a one-off gain, but not something to assert without '
                            'checking the source'),
            })
    return flags


TOPIC_TERMS = {
    '#fed_policy': ['federal reserve', 'fomc', 'interest rate', 'monetary policy', 'powell'],
    '#inflation': ['inflation', 'consumer price', 'cpi', 'ppi', 'pce'],
    '#jobs': ['payroll', 'employment', 'unemployment', 'jobless'],
    '#tariffs': ['tariff', 'trade', 'import duty'],
    '#yen_fx': ['yen', 'japanese currency', 'bank of japan', 'boj', 'intervention',
                'exchange rate', 'dollar-yen'],
    '#ai_capex': ['capital expenditure', 'capex', 'data center', 'ai infrastructure', 'gpu'],
    '#oil': ['oil', 'crude', 'barrel', 'opec', 'petroleum'],
    '#crypto': ['bitcoin', 'ethereum', 'crypto'],
    '#china_policy': ['china', 'pboc', 'stimulus'],
    '#earnings': ['earnings', 'quarterly results', 'revenue'],
}

STOPWORDS = set('the a an of and or to in on for with is are was were be been this that at by '
                'from as it its will has have had not but if then than so we you they i my our '
                'his her their about into over after before more most very just also can could '
                'would should may might now new one two three'.split())


def entity_terms(entity, posts):
    """What the document has to be about, drawn from the entity and what the authors said.

    A generic query ("yen_fx official announcement press release") returned a crypto exchange's
    product launch: high-ranked, entirely unrelated. The hotspot's own evidence is the only
    description of the story that exists at this point, so it is what gets searched.
    """
    terms = set()
    bare = entity.lstrip('$#')
    if entity.startswith('$'):
        terms.add(bare.lower())
    terms |= set(TOPIC_TERMS.get(entity, []))
    for p in posts[:6]:
        for w in re.findall(r'[A-Za-z]{4,}', p.get('text') or ''):
            w = w.lower()
            if w not in STOPWORDS and not w.startswith('http'):
                terms.add(w)
    return terms


def build_query(entity, posts):
    bare = entity.lstrip('$#').replace('_', ' ')
    topic = ' '.join(TOPIC_TERMS.get(entity, [])[:3])
    lead = ''
    if posts:
        first = min(posts, key=lambda p: p.get('created_at') or '')
        words = [w for w in re.findall(r'[A-Za-z]{4,}', first.get('text') or '')
                 if w.lower() not in STOPWORDS][:8]
        lead = ' '.join(words)
    return ' '.join(x for x in [bare, topic, lead, 'press release announcement'] if x)[:220]


def relevance(raw, entity, terms, min_hits=2):
    """Is the fetched document actually about this story?"""
    low = raw.lower()
    bare = entity.lstrip('$#').lower()
    core = [t for t in TOPIC_TERMS.get(entity, [])] or [bare]
    core_hits = sum(1 for t in core if t in low)
    term_hits = sum(1 for t in terms if len(t) > 3 and t in low)
    ticker_ok = entity.startswith('$') and (bare in low or ('$' + bare) in low)
    ok = ticker_ok or core_hits >= min_hits
    return {'ok': bool(ok), 'core_hits': core_hits, 'core_terms': core,
            'evidence_term_hits': term_hits, 'ticker_named': bool(ticker_ok)}


def resolve(entity, posts, query_hint='', max_fetch=6):
    """Pool the candidates, then pick the most authoritative document that is actually about it.

    Two earlier versions each failed one half of this. Taking the first candidate that passed
    relevance meant the choice depended on Exa's ordering, and swapping in an evidence-driven
    query alone pushed bls.gov out of the pool and left an academic paper standing in for the CPI
    release. Both queries run, every fetched document is scored on authority *and* relevance, and
    the best one wins rather than the first.
    """
    eid = 'ev-' + hashlib.sha256((entity + datetime.date.today().isoformat()).encode()).hexdigest()[:12]
    terms = entity_terms(entity, posts)
    bare = entity.lstrip('$#').replace('_', ' ')
    queries = [query_hint] if query_hint else [
        build_query(entity, posts),
        f'{bare} official press release {datetime.date.today().year}',
    ]

    cands = candidate_urls(entity, posts)
    seen_urls = {c['url'] for c in cands}
    for q in queries:
        for c in exa_search(q):
            if c['url'] not in seen_urls:
                seen_urls.add(c['url'])
                cands.append({**c, 'query': q})
    cands = [c for c in cands if c['rank'] > 0]
    cands.sort(key=lambda c: -c['rank'])

    tried, scored = [], []
    for c in cands[:max_fetch]:
        raw = jina_fetch(c['url'])
        rec = {**c, 'fetched': bool(raw), 'chars': len(raw or '')}
        tried.append(rec)
        if not raw:
            continue
        rel = relevance(raw, entity, terms)
        rec['relevance'] = rel
        if not rel['ok']:
            rec['rejected'] = f"not about this story (core terms hit {rel['core_hits']})"
            continue
        blocks = blocks_of(raw)
        facts = extract_facts(raw, eid, blocks)
        if len(facts) < 3:
            rec['rejected'] = f'only {len(facts)} extractable figures'
            continue
        # Authority decides between documents that are all genuinely about the story.
        # Weighting fact count at parity with authority put a Brookings working paper (rank 0.3,
        # 40 figures) ahead of the Federal Reserve's own release for a Fed-policy story. Authority
        # decides; the fact count only breaks ties between comparable sources.
        rec['selection_score'] = round(c['rank'] * 4 + min(len(facts), 20) / 20
                                       + rel['core_hits'] * 0.2, 3)
        scored.append((rec['selection_score'], c, raw, blocks, facts, rel))

    if not scored:
        return {'ok': False, 'entity': entity, 'reason': 'no primary document yielded facts',
                'queries': queries, 'candidates_tried': tried,
                'consequence': ('this opportunity is not writable; the system does not write '
                                'from the posts themselves')}

    scored.sort(key=lambda x: -x[0])
    _, c, raw, blocks, facts, rel = scored[0]
    SRC.mkdir(parents=True, exist_ok=True)
    path = SRC / (eid + '.txt')
    path.write_text(raw)
    title = (re.search(r'Title:\s*(.+)', raw) or [None, entity])[1]
    packet = {
        'id': eid, 'entity': entity,
        'title': str(title).strip()[:160],
        'event_type': 'hotspot_resolved',
        'tier': 'generic',
        'tier_note': ('labels come from the sentence around each figure, not from a curated '
                      'schema; no fact is marked mandatory and coverage rules do not apply'),
        'published_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'primary_url': c['url'],
        'source_rank': c['rank'],
        'discovered_via': c['via'],
        'search_queries': queries,
        'relevance': rel,
        'candidates_considered': len(cands),
        'candidates_fetched': len(tried),
        'acquisition': 'jina reader proxy over the public page',
        'artifact_sha256': sha(raw),
        'artifact_kind': 'text/markdown',
        'artifact_path': str(path.relative_to(ROOT)),
        'full_narrative': raw,
        'facts': facts,
        'blocks': blocks,
        'coverage': {'required_core_ids': [],
                     'why_empty': 'a generic pack has no curated mandatory set'},
        'methodology': [
            'Figures were scanned generically; a label is the sentence lead, not a curated name.',
            'A KOL post is a lead, never a source. Every fact here comes from the document at '
            'primary_url.',
        ],
        'numeric_passage_ids': [b['id'] for b in blocks if b['numeric_tokens']],
        'next_update': None,
        'version': 1,
        'plausibility_flags': plausibility(facts),
        'signal_posts': [p['post_id'] for p in posts],
        'candidates_tried': tried,
    }
    return {'ok': True, 'packet': packet}


def main():
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    entity = args.get('entity')
    opp = json.loads((STORE / 'opportunities.json').read_text())
    posts = {json.loads(l)['post_id']: json.loads(l)
             for l in (STORE / 'posts.jsonl').read_text().split('\n') if l.strip()}

    targets = []
    for aid, blk in opp['accounts'].items():
        for s in blk['selected']:
            if entity and s['entity'] != entity:
                continue
            targets.append((aid, s))
    if not targets:
        print('no matching opportunity');
        return

    seen = set()
    out = []
    for aid, s in targets:
        if s['entity'] in seen:
            continue
        seen.add(s['entity'])
        ps = [posts[p] for p in s['evidence_post_ids'] if p in posts]
        r = resolve(s['entity'], ps)
        if r['ok']:
            p = r['packet']
            d = ROOT / 'live/store/packets'
            d.mkdir(parents=True, exist_ok=True)
            (d / (p['id'] + '.json')).write_text(json.dumps(p, ensure_ascii=False, indent=2))
            print(f"  OK   {s['entity']:12} {len(p['facts']):>3} facts  rank {p['source_rank']}  "
                  f"{p['primary_url'][:70]}")
        else:
            print(f"  MISS {s['entity']:12} {r['reason']}  "
                  f"(tried {len(r['candidates_tried'])})")
        out.append({'account': aid, 'entity': s['entity'], **{k: v for k, v in r.items()
                                                              if k != 'packet'}})
    (STORE / 'resolution.json').write_text(json.dumps(
        {'run_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'results': out},
        ensure_ascii=False, indent=2))
    return out


if __name__ == '__main__':
    main()
