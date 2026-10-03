"""Conservative EN/ZH numerical comparison; observations are not semantic proof.

Ranges carry a shared scale/unit, ratios and percentage points keep distinct
meaning, and formula checks ignore layout only. Never generate new arithmetic.
"""
from collections import Counter
from decimal import Decimal
from datetime import date, datetime
import re

VERSION = 'numeric-fidelity-v3-compound-units-time-anchors'

VALUE = r'[+-]?\d+(?:,\d{3})*(?:\.\d+)?'
CUR = r'US\$|USD|CNY|RMB|EUR|\$|€|人民币'
SCALE = r'trillion|billion|million|thousand|bn\b|mn\b|[BMK]\b|万亿|亿|万'
UNIT = r'percentage\s+points?|percent(?:age)?|basis\s+points?|bps\b|个百分点|个?基点|%|％|美元|人民币|欧元|元|times\b|倍|[x×]\b'
SCALES = {'trillion':'1e12','billion':'1e9','million':'1e6','thousand':'1e3','bn':'1e9','mn':'1e6','b':'1e9','m':'1e6','k':'1e3','万亿':'1e12','亿':'1e8','万':'1e4'}
RANGE = re.compile(rf'(?P<ca>{CUR})?\s*(?P<a>{VALUE})\s*(?P<sa>{SCALE})?\s*(?P<ua>{UNIT})?\s*(?:to\b|through\b|到|至|[-–—~])\s*(?P<cb>{CUR})?\s*(?P<b>{VALUE})\s*(?P<sb>{SCALE})?\s*(?P<ub>{UNIT})?',re.I)
NUMBER = re.compile(rf'(?P<c>{CUR})?\s*(?P<n>{VALUE})\s*(?P<s>{SCALE})?\s*(?P<u>{UNIT})?',re.I)
MONTHS = 'January February March April May June July August September October November December'.split()


# Only explicit parenthesized navigation, never table values or narrative claims.
TABLE_NAV_EN = re.compile(r'\(\s*See\s+(?:tables?\s+[A-Z]-\d+(?:\s*(?:,\s*(?:and\s+)?|and\s+)[A-Z]-\d+)*|(?:Summary|summary)\s+table\s+[A-Z])\.?\s*\)', re.I)
TABLE_NAV_ZH = re.compile(r'[（(]\s*见(?:表\s*[A-Z]-\d+(?:\s*[、,，和及]\s*(?:表\s*)?[A-Z]-\d+)*|汇总表\s*[A-Z])\s*[。.]?\s*[）)]', re.I)
MONTH_ALIASES = {name.lower(): i for i, name in enumerate(MONTHS, 1)}
MONTH_ALIASES.update({name[:3].lower(): i for i, name in enumerate(MONTHS, 1)})
MONTH_ALIASES['sept'] = 9
MONTH_PATTERN = '|'.join(sorted(MONTH_ALIASES, key=len, reverse=True))
DATE_EN = re.compile(r'\b(?P<month>'+MONTH_PATTERN+r')\.?\s+(?P<day>\d{1,2})(?:,\s*|\s+)(?P<year>\d{4})\b', re.I)
DATE_ZH = re.compile(r'(?P<year>\d{4})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日')


def without_navigation(text):
    return TABLE_NAV_ZH.sub('', TABLE_NAV_EN.sub('', text))


def calendar_dates(text):
    found = []
    for pattern in (DATE_EN, DATE_ZH):
        for match in pattern.finditer(text):
            month = MONTH_ALIASES.get(match['month'].lower(), match['month'])
            value = (int(match['year']), int(month), int(match['day']))
            try:
                found.append(date(*value).isoformat())
            except ValueError:
                found.append('invalid:' + '-'.join(map(str, value)))
    return Counter(found)


def without_calendar_dates(text):
    for pattern in (DATE_EN, DATE_ZH):
        text = pattern.sub(lambda m: ' ' * len(m.group()), text)
    return text


