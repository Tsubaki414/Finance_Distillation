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


def test_position_patterns_spare_rhetorical_tendencies():
    import re
    from live.voice_cards import POSITION_PATTERNS
    hit = lambda t: any(p.search(t) for p in POSITION_PATTERNS)
    for t in ("Relays an external chart, report or person's point with attribution and a short added take",
              'Positions a view explicitly against consensus or conventional wisdom',
              "Relays someone else's quote, book lesson, or stat with little or no added commentary",
              'Marks the view as personal with first-person belief framing, while still holding a fairly confident directional stance',
              'Positions the view against a named person or a prevailing bear or bull narrative',
              'Frames downside losses in the index as a risk scenario'):
        assert not hit(t), t
    for t in ('Discloses a personal position, addition or holding history to frame the view',
              'Shares their own positions, stops and exposure as part of the update',
              'Calls a range or trade finished and announces the exit, giving the result',
              'Discloses current holdings with performance and stop status',
              'Explicit trade instructions with entries, stops or position sizes',
              "Grounds a view in the author's own position, trade or hands-on use",
              '经常晒出自己的持仓和加仓记录'):
        assert hit(t), t


def test_free_text_fields_drop_position_sentences():
    from live.voice_cards import sanitize_card, POSITION_PATTERNS
    card = {'qualitative': {'voice_summary': 'Fast desk banter. Judgments are tied to a stated level or personal position. Data supports views.',
                            'judgment_style': 'Assertive. Donors are open about their own positions and past mistakes.',
                            'tendencies': [], 'avoid_tendencies': []}}
    out = sanitize_card(card)['qualitative']
    for k in ('voice_summary', 'judgment_style'):
        assert not any(p.search(out[k]) for p in POSITION_PATTERNS), out[k]
    assert 'Fast desk banter.' in out['voice_summary'] and 'Data supports views.' in out['voice_summary']
    assert out['judgment_style'].startswith('Assertive.')


def test_zh_position_claims_with_time_words():
    from live.compose import position_findings
    for t in ('我今天加仓了英伟达', '我昨天刚刚清仓了特斯拉', '我们本周减仓了半导体', '我目前持有比特币现货'):
        assert position_findings(t, 'zh'), t
    for t in ('基金加仓科技股', '巴菲特今天减仓了苹果', '我认为机构在加仓'):
        assert not position_findings(t, 'zh'), t
