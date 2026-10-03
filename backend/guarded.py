import json,re,hashlib,statistics
from pathlib import Path
from decimal import Decimal
from model_client import ROOT,call,parse_json,active_role
from promotion_policy import output_gate
def compile_style(p):
 """Preserve measured targets in audit records, pass qualitative bins into prose generation."""
 f=p['measured_style_targets'];mean=f.get('sentence_mean',f.get('sentence_length_mean',60))
 return {'sentence_rhythm':'short clauses with occasional longer explanation' if mean<60 else 'develop a causal explanation across connected sentences','question_usage':'use sparingly' if f.get('question_rate',0)<.005 else 'occasional diagnostic question','hedging':'make uncertainty explicit; no certainty unsupported by evidence','format':'three concise paragraphs; no copied slogan; no personal trade claims','derivation':'deterministic bins from weighted measured profiles; editorial cutoffs not learned optimum'}
def fact_sentence(f,language):
 metric=('非农就业变动' if f['id'].startswith('payroll') else '失业率') if language=='zh' else ('nonfarm payroll change' if f['id'].startswith('payroll') else 'unemployment rate')
 value=(f"{f['value']:+,}" if f['id'].startswith('payroll') else str(f['value']))
 unit=('人' if f['unit']=='persons' else '%') if language=='zh' else (' persons' if f['unit']=='persons' else '%')
 return (f"{f['period']} {metric}为 {value}{unit}。" if language=='zh' else f"{f['period']} {metric}: {value}{unit}.")+f" [{f['label']}]"
def validate_body(obj,facts):
 if not isinstance(obj,dict) or set(obj)!={'paragraphs'}:raise ValueError('Return only paragraphs')
 ps=obj['paragraphs'];allowed={f['label'] for f in facts}
 months={str(i) for i in range(1,13)};years={f['period'].split('-')[0] for f in facts}
 allowed_numbers={Decimal(str(f['value'])) for f in facts}
 payroll=sorted([f for f in facts if f['id'].startswith('payroll')],key=lambda f:f['period'])
 if len(payroll)>=2:allowed_numbers.add(Decimal(str(payroll[-1]['value']))-Decimal(str(payroll[-2]['value'])))
 for f in facts:
  for span in f['spans']:
   allowed_numbers.update(Decimal(x.replace(',','')) for x in re.findall(r'[-+]?\d[\d,]*(?:\.\d+)?',span['text']))
 if not isinstance(ps,list) or len(ps)!=3:raise ValueError('Exactly three paragraphs required')
 for p in ps:
  if set(p)!={'interpretation','fact_refs'} or not isinstance(p['interpretation'],str) or len(p['interpretation'])<30:raise ValueError('Each paragraph needs interpretation and fact_refs')
  without_calendar=re.sub(r'\b(?:'+ '|'.join(years)+r')[-/]\d{1,2}\b', '', p['interpretation'])
  for month in months:without_calendar=re.sub(r'(?<!\d)'+month+r'\s*月', '',without_calendar)
  for year in years:without_calendar=re.sub(r'(?<!\d)'+year+r'(?:\s*年)?(?!\d)','',without_calendar)
  without_calendar=without_calendar.replace('−','-')
  without_calendar=re.sub(r'\bnegative\s+(\d[\d,]*(?:\.\d+)?)',r'-\1',without_calendar,flags=re.I)
  without_calendar=re.sub(r'\bpositive\s+(\d[\d,]*(?:\.\d+)?)',r'+\1',without_calendar,flags=re.I)
  scales={'万':10000,'千':1000,'million':1000000,'thousand':1000,'billion':1000000000,'k':1000,'m':1000000,'':1}
  for m in re.finditer(r'(?<![A-Za-z])([-+]?\d[\d,]*(?:\.\d+)?)\s*(万|千|million\b|thousand\b|billion\b|k\b|m\b)?',without_calendar,re.I):
   value=Decimal(m.group(1).replace(',',''))*scales[(m.group(2) or '').lower()]
   if value not in allowed_numbers:raise ValueError('Numeric claim absent from supplied source values: '+m.group())
  if re.search(r'\$\s*\d|\d[\d,.]*\s*(?:美元|USD)',without_calendar,re.I):raise ValueError('The supplied labor observations do not support money amounts')
  if output_gate(p['interpretation']):raise ValueError('Promotional text is forbidden')
  if not isinstance(p['fact_refs'],list) or set(p['fact_refs'])-allowed:raise ValueError('Use only supplied fact labels')
  if not p['fact_refs'] and not re.search(r'需要|尚需|缺少|无法|不能|\b(?:need|missing|cannot|additional|further|lacks?|lacking|absence|absent|insufficient|unable)\b',p['interpretation'],re.I):raise ValueError('Uncited paragraphs must explicitly discuss missing evidence or limits')
  if p['fact_refs']:
   mentioned=set(re.findall(r'(?<!\d)(\d{1,2})\s*月',p['interpretation']))
   for month,name in [('6','June'),('7','July'),('8','August')]:
    if re.search(r'\b'+name+r'\b',p['interpretation'],re.I):mentioned.add(month)
   supported={str(int(f['period'].split('-')[1])) for f in facts if f['label'] in p['fact_refs']}
   if mentioned-supported:raise ValueError('Calendar month mentioned without matching fact reference: '+','.join(sorted(mentioned-supported)))
 return ps
