"""Read-only handover inspection. Never imports product code, reads .env, or calls APIs."""
from pathlib import Path
import ast, collections, csv, datetime, hashlib, importlib.metadata, json, os, platform, re, sqlite3, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]

def file_artifacts():
 """Artifacts produced by the content pipeline, which writes files rather than DB rows.

 The database predates it, so a report built only from records showed valid=0 while three gated
 drafts and their derived products existed on disk.
 """
 import json as _json
 def rows(rel):
  d=ROOT/rel
  out=[]
  if d.is_dir():
   for f in sorted(d.glob('*.json')):
    try:out.append(_json.loads(f.read_text()))
    except Exception:pass
  return out
 def ready(xs):return sum(1 for x in xs if x.get('content_status')=='ready_for_pipeline')
 drafts=rows('content/drafts');packs=rows('content/packages')
 react=rows('content/reactivation');cross=rows('content/crosslang')
 ev=ROOT/'evergreen/deliverables/index.json'
 ev=_json.loads(ev.read_text()) if ev.is_file() else {}
 return {'source':'files under content/ and evergreen/deliverables/, not the database',
         'drafts_ready':ready(drafts),'drafts_total':len(drafts),
         'packages_ready':ready(packs),'packages_total':len(packs),
         'visuals':len(list((ROOT/'content/visuals').glob('*.svg'))) if (ROOT/'content/visuals').is_dir() else 0,
         'reactivation_ready':ready(react),'crosslang_ready':ready(cross),
         'evergreen_cards':len(ev.get('cards') or []),
         'evergreen_explainers':len(ev.get('explainers') or []),
         'evergreen_review_status':ev.get('review_status'),
         'human_reviews':0,
         'note':'no item here is human reviewed'}

def read(name):return json.loads((ROOT/name).read_text())
def rows(name):return [json.loads(s) for s in (ROOT/name).read_text().split('\n') if s.strip()]
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def count(items):return dict(sorted(collections.Counter(items).items()))
def git(args):
 p=subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,text=True,env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'})
 return p.stdout.strip() if p.returncode==0 else None
def db_records():
 with sqlite3.connect('file:'+str(ROOT/'data/lab.sqlite')+'?mode=ro',uri=True) as c:
  c.execute('PRAGMA query_only=ON')
  return [{'id':i,'kind':k,'created_at':t,'payload':json.loads(p)} for i,k,t,p in c.execute('SELECT id,kind,created_at,payload FROM records')]
def route_inventory():
 routes=[]
 for n in ast.walk(ast.parse((ROOT/'backend/app.py').read_text())):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
   for d in n.decorator_list:
    if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in ['get','post','put','delete','patch'] and d.args and isinstance(d.args[0],ast.Constant):
     routes.append({'method':d.func.attr.upper(),'path':d.args[0].value,'function':n.name,'file':'backend/app.py','line':n.lineno})
 return sorted(routes,key=lambda x:x['line'])
