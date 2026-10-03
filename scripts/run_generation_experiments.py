import json,sys,random,hashlib,statistics,difflib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from app import Generate,generate,records,save,chart_svg,REGISTRY
from model_client import call
def main():
 completed={(d['persona_id'],d['language'],d['condition']):d for d in records('draft') if d['evidence_snapshot']['id']=='august-release' and not d['parent_id']}
 for lang in ['zh','en']:
  for pid in ['macro','industry','risk']:
   for condition in ['none','description','profile','exemplar','multi']:
    key=(pid,lang,condition)
    if key in completed:continue
    d=generate(Generate(persona_id=pid,language=lang,condition=condition));completed[key]=d
    print(json.dumps({'stage':'ablation','n':len(completed),'persona':pid,'language':lang,'condition':condition,'draft_id':d['id'],'numeric_flags':d['evaluation']['numeric_mentions_requiring_review']}),flush=True)
 # Live mechanism test: actual old-evidence generation, test edit, new evidence ingestion and actual regeneration.
 old=generate(Generate(persona_id='macro',snapshot_id='july-release',condition='multi'))
 testedit=save('edit',{'draft_id':old['id'],'text':'TEST EDIT — retain the distinction between payroll changes and unemployment survey rates.','author':'automated integration fixture; not a human review'})
 evidence=save('evidence',{'snapshot':REGISTRY['snapshots'][1],'ingestion':'integration replay of captured real publication'})
 new=generate(Generate(persona_id='macro',snapshot_id=evidence['id'],parent_id=old['id'],condition='multi'))
 replay={'old_id':old['id'],'new_id':new['id'],'evidence_id':evidence['id'],'test_edit_id':testedit['id'],'old_text_hash':hashlib.sha256(old['text'].encode()).hexdigest(),'new_text_hash':hashlib.sha256(new['text'].encode()).hexdigest(),'old_chart_hash':hashlib.sha256(chart_svg(old).encode()).hexdigest(),'new_chart_hash':hashlib.sha256(chart_svg(new).encode()).hexdigest(),'changed_facts':new['changed_fact_ids'],'preserved_edits':new['preserved_edits'],'human_review':False}
 (ROOT/'runs/update_replay.json').write_text(json.dumps(replay,ensure_ascii=False,indent=2))
 # Two directional audience transfers, independent from the ablation dataset.
 cross=[];dest=ROOT/'cross_language_tests';dest.mkdir(exist_ok=True)
 for src_lang,target in [('zh','en'),('en','zh')]:
  source=completed[('macro',src_lang,'multi')]
  prompt='Adapt this research draft for an audience using '+target+'. Preserve factual values, units, dates, attribution and conditional language. Explain unfamiliar context briefly. Do not introduce any new market fact. Return only the adapted text. Facts: '+json.dumps(source['facts'],ensure_ascii=False)+'\nSource draft:\n'+source['text']
  result=call(prompt,'cross_language_'+src_lang+'_to_'+target,900)
  row={'id':src_lang+'-to-'+target,'source_draft_id':source['id'],'source_text':source['text'],'target_text':result['text'],'run_id':result['run_id'],'facts':source['facts'],'human_blind_review':None,'quality_status':'unapproved; lexical and human review required'};cross.append(row);(dest/f"{row['id']}.json").write_text(json.dumps(row,ensure_ascii=False,indent=2))
 rows=[]
 for key,d in completed.items():
  rows.append({'draft_id':d['id'],'persona_id':key[0],'language':key[1],'condition':key[2],'characters':len(d['text']),'numeric_candidate_flags':len(d['evaluation']['numeric_mentions_requiring_review']),'ai_pattern_flags':len(d['evaluation']['ai_pattern_flags']),'longest_exemplar_overlap_chars':d['evaluation']['longest_exemplar_overlap']['chars'],'generation_run_id':d['generation_run_id'],'human_quality':None,'human_faithfulness':None,'human_edit_distance':None})
 (ROOT/'ml_experiments/D_generation_ablation.json').write_text(json.dumps({'design':'3 personas × 2 languages × 5 conditions, one generation per cell; exploratory, no statistical generalization','rows':rows,'human_blind_results':None,'status':'real runs completed; human validation pending'},ensure_ascii=False,indent=2))
 blinded=[];answer={};items=list(completed.values());random.Random(42).shuffle(items)
 for i,d in enumerate(items):
  bid='case-'+hashlib.sha256((d['id']+'blind').encode()).hexdigest()[:10];blinded.append({'id':bid,'text':d['text'],'language':d['language'],'facts':[{k:f[k] for k in ['value','unit','period','source_id']} for f in d['facts']]});answer[bid]={'draft_id':d['id'],'persona_id':d['persona_id'],'condition':d['condition']}
 for r in cross:
  bid='cross-'+hashlib.sha256(r['run_id'].encode()).hexdigest()[:10];blinded.append({'id':bid,'text':r['target_text'],'language':r['id'].split('-')[-1],'facts':[{k:f[k] for k in ['value','unit','period','source_id']} for f in r['facts']]});answer[bid]={'cross_language_id':r['id']}
 (ROOT/'ml_experiments/blind_cases.json').write_text(json.dumps({'cases':blinded,'human_submissions':0},ensure_ascii=False,indent=2));(ROOT/'ml_experiments/blind_answer_key.private.json').write_text(json.dumps(answer,indent=2))
 print(json.dumps({'completed_ablation':len(rows),'cross_language':len(cross),'update_replay':replay}),flush=True)
if __name__=='__main__':main()
