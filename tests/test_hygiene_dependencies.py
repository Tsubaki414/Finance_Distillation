"""P0-3d acceptance: resolved metadata is retained deterministically; open
dependencies still go to editorial judgment. All actions stay within ACTIONS."""
import tempfile
import unittest

from live import source_hygiene as hygiene
from live.account_source_adaptation import adapt_source
from test_account_source_adaptation import FakeClient, source, EN, ZH


def row(**extra):
    return {**source(EN, 'industry_writer', 'en'), **extra}


class HygieneDependencies(unittest.TestCase):
    def run_row(self, r):
        client = FakeClient('zh_industry', ZH)
        with tempfile.TemporaryDirectory() as tmp:
            result = adapt_source(r, 'zh_industry', tmp, client)
        hygiene_calls = [p for s, p in client.calls if s == 'source_hygiene']
        return result, hygiene_calls

    def decisions(self, result):
        return result['attempt'].get('hygiene_decisions', [])

    def test_thread_only_metadata_makes_no_hygiene_call(self):
        result, calls = self.run_row(row(thread_id='100', thread_post_ids=['100', '101']))
        self.assertEqual(result['status'], 'draft_ready', result.get('why'))
        self.assertEqual(calls, [])
        decisions = self.decisions(result)
        self.assertTrue(decisions)
        self.assertTrue(all(d['action'] == 'retain' and d.get('deterministic') for d in decisions))

    def test_captured_quote_is_resolved(self):
        quoted = {'post_id': '9', 'status': 'captured_nested_context', 'text': 'Their full quoted body.'}
        result, calls = self.run_row(row(thread_id='100', quoted_post=quoted))
        self.assertEqual(calls, [])

    def test_unretrieved_reply_still_judged_alone(self):
        reply = {'post_id': '12', 'author_handle': 'someone', 'status': 'not_retrieved'}
        result, calls = self.run_row(row(thread_id='100', reply_to=reply))
        self.assertEqual(len(calls), 1)
        fields = [a['metadata'].get('field') for a in calls[0]['annotations']]
        self.assertEqual(fields, ['reply_to'])
        ids = {a['id'] for a in result['attempt']['hygiene_annotations']}
        self.assertEqual({d['annotation_id'] for d in self.decisions(result)}, ids)

    def test_unretrieved_quote_still_judged(self):
        result, calls = self.run_row(row(quoted_post={'post_id': '9', 'status': 'not_retrieved'}))
        self.assertEqual(len(calls), 1)

    def test_unresolved_media_still_judged(self):
        r = row(media_dependencies=[{'kind': 'chart', 'required': None, 'status': 'uncertain_dependency',
                                     'selection_review_required': True, 'url': 'https://example.test/c.png'}])
        result, calls = self.run_row(r)
        self.assertEqual(len(calls), 1)

    def test_actions_within_contract(self):
        result, _ = self.run_row(row(thread_id='100'))
        self.assertTrue(all(d['action'] in hygiene.ACTIONS for d in self.decisions(result)))


if __name__ == '__main__':
    unittest.main()
