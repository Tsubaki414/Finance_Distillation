"""P0-4c: post_type attribution frames.

- a declared frame (lead attribution or source footer) no longer trips
  provenance_in_body for frame-bearing post types (paragraph checks in
  fidelity.deterministic and domain_policy.generic_checks, and the post-level
  check);
- aphorism_translation still flags any provenance in the body;
- writing the source author's experience as the account's "我"/"I" is still
  an identity finding, frame or not;
- a B-tier paraphrase without its frame is blocked.
"""
import unittest

from live import attribution_frame as af
from live import domain_policy, fidelity


def lang(text):
    return ('zh', 1.0) if any('\u4e00' <= c <= '\u9fff' for c in text) else ('en', 1.0)


SOURCE = {'source_id': 'libertystreet', 'author_name': 'Gianluca Benigno',
          'source_language': 'en', 'entity_glossary': {}}
PASSAGE = [{'paragraph_id': 'P1', 'exact_text': 'Reserve demand rose to 3.2 trillion dollars in 2025, the authors estimate.'}]
BODY = '作者估计，2025年准备金需求升至3.2万亿美元。'


def codes(rows):
    return {r['code'] for r in rows}


class RenderTests(unittest.TestCase):
    def test_lead_speaker_frame_names_speaker_and_publisher(self):
        frame = af.render('view_relay', SOURCE)
        self.assertEqual(frame['placement'], 'lead')
        self.assertEqual(frame['text'], 'Liberty Street Economics 的 Gianluca Benigno 认为：')

    def test_author_equal_to_publisher_falls_back_to_publisher_frame(self):
        source = {'source_id': 'nextplatform', 'author_name': 'The Next Platform'}
        frame = af.render('mechanism_explainer', source)
        self.assertEqual(frame['name'], 'footer_source')
        self.assertEqual(frame['text'], '（来源：The Next Platform）')

    def test_unrenderable_frame_raises(self):
        with self.assertRaises(ValueError):
            af.render('view_relay', {'source_id': 'nextplatform', 'author_name': 'The Next Platform'})

    def test_aphorism_translation_has_no_frame(self):
        self.assertIsNone(af.render('aphorism_translation', {'source_id': 'x_Morris_LT', 'author_name': 'Morris'}))


class ParagraphChecksTests(unittest.TestCase):
    def run_both(self, text, frame):
        seg = [{'paragraph_id': 'P1', 'text': text}]
        a = fidelity.deterministic(SOURCE, PASSAGE, seg, 'zh', 'localization', detector=lang, frame=frame)
        b = domain_policy.GENERIC.deterministic(SOURCE, PASSAGE, seg, 'zh', 'localization', lang, frame=frame)
        return codes(a), codes(b)

    def test_framed_post_has_no_provenance_finding(self):
        frame = af.render('view_relay', SOURCE)
        for got in self.run_both(frame['text'] + BODY, frame):
            self.assertNotIn('provenance_in_body', got)
            self.assertNotIn('added_author_attribution', got)
        footer = af.render('data_take', {**SOURCE, 'author_name': ''})
        self.assertEqual(footer['name'], 'lead_publisher')
        for got in self.run_both(footer['text'] + BODY, footer):
            self.assertNotIn('provenance_in_body', got)

    def test_footer_frame_is_accepted_at_the_end_only(self):
        footer = {'name': 'footer_source', 'placement': 'footer', 'text': '（来源：Liberty Street Economics）'}
        for got in self.run_both(BODY + '\n来源：Liberty Street Economics', None):
            self.assertIn('provenance_in_body', got)
        for got in self.run_both(BODY + footer['text'], footer):
            self.assertNotIn('provenance_in_body', got)

    def test_aphorism_translation_still_flags_provenance(self):
        for got in self.run_both(BODY + '\n来源：Liberty Street Economics', None):
            self.assertIn('provenance_in_body', got)
        for got in self.run_both(BODY + ' https://libertystreeteconomics.newyorkfed.org/x', None):
            self.assertIn('provenance_in_body', got)

    def test_url_inside_framed_body_still_flagged(self):
        frame = af.render('view_relay', SOURCE)
        for got in self.run_both(frame['text'] + BODY + ' https://x.example/a', frame):
            self.assertIn('provenance_in_body', got)


