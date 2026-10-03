"""Local owned-account workbench API. Explicit writes only, never publishing."""
import hashlib
import json
from pathlib import Path
import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from live.account_intelligence import Store, accounts, now, digest, copy_risks, time as source_time
from live.account_intelligence_pipeline import Pipeline
from live.account_sources import SourcePipeline, inbox, universes

router = APIRouter(prefix='/api/account-intelligence')
STORE = Store()
RUN_LOCK = threading.Lock()
REVIEW_ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENTAL_QA = {'F01': 'supplemental_qa_length_followup', 'F02': 'supplemental_qa'}
VALIDATOR_FILES = frozenset({'live/numeric_fidelity.py', 'live/fidelity.py',
    'live/domain_policy.py', 'tests/test_fidelity_validator_v2.py'})
BLIND_REVIEW_DIR = 'runs/account_sources_v1/completion_v2/blind_review'
BLIND_INPUTS = frozenset({'data/raw_posts.jsonl',
    'runs/account_sources_v1/assisted_followups/F02/result.json',
    'runs/account_sources_v1/assisted_followups/F03/result.json'})
CURRENT_BLIND_DIR = 'runs/content_batch_v2/review'
CURRENT_BLIND_ACCOUNTS = ('en_morris_archive', 'zh_macro', 'zh_industry')


def prepared_account_blind_review(account_id):
    """Bind an existing 5+5 packet; return only participant-safe metadata.

    Public references have captured provenance, not certified human-only authorship.
    This read does not register a study, write ratings, or clear machine holds.
    """
    if account_id not in CURRENT_BLIND_ACCOUNTS:
        return None
    try:
        from scripts.build_content_batch_packet import BLIND_SEED, code_block, reference_text
        packet = json.loads((REVIEW_ROOT / CURRENT_BLIND_DIR / 'packet.json').read_text())
        inputs = packet['input_sha256']
        if not inputs:
            return None
        for relative, expected in inputs.items():
            # Outcome summaries append later failed/repaired attempts. A locked
            # participant cohort binds the immutable selected adaptations below,
            # not a mutable batch summary's unrelated follow-ups.
            if relative.startswith('runs/content_batch_v2/outcomes/'):
                continue
            path = (REVIEW_ROOT / relative).resolve()
            path.relative_to(REVIEW_ROOT.resolve())
            if not relative.startswith(('runs/content_batch_v2/', 'runs/account_sources_v1/adaptations/')):
                return None
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return None
        account_packet = next(a for a in packet['accounts'] if a['account_id'] == account_id)
        drafts = account_packet['drafts']
        if len(drafts) != 5 or len({d['run_id'] for d in drafts}) != 5:
            return None
        for draft in drafts:
            source = draft['source']
            run = STORE.get('runs', draft['run_id'])
            adaptation_path = str(Path(draft['adaptation_artifact']).resolve().relative_to(REVIEW_ROOT.resolve()))
            if adaptation_path not in inputs or draft['adaptation_sha256'] != inputs[adaptation_path]:
                return None
            adaptation = json.loads((REVIEW_ROOT / adaptation_path).read_text())
            source_rows = [STORE.get('sources', sid) for sid in run['event']['source_ids']]
            if (draft['generation_origin'] != 'automated_pipeline'
                    or adaptation.get('generation_origin') != 'automated_pipeline'
                    or adaptation != run.get('source_adaptation')
                    or run['account_id'] != account_id
                    or run.get('batch_id') != 'kol-single-post-batch-v2'
                    or digest(draft['final_draft']) != draft['draft_sha256']
                    or adaptation['final_draft'] != draft['final_draft']
                    or not any(c['text'] == draft['final_draft'] for c in run['candidates'])
                    or digest(source['original_text']) != source['source_hash']
                    or not any(s['original_text'] == source['original_text'] and s.get('url') == source.get('url')
                               for s in source_rows)):
                return None
        directory = REVIEW_ROOT / CURRENT_BLIND_DIR / 'blind' / account_id
        participant = json.loads((directory / 'participant.json').read_text())
        key = json.loads((directory / 'PRIVATE_ANSWER_KEY.json').read_text())
        references_path = f'runs/content_batch_v2/source_selection/{account_id}/references.json'
        if references_path not in inputs:
            return None
        references = json.loads((REVIEW_ROOT / references_path).read_text())['references']
        if (set(participant) != {'schema_version', 'language', 'instructions', 'items'}
                or participant['schema_version'] != 'editorial-blind-participant-v1'
                or participant['instructions'] != 'Read each post as a separate piece. Judge natural expression, useful reasoning and obvious generated style. Leave uncertain answers blank; do not guess a specific person\'s identity.'
                or participant['language'] != account_packet['language']
                or key.get('account_id') != account_id
                or key.get('study_status') != 'prepared_not_administered'
                or key.get('human_results_count') != 0
                or len(participant['items']) != 10 or len(key['items']) != 10):
            return None
        by_id = {i['opaque_id']: i for i in key['items']}
        if len(by_id) != 10 or {i['opaque_id'] for i in participant['items']} != set(by_id):
            return None
        seen_runs, seen_references = set(), set()
        lines = ['# Reading review', '', participant['instructions'], '']
        for item in participant['items']:
            if (set(item) != {'opaque_id', 'text', 'response'}
                    or set(item['response']) != {'native_expression','editorial_quality','obvious_generated_style','notes'}
                    or any(v is not None for v in item['response'].values())):
                return None
            private = by_id[item['opaque_id']]
            if digest(item['text']) != private['body_sha256']:
                return None
            if private['kind'] == 'automatic_draft':
                draft = next(d for d in drafts if d['run_id'] == private['run_id'])
                if item['text'] != draft['final_draft']:
                    return None
                seen_runs.add(draft['run_id'])
                identity = draft['run_id']
            elif private['kind'] == 'public_reference':
                reference = private['reference']
                if reference not in references or item['text'] != reference_text(reference):
                    return None
                seen_references.add(reference['reference_id'])
                identity = reference['reference_id']
            else:
                return None
            expected_id = digest(BLIND_SEED+'|'+account_id+'|'+private['kind']+'|'+identity+'|'+digest(item['text']))[:12]
            if item['opaque_id'] != expected_id:
                return None
            lines += ['## ' + item['opaque_id'], '', code_block(item['text']), '',
                      'Natural expression: ___  Editorial quality: ___  Obvious generated style: ___', 'Notes: ___', '']
        markdown = (directory / 'participant.md').read_bytes()
        if len(seen_runs) != 5 or len(seen_references) != 5 or markdown != '\n'.join(lines).encode():
            return None
        return {'status':'prepared_not_administered','account_id':account_id,
                'item_count':10,'system_candidates':5,'collected_public_posts':5,
                'generation_origin':'automated_pipeline','human_ratings_count':0,
                'binding_verified':True,'registered_in_store':False,
                'participant_sha256':hashlib.sha256(markdown).hexdigest(),
                'participant_url':f'/api/account-intelligence/accounts/{account_id}/blind-review/participant',
                'reference_authorship':'Public authorship verified; human-only composition unknown',
                'reference_quality':'Agent-curated and approximately matched; human quality approval pending',
                'human_work_remaining':['Human curator confirms reference suitability',
                    'Human colleagues independently rate the anonymous items',
                    'Lock human answers before revealing the separate answer key']}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        return None


