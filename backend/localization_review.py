"""Local review API for source-grounded candidates; separate from legacy ML reviews."""
import json
from pathlib import Path
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from live.localization_feedback import FeedbackStore, ROOT

router=APIRouter(prefix='/api/localization-review')
STORE=FeedbackStore()
ALLOWED=(ROOT/'live/store/distillation',ROOT/'runs/editorial_completion_v2',ROOT/'runs/domain_generalization_v1',
         ROOT/'runs/content_acceptance_followup_v1/follow_up_results',ROOT/'runs/content_workbench_v1')


def protect(call):
    try:return call()
    except (ValueError,OSError) as e:raise HTTPException(422,str(e)) from e

class Register(BaseModel):attempt_ref:str
@router.post('/register')
def register(body:Register):
    def work():
        p=Path(body.attempt_ref).resolve()
        if p.suffix!='.json' or not any(p.is_relative_to(r.resolve()) for r in ALLOWED):raise ValueError('Attempt outside review roots')
        d=json.loads(p.read_text())
        if not str(d.get('pipeline_version','')).startswith(('localization_','editorial_')):raise ValueError('Not a localization attempt')
        record=STORE.register(d,p)
        return {k:record[k] for k in ('id','draft_version','account_id','target_language')}
    return protect(work)

@router.get('/candidates')
def candidates():
    # Pipeline/QA identity withheld on the reading surface until a human submits.
    return [{'id':r['id'],'account_id':r['account_id'],'target_language':r['target_language'],
             'text':r['original_draft'],'draft_version':r['draft_version'],
             'source':{k:r['source'].get(k) for k in ('source_hash','original_text','author_name','url','published_at','source_language')},
             'human_review':'pending' if not any(x['candidate_id']==r['id'] for x in STORE.rows('reviews')) else 'submitted'}
            for r in STORE.rows('candidates')]

class HumanReview(BaseModel):
    candidate_id:str;expected_version:str;edited_text:str;decision:str;reviewer:str=Field(min_length=1)
    reason:str='';categories:list[str]=[];risk_dispositions:list[dict]=[]
@router.post('/reviews')
def review(body:HumanReview):
    def work():
        saved=STORE.review(**body.model_dump())
        candidate=STORE.get('candidates',body.candidate_id)
        return {**saved,'machine_review_after_submission':{k:candidate[k] for k in ('machine_status','qa','editorial_judgment','pipeline_version')}}
    return protect(work)
@router.get('/summary')
def summary():return STORE.summary()
class Publication(BaseModel):
    review_id:str;platform:str;published_post_id:str;published_at:str;published_text_hash:str;url:str|None=None
@router.post('/publications')
def publication(body:Publication):return protect(lambda:STORE.publication(**body.model_dump()))
class Engagement(BaseModel):
    publication_id:str;observed_at:str;metrics:dict;provenance:str
@router.post('/engagement')
def engagement(body:Engagement):return protect(lambda:STORE.engagement(**body.model_dump()))
