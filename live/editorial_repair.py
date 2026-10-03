"""Apply QA-addressed exact patches. No regeneration, reordering or silent edits."""
from copy import deepcopy
from live.distillation import require


def apply_repairs(candidate, findings, response):
    require(set(response)=={'edits'}, 'Repair returns edits only')
    edits=response['edits'];require(isinstance(edits,list), 'Repair edits missing')
    allowed={f['finding_id']:f for f in findings if f.get('repairable') is True and f.get('output_quote')}
    patches=[]
    for e in edits:
        require(isinstance(e,dict) and set(e)=={'finding_id','before','after'},'Invalid repair schema')
        require(all(isinstance(v,str) for v in e.values()),'Repair fields must be strings')
        f=allowed.get(e['finding_id']);require(f is not None,'Repair targets an unapproved finding')
        require(e['before']==f['output_quote'] and e['before'] and e['before']!=e['after'],'Repair must patch the exact flagged span')
        hits=[(i,r['text'].find(e['before'])) for i,r in enumerate(candidate['segments']) if e['before'] in r['text']]
        require(len(hits)==1,'Repair span missing or ambiguous')
        i,start=hits[0];row=candidate['segments'][i]
        require(row['text'].count(e['before'])==1,'Repair span repeats')
        require('\n\n' not in e['before'] and '\n\n' not in e['after'],'Repair cannot restructure paragraphs')
        require(e['after'].strip() or row['text'].strip()!=e['before'].strip(),'Repair cannot delete a paragraph')
        patches.append({**e,'segment_index':i,'start':start,'end':start+len(e['before'])})
    result=deepcopy(candidate)
    for i,row in enumerate(result['segments']):
        cursor=0;parts=[]
        for p in sorted([p for p in patches if p['segment_index']==i],key=lambda p:p['start']):
            require(p['start']>=cursor,'Overlapping repair patches')
            parts.extend([row['text'][cursor:p['start']],p['after']]);cursor=p['end']
        row['text']=''.join(parts)+row['text'][cursor:]
    result['text']='\n\n'.join(r['text'] for r in result['segments'])
    cursor=0
    for r,a in zip(result['segments'],result['alignment']):
        a.update(target_start=cursor,target_end=cursor+len(r['text']));cursor+=len(r['text'])+2
    return result,patches
