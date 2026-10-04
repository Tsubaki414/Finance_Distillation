"""ReportGem daily pull (content donor, broker research) -- offline.

Listing: theme queries per persona over realtime research, filtered to the
major banks and the day window, deduplicated. Points are read from each
response's mcp_usage and a hard cap stops further calls. Pre-screen: one
bounded Jev choice call per persona (strong / weak / none per item), with a
deterministic keyword fallback. Top items -> get_evidence passages (disclosure
boilerplate dropped) -> an EXTRACT-ready source at licence tier B whose
attribution names the bank, never ReportGem. Missing recorded responses are
emitted as a call plan instead of being invented.
"""
import json
import unittest

from live import reportgem_daily as rg


def item(i, inst='Goldman Sachs', date='2026-10-02', title='DRAM exports hit record', text='DRAM exports rose 20% yoy to US$33bn.'):
    return {'source_id': str(i), 'institution': inst, 'published_at': date, 'title': title, 'source_type': 'foreign',
            'url': f'https://www.reportgem.com/detail-foreign-rt.html?id={i}', 'ticker': '', 'industry': '',
            'matched_text': text, 'preview': text[:50], 'evidence_status': 'matched_excerpt'}


def search_response(items, points=0.5):
    return {'results': items, 'count': len(items), 'mcp_usage': {'points': points}}


class FakeMcp:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        key = rg.call_key(tool, args)
        if key not in self.responses:
            raise rg.Unrecorded(tool, args)
        return self.responses[key]


class ListingTests(unittest.TestCase):
    def test_filters_banks_window_and_dedups(self):
        q = rg.listing_queries(['industry_ai_capex'], day='2026-10-03')
        responses = {rg.call_key('search_research', q[0]): search_response([
            item(1), item(1), item(2, inst='Some Boutique'), item(3, date='2026-09-20'), item(4, inst='Morgan Stanley')])}
        budget = rg.Points(cap=15)
        items = rg.daily_listing(FakeMcp(responses), q[:1], day='2026-10-03', budget=budget)
        self.assertEqual([i['source_id'] for i in items], ['1', '4'])
        self.assertEqual(items[1]['bank'], 'Morgan Stanley')
        self.assertAlmostEqual(budget.spent, 0.5)

    def test_points_cap_stops_calls(self):
        qs = rg.listing_queries(['macro_rates_en', 'industry_ai_capex'], day='2026-10-03')
        responses = {rg.call_key('search_research', q): search_response([item(i)], points=0.9) for i, q in enumerate(qs)}
        fake = FakeMcp(responses)
        budget = rg.Points(cap=1.0, per_call_estimate=0.9)
        rg.daily_listing(fake, qs, day='2026-10-03', budget=budget)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(budget.stopped)

    def test_unrecorded_call_becomes_a_plan(self):
        qs = rg.listing_queries(['macro_zh'], day='2026-10-03')
        plan = []
        items = rg.daily_listing(FakeMcp({}), qs, day='2026-10-03', budget=rg.Points(cap=15), plan=plan)
        self.assertEqual(items, [])
        self.assertEqual(plan[0]['tool'], 'search_research')


class WindowTests(unittest.TestCase):
    def test_weekend_rolls_back_to_friday(self):
        self.assertEqual(rg.window_start('2026-10-04'), '2026-10-02')  # Sunday
        self.assertEqual(rg.window_start('2026-10-05'), '2026-10-02')  # Monday
        self.assertEqual(rg.window_start('2026-10-07'), '2026-10-06')


class PrescreenTests(unittest.TestCase):
    ITEMS = [dict(item(1, title='Fed to cut rates as payrolls slow'), bank='Goldman Sachs'),
             dict(item(2, title='AI capex: hyperscaler GPU orders'), bank='Morgan Stanley')]

    def test_keyword_fallback_scores_by_persona_theme(self):
        scores = rg.prescreen(self.ITEMS, ['macro_rates_en', 'industry_ai_capex'], jev=None)
        self.assertEqual(scores['macro_rates_en']['1'], 'strong')
        self.assertEqual(scores['industry_ai_capex']['2'], 'strong')
        self.assertEqual(scores['industry_ai_capex']['1'], 'none')

    def test_jev_answers_are_used_when_completed(self):
        class Jev:
            def review(self, state, questions):
                return {'status': 'completed', 'answers': {q: {'choice': 'weak'} for q in questions}}
        scores = rg.prescreen(self.ITEMS, ['macro_rates_en'], jev=Jev())
        self.assertEqual(scores['macro_rates_en'], {'1': 'weak', '2': 'weak'})
        self.assertEqual(scores['_method'], {'macro_rates_en': 'jev'})

    def test_jev_failure_falls_back(self):
        class Jev:
            def review(self, state, questions):
                return {'status': 'blocked', 'answers': {}, 'error_code': 'missing_api_key'}
        scores = rg.prescreen(self.ITEMS, ['macro_rates_en'], jev=Jev())
        self.assertEqual(scores['_method'], {'macro_rates_en': 'keyword'})

    def test_top_items_prefer_strong_and_spread_personas(self):
        scores = {'macro_rates_en': {'1': 'strong', '2': 'weak'}, 'industry_ai_capex': {'1': 'none', '2': 'strong'}, '_method': {}}
        top = rg.select_top(scores, per_persona=1, max_total=4)
        self.assertEqual(top, [('macro_rates_en', '1'), ('industry_ai_capex', '2')])


