from pathlib import Path
import json,sqlite3,sys,uuid,datetime,re,hashlib,html,zipfile,io,threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT))
from model_client import call,parse_json,now
from promotion_policy import output_gate
from qa.status import classify as qa_classify, assert_deliverable, label as qa_label
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,Response,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
import importlib.util
sp=importlib.util.spec_from_file_location('style',ROOT/'.agents/skills/financial-persona-distillation/scripts/stylometry.py');style=importlib.util.module_from_spec(sp);sp.loader.exec_module(style)
app=FastAPI(title='Financial Persona Evidence Lab');LOCK=threading.Lock()
from backend.localization_review import router as localization_review_router
app.include_router(localization_review_router)
from backend.content_dashboard import router as content_dashboard_router
app.include_router(content_dashboard_router)
@app.get('/content-dashboard')
def content_dashboard_page():return FileResponse(ROOT/'frontend/content-dashboard.html')
@app.get('/localization-review')
def localization_review_page():return FileResponse(ROOT/'frontend/localization-review.html')
def readj(p):return json.loads((ROOT/p).read_text())
RAW=[json.loads(l) for l in (ROOT/'data/raw_posts.jsonl').read_text().split('\n') if l]
for row in RAW:
 row['raw_text']=row['text'];row['text']=row.get('analysis_text',row['text']);row['external_links']=row.get('analysis_external_links',row['external_links'])
MANIFEST=readj('data/corpus_manifest.json');REGISTRY=readj('data/evidence/registry.json')
def db():
 c=sqlite3.connect(ROOT/'data/lab.sqlite',timeout=30);c.row_factory=sqlite3.Row;return c
with db() as c:
 c.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
def save(kind,data):
 data={'id':kind+'-'+uuid.uuid4().hex[:12],'created_at':now(),**data}
 with db() as c:c.execute('INSERT INTO records VALUES (?,?,?,?)',(data['id'],kind,data['created_at'],json.dumps(data,ensure_ascii=False)))
 return data
LEGACY_KINDS={'legacy_invalid_output','quarantined-generation'}
def get_row(rid):
 with db() as c:r=c.execute('SELECT kind,payload FROM records WHERE id=?',(rid,)).fetchone()
 if not r:raise HTTPException(404,'Record not found')
 return r[0],json.loads(r[1])
def get(rid):return get_row(rid)[1]
def get_active(rid,audit=False):
 # Single choke point for legacy isolation. Every route that renders, exports, derives from or
 # attaches to a stored record must go through here, not through get(); see docs/KNOWN_FAILURES.md.
 kind,payload=get_row(rid)
 if kind in LEGACY_KINDS:
  if not audit:raise HTTPException(409,kind+' is not effective content; explicit audit=true is required')
  return {**payload,'record_kind':kind,'content_status':'legacy_invalid_output_not_effective_content'}
 return payload
def records(kind):
 with db() as c:return [json.loads(r[0]) for r in c.execute('SELECT payload FROM records WHERE kind=? ORDER BY created_at DESC',(kind,))]
def persona(pid):
 if pid not in ['macro','industry','risk']:raise HTTPException(400,'Unknown persona')
 versions=[r for r in records('persona') if r['persona']['id']==pid]
 return versions[0]['persona'] if versions else readj(f'personas/{pid}.json')
def snapshot(sid):
 if sid.startswith('evidence-'):return get(sid)['snapshot']
 for s in REGISTRY['snapshots']:
  if s['id']==sid:return s
 raise HTTPException(400,'Unknown evidence snapshot')
@app.middleware('http')
async def local_only(request:Request,call_next):
 if request.headers.get('host','').split(':')[0] not in ['127.0.0.1','localhost','testserver']:return JSONResponse({'error':'localhost only'},status_code=403)
 if request.method not in ['GET','HEAD'] and request.headers.get('origin') not in [None,'http://127.0.0.1:8680','http://localhost:8680']:return JSONResponse({'error':'origin rejected'},status_code=403)
 response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'";return response
