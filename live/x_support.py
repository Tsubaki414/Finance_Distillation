"""Own-X packets that carry only one half of a judgment pack (Oct 8 PM P1).

A judgment packet needs a grounded view AND a fact (demo_matrix_compose.balanced; compose.eligible refuses
judgment_take / contrarian_take without a fact). X extraction usually yields only one of the two, so on 10-08 82% of
the (account, own X post) pairs never reached a pool. Two honest ways in, both only for the account's OWN X sources:

* view-only post + support fact (FD_X_SUPPORT, default 1): attach a real fact unit from
  1. a public (non-X) A/B source on the same story / 母题 - linked by the deterministic 母题 rules of live/hotspot.py
     (same URL / headline event / news hook / number + entity / two rare entities ...), or by one known coin / stock
     / $CASHTAG that the VIEW's own subject names, that is not a broad one (document frequency <= 3x the hotspot
     rarity bar, so BTC / SPX go to the price instead) and that the attached fact states (10-08 probe: a free-word
     entity link paired "Genius platform" with the GENIUS Act, so plain names do not count); published within 48h of
     the post and not after the selection reference; or
  2. the reality payload: the latest price of the main ticker the VIEW names (subject / statement / quotes), from the
     free chart fetchers (live/charts.py), only for a known coin / stock symbol (an unknown $CASHTAG could resolve to
     an unrelated listing).
  The support records keep their own source (publisher, URL, time); their span text joins the evidence packet, so the
  grounding checks read it, and the inbox row lists it as a citation. Nothing is generated: no fact, no number.
* fact-only post (FD_X_DATA, default 1): a packet with a numbered fact enters the pool for a news/data angle
  (post type data_take, which every fd20 persona has) instead of a judgment it cannot ground.
"""
from __future__ import annotations

import copy
import os
import re
from datetime import timedelta

from live import hotspot
from live.distillation_source import digest

VERSION = 'x-support-v1'
WINDOW_H = 48
MAX_FACTS = 2
# deterministic same-story links accepted for a support fact, strongest first (bigram-only zh headline links are not)
LINKS = ('url', 'headline', 'hook', 'number+entity', 'round_number+entity', 'entities', 'entity+zh_headline',
         'zh_headline+entities', 'view_entity')
DATA_POST_TYPE = 'data_take'


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_X_SUPPORT', '1') != '0'


def data_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_X_DATA', '1') != '0'


def price_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_X_SUPPORT_PRICE', '1') != '0'


def _is_fact(unit):
    return unit.get('kind') == 'fact' and unit.get('usage') != 'topic_only'


def has_fact(group):
    return any(_is_fact(r['unit']) for r in group)


# a data angle needs a market / money number: a bare count or a time span ("13 years ago, OKX started ...", "a quota
# of 7300", "within 5 minutes" on 10-08) is not data worth a post
DATA_UNITS = frozenset({'USD', 'CNY', 'EUR', 'HKD', 'JPY', 'percent', 'percentage_points', 'multiple', 'bps'})


def data_number(unit):
    return any(q[1] in DATA_UNITS for n in unit.get('numbers') or [] for q in n.get('quantity') or []
               if isinstance(q, (list, tuple)) and len(q) > 1)


def data_only(group, has_valid_view):
    """A packet without a grounded view whose facts carry at least one money / percent / multiple number
    (data_take needs facts with numbers)."""
    return (not any(has_valid_view(r['unit']) for r in group)
            and any(_is_fact(r['unit']) and data_number(r['unit']) for r in group))


def view_only(group, has_valid_view):
    return any(has_valid_view(r['unit']) for r in group) and not has_fact(group)


def is_support(record):
    return bool(record.get('support'))


def view_text(group, has_valid_view=None):
    """Subject, statement, reasoning and quotes of the packet's structured views (what the post itself argues)."""
    out = []
    for r in group:
        u = r['unit']
        v = u.get('view')
        if u.get('kind') != 'view' or not isinstance(v, dict) or (has_valid_view and not has_valid_view(u)):
            continue
        out += [str(v.get('subject') or ''), str(u.get('statement') or '')]
        out += [str(x) for x in v.get('reasoning') or []]
        out += [str((q or {}).get('quote') or '') for q in v.get('support') or [] if isinstance(q, dict)]
    return '\n'.join(x for x in out if x)


