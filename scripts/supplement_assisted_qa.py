"""One independent semantic diagnostic for an already machine-held assisted draft.

Never changes the candidate, marks a deterministic finding resolved, or publishes.
Used to distinguish guard implementation errors from actual content defects.
"""
import argparse
import copy
import json
from pathlib import Path
from live import distillation_prompts
from live.apify_distillation_client import ApifyClient
from live.distillation import Pipeline, CHECKS, require
from live.distillation_source import now, digest
from scripts.review_assisted_account_sources import OUTPUT


def supplement(fixture, max_tokens=6500):
    require(max_tokens in (6500, 13000), 'Only the original limit or one bounded length-stop follow-up')
    prior = None
    directory = OUTPUT / fixture / ('supplemental_qa' if max_tokens == 6500 else 'supplemental_qa_length_followup')
    if max_tokens != 6500:
        require(fixture == 'F01', 'Length follow-up only for recorded F01 interruption')
        prior_files = list((OUTPUT / fixture / 'supplemental_qa/calls').glob('*.json'))
        require(len(prior_files) == 1, 'Ambiguous previous QA call')
        prior = json.loads(prior_files[0].read_text())
        require(prior['status'] == 'completed' and prior['response']['finish_reason'] == 'length'
                and not prior['response'].get('refusal'), 'Only output-length interruptions may continue here')
    output = directory / 'result.json'
    if output.exists():
        return json.loads(output.read_text())
    require(not directory.exists(), 'Unsettled diagnostic; inspect calls before trying again')
    directory.mkdir(parents=True)
    result = json.loads((OUTPUT / fixture / 'result.json').read_text())
    attempt = copy.deepcopy(result['attempt'])
    source, selection = attempt['source'], attempt['selection']
    profile = attempt['account_profile']
    record = {'fixture_id': fixture, 'parent_adaptation_id': result['id'], 'started_at': now(),
              'candidate_hash': digest(result['final_draft']), 'generation_origin': 'codex_assisted',
              'scope': 'Supplemental semantic diagnostic only; does not clear original machine holds',
              'deterministic_hold_preserved': True, 'human_status': 'pending', 'max_tokens': max_tokens,
              'follow_up_of_call': prior.get('call_id') if prior else None,
              'execution_change': 'Output limit 6500 -> 13000, identical messages' if prior else None}
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    try:
        transport = ApifyClient(directory / 'calls')
        def client(stage, messages, limit):
            if prior:
                require(messages == prior['messages'], 'Length follow-up may not alter QA inputs or instructions')
            return transport(stage, messages, limit)
        pipeline = Pipeline(directory, accounts=[{**profile, 'enabled': True}], client=client)
        value = pipeline.ask(attempt, 'qa', distillation_prompts.QA,
            {'source': source, 'selection': selection, 'translation': attempt['translation'],
             'localization': attempt['localization'], 'target_language': profile['lang']}, max_tokens)
        require([r.get('paragraph_id') for r in value.get('checks', [])] ==
                [r['paragraph_id'] for r in selection['passages']], 'QA missed selected paragraphs')
        require(all(all(type(r.get(k)) is bool for k in CHECKS) and r.get('evidence')
                    for r in value['checks']), 'QA dimension evidence missing')
        require(type(value.get('selection_context_complete')) is bool, 'Missing selection check')
        require(isinstance(value.get('findings'), list), 'Missing semantic findings')
        for finding in value['findings']:
            require(finding.get('paragraph_id') in {p['paragraph_id'] for p in selection['passages']},
                    'QA cited unknown paragraph')
            require(not finding.get('source_quote') or finding['source_quote'] in source['original_text'],
                    'QA source quote not exact')
            require(not finding.get('output_quote') or finding['output_quote'] in result['final_draft']
                    or finding['output_quote'] in attempt['translation']['text'], 'QA output quote not exact')
        record.update(status='model_reviewed', semantic=value,
                      semantic_dimensions_all_pass=all(all(r[k] for k in CHECKS) for r in value['checks']))
    except Exception as exc:
        record.update(status='incomplete', error_type=type(exc).__name__, error=str(exc)[:400])
    record.update(finished_at=now(), model_responses=[r for r in attempt['model_responses']
                  if r['stage'] == 'qa'])
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__); p.add_argument('--fixture', choices=('F01', 'F02'), required=True)
    p.add_argument('--max-tokens', type=int, choices=(6500, 13000), default=6500)
    args = p.parse_args()
    r = supplement(args.fixture, args.max_tokens)
    print(json.dumps({k: r.get(k) for k in ('fixture_id', 'status', 'semantic_dimensions_all_pass',
                                          'error_type', 'error')}, indent=2))
