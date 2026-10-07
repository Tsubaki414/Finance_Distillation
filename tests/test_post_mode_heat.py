"""live/post_mode.py (quote / reply only from the draft's own X source) and live/heat.py (re-rank only)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import heat, post_mode  # noqa: E402

X = 'https://x.com/someone/status/2107470027926700373'


def _row(fmt='quick_take', url=X, pub='2026-10-06T13:56:24+00:00', rid='compose-1', acct='a'):
    return {'id': rid, 'day': '2026-10-07', 'account_id': acct, 'post_format': {'type': fmt},
            'source': {'url': url, 'published_at': pub}}


def test_non_x_source_is_original(tmp_path):
    assert post_mode.decide(_row(url='https://www.coindesk.com/a'), tmp_path)['post_mode'] == 'original'


def test_quote_comment_quotes_the_stored_url(tmp_path):
    d = post_mode.decide(_row('quote_comment', url='https://twitter.com/someone/status/2107470027926700373?s=20'), tmp_path)
    assert d == {'post_mode': 'quote', 'quote_target_url': X, 'post_mode_why': 'written as quote_comment'}


def test_stale_and_own_targets_stay_original(tmp_path):
    assert post_mode.decide(_row('quote_comment', pub='2026-10-01T00:00:00+00:00'), tmp_path)['post_mode'] == 'original'
    assert post_mode.decide(_row('quote_comment'), tmp_path, own_handles=['@Someone'])['post_mode'] == 'original'


def test_quote_share_from_donor_mix_capped(tmp_path):
    (tmp_path / 'a.json').write_text(json.dumps({'post_type_mix': {'quote_comment': 0.9}}))
    assert post_mode.quote_share('a', tmp_path) == post_mode.QUOTE_CAP
    modes = [post_mode.decide(_row(rid=f'r{i}'), tmp_path)['post_mode'] for i in range(400)]
    assert 0.2 < modes.count('quote') / 400 < 0.4
    assert post_mode.decide(_row(acct='none'), tmp_path)['post_mode'] == 'original'   # no card -> share 0


def test_reply_only_opt_in_and_once(tmp_path):
    env = {'FD_REPLY_ACCOUNTS': 'a'}
    assert post_mode.decide(_row('question'), tmp_path)['post_mode'] != 'reply'
    d = post_mode.decide(_row('question'), tmp_path, env=env)
    assert d['post_mode'] == 'reply' and d['reply_to_url'] == X
    assert post_mode.decide(_row('question'), tmp_path, env=env, replies_given=1)['post_mode'] != 'reply'


SIG = heat._signals([{'source': 'google_trends', 'term': 'nvidia earnings', 'rank': 1},
                     {'source': 'bilibili', 'term': '游戏比赛', 'rank': 1}])


def test_promote_reranks_only_within_pool():
    pool = ['fed minutes and rates', 'ETH staking flows', 'Nvidia earnings preview: the bar is high']
    new, info = heat.promote(pool, str, SIG)
    assert new[0] == pool[2] and sorted(new) == sorted(pool) and info['index'] == 2
    assert heat.promote(pool, str, SIG, already_led=True) == (pool, None)        # one heat-led draft a day
    assert heat.promote(pool, str, SIG, ok=lambda c: 'Nvidia' not in c) == (pool, None)
    assert heat.promote(['游戏'], str, SIG)[0] == ['游戏']                         # nothing added


def test_fetch_caps_cost_and_survives_errors(tmp_path, monkeypatch):
    monkeypatch.setitem(heat.SOURCES, 'paid', 0.15)

    def boom():
        raise RuntimeError('403')
    calls = []
    fetchers = {'google_trends': lambda: [{'term': 'bitcoin', 'rank': 1}], 'reddit': boom,
                'paid': lambda: calls.append(1) or [{'term': 'x', 'rank': 1}],
                'paid2': lambda: calls.append(2) or []}
    monkeypatch.setitem(heat.SOURCES, 'paid2', 0.10)
    out = heat.fetch('2026-10-07', store=tmp_path, fetchers=fetchers, cap=0.20)
    assert calls == [1] and 'cost cap' in out['errors']['paid2'] and 'reddit' in out['errors']
    assert out['cost_usd'] == 0.15 and {i['source'] for i in out['items']} == {'google_trends', 'paid'}
    assert heat.signals_for('2026-10-07', store=tmp_path, env={'FD_HEAT': '0'}) == []
