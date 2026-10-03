"""Official context must be useful without becoming content or verified facts."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from live.monitor_intake import IntakeFailure, Poller
from live.source_context import ContextStore, collect_official

NOW = '2026-10-02T08:00:00Z'
URL = 'https://official.example/releases/1'


def document(url=URL, text=None):
    return {'url': url, 'content_type': 'text/html', 'fetched_at': NOW,
            'raw': '<article><h1>Employment release</h1><p>' + (text or 'Employment increased by 100,000. The previous month was revised. ' * 3) + '</p></article>'}


class OfficialContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sub = {'source_id': 'primary_test', 'role': 'CORE', 'enabled': True}
        self.config = {'adapter': 'official', 'content_role': 'context_only',
                       'feed_url': 'https://official.example/feed', 'allowed_hosts': ['official.example'],
                       'max_documents_per_poll': 2}
        self.catalog = {'primary_test': self.config}
        self.worlds = {'macro': {'subscriptions': [self.sub]}, 'industry': {'subscriptions': []}}
        self.store = ContextStore(self.root / 'store', catalog=self.catalog, universe_loader=self.worlds.__getitem__)

    def feed(self, urls=(URL,)):
        return {'url': self.config['feed_url'], 'content_type': 'text/xml', 'fetched_at': NOW,
                'raw': '<rss><channel>' + ''.join('<item><title>Employment</title><link>' + url + '</link><pubDate>Thu, 01 Oct 2026 08:00:00 GMT</pubDate></item>' for url in urls) + '</channel></rss>'}

    def poller(self, fetch):
        return Poller(self.root / 'raw', catalog=self.catalog, universe_loader=self.worlds.__getitem__, official_fetcher=fetch)

    def test_official_poll_persists_context_never_candidates_and_restart_dedups(self):
        fetch = Mock(side_effect=[self.feed(), document()])
        first = self.poller(fetch).fetch('macro', self.sub, as_of=NOW)
        self.assertEqual(first.items, [])
        self.assertEqual(len(first.context_items), 1)
        self.assertTrue(first.complete)
        row = first.context_items[0]
        self.assertTrue(Path(row['raw_import_ref']).is_file())
        self.assertEqual(row['verification_status'], 'captured_not_fact_verified')
        self.assertEqual(self.store.record('macro', 'primary_test', first.context_items, NOW)['new'], 1)
        fetch = Mock(return_value=self.feed())
        second = self.poller(fetch).fetch('macro', self.sub, json.loads(json.dumps(first.cursor)), as_of=NOW)
        self.assertEqual(second.context_items, [])
        self.assertEqual(fetch.call_count, 1)
        reopened = ContextStore(self.store.root, catalog=self.catalog, universe_loader=self.worlds.__getitem__)
        self.assertEqual(reopened.status('macro')['sources'][0]['revision_count'], 1)

    def test_exact_citation_and_account_scope_not_topic_broadcast(self):
        result = self.poller(Mock(side_effect=[self.feed(), document()])).fetch('macro', self.sub, as_of=NOW)
        self.store.record('macro', 'primary_test', result.context_items, NOW)
        self.assertEqual(self.store.references('macro', {'original_text': 'Employment increased; official release exists.'}, NOW), [])
        linked = {'original_text': 'Employment data ' + URL + '?utm_source=test'}
        refs = self.store.references('macro', linked, NOW)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['relationship'], 'exact_url_cited_by_candidate')
        self.assertEqual(self.store.references('industry', linked, NOW), [])
        with self.assertRaisesRegex(ValueError, 'outside account'):
            self.store.record('industry', 'primary_test', result.context_items, NOW)
        self.assertEqual(self.store.references('macro', linked, '2026-10-01T00:00:00Z'), [])

    def test_same_url_revision_retains_old_snapshot_and_never_upgrades_verified(self):
        first = self.poller(Mock(side_effect=[self.feed(), document()])).fetch('macro', self.sub, as_of=NOW)
        self.store.record('macro', 'primary_test', first.context_items, NOW)
        prior_ref = first.context_items[0]['raw_import_ref']
        second = self.poller(Mock(side_effect=[self.feed(), document(text='Employment increased by 90,000 after revision. ' * 4)])).fetch(
            'macro', self.sub, first.cursor, as_of='2026-10-03T08:00:00Z')
        second.context_items[0]['verified'] = True
        second.context_items[0]['verification_status'] = 'verified'
        self.store.record('macro', 'primary_test', second.context_items, '2026-10-03T08:00:00Z')
        refs = self.store.references('macro', {'external_links': [{'url': URL}]}, '2026-10-03T08:00:00Z')
        self.assertIn('90,000', refs[0]['original_text'])
        self.assertEqual(refs[0]['verification_status'], 'captured_not_fact_verified')
        self.assertNotIn('verified', refs[0])
        self.assertTrue(Path(prior_ref).is_file())
        self.assertEqual(self.store.status('macro')['sources'][0]['revision_count'], 2)
        historical = self.store.references('macro', {'external_links': [URL]}, NOW)
        self.assertIn('100,000', historical[0]['original_text'])

    def test_failure_is_retryable_and_does_not_discard_other_release(self):
        fetch = Mock(side_effect=[self.feed((URL, URL + '2')), RuntimeError('unavailable'), document(URL + '2')])
        first = self.poller(fetch).fetch('macro', self.sub, as_of=NOW)
        self.assertFalse(first.complete)
        self.assertEqual(len(first.context_items), 1)
        self.assertEqual(len(first.diagnostics['failures']), 1)
        self.assertNotIn(URL, first.cursor['official_seen'])
        self.assertIn(URL + '2', first.cursor['official_seen'])
        cursor = json.loads(json.dumps(first.cursor))
        with self.assertRaises(IntakeFailure):
            self.poller(Mock(side_effect=RuntimeError('feed unavailable'))).fetch('macro', self.sub, cursor, as_of=NOW)
        self.assertEqual(cursor, first.cursor)

    def test_changed_feed_metadata_refreshes_same_url_before_daily_body_refresh(self):
        first = self.poller(Mock(side_effect=[self.feed(), document()])).fetch('macro', self.sub, as_of=NOW)
        revised_feed = self.feed()
        revised_feed['raw'] = revised_feed['raw'].replace('01 Oct 2026 08:00:00', '02 Oct 2026 08:05:00')
        fetch = Mock(side_effect=[revised_feed, document(text='The corrected employment number is 90,000. ' * 4)])
        second = self.poller(fetch).fetch('macro', self.sub, first.cursor, as_of='2026-10-02T08:10:00Z')
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('90,000', second.context_items[0]['original_text'])
        self.assertNotEqual(first.cursor['official_seen'][URL]['index_signature'],
                            second.cursor['official_seen'][URL]['index_signature'])

    def test_return_to_prior_body_is_latest_without_rewriting_historical_view(self):
        first = self.poller(Mock(side_effect=[self.feed(), document()])).fetch('macro', self.sub, as_of=NOW)
        row_a = first.context_items[0]
        self.store.record('macro', 'primary_test', [row_a], NOW)
        row_b = {**row_a, 'original_text': 'Employment increased by 90,000.', 'fetched_at': '2026-10-03T08:00:00Z'}
        row_b['source_hash'] = hashlib.sha256(row_b['original_text'].encode()).hexdigest()
        self.store.record('macro', 'primary_test', [row_b], '2026-10-03T08:00:00Z')
        third = {**row_a, 'fetched_at': '2026-10-04T08:00:00Z', 'raw_import_ref': 'new-observation-of-A'}
        self.assertEqual(self.store.record('macro', 'primary_test', [third], '2026-10-04T08:00:00Z')['duplicate'], 1)
        link = {'external_links': [URL]}
        self.assertIn('100,000', self.store.references('macro', link, NOW)[0]['original_text'])
        self.assertIn('90,000', self.store.references('macro', link, '2026-10-03T08:00:00Z')[0]['original_text'])
        latest = self.store.references('macro', link, '2026-10-04T08:00:00Z')[0]
        self.assertIn('100,000', latest['original_text'])
        self.assertEqual(latest['raw_import_ref'], 'new-observation-of-A')

    def test_index_explicit_document_pattern_and_outside_host_are_bounded(self):
        config = {**self.config, 'index_url': 'https://official.example/news',
                  'document_path_patterns': ['/releases/[0-9]+']}
        config.pop('feed_url')
        index = {'url': config['index_url'], 'content_type': 'text/html', 'fetched_at': NOW,
                 'raw': '<a href="/releases/1">Release</a><a href="/subscribe">Subscribe</a><a href="https://foreign.example/releases/2">Other</a>'}
        fetch = Mock(side_effect=[index, document()])
        rows, cursor, complete, info = collect_official('macro', 'primary_test', config, {}, NOW, 5, self.root, fetch)
        self.assertEqual(len(rows), 1)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(info['outside_publisher_skipped'], 1)
        self.assertIsNone(rows[0]['published_at'])

    def test_store_rejects_wrong_publisher_identity_and_body_hash(self):
        rows = self.poller(Mock(side_effect=[self.feed(), document()])).fetch('macro', self.sub, as_of=NOW).context_items
        for overrides in ({'account_id': 'industry'}, {'source_id': 'primary_other'},
                          {'url': 'https://foreign.example/release'}, {'source_hash': 'not-the-hash'}):
            with self.assertRaises(ValueError):
                self.store.record('macro', 'primary_test', [{**rows[0], **overrides}], NOW)
        self.assertEqual(self.store.status('macro')['sources'], [])

    def test_cursor_prunes_departed_feed_urls(self):
        first = self.poller(Mock(side_effect=[self.feed(), document()])).fetch('macro', self.sub, as_of=NOW)
        second = self.poller(Mock(side_effect=[self.feed((URL + '2',)), document(URL + '2')])).fetch(
            'macro', self.sub, first.cursor, as_of=NOW)
        self.assertEqual(list(second.cursor['official_seen']), [URL + '2'])


if __name__ == '__main__':
    unittest.main()