def subject_tickers(group):
    """Known coin / stock symbols and $CASHTAGS in the subjects of the packet's structured views (lower case)."""
    from live.charts import subjects_in
    subj = ' '.join(str(r['unit']['view'].get('subject') or '') for r in group
                    if r['unit'].get('kind') == 'view' and isinstance(r['unit'].get('view'), dict))
    return ({x.lower() for x in subjects_in(subj)}
            | {m.lower() for m in re.findall(r'\$([A-Za-z]{2,10})\b', subj)})


def own_records(group):
    return [r for r in group if not is_support(r)]


def _unit_text(unit):
    return f"{unit.get('statement') or ''} " + ' '.join(s.get('exact_text') or '' for s in unit.get('source_spans') or [])


def _x(source):
    return str((source or {}).get('adapter') or '').startswith('x:')


class Index:
    """Public (non-X) A/B sources with at least one fact unit, published in (ref - window_h, ref]."""

    def __init__(self, store, ref, text_of, window_h=WINDOW_H, price=None, fetchers=None):
        from live import news_hook
        self.ref, self.text_of, self.fetchers = ref, text_of, fetchers or {}
        self.price = price_enabled() if price is None else price
        self._prices = {}
        groups = hotspot.gather(store, ref, window_h=window_h)
        self.public, mats = [], []
        for key in sorted(groups, key=str):
            g = groups[key]
            m = hotspot.material(key, g, text_of(g))
            if m['_t'] is None:
                continue
            try:
                m['_hooks'] = set(news_hook.hooks(m['title']))
            except Exception:   # noqa: BLE001
                pass
            m['_event'] = hotspot._title_event(m['title'])
            mats.append(m)
            facts = [r for r in g if _is_fact(r['unit'])]
            if facts and not _x(g[0]['source']) and not hotspot.DIGEST.search(m['title']):
                self.public.append((m, facts))
        self.df = {}
        for m in mats:
            for e in m['_ents']:
                self.df[e] = self.df.get(e, 0) + 1
        self.rare = max(3, int(0.01 * len(mats)))

    def _material(self, group):
        from live import news_hook
        src = group[0]['source']
        m = hotspot.material((src.get('source_hash'), src.get('id')), group, self.text_of(group))
        try:
            m['_hooks'] = set(news_hook.hooks(m['title']))
        except Exception:   # noqa: BLE001
            pass
        m['_event'] = hotspot._title_event(m['title'])
        return m

    def public_fact(self, group):
        """(link reason, public material, fact records) of the best same-story public source, or None."""
        m = self._material(group)
        if m['_t'] is None:
            return None
        view_ents = hotspot.entities(view_text(group))
        view_ticks = subject_tickers(group)
        best = None
        for pm, facts in self.public:
            if pm['url'] and pm['url'] == m['url']:
                continue
            if abs(pm['_t'] - m['_t']) > timedelta(hours=WINDOW_H) or pm['_t'] > self.ref:
                continue
            why = hotspot.link_reason(m, pm, self.df, self.rare)
            facts_ok = facts
            if why not in LINKS:
                # one specific entity the view itself names, stated by the fact unit that gets attached
                ents = {e for e in view_ticks & pm['_ents'] if self.df.get(e, 0) <= 3 * self.rare}
                facts_ok = [r for r in facts if ents & hotspot.entities(_unit_text(r['unit']))]
                if not ents or not facts_ok:
                    continue
                why = 'view_entity'
            shared = len(m['_ents'] & pm['_ents']) + len(m['_nums'] & pm['_nums'])
            score = (-LINKS.index(why), shared, pm['n_numbers'] > 0, -abs((pm['_t'] - m['_t']).total_seconds()))
            if best is None or score > best[0]:
                best = (score, why, pm, facts_ok)
        if best is None:
            return None
        _, why, pm, facts = best

        def rel(r):
            text = _unit_text(r['unit'])
            return (len(hotspot.entities(text) & (m['_ents'] | view_ents)) + len(hotspot.numbers(text) & m['_nums']),
                    bool(r['unit'].get('numbers')))
        ranked = sorted(facts, key=rel, reverse=True)
        return why, pm, ranked[:MAX_FACTS]

    def price_fact(self, group):
        """Synthetic fact record from the latest price of the post's main known ticker, or None."""
        if not self.price:
            return None
        from live import charts
        text = view_text(group)
        subj = charts.pick_subject(text)
        if not subj or not (subj['symbol'] in charts.CRYPTO or subj['symbol'] in charts.STOCKS):
            return None
        if subj['symbol'] not in self._prices:
            # the price is always the latest one (as_of = its own bar time, never relabelled to the reference)
            self._prices[subj['symbol']] = hotspot.price_line(text, **self.fetchers)
        p = self._prices[subj['symbol']]
        if not p or p['symbol'] != subj['display']:
            return None
        return price_record(p)

    def support(self, group):
        """Support for a view-only own-X packet: {'kind', 'link', 'source', 'records'} or None."""
        hit = self.public_fact(group)
        if hit:
            why, pm, facts = hit
            src = facts[0]['source']
            cite = {'id': src.get('id'), 'source_id': src.get('source_id'), 'title': pm['title'], 'url': pm['url'],
                    'publisher': pm['publisher'], 'published_at': pm['published_at'], 'lang': pm['lang']}
            records = []
            for r in facts:
                r = copy.deepcopy(r)
                r['support'] = {'kind': 'public_fact', 'link': why, 'source': cite}
                r['unit']['support_source'] = cite
                records.append(r)
            return {'version': VERSION, 'kind': 'public_fact', 'link': why, 'source': cite, 'records': records}
        rec = self.price_fact(group)
        if rec:
            return {'version': VERSION, 'kind': 'reality_price', 'link': 'ticker', 'source': rec['support']['source'],
                    'records': [rec]}
        return None