def normalize(text):
    text = text.replace('\u2212', '-').replace('\ufe63', '-').replace('\uff0d', '-')
    # Compound adjectives retain the same explicit unit: 22-basis-point fall.
    # Only unit compounds are normalized; subtraction and ranges stay intact.
    text = re.sub(r'(?<=\d)[-\u2011](?=(?:basis|percentage)[-\s\u2011]+points?\b)', ' ', text, flags=re.I)
    text = re.sub(r'\b(basis|percentage)[-\u2011](points?)\b', r'\1 \2', text, flags=re.I)
    text = without_navigation(re.sub(r'https?://[^\s)]+', '', text))
    text = DATE_EN.sub(lambda m: f"{m['year']}年{MONTH_ALIASES[m['month'].lower()]}月{int(m['day'])}日", text)
    def month(match):
        return match['prefix'] + str(MONTH_ALIASES[match['month'].lower()]) + '月'
    # Context qualifies ambiguous names (May/March); date/heading year qualifies abbreviations.
    prefix = r'(?P<prefix>\b(?:in|during|late|early|mid|of|through|from|by|on|since|until|after|before)\s+)'
    text = re.sub(prefix+r'(?P<month>'+MONTH_PATTERN+r')\.?(?![A-Za-z])', month, text, flags=re.I)
    return re.sub(r'(?P<prefix>\b)(?P<month>'+MONTH_PATTERN+r')\.?(?=\s+\d)', month, text, flags=re.I)


def verified_time_anchors(original, output, source=None):
    """A comparison view, never a draft edit or blanket year whitelist.

    Ignore only an adjacent parenthetical year/month that resolves an existing
    relative-time phrase against the saved publication date. Freestanding dates,
    other years/months and additions without an original relative phrase remain
    ordinary numeric facts requiring review.
    """
    try:
        published = datetime.fromisoformat((source or {})['published_at'].replace('Z', '+00:00'))
    except (KeyError, TypeError, ValueError, AttributeError):
        return output, []
    groups = (
        (r'\bthis\s+year\b|今年', r'今年|\bthis\s+year\b', 'year'),
        (r'\b(?:now|currently|this\s+month)\b|如今|眼下|现在|目前|本月|这个月',
         r'如今|眼下|现在|目前|本月|这个月|\b(?:now|currently|this\s+month)\b', 'month'),
    )
    view = output
    observations = []
    for source_pattern, target_pattern, precision in groups:
        available = len(re.findall(source_pattern, original, re.I))
        if not available:
            continue
        pattern = re.compile(r'(?P<relative>'+target_pattern+r')\s*[（(]\s*'
            r'(?P<year>20\d{2})\s*年?(?:\s*(?P<month>\d{1,2})\s*月)?\s*[）)]', re.I)
        used = 0
        def replace(match):
            nonlocal used
            month = match['month']
            valid = (int(match['year']) == published.year
                     and ((precision == 'year' and month is None)
                          or (precision == 'month' and month and int(month) == published.month)))
            if not valid or used >= available:
                return match.group()
            used += 1
            observations.append({'code':'source_publication_time_anchor','quote':match.group(),
                                 'published_at':source['published_at'],'precision':precision})
            return match['relative']
        view = pattern.sub(replace, view)
    return view, observations


def quantity(value,scale='',unit='',currency=''):
    n=Decimal(value.replace(',',''))*Decimal(SCALES.get((scale or '').lower(),'1'))
    u=(unit or '').lower();c=(currency or '').upper()
    if c in ('$','US$','USD') or u=='美元': dim='USD'
    elif c in ('CNY','RMB','人民币') or u in ('元','人民币'): dim='CNY'
    elif c in ('EUR','€') or u=='欧元': dim='EUR'
    elif u in ('%','％','percent','percentage'):dim='percent'
    elif u in ('bps','基点','个基点','basis point','basis points'):n/=100;dim='percentage_points'
    elif u in ('percentage point','percentage points','个百分点'):dim='percentage_points'
    elif u in ('times','倍','x','×'):dim='multiple'
    else:dim='number'
    return str(n.normalize()),dim


