"""Review fixes on the nat3 humanize / engagement code (Oct 10)."""
from live import humanize as h
from live import engagement as eng


def test_only_droppable_intensifiers_are_deleted():
    body, chg = h._apply_intensifiers('加息概率都砸到22%了，市场简直离谱，根本扛不住', 'zh', 'a', 0.0)
    assert '砸到22%' in body and '离谱' in body      # predicates stay
    assert '简直' not in body and '根本' not in body


def test_simply_put_kept_and_caps_restored():
    body, _ = h._apply_intensifiers('Flows completely reversed. Simply put, it is massive.', 'en', 'x', 0.1)
    assert 'Simply put' in body and 'completely' not in body


def test_lowercase_keeps_tickers_and_acronyms():
    body, _ = h._apply_texture('Watching $BTC and the ETF flows.', 'en', 'q1', {'all_lower': 1.0})
    assert body == 'watching $BTC and the ETF flows.'


def test_zh_particle_before_end_and_not_after_number():
    body, _ = h._apply_texture('这种孱弱承接得当心。', 'zh', 'q1', {'particle': 1.0})
    assert body in ('这种孱弱承接得当心吧', '这种孱弱承接得当心啊')
    body2, _ = h._apply_texture('涨了22%', 'zh', 'q1', {'particle': 1.0})
    assert body2 == '涨了22%'


def test_fidelity_accepts_rounding_rejects_new_or_lost_numbers():
    assert h._fidelity_ok('dumped $681,000,000', 'dumped $681M')
    assert h._fidelity_ok('单日4.872亿美元', '单日4.9亿美元')
    assert not h._fidelity_ok('a 5%', 'a 5% in 7 days')
    assert not h._fidelity_ok('a 5% in 7 days', 'a 5%')
    assert not h._fidelity_ok('5%', '5')               # percent vs amount


def test_entities_guard():
    assert not h._entities_ok('BTC is weak', 'BTC is weak, says Powell')
    assert h._entities_ok('BTC is weak today', 'I think BTC is weak')


def test_formula_closer_drop():
    assert h.drop_formula_closer('台积电投产5.5倍光罩。\n后续要盯大客户下单节奏')[0] == '台积电投产5.5倍光罩。'
    assert h.drop_formula_closer('加息概率22%，大饼只涨1%，关键看ETF能否回流。')[0] == '加息概率22%，大饼只涨1%。'
    assert h.drop_formula_closer('Watch the weekly OI.')[1] == ''   # single line: nothing left, keep


def test_llm_uses_callable_client(monkeypatch):
    calls = []

    def client(stage, messages, max_tokens):
        calls.append(stage)
        return {'text': 'I think BTC is weak here'}
    out = h._llm_rewrite(client, {'body': 'BTC is weak here'}, 'en', ['x'], 'acct')
    assert calls == ['compose'] and out == 'I think BTC is weak here'


def test_author_cap():
    st = eng.DayState()
    st.authors |= {('a1', 'tedpillows'), ('a2', 'tedpillows')}
    assert eng.author_full(st, '@TedPillows', 'a3', env={'FD_ENGAGE_AUTHOR_CAP': '2'})
    assert not eng.author_full(st, 'tedpillows', 'a3', env={'FD_ENGAGE_AUTHOR_CAP': '0'})
    assert not eng.author_full(st, 'tedpillows', 'a2', env={'FD_ENGAGE_AUTHOR_CAP': '2'})


def test_echo_op_needs_real_echo():
    tgt = 'BTC ETFs saw $681M outflows this week, the market is shaky'
    assert eng.echo_op_findings('$681M out and nobody blinks', tgt, 'en')
    assert not eng.echo_op_findings('5 straight days of this and funding is still positive', tgt, 'en')
