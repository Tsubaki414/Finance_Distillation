"""Source trust, warning-only numbers, and offline requalification regressions."""
import json
import pytest
from live import compose, qa_levels, registry, content_units, stance
from tests.test_compose import Fake, GOOD_BODY, SOURCE, run
from tests.test_view_relaxed import view, SPANS

@pytest.mark.parametrize('source', [{'licence_tier':'A'}, {'source_id':'reportgem_goldman'}, {'adapter':'fed_rss'}, {'trust_score':.8}, {'donor_score':.9}, {'source':{'source_id':'oaktree'}}])
def test_trusted(source):
    from live.trust import is_trusted
    assert is_trusted(source)

@pytest.mark.parametrize('source', [{}, {'trust_score':.79}, {'source_id':'reportgemish'}, {'adapter':'unknown'}])
def test_untrusted(source):
    from live.trust import is_trusted
    assert not is_trusted(source)

@pytest.mark.parametrize('code', ['number_not_in_units','period_not_in_units','number_metric_binding','number_words','no_judgment','data_list','no_disagreement','view_number_unbound'])
def test_soft(code):
    assert qa_levels.level({'code':code}, frame_found=True) == 'soft'

def test_unknown_hard():
    assert qa_levels.level({'code':'new'}, frame_found=True) == 'hard'

def test_trusted_compose_skip():
    result = compose.compose_source(dict(SOURCE, trust_score=.9), 'zh_industry', Fake(body=GOOD_BODY+'利润翻倍至99%。'), post_type='data_take')
    assert result['qa']['number_check'] == 'skipped_trusted_source'
    assert not {'number_not_in_units','period_not_in_units','number_metric_binding','number_words'} & {f['code'] for f in result['post_checks']}

def test_untrusted_numbers_warn():
    result, _ = run(Fake(body=GOOD_BODY.replace('69.5%', '72%')), post_type='data_take')
    assert 'number_not_in_units' in result['qa']['soft']
    assert result['draft_status'] == 'draft_ready'

def test_movement_not_contradiction():
    assert not compose.contradiction_findings('Open interest rose by $2.1B in the 24 hours before the release, then fell by $1.5B after it.')
    assert not compose.contradiction_findings('Open interest rose by $2.1B. Open interest fell by $1.5B.')
    assert compose.contradiction_findings('True Market Mean of $73.3K. True Market Mean at $77.2K.')

def test_descriptive_not_advice():
    assert not compose.trade_reco_findings('Each move lined up with a Fed speech or soft data — and the reactions were small and short-lived', 'en')
    assert not compose.trade_reco_findings('Consider the evidence.', 'en')
    assert compose.trade_reco_findings('Consider buying QQQ.', 'en')

def test_trusted_view():
    proposed = view(); proposed['reasoning'] = ['Revenue could rise 99%.']
    assert not content_units.validate_view(proposed, SPANS, source_or_unit={'adapter':'fed'}).get('warnings')

def test_stance_number_warning():
    proposed = view(); revised = dict(proposed, conviction='high', reasoning=['Revenue could rise 99%.'])
    unit = {'unit_id':'u', 'view':proposed, 'source_spans':SPANS, 'numbers':[]}
    response = dict(decision='adapt', account_view='Revenue will rise', supporting_unit_ids=['u'], rationale='Demand', confidence=.9, view=revised)
    result = stance.stance_step(unit, {'stance':{'horizon':'months'}}, lambda *a: {'text':json.dumps(response), 'finish_reason':'stop'})
    assert result['view']['warnings'] == ['reasoning number not bound to source: 99%']
    persona = registry.persona_for_account('zh_industry')
    findings = compose.post_checks('data_take', GOOD_BODY, GOOD_BODY, {}, 'B', [unit], persona, registry.load_post_types(), result)
    assert any(f['code']=='view_number_unbound' and f['level']=='soft' for f in findings)

def test_requalification():
    from scripts.requalify_drafts import requalify
    result, _ = run(Fake(body=GOOD_BODY.replace('69.5%', '72%')), post_type='data_take')
    result['post_checks'] = [{'code':'number_not_in_units','level':'hard'}]
    report = requalify([{'account_id':'zh_industry','drafts':[{'compose':result, 'source':SOURCE}, {'reason':'failed'}]}])
    assert report['hard_before'] == 1 and report['hard_after'] == 0
    assert report['publishable'] == 1 and report['pass_rate'] == .5

@pytest.mark.parametrize('code', ['position_claim','trade_reco_specific','self_contradiction','licence_tier_not_allowed','d_tier_source_leak','quote_not_exact','missing_attribution_frame'])
def test_legal_and_claim_gates_hard(code):
    assert qa_levels.level({'code':code}, frame_found=True) == 'hard'

def test_registry_trust(monkeypatch):
    from live.trust import is_trusted
    monkeypatch.setattr(registry, 'source_licence_tier', lambda sid: 'A' if sid=='official' else None)
    assert is_trusted({'source_id':'official'})

@pytest.mark.parametrize('trusted', [True, False])
def test_all_units_trust_required(trusted):
    from live.trust import trusted_inputs
    assert trusted_inputs(None, [{'trust_score':.9}, {'trust_score':.9 if trusted else .2}]) == trusted
    assert not trusted_inputs(None, [])

def test_trusted_stance_has_no_warning():
    proposed = view(); revised = dict(proposed, conviction='high', reasoning=['Revenue could rise 99%.'])
    unit = {'unit_id':'u', 'view':proposed, 'source_spans':SPANS, 'adapter':'fed'}
    response = dict(decision='adapt', account_view='Revenue will rise', supporting_unit_ids=['u'], rationale='Demand', confidence=.9, view=revised)
    result = stance.stance_step(unit, {'stance':{'horizon':'months'}}, lambda *a: {'text':json.dumps(response), 'finish_reason':'stop'})
    assert not result['view'].get('warnings')

def test_requalification_cli(tmp_path):
    import subprocess
    import sys
    source = tmp_path/'results.json'; out = tmp_path/'out.json'
    source.write_text(json.dumps([{'drafts':[{'reason':'failed'}]}]))
    subprocess.run([sys.executable, 'scripts/requalify_drafts.py', '--results', str(source), '--out', str(out)], check=True, capture_output=True)
    assert json.loads(out.read_text())['pass_rate'] == 0
