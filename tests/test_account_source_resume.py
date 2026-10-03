import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from scripts.resume_account_sources import CompletedResponses, collect_records, provider_client
from live.distillation_source import digest


class ResumeCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.messages=[{'role':'system','content':'Frozen prompt'}, {'role':'user','content':json.dumps({
            'source':{'original_text':'Exact source','snapshot_at':'old-observation','published_at':'2026-01-01'},
            'account_context':{'as_of':'2026-01-02'}})}]
        self.record={'stage':'translation','status':'completed','max_tokens':100,'messages':self.messages,
                     'prompt_hash':digest(self.messages),'model':'claude-opus-5','temperature':0.0,
                     'response':{'text':'{"segments":[]}','finish_reason':'stop'}}
        self.charges=[]
        def client(*args): self.charges.append(args);return {'text':'new response'}
        self.client=CompletedResponses([(Path('original.json'),self.record)],client,Path(self.temp.name)/'replays.jsonl')

    def test_exact_completed_stage_no_new_charge(self):
        out=self.client('translation',self.messages,100)
        self.assertEqual(out['checkpoint_replay'],'original.json')
        self.assertEqual(self.charges,[])
        self.assertFalse(self.client.calls[0]['new_model_call'])

    def test_normalizer_observation_time_only_can_change(self):
        payload=json.loads(self.messages[1]['content']);payload['source']['snapshot_at']='new-observation'
        self.client('translation',[self.messages[0],{'role':'user','content':json.dumps(payload)}],100)
        self.assertEqual(self.charges,[])

    def test_semantic_date_or_text_change_refuses_even_a_new_charge(self):
        for key in ['published_at','original_text']:
            payload=json.loads(self.messages[1]['content']);payload['source'][key]='changed'
            with self.assertRaisesRegex(ValueError,'inputs changed'):
                self.client('translation',[self.messages[0],{'role':'user','content':json.dumps(payload)}],100)
        self.assertEqual(self.charges,[])

    def test_new_stage_uses_real_client(self):
        self.client('translation',self.messages,100)
        self.client('localization',self.messages,100)
        self.assertEqual(len(self.charges),1)

    def test_failed_stage_request_is_also_frozen_and_keeps_large_token_limit(self):
        failed={**self.record,'stage':'localization','status':'failed','max_tokens':28000}
        client=CompletedResponses([(Path('failed.json'),failed)],self.client.client,
                                  Path(self.temp.name)/'retry.jsonl')
        with self.assertRaisesRegex(ValueError,'inputs changed'):
            client('localization',self.messages,14000)
        changed=copy.deepcopy(self.messages);changed[0]['content']='Different prompt'
        with self.assertRaisesRegex(ValueError,'inputs changed'):
            client('localization',changed,28000)
        self.assertEqual(self.charges,[])
        client('localization',self.messages,28000)
        self.assertEqual(self.charges[0][2],28000)

    def test_stale_prompt_hash_refuses_before_client_creation_or_call(self):
        record=copy.deepcopy(self.record);record['messages'][0]['content']='Changed on disk'
        with self.assertRaisesRegex(ValueError,'hash is stale'):
            CompletedResponses([(Path('stale.json'),record)],self.client.client,
                               Path(self.temp.name)/'bad.jsonl')
        self.assertEqual(self.charges,[])

    def test_new_charge_cannot_skip_an_unreplayed_completed_stage(self):
        with self.assertRaisesRegex(ValueError,'Unreplayed'):
            self.client('localization',self.messages,100)
        self.assertEqual(self.charges,[])

    def test_checkpoint_model_temperature_and_ambiguous_completion_fail_closed(self):
        for change in ({'model':'different-model'},{'temperature':0.5}):
            with self.assertRaisesRegex(ValueError,'model/temperature'):
                CompletedResponses([(Path('bad.json'),{**self.record,**change})],None,
                                   Path(self.temp.name)/'bad.jsonl',expected_model='claude-opus-5')
        with self.assertRaisesRegex(ValueError,'Ambiguous cached stage'):
            CompletedResponses([(Path('one.json'),self.record),(Path('two.json'),self.record)],None,
                               Path(self.temp.name)/'bad.jsonl')


class AncestryCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.messages=[{'role':'system','content':'Frozen prompt'},
                       {'role':'user','content':json.dumps({'source':{'original_text':'Exact source','snapshot_at':'old'}})}]
        identity={'pipeline':'account_source','account_id':'zh_macro','inbox_candidate_id':'inbox-a','fixture_id':'F01'}
        self.runs={
            'legacy':{'id':'legacy','pipeline':'account_intelligence'},
            'base':{**identity,'id':'base','follow_up_of':'legacy'},
            'hop1':{**identity,'id':'hop1','follow_up_of':'base'},
            'hop2':{**identity,'id':'hop2','follow_up_of':'hop1'},
        }
        self.store=SimpleNamespace(get=lambda kind,key:self.runs[key])
        self.base_route=self.write('adaptations/base/calls/route.json','routing')
        self.write('adaptations/base/calls/translate-failed.json','translation','failed')
        self.hop1_translation=self.write('continuations/base/calls/translate.json','translation')
        self.write('continuations/base/calls/localize-failed.json','localization','failed',28000)
        self.hop2_localization=self.write('continuations/hop1/calls/localize.json','localization',max_tokens=28000)
        self.write('continuations/hop1/calls/qa-failed.json','qa','failed')
        self.replay('continuations/base/replayed_stages.jsonl',self.base_route)
        self.replay('continuations/hop1/replayed_stages.jsonl',self.base_route,self.hop1_translation)

    def write(self,relative,stage,status='completed',max_tokens=100):
        path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        record={'stage':stage,'status':status,'messages':self.messages,'max_tokens':max_tokens,
                'prompt_hash':digest(self.messages),'model':'claude-opus-5','temperature':0.0}
        if status=='completed':record['response']={'text':'{"value":"'+stage+'"}','finish_reason':'stop'}
        path.write_text(json.dumps(record))
        return path

    def replay(self,relative,*paths):
        target=self.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        rows=[{'kind':'completed_response_replay','new_model_call':False,'original_call':str(p),
               'original_call_hash':digest(json.loads(p.read_text()))} for p in paths]
        target.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')

    def test_multihop_collects_original_and_all_continuation_completions(self):
        chain,records=collect_records(self.store,self.runs['hop2'],self.root,'claude-opus-5')
        self.assertEqual([r['id'] for r in chain],['base','hop1','hop2'])
        self.assertEqual(len(records),6)
        charges=[]
        client=CompletedResponses(records,lambda *args:charges.append(args) or {'text':'new'},
                                  self.root/'new-replays.jsonl','claude-opus-5')
        for stage,tokens in [('routing',100),('translation',100),('localization',28000)]:
            self.assertIn('checkpoint_replay',client(stage,self.messages,tokens))
        client('qa',self.messages,100)
        self.assertEqual(len(charges),1)
        self.assertEqual(charges[0][0],'qa')
        self.assertEqual(client.used,{'routing','translation','localization'})

    def test_modified_ancestral_response_fails_recorded_replay_hash(self):
        record=json.loads(self.base_route.read_text());record['response']['text']='changed response'
        self.base_route.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'replay hash is stale'):
            collect_records(self.store,self.runs['hop2'],self.root,'claude-opus-5')

    def test_continuation_manifest_hash_and_explicit_child_identity_are_checked(self):
        meta=self.root/'continuations/base/continuation.json'
        meta.write_text(json.dumps({'parent_run_id':'base','child_run_id':'wrong-child'}))
        with self.assertRaisesRegex(ValueError,'manifest identity changed'):
            collect_records(self.store,self.runs['hop2'],self.root)
        meta.write_text(json.dumps({'parent_run_id':'base','child_run_id':'hop1',
                                   'checkpoint_records':[{'path':str(self.base_route),'record_hash':'stale'}]}))
        with self.assertRaisesRegex(ValueError,'record hash is stale'):
            collect_records(self.store,self.runs['hop2'],self.root)

    def test_changed_inbox_or_cyclic_ancestry_cannot_borrow_cached_responses(self):
        self.runs['hop1']['inbox_candidate_id']='different-source'
        with self.assertRaisesRegex(ValueError,'identity changed'):
            collect_records(self.store,self.runs['hop2'],self.root)
        self.runs['hop1']['inbox_candidate_id']='inbox-a'
        self.runs['base']['follow_up_of']='hop2'
        with self.assertRaisesRegex(ValueError,'cycle'):
            collect_records(self.store,self.runs['hop2'],self.root)

    def test_apify_factory_is_opt_in_and_default_relay_remains_available(self):
        apify_calls=[]
        fake=SimpleNamespace(ApifyClient=lambda path:apify_calls.append(path) or 'apify-double')
        with patch.dict('sys.modules',{'live.apify_distillation_client':fake}):
            self.assertEqual(provider_client('apify',self.root/'apify'),'apify-double')
        self.assertEqual(apify_calls,[self.root/'apify'])
        with patch('scripts.resume_account_sources.RelayClient',return_value='relay-double') as relay:
            self.assertEqual(provider_client('relay',self.root/'relay'),'relay-double')
            relay.assert_called_once_with(self.root/'relay')


if __name__=='__main__':unittest.main()
