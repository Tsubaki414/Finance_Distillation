"""Adversarial checks against saved real fixture output; paid QA only when necessary."""
from pathlib import Path
import argparse
import copy
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.distillation import Pipeline, CHECKS
from live import distillation_prompts as prompts
from live.fidelity import deterministic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required for semantic QA calls')
    args.out.mkdir(parents=True, exist_ok=False)
    macro = json.loads((args.fixtures / 'EN_SHORT_TO_ZH_MACRO/metadata.json').read_text())
    industry = json.loads((args.fixtures / 'ZH_SHORT_TO_EN_INDUSTRY/metadata.json').read_text())
    assert macro['draft_status'] == industry['draft_status'] == 'draft_ready'
    pipeline = Pipeline(args.out / 'artifacts')
    # Deliberately incorrect drafts, never fed back into translation or the production queue.
    bad_macro = [
        ('remove_condition', '政策利率下调25个基点，从5.25%降至5.00%。我认为，融资环境可能趋于宽松。这并不能说明信贷需求已经复苏。'),
        ('strengthen_may_to_will', '政策利率下调25个基点，从5.25%降至5.00%。我认为，如果银行将降息传导下去，融资环境必然会趋于宽松。这并不能说明信贷需求已经复苏。'),
        ('reverse_negation', '政策利率下调25个基点，从5.25%降至5.00%。我认为，如果银行将降息传导下去，融资环境可能趋于宽松。这证明信贷需求已经复苏。'),
        ('invent_new_view', macro['text'] + '因此，现在应该加仓风险资产。'),
        ('add_author_footer', macro['text'] + '\n来源：Synthetic Macro Desk'),
    ]
    rows = [(name, macro, text) for name, text in bad_macro]
    rows.append(('currency_swap', industry, industry['text'].replace('yuan', 'USD').replace('CNY', 'USD').replace('RMB', 'USD')))
    rows.append(('percentage_points_to_percent', industry, industry['text'].replace('percentage points', 'percent')))
    rows.append(('entity_swap', industry, industry['text'].replace('Qinghe Software', 'Another Company')))
    results = []
    for name, original, text in rows:
        assert text != original['text'], name + ' mutation was not applied'
        source = original['source']
        selected = original['selection']['passages']
        loc = copy.deepcopy(original['localization'])
        assert len(loc['segments']) == 1
        loc['segments'][0]['text'] = text
        loc['text'] = text
        deterministic_findings = deterministic(source, selected, loc['segments'], original['target_language'], 'localization')
        verdict = None
        blocked = bool(deterministic_findings)
        if not blocked:
            attempt = {'stage_calls': {}, 'model_responses': []}
            verdict = pipeline.ask(attempt, 'qa', prompts.QA,
                {'source': source, 'selection': original['selection'], 'translation': original['translation'],
                 'localization': loc, 'target_language': original['target_language']}, 4500)
            checks = verdict.get('checks') or []
            valid_coverage = [c.get('paragraph_id') for c in checks] == [p['paragraph_id'] for p in selected]
            blocked = not (valid_coverage and verdict.get('selection_context_complete') is True and
                not any(f.get('status', 'open') == 'open' for f in verdict.get('findings', [])) and
                all(all(c.get(k) is True for k in CHECKS) for c in checks))
        result = {'mutation': name, 'mutated_text': text, 'blocked': blocked,
                  'deterministic_findings': deterministic_findings, 'semantic_review': verdict}
        results.append(result)
        (args.out / (name + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({'mutation': name, 'blocked': blocked, 'semantic_call': verdict is not None}), flush=True)
    unsuitable = pipeline.run({
        'id': 'out-of-scope-regression', 'source_id': 'synthetic_fixture', 'source_type': 'fixture',
        'synthetic': True, 'content_complete': True, 'source_language': 'en',
        'title': 'Garden soil moisture experiment',
        'text': 'In our garden trial, mulch slowed evaporation by shading the soil, but it also delayed spring warming. For seedlings that need warm soil, applying mulch after germination is therefore preferable to covering the bed before sowing. That recommendation depends on the soil being wet enough at germination; in a dry climate, preserving moisture may matter more than earlier warming.'})
    stopped = ((unsuitable.get('route') or {}).get('decision') == 'NONE' and not unsuitable['text'] and
               not any(unsuitable['stage_calls'].get(s) for s in ('translation', 'localization', 'qa')))
    results.append({'mutation': 'valuable_but_no_account', 'blocked': stopped,
                    'result_ref': unsuitable['attempt_ref'], 'stage_calls': unsuitable['stage_calls']})
    print(json.dumps({'mutation': 'valuable_but_no_account', 'blocked': stopped,
                      'decision': (unsuitable.get('route') or {}).get('decision')}), flush=True)
    (args.out / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r['blocked'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
