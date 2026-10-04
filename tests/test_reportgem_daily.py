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
        self.assertEqual(scores['_method']['macro_rates_en'], 'keyword')
        self.assertTrue(scores['_method']['jev_fallback']['macro_rates_en'])

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

class ScaleTests(unittest.TestCase):
    def test_chinese_alias_and_licence(self):
        from live import registry
        for alias, bank in [('CICC', '中金公司'), ('国泰君安证券', '国泰海通'), ('广发证券', '广发证券'), ('CA-CIB', 'Credit Agricole')]:
            self.assertEqual(rg.bank_of(alias), bank)
            self.assertEqual(registry.source_licence_tier(rg.source_id_for(bank)), 'B')
        self.assertEqual(len({rg.source_id_for(b) for b in rg.BANKS}), len(rg.BANKS))

    def test_query_sources_and_cn_window(self):
        qs = rg.listing_queries(['macro_zh'], day='2026-10-04')
        self.assertGreaterEqual(len(qs), 2)
        cn = next(q for q in qs if q['sources'] == ['chinese_research'])
        self.assertEqual(cn['date_from'], '2026-09-27')
        foreign = next(q for q in qs if q['sources'] == ['realtime_research'])
        self.assertEqual(foreign['date_from'], '2026-10-02')
        it = dict(item(1, inst='广发证券', date='2026-09-28'), source_type='cn')
        rows = rg.daily_listing(lambda *_: search_response([it]), [cn], day='2026-10-04', budget=rg.Points(40))
        self.assertEqual(len(rows), 1)
        for p in rg.THEMES:
            self.assertIn(len(rg.THEMES[p][0]), (2, 3))

    def test_prescreen_batches_and_partial_fallback(self):
        class Jev:
            calls = []
            def review(self, state, questions):
                self.calls.append(questions)
                return {'status': 'completed', 'answers': {q: {'choice': 'weak'} for q in questions}}
        jev = Jev()
        rows = [dict(item(i, title='Fed rates'), bank='Goldman Sachs') for i in range(35)]
        scores = rg.prescreen(rows, ['macro_rates_en'], jev=jev)
        self.assertEqual([len(q) for q in jev.calls], [16, 16, 3])
        self.assertEqual(len(scores['macro_rates_en']), 35)
        class Broken:
            def review(self, *a):
                raise RuntimeError('offline')
        scores = rg.prescreen(rows, ['macro_rates_en'], jev=Broken())
        self.assertTrue(scores['_method']['jev_fallback']['macro_rates_en'])

    def test_round_robin_shared_item_covers_personas(self):
        scores = {'a': {'1': 'strong', '2': 'weak'}, 'b': {'1': 'strong'}, 'c': {'3': 'weak'}}
        top = rg.select_top(scores, max_total=3)
        self.assertEqual({p for p, _ in top}, {'a', 'b', 'c'})

    def test_chinese_cleaning_and_language(self):
        factual = '美联储政策变化带动美债收益率下降，市场流动性改善。' * 4
        text = '请务必阅读末页之重要声明。目标价100元；评级买入！分析师张三执业证书123。数据来源：Wind。' + factual
        clean = rg.clean_passage(text)
        self.assertEqual(clean, factual)
        src = rg.to_source(dict(item(1), bank='广发证券', source_type='cn'), {'passages': [{'text': text}]})
        self.assertEqual(src['source_language'], 'zh')
        self.assertTrue(rg.is_rating_call({'title': '公司目标价上调，评级买入'}))

    def test_projection(self):
        out = rg.projection(15)
        self.assertEqual(out['monthly_points_30d'], 450)
        self.assertAlmostEqual(out['pack_169']['days_covered'], 400 / 15)
        self.assertIn('299', out['recommendation'])
        self.assertIsNone(rg.projection(0)['pack_299']['days_covered'])

    def test_http_json_sse_and_recording(self):
        import tempfile
        from pathlib import Path
        import httpx
        from live.reportgem_mcp_http import ReportGemHTTP
        for mode in ('json', 'sse', 'structured'):
            sse = mode == 'sse'
            calls = []
            def handler(request):
                self.assertEqual(request.headers['Authorization'], 'Bearer secret')
                body = json.loads(request.content)
                if body['method'] != 'initialize':
                    self.assertEqual(request.headers['Mcp-Session-Id'], 'session')
                calls.append(body)
                if body['method'] == 'notifications/initialized':
                    return httpx.Response(202)
                result = {'protocolVersion': '2025-03-26'} if body['method'] == 'initialize' else {'content': [{'type': 'text', 'text': json.dumps(search_response([]))}]}
                if mode == 'structured' and body['method'] == 'tools/call':
                    result = {'structuredContent': search_response([])}
                payload = {'jsonrpc': '2.0', 'id': body['id'], 'result': result}
                if sse:
                    return httpx.Response(200, text='event: message\ndata: ' + json.dumps(payload) + '\n\n', headers={'content-type': 'text/event-stream', 'mcp-session-id': 'session'})
                return httpx.Response(200, json=payload, headers={'mcp-session-id': 'session'})
            with tempfile.TemporaryDirectory() as tmp:
                client = ReportGemHTTP('https://fixture.invalid/mcp', 'secret', run=Path(tmp), transport=httpx.MockTransport(handler))
                self.assertEqual(client('search_research', {'query': 'Fed'}), search_response([]))
                self.assertTrue(list((Path(tmp) / 'responses').glob('*.json')))
                self.assertEqual([c['method'] for c in calls], ['initialize', 'notifications/initialized', 'tools/call'])
                client.close()

    def test_extract_store_helper_drops_and_resumes(self):
        import tempfile
        from live.content_store import ContentStore
        from unittest.mock import patch
        src = dict(item(1), publisher='Goldman Sachs', author_name='Goldman Sachs', source_id='reportgem_goldman_sachs', source_hash='abc')
        units = [{'unit_id': k, 'licence_tier': 'B', 'usage': 'paraphrase', 'statement': 'Fed rates', 'kind': 'fact'} for k in ('keep', 'drop')]
        with tempfile.TemporaryDirectory() as tmp, patch('live.jev_front.prescreen_units', return_value={'keep': {'verdict': 'keep'}, 'drop': {'verdict': 'drop'}}):
            store = ContentStore(tmp)
            result = rg.store_units(src, units, 'macro_rates_en', store=store, jev=object())
            self.assertEqual(result['dropped'], 1)
            self.assertEqual(store.units()[0]['personas'], ['macro_rates_en'])
            self.assertEqual(rg.store_units(src, units, 'macro_rates_en', store=store, jev=object())['duplicate'], 1)


    def test_http_missing_env_is_clear(self):
        import os
        import tempfile
        from unittest.mock import patch
        from live.reportgem_mcp_http import ReportGemHTTP
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'reportgem_http_not_configured'):
                ReportGemHTTP(run=tmp)

    def test_partial_jev_answers_fallback_without_losing_completed_batch(self):
        class Jev:
            calls = 0
            def review(self, state, questions):
                self.calls += 1
                return {'status': 'completed', 'answers': {q: {'choice': 'weak'} for q in questions} if self.calls == 1 else {}}
        rows = [dict(item(i, title='美联储利率展望'), bank='广发证券') for i in range(18)]
        scores = rg.prescreen(rows, ['macro_zh'], jev=Jev())
        self.assertEqual(scores['macro_zh']['0'], 'weak')
        self.assertEqual(scores['macro_zh']['17'], 'strong')
        self.assertTrue(scores['_method']['jev_fallback']['macro_zh'])