def prepared_blind_review():
    """Existing packet preparation is not a registered or completed human study."""
    try:
        manifest = json.loads((REVIEW_ROOT / BLIND_REVIEW_DIR / 'MANIFEST.json').read_text())
        inputs = manifest.get('input_files', [])
        participant = (REVIEW_ROOT / BLIND_REVIEW_DIR / 'PARTICIPANT.md').read_bytes()
        if (manifest.get('status') != 'prepared_not_administered'
                or manifest.get('human_ratings_count') != 0
                or manifest.get('participant_file') != 'PARTICIPANT.md'
                or hashlib.sha256(participant).hexdigest() != manifest.get('participant_sha256')
                or len(inputs) != len(BLIND_INPUTS) or {i['path'] for i in inputs} != BLIND_INPUTS
                or not all(hashlib.sha256((REVIEW_ROOT / i['path']).read_bytes()).hexdigest() == i['sha256']
                           for i in inputs)):
            return None
        return {k: manifest.get(k) for k in ('status', 'created_at', 'item_count',
            'system_candidates', 'collected_public_posts', 'participant_sha256',
            'human_ratings_count', 'limitations', 'human_work_remaining')} | {
            'binding_verified': True, 'registered_in_store': False,
            'reference_authorship': 'unknown; collected public posts are not proven human-only ground truth',
            'reference_quality': 'agent-curated, pending human curator',
            'participant_url': '/api/account-intelligence/blind-review/participant'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def supplemental_review(store, run, candidate):
    """Read-only diagnostics for two saved assisted drafts, never acceptance labels.

    A filename, matching fixture name, or matching text alone is insufficient: the
    original adaptation, source snapshot, parent identity and candidate must agree.
    Invalid/stale optional artifacts simply leave the original checks in place.
    """
    fixture = run.get('fixture_id')
    if fixture not in SUPPLEMENTAL_QA or run.get('generation_origin') != 'codex_assisted':
        return None
    try:
        relative = f'runs/account_sources_v1/assisted_followups/{fixture}/result.json'
        raw = (REVIEW_ROOT / relative).read_bytes()
        saved = json.loads(raw)
        adaptation = run.get('source_adaptation', {})
        text = candidate.get('text', '')
        if (not text or saved != adaptation or saved.get('generation_origin') != 'codex_assisted'
                or saved.get('id') != run['id'] + '-adaptation'
                or saved.get('account_id') != run.get('account_id')
                or candidate.get('id') != run['id'] + '-c1'
                or text != saved.get('final_draft')):
            return None
        source = saved['source']
        source_hash = digest(source['original_text'])
        if source_hash != source.get('source_hash'):
            return None
        # Store and adaptation IDs differ after source normalization. Bind the
        # immutable source content and URL, not an assumed equality of those IDs.
        sources = [store.get('sources', key) for key in run['event'].get('source_ids', [])]
        if not any(s.get('source_hash') == source_hash
                   and s.get('original_text') == source['original_text']
                   and all(s.get(k) == source.get(k) for k in ('url', 'author_name', 'source_language'))
                   and (s.get('published_at') == source.get('published_at')
                        or (s.get('published_at') and source.get('published_at')
                            and source_time(s['published_at']) == source_time(source['published_at'])))
                   for s in sources):
            return None
        result = {'binding_verified': True, 'candidate_hash': digest(text),
                  'source_hash': source_hash, 'parent_adaptation_id': saved['id'],
                  'status_effect': 'diagnostic_only', 'original_hold_preserved': True}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None

    semantic_path = str(Path(relative).parent / SUPPLEMENTAL_QA[fixture] / 'result.json')
    try:
        qa_raw = (REVIEW_ROOT / semantic_path).read_bytes()
        qa = json.loads(qa_raw)
        responses = qa.get('model_responses', [])
        if (qa.get('fixture_id') == fixture and qa.get('parent_adaptation_id') == saved['id']
                and qa.get('candidate_hash') == digest(text)
                and qa.get('generation_origin') == 'codex_assisted'
                and qa.get('status') == 'model_reviewed'
                and qa.get('deterministic_hold_preserved') is True
                and isinstance(qa.get('semantic'), dict) and responses
                and all(r.get('finish_reason') == 'stop' and not r.get('refusal') for r in responses)):
            result['semantic'] = {k: qa.get(k) for k in ('semantic', 'scope', 'finished_at',
                'semantic_dimensions_all_pass', 'max_tokens', 'execution_change', 'follow_up_of_call')}
            result['semantic'].update({'artifact': semantic_path,
                'artifact_sha256': hashlib.sha256(qa_raw).hexdigest(),
                'models': [{k: r.get(k) for k in ('model', 'provider', 'response_model', 'finish_reason')}
                           for r in responses]})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass

    try:
        report_path = 'runs/account_sources_v1/completion_v2/validator_recheck.json'
        report = json.loads((REVIEW_ROOT / report_path).read_text())
        hashes = report.get('code_hashes', [])
        code_matches = (len(hashes) == len(VALIDATOR_FILES)
            and {h['path'] for h in hashes} == VALIDATOR_FILES
            and all(hashlib.sha256((REVIEW_ROOT / h['path']).read_bytes()).hexdigest() == h['sha256']
                    for h in hashes))
        cases = [c for c in report.get('cases', []) if c.get('fixture') == fixture]
        if code_matches and len(cases) == 1:
            case = cases[0]
            if (case.get('input_path') == relative
                    and case.get('input_sha256') == hashlib.sha256(raw).hexdigest()
                    and case.get('draft_sha256') == hashlib.sha256(text.encode()).hexdigest()
                    and case.get('machine_acceptance_changed') is False):
                result['validator_recheck'] = {**case, 'artifact': report_path,
                    'checked_at': report.get('checked_at'), 'versions': report.get('versions'),
                    'code_hashes': hashes}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return result if 'semantic' in result or 'validator_recheck' in result else None


def add_supplemental_review(run, candidates):
    for candidate in candidates:
        evidence = supplemental_review(STORE, run, candidate)
        if evidence:
            candidate['supplemental_review'] = evidence


def read_jev_advisory(run, candidate_id=None):
    """Read saved advisory records; a diagnostic failure never hides a draft.

    This is deliberately separate from machine fidelity, review guards, and
    human acceptance. GET handlers must never schedule a provider request.
    """
    from live.jev_advisory import get_advisory
    try:
        return get_advisory(STORE, run, candidate_id=candidate_id)
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'failed', 'advisory_only': True,
            'human_review_required': True, 'binding_verified': False,
            'body_scope': 'original_generated_draft', 'run_id': run['id'],
            'account_id': run['account_id'], 'candidate_id': candidate_id,
            'findings': [], 'checks': [], 'structural_checks': [],
            'feedback': {'status': 'pending_human_review', 'reviews': []},
            'error_codes': ['advisory_read_failed']}


