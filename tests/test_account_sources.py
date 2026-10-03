"""Account-first routing, stop controls and actual-human metric contracts."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from live.account_intelligence import Store, digest
from live.account_sources import admission, ingest, inbox, SourcePipeline, valid_candidate, universes
from live.account_intelligence_pipeline import Pipeline
from backend import account_intelligence as api
from backend.content_dashboard import app


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.kol = {'id': 'fixture-b', 'source_id': 'overshoot', 'url': 'https://theovershoot.co/p/employment-test',
            'author_name': 'Matthew Klein', 'original_text': 'Employment increased by 100,000. The previous month was revised.',
            'source_language': 'en', 'content_complete': True, 'source_type': 'web',
            'published_at': '2026-09-04T12:30:00Z', 'fetched_at': '2026-09-04T13:00:00Z'}
        self.morris = {**self.kol, 'id': 'fixture-m', 'source_id': 'x_Morris_LT', 'source_language': 'zh',
            'author_name': 'Morris_LT', 'author_handle': 'Morris_LT', 'url': 'https://x.com/Morris_LT/status/123',
            'original_text': '先尝试，再观察反馈，再调整方向。重要的是反复检验，而不是等待完美计划。'}
        self.semi = {**self.kol, 'id': 'fixture-s', 'source_id': 'semianalysis', 'author_name': 'SemiAnalysis',
            'url': 'https://newsletter.semianalysis.com/p/test', 'original_text': 'GPU performance depends on memory bandwidth.'}
        self.calls = []

    def adapter(self, source, account_id, output_dir, **kwargs):
        self.calls.append((source, account_id, kwargs))
        return {'status': 'draft_ready', 'draft_status': 'draft_ready', 'final_draft': '就业增加，前月数据修订。',
                'route': {'reason': 'TEST DOUBLE'}, 'selection': {'passages': []}, 'machine_fidelity': {'status': 'pass'}}

    def admitted(self, source=None, account='zh_macro', **kwargs):
        return ingest(self.store, account, source or self.kol, **kwargs)['candidate']

    def run_one(self):
        candidate = self.admitted(batch_id='TEST')
        return SourcePipeline(self.store, adapter=self.adapter).run('zh_macro', candidate['id'])

    def review(self, run, decision='approve', edit_class='unchanged', text=None):
        c = run['candidates'][0]
        return self.store.review(run['id'], c['id'], digest(c['text']), text or c['text'], decision,
            'TEST HUMAN', 'TEST ONLY: actual explicit review',
            {k: 'pass' for k in ('native_language','useful_examples','rhythm_reasoning','account_fit','angle_value')},
            risk_note='TEST verification', edit_class=edit_class, error_types=['unnatural_language'] if text else [])

    def test_macro_kol_only_macro_without_evaluating_other_accounts(self):
        self.assertTrue(admission('zh_macro', self.kol)['admitted'])
        self.assertFalse(admission('zh_industry', self.kol)['admitted'])
        self.assertFalse(admission('en_morris_archive', self.kol)['admitted'])
        self.assertFalse(ingest(self.store, 'zh_industry', self.kol)['admitted'])
        self.assertEqual(self.store.rows('inbox'), [])

    def test_official_release_never_becomes_post_even_when_core_subscribed(self):
        official = {**self.kol, 'source_id': 'primary_bls', 'author_name': 'BLS',
                    'url': 'https://www.bls.gov/news.release/empsit.htm'}
        verdict = admission('zh_macro', official)
        self.assertFalse(verdict['admitted'])
        self.assertIn('context', verdict['reason'])
        self.assertFalse(ingest(self.store, 'zh_macro', official)['admitted'])
        self.assertEqual(self.store.rows('inbox'), [])

    def test_semianalysis_only_industry(self):
        self.assertTrue(admission('zh_industry', self.semi)['admitted'])
        self.assertFalse(admission('zh_macro', self.semi)['admitted'])

    def test_exact_official_capture_reaches_pipeline_as_context_not_verified_evidence(self):
        from live.source_context import ContextStore
        url = 'https://www.bls.gov/news.release/empsit.htm'
        ContextStore(self.store.root).record('zh_macro', 'primary_bls', [{
            'source_id': 'primary_bls', 'url': url, 'original_text': 'Employment increased by 100,000.',
            'content_complete': True, 'published_at': '2026-09-04T12:30:00Z',
            'fetched_at': '2026-09-04T13:00:00Z'}], '2026-09-04T13:00:00Z')
        candidate = self.admitted({**self.kol, 'original_text': self.kol['original_text'] + ' ' + url})
        run = SourcePipeline(self.store, adapter=self.adapter).run('zh_macro', candidate['id'])
        self.assertEqual(len(run['official_source_context']), 1)
        context = self.calls[0][2]['account_context']
        self.assertEqual(context['official_source_context'][0]['url'], url)
        self.assertEqual(context['official_source_context'][0]['verification_status'], 'captured_not_fact_verified')
        self.assertEqual(context.get('current_evidence', []), [])

    def test_legacy_missing_media_is_preserved_as_blocking_annotation(self):
        row={**self.morris,'media_dependencies':['visual content required; not extracted']}
        candidate=ingest(self.store,'en_morris_archive',row)['candidate']
        self.assertEqual(candidate['status'],'needs_source')
        stored=self.store.get('sources',candidate['source_id'])
        self.assertTrue(stored['media_dependencies'][0]['required'])
        run=SourcePipeline(self.store,adapter=self.adapter).run('en_morris_archive',candidate['id'])
        self.assertEqual(run['status'],'wait')
        self.assertEqual(self.calls,[])

    def test_three_active_universes_and_inactive_account_rejected(self):
        self.assertEqual({u['account_id'] for u in universes()}, {'en_morris_archive','zh_macro','zh_industry'})
        with self.assertRaisesRegex(ValueError, 'inactive'):
            admission('en_industry', self.semi)

    def test_x_author_url_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'author'):
            admission('en_morris_archive', {**self.morris,'url':'https://x.com/another/status/123'})

    def test_morris_other_author_and_english_source_rejected(self):
        with self.assertRaises(ValueError):
            admission('en_morris_archive', {**self.morris,'author_handle':'other'})
        self.assertFalse(admission('en_morris_archive', {**self.morris,'source_language':'en'})['admitted'])

    def test_secondary_requires_its_own_topic(self):
        raw = {**self.semi,'source_id':'stratechery','url':'https://stratechery.com/test'}
        self.assertTrue(admission('zh_industry', raw)['admitted'])
        self.assertFalse(admission('zh_industry', {**raw,'original_text':'A travel diary.'})['admitted'])

    def test_account_qualified_material_can_naturally_overlap(self):
        config=universes()
        for u in config:
            if u['account_id']=='zh_industry':
                u['subscriptions'].append(copy.deepcopy(next(s for s in config[1]['subscriptions'] if s['source_id']=='overshoot')))
        with patch('live.account_sources.universes',return_value=config):
            macro=self.admitted()
            industry=self.admitted(account='zh_industry')
            self.assertNotEqual(macro['id'],industry['id'])
            self.assertEqual(len(inbox(self.store,'zh_macro')['candidates']),1)
            self.assertEqual(len(inbox(self.store,'zh_industry')['candidates']),1)

    def test_duplicate_and_newly_complete_context(self):
        first=self.admitted({**self.kol,'published_at':None,'fetched_at':None})
        fixed=self.admitted()
        self.assertNotEqual(first['id'],fixed['id'])
        self.assertEqual(fixed['blocking_gaps'],[])
        count=len(self.store.rows('sources'))
        duplicate=ingest(self.store,'zh_macro',self.kol)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.store.rows('sources')),count)

    def test_changed_title_or_quote_context_reopens_material(self):
        first=self.admitted()
        fixed=self.admitted({**self.kol,'title':'Corrected context','quoted_post':{'text':'Source speaker'}})
        self.assertNotEqual(first['id'],fixed['id'])

    def test_incomplete_source_never_calls_adapter(self):
        candidate=self.admitted({**self.kol,'content_complete':False})
        run=SourcePipeline(self.store,adapter=self.adapter).run('zh_macro',candidate['id'])
        self.assertEqual(run['status'],'wait')
        self.assertEqual(run['candidates'],[])
        self.assertEqual(self.calls,[])

    def test_cross_account_candidate_and_changed_subscription_rejected(self):
        candidate=self.admitted()
        with self.assertRaisesRegex(ValueError,'another account'):
            valid_candidate(self.store,'zh_industry',candidate['id'])
        config=universes();config[1]['universe_version']='changed'
        with patch('live.account_sources.universes',return_value=config):
            with self.assertRaisesRegex(ValueError,'Subscription changed'):
                valid_candidate(self.store,'zh_macro',candidate['id'])

    def test_concurrent_duplicate_generation_calls_adapter_once(self):
        candidate=self.admitted()
        runner=SourcePipeline(self.store,adapter=self.adapter)
        results=[]
        threads=[threading.Thread(target=lambda:results.append(runner.run('zh_macro',candidate['id']))) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(results[0]['id'],results[1]['id'])

    def test_followup_requires_original_post_not_only_same_text(self):
        run=self.run_one()
        different=self.admitted({**self.kol,'url':'https://theovershoot.co/p/different'})
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            SourcePipeline(self.store,adapter=self.adapter).run('zh_macro',different['id'],run['id'])

    def test_replay_uses_historical_state_and_feedback_cutoff(self):
        source=self.store.source(self.kol)
        event=self.store.event({'family':'TEST-replay','title':'TEST','mode':'replay','occurred_at':self.kol['published_at'],
            'as_of':'2026-09-04T14:00:00Z','source_ids':[source['id']],'evidence':[]})
        candidate=self.admitted(event_id=event['id'])
        with patch.object(self.store,'feedback_context',return_value=[]) as feedback:
            SourcePipeline(self.store,adapter=self.adapter).run('zh_macro',candidate['id'])
        feedback.assert_called_once_with('zh_macro',event['as_of'])

    def test_human_metrics_pending_first_verdict_and_edits(self):
        run=self.run_one()
        self.assertIsNone(self.store.human_quality()['groups'][0]['ready_with_at_most_minor_rate'])
        self.review(run)
        self.review(run,'reject','reject')
        stats=self.store.human_quality()['groups'][0]
        self.assertEqual((stats['reviewed'],stats['unchanged'],stats['reject']),(1,1,0))
        self.assertEqual(stats['ready_with_at_most_minor_rate'],1)
        edited=self.review(run,edit_class='minor',text='就业增加，前一个月的数据修订。')
        self.assertTrue(edited['edit_spans'])
        self.assertFalse(edited['machine_qa_applies_to_text'])

    def test_followup_does_not_inflate_first_draft_metric(self):
        run=self.run_one()
        SourcePipeline(self.store,adapter=self.adapter).run('zh_macro',run['inbox_candidate_id'],run['id'])
        stats=self.store.human_quality()['groups'][0]
        self.assertEqual((stats['generated'],stats['pending'],stats['followup_drafts']),(1,1,1))

    def test_no_machine_label_can_fill_human_edit_class(self):
        run=self.run_one()
        with self.assertRaisesRegex(ValueError,'Explicit human edit class'):
            self.review(run,edit_class=None)
        with self.assertRaisesRegex(ValueError,'Changed text'):
            self.review(run,text='Changed text')

    def test_broadcast_retired(self):
        with self.assertRaisesRegex(ValueError,'broadcast retired'):
            Pipeline(self.store,client=object()).event_all_accounts('anything')

    def test_api_inbox_and_no_legacy_generation(self):
        candidate=self.admitted()
        with patch.object(api,'STORE',self.store):
            client=TestClient(app)
            result=client.get('/api/account-intelligence/accounts/zh_macro/inbox')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['candidates'][0]['id'],candidate['id'])
            self.assertEqual(client.get('/api/account-intelligence/accounts/en_industry/inbox').status_code,422)
            response=client.post('/api/account-intelligence/events/anything/run',json={'account_id':'zh_macro'})
            self.assertEqual(response.status_code,409)


if __name__=='__main__':unittest.main()
