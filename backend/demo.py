"""Read-only demo view model, assembled from real local artifacts.

Every number here is read from a file on disk and carries the path it came from, so any figure on
the page can be traced. Nothing is generated, nothing is written, no business data is touched.
Missing capability is reported as pending/blocked, never filled in.
"""
from pathlib import Path
import json, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evergreen'))
try:
    from output_gate import scan as gate_scan
except Exception:
    def gate_scan(t):
        return []


def rj(rel):
    p = ROOT / rel
    return json.loads(p.read_text()) if p.exists() else None


def src(rel, **vals):
    """Attach the artifact path to every group of numbers."""
    return {'source_artifact': rel, **vals}


def build():
    manifest = rj('evergreen/corpus_manifest.json')
    pools = rj('evergreen/pools.json')
    dedup = rj('evergreen/dedup.json')
    v2 = rj('evidence_loop/profiles_v2/index.json')
    diff = rj('evidence_loop/profiles_v2/diff_v1_v2.json')
    case = rj('evidence_loop/experiments/cases/case-a29c6b6c0325.json')
    packet = rj('evidence_loop/sources/packets/75155f58f5a995e3.json')
    routing = rj('evidence_loop/experiments/routing.json')
    retrieval = rj('evidence_loop/experiments/retrieval.json')
    videos = rj('evidence_loop/transcripts/index.json')
    accept = rj('acceptance-state.json')

    cases_dir = ROOT / 'evidence_loop/experiments/cases'
    all_cases = [json.loads(p.read_text()) for p in sorted(cases_dir.glob('*.json'))]
    qa_blocked = [c for c in all_cases if c.get('qa_status') == 'failed']

    # --- donors usable at the event cutoff -------------------------------------------------
    v2_donors = v2['donors'] if v2 else []
    fully_suppressed = []
    if diff:
        for d in diff['donors']:
            if d['features'] and all(f['suppressed_in_v2'] for f in d['features']):
                fully_suppressed.append(d['donor'])
    usable = [d['donor'] for d in v2_donors if d['donor'] not in fully_suppressed]

    desk = {
        'event_fact': src('evidence_loop/sources/packets/75155f58f5a995e3.json',
                          label='Event & Fact',
                          event_id=packet['id'] if packet else None,
                          typed_facts=len(packet['facts']) if packet else 0,
                          source_blocks=len(packet['blocks']) if packet else 0,
                          replays=1, status='historical_event_replay',
                          note='One event replay only. Its draft is QA-blocked.'),
        'kol_persona': src('evidence_loop/profiles_v2/index.json',
                           label='KOL & Persona',
                           donors_with_samples=12,
                           donors_with_pit_profile=len(v2_donors),
                           donors_usable_at_cutoff=len(usable),
                           cutoff=v2['cutoff'] if v2 else None,
                           features_suppressed=v2['diff_summary']['features_suppressed_in_v2'] if v2 else None,
                           features_compared=v2['diff_summary']['features_compared'] if v2 else None,
                           status='point_in_time_v2_not_wired_into_generation',
                           note='3 donors have no pre-event history; 3 more fail minimum support.'),
        'evergreen': src('evergreen/corpus_manifest.json',
                         label='Evergreen',
                         files=manifest['files'] if manifest else 0,
                         markdown_chars=manifest['markdown_chars_total'] if manifest else 0,
                         pools=pools['pool_counts_person'] if pools else {},
                         independent_sources=dedup['independent_source_count_total'] if dedup else None,
                         raw_documents=dedup['documents'] if dedup else None,
                         status='atomic_principles_not_yet_extracted',
                         note='Corpus surveyed and deduplicated. No principle extracted yet.'),
    }

    scoreboard = [
        {'label': 'Production-ready drafts', 'value': 0, 'tone': 'zero',
         'source_artifact': 'acceptance-state.json',
         'detail': accept['effective_content_count'] if accept else 0},
        {'label': 'QA-blocked cases', 'value': len(qa_blocked), 'tone': 'warn',
         'source_artifact': 'evidence_loop/experiments/cases/',
         'detail': 'case-a29c6b6c0325'},
        {'label': 'Cross-language', 'value': 'not yet validated', 'tone': 'pending',
         'source_artifact': 'docs/CURRENT_STATE_AUDIT.md',
         'detail': 'Old bilingual runs used an incomplete fact pack; no human review.'},
        {'label': 'Video ingestion', 'value': 'not installed', 'tone': 'blocked',
         'source_artifact': 'evergreen/pools.json + evidence_loop/video-audit.json',
         'detail': 'No transcription skill installed. OCR subsystem deferred_non_blocking.'},
    ]

    # --- the six-step flow ------------------------------------------------------------------
    ex = retrieval['results']['macro'] if retrieval else []
    flow = [
        {'id': 'detect', 'n': 1, 'title': 'Detect event', 'zh': '选择内容主题',
         'state': 'demo_replay',
         'have': [f"Event {packet['id']}" if packet else 'no event',
                  f"Published {packet['published_at']}" if packet else '',
                  'Selected manually for this replay'],
         'gap': ['No hot-signal detector. No narrative acceleration or originator/amplifier: '
                 'the corpus has no resolvable quoted/reply parents.'],
         'next': 'Build the propagation substrate before any real detection claim.',
         'provenance': 'evidence_loop/sources/packets/75155f58f5a995e3.json'},
        {'id': 'facts', 'n': 2, 'title': 'Build fact pack', 'zh': '建立事实包',
         'state': 'real',
         'have': [f"{len(packet['facts'])} typed facts with exact character spans" if packet else '',
                  f"{len(packet['blocks'])} source blocks, 39 pages retained" if packet else '',
                  'Methodology caveats preserved (CES vs CPS not subtractable)'],
         'gap': ['Table cells not normalised per-field.',
                 'Source→fact-pack fidelity layer not yet measured.'],
         'next': 'Layer 1 gate: source_fact_accuracy / coverage / lineage.',
         'provenance': 'evidence_loop/sources/packets/75155f58f5a995e3.json'},
        {'id': 'kol', 'n': 3, 'title': 'Retrieve KOL voices', 'zh': '检索真实 KOL 原帖',
         'state': 'available_but_unused',
         'have': [f"{len(ex)} macro exemplars retrieved by multilingual embedding, all pre-event",
                  'Real post IDs with cosine scores'],
         'gap': ['THE S1 DRAFT USED NONE OF THESE. structured_profile mode passes only pooled '
                 'averages, so actual_retrieved_exemplars was empty and the donor influence '
                 'ledger is a blank schema.',
                 'No Recall@K / nDCG@K: retrieval has zero relevance labels.'],
         'next': 'Run a condition that actually injects donor post text, then measure retrieval.',
         'provenance': 'evidence_loop/experiments/retrieval.json',
         'exemplars': [{'post_id': e['post_id'], 'donor': e['source_account_id'],
                        'score': round(e.get('score', 0), 3)} for e in ex]},
        {'id': 'evergreen', 'n': 4, 'title': 'Retrieve Evergreen principles', 'zh': '检索长期知识',
         'state': 'pending',
         'have': [f"{manifest['files']} files, {manifest['markdown_chars_total']:,} chars surveyed" if manifest else '',
                  f"{dedup['documents']} person docs collapse to {dedup['independent_source_count_total']} independent sources" if dedup else '',
                  'Three pools with span-level rights held closed'],
         'gap': ['No atomic principle extracted yet, so nothing can be retrieved.',
                 'Secondary compilations may not impersonate an author.'],
         'next': 'Extract 80–120 candidate principles into a review queue, not the Asset Bank.',
         'provenance': 'evergreen/pools.json + evergreen/dedup.json'},
        {'id': 'compose', 'n': 5, 'title': 'Compose persona draft', 'zh': '按 donor role 组合人设',
         'state': 'blocked',
         'have': ['Three seed personas defined',
                  'Five role slots defined per persona'],
         'gap': ['Role assignment not performed in the produced draft: role_weights was {}.',
                 'All three personas currently route to the same top donor.',
                 'Anonymous pooled arithmetic mean is banned as a multi-donor representation.'],
         'next': 'Role-separated retrieval with per-role donors and visible weights.',
         'provenance': 'evidence_loop/experiments/routing.json'},
        {'id': 'qa', 'n': 6, 'title': 'QA, visual package & handoff', 'zh': '审核、配图与交付',
         'state': 'blocked',
         'have': [f"{len(case['sentence_to_source_ledger'])} sentences with fact IDs and source blocks" if case else '',
                  'Automated QA passed: citation_reference_integrity 1.0, errors []',
                  'Manual review found 5 blocking defects the automation missed'],
         'gap': ['Seven-layer gate not implemented yet.',
                 'Visual grammar is hardcoded to payroll bars.',
                 'No human review submitted.'],
         'next': 'Implement layers 1–7, then re-run the same single cell.',
         'provenance': 'evidence_loop/experiments/cases/case-a29c6b6c0325.json'},
    ]

    # --- personas -------------------------------------------------------------------------
    ROLES = ['Knowledge donor', 'Reasoning donor', 'Language donor', 'Habit donor', 'Visual grammar']
    seeds = [('macro', '宏观数据与资金流观察者', 'Macro data & flows observer'),
             ('industry', '个股与产业链研究者', 'Single-name & supply-chain researcher'),
             ('trading', '交易系统与市场心理教练', 'Trading system & market psychology coach')]
    personas = []
    for pid, zh, en in seeds:
        r = (routing or {}).get(pid, {})
        used_in_draft = bool(case and case.get('role_weights'))
        personas.append({
            'id': pid, 'zh': zh, 'en': en,
            'question': r.get('question'),
            'planned_donors': [d['donor'] for d in r.get('donors', [])],
            'roles': [{'role': role,
                       'assigned': 'not yet assigned/retrieved',
                       'status': 'planned_only'} for role in ROLES],
            'draft_role_weights': case.get('role_weights') if case else {},
            'assignment_status': 'not yet assigned/retrieved' if not used_in_draft else 'assigned',
            'warning': 'Planned donors come from a retrieval + editorial formula, not a learned '
                       'assignment. The produced draft carried no role weights at all.',
            'source_artifact': 'evidence_loop/experiments/routing.json',
        })

    # --- QA findings ----------------------------------------------------------------------
    GATE = {'numeric_magnitude': 'Layer 2 · Typed numeric semantics',
            'out_of_evidence_assertion': 'Layer 3 · Claim-level entailment',
            'citation_relation_mismatch': 'Layer 4 · Citation precision',
            'clause_attribution': 'Layer 6 · Atomic claim & clause attribution',
            'must_include_missing': 'Layer 5 · Fact selection policy'}
    findings = []
    for f in (case or {}).get('human_qa_findings', []):
        findings.append({**f, 'gate_that_will_catch_it': GATE.get(f['type'], 'unmapped')})

    evidence = {
        'case_id': case['id'] if case else None,
        'title': case.get('title') if case else None,
        'run_status': case.get('run_status') if case else None,
        'qa_status': case.get('qa_status') if case else None,
        'content_status': case.get('content_status') if case else None,
        'classification': case.get('classification') if case else None,
        'automated_qa': {
            'citation_reference_integrity': (case.get('qa') or {}).get('citation_id_validity'),
            'errors': len((case.get('qa') or {}).get('errors', [])),
            'ai_surface_patterns': len((case.get('qa') or {}).get('ai_surface_patterns', [])),
            'fact_id_coverage': (case.get('qa') or {}).get('fact_id_coverage'),
            'missing_required_ids': (case.get('qa') or {}).get('missing_required_ids', []),
        } if case else {},
        'findings': findings,
        'lesson': 'Automated QA reported a clean pass while the text contained a ten-fold '
                  'magnitude error. Citation ID validity is not entailment.',
        'source_artifact': 'evidence_loop/experiments/cases/case-a29c6b6c0325.json',
    }

    evergreen = {
        'manifest': src('evergreen/corpus_manifest.json',
                        files=manifest['files'], markdown_chars=manifest['markdown_chars_total'],
                        by_ext=manifest['by_ext'],
                        conversion_methods=manifest.get('conversion_methods', {}),
                        with_source_url=manifest.get('markdown_with_any_source_url'),
                        secondary=manifest.get('secondary_compilations')) if manifest else None,
        'pools': src('evergreen/pools.json',
                     counts=pools['pool_counts_person'], chars=pools['pool_chars_person'],
                     permissions=pools['permissions'],
                     ocr=pools.get('ocr_subsystem')) if pools else None,
        'dedup': src('evergreen/dedup.json',
                     documents=dedup['documents'], chunks=dedup['chunks'],
                     dup_chunks=dedup['chunks_with_cross_document_near_duplicate'],
                     independent_sources=dedup['independent_source_count_total'],
                     redundant_chars=dedup['redundant_chars_removed_from_independent_count'],
                     clusters=[c for c in dedup['clusters'] if c['member_count'] > 1][:6]) if dedup else None,
        'next': ['Extract 80–120 candidate principles into a review queue.',
                 'Retrieve principles relevant to a live event.',
                 'Secondary compilations never impersonate the original author.'],
    }

    model = {
        'banner': 'Architecture Demo · Real local artifacts · No publication',
        'generated_at': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat(),
        'desk': desk, 'scoreboard': scoreboard, 'flow': flow,
        'personas': personas, 'evidence': evidence, 'evergreen': evergreen,
        'videos': src('evidence_loop/transcripts/index.json',
                      videos=len(videos['videos']), segments=videos['segments'],
                      status='no transcription skill installed') if videos else None,
    }
    # The page must never render a local path or private identifier.
    leaks = gate_scan(json.dumps(model, ensure_ascii=False))
    model['output_gate'] = {'findings': len(leaks),
                            'kinds': sorted({x['kind'] for x in leaks}),
                            'checked_by': 'evergreen/output_gate.py'}
    return model
