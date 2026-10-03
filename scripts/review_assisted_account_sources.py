"""Explicit, one-off assisted follow-ups for the three provider-stopped fixtures.

This does not retry localization, change a production prompt, or represent a
submitted Codex edit as a Claude response. Reuses verified source/translation,
applies an attributed exact-span submission, and optionally requests the existing
independent bilingual QA. Original automated evaluations remain unchanged.
"""
import argparse
import copy
import json
from pathlib import Path
import uuid

from live.account_intelligence import Store, ROOT, copy_risks
from live.distillation import Pipeline, apply_localization_edits, require, text_and_alignment
from live.distillation_source import digest, now
from scripts.resume_account_sources import comparable

RUN_ROOT = ROOT / 'runs/account_sources_v1'
OUTPUT = RUN_ROOT / 'assisted_followups'
PACKET = RUN_ROOT / 'apify_followups/exact_outputs.json'
PROTOCOL = 'codex-exact-span-review-v1'


def prepare(case, submission):
    require(case['admitted'] and case['fixture_id'] in {'F01', 'F02', 'F03'}, 'Only the admitted stopped fixtures')
    for key in ('fixture_id', 'account_id'):
        require(case[key] == submission[key], 'Submission identity changed')
    require(case['latest_run_id'] == submission['follow_up_of'], 'Submission parent changed')
    for key, value in [('source_hash', case['source']['source_hash']),
                       ('selection_id', case['selection']['selection_id']),
                       ('translation_id', case['translation']['translation_id'])]:
        require(value == submission[key], 'Submitted input version changed: ' + key)
    require(submission['generation_origin'] == 'codex_assisted'
            and submission['generation_protocol'] == PROTOCOL, 'Assisted origin must be explicit')
    require(digest(case['source']['original_text']) == case['source']['source_hash'], 'Source hash mismatch')
    for p in case['selection']['passages']:
        require(case['source']['original_text'][p['start']:p['end']] == p['exact_text'], 'Selected source changed')
    value = {k: submission[k] for k in ('edits', 'added_background')}
    localized, edits = apply_localization_edits(value, case['translation']['segments'],
                                               case['selection']['passages'], case['source']['title'])
    return value, localized, edits


def translation_record(case):
    refs = [r for r in case['call_provenance']['consumed_stages'] if r['stage'] == 'translation']
    require(len(refs) == 1, 'Ambiguous translation provenance')
    ref = refs[0]['original_call']
    path = ROOT / ref['path']
    import hashlib
    require(hashlib.sha256(path.read_bytes()).hexdigest() == ref['sha256'], 'Translation call changed')
    record = json.loads(path.read_text())
    require(record['status'] == 'completed' and record['response']['finish_reason'] == 'stop'
            and not record['response'].get('refusal'), 'Translation is not complete')
    require(record['prompt_hash'] == digest(record['messages']), 'Translation request hash mismatch')
    require(json.loads(record['response']['text'])['segments'] == case['translation']['segments'],
            'Translation artifact is not the actual saved response')
    return path, record


