"""Near-duplicate collapse and event grouping over the news store.

`live/news.py` dedupes on URL and content hash, which catches the same item arriving twice and
nothing else. One wire story republished by three outlets under three URLs arrives three times,
and a writer handed all three would think three sources agreed.

**Why there is no similarity threshold here.**

The obvious design is a cosine cutoff. The first 292 items collected say that cannot work, and
the reason is worth writing down because it is not obvious from the outside. Pairs, measured
against the local multilingual model:

    0.988   BTC跌破84000美元，日内下跌 0.00%   vs   BTC跌破84000美元，日内下跌 2.82%
    0.961   8-K  INDEPENDENCE REALTY TRUST      vs   8-K/A  INDEPENDENCE REALTY TRUST
    0.905   8-K  Enhanced Group Inc.            vs   8-K  FIVE BELOW, INC
    0.881   台湾股市收低…下跌0.25%              vs   Taiwan stocks lower…down 0.25%
    0.816   法官裁定特朗普必须恢复…             vs   Judge orders Trump to restore…
    0.721   特朗普长子旗下1789 Capital拟募资30亿 vs  Trump Jr.'s 1789 Capital seeks $3B

The first three are the **highest-scoring pairs in the corpus and none of them is a duplicate**:
two price snapshots minutes apart, a filing and its amendment, and two unrelated companies whose
filing titles share a template. The last three are genuine duplicates and they score *lower*.
True duplicates run 0.72–0.99 and false positives run 0.80–0.96. The ranges overlap completely,
so any single cutoff either merges different events or splits the same one.

What does separate them is visible in the same six rows:

  * the 8-K pairs differ by **entity** while sharing a template
  * the BTC pair differs by **figure** while sharing a template
  * the cross-language pairs share their **figures** and differ in every word, because a
    translated entity name is a different string but 0.25% is 0.25% in both

So figures are the cross-language invariant, and similarity is demoted to what it is good at:
proposing candidates cheaply. A deterministic adjudication decides, and says why.

Two outputs, deliberately distinct:

    duplicates    the same item from different outlets — collapse to one, keep all sources
    events        different items about the same thing — group, do not collapse

Embeddings run locally on `.runtime/models/embedding` (multilingual, 384-dim): 292 items in 5.4
seconds, no API cost.

Run: .venv/bin/python -B live/cluster.py [--hours=48] [--explain]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime, collections

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
NEWS = STORE / 'news.jsonl'
OUT = STORE / 'events.jsonl'
MODEL = ROOT / '.runtime/models/embedding'

# Recall-oriented. Everything above this is *looked at*; nothing above it is accepted on the
# strength of the score. Set below the lowest true duplicate observed (0.721) with margin.
CANDIDATE_FLOOR = 0.66
# Above this, two items with no figures on either side and overlapping entities are taken as the
# same item. Kept separate from the floor because it decides rather than proposes.
FIGURELESS_DUP = 0.88
# Same thing, different item: grouped into one event, never collapsed.
EVENT_FLOOR = 0.70

# Figures that carry meaning. Percentages, prices, scales — the things that differ between two
# snapshots of the same ticker and survive translation.
FIGURE = re.compile(r'[-+]?\$?\d[\d,]*(?:\.\d+)?\s*'
                    r'(?:%|万亿|亿|万|个百分点|个基点|美元|日元|元|bps?|'
                    r'trillion|billion|million|[TBMK](?![A-Za-z]))?', re.I)
SCALE = {'万亿': 1e12, '亿': 1e8, '万': 1e4, 'trillion': 1e12, 'billion': 1e9,
         'million': 1e6, 't': 1e12, 'b': 1e9, 'm': 1e6, 'k': 1e3}
# A date or a bare small integer is not a measurement and must not decide anything.
NOT_A_MEASURE = re.compile(r'^\d{1,2}$|^(?:19|20)\d{2}$')

TICKER = re.compile(r'\$[A-Z]{1,5}\b|\((\d{10})\)')
# SEC titles are templated; the amendment suffix is the whole difference between two of them.
FORM = re.compile(r'\b(\d{1,2}-[A-Z]{1,2}(?:/A)?)\b')
CAPS = re.compile(r'\b[A-Z][A-Za-z&.\-]{2,}(?:\s+[A-Z][A-Za-z&.\-]{1,}){0,3}\b')
STOP_CAPS = {'The', 'This', 'That', 'And', 'For', 'Inc', 'Corp', 'Ltd', 'LLC',
             'Federal', 'Reserve', 'Board', 'Filer', 'Company'}


# Dates first, or the figure regex reads them as numbers. `2026-09-23` yielded -26, -23 and -9
# on every SEC row, which then agreed across unrelated filings and drove the duplicate rule on
# pure noise. Also SEC item numbers (`Item 7.01`), which are identifiers, not measurements.
DATELIKE = re.compile(r'(?:19|20)\d{2}[-/年]\s?\d{1,2}[-/月]\s?\d{1,2}日?'
                      r'|\d{1,2}[-/]\d{1,2}[-/](?:19|20)?\d{2}'
                      r'|\d{1,2}:\d{2}(?::\d{2})?'
                      r'|\bItem\s+\d{1,2}\.\d{2}\b'
                      r'|\bAccNo:?\s*[\d-]+'
                      # A CIK in parentheses is an identifier. Left in, it became the figure
                      # 1637880.0 and two filings "disagreed on figures" for the only reason
                      # that they are different companies — true, but not what the rule means.
                      r'|\(\d{7,10}\)', re.I)


def figures(text):
    """Normalised numeric values in a string. Scale words applied so $3B == 30亿."""
    out = set()
    text = DATELIKE.sub(' ', text or '')
    for m in FIGURE.finditer(text or ''):
        tok = m.group(0).strip()
        digits = re.sub(r'[^\d.\-+]', '', tok.split('%')[0])
        if not digits or NOT_A_MEASURE.match(digits):
            continue
        try:
            v = float(digits)
        except ValueError:
            continue
        low = tok.lower()
        for word, mult in SCALE.items():
            if word in low:
                v *= mult
                break
        out.add(round(v, 4))
    return out


def entities(text, boilerplate=frozenset()):
    """Tickers, CIK numbers and capitalised names. Language-specific by nature — a translated
    company name shares nothing with its original, which is why this never decides alone.

    `boilerplate` is computed per batch by `template_terms()` rather than hand-listed. SEC
    summaries all carry 'AccNo', 'Filed', 'Financial Statements' and 'Exhibits', so every pair of
    unrelated filings shared an 'entity' and the disjoint-entity veto never fired once in 270
    candidate pairs. A fixed stopword list would have fixed SEC and broken on the next templated
    source; document frequency finds them in whatever the batch happens to contain.
    """
    t = text or ''
    out = {m.group(0) for m in TICKER.finditer(t)}
    out |= {w for w in CAPS.findall(t)
            if w.split()[0] not in STOP_CAPS and len(w) > 3}
    return {w for w in out if w not in boilerplate}


# A name in more than this share of one source's items is describing that source's format, not
# the subject of any one item.
#
# Placed in an observed gap rather than picked. Document frequency across 40 SEC filings:
#
#     Size / Item / AccNo / Filed      1.00      the wrapper on every row
#     Financial Statements / Exhibits  0.82
#     Regulation FD Disclosure         0.42
#     Entry / Directors / Election     0.28-0.35  item headings, a controlled vocabulary
#     ----------------------------------------   nothing at all between 0.28 and 0.025
#     every CIK, every company name    0.025      90 terms, each appearing exactly once
#
# Real identifiers appear once. Everything a filing shares with another filing of the same type
# appears in at least eleven. At 0.30 the item headings survived, and three unrelated companies
# stayed in one group because all three had filed a 'Direct Financial Obligation'.
BOILERPLATE_DF = 0.10
MIN_ITEMS_PER_SOURCE = 4


def template_terms(rows):
    """Per source, not per batch.

    Computed over the whole batch first, at a 0.15 cutoff, this found exactly one term. 'AccNo'
    appears in every SEC filing but SEC was 40 of 292 rows, so its document frequency was 0.137 —
    under the line by accident of how many crypto headlines happened to be in the same pull. A
    global threshold makes template detection depend on the source mix, which changes every run.

    Grouping by source removes that coupling: 'AccNo' is in 100% of SEC items regardless of what
    else was collected, and a term common across *different* sources is a real shared subject
    rather than a template.
    """
    by_source = collections.defaultdict(list)
    for r in rows:
        by_source[r.get('source', '?')].append(r)
    out = set()
    for src, items in by_source.items():
        if len(items) < MIN_ITEMS_PER_SOURCE:
            continue
        df = collections.Counter()
        for r in items:
            df.update(entities(r['title'] + ' ' + (r.get('summary') or '')))
        out |= {w for w, c in df.items() if c / len(items) > BOILERPLATE_DF}
    return out


def strong_ids(text, boilerplate=frozenset()):
    """Only identifiers precise enough to decide that two items are about different things.

    A ticker, a CIK, an all-caps name, or a multi-word proper name. Deliberately **not** a single
    capitalised English word: three unrelated 8-K filings stayed in one group because they all
    contained 'Creation', from the SEC item heading 'Creation of a Direct Financial Obligation'.
    It slipped past the per-source template filter by appearing in under 30% of filings, and one
    shared common noun was enough to defeat the disjoint-entity rule.

    The asymmetry is deliberate. A weak match must not prove sameness, but it also must not prove
    difference — so this set is used only to establish that two items are *not* related, and only
    when both sides carry at least one.
    """
    out = set()
    for e in entities(text, boilerplate):
        if e.startswith('$') or e.startswith('('):
            out.add(e)
        elif ' ' in e or (e.isupper() and len(e) > 3):
            out.add(e)
    return out


def _jaccard(a, b):
    return len(a & b) / len(a | b) if (a or b) else 0.0


def adjudicate(a, b, sim, boilerplate=frozenset()):
    """Duplicate, same event, or unrelated — with the reason, so a wrong call is debuggable.

    **This is now the fallback, not the default.** Run head to head against a model on the same
    60 candidate pairs, it disagreed 19 times and was wrong all 19. See
    `live/adjudicate_llm.py` and the measured comparison in docs/KNOWN_FAILURES.md. Kept because
    it costs nothing and still has to decide when the API is unavailable — failing closed onto a
    known-worse judge beats failing open onto no judge.

    Order matters. Every rule that can say 'different' runs before any rule that can say
    'duplicate', because the failure that costs information is merging two real events, not
    leaving two copies of one.
    """
    ta = a['title'] + ' ' + (a.get('summary') or '')
    tb = b['title'] + ' ' + (b.get('summary') or '')

    # An amendment is a new filing about the same matter. Same event, never the same item.
    fa, fb = set(FORM.findall(a['title'])), set(FORM.findall(b['title']))
    if fa and fb and fa != fb:
        return 'same_event', f'filing forms differ: {sorted(fa)} vs {sorted(fb)}'

    ea, eb = entities(ta, boilerplate), entities(tb, boilerplate)
    ga, gb = figures(ta), figures(tb)

    # Two SEC filings with an identical template and disjoint filers score 0.905 and share
    # nothing. Strong identifiers only — see strong_ids() for the shared word 'Creation' that
    # kept three unrelated filings together when any capitalised token counted.
    sa, sb = strong_ids(ta, boilerplate), strong_ids(tb, boilerplate)
    if sa and sb and not (sa & sb) and a.get('lang') == b.get('lang'):
        return 'unrelated', (f'same language, no shared identifier '
                             f'({sorted(sa)[:2]} vs {sorted(sb)[:2]}); {sim:.3f} is the template)')

    # Two snapshots of one ticker minutes apart score 0.988 and differ only in the number.
    if ga and gb:
        overlap = _jaccard(ga, gb)
        if overlap == 0:
            return 'same_event', f'no shared figure ({sorted(ga)[:3]} vs {sorted(gb)[:3]})'
        if overlap >= 0.5:
            return 'duplicate', f'figures agree (jaccard {overlap:.2f}), similarity {sim:.3f}'
        return 'same_event', f'figures partly overlap (jaccard {overlap:.2f})'

    # Nothing numeric on either side: fall back to similarity plus a shared name.
    if not ga and not gb:
        if sim >= FIGURELESS_DUP and (ea & eb):
            return 'duplicate', f'no figures, similarity {sim:.3f}, shared {sorted(ea & eb)[:2]}'
        return 'same_event', f'no figures to compare, similarity {sim:.3f}'

    # One side quotes a figure and the other does not — a report and a follow-up.
    return 'same_event', 'one side carries figures and the other does not'


def load(hours=48):
    rows = []
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours))
    for line in NEWS.read_text(encoding='utf-8').split('\n'):
        if not line.strip():
            continue
        r = json.loads(line)
        try:
            at = datetime.datetime.fromisoformat(r['published_at'])
        except Exception:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=datetime.timezone.utc)
        if at >= cutoff:
            rows.append(r)
    return rows


def embed(rows):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(str(MODEL), device='cpu')
    texts = [(r['title'] + ' ' + (r.get('summary') or ''))[:500] for r in rows]
    return m.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)


class Groups:
    """Agglomerative merging where an `unrelated` verdict is a hard separator.

    Union-find was the first implementation and it produced a single "event" containing **37 SEC
    filings from 37 unrelated companies**. The adjudication had correctly called those pairs
    unrelated; transitivity routed around it. With forty filings sharing a title template, every
    one is ~0.85 similar to every other, so one weak link merges the lot.

    So a merge here has to clear every existing member, not just the one that proposed it: if any
    item in A is unrelated to any item in B, A and B do not join however strong the pair that
    suggested it. That is complete-linkage with a veto, and the veto is the point — it is what
    makes the entity rule actually bind.
    """

    def __init__(self, n):
        self.of = {i: {i} for i in range(n)}
        self.at = list(range(n))
        self.positive = set()

    def allow(self, a, b):
        self.positive.add((min(a, b), max(a, b)))

    def _all_linked(self, ca, cb):
        """Complete linkage: every cross pair must have been judged positively.

        A veto set was the first attempt and it still let eleven unrelated 8-K filings into one
        group. The hole: a veto only exists for pairs that were adjudicated, and pairs below the
        candidate floor never are. Two filings 0.5 apart have no verdict, so 'not forbidden' was
        true of them and a chain of intermediate merges walked straight through.

        Requiring positive evidence for every cross pair closes it. Absence of a verdict now
        means 'not shown to belong together', which is the correct reading of silence.
        """
        return all((min(x, y), max(x, y)) in self.positive for x in ca for y in cb)

    def join(self, a, b):
        ra, rb = self.at[a], self.at[b]
        if ra == rb:
            return True
        ca, cb = self.of[ra], self.of[rb]
        if not self._all_linked(ca, cb):
            return False
        ca |= cb
        for x in cb:
            self.at[x] = ra
        del self.of[rb]
        return True

    def groups(self):
        return list(self.of.values())


def build(hours=48, adjudicator='llm'):
    import numpy as np
    rows = load(hours)
    if len(rows) < 2:
        return {'rows': len(rows), 'error': 'not enough items in window'}
    boiler = template_terms(rows)
    E = embed(rows)
    S = E @ E.T
    np.fill_diagonal(S, -1)

    dup, ev = Groups(len(rows)), Groups(len(rows))
    calls = collections.Counter()
    decisions = []
    pairs = [(int(i), int(j), float(S[i, j]))
             for i, j in zip(*np.where(np.triu(S, 1) >= CANDIDATE_FLOOR))]
    # Adjudicate everything first, so every veto is known before any merge happens. Merging in
    # discovery order let a weak pair join two clusters that a later verdict would have kept
    # apart.
    # The model decides; the rules decide only if it cannot be reached. A silent downgrade
    # would hide that the run used the judge measured at 0/19 on disagreements, so the fallback
    # is recorded on the result and printed.
    llm_verdicts, judged_by, fallback_reason = {}, adjudicator, None
    if adjudicator == 'llm' and pairs:
        try:
            import adjudicate_llm
            llm_verdicts = adjudicate_llm.judge(
                [(rows[i], rows[j]) for i, j, _ in pairs])
        except Exception as e:
            judged_by, fallback_reason = 'rule', type(e).__name__ + ': ' + str(e)[:140]

    for k, (i, j, sim) in enumerate(pairs):
        m = llm_verdicts.get(k) if judged_by == 'llm' else None
        if m:
            verdict, why = m['verdict'], m['why']
        else:
            verdict, why = adjudicate(rows[i], rows[j], sim, boiler)
        calls[verdict] += 1
        decisions.append({'i': i, 'j': j, 'sim': round(sim, 3),
                          'verdict': verdict, 'why': why})
        if verdict == 'duplicate':
            dup.allow(i, j)
            ev.allow(i, j)
        elif verdict == 'same_event' and sim >= EVENT_FLOOR:
            ev.allow(i, j)

    by_pair = {(d['i'], d['j']): d['verdict'] for d in decisions}
    # Strongest first: a confident pair gets to define a cluster before a marginal one can
    # attach something to it.
    refused = 0
    for i, j, sim in sorted(pairs, key=lambda p: -p[2]):
        v = by_pair[(i, j)]
        if v == 'duplicate':
            dup.join(i, j)
            if not ev.join(i, j):
                refused += 1
        elif v == 'same_event' and sim >= EVENT_FLOOR:
            if not ev.join(i, j):
                refused += 1

    dup_groups = {id(g): sorted(g) for g in dup.groups()}
    ev_groups = {id(g): sorted(g) for g in ev.groups()}
    root_of = {}
    for members in dup_groups.values():
        for i in members:
            root_of[i] = members[0]

    events = []
    for members in sorted(ev_groups.values(), key=lambda m: -len(m)):
        items = [rows[i] for i in members]
        langs = sorted({x['lang'] for x in items})
        srcs = sorted({x['source'] for x in items})
        # Earliest published item names the event, so the label is not whichever outlet we
        # happened to poll first.
        items.sort(key=lambda x: x['published_at'] or '')
        events.append({
            'event_id': 'ev-' + items[0]['item_id'],
            'label': items[0]['title'][:120],
            'size': len(items),
            'languages': langs,
            'sources': srcs,
            'cross_language': len(langs) > 1,
            'first_published_at': items[0]['published_at'],
            'last_published_at': items[-1]['published_at'],
            'item_ids': [x['item_id'] for x in items],
            'titles': [x['title'][:100] for x in items],
            'distinct_items_after_dedup': len({root_of[i] for i in members}),
        })

    return {'rows': len(rows), 'window_hours': hours,
            'candidate_pairs': sum(calls.values()), 'verdicts': dict(calls),
            'duplicate_groups': sum(1 for v in dup_groups.values() if len(v) > 1),
            'items_collapsed': sum(len(v) - 1 for v in dup_groups.values() if len(v) > 1),
            'merges_vetoed': refused,
            'events': events, 'decisions': decisions,
            'judged_by': judged_by,
            'llm_fallback_reason': fallback_reason,
            'pairs_without_model_verdict': sum(
                1 for k in range(len(pairs)) if k not in llm_verdicts) if judged_by == 'llm' else None,
            'thresholds': {'candidate_floor': CANDIDATE_FLOOR, 'event_floor': EVENT_FLOOR,
                           'figureless_duplicate': FIGURELESS_DUP,
                           'boilerplate_df': BOILERPLATE_DF},
            'template_terms_dropped': sorted(boiler)[:25],
            'note': ('similarity proposes, a deterministic rule decides; see the module '
                     'docstring for the six pairs that ruled out a single cutoff')}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    r = build(hours=int(args.get('hours', 48)),
              adjudicator=args.get('adjudicator') if isinstance(args.get('adjudicator'), str)
              else 'llm')
    if r.get('error'):
        raise SystemExit(r['error'])
    print(f"{r['rows']} 条 / {r['window_hours']}h  候选对 {r['candidate_pairs']}  判定 {r['verdicts']}")
    print(f"裁决者：{r['judged_by']}" +
          (f"  ← 模型不可用已降级：{r['llm_fallback_reason']}" if r['llm_fallback_reason'] else ''))
    if r.get('pairs_without_model_verdict'):
        print(f"  其中 {r['pairs_without_model_verdict']} 对模型未给判定，已用规则兜底")
    print(f"重复组 {r['duplicate_groups']}，折叠掉 {r['items_collapsed']} 条")
    multi = [e for e in r['events'] if e['size'] > 1]
    print(f"事件 {len(r['events'])} 个，其中多条目 {len(multi)}，"
          f"跨语言 {sum(1 for e in multi if e['cross_language'])}\n")
    for e in multi[:12]:
        flag = '跨语言' if e['cross_language'] else '     '
        print(f"  [{e['size']}条 {flag}] {e['label'][:64]}")
        for t in e['titles'][1:4]:
            print(f"          · {t[:64]}")
    if 'explain' in args:
        print('\n判定明细（前 20）:')
        for d in sorted(r['decisions'], key=lambda x: -x['sim'])[:20]:
            print(f"  {d['sim']:.3f} {d['verdict']:11} {d['why'][:70]}")
    OUT.write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in r['events']) + '\n')
    print(f"\n写入 {OUT}")


if __name__ == '__main__':
    main()
