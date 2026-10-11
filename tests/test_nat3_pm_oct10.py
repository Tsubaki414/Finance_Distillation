"""Oct 10 17:30 PM decision B: short shapes at the donor short-post rate (~20%), fluency check for short shapes."""
import json
from types import SimpleNamespace

from live import compose_shapes, fluency


def _p(pid='x'):
    return SimpleNamespace(persona_id=pid)


def test_nonarg_share_is_donor_short_rate_capped(monkeypatch):
    from live import donor_rates
    monkeypatch.setattr(donor_rates, 'account_rates', lambda pid, path=None: {'short_post': 0.219})
    assert compose_shapes.nonarg_share(_p(), env={}) == 0.219
    monkeypatch.setattr(donor_rates, 'account_rates', lambda pid, path=None: {'short_post': 0.6})
    assert compose_shapes.nonarg_share(_p(), env={}) == 0.25
    monkeypatch.setattr(donor_rates, 'account_rates', lambda pid, path=None: None)
    assert compose_shapes.nonarg_share(_p(), env={}) == 0.20
    assert compose_shapes.nonarg_share(_p(), env={'FD_NAT_PROMPT': '0'}) == 0.0


def test_pick_nonarg_rate_near_20pct(monkeypatch):
    from live import donor_rates
    monkeypatch.setattr(donor_rates, 'account_rates', lambda pid, path=None: {'short_post': 0.20})
    monkeypatch.setattr(compose_shapes, 'choose_shape', lambda *a, **k: {'id': 'one_line_take'})
    # Oct 11: the rate is of ALL standalone posts; only ~half reach the gate, so per eligible post 0.20 / 0.5 = 0.40
    hits = sum(1 for i in range(1000) if compose_shapes.pick_nonarg(_p(), seed=f's{i}', env={}))
    assert 340 <= hits <= 460
    hits = sum(1 for i in range(1000) if compose_shapes.pick_nonarg(_p(), seed=f's{i}', env={}, eligible=1.0))
    assert 150 <= hits <= 250


class Judge:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, stage, messages, max_tokens):
        self.prompts.append(messages[-1]['content'])
        return {'text': json.dumps(self.answers.pop(0))}


def _row(body, shape='one_line_take', lang='zh'):
    return {'id': 'd1', 'account_id': 'a', 'body': body, 'text': body, 'plan': {'account_lang': lang},
            'post_format': {'type': 'one_liner', 'nat_shape': shape}}


GARBLED = '我看Zcash ETF首月超10亿美元，机构所谓变严只是换花样搞多元资产'


def test_fluent_passes_untouched():
    r = _row('Zcash ETF首月就超10亿美元，比我想的快。')
    fluency.apply_batch([r], lambda: Judge([{'fluent': True, 'complete': True}] * fluency.VOTES))
    assert r['fluency']['action'] == 'pass' and r['body'].startswith('Zcash')


def test_garbled_rewritten_when_numbers_and_names_kept():
    fixed = 'Zcash ETF首月就超10亿美元。机构说门槛变严，我看只是换了个多元资产的包装。'
    j = Judge([{'fluent': False, 'complete': False, 'issue': 'clauses do not connect', 'rewrite': fixed},
               {'fluent': True, 'complete': True}])
    r = _row(GARBLED)
    fluency.apply_batch([r], lambda: j)
    assert r['fluency']['action'] == 'rewrite' and r['body'] == fixed and r['text'] == fixed


def test_rewrite_with_new_number_or_name_falls_back_to_normal_shape():
    bad = 'Zcash ETF首月超12亿美元，贝莱德说机构只是换花样。'
    r = _row(GARBLED)
    calls = []

    def recompose(row):
        calls.append(row['id'])
        return {'id': 'd2', 'account_id': 'a', 'body': 'normal shape body', 'text': 'normal shape body',
                'plan': {'account_lang': 'zh'}, 'post_format': {'type': 'take'}}
    fluency.apply_batch([r], lambda: Judge([{'fluent': False, 'complete': True, 'issue': 'x', 'rewrite': bad}]),
                        recompose=recompose)
    assert calls == ['d1'] and r['body'] == 'normal shape body' and r['fluency']['action'] == 'fallback_recomposed'


def test_fallback_failed_holds_draft():
    r = _row(GARBLED)
    fluency.apply_batch([r], lambda: Judge([{'fluent': False, 'complete': False, 'issue': 'x', 'rewrite': ''}]),
                        recompose=lambda row: None)
    assert r['draft_status'] == 'needs_review' and r['fluency']['action'] == 'fallback_failed'


def test_judge_failure_keeps_draft_and_non_nat_rows_skipped():
    def boom(*a):
        raise RuntimeError('down')
    r = _row('一句话。')
    fluency.apply_batch([r], lambda: boom)
    assert r['fluency']['action'] == 'skip' and r['body'] == '一句话。'
    plain = {'id': 'p', 'body': 'x', 'post_format': {'type': 'take'}}
    fluency.apply_batch([plain], lambda: boom)
    assert 'fluency' not in plain


