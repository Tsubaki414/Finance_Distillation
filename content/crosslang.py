"""Chinese to English. Step 7 of the content delivery plan.

Not a translation pass. The claims, the figures, the units and the hedging have to survive intact,
while an overseas reader gets the context a Chinese reader did not need.

The scale conversion is the whole risk here. 16.2 万人 and 162,000 are the same fact in two
notations, and asking a model to move between them is asking for the exact magnitude error the
slot mechanism exists to prevent. So English has its own deterministic renderer: the model never
sees a figure it has to convert, and every number in the English prose must match an English slot
string exactly, direction word included.

Each sentence declares what it is — a claim carried over, a phrasing adapted for the audience, or
background added for it — and background is not allowed to carry a figure.

Run: .venv/bin/python -B content/crosslang.py [--persona=macro]
"""
from pathlib import Path
import sys, json, re, datetime, hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'evidence_loop'))
from model_client import parse_json
from qa.gates import evaluate, parse_numbers, close, converted
from qa.status import classify
from content.fact_slots import build_slots, COMPANION
from content.generate_slotted import local_call
from evergreen.output_gate import assert_exportable

OUT = ROOT / 'content/crosslang'
TOKENS = 3000
MAX_ATTEMPTS = 4


# ------------------------------------------------------------------ English rendering

def en_persons(v):
    return f'{abs(v):,.0f}'


def en_percent(v):
    return f'{v:g} percent'


def en_pp(v):
    n = abs(v)
    return f'{n:g} percentage point' + ('' if n == 1 else 's')


def en_hours(v):
    n = abs(v)
    return f'{n:g} hour' + ('' if n == 1 else 's')


def en_usd(v):
    return f'{round(v * 100):g} cents' if abs(v) < 1 else f'${v:g}'


EN_FORMAT = {
    'persons': en_persons, 'persons_decline': en_persons,
    'percent': en_percent, 'percent_of_unemployed': en_percent,
    'percentage': en_pp, 'percentage_points': en_pp, 'percentage_points_decline': en_pp,
    'hours': en_hours, 'USD': en_usd,
}

# The direction lives in the frame, exactly as it does in Chinese, so a magnitude can never
# arrive without its sign.
EN_FRAME = {
    'payroll': 'nonfarm payrolls rose by {v} in August',
    'payroll_12m_mean': 'the average monthly gain over the prior 12 months was {v}',
    'unemployment_rate': 'the unemployment rate was {v}',
    'participation': 'the labor force participation rate was {v}',
    'participation_since_jan': 'the participation rate is down {v} since January',
    'part_time_decline': 'the number working part time for economic reasons fell by {v}',
    'ahe_mom': 'average hourly earnings rose {v} on the month',
    'ahe_yoy': 'average hourly earnings rose {v} from a year earlier',
    'revision_total': 'the prior two months were revised up by a combined {v}',
    'food': 'food services and drinking places added {v}',
    'health': 'health care added {v}',
    'information': 'information employment fell by {v}',
    'local_education': 'local government education added {v}',
    'workweek_change': 'the average private workweek changed by {v}',
}

EN_DIRECTION = re.compile(r'\b(rose|fell|added|revised up|revised down|down|up)\b')


def en_value(fact):
    fn = EN_FORMAT.get(fact.get('unit') or '', lambda v: f'{v:g}')
    return fn(fact['value'])


def en_slots(packet, required_ids):
    facts = {f['id']: f for f in packet['facts']}
    ids = list(required_ids)
    for level, change in COMPANION.items():
        if level in ids and change in facts and change not in ids:
            ids.insert(ids.index(level) + 1, change)
    out = []
    for fid in ids:
        fx = facts.get(fid)
        if not fx:
            continue
        v = en_value(fx)
        frame = EN_FRAME.get(fid, '{label} was {v}').replace('{label}', fx['label'])
        rendered = frame.format(v=v)
        m = EN_DIRECTION.search(rendered)
        out.append({'slot_id': 'E' + str(len(out) + 1).zfill(2), 'fact_id': fid,
                    'rendered': rendered, 'value_rendered': v,
                    'direction_word': m.group(1) if m else None,
                    'raw_value': fx['value'], 'unit': fx['unit'], 'period': fx['period'],
                    'source_block_ids': fx['source_block_ids']})
    return out


