import copy
import json

import pytest

from live import compose, registry, voice_cards as vc
from tests.test_compose import Fake, GOOD_BODY, run


@pytest.mark.parametrize('lang,text', [
    ('en', text) for text in ('I bought NVDA.', 'I sold shares.', 'I added to it.',
        'I trimmed my stake.', 'I am long gold.', 'I am short bonds.',
        'My position is small.', 'My portfolio is up.', "We're long oil.", "I'm up 12%.",
        'I made a profit on NVDA.', 'I lost money on bonds.')
] + [('zh', text) for text in ('我买入了美光。', '我已经卖出。', '我加仓。', '我减仓。',
    '我建仓。', '我清仓。', '我持有。', '我满仓。', '我空仓。', '我的仓位很小。',
    '我的持仓。', '本人持仓。', '实盘记录。', '盈利了。', '亏了。', '我今天盈利了。', '今天实盘收益。')])
def test_position_claims(lang, text):
    assert {f['code'] for f in compose.position_findings(text, lang)} == {'position_claim'}


@pytest.mark.parametrize('lang,text', [
    ('en', 'Berkshire bought shares and sold bonds.'),
    ('en', 'The fund added exposure and trimmed its position.'),
    ('en', 'I think margins will improve.'),
    ('zh', '基金加仓，伯克希尔买入了股票。'),
    ('zh', '基金盈利了，投资者亏了。'),
    ('zh', '我认为供给偏紧。'),
])
def test_third_party_and_judgments(lang, text):
    assert compose.position_findings(text, lang) == []


def test_all_personas_have_clean_qualitative_cards():
    personas = {k: p for k, p in registry.load_personas().items() if k != 'en_morris_archive'}
    assert len(personas) == 10
    for persona in personas.values():
        card = persona.voice_card
        assert card and card['qualitative']['tendencies']
        for rows in (card['tendencies'], card['qualitative']['tendencies']):
            assert rows
            assert all(not any(p.search(r['tendency']) for p in vc.POSITION_PATTERNS) for r in rows)


def test_sanitizer_removes_text_only_and_preserves_prohibitions():
    unsafe = {'tendency': 'Shares my portfolio holdings', 'frequency': 'often',
              'evidence_ids': ['secret'], 'evidence': [{'text': 'private'}]}
    card = {'tendencies': [unsafe], 'qualitative': {'tendencies': [unsafe],
        'avoid_tendencies': [{'tendency': 'Never claim personal holdings', 'frequency': 'almost_never', 'evidence_ids': []},
                             {'tendency': 'Shows 实盘', 'frequency': 'rarely', 'evidence_ids': ['x']}],
        'signature_moves': [{'move': 'Discusses position sizing', 'example_ids': ['x']}],
        'hook_patterns': [{'pattern': 'I bought shares', 'example_ids': ['x']}]}}
    cleaned = vc.sanitize_card(copy.deepcopy(card))
    assert cleaned['tendencies'] == cleaned['qualitative']['tendencies'] == []
    assert cleaned['qualitative']['signature_moves'] == []
    assert cleaned['qualitative']['hook_patterns'] == []
    assert all(isinstance(t, str) for t in cleaned['compliance_removed'])
    assert 'private' not in json.dumps(cleaned['compliance_removed'])
    assert any(r['tendency'] == 'Never claim personal holdings' for r in cleaned['qualitative']['avoid_tendencies'])
    assert vc.sanitize_card(copy.deepcopy(cleaned)) == cleaned


def test_registry_sanitizes_existing_file(tmp_path):
    persona_path = next(p for p in registry.PERSONAS.glob('*.json')
                        if json.loads(p.read_text()).get('donor_cluster'))
    raw = json.loads(persona_path.read_text())
    (tmp_path / persona_path.name).write_text(json.dumps(raw))
    card_dir = tmp_path / 'voice_cards'
    card_dir.mkdir()
    (card_dir / (raw['donor_cluster'] + '.json')).write_text(json.dumps({
        'tendencies': [{'tendency': 'Discusses my portfolio', 'frequency': 'often'}]}))
    card = registry.load_personas(tmp_path)[raw['persona_id']].voice_card
    assert card['tendencies'] == []
    assert card['compliance_removed'] == ['Discusses my portfolio']


def test_compact_summary_sanitizes_without_registry():
    card = copy.deepcopy(registry.persona_for_account('zh_industry').voice_card)
    card['tendencies'].append({'tendency': 'Shows personal 持仓', 'frequency': 'often'})
    assert not any('Shows personal' in t for t in vc.compact_summary(card)['tendencies'])


def test_build_sanitizes_qualitative_output(monkeypatch, tmp_path):
    monkeypatch.setattr(vc, 'qualitative_card', lambda *args: {
        'tendencies': [{'tendency': 'Reports bought shares', 'frequency': 'often'}],
        'avoid_tendencies': []})
    roster = {'donors': {}, 'persona_clusters': {'test': {'lang': 'en', 'donors': []}}}
    card = vc.build_cards(tmp_path, tmp_path, roster, llm=lambda *args: '')['test']
    assert card['tendencies'] == card['qualitative']['tendencies'] == []
    assert card['compliance_removed'] == ['Reports bought shares']


def test_position_claim_blocks_draft():
    result, _ = run(Fake(body='我已经买入美光。' + GOOD_BODY), post_type='data_take')
    finding = next(f for f in result['post_checks'] if f['code'] == 'position_claim')
    assert finding['level'] == 'hard'
    assert result['draft_status'] == 'needs_review'
    assert 'position_claim' in result['qa']['hard']
    assert not result['publishable']