if __name__ == '__main__':
    unittest.main()


class ChineseQueryShapeTests(unittest.TestCase):
    def test_chinese_queries_are_single_terms(self):
        # Live 2026-10-04: chinese_research ANDs body keywords; '美联储 宏观 美债' returned 0, '宏观' returned 5.
        from live import reportgem_daily as rd
        for q in rd.listing_queries(list(rd.THEMES), day='2026-10-04'):
            if 'chinese_research' in q['sources']:
                self.assertNotIn(' ', q['query'].strip())


class SelectionQualityTests(unittest.TestCase):
    # Live 2026-10-04 expanded run: sid-string ordering put a Chinese report first for an English
    # persona, and weak filler was taken while strong items existed.
    ITEMS = {'27232236': dict(item(27232236, inst='东吴证券'), source_type='cn'),
             '903933': item(903933, inst='JPMorgan', date='2026-10-02'),
             '903895': dict(item(903895, inst='BofA'), evidence_status='metadata_only'),
             '903094': item(903094, inst='JPMorgan')}

    def test_english_persona_never_gets_a_chinese_report(self):
        scores = {'macro_rates_en': {'27232236': 'strong', '903933': 'strong'}}
        top = rg.select_top(scores, items=self.ITEMS, per_persona=2)
        self.assertEqual([s for _, s in top], ['903933'])

    def test_excerpt_backed_items_rank_before_metadata_only(self):
        scores = {'macro_rates_en': {'903895': 'strong', '903933': 'strong'}}
        top = rg.select_top(scores, items=self.ITEMS, per_persona=1)
        self.assertEqual(top, [('macro_rates_en', '903933')])

    def test_weak_is_only_used_when_persona_has_no_strong(self):
        scores = {'crypto_macro_zh': {'903933': 'strong', '903094': 'weak'}}
        top = rg.select_top(scores, items=self.ITEMS, per_persona=3)
        self.assertEqual(top, [('crypto_macro_zh', '903933')])

    def test_rating_suffix_titles_are_rating_calls(self):
        self.assertTrue(rg.is_rating_call({'title': 'Memory: MU read-across: tighter S/D; Buy SEC/Hynix'}))
        self.assertTrue(rg.is_rating_call({'title': 'HOYA (7741): demand supports glass substrate; maintain Buy'}))
        self.assertFalse(rg.is_rating_call({'title': 'Global Rates Weekly: Start of rates bite'}))


