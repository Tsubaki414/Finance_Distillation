"""Queue, cooldown, and review report. No network, no model, no fixture rewrite.

Run: .venv/bin/python -B -m unittest tests.test_production_queue
"""
from pathlib import Path
import sys, unittest, datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

import production as prod


def _queue():
    return {'opportunities': [], 'events': {}, 'themes': {}}


def setUpModule():
    """Tests must not write the live review queue."""
    import queue_store as qs
    qs.STORE = Path('/tmp/finance-distillation-test-queue.json')


class FactGate(unittest.TestCase):
    def _packet(self):
        return {
            'primary_facts': [{
                'fact_id': 'f-1',
                'source_id': 'src',
                'admission': 'two_independent_major',
                'text': 'The appeals court ruled against Kalshi. Sports contracts were not shown to be swaps.',
            }],
            'downgraded_claims': [],
            'source_views': [],
        }

    def test_a_bold_judgment_passes(self):
        import draft_from_packet as dw
        draft = {
            'text': '这条路断了。法院没把体育合约认成掉期，跨州复制这件事从此要一州一州打。',
            'attribution': 'event',
        }
        result = dw.fact_qa(draft, self._packet())
        self.assertEqual(result['status'], 'passed', result)

    def test_a_new_price_blocks(self):
        import draft_from_packet as dw
        draft = {
            'text': '这条路断了。相关标的收于92美元，市场已经重新定价。',
            'attribution': 'event',
        }
        result = dw.fact_qa(draft, self._packet())
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('new_concrete_fact', {f['code'] for f in result['findings']})

    def test_a_copied_source_sentence_blocks(self):
        import draft_from_packet as dw
        sentence = 'The appeals court ruled against Kalshi. Sports contracts were not shown to be swaps.'
        result = dw.fact_qa({'text': sentence, 'attribution': 'event'}, self._packet())
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('obvious_source_copy', {f['code'] for f in result['findings']})


class ArticleBody(unittest.TestCase):
    def test_ticker_strip_is_not_a_claim(self):
        page = (
            'Title: Example\n\nURL Source: https://example.com/a\n\n'
            'Markdown Content:\n'
            '[Markets](https://example.com/markets)\n'
            'BTC$83358.69 1.21%\n'
            'Kalshi loses appeal in court.\n'
            '\n'
            'The appeals court ruled against the company on the sports contracts in Ohio and Tennessee.\n'
            'A second paragraph says the panel did not treat the contracts as swaps under the commodity statute.\n'
        )
        sents = prod._sentences(page, n=4)
        blob = ' '.join(sents)
        self.assertNotIn('83358', blob)
        self.assertNotIn('Markets', blob)
        self.assertIn('Ohio', blob)
        linked = 'The court [ruled](https://storage.example/file.91.2.pdf) against the company on Friday in a written opinion.'
        page2 = page + '\n' + linked + '\n'
        sents2 = prod._sentences(page2, n=6)
        self.assertFalse(any('https://' in s or '91.2' in s for s in sents2))
        self.assertTrue(any('ruled' in s for s in sents2))


class CandidateBank(unittest.TestCase):
    def test_items_not_the_count(self):
        lines = prod._candidate_lines(prod.THEMES[1], limit=3)
        self.assertTrue(lines)
        self.assertTrue(all(isinstance(x, str) for x in lines))


class EventKey(unittest.TestCase):
    def test_two_openai_stories_stay_apart(self):
        a = prod._event_key({'support': ['openai', 'hearing', 'australia']})
        b = prod._event_key({'support': ['agents', 'openai', 'pauses', 'training']})
        self.assertNotEqual(a, b)

    def test_same_support_is_same_key(self):
        a = prod._event_key({'support': ['kalshi']})
        b = prod._event_key({'support': ['kalshi']})
        self.assertEqual(a, b)


class EvergreenCooldown(unittest.TestCase):
    def test_risk_family_is_not_back_to_back(self):
        now = datetime.datetime(2026, 9, 28, tzinfo=datetime.timezone.utc)
        q = _queue()
        first = prod.evergreen_pass(q, now.isoformat(), n=2)
        families = []
        for row in first:
            theme = next(t for t in prod.THEMES if t['title'] == row['theme'])
            families.append(theme['family'])
        self.assertEqual(len(first), 2)
        self.assertEqual(len(set(families)), 2)
        self.assertNotEqual(families[0], families[1])
        again = prod.evergreen_pass(q, now.isoformat(), n=2)
        again_titles = {row['theme'] for row in again}
        first_titles = {row['theme'] for row in first}
        self.assertFalse(again_titles & first_titles)
        again_families = [
            next(t['family'] for t in prod.THEMES if t['title'] == row['theme'])
            for row in again
        ]
        self.assertNotIn('risk', again_families)

    def test_review_splits_public_copy_from_audit(self):
        now = datetime.datetime(2026, 9, 28, tzinfo=datetime.timezone.utc).isoformat()
        q = _queue()
        prod.evergreen_pass(q, now, n=1)
        q['opportunities'][0]['audit'] = {'fact_qa': {'status': 'passed'}, 'secret': 'keep out'}
        hot = {'looked': [{
            'title': 'Example event',
            'personas': {'macro': 'skip', 'industry': 'draft', 'trading': 'skip'},
        }]}
        report = prod.render_review(q, hot, [{'theme': q['opportunities'][0]['topic'], 'status': 'draft'}], now)
        self.assertIn('HOT', report)
        self.assertIn('Industry: draft', report)
        self.assertIn('EVERGREEN', report)
        self.assertIn(q['opportunities'][0]['text'][:20], report)
        self.assertNotIn('fact_qa', report)
        self.assertNotIn('keep out', report)


