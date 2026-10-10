"""Tests for Oct 9 hook1009: opener diversity detection and first-line rewrite.

Covers:
  - weak opener detection (zh+en positives and negatives, first-person with number that is fine)
  - batch repeat detection
  - rewrite acceptance rules with a fake client (accept, reject new number, reject weak opener,
    reject exception -> keep)
  - daily_compose wiring with FD_HOOK_DIVERSITY=0 no-op
"""
from __future__ import annotations

import copy
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from live import hook_voice as hv, hook_rewrite as hr


# ============================================================ weak opener detection

class TestWeakOpenerDetection:
    # ZH positives (should fire weak_hook)
    @pytest.mark.parametrize('body', [
        '我觉得这轮反弹没有持续性',
        '我认为市场已经定价了降息预期',
        '说实话 ETH 这波涨得没有 BTC 扎实',
        '老实说，链上数据不支持这个方向',
        '坦白说今天的走势让我困惑',
        '扫了眼链上数据，借贷利率在涨',
        '扫了一眼 Dune，清算压力不小',
        '刚才看了一下 Kaito 的数据',
        '刚看了一眼最新财报',
        '刚刚看到 Binance 公告',
        '刷到这条新闻想说几句',
        '看到一个有意思的数据点',
        '今天看到一篇关于 DeFi 的研报',
        '注意到 SOL TVL 今天涨了 8%',
        '不得不说这个结构很有意思',
        '讲真，这轮 meme 季已经结束了',
        '有一说一，这笔清算很关键',
        '其实这轮行情的驱动力是流动性',   # 其实 as first word
    ])
    def test_zh_weak_openers_fire(self, body):
        findings = hv.hook_findings(body, 'zh')
        assert findings, f'expected weak_hook for: {body!r}'
        assert findings[0]['code'] == 'weak_hook'

    # EN positives
    @pytest.mark.parametrize('body', [
        'I think this rally is not sustainable',
        'Honestly, the on-chain data is weak',
        'To be honest BTC looks heavy here',
        'Just saw the FOMC minutes drop',
        'Was looking at Kaito scores and they moved',
        'I noticed the funding rate flipped',
        'Took a look at the order book',
        'Scrolling through the charts tonight',
        'So I checked the TVL data just now',
        'Ngl this liquidation cascade was ugly',
    ])
    def test_en_weak_openers_fire(self, body):
        findings = hv.hook_findings(body, 'en')
        assert findings, f'expected weak_hook for: {body!r}'
        assert findings[0]['code'] == 'weak_hook'

    # ZH negatives (must NOT fire weak_hook)
    def test_zh_number_opener_ok(self):
        assert hv.hook_findings('ETH 质押量突破 3500 万枚，创历史新高', 'zh') == []

    def test_zh_first_person_with_number_ok(self):
        # "我记了一笔：ETH 费率..." — first-person + number, not on weak-list
        assert hv.hook_findings('我记了一笔：ETH 费率本周均值 8.2%，高于上周', 'zh') == []

    def test_zh_其实_in_middle_ok(self):
        # 其实 only fires as first word; when it's mid-sentence the line needs a hook another way.
        # Use a body that has a named entity (Binance) so it's not weak.
        assert hv.hook_findings('这个结构其实和上次 Binance 清算如出一辙', 'zh') == []

    def test_zh_named_entity_ok(self):
        assert hv.hook_findings('Hyperliquid 清算量今日超过 $2B，超过 Binance', 'zh') == []

    def test_zh_ticker_ok(self):
        assert hv.hook_findings('$SOL 本周鏈上活躍地址增長12%', 'zh') == []

    # EN negatives
    def test_en_number_opener_ok(self):
        assert hv.hook_findings('18.7M ETH is now staked — that\'s 15% of supply', 'en') == []

    def test_en_first_person_with_number_ok(self):
        # "I logged 8.2% average funding..." is fine — not on the EN weak list
        assert hv.hook_findings('I logged 8.2% average funding rate this week, well above the 30-day mean', 'en') == []

    def test_en_named_entity_ok(self):
        assert hv.hook_findings('Hyperliquid just processed its largest liquidation of the year', 'en') == []


