"""What each language community is saying about one event, and where they part company.

`Cross-language Information Gap` is one of the six content lanes, and the amended carrying rule in
CLAUDE.md is what makes it workable: 「搬运只能跨语言或跨平台，同语言同平台一律不准搬」. Information
may cross the boundary; sentences may not. So this assembles *evidence* — who said what, when, in
which language — and hands it to the writer as material to reason over. It never hands across a
sentence to be rewritten, and it is not a translation step.

The distinction that keeps this honest: a gap is an observation about **our collection**, not
about the world. If no Chinese author in the watchlist mentioned an entity, that is what the
watchlist saw, not proof the Chinese-speaking market was silent. Every gap below is phrased that
way, and the acceptance contract requires the same care — 「An English search with no match does
not prove novelty」.

What it reports for one entity over a window:

  first_seen       earliest post on each side, so 「谁最早提出」 has a timestamp rather than a claim
  authors          distinct authors per language, the denominator for everything else
  shared_terms     vocabulary both sides use, and vocabulary only one side uses
  coverage_gap     one-sided coverage, stated as a fact about the watchlist

Run: .venv/bin/python -B live/crosslang.py --entity='#fed_policy' [--days=30]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime, collections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
STORE = ROOT / 'live/store'
OUT = STORE / 'crosslang'

# The same alias table the hotspot pass uses, so an entity means one thing across the pipeline.
ALIAS = {
    '#fed_policy': [r'\bFOMC\b', r'\bFed\b', r'Federal Reserve', r'美联储', r'联准会'],
    '#inflation': [r'\bCPI\b', r'\bPCE\b', r'inflation', r'通胀', r'物价'],
    '#ai_capex': [r'\bcapex\b', r'capital expenditure', r'资本开支', r'算力投入'],
    '#yen_fx': [r'\byen\b', r'\bBOJ\b', r'日元', r'日央行'],
    '#oil': [r'\bcrude\b', r'\bWTI\b', r'\bBrent\b', r'原油', r'油价'],
}
STOP = set('the a an of to in on for and or is are was were be been it its this that with as at '
           'from by not but we they he she you i my our their have has had will would can could '
           'about more most than then so if when what which who'.split())
TERM = re.compile(r'\$[A-Z]{1,5}\b|[A-Za-z][A-Za-z\-]{3,}|[一-鿿]{2,4}')


def _patterns(entity):
    if entity in ALIAS:
        return [re.compile(p, re.I) for p in ALIAS[entity]]
    return [re.compile(re.escape(entity.lstrip('#$')), re.I)]


def _lang(text):
    return 'zh' if re.search(r'[一-鿿]', text or '') else 'en'


def _dt(s):
    try:
        d = datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except Exception:
        return None
    return d.astimezone(datetime.timezone.utc) if d.tzinfo else d.replace(
        tzinfo=datetime.timezone.utc)


def gather(entity, days=30):
    import clean as clean_mod
    pats = _patterns(entity)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    hits = []
    for line in (STORE / 'posts.jsonl').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get('is_retweet'):
            continue
        c = clean_mod.clean_post(r)
        t = c['text']
        if len(t) < 120 or c['cleaning']['excluded']:
            continue
        d = _dt(r.get('created_at'))
        if d is None or d < cutoff:
            continue
        if not any(p.search(t) for p in pats):
            continue
        hits.append({'handle': r['handle'], 'post_id': r['post_id'], 'at': d,
                     'lang': _lang(t), 'text': t})
    hits.sort(key=lambda h: h['at'])
    return hits


URL_ANY = re.compile(r'https?://\S+|t\.co/\S+|\bwww\.\S+')
# Exchange and product names that ride along in promotional context. They are not what either
# community is *saying* about an event, and leaving them in made "bitget" and "gate" read as
# Chinese-only framing of Fed policy when they are venue names in a sponsor line.
VENUE = set('bitget gate okx binance bybit coinbase kraken huobi bitfinex 一站交易 交易所'.split())


def _terms(texts):
    c = collections.Counter()
    for t in texts:
        t = URL_ANY.sub(' ', t or '')
        for w in TERM.findall(t):
            w = w.lower() if w.isascii() else w
            if w in STOP or w in VENUE or len(w) < 2:
                continue
            c[w] += 1
    return c


def analyse(entity, days=30, per_side=6):
    hits = gather(entity, days)
    zh = [h for h in hits if h['lang'] == 'zh']
    en = [h for h in hits if h['lang'] == 'en']
    tz, te = _terms(h['text'] for h in zh), _terms(h['text'] for h in en)
    shared = sorted(set(tz) & set(te), key=lambda w: -(tz[w] + te[w]))[:20]

    def side(rows):
        if not rows:
            return {'posts': 0, 'authors': 0, 'first_seen': None, 'first_by': None,
                    'exemplars': []}
        return {
            'posts': len(rows),
            'authors': len({r['handle'] for r in rows}),
            'author_list': sorted({r['handle'] for r in rows}),
            'first_seen': rows[0]['at'].isoformat(),
            'first_by': rows[0]['handle'],
            # Excerpts, with author and id, as material to reason over — never to rewrite.
            'exemplars': [{'handle': r['handle'], 'post_id': r['post_id'],
                           'at': r['at'].isoformat(), 'text': r['text'][:700]}
                          for r in rows[-per_side:]],
        }

    z, e = side(zh), side(en)
    gap = None
    if z['posts'] and not e['posts']:
        gap = 'only_zh'
    elif e['posts'] and not z['posts']:
        gap = 'only_en'
    lead = None
    if z['first_seen'] and e['first_seen']:
        dz, de = _dt(z['first_seen']), _dt(e['first_seen'])
        hours = round((de - dz).total_seconds() / 3600, 1)
        lead = {'earlier_side': 'zh' if hours > 0 else 'en',
                'hours_ahead': abs(hours),
                'zh_first_by': z['first_by'], 'en_first_by': e['first_by'],
                'caveat': ('earliest *in this watchlist*, not earliest anywhere; the collection '
                           'polls a fixed set of accounts on a schedule')}
    return {
        'entity': entity, 'window_days': days,
        'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'zh': z, 'en': e,
        'shared_vocabulary': shared,
        'only_zh_vocabulary': [w for w, _ in tz.most_common(40) if w not in te][:12],
        'only_en_vocabulary': [w for w, _ in te.most_common(40) if w not in tz][:12],
        'coverage_gap': gap,
        'who_first': lead,
        'limits': [
            'a one-sided gap is a fact about this watchlist, not about the market',
            'earliest here means earliest among polled accounts, not earliest anywhere',
            'shared vocabulary is token overlap, not agreement; two authors can use the same '
            'word to argue opposite cases',
            'the one-sided vocabulary lists compare across scripts, so a word and its own '
            'translation both look one-sided: 加息 lands in only_zh and hike in only_en while '
            'being the same idea. What is informative is a term with no counterpart on the '
            'other side at all — 美股/港股/黄金 against treasury/yield is two communities '
            'reading one event through different assets. Telling those two cases apart is a '
            'reading, and the writer has to do it',
            'consensus and divergence are not computed — the excerpts are material for a writer '
            'to read, and that reading is the analysis',
        ],
        'version': 'crosslang-v1',
    }


def as_slots(analysis, lang='zh', start=90):
    """The collection counts, as internal evidence the writer may reason from but may not print.

    **These used to be placeable slots, and that was wrong in a way a caveat could not fix.**

    The original reasoning ran: a cross-language piece has to say how many authors on each side
    posted and who was first; those are figures; the audit rejects any figure not on the slot
    table; therefore they belong on the table, carrying `source: collection` and a subject saying
    观察窗口/in this watchlist so nobody mistakes them for facts about the market.

    Every step of that is true and the conclusion still produced this, in a draft meant for a
    real account:

        我们观察名单内，45天窗口提到该事件的英文作者有11位，中文作者4位。
        英文侧最早提及领先134.3小时。

    No account posts its own bookkeeping. Labelling the number honestly does not make it
    publishable — it makes it an honestly-labelled number that still has no business in the
    text. And the label was not even sufficient: 「134.3小时」 is a difference between two
    collection timestamps across twelve handles, and the draft rendered it as 「英文社区最早」,
    a claim about a community that twelve accounts cannot support.

    So the counts stay computed, stay in the record, and stay out of the writer's slot table.
    What the writer gets for this lane is the posts themselves — what each side actually said —
    which is the thing a reader can check and the thing a person would write about. The counts
    remain available to the reviewer, where a sample size belongs.
    """
    z, e, w = analysis['zh'], analysis['en'], analysis.get('who_first') or {}
    days = analysis['window_days']
    rows = []

    def add(value, subj_zh, subj_en, note):
        rows.append({'value': value, 'zh': subj_zh, 'en': subj_en, 'note': note})

    add(z['authors'], f'{days} 天窗口内提到该事件的中文作者数（本观察名单内）',
        f'Chinese-language authors in this watchlist posting on it over {days} days',
        'collection count')
    add(e['authors'], f'{days} 天窗口内提到该事件的英文作者数（本观察名单内）',
        f'English-language authors in this watchlist posting on it over {days} days',
        'collection count')
    add(z['posts'], f'{days} 天窗口内的中文帖数（本观察名单内）',
        f'Chinese-language posts in this watchlist over {days} days', 'collection count')
    add(e['posts'], f'{days} 天窗口内的英文帖数（本观察名单内）',
        f'English-language posts in this watchlist over {days} days', 'collection count')
    if w:
        add(w['hours_ahead'],
            f'{"英文" if w["earlier_side"] == "en" else "中文"}侧在本名单内最早提及领先的小时数',
            f'hours by which the {w["earlier_side"]} side was first in this watchlist',
            'collection timestamp difference')

    out = []
    for i, r in enumerate(rows):
        subj = r['zh'] if lang == 'zh' else r['en']
        val = f"{r['value']:g}"
        out.append({
            'slot_id': f'C{start + i}',
            'rendered': f"{subj} {val}",
            'place_verbatim': False,
            'translate_subject': subj,
            'fact_id': None,
            'value_rendered': val,
            'unit': None,
            'raw_value': r['value'],
            'direction': None,
            'source': 'collection',
            'source_quote': None,
            'context_sentence': (f"counted from live/store/posts.jsonl over {days} days; "
                                 f"{r['note']}"),
            'char_span': None,
            'label_en': subj,
            # Read by live/write.py, which keeps these in the record and withholds them from the
            # writer. A flag rather than a comment because the previous guard was a caveat string
            # asking the writer to be careful, and the writer printed the number anyway.
            'publishable': False,
            'withheld_reason': ('our own collection bookkeeping: a count over this watchlist, not '
                                'a fact about the market, and no real account publishes its own '
                                'sample size'),
            'caveat': ('a count of this watchlist, not of the market; evidence for the reviewer, '
                       'not a figure for the text'),
        })
    return out


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    entity = args.get('entity') or '#fed_policy'
    days = int(args.get('days', 30))
    r = analyse(entity, days)
    OUT.mkdir(parents=True, exist_ok=True)
    fn = OUT / (re.sub(r'[^A-Za-z0-9_]', '_', entity) + '.json')
    fn.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    print(f"{entity}  窗口 {days} 天")
    print(f"  中文 {r['zh']['posts']} 帖 / {r['zh']['authors']} 位作者   "
          f"英文 {r['en']['posts']} 帖 / {r['en']['authors']} 位作者")
    if r['who_first']:
        w = r['who_first']
        print(f"  最早提出：{w['earlier_side']} 侧领先 {w['hours_ahead']} 小时 "
              f"（zh {w['zh_first_by']} / en {w['en_first_by']}）")
    print(f"  覆盖缺口：{r['coverage_gap'] or '两侧都有'}")
    print(f"  共用词：{r['shared_vocabulary'][:10]}")
    print(f"  仅中文：{r['only_zh_vocabulary'][:8]}")
    print(f"  仅英文：{r['only_en_vocabulary'][:8]}")
    print(f"  写入 {fn}")


if __name__ == '__main__':
    main()
