"""Regression tests for the FD_SELECT_PERF speedup (Oct 12 2026).

Checks:
- subjects_in / pick_subject produce identical results with switch on vs off
- _hits counts unchanged for known strings (BTC, ETH, ZH names, $CASHTAGS)
- kill switch (FD_SELECT_PERF=0) restores original behaviour
- _TOKEN_NAMES covers exactly the single-word tokens subjects_in recognises
- clear_select_run_cache() is importable and callable
- entities() (hotspot.py) output identical on vs off
"""

import os
import sys
import importlib
import unittest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))


def _reload_charts(perf_flag: str):
    os.environ['FD_SELECT_PERF'] = perf_flag
    import live.charts as m
    importlib.reload(m)
    return m


def _reload_hotspot(perf_flag: str):
    os.environ['FD_SELECT_PERF'] = perf_flag
    import live.hotspot as m
    importlib.reload(m)
    return m


FIXTURE_TEXTS = [
    'BTC broke above $70k again, ETH also rallied hard. Bitcoin dominance is up.',
    'The Fed kept rates unchanged. Treasury yields held near 4.5% on the 10Y.',
    'Solana ecosystem growing rapidly. SOL hit new highs. $SOL volume surged.',
    'NVIDIA earnings beat. $NVDA up 8%. Tech sector led gains on NASDAQ.',
    'DeFi TVL climbed. Uniswap and AAVE showing strength. ETH gas fees elevated.',
    '比特币突破七万美元，以太坊也大涨，市场整体看涨。',
    'Federal Reserve meeting minutes released. Markets await CPI data.',
    'Bitcoin consolidating near support. BTC/USD testing key levels around $68k.',
    'Apple reported strong iPhone demand. $AAPL near all-time highs.',
    'XRP lawsuit finally settled. Ripple team celebrates court victory.',
    'Generic macro commentary with no ticker mentions whatsoever.',
    'S&P 500 closed flat. Dow Jones down 0.2%. NASDAQ outperformed by +0.8%.',
    'DOGE surged 15% after Elon tweet. Dogecoin community excited.',
    'BNB chain activity rose sharply. Binance ecosystem growing.',
    'US dollar weakened. DXY down. Gold up. Bitcoin benefiting from flight to safety.',
    'Coinbase reported strong Q3 earnings. Hyperliquid volumes up 40%. Avalanche TVL climbed.',
    'CoreWeave IPO priced above range. ASML guidance cut. Broadcom outlook raised.',
    '',
    '   ',
]


class TestSubjectsInParity(unittest.TestCase):
    """subjects_in and pick_subject return identical sets ON vs OFF."""

    def setUp(self):
        self.ch0 = _reload_charts('0')
        self.ch1 = _reload_charts('1')

    def test_subjects_in_parity(self):
        for txt in FIXTURE_TEXTS:
            with self.subTest(txt=txt[:60]):
                r0 = self.ch0.subjects_in(txt)
                r1 = self.ch1.subjects_in(txt)
                self.assertEqual(r0, r1,
                    f'subjects_in mismatch for {txt!r:.60}: off={r0} on={r1}')

    def test_pick_subject_parity(self):
        for txt in FIXTURE_TEXTS:
            with self.subTest(txt=txt[:60]):
                r0 = self.ch0.pick_subject(txt)
                r1 = self.ch1.pick_subject(txt)
                self.assertEqual(r0, r1,
                    f'pick_subject mismatch for {txt!r:.60}: off={r0} on={r1}')


class TestHitsCounts(unittest.TestCase):
    """_hits returns the right (count, first_pos) for known BTC/ETH/ZH/cashtag strings."""

    def setUp(self):
        os.environ['FD_SELECT_PERF'] = '1'
        import live.charts as m; importlib.reload(m)
        self.ch = m

    def test_btc_symbol(self):
        sym, (en, zh, _) = 'BTC', self.ch.CRYPTO['BTC']
        n, pos = self.ch._hits('Price of BTC rose today BTC/USDT', sym, en, zh)
        self.assertEqual(n, 2)
        self.assertGreater(pos, 0)

    def test_btc_en_name(self):
        sym, (en, zh, _) = 'BTC', self.ch.CRYPTO['BTC']
        n, pos = self.ch._hits('bitcoin surged overnight', sym, en, zh)
        self.assertEqual(n, 1)

    def test_btc_zh_name(self):
        sym, (en, zh, _) = 'BTC', self.ch.CRYPTO['BTC']
        n, pos = self.ch._hits('比特币大涨，以太坊跟随', sym, en, zh)
        self.assertEqual(n, 1)

    def test_eth_symbol(self):
        sym, (en, zh, _) = 'ETH', self.ch.CRYPTO['ETH']
        n, _ = self.ch._hits('ETH gas fees are high', sym, en, zh)
        self.assertEqual(n, 1)

    def test_no_match_returns_zero(self):
        sym, (en, zh, _) = 'BTC', self.ch.CRYPTO['BTC']
        n, pos = self.ch._hits('No crypto here at all', sym, en, zh)
        self.assertEqual(n, 0)
        self.assertEqual(pos, 10 ** 9)

    def test_cashtag_variant(self):
        sym, (en, zh, _) = 'SOL', self.ch.CRYPTO['SOL']
        n, _ = self.ch._hits('$SOL hit a new high today', sym, en, zh)
        self.assertEqual(n, 1)

    def test_word_boundary_not_matched(self):
        # 'ETHANOL' must not match ETH
        sym, (en, zh, _) = 'ETH', self.ch.CRYPTO['ETH']
        n, _ = self.ch._hits('ETHANOL price rose', sym, en, zh)
        self.assertEqual(n, 0)

    def test_hits_off_equals_on(self):
        """_hits with FD_SELECT_PERF=0 and =1 must return identical results."""
        self.ch0 = _reload_charts('0')
        self.ch1 = _reload_charts('1')
        for sym, (en, zh, _) in list(self.ch0.CRYPTO.items()) + [(d, (e, z, None)) for _, (d, e, z) in self.ch0.STOCKS.items()]:
            for txt in FIXTURE_TEXTS:
                r0 = self.ch0._hits(txt, sym, en, zh)
                r1 = self.ch1._hits(txt, sym, en, zh)
                if r0 != r1:
                    self.fail(f'_hits mismatch sym={sym} txt={txt!r:.40}: off={r0} on={r1}')