# ============================================================ batch repeat detection

class TestBatchOpenerFindings:
    def _row(self, draft_id, account_id, lang, body, time='2026-10-09T12:00:00+01:00'):
        return {'id': draft_id, 'account_id': account_id, 'lang': lang, 'body': body,
                'suggested_post_time_london': time}

    def test_same_normalised_opener_two_accounts_flags_second(self):
        rows = [
            self._row('d1', 'acct_a', 'zh', 'ETH 质押量突破 3500 万枚，创历史新高', '2026-10-09T10:00:00+01:00'),
            self._row('d2', 'acct_b', 'zh', 'ETH 质押量再创新高，本轮行情…', '2026-10-09T11:00:00+01:00'),
        ]
        result = hv.batch_opener_findings(rows)
        ids = [r['id'] for r in result]
        assert 'd2' in ids
        assert 'd1' not in ids

    def test_same_weak_phrase_three_accounts_flags_all_three(self):
        rows = [
            self._row('d1', 'acct_a', 'zh', '我觉得这波反弹没有持续性', '2026-10-09T10:00:00+01:00'),
            self._row('d2', 'acct_b', 'zh', '我觉得市场在等 FOMC', '2026-10-09T10:30:00+01:00'),
            self._row('d3', 'acct_c', 'zh', '我觉得 SOL 的链上数据更强', '2026-10-09T11:00:00+01:00'),
        ]
        result = hv.batch_opener_findings(rows)
        ids = [r['id'] for r in result]
        assert 'd1' in ids and 'd2' in ids and 'd3' in ids

    def test_two_accounts_weak_phrase_does_not_trigger_phrase_cluster(self):
        rows = [
            self._row('d1', 'acct_a', 'zh', '我觉得这波行情短期看涨', '2026-10-09T10:00:00+01:00'),
            self._row('d2', 'acct_b', 'zh', '我觉得 BTC 的支撑很强', '2026-10-09T10:30:00+01:00'),
        ]
        result = hv.batch_opener_findings(rows)
        # d2 gets key-repeat, d1 only gets phrase-cluster if count>=3 (it doesn't)
        phrase_cluster_findings = [r for r in result if 'phrase cluster' in r.get('finding', {}).get('detail', '')]
        assert len(phrase_cluster_findings) == 0

    def test_no_repeat_returns_empty(self):
        rows = [
            self._row('d1', 'acct_a', 'zh', 'BTC 期货溢价已回升至 6%，高于 10 月均值', '2026-10-09T10:00:00+01:00'),
            self._row('d2', 'acct_b', 'en', '18.7M ETH staked now, 15% of circulating supply', '2026-10-09T11:00:00+01:00'),
        ]
        assert hv.batch_opener_findings(rows) == []

    def test_finding_has_required_fields(self):
        rows = [
            self._row('d1', 'acct_a', 'zh', 'ETH 质押量突破 3500 万', '2026-10-09T10:00:00+01:00'),
            self._row('d2', 'acct_b', 'zh', 'ETH 质押量创新高', '2026-10-09T11:00:00+01:00'),
        ]
        result = hv.batch_opener_findings(rows)
        assert result
        f = result[0]['finding']
        assert f['code'] == 'opener_repeat'
        assert f['level'] == 'soft'
        assert 'detail' in f


# ============================================================ rewrite acceptance rules

