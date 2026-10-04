"""Front-end source adapters (offline fixtures; live runs are recorded under /workspace/x/sources_live)."""
import json
import os
import unittest
from unittest import mock

from live import content_units as cu
from live.adapters import bls, common, edgar, fed, feeds, fred, treasury

SUBMISSIONS = {'name': 'MICRON TECHNOLOGY INC', 'cik': '723125', 'filings': {'recent': {
    'form': ['4', '8-K', '10-Q', '8-K'], 'filingDate': ['2026-10-01', '2026-09-30', '2026-06-25', '2026-08-26'],
    'accessionNumber': ['0001-26-1', '0000723125-26-000018', '0000723125-26-000015', '0001104659-26-101067'],
    'primaryDocument': ['f4.xml', 'mu-20260930.htm', 'mu-20260528.htm', 'tm_8k.htm'],
    'items': ['', '2.02,9.01', '', '5.02,9.01']}}}
INDEX = {'directory': {'item': [{'name': 'mu-20260930.htm'}, {'name': 'a2026q4ex991-pressrelease.htm'}, {'name': 'R1.htm'}]}}


class CommonTests(unittest.TestCase):
    def test_html_text_keeps_paragraphs_and_drops_scripts(self):
        html = '<html><script>x=1</script><p>Revenue was $11.3 billion.</p><p>Gross margin&nbsp;was 45%.</p></html>'
        self.assertEqual(common.html_text(html), 'Revenue was $11.3 billion.\n\nGross margin was 45%.')

    def test_make_source_hash_and_cap(self):
        src = common.make_source(id='a', source_id='sec_edgar', text='P1.\n\n' + 'x' * 50, publisher='Micron', title='t',
                                 url='u', published_at='2026-09-30', adapter='edgar', max_chars=20)
        self.assertTrue(src['truncated'])
        self.assertEqual(src['original_text'], 'P1.')
        self.assertEqual(len(src['source_hash']), 64)


class EdgarTests(unittest.TestCase):
    def test_user_agent_placeholder_is_flagged(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            ua, placeholder = edgar.user_agent()
        self.assertTrue(placeholder)
        self.assertIn('@', ua)
        with mock.patch.dict(os.environ, {'SEC_USER_AGENT': 'Fiona fiona@real.example'}):
            self.assertEqual(edgar.user_agent(), ('Fiona fiona@real.example', False))

    def test_recent_filings_filters_forms_and_earnings_items(self):
        rows = edgar.recent_filings(SUBMISSIONS, forms=('8-K', '10-Q'), earnings_only=True)
        self.assertEqual([r['accession'] for r in rows], ['0000723125-26-000018'])
        self.assertEqual(rows[0]['company'], 'MICRON TECHNOLOGY INC')

    def test_exhibit_99_is_preferred_for_8k(self):
        self.assertEqual(edgar.pick_document(INDEX, 'mu-20260930.htm', '8-K'), 'a2026q4ex991-pressrelease.htm')
        self.assertEqual(edgar.pick_document(INDEX, 'mu-20260930.htm', '10-Q'), 'mu-20260930.htm')

    def test_source_is_tier_a_named_after_the_company(self):
        src = edgar.to_source({'company': 'MICRON TECHNOLOGY INC', 'cik': '723125', 'form': '8-K', 'date': '2026-09-30',
                               'accession': '0000723125-26-000018', 'document': 'a.htm'}, 'Revenue was $11.3 billion.')
        self.assertEqual(src['source_id'], 'sec_edgar')
        self.assertEqual(src['publisher'], 'Micron Technology')
        from live import registry
        self.assertEqual(registry.source_licence_tier('sec_edgar'), 'A')


FEED = '''<rss><channel><item><title>Jefferson, The U.S. Economy and Monetary Policy</title>
<link><![CDATA[https://www.federalreserve.gov/newsevents/speech/jefferson20261001a.htm]]></link>
<pubDate>Thu, 1 Oct 2026 17:30:00 GMT</pubDate></item></channel></rss>'''
SPEECH = '<html><div id="article"><p class="speaker">Vice Chair Philip N. Jefferson</p><p>Inflation has eased to 2.6 percent.</p></div><div id="footer">x</div></html>'


class FedTests(unittest.TestCase):
    def test_feed_items_and_article_text(self):
        items = fed.parse_feed(FEED, kind='speech')
        self.assertEqual(items[0]['url'], 'https://www.federalreserve.gov/newsevents/speech/jefferson20261001a.htm')
        self.assertEqual(items[0]['published_at'], '2026-10-01')
        text = fed.article_text(SPEECH)
        self.assertIn('Inflation has eased to 2.6 percent.', text)
        self.assertNotIn('footer', text)
        src = fed.to_source(items[0], text)
        self.assertEqual(src['source_id'], 'primary_fed')


BLS = {'status': 'REQUEST_SUCCEEDED', 'Results': {'series': [{'seriesID': 'LNS14000000', 'data': [
    {'year': '2026', 'period': 'M09', 'periodName': 'September', 'value': '4.2'},
    {'year': '2026', 'period': 'M08', 'periodName': 'August', 'value': '4.1'}]}]}}


class DataAdapterTests(unittest.TestCase):
    def test_bls_series_become_contract_valid_units_without_a_model(self):
        src, units = bls.to_source_and_units(BLS)
        self.assertEqual(src['source_id'], 'primary_bls')
        self.assertEqual(len(units), 1)
        u = units[0]
        self.assertEqual(u['licence_tier'], 'A')
        self.assertEqual(u['numbers'][0]['text'], '4.2 percent')
        self.assertEqual(u['numbers'][0]['period'], 'September 2026')
        self.assertIn(u['source_spans'][0]['exact_text'], src['original_text'])

    def test_treasury_rates_become_units(self):
        data = {'data': [{'record_date': '2026-08-31', 'security_desc': 'Treasury Bills', 'avg_interest_rate_amt': '3.788'},
                         {'record_date': '2026-08-31', 'security_desc': 'Treasury Notes', 'avg_interest_rate_amt': '3.345'}]}
        src, units = treasury.to_source_and_units(data)
        self.assertEqual(src['source_id'], 'primary_treasury')
        self.assertEqual([u['numbers'][0]['text'] for u in units], ['3.788%', '3.345%'])

    def test_fred_without_key_is_flagged_not_fetched(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out = fred.fetch_series('UNRATE', transport=lambda *a, **k: self.fail('no network without a key'))
        self.assertEqual(out['status'], 'missing_api_key')


PODCAST = '''<rss xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>Show</title>
<copyright>Any use for text and data mining or computational analysis is strictly prohibited</copyright>
<item><title>Ep 1</title><pubDate>Fri, 02 Oct 2026 08:00:00 +0000</pubDate>
<podcast:transcript url="https://x/t.srt" type="application/srt"/></item></channel></rss>'''


class FeedTests(unittest.TestCase):
    def test_tdm_reservation_blocks_extraction(self):
        meta = feeds.parse_podcast(PODCAST)
        self.assertTrue(meta['tdm_reserved'])
        self.assertEqual(meta['items'][0]['transcript_url'], 'https://x/t.srt')

    def test_srt_to_text(self):
        srt = '1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n2\n00:00:03,500 --> 00:00:05,000\nRates are high.\n'
        self.assertEqual(feeds.srt_text(srt), 'Hello there. Rates are high.')

    def test_without_reservation_podcast_is_allowed(self):
        self.assertFalse(feeds.parse_podcast(PODCAST.replace('text and data mining or computational analysis', 'all rights'))['tdm_reserved'])


if __name__ == '__main__':
    unittest.main()
