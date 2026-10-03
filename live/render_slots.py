"""Slot rendering for a generic fact pack, in either language.

The curated BLS pack has a hand-written Chinese frame per fact id. A pack resolved from a live
hotspot has none: its facts are `g001`-style ids whose labels are English sentence leads. So the
frame has to be built, and the rule that made the curated pipeline safe still has to hold —

    the model never converts a unit or a scale.

Here that means code turns 79,318,700,000,000 KRW into "79.32 万亿韩元" for a Chinese account and
"79.32 trillion won" for an English one. The model writes the sentence around that string and may
not restate the figure any other way. Translating a *label* is not converting a number, so the
model is free to say what the figure is about in its own words; the digits, the scale and the
unit are not its to touch.

Run: .venv/bin/python -B live/render_slots.py --packet=<id> --lang=zh
"""
from pathlib import Path
import sys, json, re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "live"))
import terms
STORE = ROOT / 'live/store'

CN_SCALE = [(1e12, '万亿'), (1e8, '亿'), (1e4, '万')]
EN_SCALE = [(1e12, 'trillion'), (1e9, 'billion'), (1e6, 'million')]

CURRENCY_ZH = {'KRW': '韩元', 'USD': '美元', 'CNY': '元', 'JPY': '日元', 'EUR': '欧元'}
CURRENCY_EN = {'KRW': 'won', 'USD': 'dollars', 'CNY': 'yuan', 'JPY': 'yen', 'EUR': 'euros'}
COUNT_ZH = {'persons': '人', 'shares': '股', 'units': '台', 'wafers': '片', 'tons': '吨'}
COUNT_EN = {'persons': '', 'shares': 'shares', 'units': 'units', 'wafers': 'wafers',
            'tons': 'tons'}


def _trim(x):
    s = f'{x:.2f}'.rstrip('0').rstrip('.')
    return s or '0'


def render_zh(value, unit):
    a = abs(value)
    if unit == 'percent':
        return f'{_trim(value)}%'
    if unit == 'percentage_points':
        return f'{_trim(value)} 个百分点'
    if unit == 'basis_points':
        return f'{_trim(value)} 个基点'
    cur = CURRENCY_ZH.get(unit)
    suffix = cur or COUNT_ZH.get(unit, '')
    for mag, word in CN_SCALE:
        if a >= mag:
            return f'{_trim(value / mag)} {word}{suffix}'
    return f'{value:,.0f}{suffix}' if float(value).is_integer() else f'{_trim(value)}{suffix}'


# How the donors actually write a figure, counted across their own posts rather than chosen:
#
#   12%                1234 occurrences        $96.2B / $118M / $1.2T    588
#   "12 percent"         18                    "$96.2 billion" etc.      267
#
# The spelled-out forms were this renderer's doing. Figures arrive pre-rendered precisely so the
# writer never converts a unit, and the safest-looking way to write them turned out to be a form
# real finance writers essentially never use — "123 million dollars" appears once in 2,086 posts,
# and both blind judges named it unprompted as the strongest sign of machine writing. Determinism
# was never what forced the words; the renderer can emit $118M just as deterministically.
EN_SYMBOL = [(1e12, 'T'), (1e9, 'B'), (1e6, 'M')]
CURRENCY_SYMBOL = {'USD': '$', 'EUR': '€', 'JPY': '¥', 'GBP': '£'}


def render_en(value, unit):
    a = abs(value)
    if unit == 'percent':
        return f'{_trim(value)}%'
    if unit == 'percentage_points':
        n = abs(value)
        return f'{_trim(value)} percentage point' + ('' if n == 1 else 's')
    if unit == 'basis_points':
        return f'{_trim(value)} basis points'

    sym = CURRENCY_SYMBOL.get(unit)
    if sym:
        sign = '-' if value < 0 else ''
        for mag, letter in EN_SYMBOL:
            if a >= mag:
                return f'{sign}{sym}{_trim(a / mag)}{letter}'
        return (f'{sign}{sym}{a:,.0f}' if float(a).is_integer()
                else f'{sign}{sym}{_trim(a)}')

    # A currency with no conventional symbol keeps its name; inventing notation for won or yuan
    # would trade one unfamiliar form for another.
    cur = CURRENCY_EN.get(unit)
    tail = (' ' + cur) if cur else ((' ' + COUNT_EN.get(unit, '')).rstrip())
    for mag, word in EN_SCALE:
        if a >= mag:
            return f'{_trim(value / mag)} {word}{tail}'
    return f'{value:,.0f}{tail}' if float(value).is_integer() else f'{_trim(value)}{tail}'


