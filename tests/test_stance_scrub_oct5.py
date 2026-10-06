"""Oct 5 stance scrub + compose paraphrase / info_dump rewrite hooks."""
import json
from live import compose, qa_levels, stance


# --- A. stance scrub ------------------------------------------------------------------

def test_banned_hits_detects_zh_and_en_families():
    assert '才是关键' in stance.banned_hits('定价权才是关键')
    assert 'valuation-free optimism' in stance.banned_hits(
        "Micron guidance is valuation-free optimism dressed up as a call.")
    assert stance.banned_hits('单月数据不足以确认趋势') == []


def test_scrub_strips_meta_label_and_banned_filler():
    cleaned, meta = stance.scrub_account_view('我的判断：单月数据不足以确认趋势。')
    assert cleaned == '单月数据不足以确认趋势。' and meta['meta_stripped'] and meta['changed']
    cleaned, meta = stance.scrub_account_view(
        '需求超过供给这个方向没问题，但定价权能否撑过新一轮产能扩张才是关键，光看周期长度不够。')
    assert '才是关键' not in cleaned and meta['hits_after'] == [] and meta['changed']
    cleaned, meta = stance.scrub_account_view(
        "Micron's record fiscal 2026 is real, but a CEO calling fiscal 2027 "
        "'even stronger' without supply discipline data is valuation-free optimism "
        "dressed up as guidance.")
    assert 'valuation-free' not in cleaned.casefold()
    assert meta['hits_after'] == []


def test_scrub_reverts_when_gutting_would_empty_sentence():
    # Phrase is the whole call — scrub would leave almost nothing; keep original for retry.
    cleaned, meta = stance.scrub_account_view('才是关键')
    assert cleaned == '才是关键' and meta.get('reverted') is True


def test_stance_cadence_soft_finding():
    found = stance.stance_cadence_findings('This is valuation-free optimism.')
    assert found and found[0]['code'] == 'stance_cadence'
    assert qa_levels.classify(found, frame_found=True)[0]['level'] == 'soft'
    assert stance.stance_cadence_findings('Demand is ahead of supply for now.') == []


def test_apply_stance_scrub_on_supplied_stance():
    dirty = {
        'decision': 'take',
        'account_view': '定价权能否撑过扩产才是关键。',
        'supporting_unit_ids': ['u'], 'rationale': 'x', 'confidence': 0.7,
    }
    out = stance.apply_stance_scrub(dirty)
    assert '才是关键' not in out['account_view']
    assert out['stance_scrub']['changed']
    assert dirty['account_view'].endswith('才是关键。')  # input not mutated


def test_stance_step_mechanical_scrub_clears_without_retry():
    from tests.test_judgment import VIEW
    from live import registry
    unit = {
        'unit_id': 'v', 'kind': 'view', 'statement': 'Supply tight.',
        'source_spans': [{'exact_text': 'Micron revenue rose'}], 'numbers': [],
        'speaker': 'S', 'speaker_type': 'media', 'view': dict(VIEW),
        'freshness_class': 'current', 'published_at': '2026-10-05T00:00:00Z',
    }
    dirty = {
        'decision': 'take',
        'account_view': 'Memory supply looks like valuation-free optimism.',
        'supporting_unit_ids': ['v'], 'rationale': 'Supply.', 'confidence': 0.7,
    }
    calls = {'n': 0}

    def client(stage, messages, max_tokens):
        calls['n'] += 1
        return {'text': json.dumps(dirty), 'finish_reason': 'stop'}

    persona = registry.persona_for_account('en_macro')
    result = stance.stance_step(unit, persona, client, sleep=lambda s: None)
    assert 'valuation-free' not in result['account_view'].casefold()
    assert calls['n'] == 1  # mechanical scrub cleared hits; no repair call
    assert not result.get('stance_scrub_retry')
    assert result['stance_scrub']['changed'] is True


def test_stance_step_retries_when_scrub_reverts():
    """When the whole account_view IS a banned span, scrub reverts and one repair fires
    (v11 cost: for ZH that repair is the small account_view rewrite, not a second full stance)."""
    from tests.test_judgment import VIEW
    from live import registry
    unit = {
        'unit_id': 'v', 'kind': 'view', 'statement': 'Supply tight.',
        'source_spans': [{'exact_text': 'Micron revenue rose'}], 'numbers': [],
        'speaker': 'S', 'speaker_type': 'media', 'view': dict(VIEW),
        'freshness_class': 'current', 'published_at': '2026-10-05T00:00:00Z',
    }
    dirty = {
        'decision': 'take', 'account_view': '才是关键',
        'supporting_unit_ids': ['v'], 'rationale': 'Supply.', 'confidence': 0.7,
    }
    clean = {
        'decision': 'take',
        'account_view': '定价权撑不过新一轮扩产就会破。',
        'supporting_unit_ids': ['v'], 'rationale': 'Supply.', 'confidence': 0.7,
    }
    calls = {'n': 0}

    def client(stage, messages, max_tokens):
        calls['n'] += 1
        payload = json.loads(messages[-1]['content'])
        value = {'account_view': clean['account_view']} if payload.get('problems') else dirty
        return {'text': json.dumps(value), 'finish_reason': 'stop'}

    persona = registry.persona_for_account('zh_industry')
    result = stance.stance_step(unit, persona, client, sleep=lambda s: None)
    assert '才是关键' not in result['account_view']
    assert calls['n'] == 2
    assert result['stance_scrub_retry'] == {'attempted': False, 'routed_to': 'zh_view_rewrite',
                                            'first_hits': ['才是关键']}
    assert result['stance_zh_retry']['kept'] == 'retry'


