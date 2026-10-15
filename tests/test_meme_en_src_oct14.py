"""Oct 14 (meme EN): two English full-text memecoin analysis feeds for crypto_meme_en appended to
live/thin_lane_sources.json behind the same FD_THIN_LANE_SRC switch (no network here)."""
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from live import fd_accounts, lane_fit, registry, source_routes, thin_lane_src
from live.adapters import feeds

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / 'live' / 'source_registry.json'
PARENT = '42f20f3'   # fd-phase0 HEAD with thin lanes 1 + 2 and thin_extract_pri merged (10 rows)
NEW = {'thin_cryptoticker_meme': {'crypto_meme_en'}, 'thin_coinjournal_meme': {'crypto_meme_en'}}


def _rows():
    return {r['id']: r for r in json.loads(thin_lane_src.PATH.read_text())['sources']}


def _item(title, n=1, text='body ' * 300):
    return {'title': title, 'text': text, 'content_complete': True, 'url': f'https://ex.org/{n}'}


def _take(row, items, limit=2):
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=(items, None)):
        return [s['title'] for s in feeds.fetch_newsletter(row, limit=limit)['sources']]


def test_config_loads_and_rows_are_new():
    cfg = json.loads(thin_lane_src.PATH.read_text())
    rows = _rows()
    assert set(NEW) <= set(rows) and set(NEW) <= thin_lane_src.ids()
    reg = REG.read_text()
    others = [r for sid, r in rows.items() if sid not in NEW]
    for sid, accounts in NEW.items():
        r = rows[sid]
        assert r['adapter'] == 'feed' and r['type'] == 'newsletter' and r['source_language'] == 'en'
        assert r['feed_url'] not in reg and sid not in reg
        assert all(o['feed_url'] != r['feed_url'] for o in others)
        assert set(r['route_accounts']) == accounts and r['route_beats'] == ['crypto_meme']
        assert 'polymarket' not in json.dumps(r).lower()
        assert cfg['licence'][sid]['tier'] == 'B' and cfg['licence'][sid]['no_reproduction']


def test_parent_rows_unchanged():
    try:
        old = json.loads(subprocess.run(['git', 'show', f'{PARENT}:live/thin_lane_sources.json'], cwd=ROOT,
                                        capture_output=True, check=True).stdout)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('git history not available')
    cur = json.loads(thin_lane_src.PATH.read_text())
    assert cur['sources'][:len(old['sources'])] == old['sources']
    assert {k: v for k, v in cur['licence'].items() if k in {r['id'] for r in old['sources']}} == old['licence']
    assert [r['id'] for r in cur['sources'][len(old['sources']):]] == list(NEW)
    assert set(cur['licence']) - set(old['licence']) == set(NEW)


def test_new_rows_routed_only_to_crypto_meme_en(monkeypatch):
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    every = {a['id'] for a in fd_accounts.rows(ROOT / 'live' / 'fd20_accounts.json')}
    assert 'crypto_meme_en' in every
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
        assert not source_routes.allowed({'source_id': sid}, 'crypto_meme_en')
    monkeypatch.setenv('FD_THIN_LANE_SRC', '1')
    assert set(NEW) <= {f['id'] for f in rca.newsletter_feeds()}


@pytest.mark.parametrize('sid', sorted(NEW))
def test_filter_keeps_memecoin_pieces_drops_general_news(sid):
    row = _rows()[sid]
    got = _take(row, [_item('South Korea blocks 27 unregistered exchanges', 1),
                      _item('Dogecoin price at $0.08 and large addresses below 70 percent: the level that decides', 2),
                      _item('Bitcoin price at $83,200 as Solana sheds 11.9 percent', 3),
                      _item('Shiba Inu today: lowest daily level since September 18', 4)])
    assert got == ['Dogecoin price at $0.08 and large addresses below 70 percent: the level that decides',
                   'Shiba Inu today: lowest daily level since September 18']


def test_filter_reads_title_and_lede_not_deep_body():
    row = _rows()['thin_cryptoticker_meme']
    deep = 'Ether leverage fell this week. ' * 20 + ' Elsewhere, memecoins were flat.'
    assert _take(row, [_item('337 million dollars of leverage gone in five days', 1, deep)]) == []


def test_cryptoticker_scans_past_the_newest_general_items():
    row = _rows()['thin_cryptoticker_meme']
    assert row['full_only'] and row['fetch_limit'] == 3
    with mock.patch('live.analysis_corpus.fetch_feed', return_value=([], None)) as ff:
        feeds.fetch_newsletter(row, limit=1)
    assert ff.call_args.kwargs['limit'] >= 60


@pytest.mark.parametrize('title', [
    'Dogecoin is missing from the new CME index while Chainlink is in, despite being a third larger',
    'Shiba Inu (SHIB) and the fake airdrop of October 12',
    'Dogecoin rebounds from $0.0800 as ETF outflows keep downside risks in focus',
])
def test_filtered_titles_pass_crypto_meme_en_lane_fit(monkeypatch, title):
    monkeypatch.setenv('FD_LANE_FIT', '1')
    assert lane_fit.packet_check(fd_accounts.by_id()['crypto_meme_en'], title)['ok']


def test_filter_skips_titles_lane_fit_would_drop():
    # a slot-taking piece that lane_fit (crypto_meme words) rejects is not fetched: PENGU / Pudgy is not a lane word
    row = _rows()['thin_cryptoticker_meme']
    assert _take(row, [_item('Pudgy Penguins without its own blockchain: what happens to PENGU now?', 1,
                             'The brand is losing its chain. ' * 40)]) == []
