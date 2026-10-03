"""Cross-language constraints. The scale conversion is the whole risk.

16.2 万人 and 162,000 are one fact in two notations, and letting a model move between them is
asking for the magnitude error the slot mechanism exists to prevent. English gets its own
deterministic renderer, and everything below checks the audit that guards it.

Run: .venv/bin/python -B -m unittest tests.test_crosslang
"""
from pathlib import Path
import sys, json, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content import crosslang as cl
from content.fact_slots import build_slots

PACKET = json.loads((ROOT / 'evidence_loop/sources/packets/75155f58f5a995e3.json').read_text())
SLOTS = cl.en_slots(PACKET, PACKET['coverage']['required_core_ids'])


class EnglishRendering(unittest.TestCase):
    def test_myriad_becomes_thousands_separated(self):
        payroll = next(s for s in SLOTS if s['fact_id'] == 'payroll')
        self.assertEqual(payroll['value_rendered'], '162,000')
        zh = next(s for s in build_slots(PACKET, PACKET['coverage']['required_core_ids'])
                  if s['fact_id'] == 'payroll')
        self.assertEqual(zh['value_rendered'], '16.2 万人')
        self.assertEqual(payroll['raw_value'], zh['raw_value'])

    def test_percentage_points_are_not_percent(self):
        s = next(s for s in SLOTS if s['fact_id'] == 'participation_since_jan')
        self.assertIn('percentage points', s['value_rendered'])
        self.assertNotIn('percent ', s['value_rendered'].replace('percentage', ''))

    def test_a_decline_carries_its_direction_in_the_frame(self):
        s = next(s for s in SLOTS if s['fact_id'] == 'information')
        self.assertEqual(s['value_rendered'], '23,000')
        self.assertIn('fell by', s['rendered'])
        self.assertEqual(cl.direction_class(s['direction_word']), 'down')


class EnglishAudit(unittest.TestCase):
    def test_a_figure_outside_the_table_is_caught(self):
        _, bad, _ = cl.audit_en('nonfarm payrolls rose by 165,000 in August', SLOTS)
        self.assertTrue(bad)

    def test_thousands_separator_is_part_of_the_number(self):
        """A trailing comma is punctuation; `[\\d,]*` swallowed it and rejected a correct figure."""
        used, bad, _ = cl.audit_en('health care added 13,000, demonstrating resilience', SLOTS)
        self.assertEqual(bad, [])
        self.assertTrue(used)

    def test_direction_may_follow_the_figure(self):
        """"the 162,000 increase" is signed just as much as "rose by 162,000"."""
        used, bad, _ = cl.audit_en('the 162,000 increase in nonfarm payrolls', SLOTS)
        self.assertEqual(bad, [])
        self.assertTrue(used)

    def test_a_figure_with_no_direction_word_loses_its_sign(self):
        _, bad, _ = cl.audit_en('information employment was 23,000 in August', SLOTS)
        self.assertTrue(any('sign is lost' in b for b in bad))

    def test_decimal_point_does_not_end_the_threshold_clause(self):
        """`[^.!?]*` stopped inside "4.1 percent" and reported ".1 percent" as invented."""
        _, bad, proposed = cl.audit_en(
            'The condition for invalidation is if the unemployment rate fell below 4.6 percent.',
            SLOTS)
        self.assertEqual(bad, [])
        self.assertIn('4.6 percent', proposed)

    def test_a_month_count_is_not_a_figure(self):
        _, bad, _ = cl.audit_en('over the prior 12 months the picture was different', SLOTS)
        self.assertEqual(bad, [])


class BackgroundGrounding(unittest.TestCase):
    """Background carries no figures, so no numeric rule catches a false claim in it. The first
    English version explained that BLS files these jobs under 'Restaurants and Hotels'."""

    def rows(self, text, kind_en='added_background', kind='interpretation'):
        return [{'sentence_id': 's1', 'text': text, 'kind': kind, 'kind_en': kind_en,
                 'slot_ids': [], 'model_written_numbers': [], 'proposed_thresholds': [],
                 'fact_ids': []}]

    def codes(self, rows):
        return {f['code'] for f in cl.check_crosslang(rows, SLOTS, PACKET)['findings']}

    def test_a_name_the_release_never_uses_is_blocked(self):
        rows = self.rows("These jobs sit under the 'Restaurants and Hotels' category "
                         "and follow NAICS codes.")
        self.assertIn('background_not_in_the_release', self.codes(rows))

    def test_a_name_the_release_uses_is_allowed(self):
        rows = self.rows('The establishment survey measures nonfarm employment by industry.')
        self.assertNotIn('background_not_in_the_release', self.codes(rows))

    def test_leading_article_does_not_break_the_match(self):
        self.assertEqual(cl.background_entities(
            'The Bureau of Labor Statistics publishes this monthly.'),
            {'Bureau of Labor Statistics'})

    def test_a_source_caveat_must_say_whose_it_is(self):
        note = PACKET['methodology'][0]
        self.assertIn('source_caveat_unattributed', self.codes(self.rows(note)))

    def test_an_attributed_source_caveat_passes(self):
        note = PACKET['methodology'][0]
        rows = self.rows(f'The release notes that {note[0].lower()}{note[1:]}')
        self.assertNotIn('source_caveat_unattributed', self.codes(rows))

    def test_background_may_not_carry_a_figure(self):
        rows = self.rows('For context, payrolls rose by 162,000 in August.')
        rows[0]['slot_ids'] = ['E10']
        self.assertIn('background_carries_a_figure', self.codes(rows))

    def test_the_invalidation_sentence_is_not_background(self):
        rows = self.rows('If the rate falls further this view is wrong.', kind='condition')
        self.assertIn('condition_mislabelled_as_background', self.codes(rows))

    def test_a_piece_with_no_background_is_a_translation(self):
        rows = self.rows('Payrolls rose.', kind_en='carried_claim')
        self.assertIn('no_background_added', self.codes(rows))


class Alignment(unittest.TestCase):
    def test_the_shipped_version_kept_every_fact(self):
        out = sorted((ROOT / 'content/crosslang').glob('*.json'))
        self.assertTrue(out)
        d = json.loads(out[-1].read_text())
        a = d['alignment']
        self.assertEqual(a['dropped_in_english'], [])
        self.assertEqual(a['added_in_english'], [])
        self.assertEqual(a['zh_fact_count'], a['en_fact_count'])
        for row in a['facts']:
            self.assertTrue(row['notation_differs_value_does_not'], row['fact_id'])
            self.assertNotEqual(row['zh'], row['en'])
