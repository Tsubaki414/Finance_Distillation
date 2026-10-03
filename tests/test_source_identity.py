"""Strong duplicate identities, with no topic-based source broadcast or merging."""
import json
from tempfile import TemporaryDirectory
import unittest

from live.account_monitor import State
from live.source_identity import aliases, canonical_url, duplicate_run


AT = '2026-10-01T12:00:00+00:00'


class SourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(self.tmp.name)

    def enqueue(self, row, account='zh_macro', **kwargs):
        return self.state.enqueue(account, 'subscribed_author', row, AT, **kwargs)

    def test_url_aliases_ignore_tracking_but_preserve_document_parameters(self):
        self.assertEqual(canonical_url('https://mobile.twitter.com/author/status/123?s=20'),
                         canonical_url('https://x.com/i/status/123'))
        self.assertEqual(canonical_url('http://www.publisher.example/post/?utm_medium=rss&gclid=a#top'),
                         'https://publisher.example/post')
        for key in ('s', 't', 'ref', 'source'):
            with self.subTest(key=key):
                self.assertNotEqual(canonical_url(f'https://publisher.example/?{key}=a'),
                                    canonical_url(f'https://publisher.example/?{key}=b'))

    def test_same_source_and_same_thread_each_prevent_duplicate_items(self):
        first = {'url': 'https://x.com/writer/status/101', 'original_text': 'First reason.', 'thread_id': '100'}
        key, duplicate = self.enqueue(first)
        self.assertFalse(duplicate)
        updated_url = {**first, 'url': 'https://twitter.com/i/status/101?utm_source=x', 'original_text': 'Corrected first reason.'}
        self.assertEqual(self.enqueue(updated_url), (key, True))
        # P0-3e2: another post in the same conversation is an independent item.
        other_thread_part = {'url': 'https://x.com/writer/status/102', 'original_text': 'Second reason.', 'thread_id': '100'}
        other, duplicate = self.enqueue(other_thread_part)
        self.assertFalse(duplicate)
        self.assertNotEqual(other, key)
        self.assertEqual(len(self.state.rows('items')), 2)

    def test_exact_event_metadata_dedups_but_similar_topics_do_not(self):
        first = {'url': 'https://writer.example/a', 'original_text': 'NVDA revenue rose in Q2.',
                 'canonical_event_id': 'NVDA-FY2027-Q2-earnings'}
        key, _ = self.enqueue(first)
        same_event = {'url': 'https://another.example/b', 'original_text': 'A different explanation of the same release.',
                      'event_key': 'NVDA-FY2027-Q2-earnings'}
        self.assertEqual(self.enqueue(same_event), (key, True))
        different_event = {'url': 'https://writer.example/c', 'original_text': 'NVDA revenue rose in Q3.',
                           'canonical_event_id': 'NVDA-FY2027-Q3-earnings'}
        self.assertFalse(self.enqueue(different_event)[1])
        unrelated_same_topic = {'url': 'https://writer.example/d', 'original_text': 'NVDA cooling architecture constraints.'}
        self.assertFalse(self.enqueue(unrelated_same_topic)[1])

    def test_accounts_have_independent_identity_sets(self):
        source = {'url': 'https://writer.example/a', 'original_text': 'A genuinely shared source.', 'event_id': 'shared-release'}
        a, _ = self.enqueue(source, account='zh_macro')
        b, duplicate = self.enqueue(source, account='zh_industry')
        self.assertFalse(duplicate)
        self.assertNotEqual(a, b)

    def test_event_thread_bridge_merges_pending_items_and_survives_restart(self):
        first = {'url': 'https://writer.example/a', 'original_text': 'A release.', 'event_id': 'release-1'}
        second = {'url': 'https://x.com/writer/status/202', 'original_text': 'A discussion.', 'event_key': 'thread-1'}
        a, _ = self.enqueue(first)
        b, _ = self.enqueue(second)
        self.state.update(a, status='drafted')
        bridge = {'url': 'https://x.com/writer/status/203', 'original_text': 'This discussion concerns the release.',
                  'event_key': 'thread-1', 'event_id': 'release-1'}
        self.assertEqual(self.enqueue(bridge), (a, True))
        saved = {r['id']: r for r in self.state.rows('items')}
        self.assertEqual(saved[a]['status'], 'drafted')
        self.assertEqual(saved[b]['status'], 'duplicate')
        restarted = State(self.tmp.name)
        self.assertEqual(restarted.enqueue('zh_macro', 'subscribed_author', second, AT), (a, True))

    def test_recovered_body_upgrades_blocked_item_without_new_identity(self):
        preview = {'url': 'https://writer.example/a', 'original_text': 'Preview.', 'content_complete': False}
        key, _ = self.enqueue(preview, status='blocked_source')
        full = {**preview, 'original_text': 'Full body with the reasoning.', 'content_complete': True}
        self.assertEqual(self.enqueue(full), (key, False))
        saved = self.state.rows('items')[0]
        self.assertEqual(saved['status'], 'pending')
        self.assertEqual(json.loads(saved['row_json'])['original_text'], full['original_text'])

    def test_prior_dashboard_run_reuse_is_account_scoped_and_event_aware(self):
        source = {'url': 'https://writer.example/a', 'original_text': 'A source.', 'canonical_event_id': 'event-1'}
        run = {'id': 'run-1', 'pipeline': 'account_source', 'account_id': 'zh_macro',
               'status': 'machine_hold', 'candidates': [{'id': 'draft-1'}], 'event': {'source_ids': ['source-1']}}

        class SavedStore:
            def rows(self, key):
                return [run] if key == 'runs' else []

            def get(self, table, key):
                return source

        same_event = {'url': 'https://writer.example/new', 'original_text': 'Another take.', 'event_key': 'event-1'}
        self.assertEqual(duplicate_run(SavedStore(), 'zh_macro', same_event), run)
        self.assertIsNone(duplicate_run(SavedStore(), 'zh_industry', same_event))


if __name__ == '__main__':
    unittest.main()
