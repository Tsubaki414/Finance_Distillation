import json
import tempfile
import unittest
from pathlib import Path
from live import voice_cards as vc


def corpus():
    posts = {h: [{'id': h + str(i), 'text': f'{h} observation {i}: margins improved while demand stayed flat. Evidence deserves a measured conclusion.'} for i in range(12)] for h in ('alpha', 'beta', 'gamma')}
    tags = {h: {p['id']: {'post_type': ('data_take', 'opinion')[i % 2]} for i, p in enumerate(rows)} for h, rows in posts.items()}
    cluster = {'lang': 'en', 'donors': [{'handle': h, 'weight': w} for h, w in zip(posts, (0.6, 0.3, 0.1))]}
    return cluster, posts, tags, {'donors': {h: {} for h in posts}}


def answer(sample):
    ids = [p['id'] for p in sample]
    return {'voice_summary': 'Measured claims follow observable changes. Conclusions distinguish demand from margins.',
            'hook_patterns': [{'pattern': f'Observed change opener {i}', 'share_estimate': 0.25, 'example_ids': [ids[i]]} for i in range(3)],
            'cadence_notes': 'Short opening, then qualification.',
            'signature_moves': [{'move': 'Pair an observation with a limiting condition', 'example_ids': [ids[0]]}],
            'do': [{'rule': f'Compare margin and demand dimension {i}', 'evidence_ids': [ids[i], ids[i+4]]} for i in range(4)],
            'dont': [{'rule': f'Avoid unsupported inference {i}', 'evidence_ids': []} for i in range(3)],
            'data_opinion_note': 'Numbers support a qualified view.'}


class SamplingTests(unittest.TestCase):
    def test_diverse_weighted_capped_deterministic_originals(self):
        cluster, posts, tags, roster = corpus()
        for flags in ({'reply': True}, {'rt': True}, {'pinned': True}, {'is_promotion': True}, {}):
            posts['alpha'].append({'id': str(flags), 'text': 'tiny' if not flags else 'Excluded observation ' * 5, **flags})
        sample = vc.sample_for_cluster(cluster, posts, tags, roster, n=10, per_donor=4, seed=17)
        self.assertEqual(sample, vc.sample_for_cluster(cluster, posts, tags, roster, n=10, per_donor=4, seed=17))
        counts = {h: sum(p['handle'] == h for p in sample) for h in posts}
        self.assertEqual(len(sample), 10)
        self.assertEqual(counts['alpha'], 4)
        self.assertGreaterEqual(counts['beta'], counts['gamma'])
        self.assertTrue(all(0 < v <= 4 for v in counts.values()))
        self.assertTrue(all(p['id'][0] in 'abg' for p in sample))
        for h in posts:
            self.assertEqual({p['post_type'] for p in sample if p['handle'] == h}, {'data_take', 'opinion'})

    def test_all_hook_categories(self):
        examples = {'42 basis points': 'number-led headline', '$NVDA margins': 'ticker-led', 'Apple margins improved': 'ticker-led', 'Growth rose but margins fell': 'contrast/turn', '需求增长，但利润下滑': 'contrast/turn', '1/ A look at margins': 'list/thread opener', '🧵 Margins': 'list/thread opener', '一、利润': 'list/thread opener', 'BREAKING: release': 'news-wire', '突发消息': 'news-wire', '【快讯】发布': 'news-wire', 'Why now?': 'question', '🚀 Growth': 'emoji-led', '“Margins”': 'quote', 'Evidence matters': 'claim-led'}
        for line, expected in examples.items():
            with self.subTest(line=line):
                self.assertEqual(vc.hook(line), expected)


