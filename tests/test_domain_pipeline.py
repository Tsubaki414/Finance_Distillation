"""Architecture/contract coverage with explicit test doubles, not domain quality evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime,timezone
from live.editorial import EditorialPipeline,FIDELITY_CHECKS
from live.distillation import account_profiles,accounts_from_file,ContractError
from live.domain_policy import DomainPolicy,FINANCE,GENERIC
from live.language_support import LanguageSupport
from live.distillation_source import source_record,detect_language
from live.source_recovery import SourceRecovery
from live.analysis_corpus import intake

SOURCE='The method uses a fixed input to test an output before a release. Repeat the test after each change.'
OUTPUT='发布前，先用固定输入测试输出。每次修改后再重复测试。'
ACCOUNT={'id':'tech_readers_zh','lang':'zh','enabled':True,'domain':'ai_tech','fidelity_policy':'generic',
         'platform':'newsletter','audience':'中文开发者','beats':['developer_tools'],'editorial_preferences':{'keep_examples':True},
         'source_preferences':{'prefer':['original methods']}}

class Client:
    def __init__(self):self.calls=[]
    def __call__(self,stage,messages,max_tokens):
        self.calls.append((stage,messages));value={
            'routing':{'decision':'MOVE','worth_moving':True,'account_id':ACCOUNT['id'],'confidence':1,'reason':'Useful method for configured readers'},
            'editorial':{'paragraph_ids':['P1'],'guidance':''},
            'adaptation':{'segments':[{'source_paragraph_ids':['P1'],'text':OUTPUT}],'needs_source':False,'editor_notes':'TEST','additions':[]},
            'qa':{'checks':dict.fromkeys(FIDELITY_CHECKS,True),'findings':[],'identity_review':[],'calculation_review':[],
                  'numeric_notes':'TEST','editorial_review':'TEST, not quality evidence'},
        }[stage]
        return {'text':json.dumps(value,ensure_ascii=False),'finish_reason':'stop','model':'TEST_DOUBLE'}

class DomainCases(unittest.TestCase):
    def test_provider_quota_is_an_external_block_not_a_content_verdict(self):
        from live.writer_backend import ProviderQuotaError
        def no_credit(*args):raise ProviderQuotaError('TEST balance exhausted')
        with tempfile.TemporaryDirectory() as d:
            result=EditorialPipeline(d,[ACCOUNT],no_credit).run({'text':SOURCE,'content_complete':True})
        self.assertEqual(result['external_block'],'provider_quota');self.assertEqual(result['text'],'')
        self.assertEqual(result['stage_calls'],{'routing':1})
    def test_nonfinance_non_x_method_flows_without_ticker_or_persona(self):
        client=Client()
        with tempfile.TemporaryDirectory() as d:
            result=EditorialPipeline(d,[ACCOUNT],client).run({'text':SOURCE,'platform':'community_forum',
                'source_type':'article','content_complete':True})
        self.assertEqual(result['text'],OUTPUT);self.assertEqual(result['account_id'],ACCOUNT['id'])
        self.assertIsNone(result['persona']);self.assertEqual(result['target_language'],'zh')
        self.assertEqual(result['source']['platform'],'community_forum')
        self.assertEqual(result['domain_policy']['id'],'generic')
        routing=json.loads(client.calls[0][1][1]['content'])['eligible_accounts'][0]
        self.assertEqual(routing['domain'],'ai_tech');self.assertEqual(routing['source_preferences'],ACCOUNT['source_preferences'])
        self.assertEqual([stage for stage,_ in client.calls],['routing','editorial','adaptation','qa'])

    def test_finance_compatibility_is_account_specific_not_persona_inference(self):
        profiles=account_profiles(accounts_from_file())
        self.assertEqual(len(profiles),5);self.assertEqual({p['fidelity_policy'] for p in profiles},{'finance'})
        account={**ACCOUNT,'domain':'generic','persona_id':'macro'}
        self.assertEqual(account_profiles([account])[0]['fidelity_policy'],'generic')
        new={'id':'unrelated','lang':'en','enabled':True,'persona_id':'industry'}
        self.assertEqual(account_profiles([new])[0]['domain'],'generic')

    def test_unknown_policy_never_silently_loses_domain_checks(self):
        account={**ACCOUNT};account.pop('fidelity_policy')
        with self.assertRaises(ContractError):account_profiles([account])
        with self.assertRaises(ContractError):account_profiles([{**ACCOUNT,'fidelity_policy':'finanec'}])

    def test_policy_version_invalidates_replay_and_reaches_review_only_as_constraints(self):
        with tempfile.TemporaryDirectory() as d:
            client=Client();account={**ACCOUNT,'fidelity_policy':'test_policy'}
            first=DomainPolicy('test_policy','1','PRIVATE POLICY: preserve release scope.')
            pipe=EditorialPipeline(Path(d)/'a',[account],client,domain_policies=[first])
            result=pipe.run({'text':SOURCE,'content_complete':True})
            other=EditorialPipeline(Path(d)/'b',[account],client,domain_policies=[DomainPolicy('test_policy','2',first.review_guidance)])
            self.assertNotEqual(pipe.key(result['source']),other.key(result['source']))
            self.assertTrue(any(first.review_guidance in messages[0]['content'] for stage,messages in client.calls if stage=='qa'))
            self.assertNotIn('PRIVATE POLICY',result['text'])

    def test_finance_numbers_and_ownership_remain_enforced(self):
        self.assertTrue(FINANCE.numeric('25 basis points','25%')[0])
        self.assertTrue(FINANCE.numeric('12亿元','12亿美元')[0])
        self.assertFalse(FINANCE.numeric('1800到1900亿美元','$180-190B')[0])
        notes=FINANCE.numeric('Revenue 10%; profit 5%.','Revenue 5%; profit 10%.')[1]
        self.assertIn('possible_metric_value_swap',[f['code'] for f in notes])
        flags=FINANCE.deterministic({'author_name':'Source'},[{'paragraph_id':'P1','exact_text':'I manage my fund.'}],
             [{'text':'我管理自己的基金。'}],'zh','adaptation',detector=detect_language)
        self.assertIn('author_identity',[f['code'] for f in flags])

    def test_generic_numeric_fidelity_survives_without_finance_metric_taxonomy(self):
        self.assertTrue(GENERIC.numeric('This experiment took 12 seconds.','实验耗时20秒。')[0])
        self.assertTrue(GENERIC.numeric('```x=a/b```','```x=a*b```')[0])

    def test_domain_extension_cannot_disable_generic_checks(self):
        policy=DomainPolicy('test','1',extra_checks=lambda *args,**kwargs:[])
        flags=policy.deterministic({},[{'paragraph_id':'P1','exact_text':'The experiment took 12 seconds.'}],
                                  [{'text':'The experiment took 20 seconds.'}],'zh','adaptation',detector=detect_language)
        self.assertTrue({'wrong_or_uncertain_language','new_numeric_value_or_unit'}<={f['code'] for f in flags})

    def test_declaring_a_new_language_does_not_enable_it(self):
        with self.assertRaises(ContractError):account_profiles([{**ACCOUNT,'lang':'fr'}])
        self.assertEqual(source_record({'text':'Bonjour.','source_language':'fr'})['source_language'],'unknown')

    def test_language_capability_can_be_injected_without_a_pipeline_fork(self):
        capabilities=LanguageSupport(frozenset({'fr','zh'}),lambda t:('zh',1) if t==OUTPUT else ('fr',1),'TEST_ONLY_NOT_SHIPPED')
        with tempfile.TemporaryDirectory() as d:
            result=EditorialPipeline(d,[ACCOUNT],Client(),languages=capabilities).run({'text':'Une méthode de test.','content_complete':True})
        self.assertEqual(result['text'],OUTPUT)
        self.assertEqual(result['source']['language_method'],'TEST_ONLY_NOT_SHIPPED')

    def test_platform_neutral_subscribed_intake_without_handle(self):
        rows=[{'source_id':'community_a','platform':'forum','text':SOURCE,'published_at':'2026-09-29T12:00:00Z'},
              {'source_id':'unsubscribed','text':SOURCE,'published_at':'2026-09-29T12:00:00Z'}]
        selected=intake(rows,now=datetime(2026,9,29,13,tzinfo=timezone.utc),source_ids={'community_a'})
        self.assertEqual(selected,[rows[0]])

    def test_recovery_uses_adapter_capability_not_platform_name(self):
        calls=[]
        def fetch(url):
            calls.append(url);return {'url':url,'content_type':'text/html','fetched_at':'TEST',
                                     'raw':'<article><p>'+SOURCE+'</p></article>'}
        with tempfile.TemporaryDirectory() as d:
            recovery=SourceRecovery(d,['example.org'],fetcher=fetch)
            row={'platform':'community_forum','source_type':'unknown','text':'Teaser','url':'https://example.org/article','content_complete':False}
            unknown=recovery.recover(row);self.assertFalse(unknown['content_complete']);self.assertEqual(calls,[])
            recovered=recovery.recover({**row,'body_recovery':'public_html'})
            self.assertTrue(recovered['content_complete']);self.assertEqual(recovered['original_text'],SOURCE)

if __name__=='__main__':unittest.main()
