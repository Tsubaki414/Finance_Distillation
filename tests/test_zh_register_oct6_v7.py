"""Oct 6 v7: 别… opener root cause (opening moves from donor distribution), ZH sentence length,
date framing, stance copy, optional zh_industry frame, long-shape length band, synthetic ledger rows,
per-slot budget sub-caps."""
import json

import pytest

from live import compose, compose_shapes as cs, registry, zh_register as zr
from live.view_ledger import ViewLedger, is_synthetic
from tests.test_zh_register_oct6_v5 import SeqFake, STANCE, PLAIN_BODY, _iso

V6_OPENERS = ['别指望美联储现在就会停手，未来几个月政策利率还得往上走。',
              '别看制造业PMI重回扩张区间、生产也在加速，新订单其实在掉。',
              '别把端侧部署当成实验室里的玩具。', '别被表面上还过得去的累计数据骗了。']


def test_opener_moves_classify():
    assert all(zr.opener_move(t) == 'neg_imperative' for t in V6_OPENERS)
    assert zr.opener_move('Synopsys终于把老旧的固定授权费，变成了跟出货量挂钩的分成。') == 'statement'
    assert zr.opener_move('美联储真停得下来吗？我看未必。') == 'question'
    assert zr.opener_move('今天的PMI有点意思。') == 'news_led'
    assert zr.opener_move('我对这轮反弹没什么信心。') == 'first_person'


def _persona(a):
    p = registry.persona_for_account(a)
    if not zr.opener_distribution(p)['shares']:
        pytest.skip('donor posts not available')
    return p


@pytest.mark.parametrize('account', ['zh_macro', 'zh_industry'])
def test_donor_negation_imperative_is_rare_and_rarely_assigned(account):
    p = _persona(account)
    shares = zr.opener_distribution(p)['shares']
    assert shares.get('neg_imperative', 0) < 0.02 and shares['statement'] > 0.5
    moves = [zr.choose_opening_move(p, f's{i}')['move'] for i in range(60)]
    assert moves.count('neg_imperative') <= 2
    assert 'conditional' not in moves and 'number_led' not in moves   # conflict with line1 / signature rules
    assert len(set(moves)) >= 3


def test_opening_move_examples_are_real_donor_lines():
    from live.exemplars import load_posts
    p = _persona('zh_macro')
    move = zr.choose_opening_move(p, 'seed-x')
    texts = [x.get('text') or '' for h in p.donor_weights for x in load_posts(h)]
    for ex in move['examples']:
        assert any(ex in t for t in texts)


def test_recent_move_is_damped():
    p = _persona('zh_macro')
    recent = ['今天的PMI有点意思。'] * 3   # news_led three times
    base = sum(zr.choose_opening_move(p, f'k{i}')['move'] == 'news_led' for i in range(200))
    damped = sum(zr.choose_opening_move(p, f'k{i}', recent)['move'] == 'news_led' for i in range(200))
    assert damped < base or base == 0


def test_opening_findings():
    assert zr.opening_findings(V6_OPENERS[0], {'move': 'statement'})[0]['code'] == 'opener_move'
    assert zr.opening_findings(V6_OPENERS[0], {'move': 'neg_imperative'}) == []
    q = '美联储真停得下来吗？我看未必。'
    assert zr.opening_findings(q, {'move': 'statement'}, ['谁能想到呢？', '这是真的吗？', '还行'])[0]['code'] == 'opener_move'
    assert zr.opening_findings('利润增速掉得很快。', {'move': 'statement'}, ['利润还行。'] * 3) == []


def test_en_opener_family_feeds_regen():
    recent = [{'text': "Don't expect the Fed to stop."}]
    assert cs.recent_opener_findings("Don't buy the bounce.", recent)[0]['code'] == 'opener_move'
    assert cs.recent_opener_findings('The bounce is thin.', recent) == []


# ---------- sentence length ----------

def test_sentence_findings_and_donor_band():
    long_body = ('8月单月利润增速只有4.2%这个数字和前八个月15.7%的累计增速放在一起看完全不是一回事情。\n'
                 '今年工业企业的利润增长基本都已经压在了上半年而下半年的动能正在明显地快速减弱下去。')
    assert zr.sentence_findings(long_body)[0]['code'] == 'zh_sentence_length'
    assert zr.sentence_findings('利润掉得很快。\n8月只涨了4.2%。\n下半年难了。') == []
    band = zr.donor_sentence_band(_persona('zh_macro'))
    assert 15 <= band['median'] <= 26     # CJK chars/sentence, not the voice-card 32


