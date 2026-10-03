"""P0-4b: post_type / persona / licence registry schema.

Required fields, legal ranges, every frame and post_type reference resolves,
every owned account resolves to a PersonaSpec. Persona voices are drafts
(D2 pending) and must not be publishable."""
import copy
import json
import unittest

from live import registry


class PostTypeSchemaTests(unittest.TestCase):
    def setUp(self):
        self.table = registry.load_post_types()

    def test_five_post_types_with_ranges_frames_and_tiers(self):
        self.assertEqual(sorted(self.table['post_types']), sorted(
            ['data_take', 'mechanism_explainer', 'view_relay', 'earnings_take', 'aphorism_translation']))
        for name, spec in self.table['post_types'].items():
            lo, hi = spec['length']['min'], spec['length']['max']
            if spec['length'].get('follows_source'):
                self.assertIsNone(lo); self.assertIsNone(hi)
            else:
                self.assertTrue(0 < lo < hi, name)
            self.assertIn(spec['frame'], self.table['frames'], name)
            self.assertTrue(set(spec['licence_tiers']) <= set(registry.LICENCE_TIERS), name)
            self.assertNotIn('D', spec['licence_tiers'], name)

    def test_aphorism_translation_has_no_frame_and_source_voice(self):
        spec = self.table['post_types']['aphorism_translation']
        self.assertEqual(spec['frame'], 'none')
        self.assertEqual(spec['voice'], 'source')
        self.assertTrue(spec['length']['follows_source'])

    def test_frames_name_speaker_or_publisher(self):
        for name, frame in self.table['frames'].items():
            if name == 'none':
                self.assertEqual(frame['placement'], 'none')
                continue
            self.assertIn(frame['placement'], ('lead', 'footer'))
            self.assertTrue(any(k in frame['template'] for k in ('{speaker}', '{publisher}')), name)

    def test_invalid_range_and_dangling_frame_are_rejected(self):
        bad = copy.deepcopy(self.table)
        bad['post_types']['data_take']['length'] = {'min': 400, 'max': 150, 'unit': 'zh_chars'}
        with self.assertRaises(ValueError):
            registry.validate_post_types(bad)
        bad = copy.deepcopy(self.table)
        bad['post_types']['data_take']['frame'] = 'missing'
        with self.assertRaises(ValueError):
            registry.validate_post_types(bad)
        bad = copy.deepcopy(self.table)
        bad['post_types']['data_take']['licence_tiers'] = ['A', 'D']
        with self.assertRaises(ValueError):
            registry.validate_post_types(bad)


class PersonaSchemaTests(unittest.TestCase):
    def test_every_owned_account_resolves_to_persona(self):
        accounts = json.loads(registry.OWNED.read_text())['accounts']
        for account in accounts:
            spec = registry.persona_for_account(account['id'])
            self.assertEqual(spec.account_id, account['id'])
            self.assertEqual(spec.lang, account['language'])
            self.assertTrue(spec.post_type_mix)

    def test_voices_are_drafts_and_not_publishable(self):
        for spec in registry.load_personas().values():
            self.assertTrue(spec.voice.get('draft'), spec.persona_id)
            self.assertFalse(spec.publishable, spec.persona_id)

    def test_morris_is_aphorism_translation_only(self):
        spec = registry.persona_for_account('en_morris_archive')
        self.assertEqual(spec.post_type_mix, {'aphorism_translation': 1.0})

    def test_post_type_mix_references_exist_and_sum_to_one(self):
        types = registry.load_post_types()['post_types']
        for spec in registry.load_personas().values():
            self.assertTrue(set(spec.post_type_mix) <= set(types))
            self.assertAlmostEqual(sum(spec.post_type_mix.values()), 1.0)

    def _raw(self, persona_id):
        return json.loads((registry.PERSONAS / f'{persona_id}.json').read_text())

    def test_missing_exemplars_rejected_for_persona_voice_types(self):
        raw = self._raw('zh_macro')
        raw.pop('exemplar_accounts')
        with self.assertRaises(ValueError):
            registry.validate_persona(raw, registry.load_post_types())
        raw = self._raw('zh_macro')
        raw['exemplar_accounts'] = []
        with self.assertRaises(ValueError):
            registry.validate_persona(raw, registry.load_post_types())

    def test_approved_persona_needs_five_exemplars_each_le_035(self):
        raw = self._raw('zh_macro')
        raw['status'] = 'approved'
        raw['voice']['draft'] = False
        with self.assertRaises(ValueError):  # migrated donors: 3 accounts, weights 0.5
            registry.validate_persona(raw, registry.load_post_types())
        raw['exemplar_accounts'] = [{'handle': f'h{i}', 'weight': 0.2, 'use': ['voice']} for i in range(5)]
        registry.validate_persona(raw, registry.load_post_types())

    def test_banned_must_cover_claimed_positions(self):
        raw = self._raw('zh_industry')
        raw['banned'] = []
        with self.assertRaises(ValueError):
            registry.validate_persona(raw, registry.load_post_types())


class LicenceTierTests(unittest.TestCase):
    def test_every_subscribed_source_has_a_tier(self):
        universes = json.loads(registry.UNIVERSES.read_text())['accounts']
        for account in universes:
            for sub in account['subscriptions']:
                self.assertIn(registry.source_licence_tier(sub['source_id']), registry.LICENCE_TIERS)

    def test_unknown_source_has_no_tier(self):
        self.assertIsNone(registry.source_licence_tier('not_a_source'))

    def test_post_types_allowed_for_tier(self):
        self.assertIn('aphorism_translation', registry.post_types_for_tier('A'))
        self.assertNotIn('aphorism_translation', registry.post_types_for_tier('B'))
        self.assertEqual(registry.post_types_for_tier('D'), [])
        self.assertEqual(registry.post_types_for_tier('C'), [])


if __name__ == '__main__':
    unittest.main()
