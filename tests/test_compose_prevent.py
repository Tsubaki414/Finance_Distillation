from live import compose_prevent as cp

EV = 'Bitcoin fell 7.2% to $61,400 as $1.1B of longs were liquidated. Analysts said leverage had built up all week.'


def test_whitelist_and_number_flag():
    assert '7.2%' in cp.whitelist(EV)
    f = cp.findings('BTC fell 7.2% today.\nShorts made 45% overnight.', 'en', EV)
    assert any('number_not_in_source' in c for x in f for c in x['codes'])
    assert all('7.2' not in x['sentence'] for x in f)


def test_openers_template_quotes_steps():
    f = cp.findings('ngl this dump hurt.\n"leverage was everywhere" they say.', 'en', EV)
    codes = {c for x in f for c in x['codes']}
    assert {'banned_opener', 'quote_not_verbatim'} <= codes
    f = cp.findings('我看这次不是散户，而是机构在砸\n1. ：', 'zh', EV)
    codes = {c for x in f for c in x['codes']}
    assert {'banned_opener', 'not_x_but_y', 'empty_step_label'} <= codes


def test_repair_one_pass_only_offending_sentence():
    body = 'BTC fell 7.2% today.\nShorts made 45% overnight.'
    found = cp.findings(body, 'en', EV)
    calls = []
    def ask(system, payload):
        calls.append(payload)
        return {'fixes': [{'old': 'Shorts made 45% overnight.', 'new': 'Shorts had a very good night.'}]}
    new, info = cp.repair(body, 'en', EV, found, ask)
    assert len(calls) == 1 and new.startswith('BTC fell 7.2% today.') and '45%' not in new
    assert info['remaining'] == []


def test_disputed():
    assert cp.disputed_for('US CPI this week')


def test_not_x_family_nfa_and_numbers():
    for b in ('原因不在美联储，是流动性', '这次不是散户在跑，是机构', "It's not the Fed, it's liquidity."):
        assert any('not_x_but_y' in x['codes'] for x in cp.findings(b, 'zh' if '原' in b or '这' in b else 'en', EV)), b
    assert any('disclaimer_on_commentary' in x['codes'] for x in cp.findings('BTC fell 7.2%. Not financial advice.', 'en', EV))
    assert not cp.findings('BTC fell 7.2%. Not financial advice.', 'en', EV, strategy=True)
    assert any(c.startswith('too_many_numbers') for x in cp.findings('7.2% 61,400 1.1 7.2 61400 1.1B', 'en', EV) for c in x['codes'])


def test_list_markers_not_flagged():
    assert not cp.findings('BTC fell 7.2%\n1. 情绪：杠杆太高\n2. 承接：看下方', 'zh', EV)


def test_final_recheck_codes_and_jargon():
    codes = {f['code'] for f in cp.final_findings('ngl open interest slid hard. Not financial advice.', 'en')}
    assert {'prevent_banned_opener', 'prevent_disclaimer_on_commentary', 'prevent_jargon_unexplained'} <= codes
    assert not cp.final_findings('Open interest (total open futures bets) slid to $333.6m. Still watching.', 'en')
    assert any(c['code'] == 'prevent_not_x_but_y' for c in cp.final_findings('原因不在美联储，是流动性', 'zh'))
    f = cp.final_repair_found('Open interest slid. Wild.', 'en')
    assert f and 'jargon_unexplained' in f[0]['codes'][0]
