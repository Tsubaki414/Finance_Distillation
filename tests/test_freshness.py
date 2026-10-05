import json
import pytest
from live import freshness as f, compose, draft_qa, qa_levels
from live.content_store import ContentStore

NOW = '2026-10-04'
def row(date='2026-10-02', adapter='cftc', **kw):
    return {'source': {'published_at': date, 'adapter': adapter}, 'unit': {'unit_id': date, 'kind': 'fact', 'usage': 'paraphrase', 'numbers': [{'text': '123', 'metric': 'payrolls', 'period': ''}], 'statement': 'Payrolls rose 123.', **kw}}

@pytest.mark.parametrize('period,expected', [('September 2026','2026-09-30'),('2026-09','2026-09-30'),('Q3 2026','2026-09-30'),('2026-09-29','2026-09-29'),('week ending September 25, 2026','2026-09-25'),('2026年9月','2026-09-30'),('9月','2026-09-30')])
def test_periods(period, expected):
    r = row(); r['unit']['numbers'][0]['period'] = period
    assert f.derive_dates(r)['as_of'] == expected

def test_invalid_future_and_clamp():
    assert f.normalize_date('T00:00:00') is None
    assert f.normalize_date('2099-01-01') is None
    assert 'future_published_at' in f.derive_dates(row('2099-01-01'))['freshness_flags']
    assert 'malformed_published_at' in f.derive_dates(row('T00:00:00'))['freshness_flags']
    r = row('2026-09-01'); r['unit']['numbers'][0]['period'] = 'September 2026'
    assert f.derive_dates(r)['as_of'] <= '2026-09-02'

@pytest.mark.parametrize('adapter,days',[('cftc',1),('cboe',1),('bls_api',3),('fed_rss',3),('edgar',10),('reportgem_daily',10),('newsletter',5)])
def test_shelf(adapter,days):
    assert f.shelf_days(row(adapter=adapter)) == days

def test_evergreen_breaking_thresholds_and_rank():
    assert f.shelf_days(row(kind='mechanism')) is None
    assert f.shelf_days(row(adapter='oaktree',kind='view')) is None
    assert f.shelf_days(row(adapter='oaktree')) == 5
    assert f.shelf_days(row(adapter='edgar',freshness_class='breaking')) == 2
    # market_flow shelf=1 business day; NOW is Sunday 2026-10-04
    for date, expected in [('2026-10-02','fresh'),('2026-10-01','stale'),('2026-09-30','expired'),('2026-09-29','expired'),('2026-09-24','expired')]:
        assert f.status(row(date),NOW)['status'] == expected
    assert f.status(row('bad'),NOW)['status'] == 'unknown'
    assert f.rank([row('2026-09-01'),row()],NOW)[0]['source']['published_at']=='2026-10-02'

def test_sidecar(tmp_path):
    r=row(); r.update(unit_id='u',personas=[])
    (tmp_path/'units.jsonl').write_text(json.dumps(r)+'\n')
    (tmp_path/'freshness.jsonl').write_text(json.dumps({'unit_id':'u','published_at':'2026-10-02','as_of':'2026-09-30','as_of_source':'number_period','date_unknown':False,'freshness_flags':[]})+'\n')
    u=ContentStore(tmp_path).units()[0]['unit']
    assert u['as_of']=='2026-09-30' and u['published_at_norm']=='2026-10-02'

def test_selection():
    old=row('2026-01-01')['unit']; old['published_at']='2026-01-01'
    new=row()['unit']; new['published_at']='2026-10-02'
    assert old not in compose.pick_units('data_take',[old,new],now=NOW)
    assert compose.pick_units('data_take',[old],now=NOW)[0]['historical'] is True
    assert 'historical' not in old

@pytest.mark.parametrize('body', ['Today payrolls are currently 123.', '今天就业人数目前为123。'])
def test_stale_qa(body):
    u=row('2026-09-01')['unit']; u['published_at']='2026-09-01'
    codes={x['code'] for x in draft_qa.stale_time_findings(body,[u],NOW,'en')}
    assert {'stale_time_word','stale_number_as_current'} <= codes
    assert qa_levels.level({'code':'stale_time_word'},frame_found=True)=='soft'

