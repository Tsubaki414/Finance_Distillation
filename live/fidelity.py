"""Deterministic fidelity checks; semantic claims still require bilingual review.

Numbers use exact Decimal values, not a rounding tolerance. Metric binding covers
an explicit small EN/ZH lexicon; the model review handles the remaining semantics.
"""
from collections import Counter
from decimal import Decimal
import re
from live.distillation_source import detect_language
from live.numeric_fidelity import normalize, calendar_dates, without_calendar_dates, verified_time_anchors

VERSION = 'finance-fidelity-v3-compound-units-time-anchors'

NUMBER = re.compile(
    r'(?P<currency>US\$|USD|CNY|RMB|EUR|\$|€|人民币)?\s*'
    r'(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*'
    r'(?P<scale>trillion|billion|million|thousand|bn\b|mn\b|万亿|亿|万)?\s*'
    r'(?P<unit>percentage\s+points?|percent(?:age)?|basis\s+points?|bps\b|USD\b|CNY\b|RMB\b|EUR\b|yuan\b|renminbi\b|个百分点|个?基点|%|％|美元|人民币|欧元|元|times\b|倍|[x×]\b)?', re.I)
SCALES = {'trillion': '1000000000000', 'billion': '1000000000', 'bn': '1000000000',
          'million': '1000000', 'mn': '1000000', 'thousand': '1000',
          '万亿': '1000000000000', '亿': '100000000', '万': '10000'}
METRICS = re.compile(r'operating\s+margin|营业利润率|经营利润率|利润率|\bmargin\b|'
                     r'\brevenues?\b|营收|营业收入|\bprofit\b|利润|'
                     r'renewal\s+rate|续约率|续订率|policy\s+rate|政策利率', re.I)


def metric_name(value):
    value = value.lower()
    if 'margin' in value or '利润率' in value:
        return 'margin'
    if 'revenue' in value or value in ('营收', '营业收入'):
        return 'revenue'
    if 'renewal' in value or value in ('续约率', '续订率'):
        return 'renewal'
    if value in ('profit', '利润'):
        return 'profit'
    return 'policy_rate'


def numbers(text, bind_metric=False):
    # Dates remain numeric facts, but their position relative to 'revenue' is not
    # a revenue/value binding. Translate date order without assigning it a metric.
    text = normalize(without_calendar_dates(text) if bind_metric else text)
    values = []
    metrics = list(METRICS.finditer(text))
    for m in NUMBER.finditer(text):
        value = Decimal(m['value'].replace(',', '')) * Decimal(SCALES.get((m['scale'] or '').lower(), '1'))
        unit = (m['unit'] or '').lower()
        currency = (m['currency'] or '').upper()
        if currency in ('$', 'US$', 'USD') or unit in ('美元', 'usd'):
            unit = 'USD'
        elif currency in ('CNY', 'RMB', '人民币') or unit in ('元', '人民币', 'yuan', 'renminbi', 'cny', 'rmb'):
            unit = 'CNY'
        elif currency in ('EUR', '€') or unit in ('欧元', 'eur'):
            unit = 'EUR'
        elif unit in ('%', '％', 'percent', 'percentage'):
            unit = 'percent'
        elif unit in ('basis point', 'basis points', 'bps', '基点', '个基点'):
            value /= 100
            unit = 'percentage_points'
        elif unit in ('percentage point', 'percentage points', '个百分点'):
            unit = 'percentage_points'
        elif unit in ('times', '倍', 'x', '×'):
            unit = 'multiple'
        else:
            unit = 'number'
        before = [v for v in metrics if v.end() <= m.start('value')]
        metric = metric_name(before[-1].group()) if before else 'unknown'
        values.append((metric, str(value.normalize()), unit) if bind_metric else (str(value.normalize()), unit))
    return Counter(values)


