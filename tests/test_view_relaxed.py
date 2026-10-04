"""Relaxed view contract retains source traceability and numerical fidelity."""
import copy
import json

import pytest

from live import content_units as cu
from live.content_store import ContentStore
from live.distillation import ContractError
from live.view_enrich import has_valid_view


SPANS = [{'paragraph_id': 'P1', 'exact_text': 'Revenue rose 10% as demand improved.'},
         {'paragraph_id': 'P2', 'exact_text': 'Costs fell 5% and margins expanded.'}]


def view(**changes):
    return dict(direction='bullish', subject='stock price', conviction='medium',
                horizon='months', reasoning=['Improved demand supports revenue.'], **changes)


@pytest.mark.parametrize('raw,subject,expected', [
    ('POSITIVE', 'stock price', 'bullish'), ('看涨', 'asset', 'bullish'),
    ('increase', 'revenue', 'higher'), ('下行', 'demand', 'lower'),
    ('BEAR', 'equities', 'bearish'), ('持平', 'demand', 'neutral'),
    ('two-sided', 'demand', 'mixed'), ('unknown', 'demand', 'mixed')])
def test_direction_coercion(raw, subject, expected):
    original = view()
    original.update(direction=raw, subject=subject)
    result = cu.coerce_view(original)
    assert result['direction'] == expected
    assert result['coerced']['direction'] == raw
    assert original['direction'] == raw
    assert cu.coerce_view(result) == result


@pytest.mark.parametrize('field,raw,expected', [
    ('conviction', 'STRONG', 'high'), ('conviction', 'very', 'high'),
    ('conviction', 'moderate', 'medium'), ('conviction', 'tentative', 'low'),
    ('conviction', .1, 'low'), ('conviction', .5, 'medium'),
    ('conviction', .9, 'high'), ('conviction', '0.9', 'high'),
    ('conviction', 'unknown', 'medium'), ('horizon', 'near-term', 'weeks'),
    ('horizon', '1-2 weeks', 'weeks'), ('horizon', 'next quarter', 'quarters'),
    ('horizon', 'this year', 'months'), ('horizon', 'structural', 'years'),
    ('horizon', 'today', 'days'), ('horizon', 'unknown', 'unspecified')])
def test_other_enum_coercion(field, raw, expected):
    proposed = view()
    proposed[field] = raw
    result = cu.validate_view(proposed, SPANS)
    assert result[field] == expected
    assert result['coerced'][field] == raw


def test_paraphrase_normalization_and_support():
    proposed = view()
    proposed['reasoning'] = 'Revenue benefits from improved demand.'
    before = copy.deepcopy(proposed)
    normalized = cu.validate_view(proposed, SPANS)
    assert proposed == before
    assert normalized['reasoning'] == [proposed['reasoning']]
    assert normalized['support'] == [dict(span_index=i, quote=s['exact_text'][:200])
                                     for i, s in enumerate(SPANS)]
    proposed['reasoning'] = ['Revenue ' + 'x' * 400] * 4
    result = cu.validate_view(proposed, SPANS)
    assert len(result['reasoning']) == 3
    assert all(len(r) == 300 for r in result['reasoning'])
    assert has_valid_view(dict(kind='view', view=before, source_spans=SPANS))


def test_cjk_traceability():
    proposed = view()
    proposed['reasoning'] = '需求改善支持增长'
    assert cu.validate_view(proposed, [{'exact_text': '需求增加，收入增长。'}])


@pytest.mark.parametrize('reason,error', [
    ('Revenue could rise 11%.', 'reasoning number not bound to source'),
    ('Revenue could rise 10 billion.', 'reasoning number not bound to source'),
    ('The weather is sunny.', 'reasoning not traceable to spans')])
def test_ungrounded_reasons(reason, error):
    proposed = view()
    proposed['reasoning'] = reason
    with pytest.raises(ContractError, match=error):
        cu.validate_view(proposed, SPANS)


def test_support_limits_grounding_to_cited_spans():
    proposed = view()
    proposed.update(reasoning=['Revenue grew 10%.'],
                    support=[dict(paragraph_id='P1', quote='Revenue rose 10%')])
    assert cu.validate_view(proposed, SPANS)
    proposed['reasoning'] = ['Costs fell 5%.']
    with pytest.raises(ContractError, match='reasoning number not bound to source'):
        cu.validate_view(proposed, SPANS)


@pytest.mark.parametrize('support', [[], [{'span_index': 9, 'quote': 'Revenue'}],
    [{'paragraph_id': 'missing', 'quote': 'Revenue'}],
    [{'span_index': 0, 'quote': 'Invented'}]])
def test_invalid_support(support):
    proposed = view()
    proposed['support'] = support
    with pytest.raises(ContractError):
        cu.validate_view(proposed, SPANS)


def write_store(root, proposed):
    row = dict(unit_id='u1', unit=dict(kind='view', view=proposed, source_spans=SPANS))
    (root / 'units.jsonl').write_text(json.dumps(row) + '\n')


def test_sidecar_precedence(tmp_path):
    write_store(tmp_path, view())
    for name, direction in [('view_enrich', 'bearish'), ('view_normalized', 'neutral')]:
        proposed = view()
        proposed['direction'] = direction
        (tmp_path / (name + '.jsonl')).write_text(json.dumps(dict(unit_id='u1', view=proposed)) + '\n')
    assert ContentStore(tmp_path).units()[0]['unit']['view']['direction'] == 'neutral'
    (tmp_path / 'view_normalized.jsonl').unlink()
    assert ContentStore(tmp_path).units()[0]['unit']['view']['direction'] == 'bearish'


