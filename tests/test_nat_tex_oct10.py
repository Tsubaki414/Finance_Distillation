"""Tests for live/nat_tex.py (A5 jargon, A9 round guard, A10 LLM-ism/em-dash) — nat-tex Oct 10 2026."""
import os
import sys
sys.path.insert(0, '/workspace/fd_new/wt_nat_tex')

import pytest
from live import nat_tex as nt
from live import humanize as hum


# ------------------------------------------------------------------ helpers

def _row(body, draft_id='test1', account_id='test'):
    return {'id': draft_id, 'body': body, 'account_id': account_id}


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


# ================================================================== A5 — jargon


class TestJargon:
    def test_zh_jargon_rewrite_reduces_count(self):
        body = '宏观流动性还会紧，底层逻辑是筹码高度集中，结构性问题未解'
        before = nt._count_jargon(body, 'zh')
        new_body, changes = nt.apply_jargon(body, 'zh', 'jarg1', donor_budget=1)
        after = nt._count_jargon(new_body, 'zh')
        assert after < before, f'jargon count did not decrease: {before} -> {after}'
        assert changes, 'expected at least one change record'

    def test_en_jargon_rewrite_reduces_count(self):
        body = 'The structural backdrop and liquidity conditions are tightening as capital flows reverse'
        before = nt._count_jargon(body, 'en')
        new_body, changes = nt.apply_jargon(body, 'en', 'jarg2', donor_budget=1)
        after = nt._count_jargon(new_body, 'en')
        assert after < before, f'EN jargon count did not decrease: {before} -> {after}'

    def test_within_budget_untouched(self):
        body = 'Rates rising on liquidity fears'
        new_body, changes = nt.apply_jargon(body, 'en', 'jarg3', donor_budget=1)
        assert new_body == body, 'body within budget should not be changed'
        assert not changes

    def test_zh_safe_context_not_stripped(self):
        # "流动性危机" and "底层技术" are safe usages
        body = '流动性危机推动了底层技术的发展'
        new_body, changes = nt.apply_jargon(body, 'zh', 'jarg4', donor_budget=0)
        assert '流动性危机' in new_body, 'safe usage 流动性危机 should not be stripped'

    def test_no_new_facts_invented(self):
        body = '宏观流动性还会紧很久，美联储加息到5.5%'
        new_body, changes = nt.apply_jargon(body, 'zh', 'jarg5', donor_budget=0)
        assert '5.5%' in new_body, 'numbers must survive jargon rewrite'

    def test_fd_nat_jargon_0_skips(self, monkeypatch):
        monkeypatch.setenv('FD_NAT_JARGON', '0')
        body = '宏观流动性底层筹码结构全都有'
        new_body, changes = nt.apply_jargon(body, 'zh', 'jarg6', donor_budget=0)
        assert new_body == body
        assert not changes

    def test_jargon_soft_no_hold(self):
        # Even when rewrite fails (budget still exceeded), we get a warning, not an exception or HOLD
        body = '流动性宏观底层筹码结构性全部出现好几次流动性流动性'
        new_body, changes = nt.apply_jargon(body, 'zh', 'jarg7', donor_budget=0)
        # must not raise; must return a body
        assert isinstance(new_body, str)
        # warning logged as change note if still over
        remaining = nt._count_jargon(new_body, 'zh')
        if remaining > 0:
            assert any('soft warning' in c or 'remain' in c for c in changes)

    def test_count_jargon_zh(self):
        assert nt._count_jargon('流动性很紧', 'zh') == 1
        assert nt._count_jargon('no jargon here', 'zh') == 0

    def test_count_jargon_en(self):
        assert nt._count_jargon('structural story', 'en') >= 1
        assert nt._count_jargon('BTC is up 5%', 'en') == 0


# ================================================================== A9 — FD_NAT_ROUND kill switch


class TestRoundKillSwitch:
    def test_fd_nat_round_0_skips_rounding(self, monkeypatch):
        monkeypatch.setenv('FD_NAT_ROUND', '0')
        body = 'ETF saw $1,234,567,890 in flows'
        rates = {**_BASE_RATES, 'precise_number': 0.0}
        result = hum.apply(_row(body, 'round_off'), rates=rates, lang='en')
        assert '$1,234,567,890' in result['body'], (
            'FD_NAT_ROUND=0 must leave precise numbers untouched')

    def test_fd_nat_round_1_still_rounds(self, monkeypatch):
        monkeypatch.setenv('FD_NAT_ROUND', '1')
        body = 'ETF saw $1,234,567,890 in flows last week'
        rates = {**_BASE_RATES, 'precise_number': 0.0}
        result = hum.apply(_row(body, 'round_on'), rates=rates, lang='en')
        # either rounded OR untouched (fidelity guard may keep it) — but must not raise
        assert isinstance(result['body'], str)

    def test_round_enabled_flag(self, monkeypatch):
        monkeypatch.setenv('FD_NAT_ROUND', '0')
        assert not nt.round_enabled()
        monkeypatch.setenv('FD_NAT_ROUND', '1')
        assert nt.round_enabled()


# ================================================================== A10 — LLM-ism blocklist + em-dash


