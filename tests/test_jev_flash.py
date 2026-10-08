"""live/jev_flash.FlashJev: Jev-compatible answers from the flash stage, strict choice validation."""
import json

from live import jev_front
from live.jev_flash import FlashJev


class FakeClient:
    def __init__(self, answer, model='gemini-3-flash', fallback=False):
        self.answer, self.model, self.fallback, self.seen = answer, model, fallback, []

    def __call__(self, stage, messages, max_tokens):
        self.seen.append((stage, messages))
        text = self.answer(messages) if callable(self.answer) else self.answer
        return {'text': text, 'response_model': self.model, 'model_fallback': self.fallback}


Q = {'1:post_type': {'type': 'choice', 'criteria': jev_front.POST_TYPE_CRITERIA, 'instructions': 'x'},
     '1:hook': {'type': 'choice', 'criteria': jev_front.HOOK_CRITERIA, 'instructions': 'y'}}


def test_completed_answers(tmp_path):
    c = FakeClient(json.dumps({'answers': {'1:post_type': 'data_take', '1:hook': 'question'}}))
    r = FlashJev(tmp_path, client=c).review({'task': 't'}, Q)
    assert r['status'] == 'completed'
    assert r['answers'] == {'1:post_type': {'choice': 'data_take'}, '1:hook': {'choice': 'question'}}
    assert c.seen[0][0] == 'extract_flash'


def test_unknown_or_missing_choice_fails_whole_call(tmp_path):
    bad = FakeClient(json.dumps({'answers': {'1:post_type': 'meme', '1:hook': 'question'}}))
    assert FlashJev(tmp_path, client=bad).review({}, Q)['status'] == 'failed'
    missing = FakeClient(json.dumps({'answers': {'1:post_type': 'data_take'}}))
    assert FlashJev(tmp_path, client=missing).review({}, Q)['status'] == 'failed'


def test_non_gemini_or_model_fallback_rejected(tmp_path):
    ok = json.dumps({'answers': {'1:post_type': 'data_take', '1:hook': 'question'}})
    assert FlashJev(tmp_path, client=FakeClient(ok, model='claude-x')).review({}, Q)['status'] == 'failed'
    assert FlashJev(tmp_path, client=FakeClient(ok, fallback=True)).review({}, Q)['status'] == 'failed'


def test_tag_posts_uses_flash_answers(tmp_path):
    def answer(messages):
        ids = [json.loads(l)['id'] for l in messages[1]['content'].splitlines()[2:] if l.strip()]
        return json.dumps({'answers': {i: ('hot_take' if i.endswith('post_type') else 'bold_claim') for i in ids}})
    posts = [{'id': str(i), 'text': f'post {i}'} for i in range(10)]
    tags = jev_front.tag_posts(posts, jev=FlashJev(tmp_path, client=FakeClient(answer)))
    assert all(not t['jev_fallback'] and t['post_type'] == 'hot_take' and t['hook'] == 'bold_claim' for t in tags.values())
