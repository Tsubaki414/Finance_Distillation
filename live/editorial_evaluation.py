"""Evaluation bookkeeping, not an automatic quality score or rollout decision."""
from collections import Counter
import json
from pathlib import Path
from live.distillation_source import digest


def summarize(cases):
    modes=sorted({mode for case in cases for mode in case.get('results',{})})
    result={'case_count':len(cases),'modes':{},'human_edit_distance':None,
            'human_editorial_quality':None,'rollout_decision':'requires human review'}
    for mode in modes:
        all_rows=[c['results'][mode] for c in cases if mode in c.get('results',{})]
        rows=[r for r in all_rows if r['status']!='not_attempted']
        statuses=Counter(r['status'] for r in rows);n=len(rows)
        result['modes'][mode]={'attempts':n,'statuses':dict(statuses),
            'not_attempted':len(all_rows)-n,
            'skip_rate':sum(statuses[s] for s in ('skipped','not_suitable'))/n if n else None,
            'hold_rate':sum(v for s,v in statuses.items() if s not in ('draft_ready','skipped','not_suitable'))/n if n else None,
            'repair_rounds':sum(r.get('repair_rounds',0) for r in rows),
            'failure_reasons':dict(Counter(r.get('why','unspecified') for r in rows if r['status'] not in ('draft_ready','skipped','not_suitable')))}
    paired=[c for c in cases if {'current','candidate'}<=set(c.get('results',{})) and
            all(c['results'][mode]['status']!='not_attempted' for mode in ('current','candidate'))]
    result['paired_cases']=len(paired)
    routed=[c for c in paired if all((c['results'][m].get('route') or {}).get('decision') for m in ('current','candidate'))]
    result['route_comparisons']=len(routed)
    result['route_agreement']=sum(c['results']['current'].get('account_id')==c['results']['candidate'].get('account_id') and
        c['results']['current']['route']['decision']==c['results']['candidate']['route']['decision'] for c in routed)/len(routed) if routed else None
    moved=[c for c in paired if all(c['results'][m].get('account_id') for m in ('current','candidate'))]
    result['language_agreement_on_both_routed']=sum(c['results']['current'].get('target_language')==c['results']['candidate'].get('target_language') for c in moved)/len(moved) if moved else None
    return result


def save_review_packet(cases,directory,feedback=None):
    """Exact candidates, anonymous order, separate private key. No synthetic approval.

    Held candidates can be judged too. Empty outputs and failure reasons are kept
    in the private summary; a nonexistent draft is never presented as a candidate.
    """
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    packet=[];key=[]
    for case in cases:
        options=[]
        for mode,row in case.get('results',{}).items():
            if not row.get('candidate_text'):continue
            attempt=json.loads(Path(row['metadata_ref']).read_text())
            record=feedback.register(attempt,row['metadata_ref']) if feedback else None
            token=digest([case['case'],attempt['run_id'],row['candidate_text']])
            options.append((token,mode,row,attempt,record))
        for i,(token,mode,row,attempt,record) in enumerate(sorted(options,key=lambda x:x[0])):
            label=chr(65+i);source=attempt['source']
            packet.append({'case':case['case'],'label':label,'account_id':row.get('account_id'),
                'target_language':row.get('target_language'),'text':row['candidate_text'],
                'source':{k:source.get(k) for k in ('original_text','source_hash','author_name','url','source_language')},
                'candidate_id':record['id'] if record else None,'human_review':'pending'})
            key.append({'case':case['case'],'label':label,'mode':mode,'metadata_ref':row['metadata_ref'],
                        'status':row['status'],'run_id':attempt['run_id']})
    for name,value in [('blind_candidates.json',packet),('private_blind_key.json',key),('comparison.json',summarize(cases))]:
        (directory/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return packet