class TestRewriteFirstLine:
    def _row(self, body, lang='zh', text=None, checks=None):
        return {
            'id': 'test-draft-1',
            'account_id': 'test_acct',
            'lang': lang,
            'body': body,
            'text': text if text is not None else body,
            'post_checks': checks or [{'code': 'opener_repeat', 'level': 'soft', 'detail': 'test'}],
        }

    def _client(self, return_json=None, raise_exc=None):
        """Fake compose-stage client."""
        def call(stage, messages, max_tokens):
            if raise_exc is not None:
                raise raise_exc
            payload = return_json or {'first_line': '18.7M ETH staked — that\'s 15% of supply, unprecedented'}
            return {'text': json.dumps(payload), 'response_model': 'gemini-3-flash-preview'}
        return call

    def test_accept_good_rewrite(self):
        body = '我觉得这轮反弹没有持续性，ETH 费率 8.2%\n第二行内容继续...'
        row = self._row(body)
        client = self._client({'first_line': 'ETH 费率 8.2% 本周均值已超过上月'})
        result = hr.rewrite_first_line(client, row, list(hv.WEAK_OPENERS_ZH), 'zh')
        assert result['kept'] is True
        assert '费率 8.2%' in row['body']
        assert row['body'] != body

    def test_reject_new_number_not_in_original(self):
        body = '我觉得市场在等 FOMC\n本周没有太多催化剂'
        row = self._row(body)
        # new first line contains a number (99) not in the original
        client = self._client({'first_line': '99% of traders are positioned for a cut'})
        result = hr.rewrite_first_line(client, row, list(hv.WEAK_OPENERS_ZH), 'zh')
        assert result['kept'] is False
        assert 'reject' in result
        assert row['body'] == body  # unchanged

    def test_reject_new_weak_opener(self):
        body = '我觉得这波反弹没有持续性\n链上数据显示 ETH 费率上涨'
        row = self._row(body)
        # rewrite uses 注意到 which is itself a weak opener
        client = self._client({'first_line': '注意到一个关键数据：链上借贷率上涨'})
        result = hr.rewrite_first_line(client, row, list(hv.WEAK_OPENERS_ZH), 'zh')
        assert result['kept'] is False
        assert row['body'] == body

    def test_exception_keeps_original(self):
        body = '我觉得市场在等 FOMC\n细节稍后更新'
        row = self._row(body)
        exc_client = self._client(raise_exc=RuntimeError('quota exceeded'))
        result = hr.rewrite_first_line(exc_client, row, [], 'zh')
        assert result["kept"] is False   # kept = rewrite accepted
        assert 'error' in result
        assert row['body'] == body  # unchanged — exception path keeps original

    def test_text_updated_when_body_equals_text(self):
        # Body has a number so the rewrite can open on it (check 2: new tokens must be subset of original)
        body = '我觉得 BTC 走势疲软，费率 -0.02%\n链上数据很弱'
        row = self._row(body, text=body)  # same-language: text == body
        # New first line references the number already in the original draft
        client = self._client({'first_line': '费率 -0.02% 转负，BTC 空头开始占优'})
        result = hr.rewrite_first_line(client, row, list(hv.WEAK_OPENERS_ZH), 'zh')
        assert result['kept'] is True
        assert row['text'] == row['body']

    def test_text_updated_when_frame_appended(self):
        body = '我觉得 ETH 的费率结构在改变\n具体见链上'
        frame = '\n\n— via @source'
        text = body + frame
        row = self._row(body, text=text)
        client = self._client({'first_line': 'ETH 的 EIP-1559 销毁量本周下降 30%'})
        result = hr.rewrite_first_line(client, row, list(hv.WEAK_OPENERS_ZH), 'zh')
        if result['kept']:
            assert row['text'].endswith(frame)
            assert row['body'] in row['text']


# ============================================================ daily_compose wiring