# The direction a figure carries, taken from the words the source used around it. A generic pack
# has no curated frame, so the sign has to survive from the document's own wording.
UP = re.compile(r'\b(rose|rise|risen|increase[sd]?|grew|grow(?:th|n)?|gain(?:ed|s)?|up|higher|'
                r'surge[sd]?|jump(?:ed)?|climb(?:ed)?|expand(?:ed)?|record)\b', re.I)
DOWN = re.compile(r'\b(fell|fall|fallen|declin\w+|decreas\w+|drop(?:ped)?|down|lower|'
                  r'slump(?:ed)?|shrank|shrink|contract\w+|loss(?:es)?)\b', re.I)


def direction_of(fact):
    lead = (fact.get('context_sentence') or '')
    q = fact['source_span']['quote']
    i = lead.find(q)
    around = lead[max(0, i - 90):i] if i > 0 else lead[:90]
    if DOWN.search(around) and not UP.search(around):
        return 'down'
    if UP.search(around) and not DOWN.search(around):
        return 'up'
    return None


ANY_NUM = re.compile(r'[-+]?\$?\d[\d,]*(?:\.\d+)?\s*'
                     r'(?:trillion|billion|million|percent|%|won|dollars?)?', re.I)
METRIC_WORDS = re.compile(
    r'revenues?|sales|turnover|operating (?:profit|income|margin)|net (?:profit|income)|'
    r'gross margin|margin|cash(?: and cash equivalents)?|capacity|shipments?|inventory|'
    r'capital expenditure|capex|share|ratio|dividend|backlog|orders?', re.I)


LEAD_FUNCTION = {'the','a','an','of','in','on','at','to','by','for','with','and','or','its',
                 'their','his','her','this','that','these','those','is','are','was','were','be',
                 'been','has','have','had','will','would','about','around','approximately',
                 'already','still','also','as','than','from','into','over','up','down'}


def short_subject(phrase, max_words=4):
    """Two to four content words, not the tail of a clause.

    The English branch was handing the writer a whole subordinate clause — "its monthly purchase
    amount by about 400 billion yen" — and demanding it be placed verbatim. Four slots then made
    four long clauses stitched together, which is exactly the uniform 73-128 character sentences
    with no fragments that the style evaluation flagged. The Chinese branch had the opposite bug
    and gave a bare number with no subject at all.
    """
    words = [w for w in re.split(r'\s+', (phrase or '').strip()) if w]
    while words and words[0].lower().strip('*·-—,.:;()') in LEAD_FUNCTION:
        words.pop(0)
    while words and words[-1].lower().strip('*·-—,.:;()') in LEAD_FUNCTION:
        words.pop()
    keep = [w.strip('*·—,;:()') for w in words[-max_words:] if w.strip('*·—,;:()')]
    return ' '.join(keep)


def subject_of(fact, lang='en'):
    """Prefer the model-supplied label when the packet has been through live/label_facts.py.

    The label then goes through terms.canonical, because a model asked to name a metric produces
    the textbook form and the donors never use it: 消费者物价指数 appears zero times in 1,236 of
    their Chinese posts against 54 for CPI.
    """
    got = fact.get('subject_zh' if lang == 'zh' else 'subject_en')
    if not got:
        got = _subject_from_context(fact)
    return terms.canonical(got, 'zh' if lang == 'zh' else 'en')