def test_stance_view_findings_length_and_jargon():
    v6 = 'Synopsys的收入模式正在从固定授权费转向随芯片出货量挂钩的分成结构，定价权能否在产能扩张中守住是这个逻辑的核心变量。'
    probs = zr.stance_view_findings(v6)
    assert any('> 35' in p for p in probs) and any('核心变量' in p for p in probs)
    assert zr.stance_view_findings('工业利润下半年明显泄气了') == []
    assert any('别' in p for p in zr.stance_view_findings('别指望美联储停手'))


def test_stance_copy_findings():
    thesis = 'Synopsys的收入模式正在从固定授权费转向随芯片出货量挂钩的分成结构，定价权能否在产能扩张中守住是这个逻辑的核心变量。'
    body = 'Synopsys终于改了收费方式。\n定价权在产能扩张中能否守住成了这个逻辑的核心变量。'
    f = zr.stance_copy_findings(body, thesis)
    assert f and f[0]['code'] == 'stance_copy' and '核心变量' in f[0]['detail']
    assert zr.stance_copy_findings('Synopsys改成按出货量分成了。\n这招能不能守住价格还得看。', thesis) == []


# ---------- date framing ----------

def test_date_label_monthly_print():
    u = {'as_of': '2026-08-31', 'published_at': '2026-09-28T00:00:00Z'}
    assert compose.date_label(u, 'zh') == '8月数据，9月28日公布'
    assert compose.date_label(u, 'en') == 'August data, published Sep 28'
    assert compose.date_label({'as_of': '2026-10-02'}, 'zh') == '10月2日'
    assert compose.date_label({}, 'zh') is None
    assert '回看历史' in zr.SYSTEM_ZH and 'date_label' in zr.SYSTEM_ZH
    assert 'looking back at history' in compose.COMPOSE


# ---------- zh_industry frame scoping (Fiona decision pending) ----------

def test_frame_optional_when_source_not_about_capacity():
    p = registry.persona_for_account('zh_industry')
    synopsys = [{'statement': 'Synopsys is converting its license business into volume-linked revenue.'}]
    micron = [{'statement': 'Micron says HBM supply stays tight and pricing improves next quarter.'}]
    assert not compose.frame_relevant(p, synopsys) and compose.frame_relevant(p, micron)
    sig = {'hard_constraints': ['第一句就是判断（需求能否撑住供给、定价权能否保住），不是事实。', '全文最多引用 3 个数字。'],
           'openings': ['对定价权泼冷水：直接说证据还撑不起什么', '表面 vs 实质一句定性'], 'closings': [], 'moves': []}
    out = compose.scope_signature_frame(sig)
    assert '可不用' in out['hard_constraints'][0] and out['hard_constraints'][1] == sig['hard_constraints'][1]
    assert '可不用' in out['openings'][0] and out['openings'][1] == sig['openings'][1]
    assert out['frame_scope']


# ---------- long shape length band ----------

def test_length_band_findings():
    long_shape = {'id': 'data_punch', 'length': 'long', 'length_target': {'min': 277, 'max': 399}}
    assert cs.length_band_findings('短' * 114, long_shape)[0]['code'] == 'length_band'
    assert cs.length_band_findings('长' * 260, long_shape) == []
    short = {'id': 'take_short', 'length': 'short', 'length_target': {'min': 83, 'max': 228}}
    assert cs.length_band_findings('长' * 300, short)[0]['code'] == 'length_band'
    assert 'stop early' not in cs.LONG_NOTE['en'] and '提前收住' not in cs.LONG_NOTE['zh']


# ---------- ledger: synthetic rows ----------

def test_synthetic_views_never_recorded_or_used(tmp_path):
    led = ViewLedger('en_industry', tmp_path)
    st = {'decision': 'adapt', 'account_view': 'AI capex demand needs revenue conversion.',
          'view': {'subject': 'AI capex demand', 'direction': 'neutral'}}
    with pytest.raises(ValueError):
        led.record(st, unit_ids=['synthetic-view'], source_ids=['synthetic-industry'])
    led.path.parent.mkdir(parents=True, exist_ok=True)
    led.path.write_text(json.dumps({'id': 'view-x', 'account_view': 'x', 'subject': 'AI capex demand',
                                    'source_ids': ['synthetic-industry'], 'created_at': '2026-10-06'}) + '\n')
    assert is_synthetic(led.entries(include_synthetic=True)[0])
    assert led.entries() == [] and led.current() == [] and led.related('AI capex demand') == []


