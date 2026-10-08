"""Jev-compatible choice-question answerer on the pipeline's flash stage (Oct 8 eve).

Drop-in for live.jev_review_client.JevReviewClient in jev_front.tag_posts / _resilient_ask: same
review(state, questions) -> {'status', 'answers': {qid: {'choice': key}}} contract, but answered by the
`extract_flash` stage of the Gemini relay client (subrouter gemini-3-flash first, same-model micuapi fallback;
live/stage_models.py). Used for donor post style tagging (scripts/donor_style_stats.py --flash) when the
TypeSafe Jev path is not wanted. Advisory tags only: post_type / hook labels for voice statistics, never content.

Every answer is validated against the question's criteria keys; one missing or unknown key fails the whole call
(status 'failed'), so _resilient_ask's retry / split logic and the rule fallback stay in charge.
"""
from __future__ import annotations

import json
from pathlib import Path

STAGE = 'extract_flash'
MAX_TOKENS = 4000
SYSTEM = ('You label finance social-media posts. Each question has an id, instructions and a fixed set of choices '
          '(key: meaning). Pick exactly one choice key per question. Answer with one JSON object only: '
          '{"answers": {"<question id>": "<choice key>", ...}} covering every question id. No other text.')


class FlashJev:
    def __init__(self, directory, *, client=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if client is None:
            from live.daily_ingest import flash_client
            client = flash_client(self.directory)
        self.client = client
        self.calls = []

    @staticmethod
    def messages(state, questions):
        lines = [f"Task: {state.get('task') or 'classification'}", '']
        for qid, q in questions.items():
            choices = '; '.join(f'{k}: {v}' for k, v in (q.get('criteria') or {}).items())
            lines.append(json.dumps({'id': qid, 'instructions': q.get('instructions') or '', 'choices': choices},
                                    ensure_ascii=False))
        return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': '\n'.join(lines)}]

    def review(self, state, questions):
        from live.model_json import parse_object
        result = {'status': 'failed', 'answers': {}, 'model': None, 'error_code': None}
        try:
            r = self.client(STAGE, self.messages(state, questions), MAX_TOKENS)
        except Exception as exc:   # noqa: BLE001 - BudgetExceeded is re-raised by the caller's _ask
            from ml.budget import BudgetExceeded
            if isinstance(exc, BudgetExceeded):
                raise
            result['error_code'] = type(exc).__name__
            self.calls.append(result['error_code'])
            return result
        result['model'] = r.get('response_model')
        if r.get('model_fallback') or not str(r.get('response_model') or '').startswith('gemini-'):
            result['error_code'] = 'non_gemini_response'
            return result
        try:
            raw = parse_object(r.get('text') or '', repair_quotes=True)
        except (ValueError, TypeError):
            result['error_code'] = 'unparseable'
            return result
        raw = raw.get('answers', raw) if isinstance(raw, dict) else {}
        answers = {}
        for qid, q in questions.items():
            choice = raw.get(qid) if isinstance(raw, dict) else None
            if isinstance(choice, dict):
                choice = choice.get('choice')
            if not isinstance(choice, str) or choice.strip() not in (q.get('criteria') or {}):
                result['error_code'] = 'invalid_choice'
                return result
            answers[qid] = {'choice': choice.strip()}
        result.update(status='completed', answers=answers)
        self.calls.append('completed')
        return result
