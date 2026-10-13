"""Oct 13 evening (thin lanes 2): on-lane feeds for the lane_fit-bound niche accounts (stablecoin yield, airdrop, meme)
appended to live/thin_lane_sources.json behind the same FD_THIN_LANE_SRC switch (no network here)."""
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from live import fd_accounts, lane_fit, registry, source_routes, thin_lane_src
from live.adapters import feeds

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / 'live' / 'source_registry.json'
PHASE1 = 'ec0e21c'   # fd-phase0 HEAD with the merged phase-1 thin lanes (7 rows)
TARGETS = {'crypto_stable_yield_en', 'crypto_stable_yield_zh', 'crypto_airdrop_en', 'crypto_airdrop_zh',
           'crypto_meme_en', 'crypto_meme_zh'}
NEW = {'thin_stablecoin_insider': {'crypto_stable_yield_en', 'crypto_stable_yield_zh'},
       'thin_airdropalert': {'crypto_airdrop_en', 'crypto_airdrop_zh', 'crypto_meme_en', 'crypto_meme_zh'},
       'thin_panews_niche': {'crypto_airdrop_zh', 'crypto_meme_zh', 'crypto_stable_yield_zh'}}


def _rows():
    return {r['id']: r for r in json.loads(thin_lane_src.PATH.read_text())['sources']}


def _feed_text(row, items):
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(items, None)):
        return [s['title'] for s in feeds.fetch_newsletter(row, limit=2)['sources']]


def _item(title, n=1):
    return {'title': title, 'text': 'body ' * 300, 'content_complete': True, 'url': f'https://ex.org/{n}'}


def test_new_rows_present_and_not_in_the_registry():
    rows = _rows()
    assert set(NEW) <= set(rows)
    reg = REG.read_text()
    for sid, accounts in NEW.items():
        r = rows[sid]
        assert r['feed_url'] not in reg and sid not in reg
        assert set(r['route_accounts']) == accounts and accounts <= TARGETS
        assert 'polymarket' not in json.dumps(r).lower()
        assert not set(r['route_accounts']) & {'crypto_prediction_en', 'crypto_prediction_zh'}
        assert json.loads(thin_lane_src.PATH.read_text())['licence'][sid]['tier'] == 'B'


def test_phase1_rows_unchanged():
    try:
        old = json.loads(subprocess.run(['git', 'show', f'{PHASE1}:live/thin_lane_sources.json'], cwd=ROOT,
                                        capture_output=True, check=True).stdout)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('git history not available')
    cur = json.loads(thin_lane_src.PATH.read_text())
    assert cur['sources'][:len(old['sources'])] == old['sources']
    assert {k: v for k, v in cur['licence'].items() if k in {r['id'] for r in old['sources']}} == old['licence']
    assert [r['id'] for r in cur['sources'][len(old['sources']):]] == list(NEW)


def test_new_rows_routed_only_to_their_accounts(monkeypatch):
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    every = {a['id'] for a in fd_accounts.rows(ROOT / 'live' / 'fd20_accounts.json')}
    for sid, accounts in NEW.items():
        assert {a for a in every if source_routes.allowed({'source_id': sid}, a)} == accounts
        assert registry.source_licence_tier(sid) == 'B'


def test_switch_off_restores_the_old_set(monkeypatch):
    from scripts import run_content_adapters as rca
    monkeypatch.setenv('FD_THIN_LANE_SRC', '0')
    base = json.loads(REG.read_text())['sources']
    assert rca.newsletter_feeds() == [r for r in base if r.get('type') in ('newsletter', 'wechat')
                                      and (r.get('feed_url') or (r.get('page_fetch') or {}).get('listing_url'))
                                      and not r.get('fetch_blocked')]
    for sid in NEW:
        assert source_routes.route(sid) is None and registry.source_licence_tier(sid) is None
        assert not any(source_routes.allowed({'source_id': sid}, a) for a in TARGETS)
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    assert set(NEW) <= {f['id'] for f in rca.newsletter_feeds()}


def test_stablecoin_filter_keeps_product_pieces_drops_sdk_howtos():
    row = _rows()['thin_stablecoin_insider']
    got = _feed_text(row, [_item('How to Send USDC with a Payments SDK (2026)', 1),
                           _item('Phone Wallet Adds USDC Savings for 50M Users', 2),
                           _item('Which Agent Payment Standard Should You Build On?', 3),
                           _item('Tokenized Treasury Funds Pass $10B as Yield Stablecoins Grow', 4)])
    assert got == ['Phone Wallet Adds USDC Savings for 50M Users',
                   'Tokenized Treasury Funds Pass $10B as Yield Stablecoins Grow']


def test_airdrop_filter_drops_general_exchange_news():
    row = _rows()['thin_airdropalert']
    got = _feed_text(row, [_item('Country Blocks 27 Crypto Exchanges', 1),
                           _item('Perp DEX Review: Points Season 2 and the Airdrop Math', 2),
                           _item('How Stock-Paired Memecoins Work', 3)])
    assert got == ['Perp DEX Review: Points Season 2 and the Airdrop Math', 'How Stock-Paired Memecoins Work']


def test_panews_niche_takes_lane_titles_only():
    row = _rows()['thin_panews_niche']
    assert row['full_only'] and row['feed_url'] == _rows()['thin_panews_deep']['feed_url']
    got = _feed_text(row, [_item('PA日报 | 某项目空投开放申领', 1), _item('当Meme走向僵化，币圈还有未来吗？', 2),
                           _item('某公链升级抗量子签名', 3), _item('生息稳定币的收益从哪里来', 4)])
    assert got == ['当Meme走向僵化，币圈还有未来吗？', '生息稳定币的收益从哪里来']


@pytest.mark.parametrize('aid,title', [
    ('crypto_stable_yield_en', 'Tokenized Treasury Funds Pass $10B as Yield Stablecoins Grow'),
    ('crypto_stable_yield_zh', 'Phone Wallet Adds USDC Savings for 50M Users'),
    ('crypto_airdrop_en', 'Perp DEX Review: Points Season 2 and the Airdrop Math'),
    ('crypto_airdrop_zh', 'Perp DEX Review: Points Season 2 and the Airdrop Math'),
    ('crypto_meme_en', 'How Stock-Paired Memecoins Work'),
    ('crypto_meme_zh', '当Meme走向僵化，币圈还有未来吗？'),
])
def test_filtered_titles_pass_the_account_lane_fit(monkeypatch, aid, title):
    monkeypatch.setenv('FD_LANE_FIT', '1')
    acc = fd_accounts.by_id()[aid]
    assert lane_fit.packet_check(acc, title)['ok']