def generate_guarded(body):
 from app import persona,snapshot,records,get,save,LOCK,checks
 from fastapi import HTTPException
 if body.language not in ['zh','en'] or body.condition not in ['none','description','profile','exemplar','multi']:raise HTTPException(422,'Invalid language or condition')
 p=persona(body.persona_id);s=snapshot(body.snapshot_id);facts=[{**f,'label':'F'+str(i+1)} for i,f in enumerate(s['facts'])]
 minimal_facts=[fact_sentence(f,'en')+' Source wording: '+f['spans'][-1]['text'] for f in facts]
 scope='These are UNITED STATES economy-wide BLS data. Payroll numbers are MONTHLY NET CHANGES in nonfarm jobs, NOT employee totals and NOT a company workforce. A positive payroll change means jobs increased in that month. Unemployment is a separate household-survey rate. No company earnings, job openings, wages, stock prices, analyst consensus or policy decisions are supplied. Revisions are revised measurements, NOT analyst forecast errors. Do not infer a surprise or a beat of expectations.'
 payroll=sorted([f for f in facts if f['id'].startswith('payroll')],key=lambda f:f['period'])
 comparison=('The latest month has a larger positive monthly net job increase than the preceding month in this release. This does not establish a policy decision or company earnings.' if len(payroll)>1 and payroll[-1]['value']>payroll[-2]['value']>0 else 'Discuss the supplied monthly change without inventing an employment level or assuming a lasting trend.')
 if any('unchanged' in span['text'].lower() for f in facts if f['id']=='unemployment' for span in f['spans']):comparison+=' The official release explicitly says the unemployment rate was UNCHANGED. 失业率保持不变，不能写成已经下降或上升。'
 comparison+=' A revision changes an estimate of a past month: it does NOT show a delayed hiring event. An unchanged unemployment rate does NOT establish participation direction, wage pressure, job quality, labor saturation or overheating. Payroll and unemployment come from different surveys. A negative initial estimate does NOT mean that an earlier downward revision occurred.'
 comparison+=' Wage, participation and sector detail are outside this limited evidence bundle, not necessarily absent from the full official report.'
 style=compile_style(p);ctx={} if body.condition=='none' else {'description':p['description'],'angle':p['analysis_angle']}
 if body.condition in ['profile','exemplar','multi']:ctx['style']=style
 exemplar_refs=[]
 if body.condition in ['exemplar','multi']:
  from app import context
  sample=context(p,'exemplar')['style_examples_untrusted'];exemplar_refs=sample
  # Keep structure, strip inherited factual values and identity. Current facts stay separate.
  ctx['structure_examples']=[{'text':re.sub(r'\d+(?:[.,]\d+)*','<historical_number>',e['text'][:180]),'use':'sentence organization only; never evidence about the current release'} for e in sample]
 if body.condition=='multi':
  ctx['role_assignments']=p['roles'];ctx['role_meaning']='Weights are editorial relative priorities, not observed returns or article facts. Knowledge selects covered questions; reasoning selects alternative mechanisms; language only affects exposition; habits select next verification; visual has no donor evidence.'
  ctx['donor_frameworks']={}
  for h in p['donors']:
   kp=json.loads((ROOT/'knowledge_profiles'/f'{h}.json').read_text())
   enrichment=kp.get('model_enrichment',{})
   ctx['donor_frameworks'][h]={'observed_topics':[f['feature'] for f in kp['features'] if f['support_count']>0], 'reasoning_approach':[f['mechanism'][:160] for f in enrichment.get('frameworks',[])[:1]],'boundary':'Sample-derived approach; never current-event evidence.'}
  ctx['observed_habits']={}
  for h in p['donors']:
   hp=json.loads((ROOT/'content_habit_profiles'/f'{h}.json').read_text())
   ctx['observed_habits'][h]={'topic_switching':'frequent among observed posts' if (hp['topic_switch_rate'] or 0)>.5 else 'topics often persist among observed posts','reaction_and_corrections':'unknown due incomplete timeline; do not invent habits'}
 payload={'scope':scope,'observations':minimal_facts,'arithmetical_comparison':comparison,'important_limit':'本证据包只摘录部分数字，不能写成官方未披露工资或参与率；没有分析师预测，不能写超预期或意外强劲。','audience_language':body.language,'persona':ctx,'editor_request':body.editor_note}
 with LOCK:
  plan=call('Create an independent analysis plan in the audience language, at most 60 words or 100 Chinese characters. Identify one interpretation, one alternative explanation, and one missing observation. Do not repeat numeric values. Payroll is a national monthly change, not a company employee count. INPUT:\n'+json.dumps(payload,ensure_ascii=False),'guarded_v41_independent_plan',180,0,model_role=active_role())
  instruction='Write an original financial interpretation in '+body.language+'. Return ONLY a JSON object with one key paragraphs. Its value is exactly three items, each with keys interpretation (two concise prose sentences) and fact_refs (a list of valid labels such as F1). Exact observed economic figures will also be inserted before cited paragraphs, so focus on interpretation and avoid unnecessary repetition. Any numeric claim must preserve the source value, unit, sign, metric and period; 万/thousand notation is allowed if exact. Initial published estimates are NOT analyst forecasts. A paragraph solely discussing missing evidence may have an empty fact_refs list. Interpret the national labor data, distinguish uncertainty, and explain what needs checking next. Do not invent company actions, policy decisions or current market flows. No promotions, subscriptions, referrals, giveaways, slogans or claimed trades. Historical examples affect exposition only. INPUT:\n'+json.dumps(payload,ensure_ascii=False)+'\nIndependent plan, subordinate to observations:\n'+plan['text']
  schema={'paragraphs':[{'interpretation':'<two original sentences in the requested language>','fact_refs':['F1','F2']},{'interpretation':'<two original sentences in the requested language>','fact_refs':['F3']},{'interpretation':'<two original sentences explaining missing evidence or limits>','fact_refs':[]}]}
  instruction+='\nREQUIRED JSON STRUCTURE (replace placeholder prose; choose fact_refs that actually support each paragraph; an array of strings is INVALID):\n'+json.dumps(schema)+'\nReturn the JSON object only.'
  attempts=[];obj=None;support=None;validation_errors=[]
  for attempt in range(2):
   result=call(instruction,'guarded_v41_persona_draft',650,0,model_role=active_role());attempts.append(result['run_id'])
   try:
    obj=parse_json(result['text']);ps=validate_body(obj,facts)
    support=call('Return exactly 1 or 0. Does this draft avoid contradicting the supplied observations and avoid asserting unsupplied company actions, labor statistics, price moves, or policy decisions as facts? Conditional hypotheses and explicitly missing information are allowed. A positive monthly payroll change is an INCREASE in jobs, not a headcount level. A stronger monthly increase cannot be described as fewer jobs added than the preceding smaller increase. This is a same-model diagnostic, not a human quality score. OBSERVATIONS: '+scope+' '+comparison+' '+json.dumps(minimal_facts)+'\nDRAFT: '+json.dumps(ps,ensure_ascii=False),'guarded_v41_semantic_diagnostic',4,0,model_role=active_role())
    if support['text'].strip()!='1':raise ValueError('Draft failed the semantic consistency diagnostic; restrict claims to supplied national monthly changes and explicit unknowns')
    break
   except Exception as e:
    validation_errors.append({'run_id':result['run_id'],'error':str(e)})
    obj=None;instruction+='\nPrevious response failed output validation: '+str(e)+'. Use this exact nested structure: '+json.dumps(schema)+'. Replace placeholders with original prose and supply accurate fact_refs. No prose outside JSON.'
  if obj is None:
   failed=save('quarantined-generation',{'persona_id':p['id'],'condition':body.condition,'language':body.language,'model_role':active_role(),'attempt_run_ids':attempts,'plan_run_id':plan['run_id'],'validation_errors':validation_errors,'reason':'failed structured factual rendering contract'});raise RuntimeError('Generation quarantined: '+failed['id'])
 parent=get(body.parent_id) if body.parent_id else None;edits=[e for e in records('edit') if parent and e['draft_id']==parent['id']]
 by={f['label']:f for f in facts};paragraphs=[]
 for i,entry in enumerate(ps):
  selected=[by[x] for x in dict.fromkeys(entry['fact_refs'])];canonical=' '.join(fact_sentence(f,body.language) for f in selected);paragraphs.append({'id':'p'+str(i+1),'text':canonical+' '+entry['interpretation'],'interpretation':entry['interpretation'],'fact_ids':[f['id'] for f in selected],'dependency_coverage':'structured fact_refs','canonical_fact_text':canonical})
 text='\n\n'.join(x['text'] for x in paragraphs);oldfacts={f['id']:(f['value'],f['period']) for f in parent['facts']} if parent else {};changed=[f['id'] for f in facts if oldfacts.get(f['id'])!=(f['value'],f['period'])] if parent else []
 resultdata={'engine':'guarded-v4.1','model_role':active_role(),'persona_id':p['id'],'persona_snapshot':p,'condition':body.condition,'language':body.language,'evidence_snapshot':s,'facts':facts,'analysis_plan':plan['text'],'plan_run_id':plan['run_id'],'generation_run_id':result['run_id'],'attempt_run_ids':attempts,'semantic_diagnostic_run_id':support['run_id'],'usage':{'plan':plan['usage'],'draft':result['usage'],'diagnostic':support['usage']},'text':text,'paragraphs':paragraphs,'raw_model_json':obj,'parent_id':body.parent_id,'changed_fact_ids':changed,'preserved_edits':[{'edit_id':e['id'],'text':e['text'],'resolution':'preserved; needs editor reconciliation'} for e in edits],'editor_note':body.editor_note,'retrieval':exemplar_refs,'style_compilation':style,'evaluation':{'structured_numeric_contract':'passed','exact_fact_rendering':True,'unbound_economic_numeric_literals':0,'observed_calendar_references_allowed':True,'semantic_faithfulness':'same-model consistency diagnostic passed; independent human review pending',**checks('\n'.join(x['interpretation'] for x in paragraphs),facts,exemplar_refs)},'approval':'unreviewed','impact':{'previous_paragraph_ids':[x['id'] for x in parent['paragraphs'] if set(x['fact_ids'])&set(changed)] if parent else [],'uncited_previous_paragraphs':[x['id'] for x in parent['paragraphs'] if not x['fact_ids']] if parent else [],'regeneration_scope':'full model regeneration; explicit paragraph dependencies and preserved manual edits'}}
 resultdata['corpus_sha256']=hashlib.sha256((ROOT/'data/clean_posts.jsonl').read_bytes()).hexdigest()
 resultdata['validation_attempts']=validation_errors
 resultdata['allowed_derivations']=[{'formula':payroll[-1]['label']+' - '+payroll[-2]['label'],'value':payroll[-1]['value']-payroll[-2]['value'],'unit':'persons','meaning':'difference between latest and preceding monthly payroll changes, not an employment level'}] if len(payroll)>=2 else []
 resultdata['profile_bundle_sha256']=hashlib.sha256(b''.join((ROOT/kind/f'{h}.json').read_bytes() for h in sorted(p['donors']) for kind in ['knowledge_profiles','style_profiles','content_habit_profiles'])).hexdigest()
 resultdata['generation_contract_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 resultdata['evaluation']['promotion_gate']={'passed':not output_gate(text),'scope':'explicit lexical screening plus reviewed clean exemplars; undisclosed promotion is not algorithmically proven absent'}
 d=save('draft',resultdata);(ROOT/'generated_samples'/f"{d['id']}.json").write_text(json.dumps(d,ensure_ascii=False,indent=2));return d