class QualitativeTests(unittest.TestCase):
    def setUp(self):
        self.cluster, posts, tags, roster = corpus()
        self.sample = vc.sample_for_cluster(self.cluster, posts, tags, roster, n=12, seed=2)
        self.sample.sort(key=lambda p: (p['handle'], p['id']))

    def test_valid_rules_attach_only_verbatim_evidence(self):
        payload = answer(self.sample)
        prompts = []
        result = vc.qualitative_card(self.cluster, {'median': 12}, self.sample, lambda p: prompts.append(p) or json.dumps(payload))
        self.assertEqual(len(prompts), 1)
        self.assertIn('median', prompts[0])
        self.assertIn(self.sample[0]['text'], prompts[0])
        self.assertEqual(result['do'][0]['evidence'][0]['text'], self.sample[0]['text'][:140])
        self.assertEqual(result['do'][0]['evidence'][1]['handle'], 'beta')

    def test_strict_validation_retry_and_failure(self):
        mutations = [lambda x: x['do'][0].update(evidence_ids=['missing', 'beta0']),
                     lambda x: x['do'][0].update(evidence_ids=['alpha0', 'alpha1']),
                     lambda x: x['do'][1].update(rule=x['do'][0]['rule']),
                     lambda x: x['dont'][0].update(evidence_ids=['alpha0']),
                     lambda x: x['dont'][1].update(evidence_ids=['alpha0']),
                     lambda x: x.update(voice_summary=42),
                     lambda x: x['hook_patterns'][0].update(share_estimate=2),
                     lambda x: x.update(extra='untrusted')]
        for mutate in mutations:
            bad = answer(self.sample)
            mutate(bad)
            # Ensure reuse test actually exceeds two rules.
            if bad['dont'][0]['evidence_ids'] or bad['dont'][1]['evidence_ids']:
                bad['dont'][0]['evidence_ids'] = ['alpha0']
                bad['dont'][1]['evidence_ids'] = ['alpha0']
            prompts = []
            result = vc.qualitative_card(self.cluster, {}, self.sample, lambda p: prompts.append(p) or json.dumps(bad))
            self.assertIn('qualitative_error', result)
            self.assertEqual(len(prompts), 2)
            self.assertIn('Validation errors', prompts[1])
        responses = iter(['not JSON', json.dumps(answer(self.sample))])
        self.assertIn('do', vc.qualitative_card(self.cluster, {}, self.sample, lambda p: next(responses)))

    def test_single_donor_and_empty_anti_pattern_allowed(self):
        sample = [dict(p, handle='solo') for p in self.sample]
        self.assertIn('do', vc.qualitative_card(self.cluster, {}, sample, lambda p: json.dumps(answer(sample))))

    def test_cli_audit_subset_and_fallback(self):
        from scripts.build_voice_cards import main
        from unittest.mock import patch
        fix = Path(__file__).parent / 'fixtures/voice'
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.build_voice_cards.subprocess.run') as run:
            run.return_value.stdout = 'invalid'
            main(['--posts-dir', str(fix/'posts'), '--tags-dir', str(fix/'tags'), '--roster', str(fix/'roster.json'), '--out', tmp, '--clusters', 'sample', '--raw-dir', tmp+'/raw', '--llm-cmd', 'fake -p', '--sample-n', '8'])
            card = json.loads((Path(tmp)/'sample.json').read_text())
            self.assertIn('qualitative_error', card)
            self.assertEqual(card['do'], card['baseline_rules']['do'])
            self.assertEqual(len(list((Path(tmp)/'raw').glob('sample*.txt'))), 2)
            self.assertEqual(run.call_args.kwargs['input'][:1], 'A')
            run.reset_mock()
            main(['--posts-dir', str(fix/'posts'), '--tags-dir', str(fix/'tags'), '--roster', str(fix/'roster.json'), '--out', tmp, '--no-llm'])
            run.assert_not_called()

    def test_build_accepts_qualitative_rules_and_preserves_baseline(self):
        from unittest.mock import patch
        fix = Path(__file__).parent / 'fixtures/voice'
        prompts = []
        def fake(name, prompt):
            prompts.append(prompt)
            return json.dumps(answer(self.sample))
        with patch.object(vc, 'sample_for_cluster', return_value=self.sample):
            card = vc.build_cards(fix/'posts', fix/'tags', fix/'roster.json', llm=fake)['sample']
        self.assertNotEqual(card['do'], card['baseline_rules']['do'])
        self.assertEqual(card['do'], card['qualitative']['do'])
        self.assertNotIn('qualitative_error', card)
        self.assertIn('post_type_mix', prompts[0])
        with tempfile.TemporaryDirectory() as tmp:
            vc.write_cards({'sample': card}, tmp)
            report = (Path(tmp)/'README.md').read_text()
            self.assertIn(card['do'][0]['rule'], report)
            self.assertIn(self.sample[0]['text'][:140], report)

    def test_summary_exposes_rules_without_snippets_or_moves(self):
        fix = Path(__file__).parent / 'fixtures/voice'
        card = vc.build_cards(fix/'posts', fix/'tags', fix/'roster.json')['sample']
        q = vc.qualitative_card(self.cluster, {}, self.sample, lambda p: json.dumps(answer(self.sample)))
        card.update(qualitative=q, do=q['do'], dont=q['dont'])
        summary = vc.compact_summary(card)
        self.assertEqual(summary['voice_summary'], q['voice_summary'])
        self.assertEqual(summary['hook_patterns'], [p['pattern'] for p in q['hook_patterns']])
        serialized = json.dumps(summary)
        self.assertNotIn(self.sample[0]['text'], serialized)
        self.assertNotIn(q['signature_moves'][0]['move'], serialized)
