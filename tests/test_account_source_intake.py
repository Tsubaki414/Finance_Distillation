"""Offline source-preservation, scoped collection and evidence-input regressions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live.account_intelligence import Store
from live.account_sources import refresh, ingest, SourcePipeline, current_evidence_records
from live.xsearch import normalize_item, search


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'store')
        self.row = {'id': 'test-source', 'source_id': 'primary_bls', 'url': 'https://www.bls.gov/news.release/test.htm',
                    'author_name': 'BLS', 'original_text': 'Employment increased by 100,000. The prior month was revised.',
                    'content_complete': True, 'published_at': '2026-09-04T12:30:00Z', 'fetched_at': '2026-09-04T13:00:00Z'}
        self.kol = {**self.row, 'source_id': 'overshoot', 'url': 'https://theovershoot.co/p/test',
                    'author_name': 'Matthew Klein'}
        self.calls = []

    def adapter(self, source, account_id, directory, **kwargs):
        self.calls.append(kwargs)
        return {'draft_status': 'skipped', 'status': 'skipped', 'final_draft': '', 'route': {'reason': 'TEST ONLY'}}

    def evidence(self, **updates):
        source = self.store.source(self.row)
        return {'id': 'e1', 'source_id': source['id'], 'source_quote': 'Employment increased by 100,000.',
                'as_of': '2026-09-04T13:00:00Z', 'verified_at': '2026-09-04T13:30:00Z',
                'verification_status': 'verified',
                'verification': {'by': 'TEST reviewer', 'method': 'manual exact-source check', 'reason': 'TEST ONLY'}, **updates}

    def test_evidence_resolves_exact_immutable_source_and_verifier(self):
        candidate = ingest(self.store, 'zh_macro', self.kol)['candidate']
        evidence = self.evidence()
        run = SourcePipeline(self.store, adapter=self.adapter).run('zh_macro', candidate['id'], current_evidence=[evidence])
        context = self.calls[0]['account_context']['current_evidence'][0]
        self.assertEqual(context['text'], evidence['source_quote'])
        self.assertEqual(context['source_id'], evidence['source_id'])
        self.assertIn('not_independently_verified', context['verification_origin'])
        self.assertEqual(run['current_evidence'], [context])

    def test_invalid_evidence_never_reaches_adapter(self):
        candidate = ingest(self.store, 'zh_macro', self.kol)['candidate']
        run = SourcePipeline(self.store, adapter=self.adapter).run('zh_macro', candidate['id'], current_evidence=[self.evidence(source_quote='invented')])
        self.assertEqual(run['status'], 'execution_failed')
        self.assertIn('exact captured span', run['contract_error'])
        self.assertEqual(self.calls, [])

    def test_evidence_date_identity_and_verification_constraints(self):
        base = self.evidence()
        bad = [{'verified_at': '2026-09-04T13:30:00'}, {'verified_at': '2026-09-04T12:00:00Z'},
               {'as_of': '2027-01-01T00:00:00Z'}, {'verification': {}},
               {'source_id': 'source-missing'}, {'verification_status': 'unverified'}]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                current_evidence_records(self.store, [{**base, **changes}], '2026-09-05T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'unique'):
            current_evidence_records(self.store, [base, base], '2026-09-05T00:00:00Z')

    def test_evidence_cannot_leak_into_historical_replay(self):
        stored = self.store.source(self.kol)
        event = self.store.event({'family': 'test-replay', 'title': 'TEST', 'mode': 'replay',
            'occurred_at': self.row['published_at'], 'as_of': '2026-09-04T13:15:00Z',
            'source_ids': [stored['id']], 'evidence': []})
        candidate = ingest(self.store, 'zh_macro', self.kol, event_id=event['id'])['candidate']
        run = SourcePipeline(self.store, adapter=self.adapter).run('zh_macro', candidate['id'], current_evidence=[self.evidence()])
        self.assertEqual(run['status'], 'execution_failed')
        self.assertEqual(self.calls, [])

    def test_new_evidence_requires_explicit_followup(self):
        candidate = ingest(self.store, 'zh_macro', self.kol)['candidate']
        pipeline = SourcePipeline(self.store, adapter=self.adapter)
        first = pipeline.run('zh_macro', candidate['id'])
        with self.assertRaisesRegex(ValueError, 'explicit follow-up'):
            pipeline.run('zh_macro', candidate['id'], current_evidence=[self.evidence()])
        second = pipeline.run('zh_macro', candidate['id'], first['id'], current_evidence=[self.evidence()])
        self.assertEqual(second['follow_up_of'], first['id'])
        self.assertEqual(len(self.calls), 2)

    def test_default_context_does_not_invent_evidence(self):
        candidate = ingest(self.store, 'zh_macro', self.kol)['candidate']
        SourcePipeline(self.store, adapter=self.adapter).run('zh_macro', candidate['id'])
        self.assertNotIn('current_evidence', self.calls[0]['account_context'])

    def test_x_never_called_implicitly_and_morris_needs_historical_window(self):
        with patch('live.xsearch.search') as call:
            result = refresh(self.store, 'en_morris_archive')
            self.assertEqual(result['fetches'], 0)
            self.assertEqual(result['notes'][0]['status'], 'x_opt_in_required')
            with self.assertRaisesRegex(ValueError, 'historical'):
                refresh(self.store, 'en_morris_archive', include_x=True)
            call.assert_not_called()

    def test_x_refresh_one_account_exact_author_and_bounded_request(self):
        good = {**self.row, 'id': 'x1', 'source_id': 'x_Morris_LT', 'author_handle': 'Morris_LT',
                'author_name': 'Morris', 'url': 'https://x.com/Morris_LT/status/123',
                'original_text': '先尝试，再观察反馈，再调整方向。重要的是反复检验，而不是等待完美计划。', 'source_language': 'zh'}
        bad = {**good, 'author_handle': 'other', 'post_id': 'wrong'}
        with patch('live.xsearch.search', return_value={'rows': [good, bad], 'billed_usd': .001}) as call:
            result = refresh(self.store, 'en_morris_archive', limit=2, include_x=True, since='2024-01-01', until='2025-01-01')
        self.assertEqual(call.call_args.args, ('from:Morris_LT since:2024-01-01 until:2025-01-01',))
        self.assertEqual(call.call_args.kwargs['max_items'], 2)
        self.assertEqual(len(result['results']), 1)
        self.assertEqual({c['account_id'] for c in self.store.rows('inbox')}, {'en_morris_archive'})
        self.assertIn('unexpected_search_author_rejected', [n['status'] for n in result['notes']])

    def test_outside_subscription_and_official_url_rejected_before_network(self):
        with patch('live.source_recovery.fetch_public') as fetch:
            with self.assertRaisesRegex(ValueError, 'outside'):
                refresh(self.store, 'zh_industry', primary_documents=[{'source_id': 'primary_bls', 'url': self.row['url']}])
            with self.assertRaisesRegex(ValueError, 'outside'):
                refresh(self.store, 'zh_macro', source_ids=['semianalysis'])
            with self.assertRaisesRegex(ValueError, 'publisher'):
                refresh(self.store, 'zh_macro', source_ids=['primary_bls'], primary_documents=[{'source_id': 'primary_bls', 'url': 'https://evil.example/a'}])
            fetch.assert_not_called()

    def test_official_capture_preserved_as_context_and_missing_date_never_invented(self):
        raw = '<html><h1>Employment release</h1><main><p>' + self.row['original_text'] * 3 + '</p></main></html>'
        doc = {'raw': raw, 'url': self.row['url'], 'content_type': 'text/html', 'fetched_at': self.row['fetched_at']}
        with patch('live.source_recovery.fetch_public', return_value=doc):
            result = refresh(self.store, 'zh_macro', source_ids=['primary_bls'],
                             primary_documents=[{'source_id': 'primary_bls', 'url': self.row['url']}])
        self.assertEqual(result['fetches'], 1)
        receipt = result['results'][0]
        self.assertFalse(receipt['admitted'])
        self.assertTrue(receipt['context_only'])
        self.assertEqual(self.store.rows('inbox'), [])
        from live.source_context import ContextStore
        captured = ContextStore(self.store.root).references('zh_macro', {'external_links': [self.row['url']]})[0]
        self.assertIsNone(captured['published_at'])
        self.assertEqual(captured['verification_status'], 'captured_not_fact_verified')
        self.assertEqual(json.loads(Path(captured['raw_import_ref']).read_text())['raw'], raw)
        self.assertEqual(captured['context_items'][0]['retrieval_mode'], 'explicit_official_url')

    def test_refresh_fetch_cap_does_not_broadcast(self):
        with patch('live.analysis_corpus.fetch_feed', return_value=([], None)) as fetch:
            result = refresh(self.store, 'zh_industry', max_sources=1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['fetches'], 1)
        self.assertEqual(result['generation_calls'], 0)

    def test_rss_chart_uncertainty_preserved_not_blanket_blocked(self):
        row = {**self.row, 'source_id': 'semianalysis', 'author_name': 'SemiAnalysis',
               'url': 'https://newsletter.semianalysis.com/p/test', 'media': [{'url': 'https://example.com/chart.png'}],
               'original_text': 'GPU performance depends on memory bandwidth. The chart shows another case.'}
        with patch('live.analysis_corpus.fetch_feed', return_value=([row], None)):
            result = refresh(self.store, 'zh_industry', source_ids=['semianalysis'])
        candidate = result['results'][0]['candidate']
        self.assertEqual(candidate['blocking_gaps'], [])
        source = self.store.get('sources', candidate['source_id'])
        self.assertEqual(source['media_dependencies'][0]['status'], 'uncertain_dependency')
        row['media_dependencies'] = [{'kind': 'required_chart', 'required': True}]
        with patch('live.analysis_corpus.fetch_feed', return_value=([row], None)):
            result = refresh(self.store, 'zh_industry', source_ids=['semianalysis'])
        self.assertIn('Required media/thread/context unresolved', result['results'][0]['candidate']['blocking_gaps'])


class XCaptureTests(unittest.TestCase):
    def item(self, **updates):
        return {'id': '123', 'text': '完整中文正文，保留原文判断。', 'fullText': '完整中文正文，保留原文判断。',
                'author': {'id': '456', 'name': 'Morris', 'userName': 'Morris_LT'}, 'lang': 'zh',
                'createdAt': '2024-01-01T12:00:00Z', 'isReply': False, 'isQuote': False, 'isRetweet': False,
                **updates}

    def normalize(self, item):
        return normalize_item(item, query='from:Morris_LT', run_id='test-run', dataset_id='test-dataset',
                              fetched_at='2026-09-01T00:00:00Z', raw_import_ref='TEST/raw.json#items/0')

    def test_longest_visible_text_not_blind_fulltext_and_unknown_completeness(self):
        item = self.item(text='完整中文正文，保留原文判断以及必要条件。', fullText='完全不同且截断的短句')
        row = self.normalize(item)
        self.assertEqual(row['original_text'], item['text'])
        self.assertFalse(row['content_complete'])
        self.assertEqual(row['extraction_status'], 'conflicting_text_variants')
        self.assertEqual(row['context_items'][0]['text_variants']['fullText'], item['fullText'])
        # P0-3a: two identical variants below the platform limit are internally consistent.
        self.assertTrue(self.normalize(self.item())['content_complete'])
        self.assertEqual(self.normalize(self.item())['completeness_basis'], 'variants_identical')
        self.assertFalse(self.normalize(self.item(fullText=None))['content_complete'])
        self.assertTrue(self.normalize(self.item(truncated=False))['content_complete'])
        self.assertFalse(self.normalize(self.item(truncated=True))['content_complete'])

    def test_reply_quote_media_author_metadata_survives_source_store(self):
        item = self.item(truncated=False, isReply=True, inReplyToId='12', inReplyToUsername='Someone',
                         isQuote=True, quoteId='13', quote={'id': '13', 'text': 'Their body', 'author': {'name': 'Other'}},
                         media=['https://pbs.twimg.com/media/chart.jpg'], conversationId='10',
                         entities={'urls': [{'expanded_url': 'https://example.com/research'}]},
                         extendedEntities={'media': [{'type': 'photo'}]}, card={'title': 'Research'})
        row = self.normalize(item)
        before = copy.deepcopy(item)
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            result = ingest(store, 'en_morris_archive', row)
            saved = store.get('sources', result['candidate']['source_id'])
        self.assertEqual(item, before)
        self.assertEqual(saved['author_id'], '456')
        self.assertEqual(saved['reply_to']['post_id'], '12')
        self.assertEqual(saved['quoted_post']['author']['name'], 'Other')
        self.assertEqual(saved['media'], item['media'])
        self.assertEqual(saved['thread_id'], '10')
        self.assertEqual(saved['context_items'][0]['card'], item['card'])
        self.assertEqual(saved['original_text'], item['text'])
        self.assertNotIn('Their body', saved['original_text'])

    def test_search_saves_untouched_raw_dataset_and_actor_input(self):
        item = self.item()
        responses = [{'data': {'id': 'test-run', 'status': 'SUCCEEDED', 'defaultDatasetId': 'test-dataset'}}, [item]]
        with tempfile.TemporaryDirectory() as temp, patch('live.xsearch.remaining_usd', return_value=10), \
             patch('live.xsearch._settle_cost', return_value=.001), patch('live.xsearch._call', side_effect=responses):
            result = search('from:Morris_LT', max_items=2, raw_directory=temp)
            raw = json.loads(Path(result['raw_snapshot']).read_text())
            self.assertEqual(raw['items'], [item])
            self.assertEqual(raw['actor_input'], {'searchTerms': ['from:Morris_LT'], 'maxItems': 2, 'sort': 'Latest'})
            self.assertEqual(raw['dataset_id'], 'test-dataset')
            self.assertEqual(result['rows'][0]['raw_import_hash'], raw['item_hashes'][0])
            self.assertIn('#items/0', result['rows'][0]['raw_import_ref'])

    def test_nonpositive_query_cap_rejected_before_network(self):
        with patch('live.xsearch._call') as call, self.assertRaises(ValueError):
            search('test', max_items=0)
        call.assert_not_called()

    def test_provider_sentinels_never_become_source_posts(self):
        self.assertIsNone(self.normalize({'noResults': True, 'text': 'No results'}))
        self.assertIsNone(self.normalize({'text': 'Missing id'}))
        self.assertIsNone(self.normalize({'id': 'missing-body'}))


if __name__ == '__main__':
    unittest.main()
