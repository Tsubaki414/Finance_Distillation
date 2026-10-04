"""Per-persona signature voice cards: every composed persona has one; COMPOSE sends the signature
(moves/openings/closings/lexicon/taboos) and leads style exemplars with judge-picked donor posts."""
import json
from pathlib import Path

from live import compose, registry
from tests.test_compose import Fake, SOURCE, GOOD_BODY

CARDS = Path(compose.__file__).with_name('personas') / 'signature_cards'
ACCOUNTS = ['zh_macro', 'zh_industry', 'en_industry', 'en_macro', 'crypto_macro_en', 'crypto_macro_zh',
            'single_stock_deepdive_en', 'trading_shortterm', 'market_data_charts', 'investing_philosophy']


class Capture(Fake):
    def __call__(self, stage, messages, max_tokens):
        if stage == 'compose':
            self.payload = json.loads(messages[-1]['content'])
        return super().__call__(stage, messages, max_tokens)


def test_all_ten_personas_have_valid_cards():
    for account in ACCOUNTS:
        p = registry.persona_for_account(account)
        card = p.signature_card
        assert card, account
        assert 3 <= len(card['moves']) <= 5
        assert len(card['exemplars']) >= 2
        assert card['openings'] and card['closings'] and card['taboos']
        assert all(not any(rx.search(t) for _, rx in compose.template_patterns(p.lang)) for t in card['lexicon'])


def test_compose_payload_carries_signature_and_exemplars():
    fake = Capture()
    compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take')
    sig = fake.payload['persona']['signature']
    assert {'moves', 'openings', 'closings', 'lexicon', 'taboos'} <= set(sig)
    card = registry.persona_for_account('zh_industry').signature_card
    shown = [e.get('id') for e in fake.payload.get('style_exemplars', [])]
    assert card['exemplars'][0]['id'] in shown
    assert 'signature' in compose.COMPOSE
