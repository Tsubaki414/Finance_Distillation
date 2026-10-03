"""P0-3e1 acceptance: a SELECT answer of needs_source is a source state, not an
execution failure, and is not retried as a model contract error."""
import tempfile
import unittest

from live.account_source_adaptation import adapt_source, execution_failure
from test_account_source_adaptation import FakeClient, source, EN, ZH

LONG = "Industry supply needs gradual verification, and technology paths need real demand. " * 30


class SelectNeedsSource(unittest.TestCase):
    def run_with(self, selection):
        client = FakeClient('zh_industry', ZH, overrides={'selection': selection})
        with tempfile.TemporaryDirectory() as tmp:
            result = adapt_source(source(LONG + "\n\n" + EN, 'industry_writer', 'en'), 'zh_industry', tmp, client)
        return result, [s for s, _ in client.calls]

    def check(self, result, stages):
        self.assertEqual(result['draft_status'], 'needs_source', result.get('why'))
        self.assertNotEqual(result['status'], 'draft_ready')
        self.assertFalse(result.get('execution_failure'))
        self.assertFalse(execution_failure(result))
        self.assertEqual(stages.count('selection'), 1)
        self.assertNotIn('translation', stages)

    def test_needs_source_true(self):
        self.check(*self.run_with(lambda v, p: {**v, 'needs_source': True, 'paragraph_ids': [],
                                                 'reason': 'TEST DOUBLE: argument continues in a linked post'}))

    def test_dependencies_incomplete(self):
        self.check(*self.run_with(lambda v, p: {**v, 'dependencies_complete': False,
                                                 'reason': 'TEST DOUBLE: depends on an unseen chart'}))


if __name__ == '__main__':
    unittest.main()