class SourceTests(unittest.TestCase):
    def test_evidence_becomes_tier_b_source_named_after_the_bank(self):
        it = dict(item(7, inst='Morgan Stanley', title='Memory upcycle'), bank='Morgan Stanley')
        passages = {'passages': [{'text': 'Memory prices rose 15% in the quarter, the steepest climb since 2017.'},
                                 {'text': 'Morgan Stanley Disclosure Appendix Reg AC We hereby certify that all of the views'}],
                    'mcp_usage': {'points': 0.2}}
        source = rg.to_source(it, passages)
        self.assertEqual(source['source_id'], 'reportgem_morgan_stanley')
        self.assertEqual(source['publisher'], 'Morgan Stanley')
        self.assertNotIn('Reg AC', source['original_text'])
        self.assertIn('steepest climb', source['original_text'])
        self.assertEqual(source['provenance']['via'], 'ReportGem MCP')
        from live import registry
        self.assertEqual(registry.source_licence_tier(source['source_id']), 'B')
        from live import attribution_frame
        frame = attribution_frame.render('data_take', source)
        self.assertEqual(frame['text'], 'Morgan Stanley：')
        self.assertNotIn('ReportGem', frame['text'])

    def test_only_boilerplate_gives_no_source(self):
        it = dict(item(8), bank='Goldman Sachs')
        self.assertIsNone(rg.to_source(it, {'passages': [{'text': 'Disclosure Appendix Reg AC hereby certify'}]}))

    def test_every_bank_has_a_tier_b_licence_entry(self):
        from live import registry
        for bank in rg.BANKS:
            self.assertEqual(registry.source_licence_tier(rg.source_id_for(bank)), 'B', bank)


class EvidenceScreenTests(unittest.TestCase):
    """Guards found on the 2026-10-04 smoke run: a re-listed February report and a
    third-party redistribution watermark must never become content."""

    def test_redistribution_watermark_rejects_the_item(self):
        it = dict(item(9, inst='BofA Global Research'), bank='BofA')
        ev = {'passages': [{'matched_text': 'Net income beat by 41% on stronger toll revenue growth this quarter. '
                                            'Unauthorized redistribution of this report is prohibited. '
                                            'This report is intended for someone@other-broker.com.hk'}]}
        self.assertIn('redistribution_watermark', rg.screen_evidence(it, ev))
        self.assertIsNone(rg.to_source(it, ev))

    def test_stale_document_date_rejects_the_item(self):
        it = dict(item(10, date='2026-10-02'), bank='BofA')
        ev = {'passages': [{'matched_text': 'Mixed 4Q25 results 10 February 2026 Top line grew 7% YoY, beating estimates by 2.5% on toll revenue.'}]}
        self.assertIn('stale_document', rg.screen_evidence(it, ev))
        self.assertIsNone(rg.to_source(it, ev))

    def test_same_week_document_date_is_fine(self):
        it = dict(item(11, date='2026-10-02'), bank='Goldman Sachs')
        ev = {'passages': [{'matched_text': 'Equity Research 1 October 2026 | 6:37PM SGT Memory supply is expected to stay tight through 2028 on HBM demand.'}]}
        self.assertEqual(rg.screen_evidence(it, ev), [])
        self.assertIsNotNone(rg.to_source(it, ev))

    def test_price_targets_and_ratings_are_stripped(self):
        text = ('Volvo Car AB Neutral Price (01 Oct 26):Skr15.30 Price Target (Dec-27):Skr18.00 Outlook withdrawn. '
                'Management attributed the deterioration to worsening conditions in China and a slower US recovery. '
                'Maintain Rating: NEUTRAL | PO: 18.50 BRL | Price: 17.18 BRL.')
        cleaned = rg.clean_passage(text)
        self.assertNotIn('Price Target', cleaned)
        self.assertNotIn('PO:', cleaned)
        self.assertIn('worsening conditions in China', cleaned)

    def test_double_quotes_are_normalised_for_json_safe_spans(self):
        # The extract model echoed “Dots” as unescaped "Dots" and broke the JSON (903933, twice).
        cleaned = rg.clean_passage('Policy normalization in line with the Fed “Dots” and the "base case" for a December hike.')
        self.assertNotIn('"', cleaned)
        self.assertNotIn('“', cleaned)
        self.assertIn("Fed 'Dots'", cleaned)

    def test_target_price_titles_are_not_selected(self):
        self.assertTrue(rg.is_rating_call({'title': 'Strategy Inc (MSTR.O): Bitcoin Reversal; Raising TP to $240, Maintain Buy/HR'}))
        self.assertFalse(rg.is_rating_call({'title': 'Global Rates Weekly: Start of rates bite'}))


if __name__ == '__main__':
    unittest.main()
