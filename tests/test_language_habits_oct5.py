"""Oct 5: donor language habits + Fiona industry / feedback exemplars."""
import json
from pathlib import Path

from live import anti_repeat as ar, language_habits as lh, registry
from tests.test_compose import Fake, GOOD_BODY, SOURCE, UNITS, run
from live import compose


class Capture(Fake):
    def __call__(self, stage, messages, max_tokens):
        out = super().__call__(stage, messages, max_tokens)
        if stage == 'compose':
            self.payload = json.loads(messages[-1]['content'])
        return out


def test_language_cards_exist_and_are_aggregates():
    personas = registry.load_personas()
    for pid in ('zh_industry', 'en_industry', 'market_data_charts', 'crypto_macro_en'):
        card = lh.load_card(personas[pid])
        assert card['persona_id'] == pid
        assert card.get('prefer') and card.get('avoid') and card.get('guidance')
        assert 'https://t.co' not in json.dumps(card, ensure_ascii=False)


def test_industry_constraints_present():
    personas = registry.load_personas()
    zh = lh.load_card(personas['zh_industry'])
    en = lh.load_card(personas['en_industry'])
    assert any('研报腔' in x or '链路' in x for x in zh['industry_constraints'])
    assert any('valuation-free' in x for x in en['industry_constraints'])
    assert 'industry_constraints' not in lh.load_card(personas['zh_macro'])


def test_zh_industry_signature_no_banned_teaching():
    sig = json.loads(Path('live/personas/signature_cards/zh_industry.json').read_text())
    # Taboos may name banned phrases; teaching surfaces must not.
    taught = json.dumps({
        'moves': sig.get('moves'), 'lexicon': sig.get('lexicon'),
        'openings': sig.get('openings'), 'closings': sig.get('closings'),
        'zh_restraint': sig.get('zh_restraint'),
    }, ensure_ascii=False)
    for bad in ('链路往下推', '还早着呢', '每一环的议价权'):
        assert bad not in taught, bad
    assert any('研报腔' in t for t in sig['taboos'])


def test_fiona_feedback_exemplars_hook():
    mdc = json.loads(Path('live/personas/signature_cards/market_data_charts.json').read_text())
    cme = json.loads(Path('live/personas/signature_cards/crypto_macro_en.json').read_text())
    assert mdc['fiona_feedback_exemplars'][0]['id'] == 'fiona-oct5-3-shape'
    assert 'level' in (mdc['fiona_feedback_exemplars'][0]['lesson'] + mdc['fiona_feedback_exemplars'][0]['text']).lower()
    assert cme['fiona_feedback_exemplars'][0]['id'] == 'fiona-oct5-4-shape'
    text = cme['fiona_feedback_exemplars'][0]['text'] + cme['fiona_feedback_exemplars'][0]['lesson']
    assert 'ETF' in text or 'OI' in text or 'open interest' in text.lower()


def test_phrase_ban_is_a_start_variants():
    assert 'phrase_ban' in {f['code'] for f in ar.findings('August print is a start for soft data.', 'en_macro')}
    assert 'phrase_ban' in {f['code'] for f in ar.findings('before that door closes on the hike.', 'en_macro')}


def test_compose_payload_fields_for_industry():
    fake = Capture(body=GOOD_BODY, units=UNITS)
    compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take', exemplars=True)
    persona = fake.payload['persona']
    assert 'language_habits' in persona
    assert persona['language_habits'].get('industry_constraints')
    hard = '\n'.join(persona['signature']['hard_constraints'])
    assert '研报腔' in hard or '链路' in hard


def test_fiona_exemplar_injected_for_charts():
    en_body = ('BTC early uptrend is fragile. Volume is thin. '
               'A close below the mean weakens it. Micron revenue rose 4.8x to $54.23 billion in the quarter. '
               'Operating margin was 69.5%. Memory makers will not build a glut because building a fab takes years.')
    fake = Capture(body=en_body, units=UNITS)
    compose.compose_source(SOURCE, 'market_data_charts', fake, post_type='data_take', exemplars=True)
    ids = {e.get('id') for e in (fake.payload.get('style_exemplars') or [])}
    assert 'fiona-oct5-3-shape' in ids
    assert any('POS shape' in h for h in fake.payload['persona']['signature']['hard_constraints'])


def test_crypto_macro_en_fiona_exemplar():
    en_body = ('Rate expectations are not driving Bitcoin. Micron revenue rose 4.8x to $54.23 billion in the quarter. '
               'Operating margin was 69.5%. Memory makers will not build a glut because building a fab takes years and prices keep rising.')
    fake = Capture(body=en_body, units=UNITS)
    compose.compose_source(SOURCE, 'crypto_macro_en', fake, post_type='data_take', exemplars=True)
    ids = {e.get('id') for e in (fake.payload.get('style_exemplars') or [])}
    assert 'fiona-oct5-4-shape' in ids


def test_write_card_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(lh, 'CARDS_DIR', tmp_path)
    persona = registry.persona_for_account('zh_industry')
    card = lh.write_card(persona)
    assert (tmp_path / 'zh_industry.json').exists()
    assert card['posts'] > 0
    assert card['industry_constraints']
