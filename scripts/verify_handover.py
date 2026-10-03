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
 missing_deps=[x for x in ['fastapi','uvicorn','httpx','mlx-lm','sentence-transformers','scikit-learn','mlx-whisper','sherpa-onnx','bilibili-api-python'] if x not in {re.sub(r'[-_.]+','-',n.lower()) for n in state['runtime_versions']['packages']}];check('dependencies','FAIL' if missing_deps else 'PASS',missing_deps)
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
 # A flat FAIL put "someone overwrote the raw posts" and "we edited a source file we are allowed
 # to edit" in the same bucket, so the check could never go green and stopped carrying
 # information. Classify instead: only the immutable set may not move.
 IMMUTABLE=('data/raw_posts.jsonl','data/clean_posts.jsonl','data/corpus_manifest.json',
            'evidence_loop/sources/','evidence_loop/experiments/cases/','evidence_loop/profiles/v1',
            'handover/requirements/','historical_workspace/','evergreen/raw/','data/evidence/')
 CODE_EXT=('.py','.js','.html','.css','.sh','.md','.json')
 CODE_DIR=('backend/','frontend/','scripts/','qa/','tests/','content/','evidence_loop/',
           'evergreen/','ml/','docs/')
 LEDGER=('runs/','.jsonl')
 def bucket(rel):
  if '__pycache__' in rel or rel.endswith('.pyc') or rel.startswith('.venv/') or '.DS_Store' in rel:
   return 'ephemeral'
  if any(rel.startswith(x) for x in IMMUTABLE):return 'immutable'
  if rel.startswith(LEDGER[0]) and rel.endswith(LEDGER[1]):return 'append_only_ledger'
  if any(rel.startswith(d) for d in CODE_DIR) and rel.endswith(CODE_EXT):return 'approved_code'
  return 'derived_artifact'
 by={}
 for rel in mismatch:by.setdefault(bucket(rel),[]).append(rel)
 # An append-only ledger must still contain everything it contained before.
 ledger_broken=[]
 for rel in by.get('append_only_ledger',[]):
  e=next(x for x in migration['entries'] if x['destination_relative']==rel)
  p=ROOT/rel
  if not p.is_file() or p.stat().st_size<e['bytes']:ledger_broken.append(rel)
 violations=by.get('immutable',[])+ledger_broken
 check('migration_immutable_artifacts','FAIL' if violations else 'PASS',
       {'files':migration['regular_files'],'symlinks':migration['symlinks'],
        'bytes':migration['bytes'],'total_mismatches':len(mismatch),
        'immutable_changed':by.get('immutable',[]),
        'append_only_ledgers_truncated':ledger_broken,
        'approved_code_changed':by.get('approved_code',[]),
        'append_only_ledgers_grown':[r for r in by.get('append_only_ledger',[]) if r not in ledger_broken],
        'derived_artifacts_changed':by.get('derived_artifact',[]),
        'ephemeral_ignored':len(by.get('ephemeral',[])),
        'rule':'only the immutable set and truncated ledgers fail; source edits are expected'})
 check('frontend_backend_entries','PASS' if (ROOT/'frontend/index.html').is_file() and (ROOT/'frontend/app.js').is_file() and state['routes'] else 'FAIL','Static entry/routes inspection; service is intentionally stopped, not a browser acceptance test')
 check('twelve_qualified_donors','PASS' if len(state['dataset']['authors'])>=12 and all(a['clean_original_rule_financial']>=150 and a['complete_180d'] for a in state['dataset']['authors']) else 'FAIL',state['dataset']['authors'],'acceptance')
 check('human_annotations_and_review','PASS' if state['dataset']['human_label_rows']>=300 and state['drafts']['human_reviews']>0 else 'FAIL',{'human_labels':state['dataset']['human_label_rows'],'human_reviews':state['drafts']['human_reviews']},'acceptance')
 check('source_complete_semantic_review','UNKNOWN','51 typed narrative facts and full text retained; table cells not normalized and semantic completeness not human reviewed','acceptance')
 check('five_group_ablation','PASS' if state['drafts']['new_completed_cases']>=15 else 'FAIL',state['drafts']['new_case_statuses'],'acceptance')
 vs=state['videos']['videos'];ready=count(v['platform'] for v in vs if v['status']=='transcript_ready')
 check('three_youtube_three_bilibili','PASS' if ready.get('youtube',0)>=3 and ready.get('bilibili',0)>=3 else 'FAIL',ready,'acceptance')
 check('speakers_financial_correction_crossplatform_dedup','FAIL','Speaker diarization and ASR never run; all ready videos are YouTube, so no cross-platform pair tested','acceptance')
 # This read frontend/app.js, which has been the legacy page behind /legacy since the workbench
 # became the entry point, so its verdict described a surface nobody opens. Read the live entry
 # and say which half of the criterion is met.
 wb=(ROOT/'frontend/workbench.js').read_text()
 desk="'today'" in wb and 'intel' in wb
 # Explainable means each feature shows its natural range, sample size, method and supporting
 # post ids next to the current value.
 explain=all(k in wb for k in ('support_post_ids','sample_size','natural_range'))
 check('intelligence_desk_and_explainable_personas','PASS' if desk and explain else 'FAIL',
       {'entry_point':'frontend/workbench.js (frontend/app.js is the legacy page behind /legacy)',
        'intelligence_desk':desk,
        'explainable_personas':explain,
        'missing':[] if explain else
         ['per-feature natural range','sample size','computation method','supporting post ids'],
        'present':'persona cards show donor set and per-role status only'},'acceptance')
 check('claim_graph_evergreen_update_pipeline','FAIL','No executed hot Claim Graph, Atomic Principle/Conflict Graph, scheduling or evidence-triggered update run','acceptance')
 iso=subprocess.run([sys.executable,'-B',str(ROOT/'tests/test_legacy_isolation.py')],capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
 check('legacy_isolation_all_routes','PASS' if iso.returncode==0 else 'FAIL',{'exit_code':iso.returncode,'test':'tests/test_legacy_isolation.py','asserts':'chart/diagram/diagram-image/editorial-reviews/drafts/export reject the 82 legacy IDs with 409; audit=true access is labelled; edits and diagrams cannot attach to legacy; blind set excludes legacy','output':(iso.stdout+iso.stderr)[-1500:]},'acceptance')
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
 print('CLEAN_LANGUAGES '+json.dumps(d['clean_languages'],sort_keys=True));print(f"DRAFTS_DB valid={g['valid']} legacy_invalid={g['legacy_invalid']} human_reviews={g['human_reviews']}")
 fa=g.get('file_artifacts') or {}
 # The DB line alone read "valid=0" while the content pipeline's artifacts sat on disk.
 print(f"DRAFTS_FILES ready={fa.get('drafts_ready')}/{fa.get('drafts_total')} "
       f"packages={fa.get('packages_ready')}/{fa.get('packages_total')} visuals={fa.get('visuals')} "
       f"reactivation={fa.get('reactivation_ready')} crosslang={fa.get('crosslang_ready')} "
       f"evergreen_cards={fa.get('evergreen_cards')} human_reviews=0")
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
