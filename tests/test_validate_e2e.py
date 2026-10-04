"""Offline end-to-end retrieval and integrity checks on a tiny JSONL store."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from live.content_store import ContentStore
from live.retrieval import units_for_persona
from scripts.validate_e2e import validate_store, render_markdown, main


def row(uid, statement='Inflation rose 4.2%.', personas=(), date='2026-10-01', adapter='bls_api'):
    return {'unit_id': uid, 'licence_tier': 'A', 'personas': list(personas),
            'attribution': {'publisher': 'Original Bank', 'speaker': 'Original Bank'},
            'source': {'source_id': 'primary', 'id': uid, 'url': 'https://example.invalid/source',
                       'published_at': date, 'source_hash': 'hash', 'adapter': adapter,
                       'publisher': 'Original Bank'},
            'unit': {'unit_id': uid, 'licence_tier': 'A', 'statement': statement,
                     'source_spans': [{'exact_text': statement}],
                     'numbers': [{'text': '4.2%', 'metric': 'inflation', 'period': None, 'span_ref': 0}]}}


class FakeJev:
    def __init__(self, verdicts=None, fail=None):
        self.verdicts = verdicts or {}
        self.fail = fail or (lambda q, n: False)
        self.calls = []

    def review(self, state, questions):
        self.calls.append((state, copy.deepcopy(questions)))
        if self.fail(questions, len(self.calls)):
            raise RuntimeError('fake failure')
        return {'status': 'completed', 'answers': {
            uid: {'choice': self.verdicts.get(uid, 'relevant'), 'confidence': 0.9}
            for uid in questions}}


class E2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def store(self, rows):
        (self.root / 'units.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return ContentStore(self.root)

    def test_routing_hits_recency_limit_and_no_mutation(self):
        rows = [row('older', 'Inflation rose 4.2%.'),
                row('newer', 'Inflation rose 4.2%.', date='2026-10-02'),
                row('hits', 'Fed inflation rate rose 4.2%.', date='2026-09-01'),
                row('routed', 'Unrelated 4.2%.', ['macro_rates_en'], '2026-08-01'),
                row('irrelevant', 'Unrelated 4.2%.')]
        rows[-1]['unit']['numbers'][0]['metric'] = 'unrelated'
        store = self.store(rows)
        served = units_for_persona(store, 'macro_rates_en', mode='legacy')
        self.assertEqual([r['unit_id'] for r in served], ['routed', 'hits', 'newer', 'older'])
        self.assertEqual([r['match'] for r in served], ['routed', 'keyword', 'keyword', 'keyword'])
        self.assertEqual(len(units_for_persona(store, 'macro_rates_en', limit=2, mode='legacy')), 2)
        self.assertTrue(all('match' not in r for r in store.units()))

    def test_chinese_and_english_reuse_and_metric_only_match(self):
        rows = [row('en'), row('zh', '美联储通胀 4.2%。'), row('metric', 'Value 4.2%.')]
        rows[2]['unit']['numbers'][0]['metric'] = 'payroll'
        store = self.store(rows)
        self.assertEqual(len(units_for_persona(store, 'macro_zh', mode='legacy')), 3)

    def test_as_of_and_age(self):
        store = self.store([row('old', date='2026-09-01'), row('current'), row('future', date='2026-10-03')])
        self.assertEqual([r['unit_id'] for r in units_for_persona(
            store, 'macro_rates_en', as_of='2026-10-02', max_age_days=2, mode='legacy')], ['current'])
        with self.assertRaises(ValueError):
            units_for_persona(store, 'macro_rates_en', max_age_days=-1, mode='legacy')

    def test_integrity_duplicate_and_reportgem_checks(self):
        good = row('good', adapter='reportgem')
        good['source']['url'] = None  # adapter + report id is offline provenance
        bad = copy.deepcopy(good)
        bad['unit_id'] = bad['unit']['unit_id'] = 'bad'
        bad['licence_tier'] = bad['unit']['licence_tier'] = 'C'
        bad['attribution'] = {'publisher': 'ReportGem'}
        bad['source']['source_hash'] = None
        bad['unit']['numbers'][0].pop('period')
        bad['unit']['statement'] += ' Price Target $100'
        result = validate_store(self.store([good, bad, good]), minimum=1, mode='legacy')
        checks = result['global_checks']
        for name in ('non_writable_tiers', 'broken_bindings', 'missing_provenance',
                     'reportgem_attributed_to_reportgem', 'ratings_targets', 'duplicate_unit_ids'):
            self.assertTrue(checks[name], name)
        self.assertEqual(result['personas']['macro_rates_en']['status'], 'FAIL')
        self.assertEqual(result['personas']['macro_rates_en']['total_served'], 2)

    def test_bad_span_text_metric_and_ref(self):
        for change in ({'text': '9%'}, {'span_ref': True}, {'metric': 'revenue'}, {'metric': ''}):
            with self.subTest(change=change):
                r = row('bad', 'Policy rate rose 4.2%.')
                r['unit']['numbers'][0].update(change)
                self.assertTrue(validate_store(self.store([r]), minimum=1)['global_checks']['broken_bindings'])

    def test_missing_attribution_provenance_and_invalid_period(self):
        r = row('bad')
        r['attribution'] = {}
        r['source']['url'] = None
        r['source']['id'] = None
        r['unit']['numbers'][0]['period'] = 2026
        checks = validate_store(self.store([r]), minimum=1)['global_checks']
        for name in ('missing_attribution', 'missing_provenance', 'broken_bindings'):
            self.assertTrue(checks[name], name)

    def test_valid_store_passes_served_persona(self):
        report = validate_store(self.store([row('good')]), minimum=1, mode='legacy')
        self.assertEqual(report['personas']['macro_rates_en']['status'], 'PASS')
        self.assertFalse(any(report['global_checks'].values()))

    def test_jev_questions_batches_and_limit(self):
        from live.retrieval import judge_relevance
        rows = [row(str(i), 'x' * 500) for i in range(19)]
        rows[0]['unit']['kind'] = 'view'
        fake = FakeJev()
        result = judge_relevance({'macro_rates_en': rows, 'macro_zh': rows[:1]}, jev=fake)
        self.assertEqual([len(q) for _, q in fake.calls], [16, 3, 1])
        question = fake.calls[0][1]['0']
        self.assertEqual(question['type'], 'choice')
        self.assertEqual(set(question['criteria']), {'relevant', 'tangential', 'irrelevant'})
        for text in ('English macro:', 'view', 'Original Bank', 'x' * 400):
            self.assertIn(text, question['instructions'])
        self.assertNotIn('x' * 401, question['instructions'])
        self.assertEqual(result['macro_rates_en']['0'],
                         {'verdict': 'relevant', 'confidence': 0.9, 'jev_fallback': False})
        limited = judge_relevance({'macro_rates_en': rows}, jev=FakeJev(), per_persona=1)
        self.assertEqual(limited['macro_rates_en']['1']['verdict'], 'unjudged')
        self.assertEqual(len(limited['macro_rates_en']), 19)

    def test_jev_retry_split_and_unjudged(self):
        from live.retrieval import judge_relevance
        rows = [row('good'), row('bad')]
        fake = FakeJev(fail=lambda q, n: len(q) > 1 or 'bad' in q)
        result = judge_relevance({'macro_rates_en': rows}, jev=fake)['macro_rates_en']
        self.assertEqual([len(q) for _, q in fake.calls], [2, 2, 1, 1, 1])
        self.assertEqual(result['good']['verdict'], 'relevant')
        self.assertEqual(result['bad'], {'verdict': 'unjudged', 'confidence': None, 'jev_fallback': True})
        retry = FakeJev(fail=lambda q, n: n == 1)
        self.assertEqual(judge_relevance({'macro_rates_en': rows}, jev=retry)
                         ['macro_rates_en']['good']['verdict'], 'relevant')
        self.assertEqual(len(retry.calls), 2)

    def test_jev_counts_examples_and_integrity(self):
        rows = [row(uid, 'Inflation ' + 'x' * 200 + ' 4.2%.')
                for uid in ('yes', 'stretch', 'no', 'unknown')]
        fake = FakeJev({'yes': 'relevant', 'stretch': 'tangential', 'no': 'irrelevant', 'unknown': 'invalid'})
        report = validate_store(self.store(rows), minimum=2, jev=fake, mode='legacy')
        persona = report['personas']['macro_rates_en']
        for label in ('relevant', 'tangential', 'irrelevant', 'unjudged'):
            self.assertEqual(persona[label], 1)
        self.assertEqual(persona['status'], 'FAIL')
        self.assertEqual(len(persona['relevant_examples'][0]), 160)
        self.assertEqual(len(persona['irrelevant_examples']), 1)
        self.assertIn('| Relevant | Tangential | Irrelevant | Unjudged |', render_markdown(report))
        self.assertIn(persona['irrelevant_examples'][0], render_markdown(report))
        self.assertEqual(validate_store(self.store(rows), minimum=1, jev=fake, mode='legacy')
                         ['personas']['macro_rates_en']['status'], 'PASS')
        rows[0]['attribution'] = {}
        self.assertEqual(validate_store(self.store(rows), minimum=1, jev=fake, mode='legacy')
                         ['personas']['macro_rates_en']['status'], 'FAIL')

    def test_jev_failure_never_counts_as_relevant_and_examples_are_bounded(self):
        rows = [row(str(i)) for i in range(5)]
        store = self.store(rows)
        offline = validate_store(store, minimum=1, mode='legacy')
        self.assertNotIn('relevant', offline['personas']['macro_rates_en'])
        self.assertNotIn('| Relevant |', render_markdown(offline))
        failed = validate_store(store, minimum=1, jev=FakeJev(fail=lambda q, n: True), mode='legacy')
        persona = failed['personas']['macro_rates_en']
        self.assertEqual((persona['relevant'], persona['unjudged'], persona['status']), (0, 5, 'FAIL'))
        relevant = validate_store(store, minimum=1, jev=FakeJev(), mode='legacy')
        self.assertEqual(len(relevant['personas']['macro_rates_en']['relevant_examples']), 3)
        irrelevant = validate_store(store, minimum=1, jev=FakeJev({str(i): 'irrelevant' for i in range(5)}), mode='legacy')
        self.assertEqual(len(irrelevant['personas']['macro_rates_en']['irrelevant_examples']), 3)

    def test_jev_cli_log_and_budget_directory(self):
        from ml import budget
        self.store([row('yes')])
        run, out = self.root / 'jev', self.root / 'jev.json'
        with patch('live.jev_review_client.JevReviewClient', return_value=FakeJev()) as client, patch.object(budget, 'STORE'), patch.object(budget, 'LEDGER'):
            self.assertEqual(main(['--store', str(self.root), '--mode', 'legacy', '--min', '1', '--jev',
                                   '--jev-run', str(run), '--out-json', str(out)]), 0)
            client.assert_called_once_with(run)
            self.assertEqual(budget.STORE, run / 'ledger')
            self.assertEqual(budget.LEDGER, run / 'ledger' / 'spend.json')
        self.assertEqual(json.loads(out.read_text())['personas']['macro_rates_en']['relevant'], 1)

    def test_cli_reports_failure_with_zero_exit(self):
        self.store([])
        out = self.root / 'result.json'
        md = self.root / 'result.md'
        proc = subprocess.run([sys.executable, 'scripts/validate_e2e.py', '--store', str(self.root),
                               '--out-json', str(out), '--out-md', str(md)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(out.read_text())
        self.assertEqual(len(result['personas']), 10)
        self.assertTrue(all(p['status'] == 'FAIL' for p in result['personas'].values()))
        self.assertIn('| macro_rates_en |', md.read_text())


if __name__ == '__main__':
    unittest.main()
