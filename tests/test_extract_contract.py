"""P0-4d: EXTRACT contract. Code, not the model, enforces:
evidence spans are exact substrings of the named paragraph; every number is
an exact substring of its span and parses to a quantity found there; a number
bound to a recognised metric must match the metric the span binds it to;
licence tier missing or D -> no extraction (zero model calls); C -> topic_only.
"""
import json
import unittest

from live import content_units as cu
from live.distillation import ContractError

TEXT = ('Micron revenue rose 4.8x to $54.23 billion in the quarter.\n\n'
        'Operating margin was 69.5% as memory prices kept rising, the company said.\n\n'
        'Memory makers are acting like OPEC: none of them wants to build a glut.')
SOURCE = {'source_id': 'nextplatform', 'source_hash': 'h' * 64, 'original_text': TEXT,
          'author_name': 'Timothy Prickett Morgan', 'title': 'Micron numbers',
          'published_at': '2026-10-02T00:00:00Z', 'source_language': 'en'}


def unit(**over):
    base = {'kind': 'fact', 'statement': 'Micron quarterly revenue grew 4.8x to $54.23B.',
            'source_spans': [{'paragraph_id': 'P1', 'exact_text': 'Micron revenue rose 4.8x to $54.23 billion'}],
            'numbers': [{'text': '$54.23 billion', 'metric': 'revenue', 'period': 'the quarter', 'span_ref': 0},
                        {'text': '4.8x', 'metric': 'revenue growth', 'period': 'the quarter', 'span_ref': 0}],
            'speaker': 'Micron', 'speaker_type': 'company_exec', 'freshness_class': 'current'}
    base.update(over)
    return base


class Fake:
    def __init__(self, units):
        self.units, self.calls = units, []

    def __call__(self, stage, messages, max_tokens):
        self.calls.append((stage, messages))
        return {'text': json.dumps({'units': self.units}), 'finish_reason': 'stop', 'model': 'fake'}


class ExtractContractTests(unittest.TestCase):
    def run_extract(self, units, source=SOURCE, tier='B'):
        fake = Fake(units)
        return cu.extract(source, fake, licence_tier=tier), fake

    def test_valid_units_get_offsets_ids_and_licence(self):
        view = unit(kind='view', statement='Makers avoid overbuilding.',
                    source_spans=[{'paragraph_id': 'P3', 'exact_text': 'none of them wants to build a glut'}],
                    numbers=[], speaker='Timothy Prickett Morgan', speaker_type='media')
        result, fake = self.run_extract([unit(), view])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][0], 'extract')
        units = result['units']
        self.assertEqual(len(units), 2)
        span = units[0]['source_spans'][0]
        self.assertEqual(TEXT[span['start']:span['end']], span['exact_text'])
        self.assertTrue(units[0]['unit_id'].startswith('cu-'))
        self.assertEqual(units[0]['licence_tier'], 'B')
        self.assertEqual(units[0]['usage'], 'paraphrase')
        self.assertEqual(units[0]['numbers'][0]['quantity'], ['5.423E+10', 'USD'])
        self.assertEqual(result['prompt_assembly']['effective_template_id'], 'content_units.EXTRACT')
        self.assertEqual(result['span_match_rate'], 1.0)

    def test_forged_span_rejected(self):
        bad = unit(source_spans=[{'paragraph_id': 'P1', 'exact_text': 'Micron revenue soared to $54.23 billion'}])
        with self.assertRaises(ContractError):
            self.run_extract([bad])

    def test_span_from_other_paragraph_rejected(self):
        bad = unit(source_spans=[{'paragraph_id': 'P2', 'exact_text': 'Micron revenue rose 4.8x to $54.23 billion'}])
        with self.assertRaises(ContractError):
            self.run_extract([bad])

    def test_number_not_in_span_rejected(self):
        bad = unit(numbers=[{'text': '69.5%', 'metric': 'operating margin', 'period': 'q', 'span_ref': 0}])
        with self.assertRaises(ContractError):
            self.run_extract([bad])

    def test_number_text_must_parse_to_one_quantity(self):
        bad = unit(numbers=[{'text': 'revenue', 'metric': 'revenue', 'period': 'q', 'span_ref': 0}])
        with self.assertRaises(ContractError):
            self.run_extract([bad])

    def test_metric_binding_mismatch_detected(self):
        spans = [{'paragraph_id': 'P1', 'exact_text': 'Micron revenue rose 4.8x to $54.23 billion'},
                 {'paragraph_id': 'P2', 'exact_text': 'Operating margin was 69.5%'}]
        bad = unit(source_spans=spans, numbers=[
            {'text': '69.5%', 'metric': 'revenue', 'period': 'q', 'span_ref': 1}])
        with self.assertRaises(ContractError):
            self.run_extract([bad])
        good = unit(source_spans=spans, numbers=[
            {'text': '69.5%', 'metric': 'operating margin', 'period': 'q', 'span_ref': 1}])
        self.run_extract([good])

    def test_bad_span_ref_and_missing_fields_rejected(self):
        for bad in (unit(numbers=[{'text': '4.8x', 'metric': 'growth', 'period': 'q', 'span_ref': 3}]),
                    unit(numbers=[{'text': '4.8x', 'span_ref': 0}]),
                    unit(kind='opinion'), unit(source_spans=[]), unit(statement='')):
            with self.assertRaises(ContractError):
                self.run_extract([bad])

    def test_licence_d_or_missing_refused_without_model_call(self):
        for tier in ('D', None, 'Z'):
            fake = Fake([unit()])
            with self.assertRaises(cu.LicenceRefused):
                cu.extract(SOURCE, fake, licence_tier=tier)
            self.assertEqual(fake.calls, [])

    def test_c_tier_is_topic_only(self):
        result, _ = self.run_extract([unit()], tier='C')
        self.assertEqual(result['units'][0]['usage'], 'topic_only')

    def test_a_tier_keeps_quote_usage(self):
        result, _ = self.run_extract([unit()], tier='A')
        self.assertEqual(result['units'][0]['usage'], 'quote')

    def test_empty_units_is_valid_no_content(self):
        result, _ = self.run_extract([])
        self.assertEqual(result['units'], [])

    def test_incomplete_response_rejected(self):
        class Cut(Fake):
            def __call__(self, stage, messages, max_tokens):
                return {'text': '{"units": [', 'finish_reason': 'length'}
        with self.assertRaises(ContractError):
            cu.extract(SOURCE, Cut([]), licence_tier='B')


if __name__ == '__main__':
    unittest.main()
