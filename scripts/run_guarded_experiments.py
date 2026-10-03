import sys,json,hashlib,random,collections,re,time
from pathlib import Path
from model_client import ROOT,call,active_role
sys.path.insert(0,str(ROOT/'backend'))
from app import Generate,records,save,get,chart_svg,checks,style
from guarded import generate_guarded
from promotion_policy import output_gate

def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
def main():
    corpus=hashlib.sha256((ROOT/'data/clean_posts.jsonl').read_bytes()).hexdigest();rows=[];failures=[]
    # Multi first produces a reviewable result for all personas/languages promptly.
    for condition in ['multi','none','description','profile','exemplar']:
      for language in ['zh','en']:
       for persona in ['macro','industry','risk']:
        existing=next((d for d in records('draft') if d.get('engine')=='guarded-v3' and d.get('model_role')==active_role() and d.get('corpus_sha256')==corpus and d['condition']==condition and d['persona_id']==persona and d['language']==language and not d.get('parent_id') and d['evidence_snapshot']['id']=='august-release'),None)
        try:
         d=existing or generate_guarded(Generate(persona_id=persona,language=language,condition=condition))
         interpretation='\n'.join(p['interpretation'] for p in d['paragraphs']);f=style.features(interpretation)
         row={'draft_id':d['id'],'persona_id':persona,'language':language,'condition':condition,'corpus_sha256':corpus,'characters':len(d['text']),'interpretation_characters':len(interpretation),'structured_numeric_contract':d['evaluation']['structured_numeric_contract'],'promotional_matches':len(output_gate(d['text'])),'model_run_id':d['generation_run_id'],'plan_run_id':d['plan_run_id'],'ai_pattern_flags':d['evaluation']['ai_pattern_flags'],'longest_exemplar_overlap':d['evaluation']['longest_exemplar_overlap'],'measured_output_style':f,'human_quality':None,'human_persona_recognition':None,'human_faithfulness':None}
         rows.append(row);print(json.dumps({'stage':'guarded_ablation','completed':len(rows),'persona':persona,'language':language,'condition':condition,'draft_id':d['id']}),flush=True)
        except Exception as e:
         failures.append({'persona':persona,'language':language,'condition':condition,'error':str(e)});print(json.dumps({'stage':'guarded_failed','persona':persona,'language':language,'condition':condition,'error':str(e)}),flush=True)
         if not rows:
          write(ROOT/'ml_experiments/D_guarded_generation_ablation.json',{'rows':rows,'failures':failures,'status':'stopped after first failed cell; preserve quarantine and correct generator before broad run'})
          raise
        write(ROOT/'ml_experiments/D_guarded_generation_ablation.json',{'design':'3 personas × 2 languages × 5 modes; one sample per cell, exploratory','model_role':active_role(),'corpus_sha256':corpus,'rows':rows,'failures':failures,'interpretation':'Model and generation contract both changed versus the 1.5B baseline; improvement cannot be attributed solely to model size. Exact numeric rendering is mechanical; semantic fidelity and persona quality await human review.','human_results':None})
    # Actual primary-evidence update, immutable old draft, independent regenerated text.
    old=generate_guarded(Generate(persona_id='macro',language='zh',snapshot_id='july-release'))
    edit=save('edit',{'draft_id':old['id'],'text':'INTEGRATION TEST NOTE — 请保留“修订可能改变判断，单月变化不等于政策承诺”的限定。','author':'automated integration fixture, not human review'})
    from app import snapshot
    ev=save('evidence',{'snapshot':snapshot('august-release'),'ingestion':'actual local ingestion of a captured primary publication for replay'})
    new=generate_guarded(Generate(persona_id='macro',language='zh',snapshot_id=ev['id'],parent_id=old['id']))
    replay={'old_id':old['id'],'new_id':new['id'],'evidence_id':ev['id'],'test_edit_id':edit['id'],'old_text_sha256':hashlib.sha256(old['text'].encode()).hexdigest(),'new_text_sha256':hashlib.sha256(new['text'].encode()).hexdigest(),'old_chart_sha256':hashlib.sha256(chart_svg(old).encode()).hexdigest(),'new_chart_sha256':hashlib.sha256(chart_svg(new).encode()).hexdigest(),'changed_facts':new['changed_fact_ids'],'manual_edit_preserved':edit['id'] in [e['edit_id'] for e in new['preserved_edits']],'human_edit_test':False,'source':'real BLS release snapshots; historical replay, no live monitor claim'}
    assert replay['manual_edit_preserved'] and replay['old_text_sha256']!=replay['new_text_sha256'] and replay['old_chart_sha256']!=replay['new_chart_sha256']
    write(ROOT/'runs/guarded-update-replay.json',replay)
    cross=[]
    for source_lang,target in [('zh','en'),('en','zh')]:
      source=next(get(r['draft_id']) for r in rows if r['language']==source_lang and r['persona_id']=='macro' and r['condition']=='multi')
      result=call('Translate this financial working draft into '+target+'. Preserve every numeric value, sign, unit, date, source label, attribution and hedge. Do not add financial facts or promotions. Return the translated article only. TEXT:\n'+source['text'],'guarded_cross_language',1200,0,model_role=active_role())
      def nums(t):return collections.Counter(re.findall(r'[-+]?\d[\d,]*(?:\.\d+)?',re.sub(r'\[F\d+\]','',t)))
      source_numbers=nums(source['text']);translated_numbers=nums(result['text'])
      record={'direction':source_lang+'-to-'+target,'source_id':source['id'],'source_text':source['text'],'translated_text':result['text'],'run_id':result['run_id'],'source_numeric_literals':dict(source_numbers),'translated_numeric_literals':dict(translated_numbers),'numeric_multiset_equal':source_numbers==translated_numbers,'source_citations':re.findall(r'\[F\d+\]',source['text']),'translated_citations':re.findall(r'\[F\d+\]',result['text']),'promotion_gate_passed':not output_gate(result['text']),'human_semantic_and_hedge_review':None,'limitations':'Lexical preservation is not semantic or translation quality validation; alternate valid numeric formatting can cause flags.'}
      write(ROOT/'cross_language_tests'/('guarded-'+record['direction']+'.json'),record);cross.append(record)
    cases=[];key=[];random.Random(73).shuffle(rows)
    for i,r in enumerate(rows):
      d=get(r['draft_id']);cid='G-'+d['id'].split('-',1)[1];cases.append({'id':cid,'language':d['language'],'text':d['text'],'facts':d['facts']});key.append({'case_id':cid,'draft_id':d['id'],'persona':d['persona_id'],'condition':d['condition']})
    for i,r in enumerate(cross):
      cid='GT-'+r['run_id'];cases.append({'id':cid,'language':r['direction'].split('-to-')[1],'text':r['translated_text']});key.append({'case_id':cid,'run_id':r['run_id'],'direction':r['direction']})
    oldcases=json.loads((ROOT/'ml_experiments/blind_cases.json').read_text())
    oldkey=json.loads((ROOT/'ml_experiments/blind_answer_key.private.json').read_text())
    write(ROOT/'ml_experiments/baseline-v1-blind-cases.json',oldcases);write(ROOT/'ml_experiments/baseline-v1-blind-answer-key.private.json',oldkey)
    write(ROOT/'ml_experiments/blind_cases.json',{'cases':cases,'status':'ready for real human review','instructions':'Do not inspect other draft views while reviewing. Conditions hidden in this form; single local editor can access full corpus elsewhere, so this is procedural blinding, not access-controlled blinding.'})
    write(ROOT/'ml_experiments/blind_answer_key.private.json',key)
    print(json.dumps({'completed_cells':len(rows),'failed_cells':len(failures),'update_replay':replay,'cross_language_tests':len(cross),'human_review':0}),flush=True)

if __name__=='__main__':main()
