"""P0-3e2 acceptance: thread_id aggregates context but never deduplicates posts."""
import json
from tempfile import TemporaryDirectory
import unittest

from live.account_monitor import State
from live.source_identity import aliases

AT = '2026-10-01T12:00:00+00:00'


class ThreadIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(self.tmp.name)

    def enqueue(self, row):
        return self.state.enqueue('zh_industry', 'x_writer', row, AT)

    def test_thread_id_is_not_an_alias(self):
        row = {'url': 'https://x.com/w/status/1', 'original_text': 'A.', 'thread_id': '100'}
        self.assertFalse(any(k.startswith('thread:') for k in aliases(row)))

    def test_two_posts_same_conversation_are_two_items(self):
        a, dup_a = self.enqueue({'url': 'https://x.com/w/status/101', 'original_text': 'First.', 'thread_id': '100'})
        b, dup_b = self.enqueue({'url': 'https://x.com/w/status/102', 'original_text': 'Second.', 'thread_id': '100'})
        self.assertNotEqual(a, b)
        self.assertFalse(dup_a or dup_b)

    def test_same_post_twice_is_one_item(self):
        row = {'url': 'https://x.com/w/status/101', 'original_text': 'First.', 'thread_id': '100'}
        a, _ = self.enqueue(row)
        self.assertEqual(self.enqueue(row), (a, True))

    def _legacy_merge(self):
        """Recreate a pre-P0 database where a thread alias merged two posts."""
        first = {'url': 'https://x.com/w/status/201', 'original_text': 'Own argument one.', 'thread_id': 't'}
        second = {'url': 'https://x.com/w/status/202', 'original_text': 'Own argument two.', 'thread_id': 't'}
        a, _ = self.enqueue(first)
        b, _ = self.enqueue(second)
        with self.state.db() as db:
            db.execute('INSERT OR IGNORE INTO identities VALUES (?,?,?)', ('zh_industry', 'thread:t', a))
            db.execute('UPDATE identities SET item_id=? WHERE account=? AND item_id=?', (a, 'zh_industry', b))
            db.execute("UPDATE items SET status='duplicate',failure=? WHERE id=?", ('duplicate_of:' + a, b))
        return a, b, second

    def test_migration_unmerges_thread_only_duplicates(self):
        a, b, second = self._legacy_merge()
        report = self.state.migrate_thread_aliases()
        self.assertEqual(report['unmerged'], [b])
        self.assertEqual(report['removed_aliases'], 1)
        items = {r['id']: r for r in self.state.rows('items')}
        self.assertEqual(items[b]['status'], 'pending')
        self.assertEqual(self.enqueue(second), (b, True))
        # idempotent
        self.assertEqual(self.state.migrate_thread_aliases(), {'removed_aliases': 0, 'unmerged': []})

    def test_migration_keeps_true_duplicates(self):
        row = {'url': 'https://x.com/w/status/301', 'original_text': 'Same post.', 'thread_id': 't3'}
        a, _ = self.enqueue(row)
        other = {**row, 'original_text': 'Same post, edited.'}
        b, _ = self.enqueue({'url': 'https://x.com/w/status/399', 'original_text': 'Unrelated.'})
        with self.state.db() as db:  # b merged into a by a shared URL alias, not by thread
            db.execute('INSERT OR REPLACE INTO identities VALUES (?,?,?)',
                       ('zh_industry', 'url:https://x.com/i/status/399', a))
            db.execute('UPDATE identities SET item_id=? WHERE account=? AND item_id=?', (a, 'zh_industry', b))
            db.execute("UPDATE items SET status='duplicate',failure=?,row_json=? WHERE id=?",
                       ('duplicate_of:' + a, json.dumps({**other, 'url': row['url']}), b))
        self.assertEqual(self.state.migrate_thread_aliases()['unmerged'], [])


if __name__ == '__main__':
    unittest.main()