@pytest.mark.parametrize('body,bad',[('Payrolls rose 123 on September 30.',True),('9月30日就业增加123。',True),('On 2026-09-30 payrolls rose 123.',True),('Payrolls rose 123 on September 1.',False),('Payrolls rose 123.',False),('On September 30 something else happened. Payrolls rose 123.',False)])
def test_wrong_date(body,bad):
    u=row('2026-09-01')['unit']; u['published_at']='2026-09-01'
    assert ('wrong_date_fact' in {x['code'] for x in draft_qa.stale_time_findings(body,[u],NOW,'en')}) == bad

def test_other_support_and_fresh_qa():
    a=row('2026-09-01')['unit']; a['published_at']='2026-09-01'
    b=dict(a,published_at='2026-09-30')
    assert not any(x['code']=='wrong_date_fact' for x in draft_qa.stale_time_findings('On September 30 payrolls rose 123.',[a,b],NOW,'en'))
    assert draft_qa.stale_time_findings('Today payrolls are currently 123.',[dict(a,published_at=NOW)],NOW,'en')==[]

def test_backfill_and_report_read_only_and_atomic(tmp_path):
    from scripts.backfill_freshness import backfill
    from scripts.freshness_report import build_report, markdown
    r=row(); r.update(unit_id='u',personas=[])
    raw=json.dumps(r)+'\n'
    (tmp_path/'units.jsonl').write_text(raw)
    (tmp_path/'persona_tags.jsonl').write_text(json.dumps({'unit_id':'u','tags':{'test':{'verdict':'relevant','confidence':.7},'low':{'verdict':'relevant','confidence':.69}}})+'\n')
    assert len(backfill(tmp_path))==1
    assert not (tmp_path/'freshness.jsonl').exists()
    report=build_report(tmp_path,NOW)
    assert report['coverage']['with_as_of_pct']==100
    assert report['age_histogram']['2-3']==1
    assert report['personas']['test']['fresh']==1
    assert report['personas']['test']['starving']
    assert 'low' not in report['personas']
    backfill(tmp_path,write=True)
    backfill(tmp_path,write=True)
    assert len((tmp_path/'freshness.jsonl').read_text().splitlines())==1
    assert (tmp_path/'units.jsonl').read_text()==raw
    assert build_report(tmp_path,NOW)==report
    assert '| test |' in markdown(report)

def test_channel_classification():
    import json
    from pathlib import Path
    channels=json.loads(Path('live/channels.json').read_text())['channels']
    for keyword,days in [('SpotGamma',1),('ECB',3),('ReportGem',10)]:
        matches=[c for c in channels if keyword.casefold() in c['name'].casefold()]
        assert matches
        for c in matches:
            r=row(adapter='channel:feed_fulltext');r['source']['source_id']='channel:'+c['channel_id']
            assert f.shelf_days(r)==days

@pytest.mark.parametrize('body,bad', [('On September 30 the Federal Reserve announced rate cuts.',True),('On September 1 the Federal Reserve announced rate cuts.',False),('On September 30 another event happened.',False)])
def test_event_date_without_number(body,bad):
    u={'kind':'fact','published_at':'2026-09-01','statement':'The Federal Reserve announced rate cuts.','numbers':[]}
    assert ('wrong_date_fact' in {x['code'] for x in draft_qa.stale_time_findings(body,[u],NOW,'en')})==bad

def test_date_digits_do_not_bind_numbers():
    u={'kind':'fact','published_at':'2026-09-01','statement':'Exports increased 30 percent.','numbers':[{'text':'30%'}]}
    assert not any(x['code']=='wrong_date_fact' for x in draft_qa.stale_time_findings('On September 30 another event happened.',[u],NOW,'en'))

def test_compose_historical_payload_and_existing_sidecar_dates():
    from tests.test_compose import Fake, SOURCE
    from live.content_units import validate_units_partial
    from tests.test_compose import UNITS
    units=validate_units_partial(SOURCE,UNITS,'A')[0]
    units=[dict(u,as_of='2026-01-01',as_of_source='number_period',date_unknown=False,freshness_flags=[],published_at_norm='2026-01-02') if u['kind']=='fact' else u for u in units]
    class Capture(Fake):
        def __call__(self,stage,messages,max_tokens):
            if stage=='compose': self.payload=json.loads(messages[-1]['content'])
            return super().__call__(stage,messages,max_tokens)
    client=Capture()
    result=compose.compose_source(SOURCE,'zh_industry',client,post_type='data_take',exemplars=False,extracted_units=units,now=NOW)
    facts=[u for u in client.payload['units'] if u['kind']=='fact']
    assert all(u['historical'] and u['as_of']=='2026-01-01' for u in facts)
    assert all(u['historical'] for u in result['units'] if u['kind']=='fact')