@app.get('/api/status')
def status():return {'phase':readj('acceptance-state.json')['label'],'acceptance':readj('acceptance-state.json'),'corpus':MANIFEST,'ml':readj('ml_experiments/run_summary.json'),'drafts':0,'baseline_drafts':len(records('draft')),'human_reviews':len(records('human-review')),'x_collector':{'selected':'Xquik','enabled':False,'new_requests':0,'reason':'missing key and live cost estimate'}}
@app.get('/api/corpus')
def corpus(donor:str='',q:str='',category:str='',retained:str='',offset:int=0,limit:int=20):
 rows=[r for r in RAW if (not donor or r['source_account_id']==donor) and (not q or q.lower() in r['text'].lower()) and (not category or r['classification']['category']==category) and (not retained or r['classification']['keep']==(retained=='true'))]
 return {'total':len(rows),'offset':offset,'items':[{k:v for k,v in r.items() if k!='source_record'} for r in rows[max(0,offset):max(0,offset)+min(100,max(1,limit))]],'categories':sorted({r['classification']['category'] for r in RAW})}
@app.get('/api/profiles/{donor}')
def profiles(donor:str):
 if donor not in [d['handle'] for d in MANIFEST['donors']]:raise HTTPException(400,'Unknown donor')
 return {kind:readj(f'{kind}/{donor}.json') for kind in ['knowledge_profiles','style_profiles','content_habit_profiles']}
@app.get('/api/personas')
def personas():return [persona(p) for p in ['macro','industry','risk']]
@app.get('/api/experiments')
def experiments():return {n:readj(p) for n,p in {'classification':'ml_experiments/A_finance_classification.json','authorship':'ml_experiments/B_authorship.json','clusters':'topic_clusters/clusters.json','self_similarity':'ml_experiments/self_similarity.json','drift':'topic_clusters/donor_distributions.json','compatibility':'donor_compatibility_matrix.json'}.items()}
@app.get('/api/finance-supplement')
def finance_supplement():return readj('data/finance_supplement/earnings-recap-and-estimate-analysis.json')
@app.get('/api/evidence-image/nvidia-income.png')
def evidence_image():return FileResponse(ROOT/'data/evidence/nvidia-q2-fy2027-income-statement.png')
@app.get('/api/evidence-original/nvidia-10q.pdf')
def evidence_original():return FileResponse(ROOT/'data/evidence/nvidia-q2-fy2027-10q.pdf',media_type='application/pdf')
@app.get('/api/promotion-audit')
def promotion_audit():return readj('runs/promotion-cleanup.json')
def editorial_reviews(rid:str):
 p=ROOT/'runs/automated-editorial-reviews.json'
 return [r for r in json.loads(p.read_text()).get('reviews',[]) if r['draft_id']==rid] if p.exists() else []
@app.get('/api/editorial-reviews/{rid}')
def editorial_reviews_api(rid:str,audit:bool=False):
 get_active(rid,audit);return editorial_reviews(rid)
class PersonaEdit(BaseModel):
 persona_id:str;roles:dict
@app.post('/api/personas')
def edit_persona(body:PersonaEdit):
 p=persona(body.persona_id)
 if set(body.roles)!=set(p['roles']):raise HTTPException(422,'Use the five existing roles')
 for role,weights in body.roles.items():
  if role=='visual' and not weights:continue
  if set(weights)-set(p['donors']) or not weights or any(not isinstance(v,(float,int)) or v<0 or v>1 for v in weights.values()) or abs(sum(weights.values())-1)>1e-6:raise HTTPException(422,'Weights must be nonnegative, total 1, and use persona donors')
 p['roles']=body.roles;p['weights_origin']='user-edited; requires ablation revalidation'
 profiles={h:readj(f'style_profiles/{h}.json') for h in p['donors']}
 p['measured_style_targets']={k:sum(body.roles['language'].get(h,0)*profiles[h]['features'][k]['mean'] for h in p['donors']) for k in p['measured_style_targets']}
 return save('persona',{'persona':p})