class RateLimitTests(unittest.TestCase):
    def test_rate_limited_tool_error_is_retried_without_recording_the_error(self):
        # Live 2026-10-04: parallel listings returned isError 'rate_limited' ("不会扣费").
        import tempfile
        from pathlib import Path
        import httpx
        from live.reportgem_mcp_http import ReportGemHTTP
        state = {'calls': 0}
        def handler(request):
            body = json.loads(request.content)
            if body['method'] == 'initialize':
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': {'protocolVersion': '2025-03-26'}})
            if 'id' not in body:
                return httpx.Response(202)
            state['calls'] += 1
            if state['calls'] == 1:
                res = {'isError': True, 'content': [{'type': 'text', 'text': '{"error": {"code": "rate_limited"}}'}]}
            else:
                res = {'content': [{'type': 'text', 'text': '{"results": [], "mcp_usage": {"points": 0}}'}]}
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': res})
        with tempfile.TemporaryDirectory() as tmp:
            client = ReportGemHTTP('https://fixture.invalid/mcp', 'secret', run=Path(tmp),
                                   transport=httpx.MockTransport(handler), sleep=lambda s: None)
            data = client('search_research', {'query': 'x'})
            self.assertEqual(data['results'], [])
            self.assertEqual(state['calls'], 2)


