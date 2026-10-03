"""Explicit isolated evaluation/shadow runs; no historical queue mutation or publication."""
import argparse
import html
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from live.editorial import EditorialPipeline
from live.distillation import Pipeline, export
from live.distillation_source import digest, now
from live.source_recovery import SourceRecovery
from live.background import BackgroundResolver
from live.editorial_evaluation import save_review_packet
from live.localization_feedback import FeedbackStore
from scripts.frozen_localization_baseline import run as run_frozen_baseline


def archive_posts():
    posts={}
    for line in (ROOT/'data/raw_posts.jsonl').read_text().split('\n'):
        if not line:continue
        row=json.loads(line)
        posts[row['post_id']]={**row,'text':html.unescape(row['text'].replace('\\n','\n'))}
    return posts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--cases');p.add_argument('--shadow',action='store_true')
    p.add_argument('--baseline-code',type=Path,help='Saved pre-refactor code root, used only with --shadow')
    p.add_argument('--accounts',type=Path,help='Optional isolated account config; does not modify production accounts')
    p.add_argument('--allow-host',action='append',default=[]);p.add_argument('--background-catalog',type=Path)
    p.add_argument('--repair-rounds',type=int,default=1);a=p.parse_args()
    if not a.live:p.error('--live required for paid requests')
    if a.baseline_code and not a.shadow:p.error('--baseline-code requires --shadow')
    if a.baseline_code and a.accounts:p.error('Frozen production baseline uses its own saved accounts; omit --accounts')
    a.out.mkdir(parents=True,exist_ok=False)
    cases=json.loads(a.inputs.read_text())['cases']
    accounts=json.loads(a.accounts.read_text())['accounts'] if a.accounts else None
    if a.cases:cases=[c for c in cases if c['case'] in a.cases.split(',')]
    assert cases
    protected=['live/accounts.json','live/store/content_queue.json','live/store/analysis_corpus.jsonl']
    before={name:digest((ROOT/name).read_text()) for name in protected}
    recovery=SourceRecovery(a.out/'retrieval',a.allow_host,archive_posts())
    bg=BackgroundResolver(recovery,json.loads(a.background_catalog.read_text()) if a.background_catalog else [])
    modes=['current','candidate'] if a.shadow else ['candidate']
    summary={'started_at':now(),'input_file':str(a.inputs),'input_hash':digest(a.inputs.read_text()),
             'evaluation':'paired_shadow' if a.shadow else 'candidate_evaluation','human_review':'pending','cases':[]}
    code_files=['live/distillation.py','live/distillation_prompts.py','live/distillation_source.py','live/accounts.json',
                'live/editorial.py','live/editorial_prompts.py','live/editorial_repair.py','live/numeric_fidelity.py',
                'live/source_recovery.py','live/background.py','live/distillation_client.py','scripts/run_editorial_v2.py']
    code_files+=['live/domain_policy.py','live/finance_policy.py','live/language_support.py','live/model_json.py','live/writer_backend.py','live/source_hygiene.py']
    summary['code_hashes']={name:digest((ROOT/name).read_text()) for name in code_files}
    summary['recovery_hosts']=a.allow_host;summary['repair_limit']=a.repair_rounds
    summary['background_catalog_hash']=digest(a.background_catalog.read_text()) if a.background_catalog else None
    summary['baseline_code']=str(a.baseline_code) if a.baseline_code else None
    summary['account_file']=str(a.accounts) if a.accounts else 'live/accounts.json'
    summary['account_file_hash']=digest(a.accounts.read_text()) if a.accounts else summary['code_hashes']['live/accounts.json']
    if a.baseline_code:
        summary['baseline_hashes']={str(p.relative_to(a.baseline_code)):digest(p.read_text()) for p in (a.baseline_code/'live').glob('*.py')}
    (a.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    external_block=None
    for case in cases:
        print('Start '+case['case'],flush=True)
        row={'case':case['case'],'tags':case.get('tags',[]),'results':{}}
        for mode in modes:
            directory=a.out/mode/case['case']
            if external_block:
                row['results'][mode]={'status':'not_attempted','why':external_block,'candidate_text':None,'ready_text':None,'stage_calls':{},'repair_rounds':0}
                continue
            if mode=='current' and a.baseline_code:
                result=run_frozen_baseline(case['source'],directory,a.baseline_code,ROOT)
            else:
                pipe=Pipeline(directory/'artifacts',accounts=accounts) if mode=='current' else EditorialPipeline(directory/'artifacts',
                    accounts=accounts,recovery=recovery,background=bg,max_repair_rounds=a.repair_rounds)
                result=pipe.run(case['source']);export(result,directory)
            candidate=result.get('localization',{}).get('text','')
            (directory/'candidate.txt').write_text(candidate)
            (directory/'original_candidate.txt').write_text(result.get('original_candidate',{}).get('text',candidate))
            row['results'][mode]={'status':result['draft_status'],'route':result.get('route'),'account_id':result.get('account_id'),
                'target_language':result.get('target_language'),'candidate_text':candidate,'ready_text':result['text'],
                'stage_calls':result['stage_calls'],'repair_rounds':len(result.get('repair_history',[])),
                'error_detail':result.get('error_detail'),'why':result['why'],'metadata_ref':str(directory/'metadata.json')}
            print(json.dumps({'case':case['case'],'mode':mode,'status':result['draft_status'],'error':result.get('error_detail')},ensure_ascii=False),flush=True)
            if result.get('external_block'):external_block=result['external_block']
        summary['cases'].append(row)
        (a.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    summary['production_data_unchanged']=all(digest((ROOT/n).read_text())==h for n,h in before.items())
    summary['finished_at']=now();(a.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    # Evaluation review records stay in the isolated output. Registration into
    # the working review app is explicit via /api/localization-review/register.
    save_review_packet(summary['cases'],a.out/'review',FeedbackStore(a.out/'feedback'))
    return int(not summary['production_data_unchanged'])

if __name__=='__main__':raise SystemExit(main())
