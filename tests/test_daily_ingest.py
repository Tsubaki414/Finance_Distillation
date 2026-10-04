import json
import time
import threading
from types import SimpleNamespace
import pytest
from live.adapters.common import make_source
from ml import budget


def source(sid):
    return make_source(id=sid, source_id='sec_edgar', text=sid+' distinct evidence', publisher=sid,
                       title=sid, url='https://example.test/'+sid, published_at='2026-10-04', adapter='edgar')


class FakeExtract:
    def __init__(self): self.seen=[]
    def __call__(self, s):
        self.seen.append(s['id'])
        return [{'unit_id':s['id'], 'source_hash':s['source_hash'], 'statement':s['original_text'],
                 'kind':'fact', 'numbers':[], 'licence_tier':'A', 'usage':'quote', 'speaker':s['publisher']}]


def setup(tmp_path, **kw):
    return dict(store=tmp_path/'store', runs_dir=tmp_path/'runs', inbox=tmp_path/'inbox',
                state_path=tmp_path/'state.json', no_dashboard=True, **kw)


def test_isolation_incremental_schema(tmp_path):
    from live.daily_ingest import run
    client=FakeExtract()
    def fail(): raise ValueError('broken')
    fetchers={'bad':fail, 'slow':lambda: (time.sleep(.15) or {}), 'good':lambda:{'sources':[source('good')]}}
    args=setup(tmp_path, channel_timeout=.02)
    r=run(**args, fetchers=fetchers, extract=client, backup=lambda:None, refresh=lambda:None)
    assert {c['id']:c['status'] for c in r['channels']} == {'bad':'failed','slow':'timeout','good':'ok'}
    assert client.seen==['good']
    assert set(('started_at','finished_at','runtime_s','steps','channels','new_units_by_persona',
                'fresh_by_persona_before','fresh_by_persona_after','cost_usd','failing_channels','deferred')) <= r.keys()
    assert set(r['cost_usd'])=={'relay','jev','total','cap'}
    assert all(set(('id','status','new_items','units','seconds','error'))<=c.keys() for c in r['channels'])
    assert list((tmp_path/'runs').glob('[0-9]'*8+'.json'))
    run(**args, fetchers={'good':fetchers['good']}, extract=client, backup=lambda:None, refresh=lambda:None)
    assert client.seen==['good']
    # Store filtering also works without state.
    (tmp_path/'state.json').unlink()
    run(**args, fetchers={'good':fetchers['good']}, extract=client, backup=lambda:None, refresh=lambda:None)
    assert client.seen==['good']


def test_priority_and_cost(tmp_path):
    from live.daily_ingest import run
    client=FakeExtract()
    fs={sid:lambda sid=sid:{'sources':[dict(source(sid),source_id=sid)]} for sid in ['other','edgar','wallstreetcn','cboe']}
    r=run(**setup(tmp_path),fetchers=fs,extract=client,backup=lambda:None,refresh=lambda:None)
    assert client.seen==['cboe','wallstreetcn','edgar','other']
    def costly(s):
        budget.reserve('gpt-4.1',[],100000,'too-expensive')
        return client(s)
    r=run(**setup(tmp_path/'cost',cost_cap_usd=.01),fetchers=fs,extract=costly,backup=lambda:None,refresh=lambda:None)
    assert len(r['deferred'])==4
    assert all(c['status']=='deferred_cost_cap' for c in r['channels'])


@pytest.mark.parametrize('as_list',[False,True])
def test_inbox(tmp_path,as_list):
    from live.daily_ingest import run
    s=source('inbox'); item={'source':s,'units':FakeExtract()(s)}
    p=tmp_path/'inbox/reportgem/drop.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps([item] if as_list else item))
    run(**setup(tmp_path),fetchers={},extract=FakeExtract(),backup=lambda:None,refresh=lambda:None)
    assert not p.exists() and (p.parent/'processed/drop.json').exists()
    assert (tmp_path/'store/units.jsonl').exists()


def test_backup_and_lock(tmp_path):
    from live.daily_ingest import run
    entered=threading.Event(); release=threading.Event()
    def backup(): entered.set(); release.wait(2)
    args=setup(tmp_path)
    worker=threading.Thread(target=lambda:run(**args,fetchers={},backup=backup,refresh=lambda:None))
    worker.start(); assert entered.wait(1)
    try: assert run(**args,fetchers={},backup=lambda:None)['status']=='locked'
    finally: release.set(); worker.join()
    def broken(): raise RuntimeError('backup failed')
    r=run(**setup(tmp_path/'failure'),fetchers={'good':lambda:pytest.fail('gather before backup')},backup=broken)
    assert r['status']=='backup_failed'
    assert not (tmp_path/'failure/store').exists()
    assert list((tmp_path/'failure/runs').glob('*.json'))


def test_dry_run_and_max_extract(tmp_path):
    from live.daily_ingest import run
    client=FakeExtract()
    fs={'test':lambda:{'sources':[source('a'),source('b')]}}
    r=run(**setup(tmp_path,dry_run=True),fetchers=fs,extract=client,backup=lambda:None)
    assert r['status']=='dry_run' and not client.seen
    assert not (tmp_path/'store').exists() and not (tmp_path/'state.json').exists()
    r=run(**setup(tmp_path,max_extract=1),fetchers=fs,extract=client,backup=lambda:None,refresh=lambda:None)
    assert client.seen==['a'] and r['deferred'][0]['status']=='deferred_max_extract'
    run(**setup(tmp_path),fetchers=fs,extract=client,backup=lambda:None,refresh=lambda:None)
    assert client.seen==['a','b']