def test_no_nat_flag_disables_gate():
    src = open('live/compose.py', encoding='utf-8').read()
    assert "not fmt_info.get('no_nat')" in src
    dc = open('scripts/daily_compose.py', encoding='utf-8').read()
    assert 'no_nat=True' in dc and '_flu.apply_batch(ok, client, recompose=_recompose)' in dc


def test_humanize_llm_on_by_default_after_guard_check(monkeypatch):
    from live import humanize
    monkeypatch.delenv('FD_HUMANIZE_LLM', raising=False)
    monkeypatch.delenv('FD_HUMANIZE', raising=False)
    assert humanize.enabled() and humanize.llm_enabled()
    monkeypatch.setenv('FD_HUMANIZE_LLM', '0')
    assert not humanize.llm_enabled()


def test_judge_language_follows_the_text():
    assert fluency.text_lang(GARBLED, 'en') == 'zh'
    assert fluency.text_lang('Robinhood buys $25 million BTC', 'zh') == 'en'
    j = Judge([{'fluent': True, 'complete': True}])
    fluency.judge(j, GARBLED, 'en')
    assert 'Chinese (Simplified)' in j.prompts[0]
    assert 'Chinese' in j.prompts[0]


def test_second_vote_can_fail_a_first_pass():
    fixed = 'Zcash ETF首月规模就超10亿美元。'
    j = Judge([{'fluent': True, 'complete': True},
               {'fluent': False, 'complete': True, 'issue': 'x', 'rewrite': fixed},
               {'fluent': True, 'complete': True}])
    r = _row('Zcash ETF首月超10亿美元。')
    fluency.apply_batch([r], lambda: j)
    assert r['fluency']['action'] == 'rewrite' and r['body'] == fixed


def test_gate_share_and_eligible_share(monkeypatch):
    from live import donor_rates
    monkeypatch.setattr(donor_rates, 'account_rates', lambda pid, path=None: {'short_post': 0.20})
    assert compose_shapes.eligible_share({'thread': 1, 'quote_comment': 1, 'quick_take': 2}) == 0.5
    assert compose_shapes.eligible_share(None) is None
    assert compose_shapes.gate_share(_p(), 0.5, env={}) == 0.4
    assert compose_shapes.gate_share(_p(), 0.1, env={}) == compose_shapes.NAT_GATE_MAX   # floor 0.2 -> 1.0 -> cap
    assert compose_shapes.gate_share(_p(), None, env={'FD_NAT_PROMPT': '0'}) == 0.0


def test_archive_fill_rows_are_humanized(monkeypatch):
    from live import archive_lookback, humanize
    seen = []
    monkeypatch.setattr(humanize, 'apply', lambda row, client=None, lang=None, **k: seen.append((client, lang)) or row)
    row = {'body': 'x', 'text': 'x', 'held': False}
    archive_lookback.humanize_row(row, {'lang': 'en'})
    assert seen == [(None, 'en')]
    archive_lookback.humanize_row({'body': 'x', 'held': True}, {'lang': 'zh'})
    assert len(seen) == 1
    src = open('live/archive_lookback.py', encoding='utf-8').read()
    assert "humanize_row(row, acc)" in src


def test_moral_last_sentence_cut_in_one_paragraph_posts():
    from live.humanize import drop_moral_line
    zh = '深度不足的品种一旦遭遇流动性抽离，盘面很容易失效。判断大级别走势，关键在趋势线的得失。频繁在震荡里猜顶底，反而容易两头失误。'
    body, cut = drop_moral_line(zh, 'zh')
    assert cut == '频繁在震荡里猜顶底，反而容易两头失误。' and body.endswith('关键在趋势线的得失。')
    en = ('Trying to tag the exact wick usually leaves orders unfilled. Laddering limits across a range fills more '
          'often. Patience usually beats precision when markets are noisy.')
    body, cut = drop_moral_line(en, 'en')
    assert cut.startswith('Patience') and body.endswith('fills more often.')
    for keep in ('BTC 6万。', '两句话。第二句也很短吧。', 'One. I think this beats everything else in the market now.'):
        assert drop_moral_line(keep, 'zh' if '话' in keep or '万' in keep else 'en')[1] == ''


def test_multi_sentence_last_paragraph_loses_only_its_last_sentence():
    from live.humanize import drop_moral_line, _NEUTRAL_EMOJI
    b = ('第一段事实。\n\n第二段事实。\n\n他们同时还在推别的项目，试图把单一账本和多个共享账本等架构全都包揽进去。'
         '不管技术怎么变，最终结算权他们是一点不肯放。')
    body, cut = drop_moral_line(b, 'zh')
    assert cut.startswith('不管技术怎么变') and '他们同时还在推别的项目' in body
    assert '👇' not in _NEUTRAL_EMOJI
