"""Append-only human edits and publication links. Nothing here publishes or trains."""
from contextlib import contextmanager
from difflib import SequenceMatcher
import fcntl
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone
from live.distillation import require
from live.distillation_source import digest, now
from live.source_hygiene import postcheck,annotate

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'live/store/localization_feedback'


def changed_spans(before,after):
    matcher=SequenceMatcher(a=before,b=after,autojunk=False)
    return [{'operation':op,'original_start':a,'original_end':b,'edited_start':c,'edited_end':d,
             'before':before[a:b],'after':after[c:d]} for op,a,b,c,d in matcher.get_opcodes() if op!='equal']


def timestamp(value):
    try:d=datetime.fromisoformat(value.replace('Z','+00:00'))
    except (AttributeError,ValueError):raise ValueError('ISO datetime required')
    require(d.tzinfo is not None,'Timestamp requires timezone')
    return d.astimezone(timezone.utc)


class FeedbackStore:
    def __init__(self,root=DEFAULT):self.root=Path(root)
    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'write.lock').open('a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def rows(self,kind):
        return [json.loads(p.read_text()) for p in sorted((self.root/kind).glob('*.json'))]
    def get(self,kind,key):
        require(isinstance(key,str) and key and all(c.isalnum() or c in '-_' for c in key),'Invalid record id')
        p=self.root/kind/(key+'.json');require(p.is_file(),'Unknown '+kind+' record');return json.loads(p.read_text())
    def append(self,kind,record):
        directory=self.root/kind;directory.mkdir(parents=True,exist_ok=True)
        with (directory/(record['id']+'.json')).open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
        return record
    def register(self,attempt,attempt_ref):
        text=(attempt.get('localization') or {}).get('text') or attempt.get('text','')
        require(isinstance(text,str) and text.strip(),'No candidate to review')
        require(attempt.get('source') and attempt.get('account_id') and attempt.get('run_id'),'Candidate provenance missing')
        cid='candidate-'+digest([attempt['run_id'],text])[:24]
        record={'id':cid,'draft_id':attempt.get('draft_id') or cid,'registered_at':now(),'attempt_ref':str(attempt_ref),
                'original_draft':text,'generation_original_draft':(attempt.get('original_candidate') or {}).get('text',text),
                'draft_version':digest(text),'source':attempt['source'],'account_id':attempt['account_id'],
                'target_language':attempt['target_language'],'editorial_judgment':attempt.get('editorial_judgment'),
                'pipeline_version':attempt['pipeline_version'],'prompt_version':attempt.get('prompt_version'),
                'account_profile':attempt.get('account_profile'),'domain_policy':attempt.get('domain_policy'),
                'machine_status':attempt['draft_status'],'qa':attempt.get('qa'),'human_review':'pending',
                'selection':attempt.get('selection'),'hygiene_decisions':attempt.get('hygiene_decisions',[]),
                'source_hygiene':attempt['source'].get('source_hygiene') or annotate(attempt['source']),
                'hygiene_review':attempt.get('hygiene_review')}
        with self.locked():
            p=self.root/'candidates'/(cid+'.json')
            if p.exists():return self.get('candidates',cid)
            return self.append('candidates',record)
    def review(self,candidate_id,expected_version,edited_text,decision,reviewer,reason='',categories=None,risk_dispositions=None):
        require(decision in ('approve','reject','save'),'Invalid human decision')
        require(isinstance(reviewer,str) and reviewer.strip(),'Reviewer identity required')
        require(isinstance(edited_text,str) and (edited_text.strip() or decision=='reject'),'Edited draft empty')
        require(isinstance(reason,str) and (categories is None or isinstance(categories,list) and all(isinstance(x,str) for x in categories)),'Invalid review notes')
        with self.locked():
            candidate=self.get('candidates',candidate_id)
            require(expected_version==candidate['draft_version'],'Stale draft version; review the changed candidate')
            risk=postcheck(candidate['source'],edited_text,(candidate.get('editorial_judgment') or {}).get('guidance',''),candidate.get('hygiene_decisions',[]))
            dispositions=risk_dispositions or []
            require(isinstance(dispositions,list),'Invalid risk dispositions')
            ids={f['id'] for f in risk['findings']};seen=set()
            for row in dispositions:
                require(isinstance(row,dict) and row.get('finding_id') in ids and row['finding_id'] not in seen,'Unknown or duplicate risk disposition')
                require(row.get('decision')=='accepted_in_context' and isinstance(row.get('reason'),str) and row['reason'].strip(),'Risk acceptance requires a reason')
                seen.add(row['finding_id'])
            if decision=='approve':
                require({f['id'] for f in risk['findings'] if f['level']=='review'}<=seen,'Review the remaining hygiene risks and record a reason before approval')
            spans=changed_spans(candidate['original_draft'],edited_text)
            record={'id':'review-'+uuid.uuid4().hex,'created_at':now(),'candidate_id':candidate_id,
                'draft_id':candidate['draft_id'],'original_draft':candidate['original_draft'],'human_edited_draft':edited_text,
                'reviewed_draft_version':expected_version,'human_draft_version':digest(edited_text),'changed_spans':spans,
                'human_edit_distance':1-SequenceMatcher(a=candidate['original_draft'],b=edited_text,autojunk=False).ratio(),
                'distance_method':'1 - character SequenceMatcher ratio; not a quality score or Levenshtein distance',
                'decision':decision,'reviewer':reviewer,'reviewer_identity':'self_reported','reason':reason,'categories':categories or [],
                'source_ref':candidate['source'],'account_id':candidate['account_id'],
                'editorial_judgment':candidate['editorial_judgment'],'pipeline_version':candidate['pipeline_version'],
                'prompt_version':candidate['prompt_version'],'human_override_of_machine_hold':candidate['machine_status']!='draft_ready'}
            record.update(account_profile=candidate.get('account_profile'),domain_policy=candidate.get('domain_policy'))
            record.update(hygiene_review=risk,risk_dispositions=dispositions,source_hygiene=candidate.get('source_hygiene'),
                          hygiene_decisions=candidate.get('hygiene_decisions',[]))
            return self.append('reviews',record)
    def publication(self,review_id,platform,published_post_id,published_at,published_text_hash,url=None):
        require(all(isinstance(x,str) and x.strip() for x in (platform,published_post_id)),'Platform/post id required')
        timestamp(published_at)
        with self.locked():
            review=self.get('reviews',review_id)
            require(review['decision']=='approve','Publication requires an actual approved human review')
            require(published_text_hash==review['human_draft_version'],'Published text differs from reviewed version')
            key=digest([review['account_id'],platform,published_post_id])[:24]
            require(not (self.root/'publications'/('publication-'+key+'.json')).exists(),'Published post already linked')
            return self.append('publications',{'id':'publication-'+key,'recorded_at':now(),'review_id':review_id,
                'draft_id':review['draft_id'],'candidate_id':review['candidate_id'],'account_id':review['account_id'],
                'platform':platform,'published_post_id':published_post_id,'published_at':published_at,
                'published_text_hash':published_text_hash,'url':url,'provenance':'user-reported linkage; no publishing action or remote verification'})
    def engagement(self,publication_id,observed_at,metrics,provenance):
        require(isinstance(metrics,dict) and metrics and all(isinstance(k,str) and type(v) in (int,float) and v>=0 and v<float('inf') for k,v in metrics.items()),'Finite nonnegative metrics required')
        require(isinstance(provenance,str) and provenance.strip(),'Metric snapshot provenance required')
        with self.locked():
            publication=self.get('publications',publication_id)
            require(timestamp(observed_at)>=timestamp(publication['published_at']),'Metrics predate publication')
            return self.append('engagement',{'id':'engagement-'+uuid.uuid4().hex,'recorded_at':now(),
                'publication_id':publication_id,'draft_id':publication['draft_id'],'account_id':publication['account_id'],
                'observed_at':observed_at,'metrics':metrics,'provenance':provenance})
    def summary(self):
        reviews=self.rows('reviews');categories={}
        for row in reviews:
            for category in row['categories']:categories[category]=categories.get(category,0)+1
        return {'human_reviews':len(reviews),'categories':categories,'publications':len(self.rows('publications')),
                'engagement_snapshots':len(self.rows('engagement')),'automatic_training':False,
                'writer_opinion_optimization':False,'human_edit_distance_mean':sum(r['human_edit_distance'] for r in reviews)/len(reviews) if reviews else None}