@app.get('/api/events')
def events():return {**REGISTRY,'topic_shifts':readj('topic_clusters/donor_distributions.json'),'ingested':records('evidence')}
class Ingest(BaseModel):
 snapshot_id:str
@app.post('/api/evidence')
def ingest(body:Ingest):return save('evidence',{'snapshot':snapshot(body.snapshot_id),'ingestion':'actual local ingestion of a captured primary publication; historical replay when old release selected'})
def context(p,condition):
 if condition=='none':return {}
 if condition=='description':return {'description':p['description']}
 d={'description':p['description'],'analysis_angle':p['analysis_angle'],'style_targets':p['measured_style_targets']}
 if condition in ['exemplar','multi']:
  samples=[]
  for donor in p['donors']:
   candidates=[r for r in RAW if r['source_account_id']==donor and r['classification']['keep'] and re.search(r'就业|非农|宏观|利率|流动性',r['text'])]
   if not candidates:candidates=[r for r in RAW if r['source_account_id']==donor and r['classification']['keep']]
   chosen=sorted(candidates,key=lambda r:r['created_at'])[0]
   samples.append({'post_id':chosen['post_id'],'donor':donor,'text':chosen['text'][:1500],'truncated':len(chosen['text'])>1500})
  d['style_examples_untrusted']=samples
 if condition=='multi':
  d['separate_roles']=p['roles'];d['knowledge']={h:readj(f'knowledge_profiles/{h}.json')['features'] for h in p['donors']};d['habits']={h:{k:readj(f'content_habit_profiles/{h}.json')[k] for k in ['interval_hours','theme_length']} for h in p['donors']}
 return d
def checks(text,facts,examples):
 allowed=set()
 for f in facts:
  for v in [str(f['value']),format(f['value'],','),str(f['value']/10000),str(f['value']/1000)]:allowed.add(v)
 numbers=re.findall(r'(?<![A-Za-z_\d])[-+]?\d[\d,]*(?:\.\d+)?',re.sub(r'\[(?:F\d+|[^\]]*payroll[^\]]*|unemployment)\]','',text));unknown=[n for n in numbers if n.lstrip('+').replace(',','') not in {a.replace(',','') for a in allowed} and n not in ['2026','07','08','1','2','3']]
 best={'chars':0,'post_id':None}
 import difflib
 for e in examples:
  match=difflib.SequenceMatcher(None,text,e['text'],autojunk=False).find_longest_match()
  if match.size>best['chars']:best={'chars':match.size,'post_id':e['post_id']}
 return {'numeric_mentions_requiring_review':unknown,'number_check':'lexical candidate flags; not entailment proof','ai_pattern_flags':style.ai_flags(text),'longest_exemplar_overlap':best,'human_review':'pending'}
class Generate(BaseModel):
 persona_id:str='macro';snapshot_id:str='august-release';language:str='zh';condition:str='multi';parent_id:str|None=None;editor_note:str=Field(default='',max_length=4000)
