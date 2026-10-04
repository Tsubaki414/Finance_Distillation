import copy
import json
import pytest
from live import content_units, compose, registry
from live.distillation import ContractError
from tests.test_extract_contract import SOURCE, unit

VIEW = {'direction': 'bullish', 'subject': 'memory', 'conviction': 'medium',
        'reasoning': ['Micron revenue rose'], 'horizon': 'months'}

def test_extract_v2_requires_view_but_legacy_validator_tolerates_absence():
    raw = unit(kind='view')
    raw.pop('view', None)
    assert content_units.validate_units(SOURCE, {'units': [raw]}, 'B')
    fake = lambda *args: {'text': json.dumps({'units': [unit(), raw]}), 'finish_reason': 'stop'}
    result = content_units.extract(SOURCE, fake, licence_tier='B')
    assert result['version'] == 'content-units-extract-v2'
    assert len(result['units']) == 1
    assert 'view' in result['dropped_units'][0]['reason']

@pytest.mark.parametrize('field,value', [('reasoning',[]), ('subject','')])
def test_view_contract(field, value):
    v = dict(VIEW, **{field:value})
    with pytest.raises(ContractError):
        content_units.validate_view(v, [{'exact_text':'Micron revenue rose'}])

def test_stance_contract_and_prefilter():
    from live.stance import stance_step
    p = registry.persona_for_account('en_macro')
    u = {'unit_id':'v', 'kind':'view', 'view':VIEW, 'source_spans':[{'exact_text':'Micron revenue rose'}], 'numbers':[]}
    output = {'decision':'take','account_view':'Memory supply looks tight.', 'supporting_unit_ids':['v'], 'rationale':'Supply discipline.', 'confidence':0.7}
    fake = lambda *a: {'text':json.dumps(output), 'finish_reason':'stop'}
    assert stance_step(u,p,fake)['decision'] == 'take'
    output['decision']='adapt'
    with pytest.raises(ContractError): stance_step(u,p,fake)
    p = copy.copy(p)
    object.__setattr__(p,'raw',dict(p.raw,stance=dict(p.raw['stance'],horizon='days')))
    assert stance_step(dict(u,view=dict(VIEW,horizon='years')),p,lambda *a: pytest.fail('called'))['decision']=='reject'

def test_judgment_choice_and_checks():
    p=registry.persona_for_account('en_macro')
    units=[{'kind':'view','usage':'paraphrase','unit_id':'v','numbers':[]}, {'kind':'fact','usage':'paraphrase','unit_id':'f','numbers':[]}]
    assert compose.choose(units,p,'B',registry.load_post_types()) == 'judgment_take'
    assert compose.judgment_findings('Revenue was 10%. Margin was 20%. Growth was 30%.',None)[0]['code']=='no_judgment'
    assert 'data_list' in {f['code'] for f in compose.judgment_findings('Revenue was 10%. Margin was 20%. Growth was 30%.',None)}
    assert compose.judgment_findings('Memory supply looks tight. Revenue increased.',{'account_view':'Memory supply looks tight.'})==[]

def test_sample_offline(tmp_path):
    from scripts.judgment_sample import run_samples
    source=dict(SOURCE)
    source['units']=[unit(), unit(kind='view',view=VIEW)]
    path=tmp_path/'source.json'; path.write_text(json.dumps(source))
    result=run_samples(tmp_path/'store',['en_macro'],2,tmp_path/'out',source_json=path)
    assert result and result[0]['stance']['decision']=='take'
    assert (tmp_path/'out'/'samples.md').exists()

def test_contrarian_names_quoted_speaker():
    from live import attribution_frame
    frame=attribution_frame.render('contrarian_take',dict(SOURCE,author_name='Reporter'),speaker='Analyst')
    assert 'Analyst' in frame['text']
    assert frame['placement']=='footer'


