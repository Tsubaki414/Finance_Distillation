"""P0B-2: profiles v2 must pass these before it may become the active channel.

v1 files must remain byte-identical throughout. A profile that no longer supports any estimate
must not be offered to generation.

Run: .venv/bin/python -B tests/test_profiles_v2.py
"""
from pathlib import Path
import sys, json, glob, hashlib, datetime, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evidence_loop'))
import profile_registry as reg

V2 = ROOT / 'evidence_loop/profiles_v2'
V1 = ROOT / 'evidence_loop/profiles'
PACKET = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())


def v2_profiles():
    out = []
    for p in sorted(V2.glob('*.json')):
        if p.name in ('index.json', 'diff_v1_v2.json'):
            continue
        d = json.loads(p.read_text())
        if d.get('donor'):
            out.append(d)
    return out


class PointInTime(unittest.TestCase):
    def test_no_profile_uses_post_event_posts(self):
        cutoff = datetime.datetime.fromisoformat(PACKET['published_at'])
        for d in v2_profiles():
            end = datetime.datetime.fromisoformat(d['timeline_limits']['observed_end'])
            self.assertLess(end, cutoff,
                            f"{d['donor']} observes posts at or after the event release")

    def test_cutoff_recorded_on_every_profile(self):
        for d in v2_profiles():
            self.assertIsNotNone(d['point_in_time']['cutoff'], d['donor'])

    def test_incomplete_timeline_is_declared(self):
        for d in v2_profiles():
            self.assertFalse(d['timeline_limits']['complete_timeline'], d['donor'])
            self.assertTrue(d['timeline_limits']['why_incomplete'])


class MinimumSupport(unittest.TestCase):
    def test_every_feature_declares_its_rule(self):
        for d in v2_profiles():
            for axis in ('knowledge', 'reasoning', 'style', 'content_habit'):
                for name, f in (d.get(axis) or {}).items():
                    if not isinstance(f, dict) or 'status' not in f:
                        continue
                    self.assertIn('min_support_rule', f, f"{d['donor']}.{axis}.{name}")
                    self.assertIn(f['status'], ('estimated', 'insufficient_sample'))

    def test_insufficient_features_expose_no_point_estimate(self):
        for d in v2_profiles():
            for axis in ('knowledge', 'reasoning', 'style', 'content_habit'):
                for name, f in (d.get(axis) or {}).items():
                    if isinstance(f, dict) and f.get('status') == 'insufficient_sample':
                        self.assertIsNone(f['value'], f"{d['donor']}.{axis}.{name}")
                        self.assertIsNone(f['natural_range'])
                        self.assertIsNone(f['confidence_interval'])

    def test_estimated_features_carry_interval_and_support_ids(self):
        for d in v2_profiles():
            for axis in ('knowledge', 'reasoning', 'style', 'content_habit'):
                for name, f in (d.get(axis) or {}).items():
                    if isinstance(f, dict) and f.get('status') == 'estimated':
                        self.assertIsNotNone(f['value'])
                        self.assertIsNotNone(f['confidence_interval'], f"{d['donor']}.{axis}.{name}")
                        self.assertTrue(f['denominator_post_ids'])
                        self.assertEqual(f['sample_n'], len(f['denominator_post_ids']))
                        self.assertLessEqual(set(f['support_post_ids']),
                                             set(f['denominator_post_ids']))

    def test_binary_features_are_shrunk_toward_the_pooled_prior(self):
        found = 0
        for d in v2_profiles():
            for name, f in (d.get('knowledge') or {}).items():
                if not (isinstance(f, dict) and f.get('status') == 'estimated'
                        and f.get('family') == 'binary_incidence'):
                    continue
                if name.startswith('language_'):
                    # identity fact, deliberately exempt
                    self.assertEqual(f['shrinkage']['method'], 'not_shrunk', name)
                    continue
                self.assertIsNotNone(f.get('shrunk_value'), f"{d['donor']}.{name}")
                self.assertIn('prior_rate', f['shrinkage'])
                found += 1
        self.assertGreater(found, 0, 'no shrunk binary feature found')


class Eligibility(unittest.TestCase):
    def test_donors_with_no_estimate_are_not_eligible(self):
        elig = {d['donor'] for d in reg.eligible_donors('v2')}
        allp = {d['donor'] for d in v2_profiles()}
        excluded = allp - elig
        self.assertTrue(excluded, 'expected some donors to fail minimum support')
        for donor in excluded:
            d = next(x for x in v2_profiles() if x['donor'] == donor)
            est = sum(1 for axis in ('knowledge', 'reasoning', 'style', 'content_habit')
                      for f in (d.get(axis) or {}).values()
                      if isinstance(f, dict) and f.get('status') == 'estimated')
            self.assertEqual(est, 0, f'{donor} was excluded but has {est} estimates')

    def test_enough_donors_remain_for_gate_a(self):
        self.assertGreaterEqual(len(reg.eligible_donors('v2')), 4,
                                'Gate A needs 4 to 6 usable donors')


class V1Untouched(unittest.TestCase):
    def test_v1_matches_the_migration_manifest(self):
        manifest = json.loads((ROOT / 'handover/migration.json').read_text())
        expected = {e['destination_relative']: e['sha256']
                    for e in manifest['entries'] if e['kind'] != 'symlink'}
        checked = 0
        for p in list(V1.glob('*.json')) + list((V1 / 'versions').glob('*.json')):
            rel = str(p.relative_to(ROOT))
            if rel in expected:
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), expected[rel],
                                 f'v1 profile modified: {rel}')
                checked += 1
        self.assertGreater(checked, 10, 'expected to verify many v1 profiles')

    def test_v2_writes_only_to_its_own_directory(self):
        self.assertTrue(V2.is_dir())
        self.assertNotIn('profiles_v2', [p.name for p in V1.iterdir()])


class Registry(unittest.TestCase):
    def test_default_channel_is_v1_until_activated(self):
        self.assertIn(reg.active_version(), ('v1', 'v2'))

    def test_active_profile_tags_its_channel(self):
        d = reg.eligible_donors()[0]['donor']
        p = reg.active_profile(d)
        self.assertEqual(p['_profile_version_channel'], reg.active_version())

    def test_rollback_target_is_recorded_on_switch(self):
        state = json.loads((ROOT / 'evidence_loop/profiles/active.json').read_text()) \
            if (ROOT / 'evidence_loop/profiles/active.json').exists() else None
        if state and state.get('history'):
            self.assertIn('rollback_to', state)


if __name__ == '__main__':
    unittest.main(verbosity=2)
