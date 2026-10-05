"""Emotion contract: brief from source/stance; soft EMOTION_DROP; never hard-block."""
import json

from live import emotion_contract as ec
from live import qa_levels
from tests.test_compose import Fake, GOOD_BODY, run


def test_brief_picks_dominant_emotion_and_intensity():
    units = [{'unit_id': 'cu-1', 'statement': 'Bitcoin panic dump overnight. Traders anxious about crash.',
              'source_spans': [{'exact_text': 'panic dump'}], 'numbers': []}]
    stance = {'account_view': 'The dump looks overdone — liquidity, not a cycle break.',
              'view': {'subject': 'Bitcoin', 'direction': 'neutral', 'reasoning': 'thin panic'}}
    brief = ec.build_emotion_brief(units, stance, lang='en')
    assert brief['target_intensity'] >= 3
    assert brief['dominant_emotions']
    assert 'required_effect' in brief and 'first two lines' in brief['required_effect']


def test_emotion_drop_on_flat_recap():
    brief = {'dominant_emotions': ['skeptical'], 'dominant_labels': ['skeptical / 怀疑'],
             'target_intensity': 4, 'allowed_devices': ['short lines']}
    flat = 'October hike odds fell from 66% to 22%. Bitcoin rose about 1% on the week. Flows were mixed.'
    findings = ec.emotion_findings(flat, brief)
    assert findings and findings[0]['code'] == 'emotion_drop'
    assert 'EMOTION_DROP' in findings[0]['detail']
    assert qa_levels.level(findings[0], frame_found=True) == 'soft'
    assert qa_levels.draft_status(findings) == 'draft_ready'


def test_punchy_opening_avoids_drop():
    brief = {'dominant_emotions': ['skeptical'], 'dominant_labels': ['skeptical / 怀疑'],
             'target_intensity': 3, 'allowed_devices': ['short lines']}
    body = ('Macro repricing is not driving Bitcoin — this shrug is the tell.\n'
            'Stay skeptical: hike odds collapsed and price barely budged.')
    assert ec.emotion_findings(body, brief) == []
    assert ec.first_two_have_reaction(body)


def test_compose_includes_emotion_brief_mid_no_force():
    """MID personas get emotion_brief + soft findings; no force rewrite (retry OFF)."""
    class Alternating(Fake):
        def __call__(self, stage, messages, max_tokens):
            self.calls.append(stage)
            if stage == 'extract':
                return {'text': json.dumps(self.units), 'finish_reason': 'stop', 'model': 'fake'}
            payload = json.loads(messages[-1]['content'])
            assert 'emotion_brief' in payload and payload['emotion_brief']['target_intensity'] >= 2
            assert payload['emotion_brief'].get('tier') == 'mid'
            assert payload['emotion_brief'].get('emotion_retry') is False
            ids = [u['unit_id'] for u in payload['units']]
            body = '供给端的克制会延续，短期内很难看到过剩。\n' + GOOD_BODY
            ledger = [{'claim': '营收', 'unit_id': ids[0], 'span_ref': 0}]
            return {'text': json.dumps({'body': body, 'claim_ledger': ledger}, ensure_ascii=False),
                    'finish_reason': 'stop', 'model': 'fake'}

    result, fake = run(Alternating(), post_type='data_take', account='zh_industry')
    assert 'emotion_brief' in result
    assert result['emotion_brief']['tier'] == 'mid'
    assert result['draft_status'] == 'draft_ready'
