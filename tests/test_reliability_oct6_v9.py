"""Oct 6 v9 reliability: persona pre-screen, slot budget plan (fail loud), crash-proof batch outputs,
small soft items (ZH emotion devices, EN imperative template, long-shape number budget, overclaim)."""
import json

import pytest

from live import source_prescreen as ps, zh_register as zr
from scripts import demo_matrix_compose as demo
from tests.test_demo_matrix_compose import isolate_globals


def _group(title, view_subject, statement, facts=()):
    src = {'id': title[:8], 'title': title}
    g = [{'unit_id': 'v', 'source': src, 'unit': {'kind': 'view', 'statement': statement,
                                                  'view': {'subject': view_subject, 'reasoning': [statement]}}}]
    g += [{'unit_id': f'f{i}', 'source': src, 'unit': {'kind': 'fact', 'statement': f}} for i, f in enumerate(facts)]
    return g


REJECTED_ZH_INDUSTRY = [
    _group('“AI沙皇”人选定了！白宫成立“超级智能”工作组，计划120天拿出AI监管方案', 'AI监管', '白宫将在120天内拿出AI监管方案。'),
    _group('一向力挺AI的孙正义突然警告：超级智能可能“极其危险”', 'superintelligence risk', '孙正义警告超级智能可能极其危险。'),
    _group('OpenAI「12朝元老」辞职死谏：试错的时代已崩坏！', 'AI safety', 'OpenAI 老员工辞职并警告安全问题。'),
    _group("Zendesk's New CFO Is Built for the Billion-Dollar AI Bet", 'Zendesk CFO hire', 'The CFO hire embeds finance in AI strategy.'),
]


@pytest.mark.parametrize('group', REJECTED_ZH_INDUSTRY)
def test_prescreen_demotes_policy_and_personnel_packets(group):
    assert not ps.prescreen('zh_industry', group)['ok']


def test_prescreen_keeps_industry_evidence_and_orders_stably():
    micron = _group('Micron Technology 8-K', 'HBM demand', 'Micron raised HBM revenue guidance.',
                    ['Revenue rose 40% to $11.3 billion.'])
    lease = _group('纳入6280亿美元表外承诺后，Meta股票“贵了”35%？', 'AI 租赁负债', '超大规模科技公司表外租赁负债上升。',
                   ['未生效租约1.0万亿美元。'])
    assert ps.prescreen('zh_industry', micron)['ok'] and ps.prescreen('zh_industry', lease)['ok']
    options = _group('2 option ideas from the Robinhood Summit', 'INTC vol', 'Sell INTC straddles on rich implied vol.')
    assert not ps.prescreen('en_industry', options)['ok']
    ordered, screens = ps.order('zh_industry', [REJECTED_ZH_INDUSTRY[0], micron, REJECTED_ZH_INDUSTRY[1], lease])
    assert ordered[:2] == [micron, lease] and [s['ok'] for s in screens] == [True, True, False, False]
    jpm = _group('The J.P. Morgan View', 'Fed path', 'The Fed delivers a second and final hike in December.',
                 ['Core PCE 3.0%.'])
    assert not ps.prescreen('zh_macro', jpm)['ok'] and ps.prescreen('en_macro', jpm)['ok']


def test_budget_plan_fails_loud_and_proposes_cap():
    m = dict(demo.COST_DEFAULTS, source='test')
    low = demo.budget_plan(2.0, 4, m)
    assert low['status'] == 'INSUFFICIENT' and low['slots_funded'] == 3
    assert any('FAIL LOUD' in line for line in demo.plan_lines(low))
    mid = demo.budget_plan(2.5, 4, m)
    assert mid['status'] == 'OK_BASE_SHARED_BACKUP' and mid['slots_funded'] == 4 and mid['backups_covered'] >= 1
    assert 3.0 <= mid['cap_for_full_guarantee_usd'] <= 3.2
    assert demo.budget_plan(3.2, 4, m)['status'] == 'OK_FULL'


def _live(monkeypatch):
    from live import erisedai_distillation_client
    monkeypatch.setattr(demo.compose_ab, 'probe', lambda *a, **k: {'available': True, 'response_model': 'ok'})
    monkeypatch.setattr(erisedai_distillation_client, 'relay_config', lambda: {})
    monkeypatch.setattr(erisedai_distillation_client, 'ErisedaiClient', lambda *a, **k: object())
    monkeypatch.setattr(demo, 'ContentStore', lambda path: object())
    monkeypatch.setattr(demo, 'select_groups', lambda store, accounts, *_a, **_k: {a: [{'unit_id': a}] for a in accounts})
    monkeypatch.setattr(demo, 'evidence_source', lambda records: ({'id': records[0]['unit_id'], 'source_hash': 'h'}, []))