def generate(body:Generate):
 if body.language not in ['zh','en'] or body.condition not in ['none','description','profile','exemplar','multi']:raise HTTPException(422,'Invalid language or condition')
 p=persona(body.persona_id);s=snapshot(body.snapshot_id);ctx=context(p,body.condition);facts=[{**f,'label':'F'+str(i+1)} for i,f in enumerate(s['facts'])]
 parent=get(body.parent_id) if body.parent_id else None
 edits=[e for e in records('edit') if parent and e['draft_id']==parent['id']]
 preserved=[{'edit_id':e['id'],'text':e['text'],'resolution':'preserved separately; editor must reconcile against new evidence'} for e in edits]
 payload={'evidence_published_at':s['published_at'],'facts':facts,'persona':ctx,'language':body.language,'editorial_note_untrusted':body.editor_note}
 with LOCK:
  plan=call('Create an independent analysis plan for this evidence and audience. No mother draft exists. Distinguish observations, interpretations, alternatives, invalidation and missing evidence. Do not invent facts. Write concise planning prose in the requested language, at most 220 words. INPUT:\n'+json.dumps(payload,ensure_ascii=False),'independent_analysis_plan',500)
  draft=call('Write an original financial research working draft, 3 short paragraphs, about 180 English words or 320 Chinese characters. Use only the supplied facts for factual claims; cite their [F1] labels. Interpretations must be conditional. No invented prices, earnings, positions or forecasts. No headings copied from examples. Audience language is '+body.language+'. Every persona starts from its own analysis plan. INPUT:\n'+json.dumps(payload,ensure_ascii=False)+'\nINDEPENDENT PLAN (model output, not verified facts):\n'+plan['text'],'persona_draft',800,.3)
 oldfacts={f['id']:(f['value'],f['period']) for f in parent['facts']} if parent else {}
 changed=[f['id'] for f in facts if oldfacts.get(f['id'])!=(f['value'],f['period'])] if parent else []
 paragraphs=[]
 for i,t in enumerate([t.strip() for t in draft['text'].split('\n\n') if t.strip()]):
  refs=re.findall(r'\[F(\d+)\]',t);deps=[facts[int(r)-1]['id'] for r in refs if 0<int(r)<=len(facts)]
  paragraphs.append({'id':'p'+str(i+1),'text':t,'fact_ids':deps,'dependency_coverage':'explicit_citations' if deps else 'uncited_requires_review'})
 data={'persona_id':p['id'],'persona_snapshot':p,'condition':body.condition,'language':body.language,'evidence_snapshot':s,'facts':facts,'analysis_plan':plan['text'],'plan_run_id':plan['run_id'],'generation_run_id':draft['run_id'],'usage':{'plan':plan['usage'],'draft':draft['usage']},'text':draft['text'],'paragraphs':paragraphs,'parent_id':body.parent_id,'changed_fact_ids':changed,'preserved_edits':preserved,'editor_note':body.editor_note,'retrieval':ctx.get('style_examples_untrusted',[]),'evaluation':checks(draft['text'],facts,ctx.get('style_examples_untrusted',[])),'approval':'unreviewed','impact':{'previous_paragraph_ids':[x['id'] for x in parent['paragraphs'] if set(x['fact_ids'])&set(changed)] if parent else [],'uncited_previous_paragraphs':[x['id'] for x in parent['paragraphs'] if not x['fact_ids']] if parent else [],'regeneration_scope':'full draft recomputed; cited dependencies shown; manual edits not overwritten'}}
 r=save('draft',data);dest=ROOT/'generated_samples';dest.mkdir(exist_ok=True);(dest/f"{r['id']}.json").write_text(json.dumps(r,ensure_ascii=False,indent=2));return r
@app.post('/api/generate')
def generate_api(body:Generate):
 if not readj('acceptance-state.json')['general_generation_enabled']:raise HTTPException(423,'General generation paused. Only source-complete, versioned evidence-loop experiments are permitted.')
 from guarded import generate_guarded
 try:return generate_guarded(body)
 except RuntimeError as e:raise HTTPException(503,str(e)) from e
@app.get('/api/drafts')
def drafts(audit:bool=False):return [{**d,'content_status':'baseline_only_not_effective_content'} for d in records('draft')] if audit else []
@app.get('/api/drafts/{rid}')
def draft(rid:str,audit:bool=False):
 if not audit:raise HTTPException(409,'Baseline only. Explicit audit=true is required; this is not effective content.')
 return get_active(rid,audit)
class Edit(BaseModel):
 draft_id:str;text:str=Field(min_length=1,max_length=10000)
