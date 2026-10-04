import json
import pytest
from unittest.mock import patch
from live.content_store import ContentStore
from tests.test_content_store import source, unit
from tests.test_validate_e2e import row

@pytest.mark.parametrize('text', ['may not be reproduced', 'This is not investment research',
    'not research', 'may not be copied', 'may not be redistributed', 'may not be forwarded',
    'No part of this document may be reproduced', 'For the exclusive use of Alice'])
def test_detect(text):
    from live.licence_rules import detect_no_reproduction
    assert detect_no_reproduction(text.upper())
    assert not detect_no_reproduction('Public economic statistics')


def test_extract_downgrades_requested_a():
    from live.content_units import extract
    src = source('Payrolls rose 22,000 in September 2026. This may not be reproduced.')
    raw = unit(src)
    raw['source_spans'] = [{'paragraph_id': 'P1', 'exact_text': src['original_text']}]
    def client(*args):
        return {'finish_reason': 'stop', 'text': json.dumps({'units': [raw]})}
    result = extract(src, client, licence_tier='A')['units'][0]
    assert (result['licence_tier'], result['usage'], result['quote_allowed'], result['no_reproduction']) == ('B', 'paraphrase', False, True)
    assert result['attribution_required'] is True
    src = source()
    src['source_id'] = 'reportgem_jpmorgan'
    raw['source_spans'][0]['exact_text'] = src['original_text']
    assert extract(src, client, licence_tier='A')['units'][0]['quote_allowed'] is False


def test_licence_sidecar_and_integrity(tmp_path):
    from scripts.apply_licence_rules import main
    from scripts.validate_e2e import validate_store
    r = row('jpm'); r['source']['source_id'] = 'reportgem_jpmorgan'
    r['unit']['no_reproduction'] = True
    path = tmp_path / 'units.jsonl'; path.write_text(json.dumps(r) + '\n')
    original = path.read_bytes()
    assert validate_store(ContentStore(tmp_path))['global_checks']['no_reproduction_quotable']
    assert main(['--store', str(tmp_path), '--source-ids', 'reportgem_jpmorgan']) == 0
    store = ContentStore(tmp_path)
    assert store.units()[0]['unit']['quote_allowed'] is False
    assert not validate_store(store)['global_checks']['no_reproduction_quotable']
    assert path.read_bytes() == original


def test_compose_refuses_even_exact_restricted_quote():
    from live.compose import post_checks
    from live import registry
    from types import SimpleNamespace
    u = unit(source())
    u['quote_allowed'] = False
    text = '"Payrolls rose 22,000 in September 2026."'
    findings = post_checks('data_take', text, text, None, 'B', [u],
                           SimpleNamespace(lang='en'), registry.load_post_types())
    assert any(f['code'] == 'no_reproduction_quote' and f['level'] == 'hard' for f in findings)


def test_sidecar_does_not_mask_duplicate_damage(tmp_path):
    from scripts.apply_licence_rules import main
    from scripts.validate_e2e import validate_store
    bad = row('duplicate'); bad['licence_tier'] = 'C'
    good = row('duplicate')
    unrelated = row('jpm'); unrelated['source']['source_id'] = 'reportgem_jpmorgan'
    (tmp_path / 'units.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in [bad, good, unrelated]))
    main(['--store', str(tmp_path), '--source-ids', 'reportgem_jpmorgan'])
    checks = validate_store(ContentStore(tmp_path))['global_checks']
    assert checks['non_writable_tiers'] and checks['duplicate_unit_ids']


def test_short_direct_quotes_refused():
    from live.licence_rules import quote_findings
    assert quote_findings('The source said “up”.', [{'quote_allowed': False}])
    assert not quote_findings('The outlook improved.', [{'quote_allowed': False}])


def test_restricted_source_c_request_never_becomes_writable():
    from live.content_units import extract
    src = source('Payrolls rose 22,000 in September 2026. This may not be reproduced.')
    raw = unit(src); raw['source_spans'] = [{'paragraph_id': 'P1', 'exact_text': src['original_text']}]
    def client(*args):
        return {'finish_reason': 'stop', 'text': json.dumps({'units': [raw]})}
    u = extract(src, client, licence_tier='C')['units'][0]
    assert u['licence_tier'] == 'C' and u['usage'] == 'topic_only'


@pytest.mark.parametrize('field,value', [('licence_tier', 'A'), ('usage', 'quote'), ('quote_allowed', True)])
def test_no_reproduction_integrity_each_field(field, value):
    from scripts.validate_e2e import check_row
    r = row('restricted')
    r['licence_tier'] = 'B'
    r['unit'].update(licence_tier='B', usage='paraphrase', no_reproduction=True, quote_allowed=False)
    assert not check_row(r)
    r['unit'][field] = value
    assert any(category == 'no_reproduction_quotable' for category, _ in check_row(r))


def test_no_reproduction_integrity_requires_publisher_even_with_speaker():
    from scripts.validate_e2e import check_row
    r = row('restricted'); r['licence_tier'] = 'B'
    r['unit'].update(licence_tier='B', usage='paraphrase', no_reproduction=True, quote_allowed=False)
    r['attribution'].pop('publisher')
    assert any(category == 'no_reproduction_quotable' for category, _ in check_row(r))


@pytest.mark.parametrize('body', ["The source said 'up'.", 'The source said 『up』.'])
def test_other_quote_marks_refused(body):
    from live.licence_rules import quote_findings
    assert quote_findings(body, [{'quote_allowed': False}])


def test_compose_restricted_c_keeps_licence_gate():
    from live.compose import compose_source
    from live.distillation import ContractError
    u = dict(unit(source(), tier='C'), no_reproduction=True, quote_allowed=False)
    with patch('live.registry.source_licence_tier', return_value='C'), \
         patch('live.content_units.extract', return_value={'units': [u], 'prompt_assembly': {}}):
        with pytest.raises(ContractError, match='not allowed for licence tier'):
            compose_source(source(), 'zh_industry', None, post_type='data_take')