def model_calls():return [json.loads(p.read_text()) for p in sorted((ROOT/'runs/model_calls').glob('*.json'))]
def api_evidence():
 calls=model_calls();ledger=rows('runs/api_run_ledger.jsonl')
 probe=read('historical_workspace/outputs/architecture-review/evidence/rapidapi_probe.json')
 reqs=probe['requests'];acq=read('evidence_loop/sources/acquisition.json')
 bili=[read(str(p.relative_to(ROOT))) for p in (ROOT/'evidence_loop/transcripts/acquisitions').glob('BV*.json')]
 videos=read('evidence_loop/transcripts/index.json')['videos']
 discovery=read('evidence_loop/transcripts/discovery/runs.json')['runs']
 assets=read('evidence_loop/visual/assets.json')['assets']
 audio=[read(str(p.relative_to(ROOT))) for p in (ROOT/'evidence_loop/transcripts/audio-runs').glob('*.json')]
 return {
  'counting_rule':'Recorded operations and on-wire HTTP requests are different units. Do not sum local model JSON and duplicate ledger entries. No inference from quota deltas or imported post counts.',
  'x_inherited_import':{'input_files':5,'import_runs':sum(x.get('operation')=='user_import' for x in ledger),'new_requests':0,'historical_provider_requests':None,'historical_pages':None,'evidence':'data/corpus_manifest.json; data/raw_posts.jsonl; runs/api_run_ledger.jsonl','payload_scope':'inherited_normalized_post_not_original_network_response'},
  'rapidapi_phase0':{'host':probe['provider_host'],'recorded_http_requests':len(reqs),'statuses':count(str(x['status']) for x in reqs),'accounts':[x['username'] for x in probe['accounts']],'timeline_pages':sum(x['endpoint']=='/user-tweets' for x in reqs),'requests':[{'endpoint':x['endpoint'],'params':x['params'],'status':x['status']} for x in reqs],'response_scope':'sanitized metadata/previews, not complete wire responses','cost':None,'evidence':'historical_workspace/outputs/architecture-review/evidence/rapidapi_probe.json'},
  'xquik':{'recorded_requests':0,'pages':0,'enabled':False,'cost_estimate':None,'evidence':'backend/app.py status(); data/corpus_manifest.json; skill-audit/audit.md'},
  'local_mlx':{'recorded_attempts':len(calls),'statuses':count(x.get('status','unknown') for x in calls),'responses_saved':sum('response' in x for x in calls),'tasks':count(x['task'] for x in calls),'target':'127.0.0.1:8681/8682/8683 /v1/chat/completions','paid_api_cost':0,'started_record_is_not_proof_of_dispatch':True,'evidence':'runs/model_calls/*.json; runs/api_run_ledger.jsonl'},
  'bls_previous':{'recorded_operations':3,'status':'failed','http_status_codes':None,'evidence':'runs/api_run_ledger.jsonl primary_public_source_fetch'},
  'bls_full':{'recorded_http_requests':len(acq),'targets':{k:{'url':v['url'],'status':v['status'],'sha256':v.get('sha256'),'at':v.get('started_at')} for k,v in acq.items()},'evidence':'evidence_loop/sources/acquisition.json'},
  'nvidia_pdf':{'recorded_http_requests':2,'statuses':[302,200],'evidence':'runs/official-pdf-capture.json; data/evidence/nvidia-q2-fy2027-10q.pdf'},
  'yahoo':{'recorded_operations':[x['operation'] for x in ledger if x.get('provider')=='yfinance / Yahoo Finance'],'target':'NVDA','operation_status':'3 completed, 4 rows per operation','wire_requests':None,'evidence':'data/finance_supplement/nvda.json; runs/api_run_ledger.jsonl'},
  'x_photo_assets':{'target':'pbs.twimg.com','recorded_http_requests':len(assets),'statuses':count(str(x.get('http_status')) for x in assets),'evidence':'evidence_loop/visual/assets.json'},
  'video_discovery':{'youtube_cli_operations':sum(x['id'].startswith('youtube') for x in discovery),'bilibili_recorded_search_http_requests':sum(x['id'].startswith('bili') for x in discovery),'bilibili_search_pages_each':1,'total_wire_requests':None,'evidence':'evidence_loop/transcripts/discovery/runs.json'},
  'video_acquisition':{'youtube_metadata_files':sum(v['platform']=='youtube' for v in videos),'youtube_transcripts_ready':sum(v['platform']=='youtube' and v['status']=='transcript_ready' for v in videos),'bilibili_metadata_requests_saved':sum(len(x.get('requests',[])) for x in bili),'bilibili_http_statuses':count(str(q['status']) for x in bili for q in x.get('requests',[])),'bilibili_transcripts_ready':sum(v['platform']=='bilibili' and v['status']=='transcript_ready' for v in videos),'audio_statuses':count(x['status'] for x in audio),'complete_wire_request_count':None,'evidence':'evidence_loop/transcripts/acquisitions/; audio-runs/; *.acquisition.log; *.audio.log','limitations':['yt-dlp internal HTTP requests are not individually journaled','Retry scripts overwrote some acquisition records/logs before handover; complete attempt count is unrecoverable from saved artifacts','Three Bilibili audio downloads are operations, not proof of three underlying HTTP requests']},
  'sec_edgar_mcp':{'enabled':False,'recorded_calls':0,'evidence':'runs/sec-mcp-preflight.json; skill-audit/sec-edgar-mcp.disabled.json'},
  'other_public_research_and_weight_downloads':{'wire_requests':None,'cost':None,'evidence':'skill-audit/skills.lock.json; evidence_loop/video-audit.json; *model-lock.json; historical_workspace/work/repo-audit/','limitation':'Hashes prove retained files, not a complete request journal'}
 }