class TightenTests(unittest.TestCase):
    def test_excluded_bofa_counted_once_before_screening(self):
        qs = rg.listing_queries(['industry_ai_capex'], day='2026-10-04')
        report = {}
        rows = rg.daily_listing(lambda *_: search_response([item(1, inst='BofA Global Research'), item(1, inst='BofA'), item(2)]),
                                qs, day='2026-10-04', budget=rg.Points(40), report=report)
        self.assertEqual([r['source_id'] for r in rows], ['2'])
        self.assertEqual(report['excluded_banks'], {'BofA': 1})
        self.assertEqual(rg.bank_of('Bank of America'), 'BofA')
        self.assertIn('2026-10-04', rg.EXCLUDED_BANKS['BofA'])

    def test_targeted_queries_dedup_and_catchup_window(self):
        personas = ['investing_philosophy', 'trading_shortterm', 'industry_ai_capex', 'zh_us_stock_commentary']
        base = rg.listing_queries(personas, day='2026-10-04')
        qs = rg.listing_queries(personas, day='2026-10-04', targeted=personas * 2, date_from='2026-09-20')
        self.assertEqual(len(qs), len(base) + 8)
        self.assertEqual(len({(q['query'], tuple(q['sources'])) for q in qs}), len(qs))
        for q in qs:
            self.assertEqual(q['date_from'], '2026-09-27' if 'chinese_research' in q['sources'] else '2026-09-20')
            if 'chinese_research' in q['sources']:
                self.assertNotIn(' ', q['query'])
        rows = rg.daily_listing(lambda *_: search_response([item(8, date='2026-09-21')]), qs[:1],
                                day='2026-10-04', date_from='2026-09-20', budget=rg.Points(40))
        self.assertEqual(len(rows), 1)

    def test_targeted_queries_use_week_window_and_wider_limit(self):
        base = rg.listing_queries(['trading_shortterm'], day='2026-10-04')
        qs = rg.listing_queries(['trading_shortterm'], day='2026-10-04', targeted=['trading_shortterm'])
        self.assertEqual(qs[:len(base)], base)  # main query keys unchanged
        for q in qs[len(base):]:
            self.assertEqual((q['date_from'], q['limit']), ('2026-09-27', 10))
        old = item(9, date='2026-09-28')
        main = rg.daily_listing(lambda *_: search_response([old]), base[:1], day='2026-10-04', budget=rg.Points(40))
        tgt = rg.daily_listing(lambda *_: search_response([old]), qs[len(base):][:1], day='2026-10-04', budget=rg.Points(40))
        self.assertEqual((len(main), len(tgt)), (0, 1))

    def test_jev_confidence_gate_and_downgrade_count(self):
        class Jev:
            def review(self, state, questions):
                return {'status': 'completed', 'answers': {q: {'choice': 'strong', **a} for q, a in zip(questions, [{'confidence': .69}, {'confidence': .7}, {}])}}
        rows = [dict(item(i), bank='Goldman Sachs') for i in range(3)]
        scores = rg.prescreen(rows, ['investing_philosophy'], jev=Jev())
        self.assertEqual(scores['investing_philosophy'], {'0': 'weak', '1': 'strong', '2': 'weak'})
        self.assertEqual(scores['_downgraded']['investing_philosophy'], 2)

    def test_failed_batch_retried_once_and_only_that_batch_falls_back(self):
        class Jev:
            calls = 0
            def review(self, state, questions):
                self.calls += 1
                if self.calls in (2, 3):
                    raise RuntimeError('offline')
                return {'status': 'completed', 'answers': {q: {'choice': 'none'} for q in questions}}
        jev = Jev()
        rows = [dict(item(i, title='PMI survey'), bank='Goldman Sachs') for i in range(35)]
        scores = rg.prescreen(rows, ['market_data_charts'], jev=jev)
        self.assertEqual(jev.calls, 4)
        self.assertEqual(scores['market_data_charts']['0'], 'none')
        self.assertEqual(scores['market_data_charts']['16'], 'strong')
        self.assertEqual(scores['market_data_charts']['34'], 'none')
        self.assertEqual(scores['_method']['market_data_charts'], 'mixed')
        self.assertEqual(scores['_method']['fallback_items']['market_data_charts'], 16)

    def test_failed_batch_recovers_on_retry(self):
        class Jev:
            calls = 0
            def review(self, state, questions):
                self.calls += 1
                return {'status': 'blocked'} if self.calls == 1 else {'status': 'completed', 'answers': {q: {'choice': 'none'} for q in questions}}
        jev = Jev()
        scores = rg.prescreen([dict(item(1), bank='Goldman Sachs')], ['industry_ai_capex'], jev=jev)
        self.assertEqual(jev.calls, 2)
        self.assertEqual(scores['industry_ai_capex']['1'], 'none')
        self.assertEqual(scores['_method']['industry_ai_capex'], 'jev')

    def test_keyword_strong_requires_title_specific_or_two_distinct_hits(self):
        for title, industry, expected in [('Monthly monthly', '', 'weak'), ('Data charts', '', 'strong'),
                                          ('PMI', '', 'strong'), ('Company update', 'PMI survey', 'weak'), ('Company update', '', 'none')]:
            self.assertEqual(rg._keyword_choice({'title': title, 'industry': industry}, 'market_data_charts'), expected)
        for p, title in [('industry_ai_capex', 'AI'), ('investing_philosophy', 'Strategy'), ('single_stock_deepdive_en', 'Results')]:
            self.assertEqual(rg._keyword_choice({'title': title}, p), 'weak')
        generic = {'data', 'monthly', 'chart', 'results', 'quarter', 'tech', 'ai', 'rate', 'outlook', 'strategy'}
        for p in rg.THEMES:
            self.assertFalse(generic & set(rg.SPECIFIC[p]))
            self.assertTrue(set(rg.SPECIFIC[p]) <= set(rg.THEMES[p][2]))

    def test_sharpened_jev_instructions(self):
        instructions = []
        class Jev:
            def review(self, state, questions):
                instructions.append(next(iter(questions.values()))['instructions'])
                return {'status': 'completed', 'answers': {q: {'choice': 'none'} for q in questions}}
        rg.prescreen([dict(item(1), bank='Goldman Sachs')], ['investing_philosophy', 'trading_shortterm', 'market_data_charts'], jev=Jev())
        for text, phrase in zip(instructions, ['long-horizon investing principles', 'short-term market structure', 'cross-market data trackers']):
            self.assertIn(phrase, text)
            self.assertIn('NOT', text)
            self.assertIn('single-company notes', text)

    def test_cli_targeted_catchup_and_exclusion_report(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from scripts import reportgem_daily as cli
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            calls = []
            def replay_call(tool, args):
                calls.append((tool, args))
                return search_response([item(1, inst='BofA')])
            with patch('sys.argv', ['reportgem_daily', '--run', tmp, '--day', '2026-10-04', '--no-jev', '--targeted', 'investing_philosophy,zh_us_stock_commentary', '--date-from', '2026-09-20']), patch.object(cli, 'replay', return_value=replay_call), patch('builtins.print'):
                cli.main()
            report = json.loads((run / 'report.json').read_text())
            self.assertEqual(report['excluded_banks'], {'BofA': 1})
            self.assertTrue(all(tool == 'search_research' for tool, _ in calls))
            self.assertIn('long-term asset allocation outlook', {args['query'] for _, args in calls})
            self.assertIn('美股', {args['query'] for _, args in calls})
            for _, args in calls:
                self.assertEqual(args['date_from'], '2026-09-27' if 'chinese_research' in args['sources'] else '2026-09-20')
            self.assertEqual(report['listing_items'], 0)
            self.assertEqual(report['points']['evidence_points'], 0)
            self.assertEqual(report['personas']['investing_philosophy']['prescreen_downgraded'], 0)


class FullPullFixes(unittest.TestCase):
    def test_reit_buy_title_is_a_rating_call(self):
        self.assertTrue(rg.is_rating_call({'title': 'Sandisk Corp (SNDK.O): MU Read-Thru: NAND Now Tight Thru CY28; Reit. Buy on S/D Fundamentals'}))
        self.assertFalse(rg.is_rating_call({'title': 'US Networking: Scaling the bandwidth wall'}))

    def test_twin_source_ids_same_report_deduped(self):
        a = item('-34660102', inst='Evercore ISI', title='Semis on Fire')
        b = item('8000000034660102', inst='Evercore ISI', title='Semis on Fire')
        rows = rg.daily_listing(lambda *_: search_response([a, b]), [{'query': 'q', 'sources': ['realtime_research'], 'date_from': '2026-10-02', 'date_to': '2026-10-04', 'limit': 6}],
                                day='2026-10-04', budget=rg.Points(40))
        self.assertEqual(len(rows), 1)

    def test_select_top_ignores_scored_ids_missing_from_items(self):
        scores = {'trading_shortterm': {'1': 'strong', 'gone': 'strong'}}
        top = rg.select_top(scores, items={'1': item(1)}, per_persona=3)
        self.assertEqual(top, [('trading_shortterm', '1')])