@app.post('/api/edits')
def edit(body:Edit):
 if output_gate(body.text):raise HTTPException(422,'Promotional copy is not allowed in posts')
 d=get_active(body.draft_id)
 if 'generation_run_id' not in d:raise HTTPException(422,'Not a draft')
 return save('edit',body.model_dump())
@app.get('/api/history')
def history():return {k:records(k) for k in ['evidence','draft','edit','human-review','diagram']}
def chart_svg(d):
 fs=[f for f in d['facts'] if f['id'].startswith('payroll')];maxv=max([abs(f['value']) for f in fs]+[1]);bars=[]
 for i,f in enumerate(fs):
  y=70+i*66;w=abs(f['value'])/maxv*390;color='#15735a' if f['value']>=0 else '#bb4838'
  bars.append(f'<text x="20" y="{y+19}" font-size="14">{html.escape(f["period"])}</text><rect x="140" y="{y}" width="{w}" height="28" fill="{color}"/><text x="{150+w}" y="{y+20}" font-size="14">{f["value"]:+,}</text>')
 return '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="340" viewBox="0 0 720 340"><rect width="720" height="340" fill="#fcfbf7"/><g font-family="Arial" fill="#243b35"><text x="20" y="32" font-size="18">US nonfarm payroll change · persons</text>'+''.join(bars)+f'<text x="20" y="300" font-size="12">BLS · vintage {html.escape(d["evidence_snapshot"]["published_at"][:10])} · signed values, bar length = magnitude</text><text x="20" y="322" font-size="11">Source IDs: {html.escape(", ".join(d["evidence_snapshot"]["source_ids"]))}</text></g></svg>'
@app.get('/api/chart/{rid}.svg')
def chart(rid:str,audit:bool=False):return Response(chart_svg(get_active(rid,audit)),media_type='image/svg+xml')
class Diagram(BaseModel):
 draft_id:str;nodes:list[dict];edges:list[dict]
def event_diagram(d):
 nodes=[{'id':'fact:'+f['id'],'label':f"{f['period']} · {f['id'].split('_')[0]} · {f['value']:,} {f['unit']}",'type':'observation','fact_ids':[f['id']],'source_id':f['source_id']} for f in d['facts']]
 edges=[]
 for p in d['paragraphs']:
  node_id='paragraph:'+p['id'];nodes.append({'id':node_id,'label':p.get('interpretation',p['text'])[:100],'type':'interpretation' if p['fact_ids'] else 'missing_evidence','fact_ids':p['fact_ids']})
  edges.extend({'from':'fact:'+fid,'to':node_id,'label':'输入依据；不证明因果'} for fid in p['fact_ids'])
 for i,event in enumerate(REGISTRY['scheduled'][:1]):
  node_id='next:'+str(i);nodes.append({'id':node_id,'label':event['title']+' · '+event['scheduled_at'],'type':'planned_unknown','fact_ids':[]})
  edges.extend({'from':'paragraph:'+p['id'],'to':node_id,'label':'后续核验'} for p in d['paragraphs'])
 return {'draft_id':d['id'],'nodes':nodes,'edges':edges,'generated_from':'actual draft fact dependencies and primary-source calendar','evidence_snapshot':d['evidence_snapshot']['id']}
@app.get('/api/diagram/{rid}')
def get_diagram(rid:str,audit:bool=False):
 d=get_active(rid,audit);versions=[x for x in records('diagram') if x['draft_id']==rid]
 return versions[0] if versions else event_diagram(d)
