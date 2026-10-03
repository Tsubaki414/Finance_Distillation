"""Draft form check. Factual integrity is not the same as being an article.

The evidence gates passed a draft whose body was twelve lines reading "S09 8 月非农就业增加
16.2 万人": every mandatory fact present, correctly stated, and completely unusable. Slot
constraints solve accuracy and create a new failure mode, so form is checked separately.

This never relaxes an evidence gate. A draft must pass both.
"""
from __future__ import annotations
import re

BLOCKING = 'blocking'
WARNING = 'warning'

SLOT_ID = re.compile(r'\bS\d{2}\b')
# Filler that carries no argument.
EMPTY_MOVE = re.compile(r'需结合[^，。]{0,20}解读|值得注意的是|综上所述|总而言之|不容忽视|'
                        r'具有重要意义|需要进一步观察(?![^，。]{0,12}[，。])')


def check(text, sentences, slots, min_sentences=8, max_bare_ratio=0.15,
          min_interpretation_ratio=0.3):
    """`sentences` are ledger rows; `slots` are the rendered fact strings."""
    f = []
    rendered = [s['rendered'] for s in slots]
    n = len(sentences)

    leaked = SLOT_ID.findall(text or '')
    if leaked:
        f.append({'code': 'slot_id_leaked', 'severity': BLOCKING,
                  'detail': f'slot identifiers appear in the body: {sorted(set(leaked))}'})

    bare = []
    for row in sentences:
        t = (row.get('text') or '').strip()
        stripped = t
        for r in rendered:
            stripped = stripped.replace(r, '')
        stripped = SLOT_ID.sub('', stripped)
        # what remains once the mandated strings are removed
        residue = re.sub(r'[\s，。、；：,.;:]', '', stripped)
        if len(residue) < 8:
            bare.append(row.get('sentence_id'))
    if n and len(bare) / n > max_bare_ratio:
        f.append({'code': 'bare_slot_sentences', 'severity': BLOCKING,
                  'detail': (f'{len(bare)} of {n} sentences are little more than a mandated fact '
                             f'string: {bare}. The draft is a list, not an analysis.')})

    kinds = [row.get('kind') for row in sentences]
    interp = sum(1 for k in kinds if k in ('interpretation', 'condition'))
    if n and interp / n < min_interpretation_ratio:
        f.append({'code': 'insufficient_analysis', 'severity': BLOCKING,
                  'detail': f'only {interp} of {n} sentences interpret or condition; '
                            f'the rest restate facts'})

    if n < min_sentences:
        f.append({'code': 'too_short', 'severity': BLOCKING,
                  'detail': f'{n} sentences, minimum {min_sentences}'})

    empties = [row.get('sentence_id') for row in sentences
               if EMPTY_MOVE.search(row.get('text') or '')]
    if empties:
        f.append({'code': 'empty_move', 'severity': WARNING,
                  'detail': f'sentences carrying no argument: {empties}'})

    # a fact repeated verbatim in two sentences reads as padding
    dupes = []
    for r in rendered:
        hits = [row.get('sentence_id') for row in sentences if r in (row.get('text') or '')]
        if len(hits) > 1:
            dupes.append({'fact_string': r, 'sentences': hits})
    if dupes:
        f.append({'code': 'repeated_fact_string', 'severity': WARNING,
                  'detail': dupes[:4]})

    # Two sentences carrying the same pair of facts are the same sentence written twice. A repair
    # pass produced exactly that, and one restated 上修 and 参与率下降 immediately after the other.
    facts_per_sentence = {}
    for row in sentences:
        t = row.get('text') or ''
        facts_per_sentence[row.get('sentence_id')] = frozenset(r for r in rendered if r in t)
    restated = []
    seen = list(facts_per_sentence.items())
    for i, (sid_a, a) in enumerate(seen):
        for sid_b, b in seen[i + 1:]:
            if len(a & b) >= 2:
                restated.append({'sentences': [sid_a, sid_b], 'shared_facts': sorted(a & b)})
    if restated:
        f.append({'code': 'sentence_restates_another', 'severity': BLOCKING,
                  'detail': (f'sentences carrying the same combination of facts, so one is the '
                             f'other rewritten: {restated[:3]}')})

    typed = [row.get('sentence_id') for row in sentences if row.get('model_written_digits')]
    if typed:
        f.append({'code': 'model_wrote_a_number', 'severity': BLOCKING,
                  'detail': (f'sentences where the model typed a figure instead of using a '
                             f'placeholder: {typed}. Every number must come from the fact slots.')})

    # Thresholds a writer proposes in an invalidation condition are legitimate, but they are not
    # sourced numbers. They are surfaced so nobody downstream reads them as data.
    proposed = [{'sentence_id': row.get('sentence_id'), 'values': row['proposed_thresholds']}
                for row in sentences if row.get('proposed_thresholds')]
    if proposed:
        f.append({'code': 'author_proposed_threshold', 'severity': WARNING,
                  'detail': (f'forward-looking thresholds stated by the writer, not drawn from '
                             f'the fact pack: {proposed}')})

    # A correct figure written without its direction word states the magnitude and drops the sign.
    misframed = [{'sentence_id': row.get('sentence_id'), 'values': row['misframed_values']}
                 for row in sentences if row.get('misframed_values')]
    if misframed:
        f.append({'code': 'direction_word_dropped', 'severity': BLOCKING,
                  'detail': (f'figures written without the direction word the fact requires, so '
                             f'the sign is lost: {misframed}')})

    uncited_fact = [row.get('sentence_id') for row in sentences
                    if row.get('kind') == 'fact' and not row.get('slot_ids')]
    if uncited_fact:
        f.append({'code': 'factual_sentence_without_slot', 'severity': BLOCKING,
                  'detail': (f'sentences stating a fact with no slot behind them: {uncited_fact}. '
                             f'Vague phrasing like "岗位增加量显著" is not a fact.')})

    lengths = [len(row.get('text') or '') for row in sentences]
    metrics = {
        'sentences': n,
        'bare_slot_sentences': len(bare),
        'bare_ratio': round(len(bare) / max(n, 1), 4),
        'interpretation_ratio': round(interp / max(n, 1), 4),
        'mean_sentence_chars': round(sum(lengths) / max(n, 1), 1),
        'sentence_chars_min_max': [min(lengths), max(lengths)] if lengths else [0, 0],
        'repeated_fact_strings': len(dupes),
        'restated_sentences': len(restated),
        'author_proposed_thresholds': sum(len(x['values']) for x in proposed),
        'misframed_values': sum(len(x['values']) for x in misframed),
    }
    blocking = [x for x in f if x['severity'] == BLOCKING]
    return {'findings': f, 'metrics': metrics,
            'form_status': 'failed' if blocking else 'passed',
            'blocking_count': len(blocking),
            'check_version': 'form-v4'}
