"""Meaningful data/provenance and API boundary checks, without pretending to be a human."""
import sys,json,hashlib,csv,datetime,traceback,zipfile,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import app,RAW,REGISTRY,MANIFEST,records,chart_svg
from fastapi.testclient import TestClient
from promotion_policy import output_gate

def main():
 results=[]
 def check(name,fn):
  try:fn();results.append({'name':name,'passed':True})
  except Exception as e:results.append({'name':name,'passed':False,'error':str(e),'trace':traceback.format_exc()[-1300:]})
 def assert_true(value,message='assertion failed'):
  if not value:raise AssertionError(message)
 raw={r['post_id']:r for r in RAW};clean=[json.loads(s) for s in (ROOT/'data/clean_posts.jsonl').read_text().split('\n') if s]
 check('original input hashes unchanged',lambda:assert_true(all(hashlib.sha256(Path(i['path']).read_bytes()).hexdigest()==i['sha256'] for i in MANIFEST['inputs'])))
 check('clean post identity, source and promotion exclusion',lambda:assert_true(all(r['post_id'] in raw and r['stable_author_id'] and r['classification']['keep'] and not output_gate(r['text']) and r['raw_source_ref']['payload_hash']==raw[r['post_id']]['raw_payload_hash'] and 'raw_text' not in r for r in clean)))
 review=list(csv.DictReader((ROOT/'data/post_classification_review.csv').open(encoding='utf-8-sig')))
 check('>=300 decisive rule references, explicitly not human',lambda:assert_true(sum(r['silver_finance_label'] in ['0','1'] for r in review)>=300 and all(not r['human_label'] for r in review)))
 def holdout():
  for file in ['A_finance_classification.json','B_authorship.json']:
   j=json.loads((ROOT/'ml_experiments'/file).read_text());tr=[raw[i] for i in j['train_ids']];te=[raw[i] for i in j['test_ids']]
   assert_true(not set(j['train_ids'])&set(j['test_ids']));assert_true(not {r['thread_id'] or r['post_id'] for r in tr}&{r['thread_id'] or r['post_id'] for r in te});assert_true(not {r['duplicate_group'] for r in tr}&{r['duplicate_group'] for r in te})
 check('predictive splits exclude held-out rows, threads and exact duplicates',holdout)
 sources={s['id']:s for s in REGISTRY['sources']}
 def evidence():
  for snapshot in REGISTRY['snapshots']:
   for f in snapshot['facts']:
    assert_true(f['source_id'] in sources)
    assert_true(all(sources[f['source_id']]['source_lines'][str(span['line'])]==span['text'] for span in f['spans']))
    normalized=' '.join(s['text'] for s in f['spans']).replace(',','')
    assert_true(str(f['value']) in normalized)
 check('facts match exact captured primary-source lines and numeric values',evidence)
 def chart_update():
  a,b=REGISTRY['snapshots'];sa=chart_svg({'facts':a['facts'],'evidence_snapshot':a});sb=chart_svg({'facts':b['facts'],'evidence_snapshot':b})
  assert_true(sa!=sb and '-23,000' in sa and '+21,000' in sb and '+162,000' in sb)
 check('chart recomputes revised and new observations',chart_update)
 with TestClient(app) as c:
  check('corpus API serves current real counts',lambda:assert_true(c.get('/api/corpus?retained=true&limit=2').json()['total']==len(clean)))
  check('unknown donor path rejected',lambda:assert_true(c.get('/api/profiles/unknown').status_code==400))
  check('foreign browser origin cannot mutate',lambda:assert_true(c.post('/api/evidence',json={'snapshot_id':'august-release'},headers={'origin':'https://untrusted.example'}).status_code==403))
  check('invalid generation contract rejected before inference',lambda:assert_true(c.post('/api/generate',json={'language':'invalid'}).status_code==422))
  check('promotional edits rejected before storage',lambda:assert_true(c.post('/api/edits',json={'draft_id':'nonexistent','text':'使用邀请码 ABC123 领取奖励'}).status_code==422))
  check('invalid persona weights rejected',lambda:assert_true(c.post('/api/personas',json={'persona_id':'macro','roles':{}}).status_code==422))
  check('no invented human reviews accepted',lambda:assert_true(c.post('/api/blind-review',json={'case_id':'nonexistent','reviewer':'AUTOMATED_INVALID_REQUEST','choice':'unknown','quality':3,'faithfulness':3,'edited_text':''}).status_code==422))
  check('issuer evidence image and original accessible',lambda:assert_true(c.get('/api/evidence-image/nvidia-income.png').content.startswith(b'\x89PNG') and c.get('/api/evidence-original/nvidia-10q.pdf').content.startswith(b'%PDF')))
  ds=records('draft')
  if ds:
   check('diagram rejects edges to missing nodes',lambda:assert_true(c.post('/api/diagram',json={'draft_id':ds[0]['id'],'nodes':[{'id':'facts','label':'Observation'}],'edges':[{'from':'facts','to':'missing'}]}).status_code==422))
   def diagram_roundtrip():
    d=next(d for d in ds if d.get('engine','').startswith('guarded-') and d['evidence_snapshot']['id']=='august-release')
    spec=c.get('/api/diagram/'+d['id']).json();node_ids={n['id'] for n in spec['nodes']}
    assert_true({'fact:'+f['id'] for f in d['facts']}<=node_ids)
    assert_true(all(e['from'] in node_ids and e['to'] in node_ids for e in spec['edges']))
    saved=c.post('/api/diagram',json={k:spec[k] for k in ['draft_id','nodes','edges']});assert_true(saved.status_code==200)
    fetched=c.get('/api/diagram/'+d['id']).json();assert_true(fetched['id']==saved.json()['id'] and fetched['nodes']==spec['nodes'])
    z=zipfile.ZipFile(io.BytesIO(c.get('/api/export/'+d['id']).content));exported=json.loads(z.read('event-structure.json'))
    assert_true(exported['nodes']==spec['nodes'] and z.read('event-structure.svg').startswith(b'<svg'))
    assert_true(c.get('/api/diagram-image/'+d['id']+'.svg').status_code==200 and 'editorial-reviews.json' in z.namelist())
    (ROOT/'runs/diagram-roundtrip.json').write_text(json.dumps({'draft_id':d['id'],'diagram_id':saved.json()['id'],'nodes':len(spec['nodes']),'edges':len(spec['edges']),'test':'Automated integration check saved the unmodified source-derived diagram as a version; not human editing'},indent=2))
   check('source-dependent diagram can be saved, replayed and exported',diagram_roundtrip)
 def numeric_contract():
  from guarded import validate_body
  fs=[{**f,'label':'F'+str(i+1)} for i,f in enumerate(next(s for s in REGISTRY['snapshots'] if s['id']=='august-release')['facts'])]
  good={'paragraphs':[{'interpretation':'In 2026-08 the monthly increase was 162 thousand, above the revised July increase of 21 thousand. This is not a payroll level.','fact_refs':['F1','F2']},{'interpretation':'The unemployment rate was unchanged at 4.1 percent. That fact alone does not determine labor participation.','fact_refs':['F3']},{'interpretation':'Additional wage and participation evidence is needed before drawing a broader conclusion.','fact_refs':[]}]}
  validate_body(good,fs)
  lexical_variants=json.loads(json.dumps(good));lexical_variants['paragraphs'][0]['interpretation']='The July estimate was revised from negative 23,000 to positive 21,000. This is a change in the estimate, not delayed hiring.';lexical_variants['paragraphs'][0]['fact_refs']=['F1'];lexical_variants['paragraphs'][2]['interpretation']='The evidence bundle lacks wage data and analyst forecasts, preventing a definitive policy conclusion.'
  validate_body(lexical_variants,fs)
  wrong_value=json.loads(json.dumps(good));wrong_value['paragraphs'][0]['interpretation']=wrong_value['paragraphs'][0]['interpretation'].replace('162 thousand','162 million')
  wrong_citation=json.loads(json.dumps(good));wrong_citation['paragraphs'][0]['fact_refs']=['F3']
  for bad in [wrong_value,wrong_citation]:
   try:validate_body(bad,fs)
   except ValueError:pass
   else:raise AssertionError('Wrong unit or month citation passed')
 check('calendar values accepted; wrong scale and mismatched month citation rejected',numeric_contract)
 report={'executed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':results,'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'test_scope':'Real datasets and FastAPI handlers, no browser automation claim, no human review submission, no inference for negative tests','raw_sha256':hashlib.sha256((ROOT/'data/raw_posts.jsonl').read_bytes()).hexdigest(),'clean_sha256':hashlib.sha256((ROOT/'data/clean_posts.jsonl').read_bytes()).hexdigest()}
 (ROOT/'runs/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
 if report['failed']:sys.exit(1)
if __name__=='__main__':main()
