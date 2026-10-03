"""Historical content review desk; new generation uses the account source desk.

Historical attempts and human edits remain readable. The account source desk and
daily monitor share the current content stages. No endpoint publishes automatically.
"""
from pathlib import Path
import json
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from live.distillation import accounts_from_file
from live.distillation_source import digest
from live.source_hygiene import annotate,postcheck
from live.localization_feedback import FeedbackStore

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'runs/content_workbench_v1'
STORE=FeedbackStore()
router=APIRouter(prefix='/api/content-workbench')
ATTEMPT_DIRS=[ROOT/'runs/domain_generalization_v1/finance-regressions/candidate',
 ROOT/'runs/domain_generalization_v1/heldout-before/candidate',
 ROOT/'runs/content_acceptance_followup_v1/follow_up_results/candidate',WORK/'generated',WORK/'morris-evaluation/candidate']


def attempts():
    paths=[p for base in ATTEMPT_DIRS for p in base.glob('*/metadata.json')]
    paths+=list((WORK/'generated').glob('*/artifacts/attempts/*.json'))
    paths+=list((ROOT/'live/store/distillation/attempts').glob('*.json'))
    rows={}
    for p in paths:
        try:
            row=json.loads(p.read_text())
            if not row.get('run_id') or not row.get('source'):continue
            row['metadata_ref']=str(p);row['case']=p.parent.name if p.name=='metadata.json' else row['source']['id']
            rows[row['run_id']]=row
        except (OSError,ValueError):continue
    return sorted(rows.values(),key=lambda r:r.get('created_at',''),reverse=True)


def get_attempt(key):
    row=next((r for r in attempts() if r['run_id']==key),None)
    if row is None:raise HTTPException(404,'Attempt not found')
    return row


def source_library():
    p=WORK/'morris/sources.json'
    return json.loads(p.read_text())['sources'] if p.exists() else []


def risks(row,text=None):
    source=row['source'];draft=text if text is not None else (row.get('localization') or {}).get('text',row.get('text',''))
    return postcheck(source,draft,(row.get('editorial_judgment') or {}).get('guidance',''),row.get('hygiene_decisions',[]))


def short(row):
    source=row['source'];draft=(row.get('localization') or {}).get('text') or row.get('text','')
    findings=risks(row)['findings'] if draft else []
    candidate_id='candidate-'+digest([row['run_id'],draft])[:24]
    reviews=[r for r in STORE.rows('reviews') if r.get('candidate_id')==candidate_id]
    reviews.sort(key=lambda r:r['created_at'],reverse=True)
    return {'id':row['run_id'],'case':row['case'],'source_title':source.get('title') or source['original_text'][:96],
      'author':source.get('author_name'),'source_language':source.get('source_language'),'target_language':row.get('target_language'),
      'account_id':row.get('account_id'),'machine_status':row['draft_status'],'has_draft':bool(draft),
      'risk_count':sum(f['level']=='review' for f in findings),'human_status':reviews[0]['decision'] if reviews else 'pending',
      'created_at':row.get('created_at'),'published_at':source.get('published_at'),'why':row.get('why'),
      'pipeline_version':row.get('pipeline_version'),'follow_up': 'follow_up_results' in row['metadata_ref']}


@router.get('/overview')
def overview():
    rows=attempts();sources=source_library();reviews=STORE.rows('reviews')
    latest={}
    for row in rows:latest.setdefault(row['case'],row)
    items=[short(row) for row in latest.values()]
    follow_up_path=ROOT/'runs/content_acceptance_followup_v1/follow_up_results/summary.json'
    follow_up=json.loads(follow_up_path.read_text()) if follow_up_path.exists() else {}
    completed=len(follow_up.get('cases',[]))
    return {'accounts':accounts_from_file(),'attempts':items,'history':[short(row) for row in rows],
      'history_count':len(rows),'source_count':len(sources),
      'draft_count':sum(r['has_draft'] for r in items),'machine_ready_count':sum(r['machine_status']=='draft_ready' for r in items),
      'human_review_count':len(reviews),'pending_review_count':sum(r['has_draft'] and r['human_status']=='pending' for r in items),
      'publishing_enabled':False,'source_coverage':'Morris: 60 ranked search results, 58 matching-author records; not exhaustive history',
      'follow_up_completed':completed,'follow_up_planned':12,
      'follow_up_state':'completed' if completed==12 else 'collecting' if follow_up else 'waiting_for_relay_balance'}


