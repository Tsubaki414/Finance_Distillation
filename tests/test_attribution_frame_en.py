"""English personas get English attribution frames (no '（来源：…）' / full-width punctuation);
Chinese personas and lang-less callers keep the existing Chinese frames."""
import re
import unittest

from live import attribution_frame as af
from live import compose
from tests.test_compose import Fake, SOURCE

CJK = re.compile(r'[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]')
LS = {'source_id': 'libertystreet', 'author_name': 'Gianluca Benigno', 'source_language': 'en'}
NP = {'source_id': 'nextplatform', 'author_name': 'The Next Platform'}

EN_BODY = ('Memory pricing power is the story here, and it is not fading soon. Revenue rose 4.8x to $54.23 billion '
           'and operating margin hit 69.5%. Nobody builds a fab overnight, so supply stays tight for longer than '
           'buyers would like. That keeps the cycle running on producer discipline rather than demand alone.')


class EnglishFrameTests(unittest.TestCase):
    def test_en_footer_source(self):
        frame = af.render('mechanism_explainer', NP, lang='en')
        self.assertEqual(frame['placement'], 'footer')
        self.assertIn('Source: The Next Platform', frame['text'])
        self.assertIsNone(CJK.search(frame['text']))

    def test_en_lead_frames(self):
        speaker = af.render('view_relay', LS, lang='en')
        self.assertEqual(speaker['placement'], 'lead')
        self.assertIn('Gianluca Benigno', speaker['text'])
        self.assertIn('Liberty Street Economics', speaker['text'])
        self.assertIsNone(CJK.search(speaker['text']))
        publisher = af.render('data_take', NP, lang='en')
        self.assertIsNone(CJK.search(publisher['text']))

    def test_en_frame_strips_and_checks_clean(self):
        frame = af.render('mechanism_explainer', NP, lang='en')
        text = EN_BODY + frame['text']
        body, found = af.strip(text, frame)
        self.assertTrue(found)
        self.assertEqual(body.strip(), EN_BODY)
        codes = {f['code'] for f in af.check('mechanism_explainer', text, frame, 'B')}
        self.assertNotIn('provenance_in_body', codes)
        self.assertNotIn('missing_attribution_frame', codes)

    def test_en_frame_drops_chinese_descriptors_from_names(self):
        src = {'source_id': 'unregistered_x', 'publisher': 'SpotGamma 免费内容', 'author_name': 'SpotGamma 免费内容'}
        frame = af.render('mechanism_explainer', src, lang='en')
        self.assertTrue(frame['text'].endswith('Source: SpotGamma'), frame['text'])
        self.assertIn('SpotGamma 免费内容', frame['names'])   # body checks still see the full name
        zh_only = {'source_id': 'unregistered_y', 'publisher': '国家统计局 数据发布'}
        with self.assertRaises(ValueError):   # display gate: no English name -> no EN post credits a Chinese name
            af.render('mechanism_explainer', zh_only, lang='en')

    def test_zh_and_default_unchanged(self):
        self.assertEqual(af.render('mechanism_explainer', NP)['text'], '（来源：The Next Platform）')
        self.assertEqual(af.render('mechanism_explainer', NP, lang='zh')['text'], '（来源：The Next Platform）')

    def test_compose_en_persona_gets_english_frame(self):
        result = compose.compose_source(SOURCE, 'en_industry', Fake(body=EN_BODY), post_type='data_take')
        frame = result['attribution_frame']
        self.assertIsNone(CJK.search(frame['text']), frame['text'])
        self.assertNotIn('来源', result['text'])
        self.assertNotIn('missing_attribution_frame', {f['code'] for f in result['post_checks']})

    def test_compose_zh_persona_keeps_chinese_frame(self):
        result = compose.compose_source(SOURCE, 'zh_industry', Fake(), post_type='data_take')
        self.assertEqual(result['attribution_frame']['text'], 'The Next Platform：')


if __name__ == '__main__':
    unittest.main()