def test_compose_stance_payload_and_rejection():
    from tests.test_compose import SOURCE as CS, UNITS
    from live.stance import stance_step
    raw=dict(UNITS['units'][2],kind='view',view=dict(VIEW,reasoning=[UNITS['units'][2]['source_spans'][0]['exact_text']]))
    seen={}
    class Fake:
        def __call__(self,stage,messages,max_tokens):
            p=json.loads(messages[-1]['content']); seen[stage]=p
            if stage=='extract': value={'units':[UNITS['units'][0],raw]}
            elif stage=='stance': value={'decision':'take','account_view':'Memory supply looks tight.', 'supporting_unit_ids':[p['unit']['unit_id']], 'rationale':'Supply discipline.', 'confidence':.7}
            else: value={'body':'Memory supply looks tight. Revenue was $54.23 billion.', 'claim_ledger':[{'claim':'Revenue was $54.23 billion','unit_id':p['units'][0]['unit_id'],'span_ref':0}]}
            return {'text':json.dumps(value),'finish_reason':'stop'}
    result=compose.compose_source(CS,'en_industry',Fake(),exemplars=False)
    assert result['post_type']=='judgment_take'
    assert seen['compose']['stance']['account_view']=='Memory supply looks tight.'
    assert any(u['kind']=='fact' and u['numbers'] for u in seen['compose']['units'])
    assert 'no_judgment' not in {f['code'] for f in result['post_checks']}


def test_reasoning_must_be_cited():
    with pytest.raises(ContractError): content_units.validate_view(dict(VIEW,reasoning=['invented reason']),[{'exact_text':'Micron revenue rose'}])

def test_numeric_sentence_boundaries():
    findings=compose.judgment_findings('Revenue was 10. Margin was 20. Growth was 30.',None)
    assert 'data_list' in {f['code'] for f in findings}

@pytest.mark.parametrize('update', [{'decision':'maybe'}, {'confidence':True}, {'supporting_unit_ids':['missing']}, {'account_view':'Looks tight. Demand is fragile.'}])
def test_stance_invalid_response(update):
    from live.stance import stance_step
    u={'kind':'view','unit_id':'v','view':VIEW,'source_spans':[{'exact_text':'Micron revenue rose'}],'numbers':[]}
    value=dict(decision='take',account_view='Supply looks tight.', supporting_unit_ids=['v'], rationale='Supply.',confidence=.7,**{})
    value.update(update)
    with pytest.raises(ContractError):
        stance_step(u,registry.persona_for_account('en_macro'),lambda *a: {'text':json.dumps(value),'finish_reason':'stop'})

def test_adapt_condition_and_reject_skip():
    from live.stance import stance_step
    u={'kind':'view','unit_id':'v','view':VIEW,'source_spans':[{'exact_text':'Micron revenue rose'}],'numbers':[], 'usage':'paraphrase'}
    value=dict(decision='adapt',account_view='Supply looks tight if discipline holds.',supporting_unit_ids=['v'],rationale='Conditional.',confidence=.6,
               view=dict(VIEW,conditions='Supply discipline holds.'))
    fake=lambda *a: {'text':json.dumps(value),'finish_reason':'stop'}
    assert stance_step(u,registry.persona_for_account('en_macro'),fake)['decision']=='adapt'
    value=dict(decision='reject',account_view='',supporting_unit_ids=[],rationale='No conviction.',confidence=.8)
    stance=stance_step(u,registry.persona_for_account('en_macro'),fake)
    fact=dict(u,kind='fact',unit_id='f')
    result=compose.compose_source(SOURCE,'en_macro',lambda *a: pytest.fail('compose called'),
                                  extracted_units=[u,fact],stance_output=stance,exemplars=False)
    assert result['text']=='' and result['status']=='skipped'

def test_contrarian_requires_disagreement():
    from live import attribution_frame
    p=registry.persona_for_account('en_macro');table=registry.load_post_types()
    frame=attribution_frame.render('contrarian_take',SOURCE,speaker='Analyst')
    body='Supply looks tight.'
    checks=compose.post_checks('contrarian_take',body,body+frame['text'],frame,'B',[],p,table)
    assert 'no_disagreement' in {f['code'] for f in checks}
