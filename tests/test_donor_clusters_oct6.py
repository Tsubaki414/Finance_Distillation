"""Oct 6 (Fiona 13:21-13:32): per-account donor clusters, cluster language habits, catchphrase cap, hedge-only removal."""
import json
from pathlib import Path

from live import compose, compose_shapes, hedge, language_habits as lh, qa_levels, registry, zh_register as zr
from tests.test_compose import Fake, GOOD_BODY, SOURCE, UNITS

ACCOUNTS = json.loads(Path('live/accounts.json').read_text())['accounts']


def test_every_account_has_a_cluster_of_at_least_three_real_donors():
    roster = registry.load_donor_roster()
    for acc in ACCOUNTS:
        if acc['id'] == 'en_morris_archive':
            continue   # source-voice archive (aphorism_translation), no donor imitation
        persona = registry.persona_for_account(acc['id'])
        name = persona.raw['donor_cluster']
        assert name == 'acct_' + acc['id']
        cluster = roster['persona_clusters'][name]
        assert len(cluster['donors']) >= 3
        assert abs(sum(d['weight'] for d in cluster['donors']) - 1) < 0.01
        for d in cluster['donors']:
            info = roster['donors'][d['handle'].lower()]
            assert info['lang'] == acc['lang'] and info['verified'] and info['donor_fit'] == 'voice'
            assert d['why']
        assert cluster['previous_cluster'] in roster['persona_clusters']
        assert acc['donor_cluster']['cluster'] == name
        assert [d['handle'] for d in acc['donor_cluster']['donors']] == [d['handle'] for d in cluster['donors']]


def test_previous_single_donor_is_kept_in_cluster_and_history():
    for acc in ACCOUNTS:
        ld = acc.get('language_donor')
        if not ld:
            continue
        handles = {d['handle'].lower() for d in acc['donor_cluster']['donors']}
        assert ld['handle'].lower() in handles
        assert any(h.get('handle') == ld['handle'] for h in acc['language_donor_history'])


def test_enabled_zh_accounts_do_not_share_donors():
    roster = registry.load_donor_roster()['persona_clusters']
    a = {d['handle'] for d in roster['acct_zh_macro']['donors']}
    b = {d['handle'] for d in roster['acct_zh_industry']['donors']}
    assert not a & b


def test_language_card_has_cluster_habits_without_donor_text():
    for pid in ('zh_macro', 'zh_industry'):
        card = lh.load_card(registry.persona_for_account(pid))
        for key in ('sentence_length', 'post_length_mix', 'openers', 'closers', 'connectives',
                    'particles_per_1k_cjk', 'reason_markers', 'implication_markers', 'catchphrases'):
            assert card.get(key), (pid, key)
        assert card['sentence_length']['p25'] <= card['sentence_length']['median'] <= card['sentence_length']['p75']
        assert not any(k in card for k in ('reason_examples', 'implication_examples', 'anchor_posts'))
        text = json.dumps(card, ensure_ascii=False)
        assert '买美股上' not in text and '@' not in text   # sponsor tails stripped before measuring


def test_strip_promo_drops_sponsor_lines():
    t = '油价回落，加息概率下来了。\n\n@BITstocks_CN 买美股上BIT，10000+ 只美股与 ETF，真实持仓，享股息分红。'
    assert lh.strip_promo(t) == '油价回落，加息概率下来了。'


class _P:
    persona_id = 'zh_test'
    lang = 'zh'
    raw = {}
    donor_weights = {'a': 0.5, 'b': 0.5}


def _posts_dir(tmp_path):
    rows = {'a': ['美联储这次不加息主要是因为就业数据太弱了，市场其实早就猜到了。所以美债收益率回落，股市也跟着松了口气。今天的数据比预期差一点。'] * 3,
                 'b': ['油价跌了不少，通胀压力小了，所以降息预期又回来了吧。因为供给恢复得比想象快，需求那边也没那么强。股票估值也跟着修复。'] * 3}
    for h, texts in rows.items():
        (tmp_path / f'{h}.jsonl').write_text('\n'.join(json.dumps({'id': f'{h}{i}', 'text': t}, ensure_ascii=False)
                                                       for i, t in enumerate(texts)))
    return tmp_path


