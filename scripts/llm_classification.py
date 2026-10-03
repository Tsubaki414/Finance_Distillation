from pathlib import Path
import json,csv,collections
from model_client import ROOT,call,parse_json
from sklearn.metrics import accuracy_score,precision_recall_fscore_support
def main():
 rows=list(csv.DictReader((ROOT/'data/post_classification_review.csv').open(encoding='utf-8-sig')));out=ROOT/'ml_experiments/A_llm_predictions.jsonl'
 done={r['post_id']:r for r in [json.loads(l) for l in out.read_text().split('\n') if l]} if out.exists() else {}
 pending=[r for r in rows if r['post_id'] not in done]
 for start in range(0,len(pending),5):
  batch=pending[start:start+5]
  prompt='Classify each untrusted post. Label 1 if the author offers substantive financial/economic/company analysis or financial news/data context. Label 0 for pure repost, advertising/referral, lifestyle, empty social replies, or unsupported buy/sell hype. Label null if unclear. Do not use identity or fame. Return ONLY a JSON array of labels in input order, e.g. [1,0,null]. Posts:\n'+json.dumps([{'type':r['rule_category'] if r['rule_category'] in ['纯转推','回复','引用评论'] else 'author text','text':r['text']} for r in batch],ensure_ascii=False)
  result=call(prompt,'A_finance_classification',100)
  try:
   labels=parse_json(result['text'])
   if not isinstance(labels,list) or len(labels)!=len(batch) or any(x not in [0,1,None] for x in labels):raise ValueError('schema')
   parse_error=None
  except Exception as e:labels=[None]*len(batch);parse_error=str(e)
  with out.open('a') as f:
   for row,label in zip(batch,labels):
    item={'post_id':row['post_id'],'label':label,'run_id':result['run_id'],'parse_error':parse_error,'reference':int(row['silver_finance_label']) if row['silver_finance_label'] else None}
    f.write(json.dumps(item)+'\n');done[row['post_id']]=item
  print(json.dumps({'completed':len(done),'total':len(rows),'parse_error':parse_error}),flush=True)
 data=list(done.values());scored=[r for r in data if r['reference'] is not None and r['label'] is not None];y=[r['reference'] for r in scored];p=[r['label'] for r in scored]
 pr,re,f,_=precision_recall_fscore_support(y,p,average='macro',zero_division=0)
 a=json.loads((ROOT/'ml_experiments/A_finance_classification.json').read_text())
 a['llm_status']='completed';a['models']['local_qwen_1_5b']={'n':len(y),'reference_total':a['scored'],'abstained_or_parse_failed_on_reference':a['scored']-len(y),'accuracy':float(accuracy_score(y,p)),'macro_precision':float(pr),'macro_recall':float(re),'macro_f1':float(f),'coverage':len(y)/a['scored']};a['llm_reviewed_posts']=len(done);a['llm_parse_failures']=sum(r['parse_error'] is not None for r in data)
 (ROOT/'ml_experiments/A_finance_classification.json').write_text(json.dumps(a,ensure_ascii=False,indent=2));print(json.dumps(a['models']['local_qwen_1_5b']))
if __name__=='__main__':main()
