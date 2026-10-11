"""Tests for live/donor_rates.py (nat3 Oct 10 2026)."""
import json
import sys

import pytest
from live import donor_rates as dr


@pytest.fixture(scope='module')
def built():
    """Build once and cache for the module."""
    return dr.build_all()


def test_build_returns_structure(built):
    assert isinstance(built, dict)
    for key in ('accounts', 'fallback', 'version'):
        assert key in built, f'missing top-level key: {key}'
    assert isinstance(built['accounts'], dict)
    assert len(built['accounts']) > 0, 'accounts dict is empty'


def test_account_has_required_fields(built):
    required = ('first_person', 'intensifier', 'emoji', 'formula_closer',
                 'short_post', 'length_p50', 'shape_mix')
    for pid, acct in built['accounts'].items():
        for field in required:
            assert field in acct, f'account {pid!r} missing field {field!r}'


def test_fallback_applied_for_low_n(built):
    for pid, acct in built['accounts'].items():
        actual_n = acct.get('actual_n')
        if actual_n is not None and actual_n < 30:
            assert acct.get('fallback') is True, (
                f'account {pid!r} has actual_n={actual_n} but fallback flag not set')


def test_no_donor_text_in_output(built):
    raw = json.dumps(built, ensure_ascii=False)
    # check no individual string value exceeds 300 chars (would mean post text slipped in)
    def walk(obj):
        if isinstance(obj, str):
            assert len(obj) <= 300, f'string value too long ({len(obj)} chars); donor text may have leaked'
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(built)


def test_shape_mix_sums_to_one(built):
    for pid, acct in built['accounts'].items():
        mix = acct.get('shape_mix') or {}
        if not mix:
            continue
        total = sum(mix.values())
        assert abs(total - 1.0) <= 0.05, (
            f'account {pid!r} shape_mix sums to {total:.3f}, expected ~1.0')


def test_language_fallback_exists(built):
    fb = built.get('fallback') or {}
    assert 'zh' in fb or 'en' in fb, \
        'fallback has neither zh nor en; no accounts cleared the MIN_POSTS floor'