def test_payload_card_rotates_real_examples_and_lists_recent_catchphrases(tmp_path, monkeypatch):
    d = _posts_dir(tmp_path)
    card = lh.build_card(_P(), posts_dir=d)
    card['catchphrases'] = {'a': ['市场其实'], 'b': []}
    monkeypatch.setattr(lh, 'load_card', lambda persona: card)
    lh._CACHE.clear()
    out = lh.payload_card(_P(), seed='s1', recent_bodies=['市场其实很平静。'], posts_dir=d)
    assert out['reason_examples'] and all(e['handle'] in ('a', 'b') for e in out['reason_examples'])
    assert len({e['handle'] for e in out['anchor_posts']}) == len(out['anchor_posts'])
    assert out['catchphrase_cap']['used_recently'] == ['市场其实']
    assert 'never copy' in out['use']


def test_catchphrase_findings(monkeypatch):
    card = {'catchphrases': {'a': ['说实话吧'], 'b': ['算一笔账']}}
    monkeypatch.setattr(lh, 'load_card', lambda persona: card)
    p = _P()
    assert lh.catchphrase_findings('利率还要降。', p) == []
    assert lh.catchphrase_findings('说实话吧，利率还要降。', p, ['算一笔账，利率还要降。']) == []
    assert lh.catchphrase_findings('说实话吧，利率还要降。', p, ['说实话吧，美元弱。'])[0]['code'] == 'catchphrase_repeat'
    assert lh.catchphrase_findings('说实话吧，算一笔账。', p)[0]['code'] == 'catchphrase_repeat'
    assert qa_levels.level({'code': 'catchphrase_repeat'}, frame_found=True) == 'soft'


def test_hedge_only_sentences():
    base = '美联储12月再加一次息就结束。核心CPI月率0.3%。'
    for hedge_line in ('当然这不构成投资建议。', '当然也有可能只是短期波动。', '现阶段盲目追高依然容易吃亏，多头需要留足安全边际。',
                       '如果12月不加息，那就说明这轮紧缩并没有真正结束。', 'Not financial advice.', 'Time will tell.'):
        assert hedge.hedge_findings(base + hedge_line)[0]['code'] == 'hedge_only', hedge_line
    # a condition with a concrete new number advances the argument and stays
    assert hedge.hedge_findings(base + '如果10月CPI回到3.5%以上，12月还得再加一次。') == []
    assert hedge.hedge_findings('The hike is the last one. If core PCE prints above 0.4% on Oct 30, the cut is off.') == []
    assert qa_levels.level({'code': 'hedge_only'}, frame_found=True) == 'soft'


def test_prompts_carry_hedge_rule_and_relaxed_falsifier():
    assert 'No hedge-only sentences' in compose.COMPOSE
    assert '删掉只为防止被质疑而存在的句子' in zr.SYSTEM_ZH
    assert 'what would change it' not in compose.COMPOSE
    rule = compose_shapes.payload_block({'id': 'short_thread'}, 'en', {'min': 100, 'max': 400})['ending_rule']
    assert 'only if' in rule and 'disclaimer' in rule
    assert '除非…否则…依然成立' in compose_shapes.SHAPES['short_thread']['zh']
    assert 'concrete falsifiers' not in lh.GUIDANCE


class Capture(Fake):
    def __call__(self, stage, messages, max_tokens):
        out = super().__call__(stage, messages, max_tokens)
        if stage == 'compose':
            self.payload = json.loads(messages[-1]['content'])
        return out


def test_compose_payload_has_cluster_habits():
    fake = Capture(body=GOOD_BODY, units=UNITS)
    compose.compose_source(SOURCE, 'zh_macro', fake, post_type='data_take', exemplars=True)
    habits = fake.payload['persona']['language_habits']
    assert habits['cluster'] == 'acct_zh_macro'
    assert 'catchphrase_cap' in habits and 'reason_markers' in habits
    donors = set(registry.persona_for_account('zh_macro').donor_weights)
    assert all(e['handle'] in donors for e in habits.get('anchor_posts') or [])