class SourceFirst(unittest.TestCase):
    """A new post is classified on its own words. Matching is only MERGE."""

    def _row(self, rid, author, text, published='2026-09-28T12:00:00+00:00', entities=None):
        return {
            'id': rid,
            'source_id': 'x_' + author,
            'author': author,
            'published_at': published,
            'title': '',
            'text': text,
            'url': 'https://x.com/' + author + '/status/' + rid,
            'entities': entities or [],
            'source_type': 'x',
        }

    def test_a_judgment_is_rewrite_and_a_relay_is_skip(self):
        import analysis_corpus as ac
        rows = [
            self._row('a', 'PhyrexNi', '说人话就是油价很大可能是和股市相反，油价涨，股市下跌的概率就会大。'),
            self._row(
                'b', 'The_RockTrading',
                '$NVDA - NVIDIA EXPANDS BUYBACK PROGRAM TO $235 BILLION Nvidia’s board authorized a $150 billion increase.',
                entities=['nvda'],
            ),
            self._row('c', 'citrini', 'Said thank you to the Waymo as I was getting out'),
        ]
        labeled = ac.classify_latest(3, rows=rows, now=datetime.datetime(2026, 9, 28, 20, tzinfo=datetime.timezone.utc))
        by_id = {row['id']: row for row in labeled}
        self.assertEqual(by_id['a']['action'], 'REWRITE')
        self.assertEqual(by_id['a']['persona'], 'macro')
        self.assertEqual(by_id['b']['action'], 'SKIP')
        self.assertEqual(by_id['c']['action'], 'SKIP')

    def test_two_sources_on_one_subject_merge(self):
        import analysis_corpus as ac
        rows = [
            self._row(
                'p', 'PhyrexNi',
                'Bitget 先开放 bitcoin 提币，是因为问题不在链上，而是第三方安全产品。处理节奏在往好的一面走。',
                published='2026-09-28T10:00:00+00:00',
            ),
            self._row(
                'q', 'qinbafrank',
                'Bitget 已按计划开放 BTC 提币。出事后先暂停、现在有序恢复，这个处理节奏说明事情在往回收。',
                published='2026-09-28T11:00:00+00:00',
            ),
        ]
        labeled = ac.classify_latest(2, rows=rows, now=datetime.datetime(2026, 9, 28, 20, tzinfo=datetime.timezone.utc))
        actions = {row['action'] for row in labeled}
        self.assertIn('MERGE', actions)
        merged = [row for row in labeled if row['action'] == 'MERGE']
        self.assertTrue(all(row['peers'] for row in merged))

    def test_a_fast_source_cannot_fill_the_round(self):
        import analysis_corpus as ac
        rows = []
        for i in range(6):
            rows.append(self._row(
                'fast-' + str(i), 'PhyrexNi',
                '油价上涨以后，股市下跌的概率就会大，这是第 %d 条。' % i,
                published='2026-09-28T1%d:00:00+00:00' % i,
            ))
        rows.append(self._row(
            'slow', 'qinbafrank',
            '长债收益率走高不能直接比九十年代，两个年代的财政不一样。',
            published='2026-09-28T08:00:00+00:00',
        ))
        labeled = ac.classify_latest(
            20, rows=rows, per_source=2, hours=24,
            now=datetime.datetime(2026, 9, 28, 20, tzinfo=datetime.timezone.utc),
        )
        by_source = {}
        for row in labeled:
            by_source[row['source']] = by_source.get(row['source'], 0) + 1
        self.assertLessEqual(by_source.get('x_PhyrexNi', 0), 2)
        self.assertEqual(by_source.get('x_qinbafrank'), 1)
        self.assertLessEqual(len(labeled), 3)

    def test_source_packet_does_not_treat_the_post_as_a_news_fact(self):
        import production as prod
        item = {
            'id': 'p', 'source': 'x_PhyrexNi', 'author': 'PhyrexNi',
            'text': '油价涨，股市下跌的概率就会大。', 'url': 'https://x.com/PhyrexNi/status/p',
            'title': '', 'action': 'REWRITE',
        }
        packet = prod._source_packet(item, [], [])
        self.assertEqual(packet['primary_facts'], [])
        self.assertEqual(packet['source_views'][0]['tier'], 'ANALYSIS')


