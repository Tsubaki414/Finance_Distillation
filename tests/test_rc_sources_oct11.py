"""Tests for rc_sources Oct 11 additions: defillama_stablecoin_supply, geckoterminal_trending.

Fake HTTP via a transport= callable (no network, no disk cache).  Mirrors the pattern used by the
existing lane_data tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live.adapters.lane_data import (
    stablecoin_supply,
    geckoterminal_trending,
    STABLE_LIST,
    GT_TRENDING,
)

# ---------------------------------------------------------------------------
# Minimal fake API responses (recorded structure, synthetic numbers)
# ---------------------------------------------------------------------------

STABLE_RESPONSE = {
    "peggedAssets": [
        {
            "id": "1", "name": "Tether", "symbol": "USDT", "pegType": "peggedUSD",
            "price": 0.9999,
            "circulating": {"peggedUSD": 184_000_000_000.0},
            "circulatingPrevDay": {"peggedUSD": 183_500_000_000.0},
            "circulatingPrevWeek": {"peggedUSD": 182_000_000_000.0},
        },
        {
            "id": "2", "name": "USD Coin", "symbol": "USDC", "pegType": "peggedUSD",
            "price": 1.0002,
            "circulating": {"peggedUSD": 73_000_000_000.0},
            "circulatingPrevDay": {"peggedUSD": 72_800_000_000.0},
            "circulatingPrevWeek": {"peggedUSD": 72_000_000_000.0},
        },
        {
            # non-USD peg — should be filtered out
            "id": "99", "name": "Some Euro Stable", "symbol": "EURX", "pegType": "peggedEUR",
            "price": 1.09,
            "circulating": {"peggedUSD": 5_000_000_000.0},
            "circulatingPrevDay": {"peggedUSD": 5_000_000_000.0},
            "circulatingPrevWeek": {"peggedUSD": 5_000_000_000.0},
        },
        {
            # depeg: price outside 0.995-1.005 band, supply above depeg_min=250m
            "id": "3", "name": "Shaky Stable", "symbol": "SHKYUSD", "pegType": "peggedUSD",
            "price": 0.990,
            "circulating": {"peggedUSD": 2_000_000_000.0},
            "circulatingPrevDay": {"peggedUSD": 2_000_000_000.0},
            "circulatingPrevWeek": {"peggedUSD": 2_000_000_000.0},
        },
    ]
}

GT_RESPONSE = {
    "data": [
        {
            "id": "solana_abc123",
            "type": "pool",
            "attributes": {
                "name": "BONKINU / SOL",
                "base_token_price_usd": "0.00015",
                "volume_usd": {"h24": 1_200_000.0},
                "price_change_percentage": {"h24": "345.5"},
                "reserve_in_usd": "85000.0",
                "fdv_usd": 3_500_000.0,
                "pool_created_at": "2026-09-01T00:00:00Z",
                "market_cap_usd": None,
            },
            "relationships": {
                "network": {"data": {"id": "solana", "type": "network"}},
                "base_token": {"data": {"id": "solana_abc123tok", "type": "token"}},
            },
        },
        {
            # should be filtered: network not in meme set
            "id": "tezos_xyz",
            "type": "pool",
            "attributes": {
                "name": "TZDOG / XTZ",
                "volume_usd": {"h24": 500_000.0},
                "price_change_percentage": {"h24": "200.0"},
                "reserve_in_usd": "30000.0",
                "fdv_usd": 1_000_000.0,
                "pool_created_at": "2026-09-01T00:00:00Z",
                "market_cap_usd": None,
            },
            "relationships": {
                "network": {"data": {"id": "tezos", "type": "network"}},
            },
        },
        {
            # should be filtered: stablecoin pair
            "id": "base_usdc_usdt",
            "type": "pool",
            "attributes": {
                "name": "USDC / USDT",
                "volume_usd": {"h24": 9_000_000.0},
                "price_change_percentage": {"h24": "0.1"},
                "reserve_in_usd": "5000000.0",
                "fdv_usd": 0.0,
                "pool_created_at": "2026-01-01T00:00:00Z",
                "market_cap_usd": None,
            },
            "relationships": {
                "network": {"data": {"id": "base", "type": "network"}},
            },
        },
        {
            # should be filtered: vol too low
            "id": "base_lowtok",
            "type": "pool",
            "attributes": {
                "name": "LOWTOK / WETH",
                "volume_usd": {"h24": 1_000.0},
                "price_change_percentage": {"h24": "50.0"},
                "reserve_in_usd": "500.0",
                "fdv_usd": 10_000.0,
                "pool_created_at": "2026-09-01T00:00:00Z",
                "market_cap_usd": None,
            },
            "relationships": {
                "network": {"data": {"id": "base", "type": "network"}},
            },
        },
    ]
}


def _stable_transport(url, _opts):
    if STABLE_LIST in url or url.split('#')[0] == STABLE_LIST:
        return 200, json.dumps(STABLE_RESPONSE)
    return 404, ''


def _gt_transport(url, _opts):
    if GT_TRENDING in url or url.split('#')[0] == GT_TRENDING:
        return 200, json.dumps(GT_RESPONSE)
    return 404, ''


def _units_text(r):
    """All statement strings from units in the result."""
    return [u.get('statement', '') for u in r.get('units', [])]


def _original_text(r):
    """Full original_text of the first source (contains all row lines joined)."""
    srcs = r.get('sources', [])
    return srcs[0].get('original_text', '') if srcs else ''


# ---------------------------------------------------------------------------
# defillama_stablecoin_supply
# ---------------------------------------------------------------------------

class TestStablecoinSupply:

    def test_returns_rows_for_usd_pegged(self):
        r = stablecoin_supply(transport=_stable_transport)
        assert r['rows'] >= 2, f"expected >= 2 rows, got {r['rows']}"

    def test_filters_out_non_usd_peg(self):
        r = stablecoin_supply(transport=_stable_transport)
        text = _original_text(r)
        assert 'EURX' not in text

    def test_depeg_row_present(self):
        r = stablecoin_supply(transport=_stable_transport)
        text = _original_text(r)
        assert 'depeg' in text.lower(), f"no depeg row in original_text: {text[:300]}"

    def test_depeg_row_contains_price(self):
        r = stablecoin_supply(transport=_stable_transport)
        text = _original_text(r)
        assert '0.990' in text or '0.9900' in text

    def test_1d_change_in_row(self):
        r = stablecoin_supply(transport=_stable_transport)
        text = _original_text(r)
        assert 'USDT' in text, "no USDT in original_text"
        assert '1d' in text

    def test_source_id(self):
        r = stablecoin_supply(transport=_stable_transport)
        assert r['sources'][0]['source_id'] == 'defillama_stablecoin_supply'

    def test_publisher(self):
        r = stablecoin_supply(transport=_stable_transport)
        assert r['sources'][0]['publisher'] == 'DefiLlama'

    def test_null_assets_no_crash(self):
        r = stablecoin_supply(transport=lambda u, _: (200, '{"peggedAssets": null}'))
        assert 'sources' in r or 'status' in r

    def test_bad_json_no_crash(self):
        r = stablecoin_supply(transport=lambda u, _: (200, 'NOT JSON'))
        assert 'sources' in r or 'status' in r

    def test_http_failure_returns_fail(self):
        r = stablecoin_supply(transport=lambda u, _: (503, ''))
        assert r.get('status', '').startswith('http_') or r.get('rows', 0) == 0

    def test_switch_off(self, monkeypatch):
        monkeypatch.setenv('FD_LANE_SRC_STABLECOIN_SUPPLY', '0')
        r = stablecoin_supply(transport=_stable_transport)
        assert r.get('sources', []) == [] or r.get('rows', -1) == 0


# ---------------------------------------------------------------------------
# geckoterminal_trending
# ---------------------------------------------------------------------------

class TestGeckoTerminalTrending:

    def test_returns_rows(self):
        r = geckoterminal_trending(transport=_gt_transport)
        assert r['rows'] >= 1

    def test_filters_non_meme_networks(self):
        r = geckoterminal_trending(transport=_gt_transport)
        text = _original_text(r)
        assert 'tezos' not in text.lower()

    def test_filters_stablecoin_pairs(self):
        r = geckoterminal_trending(transport=_gt_transport)
        text = _original_text(r)
        assert 'USDC / USDT' not in text

    def test_filters_low_volume(self):
        r = geckoterminal_trending(transport=_gt_transport)
        text = _original_text(r)
        assert 'LOWTOK' not in text

    def test_meme_pool_row_present(self):
        r = geckoterminal_trending(transport=_gt_transport)
        text = _original_text(r)
        assert 'BONKINU' in text

    def test_row_contains_24h_change_and_volume(self):
        r = geckoterminal_trending(transport=_gt_transport)
        text = _original_text(r)
        assert 'BONKINU' in text
        assert '24h' in text
        assert '$' in text

    def test_source_id(self):
        r = geckoterminal_trending(transport=_gt_transport)
        assert r['sources'][0]['source_id'] == 'geckoterminal_trending'

    def test_publisher(self):
        r = geckoterminal_trending(transport=_gt_transport)
        assert r['sources'][0]['publisher'] == 'GeckoTerminal'

    def test_empty_data_no_crash(self):
        r = geckoterminal_trending(transport=lambda u, _: (200, json.dumps({"data": []})))
        assert 'sources' in r or 'status' in r

    def test_null_data_no_crash(self):
        r = geckoterminal_trending(transport=lambda u, _: (200, json.dumps({"data": None})))
        assert 'sources' in r or 'status' in r

    def test_bad_json_no_crash(self):
        r = geckoterminal_trending(transport=lambda u, _: (200, 'NOT JSON AT ALL'))
        assert 'sources' in r or 'status' in r

    def test_http_failure_returns_fail(self):
        r = geckoterminal_trending(transport=lambda u, _: (429, ''))
        assert r.get('status', '').startswith('http_') or r.get('rows', 0) == 0

    def test_switch_off(self, monkeypatch):
        monkeypatch.setenv('FD_LANE_SRC_GT_TRENDING', '0')
        r = geckoterminal_trending(transport=_gt_transport)
        assert r.get('sources', []) == [] or r.get('rows', -1) == 0


# ---------------------------------------------------------------------------
# Route and licence registry checks
# ---------------------------------------------------------------------------

class TestRegistryRouting:

    def test_stablecoin_supply_routes_to_stable_yield(self):
        reg = json.load(open(ROOT / 'live/source_registry.json'))
        sources = {s['id']: s for s in reg['sources']}
        s = sources.get('defillama_stablecoin_supply')
        assert s is not None, 'defillama_stablecoin_supply not in source_registry.json'
        assert 'crypto_stable_yield_zh' in s['route_accounts']
        assert 'crypto_stable_yield_en' in s['route_accounts']

    def test_geckoterminal_routes_to_meme(self):
        reg = json.load(open(ROOT / 'live/source_registry.json'))
        sources = {s['id']: s for s in reg['sources']}
        s = sources.get('geckoterminal_trending')
        assert s is not None, 'geckoterminal_trending not in source_registry.json'
        assert 'crypto_meme_zh' in s['route_accounts']
        assert 'crypto_meme_en' in s['route_accounts']

    def test_stablecoin_supply_licence_tier_B(self):
        lic = json.load(open(ROOT / 'live/source_licence.json'))
        tiers = lic['tiers']
        assert 'defillama_stablecoin_supply' in tiers
        assert tiers['defillama_stablecoin_supply']['tier'] == 'B'

    def test_geckoterminal_licence_tier_B(self):
        lic = json.load(open(ROOT / 'live/source_licence.json'))
        tiers = lic['tiers']
        assert 'geckoterminal_trending' in tiers
        assert tiers['geckoterminal_trending']['tier'] == 'B'

    def test_fetchers_registry_contains_both(self):
        from live.adapters.lane_data import FETCHERS
        assert 'defillama_stablecoin_supply' in FETCHERS
        assert 'geckoterminal_trending' in FETCHERS


# ---------------------------------------------------------------------------
# Lane-word widening (no network)
# ---------------------------------------------------------------------------

class TestLaneWords:

    def test_stable_yield_matches_sUSDS(self):
        from live.lane_fit import lane_hits
        assert lane_hits('crypto_stable_yield', 'sUSDS yield is 8% APY on Sky protocol')

    def test_stable_yield_matches_RWA(self):
        from live.lane_fit import lane_hits
        assert lane_hits('crypto_stable_yield', 'RWA收益 stablecoin TVL reached $10bn')

    def test_stable_yield_matches_circulating_supply(self):
        from live.lane_fit import lane_hits
        # The stablecoin_supply fetcher produces rows like "USDT circulating supply 184bn 1d +0.3%"
        assert lane_hits('crypto_stable_yield',
                         'DefiLlama stablecoin circulating supply USDT 184bn 1d +0.3%')

    def test_stable_yield_matches_depeg(self):
        from live.lane_fit import lane_hits
        assert lane_hits('crypto_stable_yield',
                         'DefiLlama stablecoin depeg signal SHKYUSD price $0.990')

    def test_prediction_matches_kalshi(self):
        from live.lane_fit import lane_hits
        assert lane_hits('crypto_prediction', 'Kalshi crypto market volume $5m 24h')

    def test_prediction_matches_zh_odds(self):
        from live.lane_fit import lane_hits
        assert lane_hits('crypto_prediction', 'Polymarket赔率显示比特币年内突破10万概率为65%')

    def test_meme_flash_strict_matches_trending_pool(self):
        from live.adapters.lane_flashes import STRICT
        assert STRICT['crypto_meme'].search(
            'GeckoTerminal trending pool BONKINU/SOL up 345% in 24h')

    def test_prediction_flash_strict_matches_zh_odds(self):
        from live.adapters.lane_flashes import STRICT
        assert STRICT['crypto_prediction'].search('Polymarket 赔率显示概率盘走强')
