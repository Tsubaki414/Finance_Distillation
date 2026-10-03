"""Three restarted monitor cycles using saved sources and real recorded model replies.

This is an explicitly isolated transport replay, not new paid model generation or
a human content review. It runs the real intake/dedup/selection/QA/store/HTTP paths.
Faults are injected and labelled; recorded bodies are never manually rewritten.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from live.account_monitor import Monitor, ACCOUNTS, configuration
from live.account_intelligence import Store, digest
from live.account_sources import SourcePipeline
from live.account_source_adaptation import adapt_source
from live.content_stages import ContentStages
from live.monitor_intake import FetchResult, IntakeFailure
from live.writer_backend import ProviderQuotaError

BASE=ROOT/'runs/content_batch_v2'
DATES=('2026-10-01T00:00:00+00:00','2026-10-02T00:00:00+00:00','2026-10-03T00:00:00+00:00')


def catalog():
    result={}
    for aid in ACCOUNTS:
        data=json.loads((BASE/'source_selection'/aid/'selected_sources.json').read_text())
        for item in data['sources']:
            result[item['selection_id']]=(aid,item)
    return result


class RecordedStages:
    def __init__(self, directory, aid, item, cycle, evidence):
        self.item,self.cycle,self.evidence=item,cycle,evidence
        self.records={}
        for path in (BASE/'calls'/aid/item['selection_id']).rglob('*.json'):
            record=json.loads(path.read_text())
            if record.get('stage') and record.get('status')=='completed':
                self.records[record['stage']]=(path,record)

    def __call__(self, stage, messages, max_tokens):
        key=self.item['selection_id']
        if self.cycle==1 and key=='I05' and stage=='routing':
            self.evidence.append({'fixture':key,'stage':stage,'injected_failure':'provider_quota'})
            raise ProviderQuotaError('REPLAY INJECTED provider quota failure')
        if self.cycle==1 and key=='ZHM02' and stage=='routing':
            self.evidence.append({'fixture':key,'stage':stage,'injected_failure':'invalid_json'})
            return {'text':'{INVALID_JSON','finish_reason':'stop','model':'REPLAY_FAULT'}
        if stage not in self.records:
            raise AssertionError('Missing genuine saved response: '+key+'/'+stage)
        path,record=self.records[stage]
        current=json.loads(messages[1]['content'])
        original=json.loads(record['messages'][1]['content'])
        # Clock/account-history differs across replay cycles. Source meaning,
        # selected original spans, translations and final copy must match.
        for field in ('selected_passages','segments','translation','localized','draft','hygiene_decisions'):
            if field in current and field in original and current[field]!=original[field]:
                raise AssertionError('Recorded stage semantic input mismatch: '+key+'/'+stage+'/'+field)
        if 'source' in current:
            if current['source']['source_hash']!=original['source']['source_hash']:
                raise AssertionError('Source body changed in recorded replay')
        self.evidence.append({'fixture':key,'stage':stage,'original_call':str(path.relative_to(ROOT)),
            'response_hash':digest(record['response']),'new_network_call':False,
            'context_mode':'recorded_response_replay; temporal/account state differs from original call'})
        return copy.deepcopy(record['response'])


class RecordedPoller:
    def __init__(self, cycle):
        self.cycle,self.items=cycle,catalog()

    def fetch(self, account_id, subscription, cursor=None, *, as_of=None, limit=20):
        sid=subscription['source_id']
        if self.cycle==1 and sid=='conks':
            raise IntakeFailure('REPLAY_INJECTED_feed_timeout')
        ids=['M08-1908319280586015216','ZHM02','I01','I05']
        if self.cycle>=2:
            ids+=['M09-1914854284631642134','I03']  # I03 is deliberately old news.
        if self.cycle>=3:
            ids+=['M01-2071809306375389231']       # Saved genuine SKIP decision.
        rows=[]
        for key in ids:
            aid,item=self.items[key]
            if aid==account_id and item['source']['source_id']==sid:
                rows.append(copy.deepcopy(item['source']))
        # Deliberately return overlapping captures after restart to exercise the
        # monitor DB's durable URL/text/thread/event dedup, not an in-memory filter.
        if rows:
            rows.append(copy.deepcopy(rows[0]))
        return FetchResult(rows,{'account_id':account_id,'source_id':sid,'cycle':self.cycle,
                                 'last_seen':max((r['published_at'] for r in rows),default=None)},True,
                           {'adapter':'recorded_capture_replay','new_network_call':False})


def one_cycle(output,cycle):
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from backend import account_intelligence as api
    from backend.content_dashboard import app
    output.mkdir(parents=True,exist_ok=True)
    store=Store(output/'store')
    items=catalog()
    source_index={digest(item['source']['original_text']):(aid,item) for aid,item in items.values()}
    evidence=[]
    def adapter(source,aid,directory,**kwargs):
        expected,item=source_index[source['source_hash']]
        if expected!=aid:
            raise AssertionError('Account/source leakage')
        baseline_path=BASE/'source_selection'/aid/'length_baseline.json'
        baseline=json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
        client=ContentStages(directory,item,baseline,client=RecordedStages(directory,aid,item,cycle,evidence))
        return adapt_source(source,aid,directory,client=client,follow_up_of=kwargs.get('follow_up_of'),
                            account_context=kwargs.get('account_context'))
    config=configuration()
    config.update(max_attempts_per_account_cycle=5,max_drafts_per_account_day=3)
    monitor=Monitor(store,poller=RecordedPoller(cycle),pipeline=SourcePipeline(store,adapter=adapter),config=config)
    monitor.heartbeat()
    # Advance only this isolated subprocess's account clock. Production still
    # rejects future events; no source publication/capture date is rewritten.
    with patch('live.account_intelligence.now',return_value=DATES[cycle-1]), \
         patch('live.account_sources.now',return_value=DATES[cycle-1]):
        report=monitor.run_cycle(as_of=DATES[cycle-1],mode='replay')
    with patch.object(api,'STORE',store),TestClient(app) as client:
        overview=client.get('/api/account-intelligence/overview')
        assert overview.status_code==200
        api_runs={r['id']:r for r in overview.json()['runs']}
        for summary in report['accounts']:
            for candidate_id in summary['dashboard_ids']:
                run_id=candidate_id.removesuffix('-c1')
                assert run_id in api_runs
                assert api_runs[run_id]['account_id']==summary['account_id']
                response=client.get('/api/account-intelligence/runs/'+run_id)
                assert response.status_code==200
                assert any(c['id']==candidate_id and c['text'].strip() for c in response.json()['candidates'])
    report['verification']={'fresh_process':True,'pid':__import__('os').getpid(),
        'dashboard_http':'same real dashboard API, isolated replay Store, no manual import',
        'model_transport':'saved actual API responses + explicitly injected failures',
        'new_paid_calls':0,'human_reviews':len(store.rows('reviews')),'evidence':evidence}
    (output/f'cycle-{cycle}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='verification'},ensure_ascii=False))


def verify(output):
    reports=[json.loads((output/f'cycle-{i}.json').read_text()) for i in (1,2,3)]
    store=Store(output/'store')
    drafts=[(r,c) for r in store.rows('runs') for c in r.get('candidates',[])]
    keys=[(r['account_id'],store.get('sources',r['event']['source_ids'][0])['url']) for r,c in drafts]
    assert len(keys)==len(set(keys)), 'Duplicate drafts'
    assert len({r['verification']['pid'] for r in reports})==3, 'No real process restart'
    assert all(r['verification']['human_reviews']==0 for r in reports)
    expected={1:{'en_morris_archive':1,'zh_macro':0,'zh_industry':1},
              2:{'en_morris_archive':1,'zh_macro':0,'zh_industry':1},
              3:{'en_morris_archive':0,'zh_macro':0,'zh_industry':0}}
    for i,report in enumerate(reports,1):
        for a in report['accounts']:
            assert a['generated']==expected[i][a['account_id']], (i,a)
    assert reports[1]['accounts'][2]['stale_skipped']==1
    assert reports[2]['accounts'][0]['no_post'] is True
    resumed=[r for r in store.rows('runs') if r.get('follow_up_of')]
    assert len(resumed)>=2,'Failures did not retain follow-up identities'
    result={'cycles':3,'process_restarts':2,'drafts':len(drafts),'duplicate_drafts':0,
        'all_dashboard_http_checks_passed':True,'production_data_changed':False,
        'paid_calls':0,'not_claimed':'This replay does not establish live provider uptime or three elapsed operating days.',
        'reports':[{k:v for k,v in r.items() if k!='verification'} for r in reports]}
    (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cycle',type=int,choices=(1,2,3))
    args=parser.parse_args()
    if args.cycle:
        one_cycle(args.output,args.cycle)
    else:
        if args.output.exists():
            parser.error('Use a new output directory; preserve earlier replay evidence')
        for cycle in (1,2,3):
            subprocess.run([sys.executable,'-B',__file__,'--output',str(args.output),'--cycle',str(cycle)],check=True)
        result=verify(args.output)
        print(json.dumps({k:v for k,v in result.items() if k!='reports'},indent=2))


if __name__=='__main__':
    main()
