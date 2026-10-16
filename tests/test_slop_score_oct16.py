"""Oct 16: soft AI-slop score (live/slop_score.py), zh dash compression (nat_tex), short-post moral line (humanize)."""
import pytest
from live import slop_score as S, nat_tex, humanize as hum


def codes(body, lang='en'):
    return {t['code'] for t in S.score(body, lang)['tells']}


@pytest.mark.parametrize('body,code', [
    ("Starting small isn't just conservative. It's strategic.", 'neg_par_just'),          # (1)
    ("This isn't just cosmetic — it's artistry.", 'neg_par_just'),
    ("Funds don't just sell, they rotate.", 'dont_just'),
    ("No crash diets, no stress, just small adjustments.", 'no_x_no_y_just_z'),            # (2)
    ("没有杠杆，没有故事，只有现金流", 'meiyou_zhiyou'),
    ("这不只是一次加息，更是信号", 'bu_zhi'),                                               # (3)
    ("不仅是流动性问题，更是信心问题", 'bu_jin'),
    ("不再是故障，而是常态", 'bu_zai'),
    ("Think of it as a traffic cop.", 'think_of'),                                          # (4)
    ("想象一下，明天开盘全线跳水", 'think_of'),
    ("真正的问题在于信心", 'zhen_zheng'),                                                    # (6)
    ("Robust, powerful and undeniably aesthetic.", 'rule3_adv'),
    ("流动性、估值和情绪都在变", 'rule3_zh'),
    ("This is game-changing for the sector.", 'promo_en'),                                  # (7)
    ("这将重塑整个市场", 'promo_zh'),
    ("前所未有的行情", 'promo_zh'),
])
def test_each_gap_detected(body, code):
    assert code in codes(body, 'zh' if any('\u4e00' <= c <= '\u9fff' for c in body) else 'en')


def test_zh_dash_and_en_dash_density():                                                      # (5)
    assert 'zh_dash' in codes('利率还在涨——市场不买账', 'zh')
    assert 'em_dash' not in codes('One dash — only.', 'en')
    assert 'em_dash' in codes('Rates rose — stocks fell — nobody cared.', 'en')


def test_ai_vocab_density():                                                                 # (8)
    assert 'ai_vocab' not in codes('This is a robust setup.')
    assert 'ai_vocab' in codes('A profound, crucial and robust shift in the landscape.')


def test_single_tell_is_weak_stacking_triggers():
    one = S.score("Funds don't just sell, they rotate.", 'en')
    assert 0 < one['score'] < S.THRESHOLD and not S.over(one)
    stack = S.score("This isn't just a dip — it's a reset. Think of it as a game-changing transformative moment.", 'en')
    assert S.over(stack)
    zh = S.score('这不只是一次加息，更是信号。想象一下，这将重塑整个市场——前所未有。', 'zh')
    assert S.over(zh)


def test_false_positives_stay_clean():
    for b in ["Fed held. Bitcoin barely blinked.", "Not much changed today.", "这根针插得太狠了",
              "ETF 流入 3 亿美元，创 9 月以来新高", "Token unlock of 2% hits Friday; fundamentals unchanged.",
              "Leveraged longs got flushed, funding flipped negative."]:
        assert S.score(b, 'zh' if '\u4e00' <= b[0] <= '\u9fff' else 'en')['score'] == 0, b


def test_quotes_and_numeric_facts_exempt():
    assert S.score('He said "this is not just a rally, it\'s a regime change" on air.', 'en')['score'] == 0
    assert S.score('他说“这不只是一次加息，更是信号”，市场没动。', 'zh')['score'] == 0
    # numeric-fact sentence is exempt from the weak lexical tells
    assert S.score('Transformative, unprecedented: BTC up 12% in a day.', 'en')['score'] == 0
    assert S.score('Transformative, unprecedented moves.', 'en')['score'] > 0


def test_env_flag(monkeypatch):
    monkeypatch.setenv('FD_SLOP_SCORE', '0')
    row = {'body': "This isn't just a dip — it's a reset. Think of it as a game-changing moment."}
    assert S.gate(row, 'en') == ([], None)
    monkeypatch.delenv('FD_SLOP_SCORE')
    assert S.enabled()


SLOPPY = "This isn't just a dip, it's a reset. Think of it as a game-changing moment for ETH holders who bought 2000."


def test_gate_retry_clears(monkeypatch):
    row = {'body': SLOPPY, 'text': SLOPPY, 'account_id': 'x'}
    fixed = 'ETH holders who bought 2000 took a hit, and the dip looks like a reset to me.'
    monkeypatch.setattr(hum, '_fidelity_ok', lambda a, b: True)
    monkeypatch.setattr(hum, '_entities_ok', lambda a, b: True)
    fnd, info = S.gate(row, 'en', client=object(), rewrite=lambda *a, **k: fixed)
    assert fnd == [] and info['retried'] and row['body'] == fixed and row['text'] == fixed


def test_gate_still_over_holds(monkeypatch):
    row = {'body': SLOPPY, 'text': SLOPPY, 'account_id': 'x'}
    monkeypatch.setattr(hum, '_fidelity_ok', lambda a, b: True)
    monkeypatch.setattr(hum, '_entities_ok', lambda a, b: True)
    fnd, info = S.gate(row, 'en', client=object(), rewrite=lambda *a, **k: SLOPPY.replace('ETH', 'BTC').replace('2000', '2k'))
    assert fnd and fnd[0]['code'] == 'ai_slop_score' and fnd[0]['level'] == 'hard' and info['held']
    assert row['body'] == SLOPPY   # unchanged: no better text


def test_gate_clean_post_untouched():
    row = {'body': 'BTC lost 60k in under an hour and funding barely moved.'}
    assert S.gate(row, 'en', client=object()) [0] == []


def test_zh_dash_compression_in_nat_tex():
    b, chg = nat_tex.apply_llmism('利率涨了——股市跌了——没人买账', 'zh', 'd1')
    assert b.count('——') == 1 and chg
    b2, _ = nat_tex.apply_llmism('他说“利率涨了——股市跌了”，然后——走了——又回来', 'zh', 'd1')
    assert '“利率涨了——股市跌了”' in b2
    assert nat_tex.apply_llmism('一个——就好', 'zh', 'd1')[0] == '一个——就好'


def test_zh_dash_compression_flag_off(monkeypatch):
    monkeypatch.setenv('FD_SLOP_SCORE', '0')
    s = '利率涨了——股市跌了——没人买账'
    assert nat_tex.apply_llmism(s, 'zh', 'd1')[0] == s


def test_drop_moral_line_short_posts(monkeypatch):
    two_sent = 'Funds sold the Treasury rally into the close on Tuesday. Patience is always the winning strategy in markets.'
    cut, removed = hum.drop_moral_line(two_sent, 'en')
    assert removed.startswith('Patience') and cut.startswith('Funds sold')
    two_line = '外资今天又在卖韩国股票，成交很大\n市场总会回到理性的轨道上来，耐心才是最好的策略'
    cut, removed = hum.drop_moral_line(two_line, 'zh')
    assert removed == '市场总会回到理性的轨道上来，耐心才是最好的策略' and cut == '外资今天又在卖韩国股票，成交很大'
    # facts / short punch / one sentence untouched
    assert hum.drop_moral_line('Fed held. Bitcoin barely blinked.', 'en')[1] == ''
    assert hum.drop_moral_line('Funds sold the rally on Tuesday. BTC fell 3% after.', 'en')[1] == ''
    monkeypatch.setenv('FD_SLOP_SCORE', '0')
    assert hum.drop_moral_line(two_sent, 'en')[1] == ''
