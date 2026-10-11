"""Tests for live/humanize.py (nat3 Oct 10 2026)."""
import os
import sys

import pytest
from unittest.mock import patch
from live import humanize as hum


_BASE_RATES = {
    'intensifier': 0.99,
    'emoji': 0,
    'slang': 0,
    'first_person': 0,
    'ticker': 0,
    'precise_number': 1.0,
    'formula_closer': 0,
    'shape_mix': {},
    'short_post': 0,
    'top5_emoji': [],
    'last_line_period': 0,
    'hedge': 0,
    'mention': 0,
    'length_p50': 100,
}


def _row(body, draft_id='test1', account_id='test'):
    return {'id': draft_id, 'body': body, 'account_id': account_id}


def test_intensifier_cap_zh():
    body = '这简直太根本了，疯狂上涨'
    rates = {**_BASE_RATES, 'intensifier': 0.99, 'precise_number': 1.0}
    result = hum.apply(_row(body, 'id_zh_intens'), rates=rates, lang='zh')
    count = len(hum._INTENS_ZH.findall(result['body']))
    assert count <= 1, f'expected at most 1 zh intensifier, got {count} in {result["body"]!r}'


def test_intensifier_cap_en():
    body = 'The market simply completely crashed'
    rates = {**_BASE_RATES, 'intensifier': 0.99, 'precise_number': 1.0}
    result = hum.apply(_row(body, 'id_en_intens'), rates=rates, lang='en')
    count = len(hum._INTENS_EN.findall(result['body']))
    assert count <= 1, f'expected at most 1 en intensifier, got {count} in {result["body"]!r}'


def test_deterministic_per_id():
    body = '这简直离谱，疯狂上涨，绝对超预期'
    rates = {**_BASE_RATES, 'intensifier': 0.5}
    r1 = hum.apply(_row(body, 'stable_id_abc'), rates=rates, lang='zh')
    r2 = hum.apply(_row(body, 'stable_id_abc'), rates=rates, lang='zh')
    assert r1['body'] == r2['body'], 'same id should produce identical body'


def test_round_zh_direct():
    new_val, new_scale = hum._round_zh('4.872', '亿')
    assert new_val is not None, '_round_zh returned None for 4.872亿'
    # 4.872亿 -> should round to 4.9亿
    assert new_val == '4.9', f'expected 4.9, got {new_val!r}'
    assert new_scale == '亿', f'expected 亿, got {new_scale!r}'


def test_round_en_direct():
    new_val, new_scale = hum._round_en('681000000', '')
    assert new_val is not None, '_round_en returned None for 681000000'
    # 681M -> should produce a val + M scale
    combined = f'{new_val}{new_scale}'.lower()
    assert 'm' in combined or '681' in combined or '680' in combined, (
        f'unexpected rounding result: {new_val!r}{new_scale!r}')


def test_rounding_price_untouched():
    body = 'BTC trading at $82,000 right now'
    rates = {**_BASE_RATES, 'precise_number': 0.0}
    result = hum.apply(_row(body, 'price_guard_test'), rates=rates, lang='en')
    assert '$82,000' in result['body'], (
        f'price context guard failed — $82,000 was removed from {result["body"]!r}')


def test_fidelity_revert_on_fail():
    body = '这简直太离谱，疯狂上涨，完全超预期，绝对值得关注'
    rates = {**_BASE_RATES, 'intensifier': 0.99, 'formula_closer': 1.0}
    with patch('live.humanize._fidelity_ok', return_value=False):
        result = hum.apply(_row(body, 'fidelity_fail_test'), rates=rates, lang='zh')
    assert result['humanize']['reverted'] is True, 'expected reverted=True when fidelity fails'
    assert result['body'] == body, 'body should be restored to original on fidelity fail'


def test_fd_humanize_0_skips(monkeypatch):
    monkeypatch.setenv('FD_HUMANIZE', '0')
    body = '这简直离谱，疯狂上涨，绝对超预期'
    rates = {**_BASE_RATES, 'intensifier': 0.99}
    result = hum.apply(_row(body, 'skip_test'), rates=rates, lang='zh')
    assert result['body'] == body, 'FD_HUMANIZE=0 should leave body unchanged'


def test_fd_humanize_llm_0_skips_llm(monkeypatch):
    monkeypatch.setenv('FD_HUMANIZE_LLM', '0')
    body = 'The market simply crashed'
    rates = {**_BASE_RATES}
    mock_client = object()  # non-None client that should not be called
    result = hum.apply(_row(body, 'no_llm_test'), client=mock_client, rates=rates, lang='en')
    assert result['humanize']['llm'] is False, 'FD_HUMANIZE_LLM=0 should set llm=False'