def price_record(p):
    """A fact record whose only span is the plain price line (the same text hotspot.reality_lines writes)."""
    chg = f", {p['change_window']} {p['change_pct']:+.2f}%" if p.get('change_pct') is not None else ''
    line = f"{p['symbol']} {p['last_text']} ({p['source']}, as of {p['as_of']}{chg})"
    h = digest(line)
    numbers = [{'text': p['last_text'], 'metric': f"{p['symbol']} price", 'period': p['as_of'], 'span_ref': 0,
                'quantity': [[str(p['last']), 'USD']]}]
    if p.get('change_pct') is not None:
        numbers.append({'text': f"{p['change_pct']:+.2f}%", 'metric': f"{p['symbol']} {p['change_window']} change",
                        'period': p['as_of'], 'span_ref': 0, 'quantity': [[f"{p['change_pct']:.2f}", 'percent']]})
    cite = {'id': f'price-{h[:16]}', 'source_id': 'market_price', 'title': line, 'url': p.get('url'),
            'publisher': p['source'], 'published_at': p['as_of'], 'lang': 'en'}
    uid = f'price-{h[:20]}'
    unit = {'unit_id': uid, 'kind': 'fact', 'usage': 'paraphrase', 'statement': line, 'numbers': numbers, 'view': None,
            'source_id': 'market_price', 'source_hash': h, 'licence_tier': 'B', 'published_at': p['as_of'],
            'speaker': p['source'], 'speaker_type': 'market_data', 'entities': None, 'time_ref': p['as_of'],
            'source_spans': [{'source_hash': h, 'paragraph_id': 'P1', 'start': 0, 'end': len(line), 'exact_text': line,
                              'typography_normalized': False}],
            'support_source': cite}
    source = {'id': cite['id'], 'source_id': 'market_price', 'publisher': p['source'], 'title': line,
              'url': p.get('url'), 'published_at': p['as_of'], 'source_hash': h, 'adapter': 'reality:price',
              'source_language': 'en'}
    return {'unit_id': uid, 'licence_tier': 'B', 'unit': unit, 'source': source,
            'support': {'kind': 'reality_price', 'link': 'ticker', 'source': cite}, 'tag_personas': []}


def citations(result, support):
    """Claim-ledger rows of a draft that cite a support unit, with that unit's own source (for the inbox row)."""
    if not support:
        return []
    by_id = {r['unit_id']: r['support']['source'] for r in support.get('records') or []}
    out = []
    for row in (result or {}).get('claim_ledger') or []:
        if isinstance(row, dict) and row.get('unit_id') in by_id:
            s = by_id[row['unit_id']]
            out.append({'claim': row.get('claim'), 'unit_id': row['unit_id'], 'publisher': s.get('publisher'),
                        'url': s.get('url'), 'published_at': s.get('published_at')})
    return out


def summary(support):
    """Compact plan / inbox form (records kept separately)."""
    if not support:
        return None
    return {'version': support.get('version'), 'kind': support['kind'], 'link': support['link'],
            'source': support['source'], 'unit_ids': [r['unit_id'] for r in support['records']],
            'statements': [re.sub(r'\s+', ' ', str(r['unit'].get('statement') or ''))[:240]
                           for r in support['records']]}