def test_revalidation_reports_rejections_without_rewriting(tmp_path):
    from scripts.revalidate_views import main
    write_store(tmp_path, view())
    proposed = view()
    proposed.update(direction='POSITIVE', reasoning='Revenue improved with demand.')
    bad = dict(unit_id='u2', unit=dict(kind='view', view=dict(proposed, reasoning='Revenue rose 99%.'), source_spans=SPANS))
    with (tmp_path / 'units.jsonl').open('a') as fh:
        fh.write(json.dumps(bad) + '\n')
    original = (tmp_path / 'units.jsonl').read_bytes()
    (tmp_path / 'view_enrich.jsonl').write_text(json.dumps(dict(unit_id='u1', view=proposed)) + '\n')
    out = tmp_path / 'report.json'
    assert main(['--store', str(tmp_path), '--out', str(out), '--write']) == 0
    report = json.loads(out.read_text())
    assert report['valid_before'] == 0
    assert report['valid_after'] == 1
    assert report['coerced'] == 1
    assert report['rejected_with_reasons'][0]['unit_id'] == 'u2'
    assert (tmp_path / 'units.jsonl').read_bytes() == original
    saved = json.loads((tmp_path / 'view_normalized.jsonl').read_text())
    assert saved['unit_id'] == 'u1'
    assert saved['view']['direction'] == 'bullish'


def test_numbers_cannot_hide_after_truncation():
    proposed = view()
    proposed['reasoning'] = ['Revenue ' + 'x' * 310 + ' 999%.']
    with pytest.raises(ContractError, match='reasoning number not bound to source'):
        cu.validate_view(proposed, SPANS)


def test_stance_uses_normalized_input_and_adaptation():
    from live.stance import stance_step
    proposed = view()
    proposed.update(direction='POSITIVE', horizon='near-term', reasoning='Revenue benefits from demand.')
    unit = dict(unit_id='u1', kind='view', view=proposed, source_spans=SPANS)
    persona = {'stance': {'horizon': 'weeks'}}
    seen = []
    revised = dict(proposed, direction='negative', conviction='strong')
    def client(stage, messages, max_tokens):
        seen.append(json.loads(messages[-1]['content']))
        return dict(finish_reason='stop', text=json.dumps(dict(
            decision='adapt', account_view='Revenue faces pressure.', supporting_unit_ids=['u1'],
            rationale='Less optimistic.', confidence=.7, view=revised)))
    result = stance_step(unit, persona, client)
    assert seen[0]['unit']['view']['horizon'] == 'weeks'
    assert seen[0]['unit']['view']['direction'] == 'bullish'
    assert result['view']['direction'] == 'bearish'
    assert result['view']['conviction'] == 'high'
    assert unit['view'] == proposed


def test_revalidation_reports_invalid_enrichment_and_strict_success(tmp_path):
    from scripts.revalidate_views import revalidate_views
    proposed = view()
    proposed['reasoning'] = ['Revenue rose 10%']
    write_store(tmp_path, proposed)
    assert revalidate_views(tmp_path)['valid_before'] == 1
    bad = dict(proposed, reasoning=['Revenue rose 99%'])
    (tmp_path / 'view_enrich.jsonl').write_text(json.dumps(dict(unit_id='u1', view=bad)) + '\n')
    report = revalidate_views(tmp_path)
    assert report['valid_after'] == 0
    assert report['rejection_counts'] == {'view: reasoning number not bound to source': 1}
    assert not (tmp_path / 'view_normalized.jsonl').exists()


def test_normalized_sidecar_supersedes_invalid_enrichment(tmp_path):
    write_store(tmp_path, view())
    bad = dict(view(), reasoning=['Revenue rose 99%'])
    (tmp_path / 'view_enrich.jsonl').write_text(json.dumps(dict(unit_id='u1', view=bad)) + '\n')
    (tmp_path / 'view_normalized.jsonl').write_text(json.dumps(dict(unit_id='u1', view=view())) + '\n')
    assert ContentStore(tmp_path).units()[0]['unit']['view_source'] == 'normalized'


def test_cross_script_paraphrase_is_traceable_but_numbers_stay_bound():
    proposed = view()
    proposed['reasoning'] = 'Production is recovering while new orders soften.'
    spans = [{'exact_text': '9月制造业生产指数上升1.3个百分点至51.7%，新订单指数小幅回落。'}]
    assert cu.validate_view(proposed, spans)
    proposed['reasoning'] = 'Production index rose to 52.9%.'
    with pytest.raises(cu.ContractError, match='number not bound'):
        cu.validate_view(proposed, spans)


def test_conditions_coerced_to_text_or_dropped():
    proposed = view(); proposed['conditions'] = ['if demand holds', 'if margins stay firm']
    assert cu.validate_view(proposed, SPANS)['conditions'] == 'if demand holds; if margins stay firm'
    proposed['conditions'] = None
    assert 'conditions' not in cu.validate_view(proposed, SPANS)


def test_invalid_view_downgrades_unit_instead_of_failing_source():
    text = 'Revenue rose 10% as demand improved.'
    source = {'id': 's', 'source_id': 's', 'source_hash': cu.digest(text) if hasattr(cu, 'digest') else 'h', 'original_text': text}
    from live.content_units import paragraphs
    pid = paragraphs(text)[0]['paragraph_id']
    raw = {'kind': 'view', 'statement': 'Demand drives revenue growth.', 'speaker': 'Analyst', 'speaker_type': 'author',
           'source_spans': [{'paragraph_id': pid, 'exact_text': text}], 'numbers': [], 'freshness_class': 'evergreen',
           'view': dict(view(), reasoning='The weather is sunny.')}
    u = cu._unit(source, raw, 0, {p['paragraph_id']: p for p in paragraphs(text)}, text, 'B', require_view=True)
    assert 'view' not in u and 'traceable' in u['view_error']