def test_fake_result_does_not_write_ledger(tmp_path):
    from scripts import demo_matrix_compose as demo
    led = ViewLedger('en_industry', tmp_path)
    r = demo.fake_result('en_industry', led, 'test')
    assert r['ledger_entry'] is None and led.entries(include_synthetic=True) == []


# ---------- compose integration ----------

BIE_BODY = '别指望存储紧缺马上结束。\n厂商就是不想扩产，价格其实还在涨。\n下游采购节奏得跟着改。'


def test_zh_compose_payload_has_opening_move_and_band_and_regens_bie(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    from tests.test_compose import SOURCE
    fake = SeqFake([BIE_BODY, PLAIN_BODY])
    result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                    stance_output=dict(STANCE), emotion_contract=False)
    block = fake.payloads[0]['zh_register']
    if 'opening_move' not in block:
        pytest.skip('donor posts not available')
    assert block['opening_move']['move'] in zr.ASSIGNABLE and block['sentence_length']['median'] < 28
    vc = fake.payloads[0]['persona'].get('voice_card') or {}
    if 'sentence_length' in vc:
        assert vc['sentence_length']['median'] == block['sentence_length']['median']
    if block['opening_move']['move'] != 'neg_imperative':
        assert 'opener_move' in {f['code'] for f in result['structure_retry']['first_findings']}
        assert result['structure_retry']['kept'] == 'retry'


def test_retry_refused_by_budget_keeps_first_draft(monkeypatch):
    from ml import budget

    def refuse(*a, **k):
        raise budget.BudgetExceeded('slot sub-cap')
    monkeypatch.setattr(compose, '_ask', refuse)
    skips = []
    assert compose._ask_retry(None, 's', {'rewrite_note': 'x'}, [], skips) == ({}, {})
    assert skips and 'sub-cap' in skips[0]['reason']


def test_demo_slot_subcaps(tmp_path, monkeypatch):
    """Each slot gets a fair share of what is left; a refused slot does not stop later slots."""
    from scripts import demo_matrix_compose as demo
    from tests.test_demo_matrix_compose import isolate_globals
    from ml import budget
    isolate_globals(monkeypatch)
    from live import erisedai_distillation_client
    monkeypatch.setattr(demo.compose_ab, 'probe', lambda *a, **k: {'available': True, 'response_model': 'ok'})
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})
    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', lambda *a, **k: object())
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    monkeypatch.setattr(demo, 'select_groups', lambda store, accounts, *_a, **_k: {
        a: [{'unit_id': 'u-' + a}] for a in accounts})
    monkeypatch.setattr(demo, 'evidence_source', lambda group: ({'id': 's'}, []))
    caps, calls = [], []

    def fake_compose(source, account, client, **kw):
        calls.append(account)
        caps.append(round(budget.cap() - budget.spent(), 4))
        if account == demo.ACCOUNTS[0]:
            raise budget.BudgetExceeded('slot 1 over its share')
        raise RuntimeError('stop after cap check')
    monkeypatch.setattr(demo.compose, 'compose_source', fake_compose)
    results = demo.run(tmp_path, 2.5, live=True, command='t')
    assert calls == list(demo.ACCOUNTS)               # slot 1 refusal did not stop the others
    assert caps[0] == pytest.approx(2.5 - 3 * demo.SLOT_MIN_USD, abs=0.01)   # later slots keep their floor
    assert all(c >= demo.SLOT_MIN_USD - 0.01 for c in caps)
    assert all(r.get('slot_cap_usd') for r in results)
    assert budget.cap() == 2.5   # v9: base need per slot; $2.0 would fund only 3 slots (fail loud)