BIO = re.compile(r'\bI\s+(?:run|manage|charge|own|hold|earned|made|tested)|'
                 r'\bmy\s+(?:fund|portfolio|returns|clients|positions)|'
                 r'我(?:自己)?(?:管理|持有|持仓|收取|赚|实测)|我的(?:基金|组合|客户|收益)', re.I)
FIRST_PERSON = re.compile(r'\b(?:I|my|we|our)\b|我(?:们)?', re.I)
PROMO = re.compile(r'link in (?:bio|profile)|use code|join our paid|领取邀请码|扫码加群', re.I)
REFUSAL = re.compile(r'^(?:I (?:cannot|can\x27t|am unable)|Sorry[,，]|抱歉|对不起|无法生成|没有可重组)', re.I)


def segment_language_matches(original, output, target_language, document, detector):
    language, _ = detector(output)
    if language == target_language:
        return True
    # The detector requires >=8 Han. A short, script-unambiguous heading in an
    # otherwise detected Chinese document should not fail solely for being short.
    if language != 'unknown' or target_language != 'zh' or detector(document)[0] != 'zh':
        return False
    return (len(original.strip()) <= 80 and len(output.strip()) <= 80
            and len(re.findall(r'[\u4e00-\u9fff]', output)) >= 2
            and re.fullmatch(r'[\u4e00-\u9fff\d\s年月份—–:：/()（）-]+', output.strip()) is not None)


def deterministic(source, passages, segments, target_language, stage, detector=detect_language):
    findings = []

    def flag(pid, code, detail):
        findings.append({'paragraph_id': pid, 'stage': stage, 'code': code, 'detail': detail})

    for p, segment in zip(passages, segments):
        original, output, pid = p['exact_text'], segment['text'], p['paragraph_id']
        if not segment_language_matches(original, output, target_language, '\n\n'.join(s['text'] for s in segments), detector):
            flag(pid, 'wrong_or_uncertain_language', 'Language not established for target account')
        if REFUSAL.search(output.strip()):
            flag(pid, 'refusal_prose', 'Refusal is not publishable content')
        numeric_output, _ = verified_time_anchors(original, output, source)
        if numbers(original) != numbers(numeric_output):
            flag(pid, 'numeric_inventory', {'source': list(numbers(original).elements()),
                                           'output': list(numbers(numeric_output).elements())})
        if calendar_dates(original) != calendar_dates(numeric_output):
            flag(pid, 'calendar_date_binding', {'source': list(calendar_dates(original).elements()),
                                                 'output': list(calendar_dates(numeric_output).elements())})
        # Only bind when both sides have the same recognizable metric vocabulary.
        # Unknown/general entities and metric aliases are explicitly left to semantic QA.
        orig_bound, out_bound = numbers(original, True), numbers(numeric_output, True)
        orig_known = {t[0] for t in orig_bound if t[0] != 'unknown'}
        out_known = {t[0] for t in out_bound if t[0] != 'unknown'}
        if orig_known and orig_known == out_known and orig_bound != out_bound:
            flag(pid, 'numeric_metric_binding', 'Recognized metric/value/unit bindings differ')
        for entity, translated in source.get('entity_glossary', {}).items():
            if entity in original and translated.casefold() not in output.casefold():
                flag(pid, 'entity_glossary', f'Missing entity: {translated}')
        biography = bool(BIO.search(original))
        if biography and FIRST_PERSON.search(output):
            flag(pid, 'author_identity', 'Source biography still uses account first person')
        author = source.get('author_name') or ''
        if author and author not in original and author.casefold() in output.casefold() and not biography:
            flag(pid, 'added_author_attribution', 'Author metadata was inserted unnecessarily')
        if re.search(r'https?://|(?:^|\n)(?:来源|出处|译自|Source|Translated from)\s*[:：]', output, re.I):
            flag(pid, 'provenance_in_body', 'URL or provenance footer belongs in metadata')
        if PROMO.search(output):
            flag(pid, 'promotion', 'Promotion survives into draft')
    return findings
