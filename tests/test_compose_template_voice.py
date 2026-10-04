"""COMPOSE: structural template phrasing and research-summary structure are flagged (soft),
the request names the patterns to avoid, and the prompt pushes conviction without loosening
the fabrication / position / trade-call rules."""
import json
import unittest

from live import compose, qa_levels
from tests.test_compose import Fake, SOURCE, GOOD_BODY

EN_CLEAN = ('Memory makers hold the pricing power now. Revenue rose 4.8x to $54.23 billion and operating margin '
            'hit 69.5%. Nobody builds a fab overnight, so supply stays tight for longer than buyers would like. '
            'Producer discipline sets the length of this cycle, and that discipline looks intact.')


class Capture(Fake):
    def __call__(self, stage, messages, max_tokens):
        if stage == 'compose':
            self.payload = json.loads(messages[-1]['content'])
        return super().__call__(stage, messages, max_tokens)


def codes(result):
    return [(f['code'], f.get('detail')) for f in result['post_checks']]


def run(body, account='zh_industry'):
    fake = Capture(body=body)
    return compose.compose_source(SOURCE, account, fake, post_type='data_take'), fake


class TemplateChecks(unittest.TestCase):
    def test_clean_bodies_have_no_style_findings(self):
        for body, account in ((GOOD_BODY, 'zh_industry'), (EN_CLEAN, 'en_industry')):
            result, _ = run(body, account)
            self.assertFalse([c for c in codes(result) if c[0] in ('template_phrase', 'research_summary')], codes(result))

    def test_zh_contrast_templates_flagged(self):
        for phrase in ('决定周期的不是需求，而是供给。', '这不是需求问题，是供给问题。', '与其说是需求，不如说是供给。', '说白了，供给说了算。'):
            result, _ = run(GOOD_BODY + phrase)
            self.assertIn('template_phrase', [c[0] for c in codes(result)], phrase)

    def test_en_contrast_templates_flagged(self):
        for phrase in (" This isn't a demand story — it's a supply story.", ' The cycle is not demand-led but supply-led.',
                       " Here's the thing: supply is tight.", ' The real story is supply.'):
            result, _ = run(EN_CLEAN + phrase, 'en_industry')
            self.assertIn('template_phrase', [c[0] for c in codes(result)], phrase)

    def test_research_summary_structure_flagged_soft(self):
        zh = ('美光这一季很强。拆解一下具体数据：营收增长4.8倍，达到542.3亿美元；营业利润率69.5%；'
              '建一座晶圆厂要好几年；价格还在上涨。供给端的克制会延续，短期内很难看到过剩，下游买家要按更长的紧缺期安排采购和库存。')
        result, _ = run(zh)
        found = [f for f in result['post_checks'] if f['code'] == 'research_summary']
        self.assertTrue(found)
        self.assertEqual(found[0]['level'], 'soft')
        en = (EN_CLEAN + '\n- Revenue: $54.23 billion\n- Growth: 4.8x\n- Margin: 69.5%')
        result, _ = run(en, 'en_industry')
        self.assertIn('research_summary', [c[0] for c in codes(result)])
        self.assertEqual(qa_levels.level({'code': 'research_summary'}, frame_found=True), 'soft')


class PromptAndPayload(unittest.TestCase):
    def test_payload_names_patterns_to_avoid(self):
        _, fake = run(GOOD_BODY)
        shown = ' '.join(fake.payload['avoid_patterns'])
        self.assertIn('不是X', shown)
        _, fake = run(EN_CLEAN, 'en_industry')
        self.assertTrue(any('not X' in p or "isn't X" in p for p in fake.payload['avoid_patterns']))

    def test_prompt_pushes_conviction_but_keeps_guardrails(self):
        text = compose.COMPOSE.lower()
        for needle in ('conviction', 'research summary', 'short', 'never claim personal holdings',
                       'no specific trade recommendations', 'every number must come from'):
            self.assertIn(needle, text)
        self.assertIn('do not upgrade', text)   # confidence of the stance is kept, not inflated


if __name__ == '__main__':
    unittest.main()
