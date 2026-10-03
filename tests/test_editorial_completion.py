"""Permanent failure types plus resource/repair boundaries; not LLM accuracy claims."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from live.numeric_fidelity import inventory, compare
from live.editorial_repair import apply_repairs
from live.distillation import ContractError
from live.background import BackgroundResolver, calculation
from live.source_recovery import SourceRecovery, extract_page
from live.distillation_source import source_record, digest

ROOT=Path(__file__).resolve().parents[1]

class NumericCases(unittest.TestCase):
    def test_ranges_scales_currency_and_points(self):
        for a,b in [('1800到1900亿美元','$180-190B'),('$65-$72 billion','650亿至720亿美元'),
                    ('25 basis points','0.25个百分点'),('4-5%','4%至5%'),('$22.2B','222亿美元')]:
            with self.subTest(a=a):self.assertEqual(inventory(a),inventory(b))
        self.assertTrue(compare('25 basis points','25%')[0])
        self.assertTrue(compare('12亿元','12亿美元')[0])
    def test_formula_layout_but_not_operators(self):
        a='```\n2 * H * L * (d+r) # FLOPs\n```'
        self.assertFalse(compare(a,'```\n2*H*L*(d+r)\n```')[0])
        self.assertIn('changed_or_new_formula',[f['code'] for f in compare(a,a.replace('d+r','d-r'))[0]])
    def test_swapped_bindings_ratios_and_time_are_visible(self):
        from live.domain_policy import FINANCE
        notes=FINANCE.numeric('Revenue 10%; profit 5%.','Revenue 5%; profit 10%.')[1]
        self.assertIn('possible_metric_value_swap',[r['code'] for r in notes])
        self.assertIn('ratio_or_time_binding_difference',[r['code'] for r in compare('Ratio 2:1','Ratio 1:2')[1]])
        self.assertTrue(compare('Fiscal period FY2028','Fiscal period FY2029')[0])
    def test_new_computable_percentage_not_automatically_allowed(self):
        self.assertTrue(compare('Buybacks $200 billion; market value $5 trillion.','Buybacks represent 4%.')[0])
        self.assertFalse(compare('Buybacks represent 4%.','回购占4%。')[0])
    def test_real_kova_shared_range_and_haohong_dates(self):
        self.assertFalse(compare('capex指引1800到1900亿','$180-190B capex guidance')[0])
        self.assertFalse(compare('in August and late September 2024','2024年8月和9月下旬')[0])

class RepairCases(unittest.TestCase):
    def setUp(self):
        self.candidate={'text':'银行将传导降息。\n\n第二段原样保留。','segments':[{'text':'银行将传导降息。'},{'text':'第二段原样保留。'}],
                        'alignment':[{'target_start':0,'target_end':8},{'target_start':10,'target_end':18}]}
        self.findings=[{'finding_id':'F1','repairable':True,'output_quote':'将'}]
    def test_only_flagged_span_changes(self):
        result,log=apply_repairs(self.candidate,self.findings,{'edits':[{'finding_id':'F1','before':'将','after':'可能'}]})
        self.assertEqual(result['text'],'银行可能传导降息。\n\n第二段原样保留。')
        self.assertEqual(self.candidate['segments'][0]['text'],'银行将传导降息。')
        self.assertEqual(len(log),1)
    def test_cannot_regenerate_expand_scope_or_reorder(self):
        for response in [{'text':'rewritten'}, {'edits':[{'finding_id':'F2','before':'将','after':'可能'}]},
                         {'edits':[{'finding_id':'F1','before':'银行将传导降息。','after':'重写'}]},
                         {'edits':[{'finding_id':'F1','before':'将','after':'可能\n\n新总结'}]}]:
            with self.subTest(response=response),self.assertRaises(ContractError):apply_repairs(self.candidate,self.findings,response)
    def test_overlap_and_ambiguous_patch_rejected(self):
        edit={'finding_id':'F1','before':'将','after':'可能'}
        with self.assertRaises(ContractError):apply_repairs(self.candidate,self.findings,{'edits':[edit,edit]})
        self.candidate['segments'][0]['text']='将将'
        with self.assertRaises(ContractError):apply_repairs(self.candidate,self.findings,{'edits':[edit]})

class RecoveryCases(unittest.TestCase):
    def test_unknown_preview_is_redetected_only_after_complete_public_body_recovery(self):
        row = {'id':'preview', 'source_id':'example', 'author_name':'Writer',
               'url':'https://example.org/a', 'published_at':'2026-09-29T12:00:00Z',
               'fetched_at':'2026-09-29T12:05:00Z', 'source_type':'article',
               'original_text':'New report', 'source_language':'unknown', 'content_complete':False}
        frozen = deepcopy(row)
        body = 'The recovered report explains the original evidence and the conditions for its conclusion. '
        document = {'url':row['url'], 'fetched_at':row['fetched_at'], 'content_type':'text/html',
                    'raw':'<article><p>'+body*3+'</p></article>'}
        with tempfile.TemporaryDirectory() as d:
            result = SourceRecovery(d, allowed_hosts={'example.org'}, fetcher=lambda url:document).recover(row)
            normalized = source_record(result)
            self.assertEqual(normalized['source_language'], 'en')
            self.assertEqual(normalized['language_confidence'], .9)
            self.assertNotEqual(source_record(row)['source_version'], normalized['source_version'])
            action = next(a for a in result['recovery']['actions'] if a['kind']=='full_body_language_detection')
            self.assertEqual(action['previous_language'], 'unknown')
            self.assertEqual(action['body_hash'], digest(result['original_text']))
            self.assertEqual(action['method'], normalized['language_method'])
            self.assertEqual(json.loads(Path(action['document_ref']).read_text())['raw'], document['raw'])
        self.assertEqual(row, frozen)
        self.assertEqual(result['id'], row['id'])
        self.assertEqual(result['url'], row['url'])
        self.assertEqual(result['published_at'], row['published_at'])
        self.assertEqual(result['recovery']['original_text_hash'], digest(row['original_text']))

    def test_real_unknown_body_stays_held_without_model_call(self):
        from live.account_source_adaptation import AccountSourcePipeline, _account
        row = {'id':'unknown', 'author_name':'Writer', 'url':'https://example.org/a',
               'original_text':'Preview', 'source_language':'unknown',
               'content_complete':False, 'source_type':'article'}
        document = {'url':row['url'], 'fetched_at':'2026-09-29T12:05:00Z', 'content_type':'text/html',
                    'raw':'<article><p>'+('한국어 본문의 언어를 추측하지 않습니다. '*8)+'</p></article>'}
        with tempfile.TemporaryDirectory() as d:
            result = SourceRecovery(d, allowed_hosts={'example.org'}, fetcher=lambda url:document).recover(row)
            self.assertTrue(result['content_complete'])
            self.assertEqual(source_record(result)['source_language'], 'unknown')
            client = Mock(side_effect=AssertionError('Unknown language must not reach a model'))
            pipeline = AccountSourcePipeline(Path(d)/'pipeline', _account('zh_industry'), client)
            held = pipeline.run(result, replay=False)
            self.assertEqual(held['draft_status'], 'needs_review')
            self.assertEqual(held['why'], 'Unknown or uncertain source language')
            client.assert_not_called()

    def test_known_language_declarations_are_not_overridden_by_recovery(self):
        for language in ('en', 'zh'):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as d:
                row = {'url':'https://example.org/a', 'original_text':'Preview',
                       'source_language':language, 'content_complete':False, 'source_type':'article'}
                document = {'url':row['url'], 'fetched_at':'2026-09-29T12:05:00Z', 'content_type':'text/html',
                            'raw':'<article><p>'+('The report has the evidence for a careful conclusion. '*5)+'</p></article>'}
                result = SourceRecovery(d, allowed_hosts={'example.org'}, fetcher=lambda url:document).recover(row)
                self.assertEqual(result['source_language'], language)
                self.assertNotIn('full_body_language_detection',[a['kind'] for a in result['recovery']['actions']])
                self.assertEqual(source_record(result)['source_language'], 'en' if language=='en' else 'unknown')

    def test_plain_text_is_not_automatically_a_complete_article(self):
        page=extract_page({'url':'https://example.org/a','fetched_at':'now','content_type':'text/plain',
                          'raw':'A long feed summary. '*30})
        self.assertFalse(page['content_complete'])

    def test_cached_recovery_does_not_duplicate_context(self):
        with tempfile.TemporaryDirectory() as d:
            recovery=SourceRecovery(d,posts={'2':{'text':'Other speaker','author':'Other'}})
            source={'text':'The original source stays intact.','source_type':'x','content_complete':True,'quoted_post':'2'}
            once=recovery.recover(source);twice=recovery.recover(once)
            self.assertEqual(once['context_items'],twice['context_items'])
            self.assertEqual(source_record(once)['source_version'],source_record(twice)['source_version'])
    def test_public_body_formula_and_media_preserved(self):
        result=extract_page({'url':'https://example.org/a','fetched_at':'2026-09-29','content_type':'text/html',
            'raw':'<article><p>'+('Detailed original body. '*8)+'</p><pre>x = a / b</pre><img src="/chart.png" alt="chart"></article>'})
        self.assertTrue(result['content_complete']);self.assertIn('```\nx = a / b\n```',result['text'])
        self.assertEqual(result['media'][0]['url'],'https://example.org/chart.png')
    def test_partial_stays_incomplete_and_context_has_own_author(self):
        with tempfile.TemporaryDirectory() as d:
            recovery=SourceRecovery(d,posts={'2':{'text':'Quoted original','author':'Other','url':'https://example.org/2'}})
            source={'text':'Original post','quoted_post':{'post_id':'2'},'reply_to':'3','content_complete':True,'source_type':'x'}
            result=recovery.recover(source)
            self.assertEqual(result['text'],source['text']);self.assertEqual(result['context_items'][0]['author'],'Other')
            self.assertEqual(result['recovery']['unresolved'][0]['kind'],'reply')
            self.assertNotIn('context_items',source)
        page=extract_page({'url':'https://example.org/a','fetched_at':'now','content_type':'text/html','raw':'<article>'+('Teaser. '*20)+' Continue reading for paid subscribers</article>'})
        self.assertFalse(page['content_complete'])
    def test_recovery_keeps_versions_and_no_fetch_when_complete(self):
        calls=[]
        with tempfile.TemporaryDirectory() as d:
            recovery=SourceRecovery(d,allowed_hosts={'example.org'},fetcher=lambda u:calls.append(u))
            row={'text':'The source is complete and has all its own text.','source_type':'x','content_complete':True}
            a=source_record(recovery.recover(row));b=source_record(recovery.recover(row))
            self.assertEqual(a['source_version'],b['source_version']);self.assertEqual(calls,[])
    def test_background_is_requested_and_has_independent_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            b=BackgroundResolver(SourceRecovery(d),[{'id':'bp','url':'https://example.org/glossary','quote':'One basis point is 0.01 percentage points.','document_text':'One basis point is 0.01 percentage points.','fetched_at':'2026-01-01'}])
            source=source_record({'text':'The rate moved 25 basis points.','url':'https://example.org/post'})
            e=b.resolve({'evidence_id':'bp','why_needed':'Explain the unfamiliar unit'},source)
            self.assertEqual(e['role'],'external_background_not_original_author_claim')
            with self.assertRaises(ContractError):b.resolve({'evidence_id':'bp'},source)
    def test_only_explicit_grounded_arithmetic(self):
        s=source_record({'text':'Buybacks $200 billion; market cap $5 trillion.','url':'https://example.org/post'})
        request={'expression':'a / b * 100','why_needed':'Explicit test-only calculation request','operands':{
            'a':{'value':'200000000000','source_quote':'$200 billion'},'b':{'value':'5000000000000','source_quote':'$5 trillion'}}}
        self.assertEqual(calculation(request,s)['result'],'4.00')
        request['operands']['a']['value']='250'
        with self.assertRaises(ContractError):calculation(request,s)

class PermanentCases(unittest.TestCase):
    def test_five_originals_and_failures_are_permanent_separate_from_holdout(self):
        dev=json.loads((ROOT/'tests/fixtures/editorial_real_v2/cases.json').read_text())['cases']
        held=json.loads((ROOT/'benchmarks/editorial_v2/cases.json').read_text())['cases']
        self.assertEqual({c['case'] for c in dev},{'duff','semi','nvidia','haohong','kova'})
        self.assertEqual(len(held),12)
        self.assertFalse({c['source']['url'] for c in dev}&{c['source']['url'] for c in held})
        self.assertIn('which is where the 4%',next(c['original_candidate'] for c in dev if c['case']=='nvidia'))
        self.assertIn('For my own book',next(c['original_candidate'] for c in dev if c['case']=='kova'))

class EvidenceReviewCases(unittest.TestCase):
    def test_semantic_identity_observations_need_exact_quotes(self):
        from live.editorial import EditorialPipeline
        with tempfile.TemporaryDirectory() as d:
            pipe=EditorialPipeline(d,accounts=[{'id':'zh_macro','enabled':True,'lang':'zh'}],client=lambda *a:None)
            source={'original_text':'I manage a fund.','context_items':[]}
            rows=[{'source_quote':'I manage a fund.','output_quote':'作者管理一只基金。','valid':True}]
            self.assertEqual(pipe.validate_review_evidence(rows,source,'作者管理一只基金。',[],'identity'),rows)
            for mutation in ({'source_quote':'I work for a bank.'},{'output_quote':'我们管理基金。'},{'valid':'yes'}):
                with self.subTest(mutation=mutation),self.assertRaises(ContractError):
                    pipe.validate_review_evidence([{**rows[0],**mutation}],source,'作者管理一只基金。',[],'identity')

    def test_rhetorical_first_person_is_not_automatically_a_failure(self):
        from live.editorial import EditorialPipeline
        # This checks delegation/control flow, NOT whether a real model judges
        # this meaning correctly. That requires the blocked live evaluation.
        source={'original_text':'Let us imagine a bank.','context_items':[]}
        with tempfile.TemporaryDirectory() as d:
            pipe=EditorialPipeline(d,accounts=[{'id':'zh_macro','enabled':True,'lang':'zh'}],client=lambda *a:None)
            rows=[{'source_quote':'Let us imagine a bank.','output_quote':'设想一家银行。','valid':True}]
            pipe.validate_review_evidence(rows,source,'设想一家银行。',[],'identity')


class RepairLoopCases(unittest.TestCase):
    def run_pipeline(self,always_fail=False,bad_patch=False):
        from live.editorial import EditorialPipeline,FIDELITY_CHECKS
        calls=[]
        def client(stage,messages,max_tokens):
            calls.append(stage)
            if stage=='routing':v={'decision':'MOVE','worth_moving':True,'account_id':'zh_macro','reason':'TEST','confidence':1}
            elif stage=='editorial':v={'paragraph_ids':['P1'],'guidance':''}
            elif stage=='adaptation':v={'segments':[{'text':'银行将传导降息，信贷需求还没有回升。','source_paragraph_ids':['P1']}],'editor_notes':'TEST','needs_source':False,'additions':[]}
            elif stage=='qa':
                fail=always_fail or calls.count('qa')==1
                v={'checks':dict.fromkeys(FIDELITY_CHECKS,True),'identity_review':[],'calculation_review':[],
                   'findings':[],'numeric_notes':'No numerals','editorial_review':'TEST'}
                if fail:
                    v['checks']['stance_preserved']=False
                    v['findings']=[{'severity':'fidelity','code':'modality','source_quote':'may','output_quote':'将' if calls.count('qa')==1 else '可能','detail':'TEST modality error','repairable':True}]
            elif stage=='repair':
                payload=json.loads(messages[1]['content']);f=payload['findings'][0]
                v={'edits':[{'finding_id':f['finding_id'],'before':f['output_quote'],'after':'可能\n\n新段落' if bad_patch else '可能'}]}
            else:raise AssertionError(stage)
            return {'text':json.dumps(v,ensure_ascii=False),'finish_reason':'stop','model':'TEST_DOUBLE'}
        with tempfile.TemporaryDirectory() as d:
            result=EditorialPipeline(d,accounts=[{'id':'zh_macro','enabled':True,'lang':'zh'}],client=client).run({'text':'The banks may pass the cut through, but credit demand has not recovered.','content_complete':True})
        return result,calls
    def test_single_targeted_round_and_reqa(self):
        result,calls=self.run_pipeline()
        self.assertEqual(result['text'],'银行可能传导降息，信贷需求还没有回升。')
        self.assertEqual(calls,['routing','editorial','adaptation','qa','repair','qa'])
        self.assertEqual(len(result['qa_history']),2)
        self.assertIn('将',result['original_candidate']['text'])
    def test_still_failing_goes_to_human_without_second_writing(self):
        result,calls=self.run_pipeline(always_fail=True)
        self.assertEqual(result['draft_status'],'needs_review');self.assertEqual(result['text'],'')
        self.assertEqual(calls.count('repair'),1);self.assertEqual(calls.count('editorial'),1)
    def test_invalid_repair_never_replaces_original_candidate(self):
        result,calls=self.run_pipeline(bad_patch=True)
        self.assertEqual(result['draft_status'],'blocked');self.assertEqual(result['text'],'')
        self.assertEqual(result['localization']['text'],result['original_candidate']['text'])

if __name__=='__main__':unittest.main()