def test_zh_account_view_rewrite_small_call():
    from live import stance
    seen = []

    def fake(stage, messages, max_tokens):
        seen.append((stage, max_tokens, json.loads(messages[-1]['content'])))
        return {'text': json.dumps({'account_view': 'Synopsys改成按出货量分成，这招能不能守住价格还得看'}, ensure_ascii=False),
                'finish_reason': 'stop', 'model': 'f'}
    value = {'account_view': 'Synopsys的收入模式正在从固定授权费转向随芯片出货量挂钩的分成结构，定价权能否在产能扩张中守住是这个逻辑的核心变量。',
             'view': {'subject': 'Synopsys', 'direction': 'neutral', 'horizon': 'months'}}
    meta = stance.zh_account_view_rewrite(fake, value, [])
    assert meta['kept'] == 'retry' and len(zr.CJK.findall(value['account_view'])) <= 35
    assert seen[0][1] == 400 and set(seen[0][2]) == {'account_view', 'problems', 'view'}
    assert stance.zh_account_view_rewrite(fake, {'account_view': '工业利润下半年泄气了'}, []) is None


def test_zh_account_view_rewrite_rejects_new_numbers():
    from live import stance

    def fake(stage, messages, max_tokens):
        return {'text': json.dumps({'account_view': '利润只涨了4.2%，下半年难了'}, ensure_ascii=False),
                'finish_reason': 'stop', 'model': 'f'}
    value = {'account_view': '工业企业利润增长的结构性动能在下半年已经明显减弱，这一格局意味着四季度利润承压。', 'view': {}}
    meta = stance.zh_account_view_rewrite(fake, value, [])
    assert meta['kept'] == 'original' and meta['reject_reason'] == 'new_numbers'


def test_filler_examples_kept_out_of_signature_payload():
    assert cs.strip_filler_examples("A short, flat verdict: 'Carry on.' / 'There is no one left to cut.'") == \
        "A short, flat verdict: 'There is no one left to cut.'"
    assert cs.is_filler('Carry on.') and not cs.is_filler('is the tell')


def _demo_env(monkeypatch, tmp_path):
    from scripts import demo_matrix_compose as demo
    from tests.test_demo_matrix_compose import isolate_globals
    isolate_globals(monkeypatch)
    from live import erisedai_distillation_client
    monkeypatch.setattr(demo.compose_ab, 'probe', lambda *a, **k: {'available': True, 'response_model': 'ok'})
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})
    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', lambda *a, **k: object())
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    return demo


def test_stance_reject_tries_backup_and_batch_size_counts_remaining_slots(tmp_path, monkeypatch):
    demo = _demo_env(monkeypatch, tmp_path)

    def select(store, accounts, selection=None, exclude_sources=(), recent=None, backups=None):
        for a in accounts:
            backups[a] = [[{'unit_id': 'b-' + a}]]
        return {a: [{'unit_id': 'u-' + a}] for a in accounts}
    monkeypatch.setattr(demo, 'select_groups', select)
    monkeypatch.setattr(demo, 'evidence_source', lambda g: ({'id': g[0]['unit_id']}, []))
    seen = []

    def fake_compose(source, account, client, **kw):
        seen.append((account, source['id'], kw['shape_batch_size'], len(kw['shape_batch'])))
        if source['id'] == 'u-' + demo.ACCOUNTS[1]:
            return {'account_id': account, 'stance': {'decision': 'reject', 'rationale': 'not usable'}, 'draft_status': 'not_suitable'}
        return {'account_id': account, 'stance': {'decision': 'adapt'}, 'body': 'x', 'draft_status': 'draft_ready',
                'composition_shape': {'id': 'take_short', 'length': 'short'}}
    monkeypatch.setattr(demo.compose, 'compose_source', fake_compose)
    results = demo.run(tmp_path, 2.0, live=True, command='t')
    second = [s for s in seen if s[0] == demo.ACCOUNTS[1]]
    assert [s[1] for s in second] == ['u-' + demo.ACCOUNTS[1], 'b-' + demo.ACCOUNTS[1]]
    r2 = [r for r in results if r['account_id'] == demo.ACCOUNTS[1]][0]
    assert r2['selection_fallback']['rejected'][0]['source_id'] == 'u-' + demo.ACCOUNTS[1]
    for account, _, size, done in seen:   # size = shapes so far + slots still to run
        idx = demo.ACCOUNTS.index(account)
        assert size == done + (len(demo.ACCOUNTS) - idx)


def test_recent_statements_do_not_push_to_rare_moves():
    import collections
    p = _persona('zh_industry')
    recent = ['利润掉得很快。', '这波涨价还没完。', '端侧推理在加速。']   # statement x3
    c = collections.Counter(zr.choose_opening_move(p, f'r{i}', recent)['move'] for i in range(400))
    assert c['statement'] / 400 > 0.5 and c['question'] / 400 < 0.2