class PostLevelTests(unittest.TestCase):
    def test_framed_view_relay_passes(self):
        frame = af.render('view_relay', SOURCE)
        self.assertEqual(af.check('view_relay', frame['text'] + BODY, frame, 'B'), [])

    def test_b_tier_paraphrase_without_frame_is_blocked(self):
        frame = af.render('view_relay', SOURCE)
        self.assertIn('missing_attribution_frame', codes(af.check('view_relay', BODY, frame, 'B')))
        self.assertIn('missing_attribution_frame', codes(af.check('data_take', BODY, None, 'B')))

    def test_frame_in_wrong_place_or_twice_is_blocked(self):
        frame = af.render('view_relay', SOURCE)
        self.assertIn('missing_attribution_frame', codes(af.check('view_relay', BODY + frame['text'], frame, 'B')))
        self.assertIn('provenance_in_body', codes(af.check('view_relay', frame['text'] + BODY + frame['text'], frame, 'B')))

    def test_author_experience_as_account_first_person_still_blocked(self):
        frame = af.render('view_relay', SOURCE)
        text = frame['text'] + '我一直在跟踪准备金数据，' + BODY
        self.assertIn('author_identity', codes(af.check('view_relay', text, frame, 'B')))
        text = frame['text'] + '我持有美债多头，' + BODY
        self.assertIn('author_identity', codes(af.check('view_relay', text, frame, 'B')))

    def test_aphorism_translation_post_level_rejects_any_frame(self):
        self.assertIn('provenance_in_body', codes(af.check('aphorism_translation', '来源：Morris\n' + BODY, None, 'A')))
        self.assertEqual(af.check('aphorism_translation', BODY, None, 'A'), [])

    def test_tier_not_allowed_for_post_type(self):
        frame = af.render('view_relay', SOURCE)
        self.assertIn('licence_tier_not_allowed', codes(af.check('view_relay', frame['text'] + BODY, frame, 'A')))
        self.assertIn('licence_tier_not_allowed', codes(af.check('data_take', BODY, None, 'D')))


if __name__ == '__main__':
    unittest.main()


class ReviewFixFrameTests(unittest.TestCase):
    """Cross-check fixes (Claude #4/#6, Codex identity-in-frame)."""

    def test_quoted_speaker_is_not_credited_to_article_author(self):
        # primary unit speaker is a CEO quoted by the author -> no speaker frame
        frame = af.render('mechanism_explainer', SOURCE, speaker='Jensen Huang')
        self.assertEqual(frame['name'], 'footer_source')
        with self.assertRaises(ValueError):
            af.render('view_relay', SOURCE, speaker='Jensen Huang')
        same = af.render('view_relay', SOURCE, speaker='gianluca benigno')
        self.assertEqual(same['name'], 'lead_speaker')

    def test_lead_speaker_requires_publisher(self):
        with self.assertRaises(ValueError):
            af.render('view_relay', {'source_id': 'unknown_source', 'author_name': 'A Person'})

    def test_identity_checked_on_frame_text_too(self):
        frame = {'name': 'lead_speaker', 'placement': 'lead', 'text': 'X 的 我持有这家公司 认为：', 'names': []}
        self.assertIn('author_identity', codes(af.check('view_relay', frame['text'] + BODY, frame, 'B')))

    def test_common_words_with_wo_are_not_first_person(self):
        frame = af.render('view_relay', SOURCE)
        text = frame['text'] + '我国的准备金需求存在自我强化的机制，' + BODY
        self.assertNotIn('author_identity', codes(af.check('view_relay', text, frame, 'B')))


class ReviewFixAttributionTests(unittest.TestCase):
    """Cross-check fixes (Claude #1, Codex invented source names)."""

    def test_translated_source_alias_outside_frame_is_flagged(self):
        frame = af.render('data_take', {'source_id': 'libertystreet', 'author_name': ''})
        text = frame['text'] + '纽约联储研究人员指出，' + BODY
        self.assertIn('provenance_in_body', codes(af.check('data_take', text, frame, 'B')))
        bls = af.render('data_take', {'source_id': 'primary_bls', 'author_name': ''})
        text = bls['text'] + '美国劳工统计局公布的数据显示，' + BODY
        self.assertIn('provenance_in_body', codes(af.check('data_take', text, bls, 'A')))

    def test_other_attribution_outside_frame_is_flagged(self):
        frame = af.render('data_take', {'source_id': 'primary_bls', 'author_name': ''})
        for phrase in ('据彭博社报道，', '援引知情人士，', 'According to Reuters, '):
            text = frame['text'] + phrase + BODY
            self.assertIn('attribution_outside_frame', codes(af.check('data_take', text, frame, 'A')), phrase)

    def test_every_subscribed_source_has_aliases(self):
        import json
        from live import registry
        tiers = json.loads(registry.LICENCE.read_text())['tiers']
        for sid, entry in tiers.items():
            self.assertIsInstance(entry.get('aliases'), list, sid)
