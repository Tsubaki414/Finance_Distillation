import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from live.monitor_intake import FetchResult, IntakeFailure, Poller, identity


NOW = '2026-10-01T12:00:00+00:00'


def row(number, published='2026-10-01T10:00:00+00:00', handle='Morris_LT'):
    return {'post_id': str(number), 'source_id': 'x_' + handle, 'author_handle': handle,
            'author_name': handle, 'url': f'https://x.com/{handle}/status/{number}',
            'original_text': '原文逻辑和具体例子。' + str(number), 'published_at': published,
            'fetched_at': NOW, 'content_complete': True, 'source_language': 'zh'}


class PollingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sub = {'source_id': 'feed_one', 'enabled': True, 'role': 'CORE'}
        self.sub_x = {'source_id': 'x_writer', 'enabled': True, 'role': 'CORE'}
        self.archive = {'source_id': 'x_Morris_LT', 'enabled': True, 'role': 'CORE'}
        self.primary = {'source_id': 'primary_bls', 'enabled': True, 'role': 'CORE'}
        self.catalog = {'feed_one': {'adapter': 'feed', 'feed_url': 'https://writer.example/feed'},
                        'x_writer': {'adapter': 'x', 'handle': 'writer'}}
        self.worlds = {'zh_macro': {'subscriptions': [self.sub, self.sub_x, self.primary]},
                       'zh_industry': {'subscriptions': []},
                       'en_morris_archive': {'subscriptions': [self.archive]}}

    def poller(self, **kwargs):
        return Poller(self.root / 'captures', catalog=self.catalog,
                      universe_loader=lambda account: self.worlds[account], **kwargs)

    def test_account_and_cursor_are_bound_before_any_fetch(self):
        fetch = Mock()
        poller = self.poller(feed_fetcher=fetch)
        with self.assertRaisesRegex(IntakeFailure, 'source_outside_account'):
            poller.fetch('zh_industry', self.sub, as_of=NOW)
        with self.assertRaisesRegex(IntakeFailure, 'cursor_scope_mismatch'):
            poller.fetch('zh_macro', self.sub, {'account_id': 'zh_industry'}, as_of=NOW)
        fetch.assert_not_called()

    def test_unconfigured_official_material_is_context_only_and_incomplete(self):
        fetch = Mock()
        result = self.poller(feed_fetcher=fetch).fetch('zh_macro', self.primary, as_of=NOW)
        self.assertEqual(result.items, [])
        self.assertFalse(result.complete)
        self.assertFalse(result.diagnostics['checked'])
        self.assertEqual(result.diagnostics['status'], 'context_only')
        fetch.assert_not_called()

    def test_feed_restart_drains_unsorted_backlog_without_replaying(self):
        rows = [row(3, '2026-10-01T11:00:00Z'), row(1, '2026-10-01T08:00:00Z'),
                row(2, '2026-10-01T09:00:00Z')]
        poller = self.poller(feed_fetcher=lambda *a, **kw: (rows, None))
        first = poller.fetch('zh_macro', self.sub, as_of=NOW, limit=1)
        self.assertEqual(first.items[0]['post_id'], '1')
        self.assertFalse(first.complete)
        restored = json.loads(json.dumps(first.cursor))
        second = self.poller(feed_fetcher=lambda *a, **kw: (rows, None)).fetch(
            'zh_macro', self.sub, restored, as_of=NOW, limit=2)
        self.assertEqual([r['post_id'] for r in second.items], ['2', '3'])
        self.assertEqual(second.diagnostics['duplicate_skipped'], 1)
        third = poller.fetch('zh_macro', self.sub, second.cursor, as_of=NOW)
        self.assertEqual(third.items, [])
        self.assertEqual(third.diagnostics['duplicate_skipped'], 3)
        self.assertTrue(Path(first.items[0]['raw_import_ref'].split('#')[0]).is_file())

    def test_registry_archive_paths_and_appends_preserve_consumption_after_restart(self):
        base = self.root / 'history.json'
        imports = self.root / 'imports'
        imports.mkdir()
        original = {**row(1, '2024-01-01'), 'author_handle': 'Morris_LT',
                    'source_id': 'x_Morris_LT', 'url': 'https://x.com/Morris_LT/status/1',
                    'source_language': 'zh', 'original_text': '历史分析仍需人工核对是否适用于今天。'}
        base.write_text(json.dumps([original]))
        self.catalog['x_Morris_LT'] = {'adapter': 'archive', 'archive_paths': [str(base)],
            'archive_import_dir': str(imports), 'coverage': 'bounded_saved_history_not_complete'}
        first = self.poller().fetch('en_morris_archive', self.archive, as_of=NOW)
        self.assertEqual(len(first.items), 1)
        appended = {**original, 'url': 'https://x.com/Morris_LT/status/2', 'post_id': '2',
                    'published_at': '2023-01-01', 'original_text': '另一条更早的历史材料。'}
        (imports / '20261001.jsonl').write_text(json.dumps(appended) + '\n')
        second = self.poller().fetch('en_morris_archive', self.archive,
                                    json.loads(json.dumps(first.cursor)), as_of=NOW)
        self.assertEqual([item['post_id'] for item in second.items], ['2'])
        self.assertEqual(second.items[0]['published_at'], '2023-01-01T00:00:00+00:00')
        self.assertEqual(second.diagnostics['coverage'], 'bounded_saved_history_not_complete')
        third = self.poller().fetch('en_morris_archive', self.archive, second.cursor, as_of=NOW)
        self.assertEqual(third.items, [])

    def test_feed_old_and_future_dates_never_become_today(self):
        rows = [row(1, '2024-01-01'), row(2, '2026-10-02'), row(3, 'not-a-date')]
        result = self.poller(feed_fetcher=lambda *a, **kw: (rows, None)).fetch(
            'zh_macro', self.sub, as_of=NOW)
        self.assertEqual([r['post_id'] for r in result.items], ['3'])
        self.assertIsNone(result.items[0]['published_at'])
        self.assertEqual(result.diagnostics['stale_skipped'], 1)
        self.assertEqual(result.diagnostics['future_deferred'], 1)
        self.assertNotIn('x:2', result.cursor['seen_ids'])

    def test_feed_corrected_body_and_language_redeliver_same_identity_after_restart(self):
        value = {**row(1), 'url': 'https://writer.example/article',
                 'original_text': 'The first premise. The second premise.', 'source_language': 'unknown'}
        first = self.poller(feed_fetcher=lambda *a, **kw: ([value], None)).fetch(
            'zh_macro', self.sub, as_of=NOW)
        corrected = {**value, 'original_text': 'The first premise.\n\nThe second premise.'}
        second = self.poller(feed_fetcher=lambda *a, **kw: ([corrected], None)).fetch(
            'zh_macro', self.sub, json.loads(json.dumps(first.cursor)), as_of=NOW)
        self.assertEqual(len(second.items), 1)
        self.assertEqual(second.diagnostics['feed_revision_rechecks'], 1)
        self.assertEqual(identity(first.items[0]), identity(second.items[0]))
        language_fixed = {**corrected, 'source_language': 'en'}
        third = self.poller(feed_fetcher=lambda *a, **kw: ([language_fixed], None)).fetch(
            'zh_macro', self.sub, second.cursor, as_of=NOW)
        self.assertEqual(third.items[0]['source_language'], 'en')
        self.assertEqual(third.diagnostics['feed_revision_rechecks'], 1)
        unchanged = {**language_fixed, 'fetched_at': '2026-10-01T13:00:00Z',
                     'raw_import_ref': 'a-new-fetch-snapshot'}
        fourth = self.poller(feed_fetcher=lambda *a, **kw: ([unchanged], None)).fetch(
            'zh_macro', self.sub, json.loads(json.dumps(third.cursor)), as_of='2026-10-01T13:00:00Z')
        self.assertEqual(fourth.items, [])
        self.assertEqual(fourth.diagnostics['duplicate_skipped'], 1)

    def test_feed_legacy_cursor_reconciliation_is_bounded_and_freshness_prunes_digests(self):
        values = [row(1), row(2)]
        cursor = {'seen_ids': [identity(value) for value in values],
                  'seen_dates': {identity(value): value['published_at'] for value in values},
                  'body_complete_ids': [identity(value) for value in values]}
        feed = lambda *a, **kw: (values, None)
        first = self.poller(feed_fetcher=feed).fetch('zh_macro', self.sub, cursor, as_of=NOW, limit=1)
        self.assertEqual([item['post_id'] for item in first.items], ['1'])
        self.assertFalse(first.complete)
        self.assertEqual(len(first.cursor['seen_revisions']), 1)
        second = self.poller(feed_fetcher=feed).fetch('zh_macro', self.sub, first.cursor, as_of=NOW, limit=1)
        self.assertEqual([item['post_id'] for item in second.items], ['2'])
        self.assertEqual(len(second.cursor['seen_revisions']), 2)
        third = self.poller(feed_fetcher=feed).fetch('zh_macro', self.sub, second.cursor, as_of=NOW)
        self.assertEqual(third.items, [])
        expired = self.poller(feed_fetcher=feed).fetch('zh_macro', self.sub, third.cursor,
                                                     as_of='2026-10-05T12:00:00Z')
        self.assertEqual(expired.items, [])
        self.assertEqual(expired.cursor['seen_revisions'], {})
        self.assertEqual(expired.diagnostics['stale_skipped'], 2)

    def test_feed_recovered_preview_digest_does_not_repeat_full_body_retrieval(self):
        preview = {**row(1), 'url': 'https://writer.example/article',
                   'original_text': 'A short preview.', 'content_complete': False}
        document = {'url': preview['url'], 'content_type': 'text/html', 'fetched_at': NOW,
                    'raw': '<article><p>' + 'The complete original argument and its conditions. ' * 5 + '</p></article>'}
        fetch = Mock(return_value=document)
        first = self.poller(feed_fetcher=lambda *a, **kw: ([preview], None), recovery_fetcher=fetch).fetch(
            'zh_macro', self.sub, as_of=NOW)
        self.assertTrue(first.items[0]['content_complete'])
        second = self.poller(feed_fetcher=lambda *a, **kw: ([preview], None), recovery_fetcher=fetch).fetch(
            'zh_macro', self.sub, first.cursor, as_of='2026-10-01T13:00:00Z')
        self.assertEqual(second.items, [])
        self.assertEqual(fetch.call_count, 1)

    def test_feed_failure_leaves_supplied_checkpoint_untouched(self):
        cursor = {'seen_ids': ['x:123'], 'last_seen': NOW}
        original = json.loads(json.dumps(cursor))
        with self.assertRaisesRegex(IntakeFailure, 'feed_fetch_failed'):
            self.poller(feed_fetcher=lambda *a, **kw: ([], 'fetch_failed')).fetch(
                'zh_macro', self.sub, cursor, as_of=NOW)
        self.assertEqual(cursor, original)

    def test_feed_full_provider_page_marks_coverage_partial(self):
        rows = [row(i) for i in range(200)]
        result = self.poller(feed_fetcher=lambda *a, **kw: (rows, None)).fetch(
            'zh_macro', self.sub, as_of=NOW, limit=200)
        self.assertFalse(result.complete)
        self.assertTrue(result.diagnostics['retrieval_saturated'])

    def test_public_body_recovery_preserves_preview_and_source_date(self):
        preview = {**row(1), 'url': 'https://writer.example/post',
                   'original_text': 'A short preview.', 'content_complete': False}
        document = {'url': preview['url'], 'content_type': 'text/html', 'fetched_at': NOW,
                    'raw': '<article><p>' + 'A complete original sentence with its reasoning. ' * 5 + '</p></article>'}
        recovered = self.poller(feed_fetcher=lambda *a, **kw: ([preview], None),
                               recovery_fetcher=Mock(return_value=document)).fetch(
                                   'zh_macro', self.sub, as_of=NOW)
        item = recovered.items[0]
        self.assertTrue(item['content_complete'])
        self.assertIn('A complete original', item['original_text'])
        self.assertEqual(item['published_at'], preview['published_at'])
        self.assertEqual(item['context_items'][-1]['text'], 'A short preview.')
        self.assertTrue(Path(item['recovery']['actions'][0]['document_ref']).is_file())

    def test_paywall_and_outside_publisher_never_become_complete(self):
        preview = {**row(1), 'url': 'https://writer.example/post',
                   'original_text': 'A short preview.', 'content_complete': False}
        document = {'url': preview['url'], 'content_type': 'text/html', 'fetched_at': NOW,
                    'raw': '<article>' + 'A short preview of a larger argument. ' * 4 + ' Subscribe to read</article>'}
        fetch = Mock(return_value=document)
        poller = self.poller(feed_fetcher=lambda *a, **kw: ([preview], None), recovery_fetcher=fetch)
        result = poller.fetch('zh_macro', self.sub, as_of=NOW)
        self.assertFalse(result.items[0]['content_complete'])
        self.assertEqual(result.items[0]['original_text'], preview['original_text'])
        self.assertEqual(result.diagnostics['body_recovery_unresolved'], 1)
        foreign = {**preview, 'url': 'https://outside.example/private'}
        fetch.reset_mock()
        result = self.poller(feed_fetcher=lambda *a, **kw: ([foreign], None), recovery_fetcher=fetch).fetch(
            'zh_macro', self.sub, as_of=NOW)
        fetch.assert_not_called()
        self.assertFalse(result.items[0]['content_complete'])

    def test_feed_seen_cache_expires_outside_rolling_freshness_window(self):
        cursor = {'seen_ids': ['x:1'], 'seen_dates': {'x:1': '2026-09-20T12:00:00+00:00'},
                  'window_start': '2026-09-01T12:00:00+00:00'}
        result = self.poller(feed_fetcher=lambda *a, **kw: ([], None)).fetch(
            'zh_macro', self.sub, cursor, as_of=NOW)
        self.assertEqual(result.cursor['seen_ids'], [])
        self.assertEqual(result.cursor['seen_dates'], {})
        self.assertEqual(result.cursor['window_start'], '2026-09-28T12:00:00+00:00')

    def test_incomplete_preview_is_retried_with_backoff_then_legitimately_recovers(self):
        preview = {**row(1), 'url': 'https://writer.example/post',
                   'original_text': 'A short preview.', 'content_complete': False}
        paywall = {'url': preview['url'], 'content_type': 'text/html', 'fetched_at': NOW,
                   'raw': '<article>' + 'A partial preview of a larger argument. ' * 4 + ' Subscribe to read</article>'}
        full = {**paywall, 'raw': '<article><p>' + 'The full original reasoning with all necessary details. ' * 5 + '</p></article>'}
        fetch = Mock(side_effect=[paywall, full])
        poller = self.poller(feed_fetcher=lambda *a, **kw: ([preview], None), recovery_fetcher=fetch)
        first = poller.fetch('zh_macro', self.sub, as_of=NOW)
        self.assertFalse(first.complete)
        self.assertNotIn(identity(preview), first.cursor['seen_ids'])
        self.assertEqual(first.diagnostics['body_recovery_pending'], 1)
        second = poller.fetch('zh_macro', self.sub, first.cursor, as_of='2026-10-01T13:00:00Z')
        self.assertFalse(second.complete)
        self.assertEqual(second.items, [])
        self.assertEqual(second.diagnostics['body_recovery_deferred'], 1)
        third = poller.fetch('zh_macro', self.sub, second.cursor, as_of='2026-10-01T18:00:00Z')
        self.assertTrue(third.items[0]['content_complete'])
        self.assertEqual(third.items[0]['published_at'], preview['published_at'])
        self.assertTrue(third.complete)
        self.assertEqual(third.cursor['body_retries'], {})
        self.assertIn(identity(preview), third.cursor['seen_ids'])
        self.assertEqual(fetch.call_count, 2)
        fourth = poller.fetch('zh_macro', self.sub, third.cursor, as_of='2026-10-01T19:00:00Z')
        self.assertEqual(fourth.items, [])
        self.assertEqual(fetch.call_count, 2)

    def test_changed_or_now_complete_feed_body_bypasses_recovery_backoff(self):
        preview = {**row(1), 'url': 'https://writer.example/post',
                   'original_text': 'A short preview.', 'content_complete': False}
        rows = [preview]
        fetch = Mock(side_effect=RuntimeError('temporary outage'))
        poller = self.poller(feed_fetcher=lambda *a, **kw: (rows, None), recovery_fetcher=fetch)
        first = poller.fetch('zh_macro', self.sub, as_of=NOW)
        rows[0] = {**preview, 'content_complete': True}
        second = poller.fetch('zh_macro', self.sub, first.cursor, as_of='2026-10-01T12:05:00Z')
        self.assertEqual(len(second.items), 1)
        self.assertTrue(second.complete)
        self.assertEqual(second.cursor['body_retries'], {})
        self.assertEqual(fetch.call_count, 1)

    def test_legacy_checkpoint_does_not_permanently_consume_unresolved_preview(self):
        preview = {**row(1), 'url': 'https://writer.example/post',
                   'original_text': 'A short preview.', 'content_complete': False}
        key = identity(preview)
        cursor = {'seen_ids': [key], 'seen_dates': {key: preview['published_at']}}
        full = {'url': preview['url'], 'content_type': 'text/html', 'fetched_at': NOW,
                'raw': '<article><p>' + 'The full original reasoning with all necessary details. ' * 5 + '</p></article>'}
        fetch = Mock(return_value=full)
        poller = self.poller(feed_fetcher=lambda *a, **kw: ([preview], None), recovery_fetcher=fetch)
        first = poller.fetch('zh_macro', self.sub, cursor, as_of=NOW)
        self.assertEqual(len(first.items), 1)
        self.assertTrue(first.items[0]['content_complete'])
        second = poller.fetch('zh_macro', self.sub, first.cursor, as_of=NOW)
        self.assertEqual(second.items, [])
        self.assertEqual(fetch.call_count, 1)

    def test_archive_consumed_identity_survives_reorder_and_older_append(self):
        path = self.root / 'archive.json'
        path.write_text(json.dumps({'sources': [row(11, '2024-05-01'), row(12, '2024-05-02')]}))
        poller = self.poller(archive_paths=[path])
        first = poller.fetch('en_morris_archive', self.archive, as_of=NOW)
        self.assertEqual(len(first.items), 2)
        path.write_text(json.dumps({'sources': [row(13, '2023-01-01'), row(12, '2024-05-02'),
                                               row(11, '2024-05-01')]}))
        second = poller.fetch('en_morris_archive', self.archive, first.cursor, as_of=NOW)
        self.assertEqual([r['post_id'] for r in second.items], ['13'])
        self.assertEqual(second.items[0]['published_at'], '2023-01-01T00:00:00+00:00')
        self.assertEqual(second.items[0]['monitor_source_mode'], 'historical_archive')

    def test_archive_merges_verified_capture_without_counting_new_post(self):
        path, verified = self.root / 'archive.json', self.root / 'verified.json'
        first_row = row(22, '2024-05-01')
        path.write_text(json.dumps({'sources': [{**first_row, 'content_complete': False}]}))
        verified.write_text(json.dumps({'sources': [{'source': {**first_row, 'content_complete': True}}]}))
        result = self.poller(archive_paths=[path, verified]).fetch(
            'en_morris_archive', self.archive, as_of=NOW)
        self.assertEqual(len(result.items), 1)
        self.assertTrue(result.items[0]['content_complete'])

    def test_archive_corrected_capture_recovers_existing_source_hold_after_restart(self):
        from live.account_monitor import State
        path = self.root / 'archive.json'
        original = {**row(23, '2024-05-01'), 'content_complete': False}
        path.write_text(json.dumps({'sources': [original]}))
        first = self.poller(archive_paths=[path]).fetch('en_morris_archive', self.archive, as_of=NOW)
        state = State(self.root / 'store')
        item_id, _ = state.enqueue('en_morris_archive', 'x_Morris_LT', first.items[0], NOW,
                                   status='blocked_source')
        corrected = {**original, 'content_complete': True,
                     'original_text': original['original_text'] + '补全的条件和取舍。',
                     'context_items': [{'kind': 'verified_context', 'text': 'Captured missing context.'}]}
        path.write_text(json.dumps({'sources': [corrected]}))
        restored = json.loads(json.dumps(first.cursor))
        second = self.poller(archive_paths=[path]).fetch(
            'en_morris_archive', self.archive, restored, as_of=NOW)
        self.assertEqual(len(second.items), 1)
        self.assertEqual(second.diagnostics['archive_revision_rechecks'], 1)
        self.assertEqual(state.enqueue('en_morris_archive', 'x_Morris_LT', second.items[0], NOW),
                         (item_id, False))
        saved = state.rows('items')
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['status'], 'pending')
        self.assertEqual(json.loads(saved[0]['row_json'])['original_text'], corrected['original_text'])
        # A new capture timestamp/reference alone is not another content revision.
        path.write_text(json.dumps({'sources': [{**corrected, 'fetched_at': '2026-10-01T13:00:00Z',
                                                 'raw_import_ref': 'new-import'}]}))
        third = self.poller(archive_paths=[path]).fetch(
            'en_morris_archive', self.archive, second.cursor, as_of='2026-10-01T14:00:00Z')
        self.assertEqual(third.items, [])

    def test_archive_revision_never_reopens_a_drafted_identity(self):
        from live.account_monitor import State
        path = self.root / 'archive.json'
        original = row(24, '2024-05-01')
        path.write_text(json.dumps({'sources': [original]}))
        first = self.poller(archive_paths=[path]).fetch('en_morris_archive', self.archive, as_of=NOW)
        state = State(self.root / 'store')
        item_id, _ = state.enqueue('en_morris_archive', 'x_Morris_LT', first.items[0], NOW,
                                   status='drafted', last_run='existing-run')
        path.write_text(json.dumps({'sources': [{**original, 'original_text': '修订后的原文。'}]}))
        second = self.poller(archive_paths=[path]).fetch(
            'en_morris_archive', self.archive, first.cursor, as_of=NOW)
        self.assertEqual(len(second.items), 1)
        self.assertEqual(state.enqueue('en_morris_archive', 'x_Morris_LT', second.items[0], NOW),
                         (item_id, True))
        self.assertEqual(state.rows('items')[0]['status'], 'drafted')
        self.assertEqual(state.rows('items')[0]['last_run'], 'existing-run')

    def test_archive_legacy_cursor_reconciliation_is_bounded_and_stores_only_current_digests(self):
        path = self.root / 'archive.json'
        values = [row(25, '2024-05-01'), row(26, '2024-05-02')]
        path.write_text(json.dumps({'sources': values}))
        cursor = {'account_id': 'en_morris_archive', 'source_id': 'x_Morris_LT',
                  'seen_ids': [identity(value) for value in values]}
        first = self.poller(archive_paths=[path]).fetch(
            'en_morris_archive', self.archive, cursor, as_of=NOW, limit=1)
        self.assertEqual(len(first.items), 1)
        self.assertFalse(first.complete)
        self.assertEqual(len(first.cursor['archive_revisions']), 1)
        second = self.poller(archive_paths=[path]).fetch(
            'en_morris_archive', self.archive, first.cursor, as_of=NOW, limit=1)
        self.assertEqual(second.items[0]['post_id'], '26')
        self.assertTrue(second.complete)
        self.assertEqual(len(second.cursor['archive_revisions']), 2)
        self.assertTrue(all(len(value) == 64 for value in second.cursor['archive_revisions'].values()))
        path.write_text(json.dumps({'sources': values[:1]}))
        third = self.poller(archive_paths=[path]).fetch(
            'en_morris_archive', self.archive, second.cursor, as_of=NOW, limit=1)
        self.assertEqual(third.items, [])
        self.assertEqual(set(third.cursor['archive_revisions']), {identity(values[0])})

    def test_archive_filters_foreign_author_and_handles_missing_file(self):
        path = self.root / 'archive.json'
        path.write_text(json.dumps({'sources': [row(7, handle='foreign')]}))
        result = self.poller(archive_paths=[path]).fetch('en_morris_archive', self.archive, as_of=NOW)
        self.assertEqual(result.items, [])
        self.assertEqual(result.diagnostics['excluded_non_morris_or_empty'], 1)
        with self.assertRaisesRegex(IntakeFailure, 'No configured Morris'):
            self.poller(archive_paths=[self.root / 'missing']).fetch(
                'en_morris_archive', self.archive, as_of=NOW)

    def test_x_disabled_and_cap_refusal_do_not_call_provider(self):
        fetch = Mock()
        with self.assertRaisesRegex(IntakeFailure, 'paid_x_disabled'):
            self.poller(x_fetcher=fetch).fetch('zh_macro', self.sub_x, as_of=NOW)
        from ml import budget
        with patch.object(budget, 'reserve', side_effect=budget.BudgetExceeded('cap')):
            with self.assertRaises(IntakeFailure) as error:
                self.poller(x_fetcher=fetch, allow_paid_x=True).fetch('zh_macro', self.sub_x, as_of=NOW)
        self.assertEqual(error.exception.code, 'budget_exceeded')
        fetch.assert_not_called()

    def test_x_failure_keeps_unknown_paid_reservation(self):
        from ml import budget
        with patch.object(budget, 'reserve') as reserve, patch.object(budget, 'settle') as settle:
            with self.assertRaises(IntakeFailure) as error:
                self.poller(x_fetcher=Mock(side_effect=RuntimeError('provider secret detail')),
                            allow_paid_x=True).fetch('zh_macro', self.sub_x, as_of=NOW)
        self.assertEqual(error.exception.code, 'x_provider_failed')
        self.assertNotIn('secret', str(error.exception))
        reserve.assert_called_once()
        self.assertNotIn('overhead_actual_usd', settle.call_args.kwargs)

    def test_x_backlog_is_drained_from_saved_capture_without_new_paid_call(self):
        from ml import budget
        rows = [row(i, '2026-09-29T10:00:00Z', 'writer') for i in (1, 2, 3)]
        fetch = Mock(return_value={'rows': rows, 'billed_usd': .0012})
        poller = self.poller(x_fetcher=fetch, allow_paid_x=True)
        cursor = {'query_day': '2026-09-29'}
        with patch.object(budget, 'reserve'), patch.object(budget, 'settle'):
            first = poller.fetch('zh_macro', self.sub_x, cursor, as_of=NOW, limit=1)
            second = poller.fetch('zh_macro', self.sub_x, first.cursor, as_of=NOW, limit=2)
        self.assertEqual(first.cursor['query_day'], '2026-09-29')
        self.assertEqual(second.cursor['query_day'], '2026-09-30')
        self.assertEqual([r['post_id'] for r in second.items], ['2', '3'])
        self.assertTrue(second.diagnostics['cached_backlog'])
        self.assertIsNone(second.cursor['pending_capture'])
        fetch.assert_called_once()

    def test_x_saturation_does_not_advance_or_repeat_paid_calls(self):
        from ml import budget
        rows = [row(i, '2026-09-29T10:00:00Z', 'writer') for i in range(200)]
        fetch = Mock(return_value={'rows': rows, 'billed_usd': .08})
        poller = self.poller(x_fetcher=fetch, allow_paid_x=True)
        with patch.object(budget, 'reserve'), patch.object(budget, 'settle'):
            first = poller.fetch('zh_macro', self.sub_x, {'query_day': '2026-09-29'}, as_of=NOW, limit=200)
            second = poller.fetch('zh_macro', self.sub_x, first.cursor, as_of=NOW, limit=200)
        self.assertFalse(first.complete)
        self.assertEqual(second.cursor['query_day'], '2026-09-29')
        self.assertEqual(second.diagnostics['status'], 'coverage_gap_saturated')
        self.assertEqual(second.items, [])
        fetch.assert_called_once()

    def test_x_ignores_provider_rows_from_other_authors(self):
        from ml import budget
        fetch = Mock(return_value={'rows': [row(1, handle='foreign'), row(2, handle='writer')], 'billed_usd': .001})
        with patch.object(budget, 'reserve'), patch.object(budget, 'settle'):
            result = self.poller(x_fetcher=fetch, allow_paid_x=True).fetch(
                'zh_macro', self.sub_x, {'query_day': '2026-10-01'}, as_of=NOW)
        self.assertEqual([r['post_id'] for r in result.items], ['2'])
        self.assertEqual(result.diagnostics['rejected_author'], 1)
        self.assertTrue(result.complete)

    def test_x_identity_ignores_url_user_and_tracking(self):
        self.assertEqual(identity({'url': 'https://twitter.com/i/status/123?s=20'}),
                         identity({'url': 'https://x.com/Morris_LT/status/123'}))
        self.assertEqual(identity({'url': 'https://writer.example/post/?utm_source=reader#x'}),
                         'https://writer.example/post')


