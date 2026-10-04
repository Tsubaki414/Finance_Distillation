"""One first-person rule for COMPOSE and QA: opinion markers ("I think", "my read", 我觉得, 在我看来)
are allowed in persona voice; first-person experience, actions, holdings or 'we' are not."""
from live import attribution_frame as af, compose

SOURCE = {'source_id': 'libertystreet', 'author_name': 'Gianluca Benigno', 'source_language': 'en'}
BODY = '作者估计，2025年准备金需求升至3.2万亿美元。'


def ident(text, post_type='view_relay'):
    frame = af.render(post_type, SOURCE)
    return 'author_identity' in {f['code'] for f in af.check(post_type, frame['text'] + text, frame, 'B')}


def test_opinion_markers_allowed():
    for t in ('我觉得这个判断偏乐观。', '在我看来，需求还没见顶。', '我的看法是准备金仍偏紧。', '我认为风险被低估了。'):
        assert not ident(t + BODY), t
    for t in ('I think reserves stay tight. ', 'My read: demand is peaking. ', "I'm not convinced the cycle turned. "):
        assert not ident(t + BODY), t


def test_experience_actions_we_flagged():
    for t in ('我一直在跟踪准备金数据，', '我持有美债多头，', '我们团队测算过，', '我上周加仓了，'):
        assert ident(t + BODY), t
    for t in ('I bought more last week. ', 'We see demand peaking. ', 'In my portfolio this is the biggest risk. '):
        assert ident(t + BODY), t


def test_prompt_states_the_same_rule():
    text = compose.COMPOSE
    assert 'no 我/我们/I/we' not in text
    assert 'opinion markers' in text.lower()
