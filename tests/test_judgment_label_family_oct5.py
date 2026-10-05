"""Oct 5: 以我个人判断 / 个人判断： are the same judgment-label family as 我的判断：."""
import pytest
from live import anti_repeat as ar, stance

BODY = '利润撑不起估值。'


@pytest.fixture(autouse=True)
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, 'HISTORY_DIR', tmp_path)


@pytest.mark.parametrize('label', ['我的判断：', '以我个人判断', '以我个人判断，', '以我个人判断,',
                                   '以我个人判断：', '个人判断：', '个人判断: ', '我个人判断：'])
def test_anti_repeat_strips_label_family(label):
    assert ar.strip_judgment_label(label + BODY) == (BODY, True)
    codes = {f['code'] for f in ar.findings(label + BODY, 'test', recent=[])}
    assert 'judgment_label' in codes


def test_anti_repeat_strips_mid_body_label():
    cleaned, hit = ar.strip_judgment_label('数据偏弱。\n以我个人判断，' + BODY)
    assert hit and cleaned == '数据偏弱。\n' + BODY


@pytest.mark.parametrize('text', ['我认为利润撑不起估值。', '这只是个人判断而已，利润撑不起估值。',
                                  '判断：利润撑不起估值。'])
def test_anti_repeat_leaves_non_labels(text):
    assert ar.strip_judgment_label(text) == (text, False)


@pytest.mark.parametrize('label', ['以我个人判断，', '以我个人判断', '个人判断：', '我个人判断：'])
def test_stance_scrub_strips_label_family(label):
    cleaned, meta = stance.scrub_account_view(label + '单月数据不足以确认趋势。')
    assert cleaned == '单月数据不足以确认趋势。'
    assert meta['meta_stripped'] and meta['changed'] and meta['hits_after'] == []


def test_stance_banned_hits_and_mid_sentence_scrub():
    assert '以我个人判断' in stance.banned_hits('以我个人判断，降息还要等。')
    assert '个人判断：' in stance.banned_hits('数据偏弱，个人判断：降息还要等。')
    cleaned, meta = stance.scrub_account_view('就业数据偏弱，以我个人判断，年内降息还要再等一个季度。')
    assert '个人判断' not in cleaned and meta['hits_after'] == []


def test_compose_prompt_lists_label_family():
    from live import compose
    src = open(compose.__file__, encoding='utf-8').read()
    assert '以我个人判断' in src and '个人判断：' in src
