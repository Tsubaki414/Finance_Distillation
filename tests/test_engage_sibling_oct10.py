"""Oct 10: second account on a shared target post must take a different angle / opening (prompt input, check,
one targeted rewrite)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from live import engage_sibling, engagement  # noqa: E402

URL = 'https://x.com/TedPillows/status/2108834040879173877'
SRC = {'title': 'ETFs sold $681,000,000 in $BTC and $542,000,000 in $ETH this week.', 'url': URL}
A = 'ETFs dumped $681,000,000 in BTC this week.\n\nAnother $542,000,000 in ETH went out the door with it.'
B = ('ETFs dumped $681 million in BTC and $542 million in ETH this week.\n\nSo much for institutional conviction.\n\n'
     'The second volatility hits, these new holders puke their bags back onto the market.')


def row(acct, text, mode='quote', rid=None, status='draft_ready', at='2026-10-10T10:00'):
    return {'id': rid or acct, 'account_id': acct, 'draft_status': status, 'text': text, 'body': text, 'stored_at': at,
            'engagement': {'mode': mode, 'url': URL, 'author': 'TedPillows'}, 'source': dict(SRC)}


def sib():
    return [{'account': 'crypto_alt_trader_en', 'mode': 'reply', 'text': A}]


def test_findings_first_line_and_lead_number():
    assert engagement.sibling_findings(B, sib())[0]['code'] == 'engage_sibling_repeat'
    assert 'same lead number' in engagement.sibling_findings('Outflows hit $681M while bids thinned.', sib())[0]['detail']
    assert engagement.sibling_findings('So much for institutional conviction: $542M of ETH left too.', sib()) == []
    assert engagement.sibling_findings(B, []) == []
    assert engagement.numbers('$681 million') == engagement.numbers('$681,000,000') == [681000000.0]
    f = engagement.findings(B, 'quote', 'en', siblings=sib())
    assert any(x['code'] == 'engage_sibling_repeat' for x in f)
    assert 'engage_sibling_repeat' in engagement.SOFT_CODES and 'engage_sibling_repeat' in engagement.REPAIR_TRIGGER


def test_siblings_other_accounts_same_post_only():
    rows = [row('crypto_alt_trader_en', A, 'reply', at='09:00'), row('crypto_thesis_en', B),
            dict(row('x_en', 'old', 'quote'), superseded=True), dict(row('y_en', 'h'), draft_status='needs_review')]
    s = engage_sibling.siblings(rows, rows[1])
    assert [x['account'] for x in s] == ['crypto_alt_trader_en'] and s[0]['text'] == A


def fake(text):
    return lambda stage, messages, n: {'text': json.dumps({'text': text})}


def test_rewrite_accepts_different_angle_and_rejects_bad():
    good = ('So much for institutional conviction.\n\nThe second volatility hits, these new holders puke $542 million '
            'of ETH back onto the market.')
    r = row('crypto_thesis_en', B)
    res = engage_sibling.rewrite(fake(good), r, sib(), 'en')
    assert res['kept'] and r['text'] == good and r['body'] == good and res['to'] == 'So much for institutional conviction.'
    r = row('crypto_thesis_en', B)
    assert engage_sibling.rewrite(fake(B), r, sib(), 'en')['reject'].startswith('still repeats')
    bad_num = 'So much for conviction.\n\nThe tourists sold 9,999 BTC and puke their bags onto the market again.'
    assert 'number' in engage_sibling.rewrite(fake(bad_num), row('crypto_thesis_en', B), sib(), 'en')['reject']
    assert engage_sibling.rewrite(fake(good), row('t', 'Something else entirely, 3 lines.'), sib(), 'en')['skipped']


def test_rewrite_error_keeps_draft():
    def boom(*a):
        raise RuntimeError('x')
    r = row('crypto_thesis_en', B)
    res = engage_sibling.rewrite(boom, r, sib(), 'en')
    assert not res['kept'] and res['error'] and r['text'] == B


def test_prompt_rule_and_off_switch(monkeypatch):
    assert 'different angle' in engagement.sibling_rule(sib())
    monkeypatch.setenv('FD_ENGAGE_SIBLING', '0')
    assert engagement.sibling_rule(sib()) is None and engagement.sibling_findings(B, sib()) == []


def test_day_engage_siblings_reads_inbox(monkeypatch):
    import daily_compose as dc
    from live import compose_inbox
    monkeypatch.setattr(compose_inbox, 'rows', lambda d=None, **k: [row('crypto_alt_trader_en', A, 'reply')])
    dc._SIB_ROWS.clear()
    s = dc.day_engage_siblings('2026-10-10', 'crypto_thesis_en', {'mode': 'quote', 'url': URL})
    assert s and s[0]['account'] == 'crypto_alt_trader_en'
    assert dc.day_engage_siblings('2026-10-10', 'crypto_alt_trader_en', {'mode': 'reply', 'url': URL}) == []
    dc._SIB_ROWS.clear()


def test_engage_sibling_pass_rewrites_later_run_draft(monkeypatch):
    import threading
    from datetime import date
    from types import SimpleNamespace
    import daily_compose as dc
    from live import compose_inbox
    monkeypatch.setattr(compose_inbox, 'rows', lambda d=None, **k: [])
    good = 'So much for institutional conviction.\n\nThese new holders puke $542 million of ETH back onto the market.'
    eng = {'mode': 'quote', 'url': URL, 'author': 'TedPillows'}
    r1 = {'id': 'a', 'account_id': 'crypto_alt_trader_en', 'draft_status': 'draft_ready', 'body': A, 'text': A,
          'plan': {'engagement': dict(eng, mode='reply'), 'suggested_post_time_london': '2026-10-10T10:00'}}
    r2 = {'id': 'b', 'account_id': 'crypto_thesis_en', 'draft_status': 'draft_ready', 'body': B, 'text': B,
          'plan': {'engagement': eng, 'title': SRC['title'], 'suggested_post_time_london': '2026-10-10T10:30', 'account_lang': 'en'}}
    args = SimpleNamespace(day=date(2026, 10, 10), budget_usd=1.0)
    dc.engage_sibling_pass([r2, r1], args, lambda: fake(good), threading.Lock(), {'usd': 0.0}, {}, 0.01, True,
                           lambda: 0)
    assert r1['text'] == A and 'engage_sibling' not in r1
    assert r2['engage_sibling']['kept'] and r2['text'] == good
