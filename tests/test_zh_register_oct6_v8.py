"""Oct 6 v8: Carry on. ban, question-form 不是X而是Y, intensifiers, crowd attribution, long-draft
line breaks, coherence reserve, entity-family ledger gate, fill-in arbitration, ingest fair share."""
import json
import sys
from pathlib import Path

import pytest

from live import zh_register as zr
from live.view_ledger import ViewLedger
from ml import budget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def test_en_macro_card_has_no_carry_on():
    card = json.loads((ROOT / 'live/personas/signature_cards/en_macro.json').read_text())
    blob = json.dumps(card.get('lexicon')) + json.dumps(card.get('closings'))
    assert 'Carry on' not in blob
    assert 'Carry on.' in card.get('lexicon_dropped', [])


@pytest.mark.parametrize('text', ['只是一次降息？人家这是在给衰退买保险。', '你以为是AI泡沫？其实是电力瓶颈。'])
def test_question_form_zh_flagged(text):
    assert any('AI 套话' in f['detail'] for f in zr.register_findings(text))
    assert '「不是X而是Y」句式' in zr.stance_view_findings(text)


def test_question_form_en_flagged_and_plain_question_not():
    assert zr.en_template_findings("Just a rate cut? No, it's insurance against a recession.")
    assert not zr.en_template_findings('Will the Fed cut in December? I doubt it.')


def test_intensifiers():
    assert zr.register_findings('资金死死按住了长端。')                    # any strong hit
    assert zr.register_findings('疯狂加仓，情绪拉满。')                     # two mild hits
    assert not zr.register_findings('有人在疯狂加仓，我没跟。')            # one mild hit is donor-normal


def test_crowd_action_people_only():
    assert zr.market_feeling_findings('大家都在盯着周五的非农。')
    assert zr.market_feeling_findings('散户都在押注降息。')
    assert not zr.market_feeling_findings('资金都在追AI。')                 # flows: donors use them


V7ZI_LIKE = '\n'.join(['亚洲数据中心支出长期会涨', '但能不能守住定价权', '要看供给纪律',
                       '普华永道估计到2050年', '亚洲数据中心支出能到8.2万亿美元', '大头砸在GPU和服务器上',
                       '需求曲线很陡', '可利润不一定跟着走', '产能一旦放得比需求快', '价格就会先崩',
                       '银行已经在抢着做GPU融资', '这本身说明抵押品很热', '热的东西最怕供给追上来',
                       '我现在的态度是长期看多需求', '但不追硬件厂的估值', '等供给数据出来再说',
                       '三季度的出货和库存', '比任何长期预测都重要', '尤其是二线厂', '它们扩产最积极',
                       '去年存储也是这么走的', '先是需求故事', '然后是扩产', '最后是降价', '这次未必一样', '但我不赌它不一样'])


def test_line_breaks_long_one_clause_lines_flagged():
    assert [f['code'] for f in zr.line_break_findings(V7ZI_LIKE)] == ['zh_line_breaks']
    paragraphs = V7ZI_LIKE.replace('\n', '，')
    paragraphs = paragraphs.replace('银行已经', '。\n\n银行已经').replace('我现在的', '。\n\n我现在的') + '。'
    assert zr.line_break_findings(paragraphs) == []
    assert zr.line_break_findings('短帖\n一行\n一句') == []                  # short drafts exempt


def test_coherence_reserve_blocks_polish_not_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'LEDGER', tmp_path / 'spend.json')
    budget.set_cap(0.5)
    budget.set_advisory_hold(0.45)
    try:
        assert budget.remaining() == pytest.approx(0.5 - budget.spent())
        with budget.advisory():
            assert budget.remaining() == pytest.approx(0.05 - budget.spent())
    finally:
        budget.set_advisory_hold(0.0)


def _row(subject, direction, view, vid):
    return {'id': vid, 'subject': subject, 'direction': direction, 'account_view': view, 'status': 'active'}


def test_fed_hike_does_not_contradict_china_easing(tmp_path):
    led = ViewLedger('zh_macro', tmp_path)
    led.record({'decision': 'adapt', 'account_view': '货币政策仍以流动性和结构性工具为主，年内降息降准空间有限。',
                'view': {'subject': 'China interest rates and reserve requirement ratio', 'direction': 'lower',
                         'conviction': 'medium', 'horizon': 'quarters'}}, unit_ids=['u1'], source_ids=['s1'])
    stance = {'account_view': '美联储12月加息一次后暂停。',
              'view': {'subject': 'Federal Reserve policy rate', 'direction': 'higher'}}
    assert led.contradictions(stance) == []
    same = {'account_view': '人民银行年内还会再降准。',
            'view': {'subject': 'China interest rates and reserve requirement ratio', 'direction': 'higher'}}
    assert [f['code'] for f in led.contradictions(same)] == ['contradicts_prior_view']