def collect():
 raw=rows('data/raw_posts.jsonl');clean=rows('data/clean_posts.jsonl');records=db_records();manifest=read('data/corpus_manifest.json')
 authors=[]
 for a in sorted({x['source_account_id'] for x in raw}):
  rr=[x for x in raw if x['source_account_id']==a];cc=[x for x in clean if x['source_account_id']==a]
  authors.append({'donor':a,'raw':len(rr),'clean':len(cc),'clean_original_rule_financial':sum(x['post_type']=='original' and x['classification']['financial_relevant'] for x in cc),'languages':count(x['language'] for x in cc),'post_types':count(x['post_type'] for x in cc),'oldest':min(x['created_at'] for x in rr),'newest':max(x['created_at'] for x in rr),'complete_180d':next(x['complete_180d'] for x in manifest['donors'] if x['handle']==a)})
 videos=read('evidence_loop/transcripts/index.json');segments=rows('evidence_loop/transcripts/segments.jsonl')
 cases=[read(str(p.relative_to(ROOT))) for p in sorted((ROOT/'evidence_loop/experiments/cases').glob('*.json'))]
 review=list(csv.DictReader((ROOT/'data/post_classification_review.csv').open(encoding='utf-8-sig')))
 packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}
 env_names=['XQUIK_API_KEY','RAPIDAPI_KEY','APIFY_API_TOKEN','SEC_EDGAR_USER_AGENT','HF_TOKEN','OPENAI_API_KEY','GROQ_API_KEY']
 return {'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repository_root':str(ROOT),'git':{'is_repository':git(['rev-parse','--is-inside-work-tree'])=='true','branch':git(['branch','--show-current']),'commit_sha':git(['rev-parse','HEAD']),'dirty_files':git(['status','--porcelain=v1'])},'runtime_versions':{'python':platform.python_version(),'python_executable':sys.executable,'platform':platform.platform(),'packages':dict(sorted(packages.items())),'external_executables':{x:shutil_which(x) for x in ['ffmpeg','yt-dlp','node','bilibili']}},'environment_present':{k:bool(os.environ.get(k)) for k in env_names},'environment_scope':'current process only; no .env, cookies or user credentials opened',
 'dataset':{'raw':len(raw),'clean':len(clean),'raw_sha256':sha(ROOT/'data/raw_posts.jsonl'),'clean_sha256':sha(ROOT/'data/clean_posts.jsonl'),'authors':authors,'author_count':len(authors),'raw_languages':count(x['language'] for x in raw),'clean_languages':count(x['language'] for x in clean),'platform_counts':{'x_raw':len(raw),'x_clean':len(clean),'youtube_segments':sum(s['platform']=='youtube' for s in segments),'bilibili_segments':sum(s['platform']=='bilibili' for s in segments)},'real_vs_fixture':{'raw_imported_real_provider_records':len(raw),'clean_derived_from_imports':len(clean),'explicit_fixture_rows_in_these_files':sum(bool(x.get('is_fixture') or x.get('synthetic')) for x in raw),'independently_revalidated_all_raw_posts':False,'all_archive_fixture_count':None},'missing_raw_provenance':{k:sum(x.get(k) in [None,''] for x in raw) for k in ['post_id','stable_author_id','url','created_at','collected_at','provider_run_id','raw_payload_hash','thread_id']},'human_label_rows':sum(bool(x.get('human_label','').strip()) for x in review),'review_rows':len(review)},
 'drafts':{'database_kinds':count(x['kind'] for x in records),'legacy_invalid':sum(x['kind']=='legacy_invalid_output' for x in records),'legacy_json_files':len(list((ROOT/'generated_samples').glob('*.json'))),'valid':sum(x['kind']=='draft' and x['payload'].get('approval')=='approved' for x in records),'human_reviews':sum(x['kind']=='human-review' for x in records),'new_case_statuses':count(x['status'] for x in cases),'new_completed_cases':sum(x['status'] in ['completed','completed_with_qa_failures'] for x in cases),'file_artifacts':file_artifacts(),'cases':[{'id':x['id'],'condition':x['condition'],'persona_id':x['persona_id'],'recorded_status':x['status'],'effective_status':'interrupted_by_handover' if x['status']=='running' else x['status'],'plan_run_id':x.get('plan_run_id'),'generation_run_id':x.get('generation_run_id'),'error':x.get('error')} for x in cases]},
 'profiles':read('evidence_loop/profiles/index.json'),'videos':videos,'source':{k:v for k,v in read('evidence_loop/sources/packets/75155f58f5a995e3.json').items() if k in ['id','version','published_at','observed_at','artifact_sha256','artifact_kind','primary_url','coverage']},'api':api_evidence(),'routes':route_inventory()}
def shutil_which(name):
 import shutil
 return shutil.which(name)
