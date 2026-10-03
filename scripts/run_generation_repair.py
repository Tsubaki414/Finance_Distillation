"""Six operational smoke cases after the frozen v3 ablation; never merge cohorts."""
from pathlib import Path
import json,sys,datetime,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import Generate
from guarded import generate_guarded
def main():
 rows=[];failures=[]
 for language in ['zh','en']:
  for persona in ['macro','industry','risk']:
   try:
    d=generate_guarded(Generate(persona_id=persona,language=language,condition='multi'))
    rows.append({'draft_id':d['id'],'persona':persona,'language':language,'engine':d['engine'],'run_id':d['generation_run_id'],'corpus_sha256':d['corpus_sha256'],'generation_contract_sha256':d['generation_contract_sha256']})
   except Exception as e:failures.append({'persona':persona,'language':language,'error':str(e)})
   report={'as_of':datetime.datetime.now(datetime.timezone.utc).isoformat(),'design':'3 personas × 2 languages, multi only; operational repair checks, not five-mode ablation','engine':'guarded-v4','change':'Explicit nested JSON example, calendar normalization, distinction between measurement revisions and economic events, unemployment inference limits','rows':rows,'failures':failures,'human_quality':None,'comparison_limitation':'No claim of causal improvement; v3 cohort is frozen in D_guarded_generation_ablation.json'}
   (ROOT/'runs/generation-repair-v4.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'completed':len(rows),'failed':len(failures),'persona':persona,'language':language}),flush=True)
if __name__=='__main__':main()