class FeedAuthorshipTest(unittest.TestCase):
    def parse(self, xml):
        from live.analysis_corpus import fetch_feed
        reply = Mock(returncode=0, stdout=xml)
        with patch('live.analysis_corpus.subprocess.run', return_value=reply):
            rows, error = fetch_feed({'id': 'publication', 'author': 'Publisher Desk',
                                      'url': 'https://writer.example/feed'})
        self.assertIsNone(error)
        return rows[0]

    def rss(self, byline=''):
        return ('<rss xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>'
                '<title>Employment</title><link>https://writer.example/article</link>' + byline +
                '<content:encoded><![CDATA[<p>Alice Example</p><p>The employment details.</p>]]>'
                '</content:encoded></item></channel></rss>')

    def test_rss_creator_preserves_article_author_and_publisher_separately(self):
        value = self.parse(self.rss('<dc:creator>Alice Example and Bob Example</dc:creator>'))
        self.assertEqual(value['author_name'], 'Alice Example and Bob Example')
        self.assertEqual(value['author'], value['author_name'])
        self.assertEqual(value['publisher_name'], 'Publisher Desk')
        self.assertEqual(value['author_basis'], 'feed_creator')
        from live.distillation_source import source_record
        persisted = source_record(value)
        self.assertEqual(persisted['author_name'], 'Alice Example and Bob Example')
        self.assertEqual(persisted['context_items'][0]['publisher_name'], 'Publisher Desk')
        self.assertEqual(value['original_text'], 'Alice Example\n\n\n\nThe employment details.')

    def test_missing_creator_is_explicit_publisher_fallback_not_prose_guess(self):
        value = self.parse(self.rss())
        self.assertEqual(value['author_name'], 'Publisher Desk')
        self.assertEqual(value['author_basis'], 'publisher_fallback_no_article_author')
        self.assertEqual(value['context_items'][0]['identity_scope'], 'publisher_only')

    def test_atom_named_author_does_not_concatenate_email_or_uri(self):
        value = self.parse('<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            '<title>Employment</title><link href="https://writer.example/article"/>'
            '<author><name>Alice Example</name><email>alice@example.com</email></author>'
            '<content type="html">&lt;p&gt;The employment details.&lt;/p&gt;</content>'
            '</entry></feed>')
        self.assertEqual(value['author_name'], 'Alice Example')
        self.assertEqual(value['author_basis'], 'feed_author')
        self.assertNotIn('alice@example.com', value['author_name'])


if __name__ == '__main__':
    unittest.main()
