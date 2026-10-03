from pathlib import Path
import json, datetime, os, shutil
ROOT=Path('/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation')
def put(name,text):
 p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():raise RuntimeError('Refusing overwrite: '+name)
 p.write_text(text.strip()+'\n')
put('scripts/handover_checks.py',r'''
"""Read-only handover inspection. Never imports product code, reads .env, or calls APIs."""
from pathlib import Path
import ast, collections, csv, datetime, hashlib, importlib.metadata, json, os, platform, re, sqlite3, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text())
def rows(name):return [json.loads(s) for s in (ROOT/name).read_text().split('\n') if s.strip()]
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def count(items):return dict(sorted(collections.Counter(items).items()))
def git(args):
 p=subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,text=True)
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
 'drafts':{'database_kinds':count(x['kind'] for x in records),'legacy_invalid':sum(x['kind']=='legacy_invalid_output' for x in records),'legacy_json_files':len(list((ROOT/'generated_samples').glob('*.json'))),'valid':0,'human_reviews':sum(x['kind']=='human-review' for x in records),'new_case_statuses':count(x['status'] for x in cases),'new_completed_cases':sum(x['status'] in ['completed','completed_with_qa_failures'] for x in cases),'cases':[{'id':x['id'],'condition':x['condition'],'persona_id':x['persona_id'],'recorded_status':x['status'],'effective_status':'interrupted_by_handover' if x['status']=='running' else x['status'],'plan_run_id':x.get('plan_run_id'),'generation_run_id':x.get('generation_run_id'),'error':x.get('error')} for x in cases]},
 'profiles':read('evidence_loop/profiles/index.json'),'videos':videos,'source':{k:v for k,v in read('evidence_loop/sources/packets/75155f58f5a995e3.json').items() if k in ['id','version','published_at','observed_at','artifact_sha256','artifact_kind','primary_url','coverage']},'api':api_evidence(),'routes':route_inventory()}
def shutil_which(name):
 import shutil
 return shutil.which(name)
''')
put('handover/test_invariants.py',r'''
"""Real artifact integrity tests; no product imports, fixtures, writes or network."""
from pathlib import Path
import sys,json,unittest,datetime,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from handover_checks import read,rows,sha,db_records
class ArtifactIntegrity(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.raw={x['post_id']:x for x in rows('data/raw_posts.jsonl')};cls.clean=rows('data/clean_posts.jsonl');cls.ids={x['post_id'] for x in cls.clean}
 def test_clean_resolves_to_raw_payload(self):
  for x in self.clean:
   r=self.raw[x['post_id']];self.assertEqual(x['raw_source_ref']['payload_hash'],r['raw_payload_hash'])
   canonical=json.dumps(r['source_record'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
   self.assertEqual(hashlib.sha256(canonical).hexdigest(),r['raw_payload_hash'])
 def test_unique_ids_and_manifest_counts(self):
  raw=rows('data/raw_posts.jsonl');m=read('data/corpus_manifest.json')
  self.assertEqual(len(raw),len(self.raw));self.assertEqual(len(self.clean),len(self.ids));self.assertEqual(m['raw_posts'],len(raw));self.assertEqual(m['clean_posts'],len(self.clean))
 def test_legacy_registry_matches_database(self):
  ids={d['id'] for d in read('evidence_loop/quarantine/registry.json')['drafts']}
  db={d['id'] for d in db_records() if d['kind']=='legacy_invalid_output'}
  self.assertEqual(ids,db);self.assertEqual(len(ids),45)
  self.assertFalse(any(d['kind']=='draft' for d in db_records()))
 def test_source_hash_and_exact_fact_spans(self):
  p=read('evidence_loop/sources/packets/75155f58f5a995e3.json');f=ROOT/'evidence_loop'/p['artifact_path'];t=f.read_text()
  self.assertEqual(sha(f),p['artifact_sha256']);block_ids={b['id'] for b in p['blocks']}
  for fact in p['facts']:
   s=fact['source_span'];self.assertEqual(t[s['start']:s['end']],s['quote']);self.assertTrue(set(fact['source_block_ids'])<=block_ids)
 def test_profile_measurements_reference_real_posts(self):
  def walk(value):
   if isinstance(value,dict):
    if 'denominator_post_ids' in value:
     self.assertTrue(set(value['denominator_post_ids'])<=self.ids);self.assertTrue(set(value['support_post_ids'])<=set(value['denominator_post_ids']));self.assertEqual(value['sample_n'],len(value['denominator_post_ids']));self.assertTrue(value['method'])
    for v in value.values():walk(v)
   elif isinstance(value,list):
    for v in value:walk(v)
  for p in (ROOT/'evidence_loop/profiles').glob('*.json'):walk(json.loads(p.read_text()))
 def test_retrieval_pre_event_and_versioned(self):
  retrieval=read('evidence_loop/experiments/retrieval.json');routing=read('evidence_loop/experiments/routing.json');release=datetime.datetime.fromisoformat(read('evidence_loop/sources/packets/75155f58f5a995e3.json')['published_at'])
  for pid,items in retrieval['results'].items():
   for x in items:
    self.assertIn(x['post_id'],self.ids);self.assertLess(datetime.datetime.fromisoformat(x['created_at']),release)
   for d in routing[pid]['donors']:self.assertTrue((ROOT/'evidence_loop/profiles/versions'/f"{d['donor']}-{d['profile_version']}.json").is_file())
 def test_caption_hashes_time_links_and_no_shortpost_style(self):
  for s in rows('evidence_loop/transcripts/segments.jsonl'):
   self.assertEqual(sha(ROOT/'evidence_loop/transcripts'/s['raw_caption_file']),s['raw_caption_sha256']);self.assertLess(s['start'],s['end']);self.assertGreaterEqual(s['start'],0);self.assertIn('t=',s['timestamp_url']);self.assertFalse(s['eligible_for_short_post_style']);self.assertTrue(s['raw_cue_ids'])
 def test_real_new_plans_have_saved_requests_and_responses(self):
  for p in (ROOT/'evidence_loop/experiments/cases').glob('*.json'):
   d=json.loads(p.read_text());call=read('runs/model_calls/'+d['plan_run_id']+'.json');self.assertEqual(call['task'],'evidence_loop_independent_plan');self.assertIn('response',call);self.assertIn('messages',call['request'])
if __name__=='__main__':unittest.main(verbosity=2)
''')
put('scripts/verify_handover.sh',r'''
#!/bin/sh
# Only writes handover/verification.json. No download, paid API, data mutation or .env reads.
set -eu
HANDOVER_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
if [ ! -x "$HANDOVER_ROOT/.venv/bin/python" ]; then
  echo 'FAIL project Python missing; verifier cannot run' >&2
  exit 3
fi
export PYTHONDONTWRITEBYTECODE=1
exec "$HANDOVER_ROOT/.venv/bin/python" -B "$HANDOVER_ROOT/scripts/verify_handover.py" "$@"
''')
put('scripts/verify_handover.py',r'''
"""Exit 0=all checked gates pass, 1=integrity failure, 2=product incomplete, 3=verifier error."""
from handover_checks import *
import traceback
REQUIRED=['CLAUDE.md','docs/CURRENT_STATE_AUDIT.md','docs/REPOSITORY_MAP.md','docs/DATA_LINEAGE.md','docs/VIDEO_TRANSCRIPT_PIPELINE.md','docs/CONTENT_PIPELINES.md','docs/KNOWN_FAILURES.md','docs/ACCEPTANCE_TESTS.md','docs/RUNBOOK.md','scripts/verify_handover.sh','scripts/verify_handover.py','scripts/handover_checks.py','handover/test_invariants.py','handover/manifest.json','handover/migration.json','handover/freeze.json']
def main():
 print('Finance Distillation handover verification (offline, read-only inputs)',flush=True)
 state=collect();checks=[]
 def check(name,result,detail,scope='integrity'):checks.append({'name':name,'result':result,'detail':detail,'scope':scope})
 missing=[p for p in REQUIRED if not (ROOT/p).is_file()];check('required_files','FAIL' if missing else 'PASS',missing)
 check('git_metadata','PASS' if state['git']['is_repository'] else 'UNKNOWN','Not a Git repository; branch, commit and dirty_files are null' if not state['git']['is_repository'] else state['git'])
 missing_deps=[x for x in ['fastapi','uvicorn','httpx','mlx-lm','sentence-transformers','scikit-learn','mlx-whisper','sherpa-onnx','bilibili-api-python'] if x not in state['runtime_versions']['packages']];check('dependencies','FAIL' if missing_deps else 'PASS',missing_deps)
 syntax=[]
 for folder in ['backend','scripts','evidence_loop']:
  for p in (ROOT/folder).glob('*.py'):
   try:ast.parse(p.read_text())
   except SyntaxError as e:syntax.append({'file':str(p.relative_to(ROOT)),'line':e.lineno})
 check('python_syntax','FAIL' if syntax else 'PASS',syntax)
 test=subprocess.run([sys.executable,'-B',str(ROOT/'handover/test_invariants.py')],capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
 check('artifact_unit_tests','PASS' if test.returncode==0 else 'FAIL',{'exit_code':test.returncode,'output':test.stdout+test.stderr})
 print('Artifact checks complete; verifying all migrated files against their pre-move hashes.',flush=True)
 migration=read('handover/migration.json');mismatch=[]
 for e in migration['entries']:
  p=ROOT/e['destination_relative']
  if e['kind']=='symlink':ok=p.is_symlink() and os.readlink(p)==e['link_target']
  else:ok=p.is_file() and p.stat().st_size==e['bytes'] and sha(p)==e['sha256']
  if not ok:mismatch.append(e['destination_relative'])
 check('migration_all_file_hashes','FAIL' if mismatch else 'PASS',{'files':migration['regular_files'],'symlinks':migration['symlinks'],'bytes':migration['bytes'],'mismatches':mismatch})
 check('frontend_backend_entries','PASS' if (ROOT/'frontend/index.html').is_file() and (ROOT/'frontend/app.js').is_file() and state['routes'] else 'FAIL','Static entry/routes inspection; service is intentionally stopped, not a browser acceptance test')
 check('twelve_qualified_donors','PASS' if len(state['dataset']['authors'])>=12 and all(a['clean_original_rule_financial']>=150 and a['complete_180d'] for a in state['dataset']['authors']) else 'FAIL',state['dataset']['authors'],'acceptance')
 check('human_annotations_and_review','PASS' if state['dataset']['human_label_rows']>=300 and state['drafts']['human_reviews']>0 else 'FAIL',{'human_labels':state['dataset']['human_label_rows'],'human_reviews':state['drafts']['human_reviews']},'acceptance')
 check('source_complete_semantic_review','UNKNOWN','51 typed narrative facts and full text retained; table cells not normalized and semantic completeness not human reviewed','acceptance')
 check('five_group_ablation','PASS' if state['drafts']['new_completed_cases']>=15 else 'FAIL',state['drafts']['new_case_statuses'],'acceptance')
 vs=state['videos']['videos'];ready=count(v['platform'] for v in vs if v['status']=='transcript_ready')
 check('three_youtube_three_bilibili','PASS' if ready.get('youtube',0)>=3 and ready.get('bilibili',0)>=3 else 'FAIL',ready,'acceptance')
 check('speakers_financial_correction_crossplatform_dedup','FAIL','Speaker diarization and ASR never run; all ready videos are YouTube, so no cross-platform pair tested','acceptance')
 js=(ROOT/'frontend/app.js').read_text();check('intelligence_desk_and_explainable_personas','FAIL' if "'corpus'" in js or '"corpus"' in js else 'UNKNOWN','Current UI is Corpus / JSON persona / Studio / Handoff; no new evidence-loop views','acceptance')
 check('claim_graph_evergreen_update_pipeline','FAIL','No executed hot Claim Graph, Atomic Principle/Conflict Graph, scheduling or evidence-triggered update run','acceptance')
 check('legacy_isolation_all_routes','FAIL','SQL kind changed and generation gate closed; get(rid), audit routes and chart/diagram paths can still expose legacy IDs','acceptance')
 check('live_ui_acceptance','UNKNOWN','No browser run in handover; existing Chrome restriction; backend stopped for migration','acceptance')
 markers=[];locations=[]
 for folder in ['frontend','backend','scripts','evidence_loop']:
  for p in (ROOT/folder).rglob('*'):
   if not p.is_file() or p.suffix not in ['.py','.js','.html'] or p.name in ['verify_handover.py','handover_checks.py']:continue
   for i,line in enumerate(p.read_text().split('\n'),1):
    found=sorted(set(re.findall(r'(?i)\b(?:hardcoded|hardcode|mock|fixture|sample|synthetic|demo)\b',line)))
    if found:markers.append({'file':str(p.relative_to(ROOT)),'line':i,'markers':found})
    if re.search(r'client\.post|httpx\.|requests\.|urlopen|yt-dlp|generate_content|chat/completions|SYSTEM_PROMPT|planprompt',line):locations.append({'file':str(p.relative_to(ROOT)),'line':i})
 check('marker_and_api_location_inventory','PASS',{'marker_hits':len(markers),'api_prompt_locations':len(locations),'note':'Marker presence is not proof a record is synthetic; line contents omitted to avoid exposing secrets.'})
 result={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'counts':count(c['result'] for c in checks),'state':state,'marker_locations':markers,'api_prompt_locations':locations,'safe_test_command':'.venv/bin/python -B handover/test_invariants.py','safe_tests_exit_code':test.returncode,'write_scope':['handover/verification.json'],'external_network_requests':0}
 integrity_fail=any(c['result']=='FAIL' and c['scope']=='integrity' for c in checks)
 incomplete=any(c['result'] in ['FAIL','UNKNOWN'] and c['scope']=='acceptance' for c in checks)
 code=1 if integrity_fail else 2 if incomplete else 0;result['exit_code']=code
 (ROOT/'handover/verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print('ROOT '+str(ROOT));print('GIT '+('repository' if state['git']['is_repository'] else 'not a Git repository; branch=null commit=null dirty_files=null'))
 d=state['dataset'];g=state['drafts'];print(f"DATA raw={d['raw']} clean={d['clean']} authors={d['author_count']} human_labels={d['human_label_rows']}")
 print('CLEAN_LANGUAGES '+json.dumps(d['clean_languages'],sort_keys=True));print(f"DRAFTS valid={g['valid']} legacy_invalid={g['legacy_invalid']} human_reviews={g['human_reviews']}")
 print('VIDEO_READY '+json.dumps(ready,sort_keys=True)+' segments='+str(state['videos']['segments']))
 print('MODEL_CALL_RECORDS '+json.dumps(state['api']['local_mlx']['statuses'],sort_keys=True))
 print('ENV_PRESENT '+json.dumps(state['environment_present'],sort_keys=True))
 for c in checks:print(c['result']+' '+c['name'])
 print('COUNTS '+json.dumps(result['counts'],sort_keys=True));print('SAFE_TEST_EXIT_CODE '+str(test.returncode));print('REPORT handover/verification.json');print('EXIT_CODE '+str(code))
 return code
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:
  failure={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit_code':3,'result':'FAIL','error_type':type(e).__name__,'message':'Verifier failed; no product files changed. Inspect verifier implementation and local traceback.'}
  (ROOT/'handover/verification.json').write_text(json.dumps(failure,indent=2)+'\n');print('FAIL verifier_error '+type(e).__name__);print('EXIT_CODE 3');traceback.print_exc();sys.exit(3)
''')
os.chmod(ROOT/'scripts/verify_handover.sh',0o755)
put('handover/freeze.json',json.dumps({'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reason':'User switched to complete project handover, then authorized full migration. No new features or content generation.','paused':True,'stopped_processes':[{'pid':65334,'role':'evidence_loop/run_experiments.py','exact_stop_time':None},{'pid':61610,'role':'local MLX modern generator :8683','exact_stop_time':None},{'pid':64057,'role':'project backend :8680 stopped for migration','evidence':'handover/migration.json'}],'original_run_records_preserved':True,'effective_interrupted_cases':['case-21b8d4f70185'],'possible_related_draft_call':'local-0538caa511c642cf','case_to_draft_direct_link_missing':True,'asr_executed':False,'diarization_executed':False,'backend_running_after_migration':False},ensure_ascii=False,indent=2))
print('Created read-only audit helpers, unit tests, verifier and freeze record.')
