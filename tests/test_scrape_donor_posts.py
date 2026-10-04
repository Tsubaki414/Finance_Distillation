"""scripts/scrape_donor_posts.py: timeline parsing, cursor and merge (offline)."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('scrape', Path(__file__).parents[1] / 'scripts' / 'scrape_donor_posts.py')
scrape = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scrape)


def tweet(i, uid='1', reply_user=None, rt=False):
    legacy = {'full_text': f'post {i}', 'created_at': 'Sat Oct 03 10:00:00 +0000 2026', 'user_id_str': uid, 'lang': 'en'}
    if reply_user:
        legacy.update(in_reply_to_status_id_str='9', in_reply_to_user_id_str=reply_user)
    if rt:
        legacy['retweeted_status_result'] = {}
    return {'content': {'itemContent': {'tweet_results': {'result': {'rest_id': str(i), 'legacy': legacy}}}}}


PAGE = {'cursor': {'bottom': 'NEXT'}, 'result': {'timeline': {'instructions': [
    {'type': 'TimelineAddEntries', 'entries': [tweet(3), tweet(2, reply_user='7'), tweet(1, reply_user='1'),
                                               tweet(5, uid='99'), tweet(4, rt=True)]}]}}}


class ScrapeTests(unittest.TestCase):
    def test_parse_flags(self):
        posts = {p['id']: p for p in scrape.timeline_posts(PAGE)}
        self.assertTrue(posts['2']['reply'])
        self.assertTrue(posts['1']['self_thread'] and not posts['1']['reply'])
        self.assertTrue(posts['4']['rt'])
        self.assertEqual(scrape.bottom_cursor(PAGE), 'NEXT')

    def test_merge_dedups_and_drops_other_users(self):
        posts = scrape.merge([{'id': '3', 'uid': '1', 'rt': False, 'text': 'old'}], scrape.timeline_posts(PAGE), uid='1')
        ids = [p['id'] for p in posts]
        self.assertEqual(ids, ['4', '3', '2', '1'])
        self.assertEqual(posts[1]['text'], 'old')


if __name__ == '__main__':
    unittest.main()
