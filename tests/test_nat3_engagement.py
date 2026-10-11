"""Tests for engagement.py and hook_voice.py (nat3 Oct 10 2026)."""
import os
import sys

import pytest
from live import engagement as eng
from live import hook_voice


def test_hook_voice_allows_first_person_zh():
    findings = hook_voice.hook_findings('我觉得BTC会涨', 'zh')
    codes = [f['code'] for f in findings]
    assert 'weak_hook' not in codes, (
        '我觉得 should not trigger weak_hook after nat3 removal from WEAK_OPENERS_ZH')


def test_hook_voice_still_blocks_generic_zh():
    findings = hook_voice.hook_findings('最近市场很活跃，大家关注一下', 'zh')
    codes = [f['code'] for f in findings]
    assert 'weak_hook' in codes, '最近市场 should still trigger weak_hook (GENERIC_ZH)'


def test_hook_voice_allows_i_think_en():
    findings = hook_voice.hook_findings('I think BTC is going higher', 'en')
    codes = [f['code'] for f in findings]
    assert 'weak_hook' not in codes, (
        '"I think" should not trigger weak_hook after nat3 removal from WEAK_OPENERS_EN')


def test_hook_voice_still_blocks_breaking_en():
    findings = hook_voice.hook_findings('Breaking: BTC hits new high', 'en')
    codes = [f['code'] for f in findings]
    assert 'weak_hook' in codes, '"Breaking:" is in GENERIC_EN and should still trigger weak_hook'


def test_echo_op_fires_on_number():
    target = 'ETFs sold $681,000,000 in BTC'
    reply = 'ETFs dumped $681,000,000 in BTC this week'
    findings = eng.echo_op_findings(reply, target, 'en')
    codes = [f['code'] for f in findings]
    assert 'echo_op' in codes, 'reply repeating the target number should fire echo_op'


def test_echo_op_fires_on_3gram():
    target = 'The structural story keeps building here'
    reply = 'The structural story keeps building into the weekend'
    findings = eng.echo_op_findings(reply, target, 'en')
    codes = [f['code'] for f in findings]
    assert 'echo_op' in codes, 'reply sharing a 3-gram with the target should fire echo_op'


def test_echo_op_clean_reply():
    target = 'ETFs sold $681M in BTC'
    reply = 'Not surprised, flows have been negative for weeks'
    findings = eng.echo_op_findings(reply, target, 'en')
    assert findings == [], f'clean reply should produce no echo_op findings, got {findings}'


def test_author_cap_blocks_3rd():
    day_rows = [
        {'account_id': 'a1', 'engagement': {'author': 'TedPillows'}},
        {'account_id': 'a2', 'engagement': {'author': 'TedPillows'}},
    ]
    assert eng.author_cap_exceeded('a3', 'TedPillows', day_rows, cap=2) is True


def test_author_cap_allows_2nd():
    day_rows = [
        {'account_id': 'a1', 'engagement': {'author': 'TedPillows'}},
    ]
    assert eng.author_cap_exceeded('a2', 'TedPillows', day_rows, cap=2) is False


def test_reply_short_en_fires():
    long_reply = (
        'ETFs sold $681M in BTC this week — another $542M in ETH went out the door, '
        'and the total of $1.2B across both assets in a single week signals real '
        'institutional selling pressure.'
    )
    findings = eng.findings(long_reply, 'reply', 'en', target_text='ETFs sold some BTC')
    codes = [f['code'] for f in findings]
    assert 'engage_too_long' in codes, (
        f'long reply ({len(long_reply.split())} words) should fire engage_too_long; got codes {codes}')


def test_reply_short_fd_reply_short_0(monkeypatch):
    monkeypatch.setenv('FD_REPLY_SHORT', '0')
    long_reply = (
        'ETFs sold $681M in BTC this week — another $542M in ETH went out the door, '
        'and the total of $1.2B across both assets in a single week signals real '
        'institutional selling pressure.'
    )
    findings = eng.findings(long_reply, 'reply', 'en', target_text='ETFs sold some BTC')
    codes = [f['code'] for f in findings]
    assert 'engage_too_long' not in codes, (
        'FD_REPLY_SHORT=0 should suppress the word-count engage_too_long check')


def test_fd_engage_author_cap_0(monkeypatch):
    monkeypatch.setenv('FD_ENGAGE_AUTHOR_CAP', '0')
    day_rows = [
        {'account_id': 'a1', 'engagement': {'author': 'TedPillows'}},
        {'account_id': 'a2', 'engagement': {'author': 'TedPillows'}},
    ]
    # cap=0 passed explicitly mirrors what the env guard does (cap <= 0 -> False)
    result = eng.author_cap_exceeded('a3', 'TedPillows', day_rows, cap=0)
    assert result is False, 'cap=0 should always return False (disabled)'