# Thousands separators are part of the number; a trailing comma is punctuation. Writing
# `[\d,]*` swallowed the comma in "health care adding 13,000, demonstrating" and rejected a
# correctly written figure over it.
EN_NUM = re.compile(r'[-+]?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*'
                    r'(?:percentage points?|percent|%|cents?|hours?)?', re.I)
EN_DURATION = re.compile(r'\d+\s*(?:months?|quarters?|weeks?|days?|years?|sessions?)', re.I)
EN_CALENDAR = re.compile(r'\b(?:20\d{2})\b|\bQ[1-4]\b')
# `[^.!?]*` treated the decimal point as a sentence end, so the clause stopped inside "4.1
# percent" and the leftover ".1 percent" was reported as a figure nobody wrote.
EN_THRESHOLD = re.compile(r'(?:if|unless|should|falls? below|rises? above|would be wrong|'
                          r'invalidat\w+|no longer holds)(?:[^.!?]|\.(?=\d))*', re.I)

# What matters is that a figure keeps its sign, not that a particular verb was used. English
# carries direction in nouns and participles too — "a gain of 162,000", "adding 59,000" — and
# demanding the frame's exact verb rejected correct prose.
UP_WORDS = re.compile(r'\b(?:rose|rise|rising|risen|gain|gains|gained|add|adds|added|adding|'
                      r'up|upward|increase[sd]?|increasing|higher|grew|grow(?:th|ing)?|'
                      r'revised up)\b', re.I)
DOWN_WORDS = re.compile(r'\b(?:fell|fall|falls|falling|fallen|declin\w+|drop|drops|dropped|'
                        r'down|downward|decreas\w+|lower|fewer|loss|losses|shed|'
                        r'contract\w+|revised down)\b', re.I)


def direction_class(word):
    if not word:
        return None
    return 'up' if UP_WORDS.fullmatch(word.strip()) else (
        'down' if DOWN_WORDS.fullmatch(word.strip()) else None)


def audit_en(text, slots, allow_threshold=True):
    """Every figure in the English prose must be one of the English slot values, exactly."""
    allowed = {s['value_rendered'].replace(' ', '').lower(): s for s in slots}
    body = text or ''
    scoped = EN_THRESHOLD.sub('', body) if allow_threshold else body

    def scan(s):
        stripped = EN_CALENDAR.sub('', EN_DURATION.sub('', s))
        used, other = [], []
        for m in EN_NUM.finditer(stripped):
            tok = m.group(0).strip().replace(' ', '').lower()
            if not re.search(r'\d', tok):
                continue
            slot = allowed.get(tok)
            if slot is None:
                other.append(m.group(0).strip())
                continue
            cls = direction_class(slot.get('direction_word'))
            if cls:
                # English puts the direction on either side: "payrolls rose by 162,000" and
                # "the 162,000 increase in payrolls" are both signed. Looking only backwards
                # rejected the second.
                window = (stripped[max(0, m.start() - 40):m.start()]
                          + ' | ' + stripped[m.end():m.end() + 40])
                pat = UP_WORDS if cls == 'up' else DOWN_WORDS
                if not pat.search(window):
                    other.append(m.group(0).strip()
                                 + f' (no {cls} word beside it; the sign is lost)')
                    continue
            used.append(slot['slot_id'])
        return used, other

    used, invented = scan(body)
    _, outside = scan(scoped)
    proposed = [x for x in invented if x not in outside]
    return sorted(set(used)), outside, proposed


# ------------------------------------------------------------------ alignment

KIND_OK = {'carried_claim', 'adapted_for_audience', 'added_background'}