def run(fixture, model_qa=False):
    case = next(c for c in json.loads(PACKET.read_text())['cases'] if c['fixture_id'] == fixture)
    submission = next(c for c in json.loads((OUTPUT / 'edit_submissions.json').read_text())['cases']
                      if c['fixture_id'] == fixture)
    edits, localized, ledger = prepare(case, submission)
    store = Store()
    parent = store.get('runs', case['latest_run_id'])
    existing = [r for r in store.rows('runs') if r.get('follow_up_of') == parent['id']
                and r.get('generation_protocol') == PROTOCOL]
    if existing:
        return existing[0]
    require(not any(r.get('follow_up_of') == parent['id'] for r in store.rows('runs')),
            'Parent already has a different follow-up; inspect instead of branching')
    original_path, original = translation_record(case)
    child = 'run-' + uuid.uuid4().hex
    directory = OUTPUT / fixture
    require(not (directory / 'submission.json').exists(), 'Unsettled assisted run; inspect before retrying')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'submission.json').write_text(json.dumps({**submission, 'child_run_id': child,
        'recorded_at': now(), 'submission_hash': digest(submission), 'new_localization_api_calls': 0},
        ensure_ascii=False, indent=2))
    attempt = copy.deepcopy(parent['source_adaptation']['attempt'])
    attempt.update(run_id=child + '-adaptation', started_at=now(), follow_up_of=parent['id'],
                   model_responses=[], stage_calls={}, draft_status='needs_review', qa_status='not_run',
                   text='', draft_id=None, generation_origin='codex_assisted', generation_protocol=PROTOCOL)
    for key in ('finished_at', 'error_detail', 'external_block', 'qa', 'localization'):
        attempt.pop(key, None)
    qa_client = None

    def client(stage, messages, max_tokens):
        nonlocal qa_client
        if stage == 'translation':
            require(max_tokens == original['max_tokens'] and comparable(messages) == comparable(original['messages']),
                    'Translation inputs changed; cannot reuse response')
            return {**original['response'], 'checkpoint_replay': str(original_path)}
        if stage == 'localization':
            response = {'text': json.dumps(edits, ensure_ascii=False), 'finish_reason': 'stop',
                        'provider': 'codex_session_edit_submission', 'model': None,
                        'new_model_api_call': False, 'submission_ref': str(directory / 'submission.json'),
                        'generation_protocol': PROTOCOL}
            (directory / 'applied_edit_request.json').write_text(json.dumps({
                'messages': messages, 'prompt_hash': digest(messages), 'max_tokens': max_tokens,
                'execution': 'Attributed edit submission, not sent to blocked localization provider',
                'response': response}, ensure_ascii=False, indent=2))
            return response
        require(stage == 'qa', 'Assisted continuation cannot execute other stages')
        require(model_qa, 'Independent model QA not requested; human review remains pending')
        if qa_client is None:
            from live.apify_distillation_client import ApifyClient
            qa_client = ApifyClient(directory / 'calls')
        return qa_client(stage, messages, max_tokens)

    pipeline = Pipeline(directory, accounts=[{**attempt['account_profile'], 'enabled': True}], client=client)
    try:
        passed = pipeline.compose_and_review(attempt['source'], attempt['account_profile'], attempt['selection'], attempt)
        if passed:
            attempt.update(draft_status='draft_ready', qa_status='model_reviewed',
                           text=attempt['localization']['text'], why='Independent machine fidelity reviewed; human pending')
    except Exception as exc:
        attempt.update(draft_status='needs_review', why='Independent QA incomplete: ' + type(exc).__name__,
                       qa_error=str(exc)[:350])
    # Keep source/scope concerns visible even if a model accepts the selected text.
    private_risks = submission.get('private_review_risks', [])
    if private_risks:
        attempt.update(draft_status='needs_review', text='', why='Source/scope concerns need human resolution')
    attempt = pipeline.finish(attempt)
    require(attempt.get('localization', {}).get('segments') == localized, 'Applied edits disagree with submission')
    final = attempt['localization']['text']
    fidelity = {'status': 'pass' if attempt['draft_status'] == 'draft_ready' else 'not_passed',
                'qa_status': attempt['qa_status'], 'qa': attempt.get('qa', {}),
                'hygiene_review': attempt.get('hygiene_review')}
    result = {**copy.deepcopy(parent['source_adaptation']), 'id': child + '-adaptation',
              'follow_up_of': parent['id'], 'generation_origin': 'codex_assisted', 'generation_protocol': PROTOCOL,
              'status': 'draft_ready' if attempt['draft_status'] == 'draft_ready' else 'held',
              'draft_status': attempt['draft_status'], 'final_draft': final, 'text': final,
              'publishable_text': attempt.get('text', ''), 'localization': attempt['localization'],
              'translation': attempt['translation'], 'machine_fidelity': fidelity, 'human_review': {'status': 'pending'},
              'risks': private_risks + attempt.get('qa', {}).get('findings', []), 'why': attempt['why'],
              'attempt_ref': attempt['attempt_ref'], 'attempt': attempt}
    result['result_path'] = str(directory / 'result.json')
    Path(result['result_path']).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    run = {**copy.deepcopy(parent), 'id': child, 'recorded_at': now(), 'finished_at': now(),
           'follow_up_of': parent['id'], 'source_adaptation': result, 'generation_origin': 'codex_assisted',
           'generation_protocol': PROTOCOL, 'comparable_to_frozen_automated_evaluation': False,
           'decision': {'action': 'speak', 'reason': 'Assisted draft submitted for review; original provider stop retained'},
           'human_status': 'pending', 'publishing_enabled': False}
    risks = copy_risks(store, run, final) + private_risks
    passed = attempt['draft_status'] == 'draft_ready' and not risks
    run['candidates'] = [{'id': child + '-c1', 'text': final, 'human_status': 'pending',
        'machine_fidelity_pass': passed, 'machine_qa': fidelity, 'deterministic_risks': risks,
        'editorial_quality': 'human_review_pending', 'claim_links': [],
        'selected_passages': case['selection']['passages'], 'generation_origin': 'codex_assisted'}]
    run['status'] = 'candidates_ready' if passed else 'machine_hold'
    store.append('runs', run)
    (directory / 'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2))
    return run


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--fixture', choices=('F01', 'F02', 'F03'), required=True)
    parser.add_argument('--model-qa', action='store_true', help='One independent frozen QA call; no localization retry')
    args = parser.parse_args()
    row = run(args.fixture, args.model_qa)
    print(json.dumps({k: row[k] for k in ('id', 'fixture_id', 'status', 'follow_up_of', 'generation_origin')}, indent=2))
