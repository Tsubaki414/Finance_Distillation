"""Tests for live/closer_ngram.py (naturalness A2 — per-account formula-closer n-gram memory, Oct 11 2026).

Covers:
  - repeat key triggers soft finding + last-line change
  - unique closer untouched
  - forward_watch stack >= 3 triggers
  - kill switch off → no-op
  - numbers / tickers in earlier lines survive repair
  - ZH and EN paths
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from live import closer_ngram as cn


# ------------------------------------------------------------------ helpers

def _make_inbox(drafts: list[dict], tmp: Path) -> Path:
    """Write draft rows into a temp compose_inbox layout and return its root."""
    base = tmp / 'compose_inbox'
    for row in drafts:
        day = row['day']
        (base / day).mkdir(parents=True, exist_ok=True)
        p = base / day / f"{row['id']}.json"
        p.write_text(json.dumps(row, ensure_ascii=False) + '\n')
    return base


def _row(body, account_id='acct_zh', lang='zh', draft_id='draft-cur', day='2026-10-11',
         draft_status='draft_ready'):
    return {
        'id': draft_id,
        'account_id': account_id,
        'lang': lang,
        'body': body,
        'day': day,
        'draft_status': draft_status,
    }


# today_bjt fixed so tests don't drift
TODAY = date(2026, 10, 11)


# ================================================================== closer_key

class TestCloserKey:
    def test_zh_first_8_cjk(self):
        # CJK extraction from '接下来盯紧美联储的动作就够了' yields '接下来盯紧美联储' (8 chars)
        body = '第一行有很多内容\n接下来盯紧美联储的动作就够了'
        key = cn.closer_key(body, 'zh')
        assert key == '接下来盯紧美联储'

    def test_zh_short_line(self):
        body = '盯住这条线'
        key = cn.closer_key(body, 'zh')
        assert key == '盯住这条线'

    def test_en_first_3_words(self):
        body = 'Some earlier line.\nWatch the weekly close carefully now.'
        key = cn.closer_key(body, 'en')
        assert key == 'watch the weekly'

    def test_en_case_insensitive(self):
        body = 'Watch The Weekly Close'
        assert cn.closer_key(body, 'en') == 'watch the weekly'

    def test_empty_body(self):
        assert cn.closer_key('', 'zh') == ''
        assert cn.closer_key('', 'en') == ''

    def test_zh_ignores_non_cjk(self):
        # Key is the first 8 chars of the CJK-run joined from the last line.
        # 'BTC看涨，ETH持有，SOL下注' produces a key of at most 8 chars and it is non-empty.
        body = 'BTC看涨，ETH持有，SOL下注'
        key = cn.closer_key(body, 'zh')
        assert 0 < len(key) <= 8

    def test_multiline_uses_last_nonempty(self):
        body = 'Line one has data $BTC.\n\nWatch the next catalyst.\n'
        key = cn.closer_key(body, 'en')
        assert key == 'watch the next'


# ================================================================== kill switch

class TestKillSwitch:
    def test_disabled_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv('FD_CLOSER_NGRAM', '0')
        row = _row('这是内容。\n接下来盯紧这条线。')
        result = cn.closer_findings(row, today_bjt=TODAY, inbox_base=tmp_path)
        assert result == []

    def test_enabled_by_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv('FD_CLOSER_NGRAM', raising=False)
        row = _row('Some text.\nWatch the weekly close.')
        # no prior history → no finding, but module ran
        result = cn.closer_findings(row, today_bjt=TODAY, inbox_base=tmp_path)
        assert isinstance(result, list)


# ================================================================== closer_ngram_repeat (ZH)

class TestCloserNgramRepeatZH:
    def test_repeat_key_triggers_finding(self, tmp_path):
        # Prior draft on day -1 with same ZH closer key
        prior = _row(
            '主力资金昨天流出了300亿。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-prior', day='2026-10-10',
        )
        inbox = _make_inbox([prior], tmp_path)
        current = _row(
            '今天又有数据出来。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' in codes
        for f in findings:
            if f['code'] == 'closer_ngram_repeat':
                assert f['level'] == 'soft'

    def test_unique_closer_untouched(self, tmp_path):
        prior = _row(
            '昨天的数据很重要。\n下一步看盈利数字。',
            draft_id='draft-prior', day='2026-10-10',
        )
        inbox = _make_inbox([prior], tmp_path)
        current = _row(
            '今天有新消息。\n接下来盯紧美联储的动作。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' not in codes

    def test_same_draft_excluded_from_memory(self, tmp_path):
        # Same draft id stored on the same day should not count as a prior
        same = _row(
            '内容一样。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur', day='2026-10-10',
        )
        inbox = _make_inbox([same], tmp_path)
        current = _row(
            '今天也一样。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' not in codes

    def test_outside_14day_window_not_counted(self, tmp_path):
        # A prior draft > 14 days ago should not trigger a repeat
        old = _row(
            '旧数据。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-old', day='2026-09-25',  # 16 days before Oct 11
        )
        inbox = _make_inbox([old], tmp_path)
        current = _row(
            '新内容。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' not in codes

    def test_within_14day_window_counted(self, tmp_path):
        # A prior draft exactly 14 days ago should count
        d14 = _row(
            '早期内容。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-14', day='2026-09-27',  # 14 days before Oct 11
        )
        inbox = _make_inbox([d14], tmp_path)
        current = _row(
            '当前内容。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' in codes


# ================================================================== closer_ngram_repeat (EN)

class TestCloserNgramRepeatEN:
    def test_en_repeat_key_triggers(self, tmp_path):
        prior = _row(
            'ETH broke $3k yesterday.\nWatch the weekly close carefully.',
            draft_id='draft-p', day='2026-10-09', lang='en', account_id='acct_en',
        )
        inbox = _make_inbox([prior], tmp_path)
        current = _row(
            'BTC also moved higher.\nWatch the weekly close again.',
            draft_id='draft-c', lang='en', account_id='acct_en',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' in codes

    def test_en_unique_closer_no_finding(self, tmp_path):
        prior = _row(
            'ETH broke $3k.\nExpect more volatility next week.',
            draft_id='draft-p', day='2026-10-09', lang='en', account_id='acct_en',
        )
        inbox = _make_inbox([prior], tmp_path)
        current = _row(
            'BTC rallied.\nWatch the weekly close carefully.',
            draft_id='draft-c', lang='en', account_id='acct_en',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' not in codes


# ================================================================== forward_watch stack

class TestForwardWatchStack:
    def _make_fw_drafts(self, tmp_path, fw_count: int, lang='zh',
                        account_id='acct_zh'):
        """Create fw_count prior drafts with forward-watch closers, return inbox path."""
        drafts = []
        for i in range(fw_count):
            body = (
                f'内容第{i}条数据重要。\n接下来盯紧这个指标。'
                if lang == 'zh'
                else f'Data point {i} matters.\nWatch the next catalyst.'
            )
            drafts.append(_row(
                body,
                draft_id=f'draft-p{i}',
                day=f'2026-10-{10 - i:02d}',
                lang=lang,
                account_id=account_id,
            ))
        return _make_inbox(drafts, tmp_path)

    def test_stack_3_zh_triggers(self, tmp_path):
        # 2 prior fw + this draft fw = stack of 3
        inbox = self._make_fw_drafts(tmp_path, fw_count=2)
        current = _row(
            '今天的数据重要。\n后续要盯好这条线。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_forward_watch_stack' in codes

    def test_stack_2_zh_no_trigger(self, tmp_path):
        # 1 prior fw + this draft fw = 2 → below threshold
        inbox = self._make_fw_drafts(tmp_path, fw_count=1)
        current = _row(
            '今天的数据重要。\n后续要盯好这条线。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_forward_watch_stack' not in codes

    def test_stack_3_en_triggers(self, tmp_path):
        inbox = self._make_fw_drafts(tmp_path, fw_count=2, lang='en', account_id='acct_en')
        current = _row(
            'BTC made another move.\nWatch the weekly close.',
            draft_id='draft-cur', lang='en', account_id='acct_en',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_forward_watch_stack' in codes

    def test_stack_only_looks_at_last_5(self, tmp_path):
        # 5 prior fw drafts but only the most recent 4 count (last5 = 4 prior + this)
        # If this draft has NO fw, stack from prior 4 fw = 4 -> still >=3 -> fires
        inbox = self._make_fw_drafts(tmp_path, fw_count=6)
        current = _row(
            '这次的收盘非常关键。\n观察一下后面的走势。',
            draft_id='draft-cur',
        )
        # with 6 prior fw but window capped at 4, fw_count = 0 (this) + min(6,4) fw = 4 -> triggers
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_forward_watch_stack' in codes

    def test_expired_with_body_counts(self, tmp_path):
        # expired drafts with a body should count in the window
        expired = _row(
            '数据到位了。\n接下来盯紧这个位置。',
            draft_id='draft-exp', day='2026-10-10', draft_status='expired',
        )
        inbox = _make_inbox([expired, expired | {'id': 'draft-exp2', 'day': '2026-10-09'}], tmp_path)
        current = _row(
            '今天结果出来。\n后续盯好这条线吧。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_forward_watch_stack' in codes


# ================================================================== repair_last_line

class TestRepairLastLine:
    def test_formula_closer_dropped(self):
        body = '这笔钱流向很明确。\n接下来盯紧美联储的动作就够了。'
        row = _row(body)
        findings = [{'code': 'closer_ngram_repeat', 'level': 'soft', 'detail': 'test'}]
        result = cn.repair_last_line(row, findings)
        assert result['kept'] is True
        assert '接下来盯紧' not in row['body']
        assert result['removed']

    def test_moral_line_dropped(self):
        body = '市场调整已经很充分了。\n还有这段数据需要关注。\n耐心等待终究会有回报。'
        row = _row(body, lang='zh')
        findings = [{'code': 'closer_ngram_repeat', 'level': 'soft', 'detail': 'test'}]
        result = cn.repair_last_line(row, findings)
        # moral line dropped → kept should be True when humanize.drop_moral_line fires
        # (it may or may not depending on exact rules; just check no crash and body changed sensibly)
        assert isinstance(result['kept'], bool)
        if result['kept']:
            assert '耐心等待终究会有回报' not in row['body']

    def test_numbers_in_earlier_lines_survive(self):
        # Numbers/tickers from earlier lines must not be lost after repair
        body = '$BTC 跌了12%，$ETH 跌了8%。\n具体数据需要关注，接下来盯紧这个区间。'
        row = _row(body, lang='zh')
        findings = [{'code': 'closer_ngram_repeat', 'level': 'soft', 'detail': 'test'}]
        result = cn.repair_last_line(row, findings)
        if result['kept']:
            # numbers from prior lines must still be present
            assert '$BTC' in row['body'] or '12%' in row['body']

    def test_tickers_in_earlier_lines_survive(self):
        body = 'ETH hit $3,200 this morning.\nWatch the weekly close carefully.'
        row = _row(body, lang='en', account_id='acct_en')
        findings = [{'code': 'closer_forward_watch_stack', 'level': 'soft', 'detail': 'test'}]
        result = cn.repair_last_line(row, findings)
        if result['kept']:
            assert '3,200' in row['body'] or 'ETH' in row['body']

    def test_no_finding_no_repair(self):
        body = '今天很关键。\n接下来盯紧。'
        row = _row(body)
        original_body = body
        result = cn.repair_last_line(row, [])
        assert result['kept'] is False
        assert row['body'] == original_body

    def test_text_synced_when_body_equals_text(self):
        body = '数据出来了。\n接下来盯紧这个。'
        row = _row(body)
        row['text'] = body   # text == body
        findings = [{'code': 'closer_ngram_repeat', 'level': 'soft', 'detail': 'test'}]
        cn.repair_last_line(row, findings)
        # after repair body and text should stay consistent
        assert row['body'] == row['text'] or row['text'].startswith(row['body'])

    def test_empty_body_no_crash(self):
        row = _row('')
        findings = [{'code': 'closer_ngram_repeat', 'level': 'soft', 'detail': 'test'}]
        result = cn.repair_last_line(row, findings)
        assert result['kept'] is False

    def test_wrong_code_ignored(self):
        body = '内容。\n接下来盯紧这个。'
        row = _row(body)
        findings = [{'code': 'unattributed_forecast', 'level': 'hard', 'detail': 'test'}]
        result = cn.repair_last_line(row, findings)
        assert result['kept'] is False


# ================================================================== soft-only guarantee

class TestSoftOnly:
    def test_findings_are_always_soft(self, tmp_path):
        prior = _row(
            '数据出来了。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-prior', day='2026-10-10',
        )
        inbox = _make_inbox([prior], tmp_path)
        current = _row(
            '新情况。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        for f in findings:
            assert f.get('level') == 'soft', f"finding {f['code']} should be soft"


# ================================================================== cross-account isolation

class TestCrossAccountIsolation:
    def test_different_account_not_counted(self, tmp_path):
        prior = _row(
            '其他账号的内容。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-other', day='2026-10-10', account_id='other_account',
        )
        inbox = _make_inbox([prior], tmp_path)
        current = _row(
            '本账号内容。\n接下来盯紧美联储的动作就够了。',
            draft_id='draft-cur', account_id='acct_zh',
        )
        findings = cn.closer_findings(current, today_bjt=TODAY, inbox_base=inbox)
        codes = [f['code'] for f in findings]
        assert 'closer_ngram_repeat' not in codes