# Named entities the background introduces have to come from the release. The first English
# version explained that 'food services and drinking places' maps to a BLS category called
# 'Restaurants and Hotels' and that the Chinese piece used a different classification. Neither is
# true, and no rule about figures would have caught it, because it contains no figures.
QUOTED = re.compile(r"[\u2018\u2019'\"\u201c\u201d]([^\u2018\u2019'\"\u201c\u201d]{3,60})"
                    r"[\u2018\u2019'\"\u201c\u201d]")
PROPER = re.compile(r'\b(?:[A-Z][a-z]{2,}(?:\s+(?:of|and|the)?\s*[A-Z][a-z]{2,})+|[A-Z]{3,})\b')
# Words a sentence may capitalise for grammar, not because they name something.
NOT_AN_ENTITY = {'For', 'The', 'This', 'That', 'These', 'Those', 'It', 'In', 'On', 'At', 'As',
                 'But', 'And', 'While', 'When', 'Chinese', 'English', 'US', 'U.S.'}


ARTICLE = re.compile(r'^(?:The|A|An)\s+')
ATTRIBUTED = re.compile(r'\b(?:the release|the report|the BLS|BLS)\b[^.]{0,40}'
                        r'\b(?:notes?|states?|cautions?|warns?|says?|reminds?|specifies)\b'
                        r'|\baccording to the (?:release|report|BLS)\b'
                        r'|\bas the (?:release|report) (?:notes?|puts it)\b', re.I)


def background_entities(text):
    """Names the sentence introduces. A leading article is grammar, not part of the name —
    keeping it made "The Bureau of Labor Statistics" miss "U.S. Bureau of Labor Statistics" in
    the release and reported a grounded term as ungrounded."""
    out = set()
    for m in QUOTED.finditer(text or ''):
        out.add(m.group(1).strip())
    for m in PROPER.finditer(text or ''):
        term = ARTICLE.sub('', m.group(0).strip()).strip()
        if not term or (len(term.split()) == 1 and term in NOT_AN_ENTITY):
            continue
        out.add(term)
    return {x for x in out if x not in NOT_AN_ENTITY}