def _subject_from_context(fact):
    """What this figure is, in words, with every other figure stripped out.

    Masking off-table numbers inside the label stopped the leak and destroyed the meaning: the
    writer could no longer tell revenue from operating profit and attached 60.54 trillion won —
    the operating profit — to revenue. The subject has to survive the masking, so it is built
    from words only.
    """
    ctx = fact.get('context_sentence') or ''
    q = fact['source_span']['quote']
    i = ctx.find(q)
    lead = ctx[:i] if i > 0 else ctx
    # A rate of change is not a level. "operating profit 557%" read as though the profit *was*
    # 557 percent, and the writer produced "51% of revenue came from a 557% operating profit".
    change = bool(re.search(r'increas\w+|grew|grow\w*|rose|up\s|declin\w+|fell|down\s|'
                            r'change[sd]?|versus|compared', lead, re.I))
    # The metric word has to belong to this figure. Taking the last match anywhere in the lead
    # labelled a 160-billion-dollar Fed operation "ratio", because that word appeared far earlier
    # in the sentence.
    tail = lead[-46:]
    hits = METRIC_WORDS.findall(tail)
    if hits:
        base = short_subject(hits[-1].strip())
        if fact.get('unit') in ('percent', 'percentage_points') and change:
            return base + ' growth'
        return base
    words = ANY_NUM.sub(' ', lead)
    s = short_subject(words)
    return s or (fact.get('label') or '')[:40]


DIGIT_RUN = re.compile(r'[\d,.]{4,}')
WORD = re.compile(r'[A-Za-z]{2,}')


def label_quality(fact):
    """How usable the sentence lead is as a subject.

    Sorting every percentage to the front handed the writer eight margin figures and none of the
    revenue, and three of them were scraped out of a results table whose lead reads
    "(K-IFRS)** *Unit: Billion KRW". A figure whose subject cannot be read is not a slot.
    """
    lab = fact.get('label') or ''
    words = WORD.findall(lab)
    digits = sum(len(m.group()) for m in DIGIT_RUN.finditer(lab))
    return len(words) - 2.5 * (digits / max(len(lab), 1) > 0.25) - (2 if len(words) < 3 else 0)


# The curated pipeline works because a slot arrives as a finished phrase the writer only has to
# place. Handing over a bare value plus an English subject put the framing back in the model's
# hands, and it produced "88-layer product" from an 88-trillion-won cash balance. The generic
# path now renders the whole phrase too.
SUBJECT_ZH = {
    'revenue': '营收', 'revenues': '营收', 'sales': '营收', 'turnover': '营收',
    'operating profit': '营业利润', 'operating income': '营业利润',
    'operating margin': '营业利润率', 'gross margin': '毛利率', 'margin': '利润率',
    'net profit': '净利润', 'net income': '净利润',
    'cash': '现金', 'cash and cash equivalents': '现金及现金等价物',
    'capacity': '产能', 'share': '占比', 'ratio': '占比',
    'shipments': '出货量', 'inventory': '库存', 'capex': '资本开支',
    'capital expenditure': '资本开支', 'dividend': '股息', 'backlog': '在手订单',
    'orders': '订单',
}
GROWTH_ZH, GROWTH_EN = '同比增长', 'growth of'


def phrase(subject, value, lang):
    """A finished phrase in the target language, or the number plus a subject to translate.

    A generic English source has subjects outside the known metric set, and pasting them into a
    Chinese piece produced "and with a per-counterparty limit of 1600 亿美元". Rendering the
    number is not negotiable; naming what it is in Chinese is ordinary writing, so an unmapped
    subject is handed over to be translated with the figure locked.
    """
    base = subject.strip()
    is_growth = base.lower().endswith(' growth')
    if is_growth:
        base = base[:-7].strip()
    if lang != 'zh':
        return (f'{base} {GROWTH_EN} {value}' if is_growth else f'{base} {value}'), True
    if any('\u4e00' <= c <= '\u9fff' for c in base):
        return (f'{base}{GROWTH_ZH} {value}' if is_growth else f'{base} {value}'), True
    zh = SUBJECT_ZH.get(base.lower())
    if zh:
        return (f'{zh}{GROWTH_ZH} {value}' if is_growth else f'{zh} {value}'), True
    hint = base + ('（同比增长）' if is_growth else '')
    return f'{value}', False, hint