def diagram_svg(spec):
 import textwrap
 left=[n for n in spec['nodes'] if n.get('type')=='observation'];right=[n for n in spec['nodes'] if n.get('type')!='observation'];positions={n['id']:(20 if col==0 else 450,60+i*116) for col,ns in enumerate([left,right]) for i,n in enumerate(ns)}
 height=100+max(len(left),len(right),1)*116;parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="840" height="{height}" viewBox="0 0 840 {height}"><rect width="840" height="{height}" fill="#fcfbf7"/><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#92a69e"/></marker></defs><g font-family="Arial" fill="#243b35"><text x="20" y="28" font-size="16">Evidence → interpretation → next verification</text>']
 for e in spec['edges']:
  if e.get('from') not in positions or e.get('to') not in positions:continue
  x,y=positions[e['from']];xx,yy=positions[e['to']];parts.append(f'<path d="M{x+350},{y+45} L{xx},{yy+45}" fill="none" stroke="#92a69e" marker-end="url(#arrow)"/>')
 for n in spec['nodes']:
  x,y=positions[n['id']];parts.append(f'<rect x="{x}" y="{y}" width="350" height="92" rx="6" fill="#edf4ee" stroke="#bac9bf"/><text x="{x+12}" y="{y+18}" font-size="10">{html.escape(n.get("type","edited"))}</text>')
  lines=textwrap.wrap(n['label'],width=26)
  for i,line in enumerate(lines[:3]):
   if i==2 and len(lines)>3:line=line.rstrip('，。,. ')+'…'
   parts.append(f'<text x="{x+12}" y="{y+38+i*17}" font-size="12">{html.escape(line)}</text>')
 parts.append(f'<text x="20" y="{height-18}" font-size="11">Arrows show evidence dependencies and next checks, not established causation. Full text remains in draft.json.</text>')
 return ''.join(parts)+'</g></svg>'
@app.get('/api/diagram-image/{rid}.svg')
def diagram_image(rid:str,audit:bool=False):return Response(diagram_svg(get_diagram(rid,audit)),media_type='image/svg+xml')
@app.post('/api/diagram')
def diagram(body:Diagram):
 get_active(body.draft_id)
 if len(body.nodes)>20 or len(body.edges)>40:raise HTTPException(422,'Diagram too large')
 ids=[n.get('id') for n in body.nodes]
 if any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):raise HTTPException(422,'Node IDs must be unique strings')
 if any(not isinstance(n.get('label'),str) or len(n['label'])>200 for n in body.nodes):raise HTTPException(422,'Each node needs a concise label')
 if any(e.get('from') not in ids or e.get('to') not in ids for e in body.edges):raise HTTPException(422,'Edges must reference existing nodes')
 return save('diagram',body.model_dump())
@app.get('/api/export/{rid}')
def export(rid:str,audit:bool=False):
 if not audit:raise HTTPException(409,'Baseline export requires explicit audit=true; not effective content.')
 d=get_active(rid,audit);stream=io.BytesIO();diagrams=[x for x in records('diagram') if x['draft_id']==rid]
 if output_gate(d['text']):raise HTTPException(422,'Export blocked: promotional copy detected')
 with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('draft.md',d['text']+'\n\nReview: unreviewed working draft\n\n'+'\n'.join(s['url'] for s in REGISTRY['sources'] if s['id'] in d['evidence_snapshot']['source_ids']))
  for name,obj in [('draft.json',d),('evidence.json',REGISTRY),('chart-data.json',d['facts']),('diagram.json',diagrams),('editorial-reviews.json',editorial_reviews(rid)),('handoff.json',{'approval':d['approval'],'preserved_edits':d['preserved_edits'],'next_checks':REGISTRY['scheduled'],'editorial_reviews':editorial_reviews(rid)})]:z.writestr(name,json.dumps(obj,ensure_ascii=False,indent=2))
  z.writestr('chart.svg',chart_svg(d))
  spec=diagrams[0] if diagrams else event_diagram(d)
  z.writestr('event-structure.svg',diagram_svg(spec));z.writestr('event-structure.json',json.dumps(spec,ensure_ascii=False,indent=2))
 return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{rid}.zip"'})