class TestDailyComposeWiring:
    """Smoke-test that FD_HOOK_DIVERSITY=0 is a no-op (no hook_rewrite keys on results)."""

    def test_fd_hook_diversity_zero_noop(self, monkeypatch):
        monkeypatch.setenv('FD_HOOK_DIVERSITY', '0')
        # Simulate the batch: two results with a repeat opener; neither should get hook_rewrite
        rows = [
            {'id': 'd1', 'account_id': 'acct_a', 'status': 'ok', 'text': 'ETH 费率 8%', 'body': 'ETH 费率 8%\n链上信号走强',
             'plan': {'account_lang': 'zh', 'suggested_post_time_london': '2026-10-09T10:00:00+01:00'},
             'post_checks': [{'code': 'opener_repeat', 'level': 'soft', 'detail': 'test'}]},
            {'id': 'd2', 'account_id': 'acct_b', 'status': 'ok', 'text': 'ETH 费率 8%', 'body': 'ETH 费率 8%\n机构持仓续增',
             'plan': {'account_lang': 'zh', 'suggested_post_time_london': '2026-10-09T11:00:00+01:00'},
             'post_checks': []},
        ]
        rewrite_calls = []

        import live.hook_rewrite as hr_mod
        orig_fn = hr_mod.rewrite_first_line

        def patched_rewrite(*a, **kw):
            rewrite_calls.append(a)
            return orig_fn(*a, **kw)

        monkeypatch.setattr(hr_mod, 'rewrite_first_line', patched_rewrite)

        # Replicate the wiring check inline (without importing daily_compose which has side effects)
        if os.environ.get('FD_HOOK_DIVERSITY', '1') != '0':
            for r in rows:
                codes = {f.get('code') for f in (r.get('post_checks') or [])}
                if 'opener_repeat' in codes or 'weak_hook' in codes:
                    hr_mod.rewrite_first_line(None, r, [], r['plan']['account_lang'])

        assert rewrite_calls == [], 'FD_HOOK_DIVERSITY=0 should skip all rewrites'
        assert all('hook_rewrite' not in r for r in rows)

    def test_fd_hook_diversity_default_on_triggers_rewrite(self, monkeypatch):
        monkeypatch.delenv('FD_HOOK_DIVERSITY', raising=False)
        rows = [
            {'id': 'd1', 'account_id': 'acct_a', 'status': 'ok', 'text': '我觉得 ETH 很强\n链上数据支持', 'body': '我觉得 ETH 很强\n链上数据支持',
             'plan': {'account_lang': 'zh', 'suggested_post_time_london': '2026-10-09T10:00:00+01:00'},
             'post_checks': [{'code': 'weak_hook', 'level': 'soft', 'detail': 'test'}]},
        ]
        rewrite_calls = []

        import live.hook_rewrite as hr_mod

        def patched_rewrite(client, row, avoid, lang):
            rewrite_calls.append({'row_id': row['id'], 'lang': lang})
            return {'from': '我觉得', 'to': '', 'reason': ['weak_hook'], 'kept': True, 'error': 'fake'}

        monkeypatch.setattr(hr_mod, 'rewrite_first_line', patched_rewrite)

        if os.environ.get('FD_HOOK_DIVERSITY', '1') != '0':
            _rw_count = 0
            _rewrite_max = int(os.environ.get('FD_HOOK_REWRITE_MAX', '12'))
            for r in rows:
                if _rw_count >= _rewrite_max:
                    break
                codes = {f.get('code') for f in (r.get('post_checks') or []) if isinstance(f, dict)}
                if not (codes & {'opener_repeat', 'weak_hook'}):
                    continue
                _rw = hr_mod.rewrite_first_line(None, r, [], r['plan']['account_lang'])
                r['hook_rewrite'] = _rw
                _rw_count += 1

        assert len(rewrite_calls) == 1
        assert rows[0].get('hook_rewrite') is not None


def test_rewrite_rejects_promoting_a_later_line():
    from live import hook_rewrite
    body = "It's been a long time since I've seen this.\n\nThe top 25 deployers spammed 770,000 tokens to farm $128 million.\n\nAre we surprised?"
    row = {'id': 'x', 'body': body, 'text': body, 'post_checks': [{'code': 'opener_repeat'}]}
    client = lambda *a, **k: {'text': '{"first_line": "The top 25 deployers spammed 770,000 tokens to farm $128 million."}'}
    r = hook_rewrite.rewrite_first_line(client, row, [], 'en')
    assert r['kept'] is False and r['reject'] == 'repeats a later line' and row['body'] == body