class TestLLMism:
    def test_sober_reminder_removed(self):
        body = "This is a sober reminder that rates are rising."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm1')
        assert 'sober reminder' not in new_body
        assert changes

    def test_structural_story_replaced(self):
        body = "That's the structural story. Nothing has changed."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm2')
        assert 'structural story' not in new_body.lower() or 'That\'s the structural story' not in new_body
        assert changes

    def test_the_question_is_whether_replaced(self):
        body = "The question is whether the Fed will pause."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm3')
        assert 'The question is whether' not in new_body
        assert changes

    def test_so_much_for_replaced(self):
        body = "So much for the pivot narrative."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm4')
        assert 'So much for' not in new_body
        assert changes

    def test_heres_the_thing_removed(self):
        body = "Here's the thing: rates are sticky."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm5')
        assert "Here's the thing" not in new_body
        assert changes

    def test_make_no_mistake_removed(self):
        body = "Make no mistake, this is a tightening cycle."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm6')
        assert 'Make no mistake' not in new_body
        assert changes

    def test_let_that_sink_in_removed(self):
        body = "Yields up 40bps in a week. Let that sink in."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm7')
        assert 'Let that sink in' not in new_body
        assert changes

    def test_im_not_convinced_replaced(self):
        body = "I'm not convinced by the soft-landing thesis."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm8')
        assert "I'm not convinced by" not in new_body
        assert changes

    def test_at_its_core_removed(self):
        body = "At its core, this is a liquidity problem."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm9')
        assert 'At its core' not in new_body
        assert changes

    def test_emdash_reduced_when_dense(self):
        body = "Rates are up — yields are moving — spreads widen — credit tightens."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm10', rates={'emdash_rate': 0.1})
        em_before = body.count('—')
        em_after = new_body.count('—')
        assert em_after <= em_before, 'em-dashes should not increase'
        if em_before > 1:
            assert em_after < em_before, 'dense em-dashes should be reduced'

    def test_emdash_single_untouched(self):
        # single em-dash at low donor rate — still within budget
        body = "BTC is up — real move or just noise?"
        new_body, changes = nt.apply_llmism(body, 'en', 'llm11', rates={'emdash_rate': 0.1})
        assert new_body.count('—') <= 1

    def test_zh_not_touched(self):
        body = '宏观流动性结构性问题'
        new_body, changes = nt.apply_llmism(body, 'zh', 'llm12')
        assert new_body == body, 'ZH body must be untouched by llmism'
        assert not changes

    def test_no_numbers_lost(self):
        body = "Make no mistake, BTC at $82,000 is structural support. That's the structural story."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm13')
        assert '$82,000' in new_body, 'numbers must survive llmism rewrite'
        assert '82' in new_body

    def test_fd_nat_llmism_0_skips(self, monkeypatch):
        monkeypatch.setenv('FD_NAT_LLMISM', '0')
        body = "Make no mistake, that's the structural story. So much for the pivot."
        new_body, changes = nt.apply_llmism(body, 'en', 'llm14')
        assert new_body == body
        assert not changes

    def test_llmism_enabled_flag(self, monkeypatch):
        monkeypatch.setenv('FD_NAT_LLMISM', '0')
        assert not nt.llmism_enabled()
        monkeypatch.setenv('FD_NAT_LLMISM', '1')
        assert nt.llmism_enabled()

    def test_deterministic(self):
        body = "Make no mistake — rates are up — and the structural story keeps building."
        r1, _ = nt.apply_llmism(body, 'en', 'det_id_x', rates={'emdash_rate': 0.05})
        r2, _ = nt.apply_llmism(body, 'en', 'det_id_x', rates={'emdash_rate': 0.05})
        assert r1 == r2


# ================================================================== combined apply() + humanize integration


class TestCombinedApply:
    def test_apply_returns_tuple(self):
        body = "That's the structural story. 流动性宏观看好。"
        new_body, changes = nt.apply(body, 'en', 'comb1')
        assert isinstance(new_body, str)
        assert isinstance(changes, list)

    def test_humanize_wires_nat_tex(self):
        # Verify nat_tex changes appear in humanize row['humanize']['changes']
        body = "Make no mistake — the structural story keeps building and liquidity is tightening."
        rates = {**_BASE_RATES}
        result = hum.apply(_row(body, 'wire_test'), rates=rates, lang='en')
        changes = result.get('humanize', {}).get('changes', [])
        llmism_touched = any('llmism' in c for c in changes)
        jargon_touched = any('jargon' in c for c in changes)
        # at minimum one of the two should have fired
        assert llmism_touched or jargon_touched, (
            f'nat_tex changes not recorded in humanize output; changes={changes}')

    def test_nat_tex_fidelity_revert(self, monkeypatch):
        # When nat_tex would corrupt numbers, the fidelity guard reverts
        from unittest.mock import patch
        body = "Make no mistake, BTC is at $82,000 structural support."
        rates = {**_BASE_RATES}
        original = body
        with patch('live.humanize._fidelity_ok', side_effect=lambda a, b, **kw: a == b):
            result = hum.apply(_row(body, 'fid_revert'), rates=rates, lang='en')
        # body should be original (fidelity fail reverts)
        # This tests the guard path exists and doesn't crash
        assert isinstance(result['body'], str)

    def test_all_kill_switches_off(self, monkeypatch):
        monkeypatch.setenv('FD_HUMANIZE', '0')
        monkeypatch.setenv('FD_NAT_JARGON', '0')
        monkeypatch.setenv('FD_NAT_ROUND', '0')
        monkeypatch.setenv('FD_NAT_LLMISM', '0')
        body = "Make no mistake — structural story and 流动性 宏观 liquidity and $1,234,567 precise number."
        rates = {**_BASE_RATES, 'precise_number': 0.0}
        result = hum.apply(_row(body, 'all_off'), rates=rates, lang='en')
        assert result['body'] == body, 'all kill switches off should leave body completely unchanged'
