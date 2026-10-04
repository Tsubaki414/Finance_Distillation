from live import jev_front as jf


class FakeJev:
    def __init__(self, fails):
        self.fails = fails
        self.calls = []

    def review(self, state, questions):
        self.calls.append(questions)
        if self.fails(questions, len(self.calls)):
            return {'status': 'failed', 'answers': {}}
        return {'status': 'completed', 'answers': {
            q: {'choice': next(iter(spec['criteria'])), 'confidence': .9}
            for q, spec in questions.items()}}


def posts(n=8):
    return [{'id': str(i), 'text': 'Fed news'} for i in range(n)]


def test_retry_recovers_batch():
    jev = FakeJev(lambda q, n: n == 1)
    stats = {}
    tags = jf.tag_posts(posts(), jev=jev, stats=stats)
    assert not any(t['jev_fallback'] for t in tags.values())
    assert stats == dict(calls=2, failed_calls=1, retried=1, split=0, fallback_posts=0)


def test_split_isolates_bad_post():
    jev = FakeJev(lambda q, n: '0:hook' in q)
    stats = {}
    tags = jf.tag_posts(posts(), jev=jev, stats=stats)
    assert [k for k, t in tags.items() if t['jev_fallback']] == ['0']
    assert stats['fallback_posts'] == 1
    assert stats['split'] == 3
    assert stats['calls'] <= 18


def test_all_failures_are_bounded_and_rules_preserved():
    jev = FakeJev(lambda q, n: True)
    stats = {}
    assert jf.tag_posts(posts(), jev=jev, stats=stats) == jf.tag_posts(posts())
    assert len(jev.calls) <= 18
    assert stats['failed_calls'] == stats['calls']
    assert stats['fallback_posts'] == 8


def test_separate_question_calls_and_generator():
    jev = FakeJev(lambda q, n: len({key.split(':')[-1] for key in q}) > 1)
    tags = jf.tag_posts(iter(posts()), jev=jev, questions_per_call=8)
    assert not any(t['jev_fallback'] for t in tags.values())
    assert len(jev.calls) == 2
    assert all(len(q) <= 8 for q in jev.calls)


def test_other_front_calls_retry_and_split():
    for operation in ('route', 'screen'):
        jev = FakeJev(lambda q, n: len(q) > 1)
        if operation == 'route':
            result = jf.route_sources(posts(4), jev=jev)
        else:
            result = jf.prescreen_units([{'unit_id': str(i)} for i in range(4)], persona='macro_zh', jev=jev)
        assert not any(t['jev_fallback'] for t in result.values())