class AnalysisMatch(unittest.TestCase):
    """The two cases already checked by hand. Matching must find the
    analyst, not only the wire that reported the event.
    """

    def test_kalshi_finds_sportico_not_only_the_wire(self):
        import analysis_corpus as ac
        rows = [
            {
                'id': 'wire',
                'source_id': 'cointelegraph',
                'author': 'cointelegraph',
                'published_at': '2026-09-26T13:21:12+00:00',
                'title': 'Kalshi loses appeal',
                'text': 'Kalshi loses appeal in the Sixth Circuit.',
                'url': 'https://cointelegraph.com/kalshi',
                'entities': [],
                'source_type': 'wire',
            },
            {
                'id': 'sportico',
                'source_id': 'sportico',
                'author': 'Michael McCann',
                'published_at': '2026-09-26T18:00:00+00:00',
                'title': 'Kalshi circuit split',
                'text': (
                    'The likelihood that the Supreme Court will review prediction markets '
                    'rose as the Sixth Circuit ruled against Kalshi. Sports event contracts '
                    'are not swaps. A change in interest rates has inherent financial '
                    'consequences. Who wins Super Bowl MVP does not. Until the Court speaks, '
                    'sports prediction markets face different legal treatment in different states.'
                ),
                'url': 'https://www.sportico.com/law/analysis/kalshi',
                'entities': [],
                'source_type': 'analysis',
            },
        ]
        packet = {
            'support': ['kalshi'],
            'title': 'kalshi',
            'source_views': [{'claim': 'Kalshi loses appeal'}],
        }
        found = ac.match_event(packet, rows=rows)
        authors = [r['author'] for r in found]
        self.assertIn('Michael McCann', authors)
        self.assertGreater(len(found[0]['original_text']), 80)

    def test_alpenglow_finds_the_designer(self):
        import analysis_corpus as ac
        rows = [
            {
                'id': 'wire',
                'source_id': 'panews',
                'author': 'PANews',
                'published_at': '2026-09-26T12:00:00+00:00',
                'title': 'Alpenglow on testnet',
                'text': 'Solana Alpenglow reached a public test network.',
                'url': 'https://www.panewslab.com/alpenglow',
                'entities': [],
                'source_type': 'wire',
            },
            {
                'id': 'watt',
                'source_id': 'x_TheWattenhofer',
                'author': 'TheWattenhofer',
                'published_at': '2026-09-27T17:39:37+00:00',
                'title': '',
                'text': (
                    'Many crypto news outlets claim Alpenglow will activate on mainnet '
                    'on September 28. Why would we test a protocol for only a few days '
                    'before activating it? There is no Alpenrush.'
                ),
                'url': 'https://x.com/TheWattenhofer/status/2104264711479173497',
                'entities': [],
                'source_type': 'x',
            },
        ]
        found = ac.match_event(
            {'support': ['alpenglow', 'solana'], 'title': 'alpenglow solana', 'source_views': []},
            rows=rows,
        )
        self.assertIn('TheWattenhofer', [r['author'] for r in found])
        self.assertIn('Alpenrush', found[0]['original_text'] + found[-1]['original_text'])

    def test_a_generic_asset_name_does_not_pull_every_post(self):
        import analysis_corpus as ac
        rows = [{
            'id': 'oil',
            'source_id': 'x_PhyrexNi',
            'author': 'PhyrexNi',
            'published_at': '2026-09-28T02:00:00+00:00',
            'title': '',
            'text': '油价上涨以后，bitcoin 和股市一起承压。美债收益率过了 5.2%。',
            'url': 'https://x.com/PhyrexNi/status/2',
            'entities': [],
            'source_type': 'x',
        }]
        found = ac.match_event(
            {'support': ['bitcoin', 'btc'], 'title': 'bitcoin btc', 'source_views': []},
            rows=rows,
        )
        self.assertEqual(found, [])

    def test_unrelated_analyst_is_not_forced_in(self):
        import analysis_corpus as ac
        rows = [{
            'id': 'oil',
            'source_id': 'x_PhyrexNi',
            'author': 'PhyrexNi',
            'published_at': '2026-09-28T02:00:00+00:00',
            'title': '',
            'text': '油价和股市以及 Bitcoin 相反。霍尔木兹还在谈。',
            'url': 'https://x.com/PhyrexNi/status/1',
            'entities': [],
            'source_type': 'x',
        }]
        found = ac.match_event(
            {'support': ['kalshi'], 'title': 'kalshi', 'source_views': []},
            rows=rows,
        )
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
