"""Boundary checks are heuristic; TEST_DOUBLE outputs are not content acceptance."""
import copy,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from live.source_hygiene import annotate,postcheck,validate_decisions,eligible
from live.distillation_source import source_record
from live.distillation import Pipeline,accounts_from_file,account_profiles
from live.editorial import EditorialPipeline,FIDELITY_CHECKS
from live.localization_feedback import FeedbackStore

ADDRESS='0x'+'a'*40
NOW='2026-09-30T12:00:00+00:00'
def source(text):return source_record({'text':text,'source_language':'en','content_complete':True,'author_name':'Duff','published_at':'2025-01-01T12:00:00+00:00'})

class HygieneCases(unittest.TestCase):
    def test_annotations_preserve_source_and_exact_offsets(self):
        s=source('I hold shares. My returns rose. I worked at a bank. Today, see the chart below. "I think it works."\nContact me: name@example.com\nUse my code SAVE at https://site.test/?ref=abc\n'+ADDRESS)
        before=copy.deepcopy(s);a=annotate(s)
        self.assertEqual(before,s)
        for row in a['annotations']:
            if row['start'] is not None:self.assertEqual(row['quote'],s['original_text'][row['start']:row['end']])
        self.assertTrue({'holdings','personal_performance','employment_history','time_relative','media_reference','quoted_speech','contact_details','cta','referral_link','wallet_or_contract_address'}<={r['kind'] for r in a['annotations']})
    def test_ticker_and_company_revenue_are_not_personal_holdings(self):
        s=source('$NVDA revenue rose. I think this is a useful example.')
        self.assertNotIn('holdings',{r['kind'] for r in annotate(s)['annotations']})
        self.assertNotIn('possible_identity_transfer',{r['code'] for r in postcheck(s,s['original_text'],as_of=NOW)['findings']})
    def test_quotes_keep_speaker_hint(self):
        s=source('Jane said, "I hold shares."')
        a=next(r for r in annotate(s)['annotations'] if r['kind']=='holdings')
        self.assertEqual(a['speaker_hint'],'quoted_speaker_unresolved')
    def test_editor_can_keep_experience_not_blanket_remove(self):
        s=source('I hold shares.');rows=annotate(s)['annotations']
        d=[{'annotation_id':a['id'],'action':'attribute','reason':'The experience supports the conclusion.','attribution':'Duff'} for a in rows]
        self.assertEqual(validate_decisions(d,rows),d)
        self.assertFalse(postcheck(s,'Duff said, "I hold shares."',as_of=NOW)['requires_review'])
        self.assertTrue(postcheck(s,'For my positions, the limit matters.',as_of=NOW)['requires_review'])
    def test_author_elsewhere_does_not_license_ownership(self):
        s=source('I hold shares.');r=postcheck(s,'Duff said markets change. For my positions, the limit matters.',as_of=NOW)
        self.assertIn('possible_identity_transfer',{x['code'] for x in r['findings']})
    def test_wrong_guidance_flagged_separately_from_correct_draft(self):
        r=postcheck(source('I hold shares.'),'Duff said, "I hold shares."','Keep the first-person holdings as the author’s stance.',as_of=NOW)
        self.assertTrue(any(x['location']=='editorial_guidance' for x in r['findings']))
    def test_address_cta_and_media_need_review_without_deletion(self):
        s=source('Example '+ADDRESS);body='Today see the chart below. Use my code SAVE. '+ADDRESS
        result=postcheck(s,body,as_of=NOW)
        self.assertTrue({'naked_address','source_cta','media_or_thread_reference','stale_time_reference'}<={r['code'] for r in result['findings']})
        self.assertNotIn('replacement',result);self.assertEqual(body,'Today see the chart below. Use my code SAVE. '+ADDRESS)
    def test_contextual_address_example_is_not_naked(self):
        r=postcheck(source(ADDRESS),'The contract address in this example is '+ADDRESS,as_of=NOW)
        self.assertNotIn('naked_address',{x['code'] for x in r['findings']})
        self.assertIn('address_context_review',{x['code'] for x in r['findings']})
    def test_stale_times_anchor_without_automatic_redating(self):
        s=source('Today I think growth may slow.')
        self.assertTrue(postcheck(s,'Today growth may slow.',as_of=NOW)['requires_review'])
        self.assertFalse(postcheck(s,'On 2025-01-01, the author wrote: "Today growth may slow."',as_of=NOW)['requires_review'])
    def test_bad_decisions_do_not_silently_remove(self):
        annotations=annotate(source('I hold shares.'))['annotations']
        with self.assertRaises(ValueError):validate_decisions([],annotations)
        with self.assertRaises(ValueError):validate_decisions([{'annotation_id':'fake','action':'remove','reason':'easy'}],annotations)
    def test_five_accounts_and_source_specific_routing(self):
        accounts=accounts_from_file();self.assertEqual(len(accounts),5)
        a=next(r for r in accounts if r['id']=='en_morris_archive')
        self.assertTrue(eligible(a,{'author_handle':'Morris_LT'}))
        self.assertFalse(eligible(a,{'author_handle':'someone_else','original_text':'@Morris_LT said'}))
        self.assertEqual(a['lang'],'en');self.assertIsNone(a['handle'])
        self.assertEqual(len(account_profiles(accounts)),5)
    def test_annotation_decisions_reach_writer_and_risk_holds_output(self):
        calls=[]
        account={'id':'zh_demo','lang':'zh','enabled':True,'source_hygiene':{'enabled':True}}
        def client(stage,messages,max_tokens):
            p=json.loads(messages[1]['content']);calls.append((stage,p))
            values={'routing':{'decision':'MOVE','worth_moving':True,'account_id':'zh_demo','confidence':1,'reason':'TEST'},
              'editorial':{'paragraph_ids':['P1'],'guidance':'','hygiene_decisions':[]},
              'adaptation':{'segments':[{'text':'我持仓并管理自己的组合。','source_paragraph_ids':['P1']}],'needs_source':False,'editor_notes':'TEST','additions':[]},
              'qa':{'checks':dict.fromkeys(FIDELITY_CHECKS,True),'findings':[],'identity_review':[],'calculation_review':[],'numeric_notes':'TEST','editorial_review':'TEST'},
              'identity_qa':{'valid':True,'observations':[],'findings':[]}}
            v=values[stage]
            if stage=='editorial':v['hygiene_decisions']=[{'annotation_id':a['id'],'action':'attribute','reason':'Needed personal example','attribution':'Duff'} for a in p['source']['source_hygiene']['annotations']]
            return {'text':json.dumps(v,ensure_ascii=False),'finish_reason':'stop','model':'TEST_DOUBLE'}
        with tempfile.TemporaryDirectory() as d:
            result=EditorialPipeline(d,[account],client).run(source('I hold shares and manage my own portfolio. The risk limits are important because the portfolio can change over time.'))
        self.assertEqual(result['draft_status'],'needs_review');self.assertEqual(result['text'],'')
        self.assertIn('hygiene_decisions',result)
        self.assertTrue(dict(calls)['adaptation']['source_hygiene_decisions'])
        self.assertTrue(result['hygiene_review']['requires_review'])
    def test_approval_rechecks_edited_text_and_requires_risk_disposition(self):
        with tempfile.TemporaryDirectory() as d:
            store=FeedbackStore(d);s=source('The example matters.')
            a={'source':s,'account_id':'demo','run_id':'r','pipeline_version':'editorial_test','target_language':'en','draft_status':'draft_ready','text':'The example matters.'}
            c=store.register(a,'test.json');body='Send funds to '+ADDRESS
            with self.assertRaises(ValueError):store.review(c['id'],c['draft_version'],body,'approve','TEST')
            report=postcheck(s,body)
            dispositions=[{'finding_id':f['id'],'decision':'accepted_in_context','reason':'TEST ONLY'} for f in report['findings'] if f['level']=='review']
            r=store.review(c['id'],c['draft_version'],body,'approve','TEST',risk_dispositions=dispositions)
            self.assertTrue(r['hygiene_review']['requires_review']);self.assertEqual(r['human_edited_draft'],body)

if __name__=='__main__':unittest.main()
