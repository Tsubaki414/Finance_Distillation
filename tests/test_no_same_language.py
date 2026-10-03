"""P0-1 acceptance: same-language sources never enter the publish chain.

Same-language material may only return later as an attributed view_relay post
type. Until then it is rejected at admission with zero model calls.
"""
import json
from pathlib import Path
import tempfile
import unittest

from live.account_intelligence import Store, account
from live.account_sources import admission, ingest

ROOT = Path(__file__).resolve().parents[1]


class SameLanguageIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        base = {'content_complete': True, 'source_type': 'x', 'platform': 'x',
                'published_at': '2026-09-04T12:30:00Z', 'fetched_at': '2026-09-04T13:00:00Z'}
        # Chinese KOL subscribed by zh_macro; text carries macro topic terms.
        self.zh_on_zh = {**base, 'id': 'f-zh', 'source_id': 'x_qinbafrank', 'author_handle': 'qinbafrank',
                         'author_name': 'qinbafrank', 'url': 'https://x.com/qinbafrank/status/1',
                         'source_language': 'zh',
                         'original_text': '美联储降息预期升温，美债收益率回落，通胀与就业数据是关键。'}
        self.en_on_zh = {**base, 'id': 'f-en', 'source_id': 'overshoot', 'source_type': 'web', 'platform': 'web',
                         'url': 'https://theovershoot.co/p/employment-test', 'author_name': 'Matthew Klein',
                         'source_language': 'en',
                         'original_text': 'Employment increased by 100,000. The previous month was revised.'}

    def test_same_language_rejected_at_admission(self):
        self.assertEqual(account('zh_macro')['language'], 'zh')
        verdict = admission('zh_macro', self.zh_on_zh)
        self.assertFalse(verdict['admitted'])
        self.assertEqual(verdict.get('code'), 'same_language')

    def test_same_language_ingest_creates_no_inbox_row(self):
        result = ingest(self.store, 'zh_macro', self.zh_on_zh)
        self.assertFalse(result['admitted'])
        self.assertEqual(self.store.rows('inbox'), [])

    def test_cross_language_still_admitted(self):
        self.assertTrue(admission('zh_macro', self.en_on_zh)['admitted'])

    def test_morris_cross_language_unchanged(self):
        morris = {**self.zh_on_zh, 'source_id': 'x_Morris_LT', 'author_handle': 'Morris_LT',
                  'author_name': 'Morris_LT', 'url': 'https://x.com/Morris_LT/status/123',
                  'original_text': '先尝试，再观察反馈，再调整方向。'}
        self.assertTrue(admission('en_morris_archive', morris)['admitted'])

    def test_adaptation_does_not_rewrite_configured_languages(self):
        from live.account_source_adaptation import _account
        for aid in ('zh_macro', 'zh_industry'):
            configured = next(a for a in json.loads((ROOT / 'live/accounts.json').read_text())['accounts']
                              if a['id'] == aid)['source_preferences']['languages']
            self.assertEqual(_account(aid)['source_preferences']['languages'], configured)
            self.assertNotIn('zh', _account(aid)['source_preferences']['languages'])

    def test_adaptation_has_no_same_language_passthrough(self):
        text = (ROOT / 'live/account_source_adaptation.py').read_text()
        self.assertNotIn('same_language_original', text)

    def test_adaptation_route_refuses_same_language(self):
        from live.account_source_adaptation import AccountSourcePipeline
        from live.distillation_source import source_record
        calls = []
        pipe = AccountSourcePipeline.__new__(AccountSourcePipeline)
        from live.account_source_adaptation import _account
        acc = _account('zh_macro'); acc['lang'] = acc.get('lang') or acc['language']
        acc.setdefault('profile_version', 'test')
        pipe.accounts = [acc]
        pipe.ask = lambda *a, **k: calls.append(a) or {}
        route, _ = AccountSourcePipeline.route(pipe, source_record(self.zh_on_zh), {})
        self.assertEqual(route['decision'], 'NONE')
        self.assertEqual(calls, [])

    def test_docs_no_longer_allow_same_language_light_edit(self):
        owned = (ROOT / 'live/owned_accounts.json').read_text()
        self.assertNotIn('same-language light editing is allowed', owned)
        daily = (ROOT / 'docs/DAILY_PIPELINE.md').read_text()
        self.assertNotIn('同语言原文底稿', daily)


if __name__ == '__main__':
    unittest.main()


class MonitorRecordsRejectionCode(unittest.TestCase):
    def test_monitor_skip_records_same_language_code(self):
        text = (ROOT / 'live/account_monitor.py').read_text()
        # The skip branch must carry the admission code so same_language is countable.
        self.assertIn("'not_admitted:' + result['code']", text)