def add_jev_advisory(run, candidates):
    for candidate in candidates:
        candidate['jev_advisory'] = read_jev_advisory(run, candidate_id=candidate['id'])


def invoke(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/overview')
def overview():
    runs = STORE.rows('runs')
    reviews = STORE.rows('reviews')
    families = {}
    for event in STORE.rows('events'):
        latest = STORE.latest_event(event['family'])
        families[event['family']] = latest
    return {'accounts': [{**a, 'state': STORE.snapshot(a['id'])} for a in accounts()],
        'events': list(families.values()), 'research': STORE.rows('research'), 'research_reviews': STORE.rows('research_reviews'),
        'state_proposals': STORE.rows('state_proposals'), 'state_actions': STORE.rows('state_actions'),
        'active_accounts': [a['id'] for a in accounts(active_only=True)], 'universes': universes(),
        'human_quality': STORE.human_quality(), 'blind_review_preparation': prepared_blind_review(),
        'account_blind_review_preparations': {aid: prepared_account_blind_review(aid) for aid in CURRENT_BLIND_ACCOUNTS},
        'runs': [{k: r.get(k) for k in ('id', 'account_id', 'status', 'recorded_at', 'decision', 'follow_up_of',
                                       'pipeline', 'inbox_candidate_id', 'batch_id', 'fixture_id', 'generation_origin', 'generation_protocol')}
            | {'event_id': r['event']['id'], 'event_family': r['event']['family'],
               'draft_count': len(r['candidates']), 'current': STORE.current(r),
               'human_review_count': sum(v['run_id'] == r['id'] for v in reviews)} for r in runs],
        'feedback': STORE.feedback_summary(), 'publishing_enabled': False,
        'publications': STORE.rows('publications'), 'engagement': STORE.rows('engagement')}


@router.get('/monitor-status')
def monitor_status():
    """Read persisted monitor progress without starting work or model calls."""
    from live.account_monitor import monitor_status as persisted_status
    from live.pipeline_health import inventory
    from live.source_context import ContextStore
    status = persisted_status(store_root=STORE.root)
    return {**status, 'pipeline': inventory(STORE, status=status),
            'official_context': {a['id']: ContextStore(STORE.root).status(a['id'])
                                 for a in accounts(active_only=True)}}


@router.get('/events/{key}')
def event_detail(key):
    event = invoke(STORE.get, 'events', key)
    return {**event, 'sources': [STORE.get('sources', sid) for sid in event.get('source_ids', [])]}


@router.get('/runs/{key}')
def run_detail(key):
    run = invoke(STORE.get, 'runs', key)
    add_supplemental_review(run, run['candidates'])
    add_jev_advisory(run, run['candidates'])
    if not run['candidates']:
        run['jev_advisory'] = read_jev_advisory(run)
    for candidate in run['candidates']:
        candidate['text_version'] = digest(candidate['text'])
        candidate['review_guard_risks'] = copy_risks(STORE, run, candidate['text'], as_of=now())
    return {**run, 'current': STORE.current(run), 'reviews': [r for r in STORE.rows('reviews') if r['run_id'] == key],
        'sources': [STORE.get('sources', sid) for sid in run['event'].get('source_ids', [])],
        'human_decisions': [r for r in STORE.rows('decision_feedback') if r['run_id'] == key]}


@router.get('/accounts/{account_id}/review-packet')
def account_review_packet(account_id, batch_id: str | None = None):
    packet = invoke(STORE.review_packet, account_id, batch_id)
    for entry in packet['entries']:
        run = STORE.get('runs', entry['run_id'])
        add_supplemental_review(run, entry['candidates'])
        add_jev_advisory(run, entry['candidates'])
    study = packet['blind_study']
    study['real_reference_count_basis'] = 'Registered human-validated references, not prepared collected public posts'
    study['registered_in_store'] = False
    prepared = prepared_account_blind_review(account_id)
    if prepared:
        study.update({'status': prepared['status'], 'prepared_packet': prepared,
            'missing': prepared['human_work_remaining']})
    return packet


@router.get('/accounts/{account_id}/blind-review/participant')
def account_blind_review_participant(account_id):
    prepared = prepared_account_blind_review(account_id)
    if not prepared:
        raise HTTPException(409, 'Account participant packet is absent or no longer bound to exact saved outputs')
    path = REVIEW_ROOT / CURRENT_BLIND_DIR / 'blind' / account_id / 'participant.md'
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != prepared['participant_sha256']:
        raise HTTPException(409, 'Participant packet changed during read')
    return Response(content, media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{account_id}-blind-participant.md"'})


@router.get('/blind-review/participant')
def blind_review_participant():
    prepared = prepared_blind_review()
    if not prepared:
        raise HTTPException(409, 'Prepared packet is absent or its input/text hashes no longer match')
    content = (REVIEW_ROOT / BLIND_REVIEW_DIR / 'PARTICIPANT.md').read_bytes()
    if hashlib.sha256(content).hexdigest() != prepared['participant_sha256']:
        raise HTTPException(409, 'Prepared packet changed during read')
    return Response(content, media_type='text/markdown',
        headers={'Content-Disposition': 'attachment; filename="blind-review-participant.md"'})


@router.get('/accounts/{account_id}/inbox')
def account_inbox(account_id):
    return invoke(inbox, STORE, account_id)


class SourceGenerate(BaseModel):
    follow_up_of: str | None = None
    current_evidence: list[dict] | None = None


@router.post('/accounts/{account_id}/inbox/{candidate_id}/run')
def generate_source(account_id, candidate_id, body: SourceGenerate):
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Another source evaluation is running')
    try:
        return invoke(SourcePipeline(STORE).run, account_id, candidate_id, body.follow_up_of,
                      current_evidence=body.current_evidence)
    finally:
        RUN_LOCK.release()


class Generate(BaseModel):
    account_id: str
    follow_up_of: str | None = None
    current_state: bool = False


@router.post('/events/{key}/run')
def generate(key, body: Generate):
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Another event evaluation is running')
    try:
        raise HTTPException(409, 'Event-first generation retired. Use an admitted account source candidate.')
    finally:
        RUN_LOCK.release()


class Decision(BaseModel):
    decision: str
    reviewer: str
    reason: str


@router.post('/runs/{key}/decision')
def decision(key, body: Decision):
    return invoke(STORE.decision_feedback, key, **body.model_dump())


class Review(BaseModel):
    expected_version: str
    text: str
    decision: str
    reviewer: str
    reason: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    risk_note: str = ''
    edit_class: str | None = None
    error_types: list[str] = Field(default_factory=list)
    issue_annotations: list[dict] = Field(default_factory=list)


@router.post('/runs/{key}/candidates/{cid}/review')
def review(key, cid, body: Review):
    return invoke(STORE.review, key, cid, **body.model_dump())


class Proposal(BaseModel):
    account_id: str
    kind: str
    topic: str
    text: str
    evidence_refs: list[dict]
    origin: str = 'human proposal'


class ResearchReview(BaseModel):
    treatment: str
    reviewer: str
    reason: str
    supporting_event_id: str | None = None


@router.post('/research/{key}/review')
def research_review(key, body: ResearchReview):
    return invoke(STORE.review_research, key, **body.model_dump())


@router.post('/state/propose')
def propose(body: Proposal):
    return invoke(STORE.propose, **body.model_dump())


class StateAction(BaseModel):
    action: str
    reviewer: str
    reason: str
    supersedes: str | None = None


@router.post('/state/{key}/decision')
def state_decision(key, body: StateAction):
    return invoke(STORE.state_action, key, **body.model_dump())


class Publication(BaseModel):
    review_id: str
    platform: str
    post_id: str
    published_at: str
    text_hash: str
    url: str = ''


@router.post('/publications')
def publication(body: Publication):
    return invoke(STORE.publication, **body.model_dump())


class Engagement(BaseModel):
    publication_id: str
    observed_at: str
    metrics: dict[str, float]
    provenance: str


@router.post('/engagement')
def engagement(body: Engagement):
    return invoke(STORE.engagement, **body.model_dump())


@router.get('/learning-export')
def learning_export():
    return STORE.learning_export()