def inventory(text):
    text=normalize(re.sub(r'```[\s\S]*?```','',text))
    text=re.sub(r'\bFY\s*(\d{4})\b',r'\1',text,flags=re.I)
    # Model identifiers such as GLM-5/H800 are entities, not signed quantities.
    text=re.sub(r'(?<![A-Za-z0-9_])[A-Za-z]+[-_]?\d+(?:\.\d+)?(?:[A-Za-z]+)?(?![A-Za-z0-9_])','',text)
    found=[];covered=[]
    for m in RANGE.finditer(text):
        # A dash joining dates/models is still reviewed semantically; values are retained.
        # A comma-grouped absolute value is explicit: 414,000 to 4.4 million
        # is a change/endpoint pair, not 414,000 million. Shared range notation
        # such as 2 to 4 million still inherits the trailing scale.
        own_a = quantity(m['a'], m['sa'], m['ua'], m['ca'])
        own_b = quantity(m['b'], m['sb'], m['ub'], m['cb'])
        # "rose 4.4X to $39.77 billion" joins a multiple to an amount, not
        # a shared-unit range. Never inherit USD/billion onto the multiple.
        explicit_different = (own_a[1] != 'number' and own_b[1] != 'number'
                              and own_a[1] != own_b[1])
        if explicit_different:
            a, b = own_a, own_b
        else:
            a_scale = m['sa'] or ('' if ',' in m['a'] else m['sb'])
            a=quantity(m['a'],a_scale,m['ua'] or m['ub'],m['ca'] or m['cb'])
            b=quantity(m['b'],m['sb'] or m['sa'],m['ub'] or m['ua'],m['cb'] or m['ca'])
        found.extend([a,b]);covered.append(m.span())
    for m in NUMBER.finditer(text):
        if any(a<=m.start()<b or a<m.end()<=b for a,b in covered):continue
        found.append(quantity(m['n'],m['s'],m['u'],m['c']))
    return Counter(found)


def formulas(text):
    # Preserve syntax/operators; comments and whitespace do not change a formula.
    return [re.sub(r'\s+','',re.sub(r'#.*','',block)) for block in re.findall(r'```(?:\w+\n)?([\s\S]*?)```',text)
            if re.search(r'[=+*/]|~=|\^',block)]


def metric_bindings(text,aliases=None):
    aliases=aliases or {}
    if not aliases:return set()
    pattern=re.compile('|'.join((r'\b'+re.escape(k)+r'\b') if k.isascii() else re.escape(k)
                               for k in sorted(aliases,key=len,reverse=True)),re.I)
    out=[]
    for clause in re.split(r'[。；;\n]',text):
        matches=list(pattern.finditer(clause))
        if len(matches)!=1:continue
        metric=aliases[matches[0].group().lower()]
        out.extend((metric,*v) for v in inventory(clause))
    return set(out)


def compare(original,output,metric_aliases=None,source=None):
    output, anchor_observations = verified_time_anchors(original, output, source)
    a,b=inventory(original),inventory(output)
    findings=[];observations=list(anchor_observations)
    novel=[]
    for value,unit in set(b)-set(a):
        # Unspecified source currency/unit requires semantic resolution, not an invented FX conversion.
        compatible=(value,'number') in a or (unit=='number' and any(v==value for v,u in a))
        if compatible:observations.append({'code':'unit_or_notation_resolution','value':value,'output_unit':unit})
        else:novel.append((value,unit))
    if novel:findings.append({'code':'new_numeric_value_or_unit','detail':sorted(novel)})
    if a!=b:observations.append({'code':'numeric_inventory_difference','source':list(a.elements()),'output':list(b.elements())})
    da,db=calendar_dates(original),calendar_dates(output)
    if da!=db:findings.append({'code':'calendar_date_binding','detail':{'source':list(da.elements()),'output':list(db.elements())}})
    fa,fb=formulas(original),formulas(output)
    if any(f not in fa for f in fb):findings.append({'code':'changed_or_new_formula','detail':'Formula operators/operands differ; formatting alone is normalized'})
    if fa!=fb:observations.append({'code':'formula_inventory_difference','source':fa,'output':fb})
    def ratios(text):
        return {(str(Decimal(a)/Decimal(b))) for a,b in re.findall(r'(?<!\d)(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)(?!\d)',text) if Decimal(b)}
    ra,rb=ratios(original),ratios(output)
    if ra!=rb:observations.append({'code':'ratio_or_time_binding_difference','source':sorted(ra),'output':sorted(rb)})
    ma,mb=metric_bindings(original,metric_aliases),metric_bindings(output,metric_aliases)
    if ma and {r[0] for r in ma}=={r[0] for r in mb} and ma!=mb:
        observations.append({'code':'possible_metric_value_swap','source':sorted(ma),'output':sorted(mb)})
    return findings,observations