def test_jev_cost_deferral(tmp_path):
    from live.daily_ingest import run
    class FakeJev:
        def review(self,state,questions):
            return {'status':'failed','error_code':'budget_exceeded','answers':{}}
    r=run(**setup(tmp_path),fetchers={'test':lambda:{'sources':[source('a'),source('b')]}},
          extract=FakeExtract(),jev=FakeJev(),backup=lambda:None,refresh=lambda:None)
    assert len(r['deferred'])==2
    assert not (tmp_path/'store/units.jsonl').exists()


def test_ledger_reconciliation(tmp_path):
    from live.daily_ingest import run
    client=FakeExtract()
    def paid(s):
        budget.reserve('gpt-4.1',[],100,'relay')
        budget.settle('relay',{'prompt_tokens':100,'completion_tokens':10})
        budget.reserve('typesafe/jev-1.13.0',[],0,'jev')
        budget.settle('jev',{'prompt_tokens':100,'completion_tokens':0})
        return client(s)
    r=run(**setup(tmp_path),fetchers={'test':lambda:{'sources':[source('a')]}},
          extract=paid,backup=lambda:None,refresh=lambda:None)
    assert r['cost_usd']['relay']==pytest.approx(.00028,abs=1e-6)
    assert r['cost_usd']['jev']==pytest.approx(.0000042,abs=1e-6)
    assert r['cost_usd']['total']==pytest.approx(r['cost_usd']['relay']+r['cost_usd']['jev'])


def test_long_sources_are_trimmed_before_extract(tmp_path):
    from live.daily_ingest import run
    seen=[]
    def ex(s):
        seen.append(s)
        return FakeExtract()(s)
    long=make_source(id='long', source_id='sec_edgar', text='\n\n'.join(f'para {i} '+'x'*400 for i in range(80)),
                     publisher='p', title='t', url='https://example.test/long', published_at='2026-10-04', adapter='edgar')
    run(**setup(tmp_path, max_source_chars=3000), fetchers={'c':lambda:{'sources':[long]}}, extract=ex,
        backup=lambda:None, refresh=lambda:None)
    assert len(seen[0]['original_text'])<=3000 and seen[0]['truncated'] is True


def test_round_robin_within_priority_and_per_channel_cap(tmp_path):
    from live.daily_ingest import run
    client=FakeExtract()
    def many(prefix, n): return lambda:{'sources':[dict(source(f'{prefix}{i}'),source_id=prefix) for i in range(n)]}
    fs={'cboe':many('cboe',3), 'cftc':many('cftc',3), 'other':many('other',3)}
    run(**setup(tmp_path, per_channel_max=2), fetchers=fs, extract=client, backup=lambda:None, refresh=lambda:None)
    assert client.seen[:4]==['cboe0','cftc0','cboe1','cftc1']
    assert client.seen[4:]==['other0','other1']


def test_failed_extract_is_not_retried_forever(tmp_path):
    from live.daily_ingest import run
    calls=[]
    def broken(s):
        calls.append(s['id']); raise RuntimeError('incomplete finish_reason')
    args=setup(tmp_path)
    for _ in range(3):
        run(**args, fetchers={'c':lambda:{'sources':[source('bad')]}}, extract=broken, backup=lambda:None, refresh=lambda:None)
    assert calls==['bad','bad']


def test_extract_model_override_needs_explicit_flag(tmp_path, monkeypatch):
    from live import daily_ingest
    monkeypatch.setattr(daily_ingest, '_relay_config', lambda: {'base_url': 'https://api.erisedai.com/v1', 'api_key': 'k',
                        'model': 'claude-opus-5', 'input_usd_per_million': 15.0, 'output_usd_per_million': 75.0})
    with pytest.raises(ValueError, match='allow'):
        daily_ingest.extract_client(tmp_path, model='claude-sonnet-5', allow_nondefault=False)
    c = daily_ingest.extract_client(tmp_path, model='claude-sonnet-5', allow_nondefault=True)
    from live import stage_models
    assert stage_models.for_stage(c.stage_models, 'extract')['model'] == 'claude-sonnet-5'
    assert stage_models.for_stage(c.stage_models, 'compose')['model'] == 'claude-opus-5'
    default = daily_ingest.extract_client(tmp_path/'d')
    assert stage_models.for_stage(default.stage_models, 'extract')['model'] == 'claude-opus-5'


def test_incomplete_output_retries_once_on_a_shorter_source(tmp_path):
    from live.daily_ingest import run
    seen=[]
    long=make_source(id='long', source_id='sec_edgar', text='\n\n'.join(f'para {i} '+'x'*300 for i in range(15)),
                     publisher='p', title='t', url='https://example.test/long2', published_at='2026-10-04', adapter='edgar')
    def ex(s):
        seen.append(len(s['original_text']))
        if len(seen)==1: raise RuntimeError('ContractError: extract: incomplete/unknown finish_reason')
        return FakeExtract()(s)
    r=run(**setup(tmp_path), fetchers={'c':lambda:{'sources':[long]}}, extract=ex, backup=lambda:None, refresh=lambda:None)
    assert len(seen)==2 and seen[1] < seen[0] and r['channels'][0]['units']==1