def test_entity_family_match():
    from live.finance_aliases import entity_family_match
    assert not entity_family_match({'@fed', '@rates'}, {'@rates'})
    assert not entity_family_match({'@fed'}, {'@pboc'})
    assert entity_family_match({'@fed', 'x'}, {'@fed'})
    assert entity_family_match({'@rates'}, {'@rates', 'y'})


def _draft(account, subject, direction, view, source_id, units):
    return {'account_id': account, 'key': account, 'stance': {'account_view': view,
            'view': {'subject': subject, 'direction': direction}},
            'source': {'id': source_id, 'source_id': 'wallstreetcn'},
            'units': [{'unit_id': u} for u in units], 'status': 'needs_review'}


def test_fill_in_arbitrates_with_carried_batch(tmp_path):
    import demo_matrix_compose as d
    batch = tmp_path / 'v7'
    (batch / 'drafts').mkdir(parents=True)
    carried = [_draft('en_industry', 'Asia data center hardware demand', 'bullish',
                      'Asia data center hardware demand will grow through 2050.', 'wscn-1', ['cu-a', 'cu-b']),
               _draft('en_macro', '30-year Treasury yield', 'higher', 'Long yields keep rising.', 'wscn-2', ['cu-c'])]
    for c in carried:
        (batch / 'drafts' / (c['account_id'] + '.json')).write_text(json.dumps(c))
    new = _draft('zh_industry', 'Asia data center spending', 'higher', '亚洲数据中心支出长期会涨。', 'wscn-1', ['cu-a'])
    loaded = d.load_fill_into(batch, ['zh_industry'])
    assert {c['account_id'] for c in loaded} == {'en_industry', 'en_macro'}
    out = d.arbitrate_with_carried([new], loaded)
    assert len(out) == 1 and out[0]['arbitration']['status'] == 'HOLD'
    assert out[0]['arbitration']['reassigned_to'] == 'en_industry'
    # same publisher, different article: not one event
    other = _draft('zh_industry', 'HBM pricing', 'higher', 'HBM 价格还会涨。', 'wscn-9', ['cu-z'])
    assert d.arbitrate_with_carried([other], loaded)[0]['arbitration']['status'] == 'WRITE'


def test_direction_polarity_compatible():
    from live.claim_arbitration import direction_compatible
    assert direction_compatible('bullish', 'higher') is True
    assert direction_compatible('bullish', 'lower') is not True
    assert direction_compatible('higher', 'lower') is False


def _task(channel, sid, rank=0, units=None):
    return ({'id': channel}, {'id': sid, 'source_id': channel}, units, channel, [sid], rank)


def test_ingest_order_fair_share_and_prior_deferred(monkeypatch):
    from live import ingest_priority as ip
    hints = {'chA': ['macro_rates_en'], 'chB': ['crypto_macro_en'], 'chC': ['crypto_macro_zh'], 'chP': ['macro_rates_en']}
    monkeypatch.setattr(ip, 'channel_personas', lambda cid, s=None: hints.get(cid, [ip.UNKNOWN]))
    tasks = [_task('chA', 'a1', 0), _task('chA', 'a2', 1), _task('chA', 'a3', 2), _task('chB', 'b1', 0),
             _task('chC', 'c1', 0), _task('chP', 'p1', 0), _task('chX', 'x1', 0, units=[{'u': 1}])]
    fresh = {'macro_rates_en': 69, 'crypto_macro_en': 33, 'crypto_macro_zh': 17}
    order, plan = ip.order_tasks(tasks, fresh, {'a3'}, floor=1, legacy_priority=lambda c, s: 3)
    ids = [t[1]['id'] for t in order]
    assert ids[0] == 'x1'                                   # pre-extracted: free
    assert ids[1:4] == ['c1', 'b1', 'a3']                   # fewest fresh first; prior-deferred first in persona
    assert ids[4] in ('a1', 'p1') and plan[3]['prior_deferred']


def test_previous_deferred_skips_dry_runs(tmp_path):
    from live import ingest_priority as ip
    (tmp_path / '20261006.json').write_text(json.dumps({'status': 'ok', 'deferred': [{'id': 'a', 'channel': 'c'}]}))
    (tmp_path / '20261007.json').write_text(json.dumps({'status': 'dry_run', 'deferred': []}))
    prev = ip.previous_deferred(tmp_path)
    assert prev['run'] == '20261006.json' and prev['ids'] == {'a'}


