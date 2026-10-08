"""Cross-language twin rule (live/twins.py): zh/en twins 27/32, 28/33, 29/34, 30/36 never take one event on one day."""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

from live import hotspot as H, twins

ROOT = Path(__file__).resolve().parents[1]


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pairs_are_the_four_new_zh_en_lanes_and_real_accounts():
    assert twins.twin_of('crypto_meme_zh') == 'crypto_meme_en' and twins.twin_of('crypto_stable_yield_en') == 'crypto_stable_yield_zh'
    assert twins.twin_of('crypto_macro_zh') is None and twins.twin_of('sol_base_alpha_en') is None
    rows = json.loads((ROOT / 'live' / 'fd_accounts_new.json').read_text())
    rows = rows if isinstance(rows, list) else rows.get('accounts', rows)
    lang = {r['id']: r['lang'] for r in rows}
    for zh, en in twins.PAIRS:
        assert lang[zh] == 'zh' and lang[en] == 'en'


def test_entities_skip_generic_and_lane_words():
    ents = twins.entities('Polymarket 上 Zohran Mamdani 当选纽约市长概率升至 94%，BTC 横盘', '')
    assert ents == {'zohran', 'mamdani'}
    assert twins.entities('$WIF and $BONK lead Solana memecoins', '') == {'wif', 'bonk'}
    # short ordinary words are too common to count; a short ALL-CAPS ticker still counts
    assert twins.entities('Mark says Yes on the Gold market', '') == set()
    assert twins.entities('HYPE perps open interest', '') == {'hype'}


def test_clash_on_shared_event_key_or_two_names(monkeypatch):
    monkeypatch.delenv('FD_TWIN_RULE', raising=False)
    taken = {('motif', 'm1'): [('crypto_prediction_zh', 'a', 'zh')]}
    assert 'twin crypto_prediction_zh' in twins.clash('crypto_prediction_en', {('motif', 'm1')}, set(), taken, {})
    ents = {'crypto_prediction_zh': {'zohran', 'mamdani'}}
    assert twins.clash('crypto_prediction_en', {('srcid', 'x')}, {'zohran', 'mamdani', 'cuomo'}, {}, ents)
    assert twins.clash('crypto_prediction_en', {('srcid', 'x')}, {'zohran'}, {}, ents) is None   # one name: not enough
    assert twins.entities('DefiLlama: Tokenless protocols in October', '') == set()                # publisher / date / generic
    assert twins.clash('crypto_macro_en', {('motif', 'm1')}, set(), taken, {}) is None             # not a twin
    monkeypatch.setenv('FD_TWIN_RULE', '0')
    assert twins.clash('crypto_prediction_en', {('motif', 'm1')}, set(), taken, {}) is None


def test_hotspot_holds_the_second_twin_but_not_other_accounts(monkeypatch):
    monkeypatch.delenv('FD_TWIN_RULE', raising=False)
    accts = [{'id': 'crypto_meme_zh', 'lang': 'zh'}, {'id': 'crypto_meme_en', 'lang': 'en'},
             {'id': 'sol_base_alpha_en', 'lang': 'en'}]
    univ = {a['id']: {'topic_mix': {'crypto': 0.5}} for a in accts}
    m = {'id': 'm1', 'pool': 'hotspot', 'type': 'crypto', 'topics': ['crypto'], 'title': 'm1',
         'members': [{'key': ['h1', 's1'], 'title': 'WIF', 'tags': []}]}
    pools = {a['id']: [('h1', 's1')] for a in accts}
    table, assign = H.decide([m], accts, univ, pools, ok=lambda a, k: True)
    row = table['m1']
    writers = {a for a, r in row.items() if r['decision'] == 'WRITE'}
    assert len(writers & {'crypto_meme_zh', 'crypto_meme_en'}) == 1
    loser = ({'crypto_meme_zh', 'crypto_meme_en'} - writers).pop()
    assert row[loser]['decision'] == 'HOLD' and 'twin rule' in row[loser]['reason']
    monkeypatch.setenv('FD_TWIN_RULE', '0')
    row = H.decide([m], accts, univ, pools, ok=lambda a, k: True)[0]['m1']
    assert row['crypto_meme_zh']['decision'] == 'WRITE' and row['crypto_meme_en']['decision'] == 'WRITE'


def test_ready_events_carry_twin_names_for_fill_runs(monkeypatch):
    dc = _script('daily_compose')
    rows = [{'account_id': 'crypto_airdrop_zh', 'draft_status': 'draft_ready', 'text': 'x', 'body': 'Linea 和 MetaMask 积分快照',
             'angle': 'a', 'source': {'id': 's1', 'title': 'Linea 空投查询开放'}},
            {'account_id': 'crypto_macro_zh', 'draft_status': 'draft_ready', 'text': 'x', 'body': 'Linea MetaMask',
             'angle': 'a', 'source': {'id': 's2', 'title': 'short'}}]
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day: rows)
    ev = dc.ready_events(date(2026, 10, 9), [{'id': 'crypto_airdrop_zh', 'lang': 'zh'}, {'id': 'crypto_macro_zh', 'lang': 'zh'}])
    ents = {e[1] for e, acc, _a, _l in ev if e[0] == 'ent' and acc == 'crypto_airdrop_zh'}
    assert {'linea', 'metamask'} <= ents
    assert not [e for e, acc, _a, _l in ev if e[0] == 'ent' and acc == 'crypto_macro_zh']   # only twins carry names


def test_select_wires_the_rule():
    src = (ROOT / 'scripts' / 'daily_compose.py').read_text()
    assert 'twins.clash(account, events, packet_entities(g), event_takers, ent_takers)' in src
    assert "if e[0] == 'ent':" in src
