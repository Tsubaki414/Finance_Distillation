"""Content assets view model. Step 8 of the content delivery plan.

Everything steps 2 to 7 produced, assembled for the workbench. Read-only: it reads the artifact
files and reports what they say, including when they say a piece is blocked.

Nothing here is allowed to improve on the artifacts. A draft's status, a package's platform
measurement, an evergreen item's review state and a cross-language alignment count are copied
across as written, so the surface cannot look healthier than the pipeline is.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def _load(rel):
    d = ROOT / rel
    out = []
    if not d.exists():
        return out
    for p in sorted(d.glob('*.json')):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def _blocking(rec, *keys):
    out = []
    for k in keys:
        block = rec.get(k) or {}
        for f in block.get('findings', []):
            if f.get('severity') == 'blocking':
                out.append({'where': k, 'code': f.get('code'),
                            'detail': str(f.get('detail'))[:200]})
    return out


def drafts():
    """Both pipelines. The surface used to read `content/drafts` only, so the daily output —
    the whole point of the live loop — was invisible in the product."""
    rows = []
    for d in _load('content/drafts') + _load('live/store/drafts'):
        if not d.get('sentence_to_source_ledger'):
            continue
        live = bool(d.get('account_id'))
        m = (d.get('qa') or {}).get('metrics', {})
        fm = (d.get('form') or {}).get('metrics', {})
        rows.append({
            'id': d['id'], 'persona_id': d.get('persona_id'),
            'origin': 'live' if live else 'curated',
            'account_id': d.get('account_id'),
            'lang': d.get('lang') or 'zh',
            'entity': d.get('entity'),
            'packet_id': d.get('packet_id') or d.get('source_id'),
            'primary_url': d.get('primary_url'),
            'source_rank': d.get('source_rank'),
            'language_donor': d.get('language_donor'),
            'style_status': d.get('style_status'),
            'figure_density': (d.get('tell_check') or {}).get('figure_density'),
            'persona_name': d.get('persona_name') or d.get('account_name'),
            'title': d.get('title'), 'created_at': d.get('created_at'),
            'run_status': d.get('run_status'), 'qa_status': d.get('qa_status'),
            'form_status': d.get('form_status'),
            # a live draft records the daily loop's own queue decision under `status`
            'content_status': d.get('content_status') or {
                'ready_for_queue': 'ready_for_pipeline'}.get(d.get('status'), 'blocked'),
            'must_include_coverage': m.get('must_include_coverage'),
            'slots': d.get('slot_placement', {}),
            'sentences': fm.get('sentences'),
            'interpretation_ratio': fm.get('interpretation_ratio'),
            'roles': d.get('roles'), 'profile_channel': d.get('profile_channel'),
            'attempts': len(d.get('attempts') or []),
            'gate_version': (d.get('qa') or {}).get('gate_version'),
            'form_version': (d.get('form') or {}).get('check_version'),
            'blocking': _blocking(d, 'qa', 'form', 'leak_check', 'tell_check'),
            'ledger': [{'sentence_id': r['sentence_id'], 'text': r['text'], 'kind': r.get('kind'),
                        'fact_ids': r.get('fact_ids'),
                        'proposed_thresholds': r.get('proposed_thresholds') or [],
                        'primary_url': r.get('primary_url')}
                       for r in d['sentence_to_source_ledger']],
        })
    queue = ROOT / 'live/store/content_queue.json'
    if queue.is_file():
        for d in json.loads(queue.read_text()).get('opportunities', []):
            if d.get('pipeline_mode') != 'localization_v1':
                continue
            attempt = {}
            path = Path(d.get('attempt_ref') or '')
            if path.is_absolute() and path.resolve().is_relative_to(ROOT.resolve()) and path.is_file():
                attempt = json.loads(path.read_text())
            from live.distillation import comparison_rows
            comparison = comparison_rows(attempt)
            rows.append({
                'id': d.get('draft_id') or d['opportunity_id'], 'origin': 'localization_v1',
                'persona_id': d.get('persona'), 'account_id': d.get('account_id'),
                'lang': d.get('target_language'), 'source_language': d.get('source_language'),
                'title': d.get('topic'), 'text': d.get('text'), 'created_at': d.get('created_at'),
                'why': d.get('why'),
                'content_status': d.get('draft_status'), 'qa_status': d.get('qa_status'),
                'review_status': d.get('review_status'), 'source_ref': d.get('source_ref'),
                'attempt_ref': d.get('attempt_ref'), 'blocking': d.get('qa_findings', []),
                'ledger': [], 'review_kind': 'source_translation_localization',
                'comparison': comparison, 'persona_name': d.get('account_id') or 'Unrouted',
                'provenance': attempt.get('source'), 'edits': (attempt.get('localization') or {}).get('edits', []),
                'editorial_judgment': attempt.get('editorial_judgment'),
                'editor_notes': (attempt.get('localization') or {}).get('editor_notes'),
            })
    return sorted(rows, key=lambda r: r.get('persona_id') or '')


def packages():
    rows = []
    for p in _load('content/packages'):
        fc = p.get('form_check') or {}
        rows.append({
            'id': p['id'], 'form': p.get('form'), 'form_name': p.get('form_name'),
            'persona_id': p.get('persona_id'), 'draft_id': p.get('draft_id'),
            'origin': p.get('origin', 'curated'), 'account_id': p.get('account_id'),
            'entity': p.get('entity'), 'packet_id': p.get('source_id'),
            'title': p.get('title'),
            'qa_status': p.get('qa_status'), 'form_status': p.get('form_status'),
            'content_status': p.get('content_status'),
            'measured': fc.get('measured'), 'measure': fc.get('measure'),
            'units': fc.get('units'), 'unit_name': fc.get('unit_name'),
            'segments': [{'segment_id': s['segment_id'], 'text': s['text'],
                          'kind': s.get('kind'), 'fact_ids': s.get('fact_ids'),
                          'proposed_thresholds': s.get('proposed_thresholds') or []}
                         for s in (p.get('segments') or [])],
            'conditions': p.get('conditions'),
            'source_pack': p.get('source_pack'),
            'blocking': _blocking(p, 'qa', 'form_check'),
        })
    order = ['x_post', 'x_thread', 'xiaohongshu', 'reddit', 'brief']
    return sorted(rows, key=lambda r: (r['persona_id'] or '',
                                       order.index(r['form']) if r['form'] in order else 9))


def visuals():
    rows = []
    for v in _load('content/visuals'):
        rows.append({
            'id': v['id'], 'persona_id': v.get('persona_id'), 'draft_id': v.get('draft_id'),
            'chart_kind': v.get('chart_kind'),
            'svg_url': f"/api/visual/{v['id']}.svg" if v.get('svg_path') else None,
            'brief': v.get('brief'),
            'numbers_drawn': v.get('numbers_drawn'),
            'every_number_bound_to_a_fact': v.get('every_number_bound_to_a_fact'),
            'rendered_by': v.get('rendered_by'),
        })
    return rows


def evergreen():
    idx = ROOT / 'evergreen/deliverables/index.json'
    if not idx.exists():
        return {'available': False}
    d = json.loads(idx.read_text())
    chapter = ROOT / 'evergreen/deliverables/chapter_01.md'
    explainers = []
    for e in d.get('explainers', []):
        p = ROOT / e['markdown']
        explainers.append({**e, 'markdown_text': p.read_text() if p.exists() else None})
    return {
        'available': True,
        'candidates': d.get('candidates'), 'eligible': d.get('eligible'),
        'held_back': d.get('held_back'), 'held_back_detail': d.get('held_back_detail'),
        'span_resolves_in_file': d.get('span_resolves_in_file'),
        'four_part_and_traceable': d.get('four_part_and_traceable'),
        'counterexample_audit': d.get('counterexample_audit'),
        'review_status': d.get('review_status'),
        'direct_quotes_used': d.get('direct_quotes_used'),
        'policy': d.get('policy'),
        'cards': [{**c, 'svg_url': f"/api/evergreen-card/{c['principle_id']}.svg"}
                  for c in d.get('cards', [])],
        'explainers': explainers,
        'chapter_text': chapter.read_text() if chapter.exists() else None,
        'chapter_entries': d.get('chapter_entries'),
    }


def reactivation():
    rows = []
    for r in _load('content/reactivation'):
        md = ROOT / f"content/reactivation/{r['id']}.md"
        rows.append({
            'id': r['id'], 'persona_id': r.get('persona_id'), 'title': r.get('title'),
            'event_label': r.get('event_label'),
            'qa_status': r.get('qa_status'), 'form_status': r.get('form_status'),
            'principles_status': r.get('principles_status'),
            'content_status': r.get('content_status'),
            'parent_draft_id': r.get('parent_draft_id'),
            'retrieval': r.get('retrieval'),
            'principles': r.get('principles'),
            'markdown_text': md.read_text() if md.exists() else None,
            'blocking': _blocking(r, 'qa', 'form_check', 'principle_check'),
        })
    return rows


def crosslang():
    rows = []
    for c in _load('content/crosslang'):
        md = ROOT / f"content/crosslang/{c['id']}.md"
        rows.append({
            'id': c['id'], 'persona_id': c.get('persona_id'), 'title': c.get('title'),
            'zh_draft_id': c.get('zh_draft_id'),
            'source_language': c.get('source_language'), 'target_language': c.get('target_language'),
            'qa_status': c.get('qa_status'), 'crosslang_status': c.get('crosslang_status'),
            'content_status': c.get('content_status'),
            'alignment': c.get('alignment'), 'method': c.get('method'),
            'sentences': [{'sentence_id': r['sentence_id'], 'text': r['text'],
                           'kind_en': r.get('kind_en')}
                          for r in (c.get('sentence_to_source_ledger') or [])],
            'markdown_text': md.read_text() if md.exists() else None,
            'blocking': _blocking(c, 'qa', 'crosslang_check'),
        })
    return rows


def traceback():
    p = ROOT / 'content/traceback.json'
    if not p.exists():
        return {'available': False}
    d = json.loads(p.read_text())
    return {k: d[k] for k in (
        'run_id', 'checked_at', 'artifact', 'artifact_sha256',
        'artifact_sha256_matches_packet', 'primary_url', 'segments_available', 'sampled',
        'fact_bearing_sampled', 'traced', 'trace_rate_of_fact_bearing',
        'segments_without_a_fact', 'segments_without_a_fact_note', 'uncited_numbers',
        'author_declared_thresholds', 'method') if k in d}


def build():
    d, p = drafts(), packages()
    return {
        'generated_from': 'artifact files on disk; no value is recomputed for display',
        'drafts': d,
        'packages': p,
        'visuals': visuals(),
        'evergreen': evergreen(),
        'reactivation': reactivation(),
        'crosslang': crosslang(),
        'traceback': traceback(),
        'counts': {
            'drafts_ready': sum(1 for x in d if x['content_status'] in ('ready_for_pipeline', 'draft_ready')),
            'drafts_total': len(d),
            'drafts_live': sum(1 for x in d if x['origin'] in ('live', 'localization_v1')),
            'packages_live': sum(1 for x in p if x.get('origin') == 'live'),
            'packages_ready': sum(1 for x in p if x['content_status'] == 'ready_for_pipeline'),
            'packages_total': len(p),
        },
    }