def test_daily_ingest_prior_deferred_bypasses_channel_cap(tmp_path):
    from live.adapters.common import make_source
    from live.daily_ingest import run
    runs = tmp_path / 'runs'
    runs.mkdir()
    (runs / '20261006.json').write_text(json.dumps({'status': 'ok', 'deferred': [{'id': 's3', 'channel': 'feed'}]}))
    seen = []

    def extract(s):
        seen.append(s['id'])
        return [{'unit_id': s['id'], 'source_hash': s['source_hash'], 'statement': s['original_text'], 'kind': 'fact',
                 'numbers': [], 'licence_tier': 'A', 'usage': 'quote', 'speaker': s['publisher']}]
    srcs = [make_source(id=f's{i}', source_id='sec_edgar', text=f's{i} distinct evidence', publisher=f's{i}',
                        title=f's{i}', url=f'https://example.test/s{i}', published_at='2026-10-04', adapter='edgar')
            for i in range(4)]
    r = run(store=tmp_path / 'store', runs_dir=runs, inbox=tmp_path / 'inbox', state_path=tmp_path / 'state.json',
            no_dashboard=True, per_channel_max=1, fetchers={'feed': lambda: {'sources': srcs}}, extract=extract,
            backup=lambda: None, refresh=lambda: None)
    assert seen[0] == 's3' and set(seen) == {'s0', 's3'}
    assert r['ordering']['previous_run'] == '20261006.json' and r['ordering']['prior_deferred_gathered'] == 1


def test_backup_failure_keeps_rejected_slot():
    import demo_matrix_compose as d
    rej = {'stance': {'decision': 'reject', 'account_view': ''}, 'status': 'skipped'}
    kept = d._keep_rejected(rej, 'zh_macro', [{'source_id': 's1'}], 'BudgetExceeded')
    assert kept['key'] == 'zh_macro' and kept['mode'] == 'live' and kept['selection_fallback']['rejected']
    assert d._keep_rejected(None, 'zh_macro', [], 'x') is None
    assert d._keep_rejected({'stance': {'decision': 'adapt'}}, 'zh_macro', [], 'x') is None


def test_continue_batch_excludes_rejected_sources(tmp_path):
    import demo_matrix_compose as d
    prev = tmp_path / 'prev'
    (prev / 'drafts').mkdir(parents=True)
    (prev / 'drafts' / 'zh_macro.json').write_text(json.dumps(
        {'source_id': 'reportgem-1', 'stance': {'decision': 'reject'},
         'selection_fallback': {'rejected': [{'source_id': 'doc-2'}]}}))
    out = tmp_path / 'out'
    out.mkdir()
    assert {'reportgem-1', 'doc-2'} <= d.continue_batch(prev, out)


def test_direction_hedge_prefix_coerced():
    from live.content_units import coerce_view
    v = coerce_view({'direction': 'conditionally_bullish', 'subject': 'x', 'conviction': 'medium', 'horizon': 'quarters'})
    assert v['direction'] == 'bullish'


def test_stance_soft_contracts():
    from live.stance import _validate_stance_value
    view = {'direction': 'higher', 'subject': 'Fed policy rate', 'conviction': 'medium', 'horizon': 'months',
            'reasoning': ['Williams said no urgency.']}
    unit = {'unit_id': 'u1', 'source_spans': [{'exact_text': 'Williams said no urgency.'}], 'view': view}
    value = {'decision': 'adapt', 'account_view': '美联储不急着再加息。', 'supporting_unit_ids': ['u1'],
             'rationale': 'r', 'confidence': 0.6, 'view': dict(view), 'revises_view_id': 'cu-not-a-view'}
    out = _validate_stance_value(value, unit, view, [], {'u1'})
    assert out['decision'] == 'take' and out['adapt_unchanged']
    assert out['revises_view_id'] is None and out['revises_view_id_dropped'] == 'cu-not-a-view'


def test_question_opener_rolling_cap():
    q = '短期内继续加息的概率已经大幅降低，难道还要硬加？威廉姆斯表态放缓步伐后，内部态度已经很明显。'
    recent = ['美联储真停得下来吗？我看未必。', '今天的PMI有点意思。', '我对这轮反弹没什么信心。']
    assert zr.opening_findings(q, {'move': 'question'}, recent)              # question already in last 3
    assert zr.opening_findings(q, {'move': 'statement'}, [])                 # not assigned
    assert not zr.opening_findings(q, {'move': 'question'}, ['今天的PMI有点意思。'])
    from live import registry
    p = registry.persona_for_account('zh_macro')
    if zr.opener_distribution(p)['shares']:
        assert all(zr.choose_opening_move(p, f's{i}', recent)['move'] != 'question' for i in range(40))