# --- B. verbatim line1 ----------------------------------------------------------------

def test_verbatim_line1_triggers_on_exact_and_near_copy():
    thesis = '比特币短期内对降息预期的钝感反应，恰恰说明当前价格驱动力不在货币政策预期，而在链上资金流与监管信号。'
    assert compose.line1_near_thesis(thesis + '\n第二段', thesis)
    found = compose.verbatim_line1_findings(thesis + '\n第二段', thesis_lock=thesis)
    assert found and found[0]['code'] == 'verbatim_line1'
    assert qa_levels.classify(found, frame_found=True)[0]['level'] == 'soft'
    paraphrased = '降息预期再也撬不动币价，真正驱动在链上资金和监管。\n第二段'
    assert not compose.verbatim_line1_findings(paraphrased, thesis_lock=thesis)


def test_judgment_retry_shares_budget_with_verbatim(monkeypatch):
    """verbatim_line1 shares the single judgment_repair slot (no extra retry explosion)."""
    from tests.test_compose import SOURCE as CS, UNITS
    from tests.test_judgment import VIEW
    raw = dict(UNITS['units'][2], kind='view',
               view=dict(VIEW, reasoning=[UNITS['units'][2]['source_spans'][0]['exact_text']]))
    thesis = 'Memory supply looks tight without a capacity flood.'
    seen = {'compose': 0, 'notes': []}

    class Fake:
        def __call__(self, stage, messages, max_tokens):
            p = json.loads(messages[-1]['content'])
            if stage == 'extract':
                return {'text': json.dumps({'units': [UNITS['units'][0], UNITS['units'][1], raw]}),
                        'finish_reason': 'stop'}
            if stage == 'stance':
                return {'text': json.dumps({
                    'decision': 'take', 'account_view': thesis,
                    'supporting_unit_ids': [p['unit']['unit_id']], 'rationale': 'Supply.',
                    'confidence': 0.7}), 'finish_reason': 'stop'}
            # compose
            seen['compose'] += 1
            note = p.get('rewrite_note') or ''
            seen['notes'].append(note)
            if ('paraphrase' in note.lower() or 'verbatim' in note.lower() or 'do not copy' in note.lower()) and 'info_dump' not in note:
                body = 'Supply stays tight into next year.\nRevenue was $54.23 billion.'
            else:
                # First draft copies thesis verbatim as line 1.
                body = thesis + '\nRevenue was $54.23 billion.'
            fact_id = next(u['unit_id'] for u in p['units'] if u['kind'] == 'fact')
            return {'text': json.dumps({
                'body': body,
                'claim_ledger': [{'claim': 'Revenue was $54.23 billion', 'unit_id': fact_id, 'span_ref': 0}],
            }), 'finish_reason': 'stop'}

    result = compose.compose_source(CS, 'en_industry', Fake(), exemplars=False)
    assert result.get('judgment_retry', {}).get('attempted') is True
    assert any('paraphrase' in n.lower() or 'verbatim' in n.lower() or 'do not copy' in n.lower()
               for n in seen['notes'])
    # One judgment repair only (compose calls: initial + judgment repair; possibly info_dump/anti_repeat none)
    assert seen['compose'] <= 3  # initial + judgment (+ optional style) — not an explosion
    assert not compose.line1_near_thesis(result['body'], thesis)


# --- C. info_dump rewrite hook --------------------------------------------------------

def test_info_dump_retry_hook_fires_and_keeps_soft(monkeypatch):
    from tests.test_compose import SOURCE as CS, UNITS
    from tests.test_judgment import VIEW
    raw = dict(UNITS['units'][2], kind='view',
               view=dict(VIEW, reasoning=[UNITS['units'][2]['source_spans'][0]['exact_text']]))
    # Body with >=4 distinct numbers -> info_dump
    dump_body = (
        'Supply is the real constraint.\n'
        'Revenue hit $54.23 billion; margin 69.5%; inventory 120 days; capex 30 billion.'
    )
    thin_body = 'Supply is the real constraint.\nRevenue was $54.23 billion.'
    seen = {'notes': []}

    class Fake:
        def __call__(self, stage, messages, max_tokens):
            p = json.loads(messages[-1]['content'])
            if stage == 'extract':
                return {'text': json.dumps({'units': [UNITS['units'][0], UNITS['units'][1], raw]}),
                        'finish_reason': 'stop'}
            if stage == 'stance':
                return {'text': json.dumps({
                    'decision': 'take', 'account_view': 'Supply is the real constraint.',
                    'supporting_unit_ids': [p['unit']['unit_id']], 'rationale': 'Supply.',
                    'confidence': 0.7}), 'finish_reason': 'stop'}
            note = p.get('rewrite_note') or ''
            seen['notes'].append(note)
            body = thin_body if 'info_dump_repair' in note else dump_body
            fact_id = next(u['unit_id'] for u in p['units'] if u['kind'] == 'fact')
            return {'text': json.dumps({
                'body': body,
                'claim_ledger': [{'claim': 'Revenue was $54.23 billion', 'unit_id': fact_id, 'span_ref': 0}],
            }), 'finish_reason': 'stop'}

    result = compose.compose_source(CS, 'en_industry', Fake(), exemplars=False)
    assert any('info_dump_repair' in n for n in seen['notes'])
    assert result.get('info_dump_retry', {}).get('attempted') is True
    # Soft only — never hard-blocks compose
    assert result['draft_status'] in ('draft_ready', 'needs_review')
    soft_codes = (result.get('qa') or {}).get('soft') or []
    assert 'info_dump' not in soft_codes or result['info_dump_retry'].get('kept') == 'original'