def completed_experiment_cases():
 # Only source-complete evidence-loop cases are reviewable. Legacy kinds and the old
 # cross_language_tests/ml_experiments blind sets are never assembled here.
 d=ROOT/'evidence_loop/experiments/cases'
 return [c for c in (json.loads(p.read_text()) for p in sorted(d.glob('*.json'))) if c.get('status') in ['completed','completed_with_qa_failures'] and c.get('text')] if d.exists() else []
@app.get('/api/blind')
def blind():
 p=ROOT/'evidence_loop/experiments/blind-cases.json'
 if p.exists():return json.loads(p.read_text())
 cases=completed_experiment_cases()
 if not cases:return {'cases':[],'status':'No completed evidence-loop case yet; legacy_invalid_output is never offered for review.','eligible_source':'evidence_loop/experiments/cases'}
 import random
 items=[{'id':'C-'+c['id'].split('-',1)[1],'language':c['language'],'title':c.get('title'),'text':c['text'],'case_ref':c['id']} for c in cases]
 random.Random(73).shuffle(items)
 return {'cases':items,'status':'ready for real human review','blinding':'persona, condition, donors and role weights withheld from this payload; the full case JSON stays on disk for the local editor','legacy_excluded':True}
class Review(BaseModel):
 case_id:str;reviewer:str=Field(min_length=1);choice:str;quality:int=Field(ge=1,le=5);faithfulness:int=Field(ge=1,le=5);edited_text:str;comment:str=''
@app.post('/api/blind-review')
def review(body:Review):
 cases={c['id']:c for c in blind().get('cases',[])}
 if body.case_id not in cases:raise HTTPException(422,'Unknown blind case')
 return save('human-review',{**body.model_dump(),'case_ref':cases[body.case_id].get('case_ref'),'provenance':'user submitted via review form; identity self-reported','verification':'not externally verified'})
@app.get('/api/deliverable/{rid}')
def deliverable(rid:str):
 # Single choke point for anything leaving the system as content.
 kind,payload=get_row(rid)
 try:assert_deliverable({**payload,'record_kind':kind},'record '+rid)
 except PermissionError as e:raise HTTPException(409,str(e)) from e
 return qa_label({**payload,'record_kind':kind})
@app.get('/api/qa/regression')
def qa_regression():
 p=ROOT/'qa/runs/latest.json'
 return json.loads(p.read_text()) if p.exists() else {'status':'no run yet'}
@app.get('/api/demo-workbench')
def demo_workbench():
 # Read-only architecture demo. Assembles a view model from existing artifacts; writes nothing.
 import demo;return demo.build()
@app.get('/api/intel')
def intel_api():
 import intel;return intel.build()
@app.get('/api/assets')
def assets_api():
 # Real artifacts from steps 2-7. Read-only; statuses are copied, never recomputed for display.
 import assets;return assets.build()
@app.get('/api/visual/{vid}.svg')
def visual_svg(vid:str):
 p=ROOT/'content/visuals'/(vid+'.svg')
 if not re.fullmatch(r'vis-[0-9a-f]{12}',vid) or not p.exists():raise HTTPException(404)
 return Response(p.read_text(),media_type='image/svg+xml')
@app.get('/api/evergreen-card/{pid}.svg')
def evergreen_card(pid:str):
 p=ROOT/'evergreen/deliverables/cards'/(pid+'.svg')
 if not re.fullmatch(r'pr-[0-9a-f]{12}',pid) or not p.exists():raise HTTPException(404)
 return Response(p.read_text(),media_type='image/svg+xml')
@app.get('/system-status')
def system_status():return FileResponse(ROOT/'frontend/demo.html')
@app.get('/demo')
def demo_page():
 # Old bookmark from an earlier round. The audit page is no longer an entry point.
 from fastapi.responses import RedirectResponse;return RedirectResponse('/',status_code=307)
@app.get('/legacy')
def legacy():return FileResponse(ROOT/'frontend/index.html')
@app.get('/')
def index():return FileResponse(ROOT/'frontend/workbench.html')
app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='assets')
