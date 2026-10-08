"""Oct 8 Sirius borrow (hotspots): 母题 clustering, per-account WRITE / HOLD / IGNORE, reality payload, viral priors,
review feedback loop, dashboard tags; FD_HOTSPOT=0 leaves selection untouched."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import angles, feedback, hotspot as H, span_grounding as sg, viral_priors as vp

ROOT = Path(__file__).resolve().parents[1]
REF = datetime(2026, 10, 7, 22, 13, tzinfo=timezone.utc)


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mat(i, title, hours_ago=2, publisher=None, adapter='feed', accounts=(), tags=(), url=''):
    t = REF - timedelta(hours=hours_ago)
    group = [{'unit_id': f'u{i}', 'licence_tier': 'B', 'tag_personas': list(tags),
              'unit': {'numbers': [], 'statement': title},
              'source': {'title': title, 'publisher': publisher or f'pub{i}', 'url': url, 'adapter': adapter,
                         'published_at': t.isoformat(), 'id': f's{i}', 'source_hash': f'h{i}'}}]
    m = H.material(('h%d' % i, 's%d' % i), group, title)
    m['_event'] = H._title_event(title)
    m['accounts'] = list(accounts)
    return m


# ------------------------------------------------------------------ features + clustering

def test_numbers_normalise_across_languages_and_skip_years():
    assert H.numbers('Bitcoin briefly slides below $84,000') & H.numbers('比特币跌破84000美元')
    assert H.numbers('adds $25 million worth of bitcoin') == H.numbers('增持价值2500万美元的比特币')
    assert not H.numbers('since 2025, the 2026 outlook')
    assert H.numbers('up 2.98% today') == {'2.98%'} and not H.numbers('up 2% today')


def test_entities_fold_synonyms_and_zh_names():
    assert H.entities('Solana Foundation and SOL') == {'sol', 'foundation'}
    assert 'robinhood' in H.entities('罗宾汉增持比特币') and 'btc' in H.entities('罗宾汉增持比特币')
    assert 'september' not in H.entities('Crypto job postings in September')


def test_same_story_links_and_broad_topic_does_not():
    a = mat(1, 'Bitcoin briefly slides below $84,000 as crypto long liquidations reach $487 million')
    b = mat(2, '比特币跌破84000美元 日内跌逾2%')
    c = mat(3, 'Ethereum Alone Holds Nearly Half of All Tokenized Real-World Asset Value')
    d = mat(4, 'Compared to Fusaka, Glamsterdam goes deeper and changes how Ethereum builds blocks')
    groups = H.cluster([a, b, c, d])
    assert sorted(map(sorted, groups)) == [[0, 1], [2], [3]]


def test_digest_joins_but_never_bridges_two_stories():
    a = mat(1, 'SpaceX考虑融资400亿美元，用于购买英伟达芯片')
    b = mat(2, 'SpaceX盘前股价跌近2% 公司据悉正寻求400亿美元融资以购买英伟达芯片')
    c = mat(3, 'Robinhood adds $25 million worth of bitcoin to balance sheet')
    d = mat(4, 'Robinhood adds bitcoin worth $25 million to its balance sheet')
    hub = mat(5, '早报丨SpaceX考虑融资400亿美元；Robinhood增持2500万美元比特币')
    groups = sorted(map(sorted, H.cluster([a, b, c, d, hub])))
    assert [0, 1] in groups or [0, 1, 4] in groups
    assert not any({0, 2} <= set(g) for g in groups)            # the hub did not merge SpaceX with Robinhood


def test_merge_validation_ignores_unknown_and_duplicate_ids():
    clusters = [('c0', [0]), ('c1', [1]), ('c2', [2])]
    merged, titles = H.apply_merge(clusters, {'groups': [{'ids': ['c0', 'c1', 'zz'], 'title_zh': '甲', 'title_en': 'A'},
                                                         {'ids': ['c1', 'c2'], 'title_en': 'B'}]})
    assert ('c0', [0, 1]) in merged and ('c2', [2]) in merged and len(merged) == 2
    assert titles['c0']['zh'] == '甲' and 'c1' not in titles


def test_merge_call_is_cached_and_capped(tmp_path):
    mats = [mat(1, 'A story about X'), mat(2, 'Another about Y')]
    calls = []

    class Client:
        calls = []

        def __call__(self, stage, messages, max_tokens):
            calls.append(stage)
            return {'text': json.dumps({'groups': [{'ids': ['c0', 'c1'], 'title_en': 'X and Y'}]}),
                    'response_model': 'gemini-3-flash-preview'}
    clusters = [('c0', [0]), ('c1', [1])]
    assert H.run_merge(clusters, mats, '2026-10-08', client=Client(), store=tmp_path) == {
        'groups': [{'ids': ['c0', 'c1'], 'title_en': 'X and Y'}]}
    H.run_merge(clusters, mats, '2026-10-08', client=Client(), store=tmp_path)    # cached: no second call
    assert calls == ['extract_flash']
    assert H.run_merge(clusters, mats, '2026-10-09', client=Client(), store=tmp_path, cap_usd=0.0001) is None
    assert calls == ['extract_flash']                                           # over the cap: never called


# ------------------------------------------------------------------ decisions

ACCTS = [{'id': 'crypto_macro_zh', 'lang': 'zh'}, {'id': 'crypto_macro_en', 'lang': 'en'},
         {'id': 'btc_cycles_en', 'lang': 'en'}, {'id': 'crypto_research_en', 'lang': 'en'},
         {'id': 'defi_narratives_en', 'lang': 'en'}, {'id': 'market_data_charts', 'lang': 'en'}]
UNIV = {'crypto_macro_zh': {'topic_mix': {'crypto': 0.27}}, 'crypto_macro_en': {'topic_mix': {'crypto': 0.34}},
        'btc_cycles_en': {'topic_mix': {'crypto': 0.43}, 'lanes': ['crypto_onchain']},
        'crypto_research_en': {'topic_mix': {'crypto': 0.25}},
        'defi_narratives_en': {'topic_mix': {'crypto': 0.33}, 'lanes': ['crypto_defi']},
        'market_data_charts': {'topic_mix': {'crypto': 0.01, 'rates_fed': 0.2}}}


def motif(mid, n_pub=2, keys=(('h1', 's1'),), tags=('crypto_onchain',), ttype='crypto'):
    return {'id': mid, 'pool': 'hotspot', 'type': ttype, 'topics': [ttype], 'title': mid,
            'members': [{'key': list(k), 'title': 'Bitcoin', 'tags': list(tags)} for k in keys]}


def test_decision_respects_beat_spread_lanes_and_caps():
    m1 = motif('m1')
    pools = {a['id']: [('h1', 's1')] for a in ACCTS}
    table, assign = H.decide([m1], ACCTS, UNIV, pools, ok=lambda a, k: True)
    row = table['m1']
    assert row['market_data_charts']['decision'] == 'IGNORE' and 'topic spread' in row['market_data_charts']['reason']
    # Oct 8: outside its lanes but crypto is 0.33 of its topic mix (>= 0.2) -> on beat, competes for the en slots
    assert row['defi_narratives_en']['decision'] != 'IGNORE'
    en = [a for a in ('crypto_macro_en', 'btc_cycles_en', 'crypto_research_en', 'defi_narratives_en')
          if row[a]['decision'] == 'WRITE']
    assert len(en) == 1                                     # Oct 8 evening: 1 per language per 母题 (was 2)
    assert [a for a in ('crypto_macro_en', 'btc_cycles_en', 'crypto_research_en', 'defi_narratives_en')
            if row[a]['decision'] == 'HOLD' and 'cap' in row[a]['reason']]
    assert row['crypto_macro_zh']['decision'] == 'WRITE'


def test_lane_rule_is_lane_or_topic_share():
    m1 = motif('m1')                                                           # tags crypto_onchain, type crypto
    pools = {'defi_narratives_en': [('h1', 's1')]}
    accts = [{'id': 'defi_narratives_en', 'lang': 'en'}]
    low = {'defi_narratives_en': {'topic_mix': {'crypto': 0.15}, 'lanes': ['crypto_defi']}}
    row = H.decide([m1], accts, low, pools, ok=lambda a, k: True)[0]['m1']['defi_narratives_en']
    assert row['decision'] == 'IGNORE' and 'lanes' in row['reason'] and '0.15 < 0.2' in row['reason']
    high = {'defi_narratives_en': {'topic_mix': {'crypto': 0.2}, 'lanes': ['crypto_defi']}}
    assert H.decide([m1], accts, high, pools, ok=lambda a, k: True)[0]['m1']['defi_narratives_en']['decision'] == 'WRITE'
    inlane = {'defi_narratives_en': {'topic_mix': {'crypto': 0.1}, 'lanes': ['crypto_onchain']}}
    assert H.decide([m1], accts, inlane, pools, ok=lambda a, k: True)[0]['m1']['defi_narratives_en']['decision'] == 'WRITE'


def test_x_only_motif_needs_three_publishers():
    def m(adapter, pub):
        return {'adapter': adapter, 'publisher': pub}
    two_x = [m('x:a', '@a'), m('x:b', '@b')]
    assert not H.hot_pool(two_x, {'@a', '@b'}, 0.0, ['acct'])
    assert not H.hot_pool(two_x, {'@a', '@b'}, 2.0, ['acct'])                # public heat does not lift an X-only pair
    three_x = two_x + [m('x:c', '@c')]
    assert H.hot_pool(three_x, {'@a', '@b', '@c'}, 0.0, [])
    mixed = [m('x:a', '@a'), m('rss', 'CoinDesk')]
    assert H.hot_pool(mixed, {'@a', 'CoinDesk'}, 0.0, [])                    # any public source: 2 publishers as before


def test_no_member_in_own_pool_is_ignore_and_one_hotspot_per_account():
    m1, m2 = motif('m1'), motif('m2', keys=(('h2', 's2'),))
    pools = {'crypto_macro_zh': [('h1', 's1'), ('h2', 's2')], 'crypto_macro_en': [('h2', 's2')]}
    table, assign = H.decide([m1, m2], ACCTS[:2], UNIV, pools, ok=lambda a, k: True)
    assert table['m1']['crypto_macro_en']['decision'] == 'IGNORE'               # heat never adds a topic
    assert assign['crypto_macro_zh'][0] == 'm1'
    assert table['m2']['crypto_macro_zh'] == {'decision': 'HOLD', 'reason': 'already has its hotspot today', 'fit': 0.27}
    table, assign = H.decide([m1], ACCTS[:1], UNIV, pools, ok=lambda a, k: True, led={'crypto_macro_zh'})
    assert not assign and table['m1']['crypto_macro_zh']['decision'] == 'HOLD'
    table, assign = H.decide([m1], ACCTS[:1], UNIV, pools, ok=lambda a, k: False)
    assert not assign and 'timely' in table['m1']['crypto_macro_zh']['reason']
    discovery = dict(m1, pool='discovery')
    assert H.decide([discovery], ACCTS[:1], UNIV, pools, ok=lambda a, k: True) == ({}, {})


def test_motif_type_counts_members_not_regex_order():
    assert H.motif_topics(['比特币跌破84000美元', 'Bitcoin briefly slides below $84,000']) == ['crypto']
    assert H.motif_topics(['L2网络Abstract宣布停止运营'], [True]) == ['crypto']
    assert H.motif_topics(['WTI原油期货向上触及90美元/桶'])[0] == 'commodities'


# ------------------------------------------------------------------ reality payload

class Plan:
    def __init__(self, m):
        self.by_id = {m['id']: m}


def test_reality_keeps_recent_own_sources_and_a_current_price():
    m = {'id': 'm1', 'title': 'BTC dip', 'members': [
        {'publisher': 'The Block', 'title': 'Bitcoin slides below $84,000', 'url': 'u1', 'adapter': 'feed', 'tier': 'B',
         'published_at': (REF - timedelta(hours=3)).isoformat()},
        {'publisher': '@other (X)', 'title': 'BTC lol', 'url': 'u2', 'adapter': 'x:other', 'tier': 'B',
         'published_at': (REF - timedelta(hours=1)).isoformat()},
        {'publisher': '@mine (X)', 'title': 'BTC dip again', 'url': 'u3', 'adapter': 'x:mine', 'tier': 'B',
         'published_at': (REF - timedelta(hours=2)).isoformat()},
        {'publisher': 'Old', 'title': 'Bitcoin last week', 'url': 'u4', 'adapter': 'feed', 'tier': 'B',
         'published_at': (REF - timedelta(hours=30)).isoformat()}]}
    now = datetime.now(timezone.utc)
    bar = int((now - timedelta(minutes=20)).timestamp())
    rows = [[bar - 3600 * (25 - i), 1, 1, 1, 80000.0 if i < 24 else 83320.65, 1] for i in range(25)]
    r = H.reality(Plan(m), 'm1', 'acct', REF, x_handles=['mine'],
                  fetchers={'fetch_crypto': lambda *a: {'rows': rows, 'source': 'Binance spot', 'url': 'x'}})
    assert [s['url'] for s in r['recent_sources']] == ['u3', 'u1']             # other handles and >24h dropped
    p = r['price']
    assert p['symbol'] == 'BTC' and p['last_text'] == '83,321' and p['change_pct'] == pytest.approx(4.15, 0.01)
    assert datetime.fromisoformat(p['as_of']) <= now                           # an open bar is never in the future
    lines = H.reality_lines(r)
    assert lines[0].startswith('BTC 83,321 (Binance spot')


def test_reality_lines_ground_a_current_price():
    r = {'price': {'symbol': 'MU', 'last_text': '312.40', 'source': 'Yahoo Finance', 'as_of': '2026-10-07T20:00+00:00',
                   'change_pct': -0.5, 'change_window': '1 trading day'}, 'recent_sources': []}
    body = '美光股价最新报312.40美元。'
    assert 'ungrounded_number' in {f['code'] for f in sg.findings(body, [], {'original_text': 'Micron news.'})}
    src = {'original_text': 'Micron news.\n\n' + '\n'.join(H.reality_lines(r))}
    assert 'ungrounded_number' not in {f['code'] for f in sg.findings(body, [], src)}


def test_compose_source_carries_reality_into_payload_and_grounding():
    from live import compose
    from tests.test_compose import GOOD_BODY, SOURCE, Fake
    seen = {}

    class Spy(Fake):
        def __call__(self, stage, messages, max_tokens):
            if stage == 'compose':
                seen['payload'] = json.loads(messages[-1]['content'])
            return super().__call__(stage, messages, max_tokens)
    body = GOOD_BODY + '美光股价最新报312.40美元。'
    reality = {'as_of': '2026-10-07T22:13+00:00', 'recent_sources': [],
               'price': {'symbol': 'MU', 'last_text': '312.40', 'source': 'Yahoo Finance',
                         'as_of': '2026-10-07T20:00+00:00', 'change_pct': None, 'change_window': '1 trading day'}}
    plain = compose.compose_source(SOURCE, 'zh_industry', Fake(body=body), post_type='data_take')
    assert 'ungrounded_number' in {f['code'] for f in plain['post_checks']}
    result = compose.compose_source(SOURCE, 'zh_industry', Spy(body=body), post_type='data_take', reality=reality)
    assert 'ungrounded_number' not in {f['code'] for f in result['post_checks']}
    assert seen['payload']['reality']['lines'] == ['MU 312.40 (Yahoo Finance, as of 2026-10-07T20:00+00:00)']
    assert 'stale' in seen['payload']['reality']['rule']
    assert result['source_hash'] == SOURCE['source_hash']                      # identity unchanged


# ------------------------------------------------------------------ viral priors + angle boost

def test_viral_priors_are_within_donor_lifts_and_bounded():
    posts = []
    for i in range(60):
        lead = i % 2 == 0
        posts.append({'text': ('$84,000 is the line. ' if lead else 'Thinking about cycles. ') + 'more text',
                      'views': 2000 if lead else 1000, 'rt': 'False', 'reply': 'False'})
    out = vp.compute({'d1': posts, 'd2': posts})
    assert out['en']['lead_number']['lift'] == pytest.approx(2.0) and out['en']['lead_number']['n_donors'] == 2
    boost = vp.angle_boost('en', 'BTC fell to $84,000', priors={'priors': out})
    assert boost['price_structure'] == 1 + vp.MAX_BOOST                        # capped
    assert vp.angle_boost('en', 'no numbers here', priors={'priors': {}}) == {}


def test_angle_boost_only_reorders_own_top_lenses():
    mix = {'macro_liquidity': 0.30, 'price_structure': 0.28, 'cycle_position': 0.2}
    text = 'bitcoin price support and rates liquidity cycle'
    assert angles.assign(mix, text) == angles.assign(mix, text, boost=None) == ('macro_liquidity', 'source_fit')
    assert angles.assign(mix, text, boost={'price_structure': 1.15})[0] == 'price_structure'
    assert angles.assign(mix, text, boost={'data_history': 9.0})[0] == 'macro_liquidity'   # never adds a lens


def test_shipped_viral_priors_have_counts_and_no_text():
    data = json.loads((ROOT / 'live' / 'viral_priors.json').read_text())
    for lang, feats in data['priors'].items():
        for f, v in feats.items():
            assert set(v) == {'lift', 'n_donors', 'n_posts_with', 'iqr'} and v['n_donors'] >= 1
    assert 'text' not in json.dumps(data['priors'])


# ------------------------------------------------------------------ feedback loop

def test_feedback_rates_diffs_and_soft_multipliers(tmp_path):
    def row(i, angle, hot=None):
        return {'id': f'd{i}', 'account_id': 'a1', 'angle': {'id': angle}, 'body': f'draft {i}\nline two',
                **({'hotspot': {'motif_id': 'm', 'type': hot}} if hot else {})}
    decided = [('2026-10-08', row(1, 'flows_etf', 'crypto'), {'action': 'approve'}),
               ('2026-10-08', row(2, 'flows_etf', 'crypto'), {'action': 'published', 'text': 'draft 2\nline 2!'}),
               ('2026-10-08', row(3, 'flows_etf'), {'action': 'approve'}),
               ('2026-10-08', row(4, 'price_structure'), {'action': 'hold', 'note': 'stale'}),
               ('2026-10-08', row(5, 'price_structure'), {'action': 'rewrite'}),
               ('2026-10-08', row(6, 'price_structure'), {'action': 'hold'}),
               ('2026-10-08', row(7, 'price_structure'), {'action': 'edit', 'text': 'draft 7 edited'})]
    res = feedback.build(decided)
    a1 = res['accounts']['a1']
    assert a1['overall']['n'] == 6 and a1['angle']['flows_etf'] == {'approve_rate': 0.8, 'n': 3}
    assert a1['motif']['hot:crypto']['n'] == 2 and a1['motif']['regular']['n'] == 4
    assert [e['draft_id'] for e in res['edits']] == ['d2', 'd7'] and '+line 2!' in res['edits'][0]['diff']
    feedback.write(res, store=tmp_path)
    priors = feedback.load(store=tmp_path)
    assert (tmp_path / 'style_examples' / 'a1.jsonl').read_text().count('\n') == 2
    up, down = feedback.angle_multiplier(priors, 'a1', 'flows_etf'), feedback.angle_multiplier(priors, 'a1', 'price_structure')
    assert 1.0 < up <= 1 + feedback.MAX_SHIFT and 1 - feedback.MAX_SHIFT <= down < 1.0
    assert feedback.motif_multiplier(priors, 'a1', 'crypto') == 1.0           # n=2 < MIN_N: no prior yet
    assert feedback.angle_multiplier(priors, 'nobody', 'flows_etf') == 1.0


def test_feedback_collect_joins_decisions_with_inbox_rows(tmp_path):
    (tmp_path / 'dec').mkdir()
    (tmp_path / 'inbox' / '2026-10-08').mkdir(parents=True)
    (tmp_path / 'dec' / '2026-10-08.json').write_text(json.dumps(
        {'day': '2026-10-08', 'decisions': {'d1': {'id': 'd1', 'action': 'approve'}, 'gone': {'action': 'hold'}}}))
    (tmp_path / 'inbox' / '2026-10-08' / 'd1.json').write_text(json.dumps({'id': 'd1', 'account_id': 'a1'}))
    got = feedback.collect(tmp_path / 'dec', tmp_path / 'inbox')
    assert [(d, r['id'], x['action']) for d, r, x in got] == [('2026-10-08', 'd1', 'approve')]


def test_published_is_an_admin_action():
    aad = _script('apply_admin_decisions')
    assert aad.clean({'id': 'd1', 'action': 'published'})['action'] == 'published'
    ops = _script('build_ops_dashboard')
    drafts = [{'id': 'd1', 'text': 'x', 'parts': None, 'status': 'HOLD', 'note': 'n'}]
    assert ops.apply_decisions(drafts, {'d1': {'action': 'published'}})[0]['status'] == 'draft_ready'
    js = (ROOT / 'scripts' / 'ops_admin' / 'api' / 'decisions.js').read_text()
    assert "'published'" in js


# ------------------------------------------------------------------ dashboards + inbox row

def test_dashboards_tag_hotspot_drafts():
    ops = _script('build_ops_dashboard')
    row = {'hotspot': {'title': '比特币跌破84000美元', 'publisher_count': 4, 'account_source_count': 10}}
    media = ops.media_of(row)
    assert media['hotspot'] == '比特币跌破84000美元' and '4 家来源' in media['hotspot_meta']
    assert ops.media_of({})['hotspot'] == ''
    admin = (ROOT / 'scripts' / 'build_admin_console.py').read_text()
    assert '热点</span>' in admin and '热点母题' in admin and 'data-a="published"' in admin
    assert '热点</span>' in (ROOT / 'scripts' / 'build_ops_dashboard.py').read_text()
    from backend.compose_inbox import render
    page = render([{'id': 'd1', 'account_id': 'a', 'name': 'n', 'lang': 'zh', 'text': 't', 'body': 't',
                    'hotspot': {'title': '比特币跌破84000美元'}}], '2026-10-08')
    assert '【热点】' in page and '比特币跌破84000美元' in page


def test_inbox_row_carries_hotspot_tag_and_reality():
    dc = _script('daily_compose')
    pick = {'post_format': {}, 'suggested_post_time_london': '', 'angle_why': '', 'shared_event_with': [],
            'source_id': 's', 'hotspot': {'motif_id': 'm1', 'title': 'T', 'type': 'crypto'},
            'reality': {'as_of': 'x', 'recent_sources': []}}
    acct = {'id': 'crypto_macro_en', 'no': 11, 'name': 'x', 'beat': 'b', 'lang': 'en'}
    row = dc.inbox_row({'plan': pick, 'body': 'b', 'text': 'b', 'spend_usd': 0}, acct,
                       __import__('datetime').date(2026, 10, 8), 'run')
    assert row['hotspot']['motif_id'] == 'm1' and row['reality']['as_of'] == 'x'
    plain = dict(pick)
    plain.pop('hotspot')
    assert 'hotspot' not in dc.inbox_row({'plan': plain, 'body': 'b', 'text': 'b', 'spend_usd': 0}, acct,
                                         __import__('datetime').date(2026, 10, 8), 'run')


# ------------------------------------------------------------------ flag off

def test_flag_off_is_the_old_selection(monkeypatch):
    dc = _script('daily_compose')
    monkeypatch.setenv('FD_HOTSPOT', '0')
    assert not H.enabled()
    assert dc.hotspot_plan(None, {}, [], {}, __import__('datetime').date(2026, 10, 8), REF) is None
    assert dc.angle_boost(None, 'a', 'en', []) is None
    monkeypatch.setenv('FD_HOTSPOT', '1')
    assert H.enabled()


def test_hotspot_plan_failure_is_not_fatal(monkeypatch):
    dc = _script('daily_compose')
    monkeypatch.setenv('FD_HOTSPOT', '1')
    monkeypatch.setattr(H, 'plan_day', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    monkeypatch.setattr(dc.compose_inbox, 'rows', lambda day: [])
    assert dc.hotspot_plan(None, {}, [], {}, __import__('datetime').date(2026, 10, 8), REF) is None


def test_cached_merge_is_remapped_through_member_keys():
    a, b, c = mat(1, 'Abstract L2 shuts down'), mat(2, 'Abstract wallet funds withdrawn'), mat(3, 'Gold swings')
    first = [('c0', [0]), ('c1', [1]), ('c2', [2])]
    members = H._members(first, [a, b, c])
    merge = {'groups': [{'ids': ['c0', 'c1'], 'title_en': 'Abstract shuts down'}]}
    # a later run the same day: one new material in front shifts every positional id
    later_mats = [c, mat(4, 'New item'), a, b]
    later = [('c0', [0]), ('c1', [1]), ('c2', [2]), ('c3', [3])]
    got = H.remap_merge(merge, members, later, later_mats)
    assert got['groups'][0]['ids'] == ['c2', 'c3']
    assert H.remap_merge(merge, None, later, later_mats) is None