def _flat(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def check_background_grounding(rows, packet):
    """Background is context about the release, so the release has to contain what it names.

    Grounding alone is not enough: handed the release's methodology notes, the model pasted all
    four back verbatim as its own "background". But the fix is not a ban on reproducing them —
    that put the model between two rules, since paraphrasing the notes introduces names the
    release never spells out. A caveat is the release's, and repeating it is correct as long as
    it is attributed rather than passed off as our own analysis.
    """
    source = (packet.get('full_narrative') or '') + ' ' + ' '.join(packet.get('methodology') or [])
    hay = re.sub(r'\s+', ' ', source).lower()
    notes = [_flat(m) for m in (packet.get('methodology') or [])]
    f = []
    for r in rows:
        if r['kind_en'] != 'added_background':
            continue
        flat = _flat(r['text'])
        if any(flat == n or (len(n) > 30 and n in flat) for n in notes):
            if not ATTRIBUTED.search(r['text']):
                f.append({'code': 'source_caveat_unattributed', 'severity': 'blocking',
                          'detail': (f"{r['sentence_id']} reproduces one of the release's own "
                                     f"methodology notes without saying so; attribute it to the "
                                     f"release rather than presenting it as your own context")})
            continue
        ungrounded = sorted(e for e in background_entities(r['text'])
                            if re.sub(r'\s+', ' ', e).lower() not in hay)
        if ungrounded:
            f.append({'code': 'background_not_in_the_release', 'severity': 'blocking',
                      'detail': (f"{r['sentence_id']} names {ungrounded}, which does not appear in "
                                 f"the release; background explains the source, it does not draw "
                                 f"on outside knowledge")})
    return f


def alignment(zh_draft, rows, slots, packet):
    """Fact-by-fact and claim-by-claim, so "nothing was lost" is a measurement."""
    facts = {f['id']: f for f in packet['facts']}
    zh_slots = {s['fact_id']: s for s in build_slots(
        packet, packet['coverage']['required_core_ids'])}
    en_by_fact = {s['fact_id']: s for s in slots}

    zh_facts = {fid for r in zh_draft['sentence_to_source_ledger']
                for fid in (r.get('fact_ids') or [])}
    en_facts = {fid for r in rows for fid in (r.get('fact_ids') or [])}

    table = []
    for fid in sorted(zh_facts | en_facts):
        fx = facts.get(fid)
        table.append({
            'fact_id': fid,
            'raw_value': fx['value'] if fx else None,
            'unit': fx['unit'] if fx else None,
            'zh': zh_slots[fid]['rendered'] if fid in zh_slots else None,
            'en': en_by_fact[fid]['rendered'] if fid in en_by_fact else None,
            'in_zh': fid in zh_facts, 'in_en': fid in en_facts,
            'notation_differs_value_does_not': (
                fid in zh_slots and fid in en_by_fact
                and zh_slots[fid]['raw_value'] == en_by_fact[fid]['raw_value']),
        })
    dropped = sorted(zh_facts - en_facts)
    added = sorted(en_facts - zh_facts)

    kinds = {}
    for r in rows:
        kinds[r['kind_en']] = kinds.get(r['kind_en'], 0) + 1
    return {'facts': table, 'dropped_in_english': dropped, 'added_in_english': added,
            'zh_fact_count': len(zh_facts), 'en_fact_count': len(en_facts),
            'sentence_kinds': kinds,
            'method': ('facts are compared by id and raw value, not by string; the two notations '
                       'are expected to differ and the underlying values are not')}


def check_crosslang(rows, slots, packet):
    f = []
    for r in rows:
        if r['kind_en'] not in KIND_OK:
            f.append({'code': 'unknown_sentence_kind', 'severity': 'blocking',
                      'detail': f"{r['sentence_id']}: {r['kind_en']}"})
        if r.get('kind') == 'condition' and r['kind_en'] == 'added_background':
            f.append({'code': 'condition_mislabelled_as_background', 'severity': 'blocking',
                      'detail': (f"{r['sentence_id']} is the invalidation condition, which is "
                                 f"carried over from the Chinese piece, not context added here")})
        elif r['kind_en'] == 'added_background' and (r['slot_ids'] or r['model_written_numbers']):
            f.append({'code': 'background_carries_a_figure', 'severity': 'blocking',
                      'detail': (f"{r['sentence_id']} is labelled added background but states a "
                                 f"figure; background is context, not new evidence")})
        if r['model_written_numbers']:
            f.append({'code': 'model_wrote_a_number', 'severity': 'blocking',
                      'detail': f"{r['sentence_id']}: {r['model_written_numbers']}"})
    f += check_background_grounding(rows, packet)
    if not any(r['kind_en'] == 'added_background' for r in rows):
        f.append({'code': 'no_background_added', 'severity': 'blocking',
                  'detail': ('an overseas reader needs context a Chinese reader did not; a piece '
                             'with none is a translation, which is not what this is')})
    blocking = [x for x in f if x['severity'] == 'blocking']
    return {'findings': f, 'status': 'failed' if blocking else 'passed',
            'blocking_count': len(blocking), 'check_version': 'crosslang-v1'}


FAULT = {
    'model_wrote_a_number': 'A figure was rejected. Either it is not in the table — every number '
                            'must match the table exactly, apart from a threshold in the '
                            'invalidation clause — or it was written without a direction word '
                            'beside it, which loses the sign. "162,000" needs "rose", "increase", '
                            '"added" or similar next to it.',
    'background_carries_a_figure': 'A sentence marked added_background stated a figure. Background '
                                   'gives context; it does not introduce evidence.',
    'no_background_added': 'Nothing was marked added_background. Add context an overseas reader '
                           'needs, for example what the survey is or why the revision matters.',
    'unknown_sentence_kind': 'Use only carried_claim, adapted_for_audience or added_background.',
    'source_caveat_unattributed': "A caveat from the release was reproduced as if it were your "
                                  'own context. Repeating it is fine — say whose it is, e.g. '
                                  '"The release notes that ...".',
    'background_not_in_the_release': 'The background named something that is not in the release. '
                                     'Background explains this source to a reader who has not '
                                     'seen it — the survey, the revision policy, what the release '
                                     'does and does not contain — using only what the release '
                                     'itself says. Do not bring in outside knowledge, and do not '
                                     'expand an acronym the release never spells out: it calls '
                                     'them the establishment survey and the household survey.',
    'condition_mislabelled_as_background': 'The invalidation sentence was labelled '
                                           'added_background. It is carried over from the Chinese '
                                           'piece, so label it carried_claim.',
    'unsupported_relation': 'A relation was asserted that the fact pack does not support '
                            '(acceleration, causation, a record, or proof). State co-occurrence, '
                            'or mark it explicitly as your inference.',
    'unsupported_claim': 'A claim was made that no cited fact supports.',
    'numeric_magnitude': 'A figure was written at the wrong magnitude.',
    'percent_vs_percentage_point': 'A percentage point was written as a percent, or the reverse.',
    'must_include_missing': 'Some mandatory facts are missing.',
    'out_of_evidence_assertion': 'A comparison against market expectations was made. The fact '
                                 'pack contains no consensus forecasts.',
    'sign_direction_mismatch': 'A falling series was described as growing, or the reverse.',
    'citation_relation_mismatch': 'A change was asserted while citing only a level.',
    'fact_not_in_parent_draft': 'A fact appeared that the Chinese draft did not establish.',
}


def prompt_for(zh_draft, slots, packet, faults=None):
    zh = '\n'.join(f"  {r['text']}" for r in zh_draft['sentence_to_source_ledger'])
    notes = '\n'.join(f'  - {m}' for m in (packet.get('methodology') or []))
    # Sentences from the release that explain the release. Handing over only the methodology
    # notes, which use the bare acronyms CES and CPS, pushed the model to expand them from its
    # own knowledge into names the release never prints.
    glossary = [m.group(0).strip() for m in re.finditer(
        r'[^.\n]*(?:establishment survey|household survey)[^.\n]*\.',
        packet.get('full_narrative') or '') if len(m.group(0).strip()) > 40][:4]
    gloss = '\n'.join(f'  - {g}' for g in glossary)
    table = '\n'.join(f"  {s['rendered']}" for s in slots)
    fix = ('\nFix from the last attempt:\n' + '\n'.join('  - ' + x for x in faults) + '\n') \
        if faults else ''
    return (
        f"Below is a Chinese analysis of {packet['title']} that has passed fact checking.\n\n"
        f"{zh}\n\n"
        f"Write the English version for an international finance audience. This is not a "
        f"translation: keep every claim, figure, unit and hedge intact, and add the context an "
        f"overseas reader needs that a Chinese reader did not.\n\n"
        f"Hard rule: every number in your text must match this table word for word, including the "
        f"direction word. Do not convert, round or restate a figure any other way:\n{table}\n\n"
        f"Label each sentence:\n"
        f"  carried_claim        — a claim from the Chinese piece, same meaning\n"
        f"  adapted_for_audience — same claim, phrased for a different reader\n"
        f"  added_background     — context added for this audience; **no figures**\n"
        f"Material you may build background from — the release's own notes:\n{notes}\n"
        f"and the release's own description of its two surveys:\n{gloss}\n"
        f"Use these names. The release prints CES and CPS as acronyms and never spells them out, "
        f"so write 'the establishment survey' and 'the household survey'.\n"
        f"At least one sentence must be added_background, and it must be genuinely new context "
        f"for this audience — not the invalidation condition, which is carried over and should be "
        f"labelled carried_claim. Background may only explain this release; anything it names "
        f"must appear in the release itself. Write it in your own words for a reader who has "
        f"not seen the release. You may repeat one of the release's own caveats, but attribute "
        f"it: \"The release notes that ...\".\n"
        f"Avoid claiming acceleration, causation, records or proof; the fact pack supports "
        f"co-occurrence only.\n"
        f"The fact pack has no consensus forecasts, so never compare against expectations.\n"
        f"A threshold you propose in the invalidation sentence is the only figure allowed "
        f"outside the table.\n"
        f"{fix}\n"
        f"Return JSON only: {{\"title\":\"...\",\"sentences\":[{{\"text\":\"...\","
        f"\"kind\":\"fact|interpretation|condition\","
        f"\"kind_en\":\"carried_claim|adapted_for_audience|added_background\","
        f"\"fact_ids\":[]}}]}}")


def build(zh_draft, packet, faults=None):
    slots = en_slots(packet, packet['coverage']['required_core_ids'])
    parent_facts = {fid for r in zh_draft['sentence_to_source_ledger']
                    for fid in (r.get('fact_ids') or [])}
    slots = [s for s in slots if s['fact_id'] in parent_facts]
    allowed = {f['id']: f for f in packet['facts']}

    cid = 'en-' + hashlib.sha256(
        (zh_draft['id'] + datetime.datetime.now().isoformat()).encode()).hexdigest()[:12]
    rec = {'id': cid, 'source_language': 'zh', 'target_language': 'en',
           'zh_draft_id': zh_draft['id'], 'persona_id': zh_draft['persona_id'],
           'persona_name': zh_draft['persona_name'],
           'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'source_id': packet['id'], 'source_version': packet['version'],
           'method': ('English figures are rendered by code from the fact pack; the model never '
                      'converts a scale between the two languages'),
           'en_slots': [{'slot_id': s['slot_id'], 'fact_id': s['fact_id'],
                         'rendered': s['rendered']} for s in slots],
           'run_status': 'running', 'qa_status': 'not_run', 'content_status': 'blocked',
           'attempts': []}

    best, best_score, faults = None, -1e9, faults or []
    for attempt in range(MAX_ATTEMPTS):
        r = local_call(prompt_for(zh_draft, slots, packet, faults), 'crosslang_en', TOKENS,
                       temperature=.2 + .12 * attempt)
        rec['attempts'].append({'attempt': attempt + 1, 'run_id': r['run_id'],
                                'latency_s': r['_latency_s'], 'usage': r['usage']})
        try:
            o = parse_json(r['text'])
            rows = o['sentences']
            for i, row in enumerate(rows):
                text = (row.get('text') or '').strip()
                used, invented, proposed = audit_en(text, slots)
                row['sentence_id'] = 's' + str(i + 1)
                row['text'] = text
                row['kind_en'] = row.get('kind_en') or 'carried_claim'
                row['slot_ids'] = used
                row['model_written_numbers'] = invented
                row['proposed_thresholds'] = proposed
                refs = [x for x in (row.get('fact_ids') or []) if x in allowed]
                for sid in used:
                    s = next(s for s in slots if s['slot_id'] == sid)
                    if s['fact_id'] not in refs:
                        refs.append(s['fact_id'])
                row['fact_ids'] = refs
        except Exception as e:
            rec['attempts'][-1]['error'] = type(e).__name__ + ': ' + str(e)[:200]
            continue

        ledger = [{'sentence_id': r_['sentence_id'], 'text': r_['text'], 'kind': r_.get('kind'),
                   'kind_en': r_['kind_en'], 'fact_ids': r_['fact_ids'],
                   'slot_ids': r_['slot_ids'],
                   'proposed_thresholds': r_['proposed_thresholds'],
                   'source_block_ids': sorted({b for fid in r_['fact_ids']
                                               for b in allowed[fid]['source_block_ids']}),
                   'primary_url': packet['primary_url'],
                   'source_hash': packet['artifact_sha256']} for r_ in rows]
        qa = evaluate({'sentence_to_source_ledger': ledger}, packet, must_include=[])
        outside = sorted({fid for l in ledger for fid in l['fact_ids']} - parent_facts)
        if outside:
            qa['findings'].append({'layer': 5, 'code': 'fact_not_in_parent_draft',
                                   'severity': 'blocking', 'detail': outside})
            qa['status']['blocking_count'] += 1
            qa['status']['qa_status'] = 'failed'
        cl = check_crosslang(rows, slots, packet)
        align = alignment(zh_draft, rows, slots, packet)
        score = (-3 * qa['status']['blocking_count'] - 3 * cl['blocking_count']
                 - 2 * len(align['dropped_in_english']) + len(rows))
        rec['attempts'][-1].update(qa_status=qa['status']['qa_status'],
                                   qa_blocking=qa['status']['blocking_count'],
                                   crosslang_status=cl['status'], score=score,
                                   dropped=len(align['dropped_in_english']),
                                   codes=sorted({x['code'] for x in qa['findings'] + cl['findings']
                                                 if x['severity'] == 'blocking'}))
        seen, faults = set(), []
        for x in qa['findings'] + cl['findings']:
            if x.get('severity') == 'blocking' and x['code'] in FAULT and x['code'] not in seen:
                seen.add(x['code'])
                faults.append(FAULT[x['code']])
        if score > best_score:
            best, best_score = (o, rows, ledger, qa, cl, align), score
            rec['best_attempt'] = attempt + 1
        if (qa['status']['qa_status'] == 'passed' and cl['status'] == 'passed'
                and not align['dropped_in_english']):
            break

    if best is None:
        rec.update(run_status='failed',
                   finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / (cid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return rec

    o, rows, ledger, qa, cl, align = best
    ok = (qa['status']['qa_status'] == 'passed' and cl['status'] == 'passed'
          and not align['dropped_in_english'])
    text = '\n\n'.join(r_['text'] for r_ in rows)

    md = [f"# {o.get('title')}", '']
    for r_ in rows:
        tag = {'carried_claim': '', 'adapted_for_audience': ' _[adapted for this audience]_',
               'added_background': ' _[background added for this audience]_'}[r_['kind_en']]
        md.append(r_['text'] + tag)
        md.append('')
    md += ['---', '',
           f"Chinese original: {zh_draft['id']}. Figures are rendered from the fact pack by code "
           f"in each language, so the notations differ and the values do not.",
           '', '| fact | value | Chinese | English |', '| --- | --- | --- | --- |']
    for row in align['facts']:
        md.append(f"| {row['fact_id']} | {row['raw_value']} | {row['zh'] or '—'} | "
                  f"{row['en'] or '—'} |")
    article = '\n'.join(md)
    assert_exportable(article, f'crosslang {cid}')

    rec.update(title=o.get('title'), text=text, article_markdown=article,
               sentence_to_source_ledger=ledger, qa=qa, crosslang_check=cl, alignment=align,
               run_status='completed', qa_status=qa['status']['qa_status'],
               crosslang_status=cl['status'],
               content_status='ready_for_pipeline' if ok else 'blocked',
               output_gate='passed',
               finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    rec['delivery'] = classify(rec)
    rec['human_review'] = 'none'
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (cid + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    (OUT / (cid + '.md')).write_text(article)
    return rec


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    packet = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
    drafts = {}
    for p in sorted((ROOT / 'content/drafts').glob('*.json')):
        d = json.loads(p.read_text())
        if d.get('content_status') == 'ready_for_pipeline':
            drafts[d['persona_id']] = d
    for pid in ([args['persona']] if args.get('persona') else ['macro']):
        r = build(drafts[pid], packet)
        a = r.get('alignment', {})
        print(json.dumps({'id': r['id'], 'persona': pid, 'run': r['run_status'],
                          'qa': r.get('qa_status'), 'crosslang': r.get('crosslang_status'),
                          'content': r.get('content_status'),
                          'zh_facts': a.get('zh_fact_count'), 'en_facts': a.get('en_fact_count'),
                          'dropped': a.get('dropped_in_english'),
                          'attempts': len(r['attempts'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