@router.get('/attempts/{key}')
def detail(key:str):
    row=get_attempt(key);source=row['source'];draft=(row.get('localization') or {}).get('text') or row.get('text','')
    cid='candidate-'+digest([row['run_id'],draft])[:24]
    reviews=sorted([r for r in STORE.rows('reviews') if r['candidate_id']==cid],key=lambda r:r['created_at'],reverse=True)
    return {**short(row),'source':source,'selected_passages':(row.get('selection') or {}).get('passages',[]),
      'excluded_ranges':(row.get('selection') or {}).get('excluded_ranges',[]),'draft':draft,'draft_version':digest(draft),
      'editorial_guidance':row.get('editorial_judgment'),'hygiene_decisions':row.get('hygiene_decisions',[]),
      'annotations':(source.get('source_hygiene') or annotate(source))['annotations'],
      'hygiene':risks(row),'machine_qa':row.get('qa'),'machine_qa_status':row.get('qa_status'),
      'human_reviews':reviews,'metadata_ref':str(Path(row['metadata_ref']).relative_to(ROOT)),
      'history':[short(r) for r in attempts() if r['case']==row['case']]}


@router.get('/sources')
def sources():
    return [{'id':s['id'],'author':s['author_name'],'published_at':s.get('published_at'),'text':s['original_text'],
       'language':s['source_language'],'complete':s['content_complete'],'media_dependencies':s['media_dependencies'],
       'annotation_count':len((s.get('source_hygiene') or annotate(s))['annotations'])} for s in source_library()]


@router.get('/sources/{key}')
def source_detail(key:str):
    row=next((s for s in source_library() if s['id']==key),None)
    if row is None:raise HTTPException(404,'Source not found')
    return row


class Preview(BaseModel):text:str
@router.post('/attempts/{key}/preview')
def preview(key:str,body:Preview):return risks(get_attempt(key),body.text)


class Review(BaseModel):
    expected_version:str;edited_text:str;decision:str;reviewer:str
    reason:str='';categories:list[str]=[];risk_dispositions:list[dict]=[]
@router.post('/attempts/{key}/review')
def review(key:str,body:Review):
    row=get_attempt(key)
    try:
        record=STORE.register(row,row['metadata_ref'])
        return STORE.review(record['id'],**body.model_dump())
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc)) from exc


@router.post('/sources/{key}/generate')
def generate(key:str):
    raise HTTPException(409, detail={
        'code': 'legacy_generation_disabled',
        'message': 'Generate from the account source inbox, using the current shared pipeline.',
        'dashboard': '/account-intelligence'})


app=FastAPI(title='Content Review Desk')
app.include_router(router)
from backend.account_intelligence import router as intelligence_router
app.include_router(intelligence_router)
@app.middleware('http')
async def local_only(request:Request,call_next):
    host=request.headers.get('host','')
    if host.split(':')[0] not in ('127.0.0.1','localhost','testserver'):return JSONResponse({'detail':'Local workspace only'},status_code=403)
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD') and origin not in (None,'http://'+host):return JSONResponse({'detail':'Origin rejected'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return response
@app.get('/content-dashboard')
def page():return FileResponse(ROOT/'frontend/content-dashboard.html')
@app.get('/')
@app.get('/account-intelligence')
def intelligence_page():return FileResponse(ROOT/'frontend/account-intelligence.html')
@app.get('/health')
def health():return {'ok':True,'publishing':False}
app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='assets')