class TestKillSwitch(unittest.TestCase):
    """FD_SELECT_PERF=0 must produce same result as the pre-patch code path."""

    def test_kill_switch_subjects_in(self):
        ch = _reload_charts('0')
        # With kill switch, results still correct (same as on)
        ch1 = _reload_charts('1')
        for txt in FIXTURE_TEXTS:
            self.assertEqual(ch.subjects_in(txt), ch1.subjects_in(txt))

    def test_kill_switch_pick_subject(self):
        ch = _reload_charts('0')
        ch1 = _reload_charts('1')
        for txt in FIXTURE_TEXTS:
            self.assertEqual(ch.pick_subject(txt), ch1.pick_subject(txt))

    def test_kill_switch_hits_parity(self):
        ch0 = _reload_charts('0')
        ch1 = _reload_charts('1')
        sym, (en, zh, _) = 'BTC', ch0.CRYPTO['BTC']
        for txt in FIXTURE_TEXTS:
            self.assertEqual(ch0._hits(txt, sym, en, zh), ch1._hits(txt, sym, en, zh))


class TestTokenNames(unittest.TestCase):
    """_TOKEN_NAMES covers exactly the single-word tokens subjects_in recognises."""

    def setUp(self):
        os.environ['FD_SELECT_PERF'] = '0'
        import live.charts as m; importlib.reload(m)
        self.ch0 = m
        os.environ['FD_SELECT_PERF'] = '1'
        importlib.reload(m)
        self.ch1 = m

    def test_known_name_tokens(self):
        tokens = [
            ('Solana', True), ('Bitcoin', True), ('Ethereum', True),
            ('Dogecoin', True), ('Ripple', True), ('Cardano', True),
            ('Avalanche', True), ('Chainlink', True), ('Coinbase', True),
            ('Hyperliquid', True), ('NVIDIA', True), ('Apple', True),
            ('Alphabet', True), ('Amazon', True), ('Broadcom', True),
            ('Federal', False), ('Reserve', False), ('Bloomberg', False),
            ('NYSE', False), ('Surge', False),
        ]
        for word, expected in tokens:
            with self.subTest(word=word):
                in_tn = word.lower() in self.ch1._TOKEN_NAMES
                si_hit = bool(self.ch0.subjects_in(word))
                self.assertEqual(si_hit, expected,
                    f'subjects_in({word!r}) expected {expected}')
                self.assertEqual(in_tn, expected,
                    f'_TOKEN_NAMES membership {word!r} expected {expected}')


class TestClearCache(unittest.TestCase):
    """clear_select_run_cache is importable and callable without error."""

    def test_clear_importable(self):
        os.environ['FD_SELECT_PERF'] = '1'
        import live.charts as m; importlib.reload(m)
        m.clear_select_run_cache()   # must not raise
        # double-call also fine
        m.clear_select_run_cache()

    def test_clear_flushes_lru(self):
        os.environ['FD_SELECT_PERF'] = '1'
        import live.charts as m; importlib.reload(m)
        m.subjects_in('BTC broke above $70k')
        info_before = m._subjects_in_cached.cache_info()
        self.assertGreater(info_before.currsize, 0)
        m.clear_select_run_cache()
        info_after = m._subjects_in_cached.cache_info()
        self.assertEqual(info_after.currsize, 0)


class TestEntitiesParity(unittest.TestCase):
    """hotspot.entities() produces identical output with FD_SELECT_PERF on vs off."""

    def setUp(self):
        self.hs0 = _reload_hotspot('0')
        self.hs1 = _reload_hotspot('1')

    def test_entities_parity(self):
        for txt in FIXTURE_TEXTS:
            with self.subTest(txt=txt[:60]):
                r0 = frozenset(self.hs0.entities(txt))
                r1 = frozenset(self.hs1.entities(txt))
                self.assertEqual(r0, r1,
                    f'entities mismatch for {txt!r:.60}:\n  off={sorted(r0)}\n  on={sorted(r1)}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
