"""Re-evaluate real extracted candidates with language-aware parsing and exact source retrieval."""
import json,re,hashlib,datetime
import numpy as np
from model_client import ROOT,call,parse_json
def main():
 raw=[json.loads(s) for s in (ROOT/'data/raw_posts.jsonl').read_text().split('\n') if s];index={r['post_id']:i for i,r in enumerate(raw)}
 clean=[json.loads(s) for s in (ROOT/'data/clean_posts.jsonl').read_text().split('\n') if s];byid={r['post_id']:r for r in clean}
 em=json.loads((ROOT/'ml_experiments/embedding_manifest.json').read_text());vectors=np.load(ROOT/'ml_experiments'/em['cache'])['embeddings'];heldout=set(json.loads((ROOT/'ml_experiments/B_authorship.json').read_text())['test_ids']);reports=[]
 for path in sorted((ROOT/'knowledge_profiles').glob('*.json')):
  kp=json.loads(path.read_text());prev=kp.get('model_enrichment',{})
  if not prev.get('run_id') or not prev.get('selected_excerpts'):continue
  record=json.loads((ROOT/'runs/model_calls'/f"{prev['run_id']}.json").read_text());by={s['evidence_id']:s for s in prev['selected_excerpts']};accepted=[];diagnostics=[]
  try:
   obj=parse_json(record['text']);fs=obj if isinstance(obj,list) else obj.get('frameworks',[])
  except Exception:fs=[]
  for f in fs[:2]:
   ids=f.get('evidence_ids',[])
   if not isinstance(ids,list) or not ids or any(x not in by for x in ids) or not all(isinstance(f.get(k),str) and f[k].strip() for k in ['claim','mechanism','boundary']):continue
   evidence=[{'post_id':by[x]['post_id'],'quote':by[x]['excerpt'],'selection':'model-selected indexed source'} for x in dict.fromkeys(ids)];neighbors=[]
   if len(evidence)==1:
    anchor=byid[evidence[0]['post_id']];ai=index[anchor['post_id']];at=datetime.datetime.fromisoformat(anchor['created_at'])
    candidates=[r for r in clean if r['source_account_id']==kp['donor'] and r['post_id'] not in heldout and r['post_id']!=anchor['post_id'] and r['duplicate_group']!=anchor['duplicate_group'] and (r['thread_id'] or r['post_id'])!=(anchor['thread_id'] or anchor['post_id']) and abs((datetime.datetime.fromisoformat(r['created_at'])-at).days)>=7]
    candidates.sort(key=lambda r:float(vectors[ai]@vectors[index[r['post_id']]]),reverse=True)
    for r in candidates[:2]:
     parts=[p for p in r['text'].split('\n\n') if len(p)>=80];causal=[p for p in parts if re.search(r'因为|所以|如果|意味着|\b(?:because|if|risk|demand|driven)\b',p,re.I)]
     quote=(max(causal or parts,key=len) if parts else r['text'])[:600]
     evidence.append({'post_id':r['post_id'],'quote':quote,'selection':'same-donor embedding neighbor, different thread and >=7d apart'});neighbors.append({'post_id':r['post_id'],'cosine':float(vectors[ai]@vectors[index[r['post_id']]])})
   if len(evidence)<2:continue
   assert all(e['quote'] in byid[e['post_id']]['text'] for e in evidence)
   candidate={k:f[k] for k in ['claim','mechanism','boundary']}|{'evidence':evidence}
   result=call('Return exactly one digit, 1 or 0. Does at least TWO of the supplied source excerpts demonstrate this specific author reasoning mechanism? Return 0 for a generic shared topic, an invented/reversed causal link, a company fact mistaken for an author habit, or support from only one excerpt. This is an automated support diagnostic; company facts and author expertise are NOT verified. CANDIDATE:\n'+json.dumps(candidate,ensure_ascii=False),'framework_single_candidate_support',4,0,model_role='comparison')
   ok=result['text'].strip()=='1';diagnostics.append({'claim':f['claim'],'run_id':result['run_id'],'response':result['text'],'accepted':ok,'neighbor_retrieval':neighbors,'evidence_ids':[e['post_id'] for e in evidence]})
   if ok:accepted.append(candidate)
  kp['model_enrichment']={**prev,'frameworks':accepted,'status':'exact_source_linked_model_support_proxy' if accepted else 'no_supported_recurring_framework','support_diagnostics_v3':diagnostics,'validation_scope':'Exact source membership and >=2 distinct posts; any added neighbors use frozen embedding retrieval with thread/date separation. Same-model 0/1 support is a diagnostic, not human validation or verified expertise.'}
  path.write_text(json.dumps(kp,ensure_ascii=False,indent=2));reports.append({'donor':kp['donor'],'accepted_frameworks':len(accepted),'diagnostics':diagnostics});print(json.dumps({'stage':'framework_support_v3','donor':kp['donor'],'accepted':len(accepted)}),flush=True)
 (ROOT/'ml_experiments/knowledge_support_v3.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
