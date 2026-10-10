"""Tests for compose_shapes.py new shapes (nat3 Oct 10 2026)."""
import os
import sys
sys.path.insert(0, '/workspace/fd_new/wt_nat3')

import pytest
from live import compose_shapes as cs


class FakePersona:
    persona_id = 'test_acct'
    lang = 'en'
    donor_weights = {}
    signature_card = None


def test_new_shapes_exist():
    for sid in ('one_line_take', 'quick_note', 'question_only', 'reaction', 'short_list'):
        assert sid in cs.SHAPES, f'expected new shape {sid!r} to be in cs.SHAPES'


def test_no_formula_closer_in_shape_text():
    import re
    # The phrase is allowed when it appears only inside a quoted negation (「接下来盯...」or 不要加「...」).
    # We only fail when it appears as an actual positive instruction (not inside 「…」quotes).
    _quoted = re.compile(r'「[^」]*接下来盯[^」]*」')
    _watch = re.compile(r'what to watch', re.I)
    for sid, spec in cs.SHAPES.items():
        for key in ('en', 'zh'):
            text = spec[key]
            # Remove all quoted-negation spans before checking
            stripped = _quoted.sub('', text)
            assert '接下来盯' not in stripped, (
                f'{sid}.{key} contains 接下来盯 outside a quoted negation context')
            assert not _watch.search(spec[key]), (
                f'{sid}.{key} contains "what to watch" (formula closer)')


def test_no_formula_closer_in_ending_rules():
    import re
    # Strip all negation contexts where 接下来盯 appears as a banned example, not a positive instruction:
    # 1. "NEVER 接下来盯/..." (en explicit ban list)
    # 2. "(接下来盯/...)" parenthetical example after no forward-watch / no formula etc.
    # 3. "不要...接下来盯..." (zh negation)
    _never_neg = re.compile(r'NEVER\s+接下来盯[^\n。.]*', re.I)
    _paren_neg = re.compile(r'\([^)]*接下来盯[^)]*\)')
    _jp_neg = re.compile(r'不要[^。\n]*接下来盯[^。\n]*')
    non_thread = [sid for sid in cs.SHAPES if sid != 'short_thread']
    for sid in non_thread:
        spec = cs.SHAPES[sid]
        shape_obj = {'id': sid, 'length': spec['length']}
        block = cs.payload_block(shape_obj, 'en', {'min': 80, 'max': 400})
        ending_rule = block.get('ending_rule', '')
        stripped = _never_neg.sub('', ending_rule)
        stripped = _paren_neg.sub('', stripped)
        stripped = _jp_neg.sub('', stripped)
        assert 'what to watch next' not in ending_rule.lower(), (
            f'shape {sid}: ending_rule contains "what to watch next" as a positive instruction')
        assert '接下来盯' not in stripped, (
            f'shape {sid}: ending_rule contains 接下来盯 outside a negation/parenthetical context')


def test_arg_shapes_capped():
    """Non-arg shapes are added alongside arg shapes; arg shapes themselves are not scaled down."""
    class FakePersonaArg(FakePersona):
        persona_id = 'test_arg_acct'

    import unittest.mock as mock
    fake_rates = {'shape_mix': {'argument': 0.3, 'personal': 0.3, 'one_liner': 0.2, 'reaction': 0.2}}
    with mock.patch('live.donor_rates.account_rates', return_value=fake_rates):
        shapes = cs.persona_shapes(FakePersonaArg())

    _NON_ARG = frozenset({'one_line_take', 'quick_note', 'question_only', 'reaction', 'short_list'})
    _ARG_SHAPES = frozenset(cs.SHAPES) - _NON_ARG

    # non-arg shapes should be present (nat3 adds them)
    assert any(sid in shapes for sid in _NON_ARG), 'expected at least one non-arg shape in persona_shapes'

    # non-arg shapes should have lower weights than arg shapes (they are added at donor share * 0.8 or floor 0.05)
    non_arg_max = max((shapes[sid] for sid in _NON_ARG if sid in shapes), default=0)
    arg_weights = [shapes[sid] for sid in _ARG_SHAPES if sid in shapes]
    if arg_weights:
        arg_max = max(arg_weights)
        assert non_arg_max <= arg_max, (
            f'non-arg max weight {non_arg_max} should be <= arg max {arg_max}')

    # with FD_NAT_PROMPT=0, no non-arg shapes
    import os
    old = os.environ.pop('FD_NAT_PROMPT', None)
    try:
        os.environ['FD_NAT_PROMPT'] = '0'
        shapes_off = cs.persona_shapes(FakePersonaArg())
        for sid in _NON_ARG:
            assert sid not in shapes_off, f'FD_NAT_PROMPT=0: {sid!r} should not be present'
    finally:
        if old is None:
            os.environ.pop('FD_NAT_PROMPT', None)
        else:
            os.environ['FD_NAT_PROMPT'] = old


def test_nat_prompt_0_no_non_arg(monkeypatch):
    monkeypatch.setenv('FD_NAT_PROMPT', '0')
    _NON_ARG = frozenset({'one_line_take', 'quick_note', 'question_only', 'reaction', 'short_list'})
    shapes = cs.persona_shapes(FakePersona())
    for sid in _NON_ARG:
        assert sid not in shapes, (
            f'FD_NAT_PROMPT=0 should exclude non-arg shape {sid!r} from persona_shapes; '
            f'got {sorted(shapes.keys())}')