def build(packet, lang='zh', limit=12):
    """A usable spread of figures, not every figure of one kind.

    A fact caught by a plausibility flag is withheld rather than warned about. Warning the writer
    off the revenue/profit pair while still listing the 118% margin derived from it meant the
    contradiction reached the draft through the back door.
    """
    render = render_zh if lang == 'zh' else render_en
    flagged = {fid for f in (packet.get('plausibility_flags') or [])
               for fid in f.get('fact_ids', [])}
    facts = [f for f in packet['facts'] if f.get('unit') and f['id'] not in flagged
             and not f.get('subject_skip')]
    facts = [f for f in facts if label_quality(f) >= 3]
    # Round-robin across unit families so the writer sees the revenue as well as the margin.
    families = {}
    for f in sorted(facts, key=lambda f: -label_quality(f)):
        fam = ('pct' if f['unit'] in ('percent', 'percentage_points', 'basis_points')
               else 'money' if f['unit'] in CURRENCY_ZH else 'count')
        families.setdefault(fam, []).append(f)
    ordered, i = [], 0
    while len(ordered) < limit and any(families.values()):
        for fam in ('money', 'pct', 'count'):
            if families.get(fam):
                ordered.append(families[fam].pop(0))
                if len(ordered) >= limit:
                    break
        i += 1
        if i > 60:
            break
    # Two slots rendering to the same string are one figure to the reader. Offering both had a
    # draft write "revenue 100 trillion won and cumulative H1 revenue 100 trillion won" as though
    # they were two findings.
    slots, rendered_seen = [], set()
    for f in ordered:
        # A range renders as both bounds. Rendering only `value` would put half a range on the
        # page, which is how "expected to be between 16 percent" reached a draft.
        if f.get('kind') == 'range' and f.get('value_high') is not None:
            lo = render(f['value_low'], f['unit'])
            hi = render(f['value_high'], f['unit'])
            rv = (f'{lo} 至 {hi}' if lang == 'zh' else f'{lo} to {hi}')
        else:
            rv = render(f['value'], f['unit'])
        if rv in rendered_seen:
            continue
        rendered_seen.add(rv)
        v = rv
        subj = subject_of(f, lang)
        made = phrase(subj, v, lang)
        rendered, verbatim = made[0], made[1]
        hint = made[2] if len(made) > 2 else None
        slots.append({
            'slot_id': 'L' + str(len(slots) + 1).zfill(2),
            'rendered': rendered,
            'place_verbatim': verbatim,
            'translate_subject': hint,
            'fact_id': f['id'],
            'value_rendered': v,
            'unit': f['unit'],
            'raw_value': f['value'],
            'direction': direction_of(f),
            'source_quote': f['source_span']['quote'],
            'context_sentence': f['context_sentence'],
            'char_span': [f['source_span']['start'], f['source_span']['end']],
            'label_en': f['label'],
            'subject': subj,
            'rule': ('the digits, the scale and the unit are rendered here; the writer supplies '
                     'the sentence and may not restate the figure any other way'),
        })
    return slots


def main():
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    pid = args.get('packet')
    files = sorted((STORE / 'packets').glob('*.json'))
    p = json.loads((STORE / 'packets' / (pid + '.json')).read_text()) if pid \
        else json.loads(files[0].read_text())
    for lang in ('zh', 'en'):
        print(f"\n=== {p['entity']}  {lang}  ({p['primary_url'][:60]}) ===")
        for s in build(p, lang)[:8]:
            d = {'up': '↑', 'down': '↓', None: ' '}[s['direction']]
            print(f"  {s['slot_id']} {d} {s['rendered']}")


if __name__ == '__main__':
    main()