def test_slot_exception_is_error_row_and_outputs_always_written(tmp_path, monkeypatch):
    isolate_globals(monkeypatch)
    _live(monkeypatch)

    def compose_source(source, account, client, **kw):
        if account == 'zh_industry':
            raise KeyError('key')            # v8 crash class
        return dict(account_id=account, text='J ' + account, body='J ' + account,
                    stance={'decision': 'adapt', 'account_view': 'J ' + account,
                            'view': {'subject': account, 'direction': 'neutral'}}, units=[], draft_status='draft_ready')
    monkeypatch.setattr(demo.compose, 'compose_source', compose_source)
    monkeypatch.setattr(demo, 'arbitrate_with_carried', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('arb boom')))
    results = demo.run(tmp_path, 2.5, live=True, command='t')
    by = {r['account_id']: r for r in results}
    assert by['zh_industry']['mode'] == 'error' and not by['zh_industry']['synthetic']
    assert sum(r['mode'] == 'live' for r in results) == 3
    summary = (tmp_path / 'SUMMARY.md').read_text()
    assert 'Live drafts: 3/4' in summary and 'arb boom' in summary and 'Budget plan' in summary
    assert (tmp_path / 'arbitration.json').exists() and len(list((tmp_path / 'drafts').glob('*.json'))) == 4
    assert json.loads((tmp_path / 'budget_plan.json').read_text())['slots_funded'] == 4


def test_zh_emotion_devices_drop_rhetorical_question():
    from live import emotion_contract as ec
    import inspect
    src = inspect.getsource(ec)
    assert "lang == 'zh' and (d == 'rhetorical question'" in src   # v11: + ZH_NO_DEVICES


def test_en_imperative_template_flagged():
    body = ('Forget the obsession with power and networking—memory bandwidth and capacity are the actual '
            'binding constraints choking AI datacenter scaling.')
    assert zr.en_template_findings(body)
    assert not zr.en_template_findings('Memory bandwidth is the binding constraint now, more than power.')


def test_long_shape_number_budget_and_overclaim():
    from live import compose
    assert compose.number_budget({'length': 'long', 'max_numbers': 3}) == 4
    assert compose.number_budget({'length': 'medium', 'max_numbers': 3}) == 3
    assert compose.number_budget({'length': 'short', 'max_numbers': 1}) == 1
    assert compose.info_dump_findings('1 2 3 4 5 6', 'judgment_take', budget_numbers=4)[0]['detail'].endswith('(budget 4)')
    assert any('绝对化副词' in f['detail'] for f in zr.register_findings('这轮加息周期实际上已经彻底进入了尾声。'))


def test_ingest_mapping_for_newsletters():
    from live import ingest_priority as ip
    assert ip.channel_personas('newsletters:libertystreet')[0] == 'macro_rates_en'
    assert ip.channel_personas('newsletters:stratechery') != [ip.UNKNOWN]


def test_continue_from_missing_dir_fails_loud(tmp_path):
    import pytest
    from scripts import demo_matrix_compose as demo
    with pytest.raises(SystemExit):
        demo.main(['--dry', '--out', str(tmp_path / 'o'), '--continue-from', str(tmp_path / 'nope')])


def test_prescreen_demotes_consumer_app_without_supply_chain():
    muse = [{'source': {'title': 'Meta Muse爆红后遇留存瓶颈：打开率低于主流应用，长期变现面临考验'},
             'unit': {'kind': 'view', 'statement': 'Muse 对垂直电商和旅游平台短期没有威胁',
                      'view': {'subject': 'Meta Muse', 'reasoning': ['用户渗透率低', '缺乏交易能力']}}}]
    phone = [{'source': {'title': 'Qualcomm Makes Its Case for the Phone as AI Hub'},
              'unit': {'kind': 'view', 'statement': 'On-device AI drives a smartphone chip upgrade cycle',
                       'view': {'subject': 'Qualcomm', 'reasoning': ['modem and NPU content per phone rises']}}}]
    assert ps.prescreen('zh_industry', muse)['reasons'][0].startswith('consumer_app_without_supply_chain_evidence')
    assert ps.prescreen('zh_industry', phone)['ok']


def test_backup_failure_after_reject_counts_as_error():
    first = {'stance': {'decision': 'reject', 'rationale': 'not my lane'}}
    row = demo._keep_rejected(first, 'zh_industry', [{'source_id': 's1'}], 'BudgetExceeded: x', 'budget')
    assert row['error_kind'] == 'backup_budget' and row['mode'] == 'live' and not row.get('body')


def test_summary_fails_loud_on_provider_quota(tmp_path, monkeypatch):
    from live import erisedai_distillation_client as relay
    isolate_globals(monkeypatch)
    _live(monkeypatch)

    def compose_source(source, account, client, **kw):
        relay.QUOTA_TRIPPED[('compose', 'gemini-3.1-pro-preview')] = 'gemini: Relay HTTP 403 insufficient_user_quota'
        return dict(account_id=account, text='J ' + account, body='J ' + account,
                    stance={'decision': 'adapt', 'account_view': 'J ' + account,
                            'view': {'subject': account, 'direction': 'neutral'}}, units=[], draft_status='draft_ready')
    monkeypatch.setattr(demo.compose, 'compose_source', compose_source)
    demo.run(tmp_path, 2.5, live=True, command='t')
    summary = (tmp_path / 'SUMMARY.md').read_text()
    assert 'FAIL LOUD — provider quota exhausted' in summary and 'insufficient_user_quota' in summary
