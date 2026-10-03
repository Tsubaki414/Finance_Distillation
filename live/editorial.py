"""Opt-in source-grounded editing with bounded QA-addressed repair.

Production's default Pipeline is unchanged. All candidates, reviews and patches
remain inspectable; model-reviewed is never human-approved.
"""
from copy import deepcopy
import re
from live.distillation import Pipeline, require
from live.distillation_source import digest, paragraphs, snapshot
from live.numeric_fidelity import normalize as numeric_text
from live.editorial_repair import apply_repairs
from live import editorial_prompts as prompts
from live.source_hygiene import VERSION as HYGIENE_VERSION

FIDELITY_CHECKS = ('facts_preserved','numeric_bindings_preserved','entities_preserved','reasoning_preserved',
                   'stance_preserved','identity_preserved','no_unsupported_additions','no_editorial_commentary','context_complete')
FIRST_PERSON = re.compile(r'\b(?:I|my|mine|we|our|ours)\b|我(?:们)?|本人|笔者', re.I)
FOOTER = re.compile(r'(?:^|\n)(?:来源|出处|译自|Source|Translated from)\s*[:：]',re.I)


class EditorialPipeline(Pipeline):
    pipeline_mode='editorial_candidate'
    pipeline_version='editorial_completion_v2.2-hygiene'
    prompt_version=prompts.VERSION+'+'+HYGIENE_VERSION

    def __init__(self,*args,max_repair_rounds=1,recovery=None,background=None,**kwargs):
        super().__init__(*args,**kwargs)
        require(type(max_repair_rounds) is int and 0<=max_repair_rounds<=2,'Repair rounds must be 0–2')
        self.max_repair_rounds=max_repair_rounds;self.recovery=recovery;self.background=background

    def key(self,source):
        return digest([super().key(source),self.max_repair_rounds,
                       digest(self.background.catalog) if self.background else None,
                       sorted(self.recovery.allowed_hosts) if self.recovery else []])

    def run(self,row,replay=True):
        if self.recovery:
            snapshot(self.normalize_source(row),self.store/'intake')
            row=self.recovery.recover(row)
        return super().run(row,replay=replay)

    def select(self,source,account,attempt):
        spans=paragraphs(source['original_text'])
        value=self.ask(attempt,'editorial',prompts.PLAN,{'source':source,'paragraphs':spans,
            'target_account':account,'target_language':account['lang'],
            'background_catalog':self.background.descriptors() if self.background else []},4000)
        attempt['editorial_judgment']=value
        if value.get('needs_source') is True or value.get('dependencies_complete') is False:
            return {'passages':[],'needs_source':True,'reason':value.get('source_request') or value.get('guidance')}
        ids=value.get('paragraph_ids');require(isinstance(ids,list) and ids,'Empty editorial selection')
        chosen=[p for p in spans if p['paragraph_id'] in ids]
        require([p['paragraph_id'] for p in chosen]==ids,'Invalid/reordered/duplicate source selection')
        require(isinstance(value.get('guidance'),str),'Missing editorial judgment')
        requests=value.get('background_requests',[])
        require(isinstance(requests,list) and len(requests)<=2,'Background request limit exceeded')
        attempt['factual_context']=[]
        for request in requests:
            try:
                require(isinstance(request,dict),'Invalid background request')
                require(self.background is not None,'Background recovery not configured')
                attempt['factual_context'].append(self.background.resolve(request,source))
            except Exception as exc:
                attempt['background_failure']={'request':request,'error_type':type(exc).__name__}
                return {'passages':chosen,'needs_source':True,'reason':'Requested necessary background unavailable'}
        return {'source_hash':source['source_hash'],'passages':chosen,'reason':value['guidance'],
                'selection_id':digest([source['source_hash'],[(p['start'],p['end']) for p in chosen]]),
                'excluded_ranges':[p for p in spans if p['paragraph_id'] not in ids]}

    def candidate(self,value,selection):
        require(value.get('needs_source') is False,'Missing context status')
        rows=value.get('segments');require(isinstance(rows,list) and rows,'Missing adapted paragraphs')
        require(isinstance(value.get('editor_notes'),str),'Missing private edit notes')
        ids={p['paragraph_id'] for p in selection['passages']};segments=[];alignment=[];cursor=0
        for i,row in enumerate(rows):
            require(isinstance(row,dict) and isinstance(row.get('text'),str) and row['text'].strip(),'Empty/invalid adaptation paragraph')
            refs=row.get('source_paragraph_ids')
            require(isinstance(refs,list) and refs and all(isinstance(r,str) for r in refs) and len(set(refs))==len(refs) and set(refs)<=ids,'Unknown source alignment')
            pid=f'D{i+1}';segments.append({'paragraph_id':pid,'text':row['text'],'source_paragraph_ids':refs})
            alignment.append({'paragraph_id':pid,'target_start':cursor,'target_end':cursor+len(row['text']),
                'source_ranges':[{k:p[k] for k in ('paragraph_id','start','end')} for p in selection['passages'] if p['paragraph_id'] in refs]})
            cursor+=len(row['text'])+2
        return {'text':'\n\n'.join(r['text'] for r in segments),'segments':segments,'alignment':alignment,
                'editor_notes':value['editor_notes'],'edits':[],'added_background':value.get('additions',[]),
                'method':'source-grounded adaptation; no mandatory literal intermediate'}

    def validate_additions(self,candidate,context):
        additions=candidate.get('added_background',[])
        require(isinstance(additions,list),'Invalid additions ledger')
        by_id={e['evidence_id']:e for e in context}
        for addition in additions:
            require(isinstance(addition,dict),'Invalid addition')
            e=by_id.get(addition.get('evidence_id'));require(e is not None,'Unrequested background addition')
            require(addition.get('output_quote') and addition['output_quote'] in candidate['text'],'Addition output quote missing')
            require(addition.get('evidence_quote') and addition['evidence_quote'] in e['quote'],'Addition lacks exact independent evidence')

    def guards(self,source,selection,candidate,account,context):
        text=candidate['text'];mechanical=[];observations=[]
        lang,_=self.languages.detect(text)
        if lang!=account['lang']:mechanical.append({'code':'wrong_or_uncertain_language','detail':f'{lang} != {account["lang"]}'})
        for row in candidate['segments']:
            original='\n\n'.join(p['exact_text'] for p in selection['passages'] if p['paragraph_id'] in row['source_paragraph_ids'])
            for flag in self.policy(account).deterministic(source,[{'paragraph_id':row['paragraph_id'],'exact_text':original}],[row],account['lang'],'adaptation',detector=self.languages.detect):
                code=flag['code']
                if code=='wrong_or_uncertain_language':
                    # Unknown short definitions/formulas are not the wrong language.
                    rowlang,_=self.languages.detect(row['text'])
                    (mechanical if rowlang not in ('unknown',account['lang']) else observations).append(flag)
                elif code=='provenance_in_body':
                    urls=re.findall(r'https?://[^\s)]+',row['text'])
                    evidence=source['original_text']+'\n'+'\n'.join(e.get('url','') for e in context)
                    if FOOTER.search(row['text']) or any(u not in evidence for u in urls):mechanical.append(flag)
                    else:observations.append({**flag,'code':'in_source_evidence_link'})
                elif code in ('refusal_prose','promotion'):mechanical.append(flag)
                else:observations.append(flag)
        original='\n\n'.join(p['exact_text'] for p in selection['passages'])
        approved='\n'.join(e['quote'] for e in context)
        numeric,notes=self.policy(account).numeric(original+'\n'+approved,text);mechanical.extend(numeric);observations.extend(notes)
        return mechanical,observations

    def validate_findings(self,findings,source,text,context):
        require(isinstance(findings,list),'Missing QA findings')
        evidence=source['original_text']+'\n'+'\n'.join(c.get('text','') for c in source.get('context_items',[]))+'\n'+'\n'.join(e['quote'] for e in context)
        for i,f in enumerate(findings):
            require(isinstance(f,dict) and f.get('severity') in ('fidelity','editorial') and f.get('code') and f.get('detail'),'Invalid QA finding')
            for key,haystack in [('source_quote',evidence),('output_quote',text)]:
                quote=f.get(key);require(isinstance(quote,str) and (not quote or quote in haystack),'Invented QA quote')
            f['finding_id']=digest([i,f['code'],f['source_quote'],f['output_quote']])[:16]
        return findings

    def validate_review_evidence(self,rows,source,text,context,label):
        require(isinstance(rows,list),'Missing '+label)
        evidence=source['original_text']+'\n'+'\n'.join(c.get('text','') for c in source.get('context_items',[]))+'\n'+'\n'.join(e['quote'] for e in context)
        for item in rows:
            require(isinstance(item,dict) and type(item.get('valid')) is bool,'Invalid '+label)
            for key,haystack in [('source_quote',evidence),('output_quote',text)]:
                quote=item.get(key)
                require(isinstance(quote,str) and (not quote or quote in haystack),'Invented '+label+' quote')
        return rows

    def review(self,source,account,selection,attempt):
        candidate=attempt['localization'];context=attempt.get('factual_context',[])
        self.validate_additions(candidate,context)
        mechanical,observations=self.guards(source,selection,candidate,account,context)
        payload={'source':source,'selection':selection,'candidate':candidate,'target_account':account,
                 'target_language':account['lang'],'editorial_judgment':attempt['editorial_judgment'],
                 'factual_context':context,'deterministic_observations':observations+mechanical}
        verdict=self.ask(attempt,'qa',prompts.QA,payload,6500)
        checks=verdict.get('checks');require(isinstance(checks,dict) and all(type(checks.get(k)) is bool for k in FIDELITY_CHECKS),'Incomplete fidelity review')
        require(isinstance(verdict.get('numeric_notes'),str),'Unreviewed numeric differences')
        for field in ('identity_review','calculation_review'):
            for item in self.validate_review_evidence(verdict.get(field),source,candidate['text'],context,field):
                if not item['valid']:checks['identity_preserved' if field=='identity_review' else 'no_unsupported_additions']=False
        findings=self.validate_findings(verdict.get('findings'),source,candidate['text'],context)
        identity=None
        if FIRST_PERSON.search(source['original_text']) or FIRST_PERSON.search(candidate['text']):
            identity=self.ask(attempt,'identity_qa',prompts.IDENTITY,
                {'source':source,'selection':selection,'candidate':candidate,'target_account':account},3000)
            require(type(identity.get('valid')) is bool and isinstance(identity.get('observations'),list),'Incomplete identity review')
            self.validate_review_evidence(identity['observations'],source,candidate['text'],context,'identity observations')
            if not identity['valid'] or any(o.get('valid') is not True for o in identity['observations']):checks['identity_preserved']=False
            findings+=self.validate_findings(identity.get('findings'),source,candidate['text'],context)
        qa={'method':'numerical/code guards + semantic fidelity + focused identity; editorial assessment separate',
            'semantic':verdict,'identity':identity,'findings':[{'severity':'fidelity','repairable':False,**f} for f in mechanical]+findings,
            'observations':observations,'human_status':'pending','semantic_status':'model_reviewed',
            'editorial_status':'model_reviewed' if verdict.get('editorial_review') else 'missing_assessment'}
        attempt['qa']=qa;attempt.setdefault('qa_history',[]).append(deepcopy(qa))
        passed=not mechanical and all(checks[k] for k in FIDELITY_CHECKS) and not any(f['severity']=='fidelity' for f in findings)
        if not passed:attempt.update(draft_status='needs_review' if checks['context_complete'] else 'needs_source',
                                     qa_status='failed_or_uncertain',why='Fidelity/context review did not pass')
        return passed

    def compose_and_review(self,source,account,selection,attempt):
        value=self.ask(attempt,'adaptation',prompts.ADAPT,{'source':source,'selected_passages':selection['passages'],
            'target_account':account,'target_language':account['lang'],'editorial_judgment':attempt['editorial_judgment'],
            'factual_context':attempt.get('factual_context',[])},8000)
        attempt['adaptation_response']=value
        if value.get('needs_source') is True:
            attempt.update(draft_status='needs_source',why='Writer reports missing context');return False
        attempt['localization']=self.candidate(value,selection)
        attempt['original_candidate']=deepcopy(attempt['localization'])
        attempt['repair_history']=[]
        for round_no in range(self.max_repair_rounds+1):
            if self.review(source,account,selection,attempt):return True
            if round_no>=self.max_repair_rounds or attempt['draft_status']=='needs_source':break
            actionable=[f for f in attempt['qa']['findings'] if f.get('repairable') is True and f.get('output_quote')
                        and (f['severity']=='fidelity' or f['code']=='unnecessary_attribution')]
            if not actionable:break
            value=self.ask(attempt,'repair',prompts.REPAIR,{'source':source,'selected_passages':selection['passages'],
                'candidate':attempt['localization'],'findings':actionable,'target_language':account['lang'],
                'factual_context':attempt.get('factual_context',[])},4000)
            before=deepcopy(attempt['localization'])
            attempt['repair_history'].append({'round':round_no+1,'before':before,'response':value,'status':'received'})
            repaired,patches=apply_repairs(before,actionable,value)
            attempt['repair_history'][-1].update(patches=patches,after=repaired,status='applied' if patches else 'no_safe_edit')
            if not patches:break
            attempt['localization']=repaired
        return False
