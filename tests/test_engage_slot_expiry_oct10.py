"""Oct 10: an unposted engagement draft whose target window closed frees the account's engagement slot (marked
expired); a posted one keeps it. Same window logic as the ops slotter (engagement.window_close)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from live import engagement  # noqa: E402

NOW = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)


def row(rid='e1', acct='a', age_h=11.5, likes=300, views=20000, mode='quote', lang='en'):
    pub = (NOW - timedelta(hours=age_h)).isoformat()
    return {'id': rid, 'account_id': acct, 'lang': lang, 'draft_status': 'draft_ready', 'text': 't', 'body': 't',
            'post_mode': mode, 'post_format': {'engage': mode}, 'source': {'published_at': pub},
            'engagement': {'mode': mode, 'likes': likes, 'views': views, 'url': f'https://x.com/h/status/{rid}9'}}


def test_window_close_modes():
    assert engagement.window_close(row(age_h=0, mode='reply')) == NOW + timedelta(hours=6)
    assert engagement.window_close(row(age_h=0)) == NOW + timedelta(hours=12)
    assert engagement.window_close(row(age_h=0, likes=900)) == NOW + timedelta(hours=18)   # extended (en >= 500)
    assert engagement.window_close({'post_mode': 'original', 'source': {'published_at': NOW.isoformat()}}) is None


def test_slot_expired_rules():
    assert engagement.slot_expired(row(age_h=11.5), NOW)                    # closes in 30 min < 50 min lead
    assert not engagement.slot_expired(row(age_h=11.5), NOW, published=True)
    assert not engagement.slot_expired(row(age_h=8), NOW)
    assert not engagement.slot_expired(row(age_h=11.5, likes=900), NOW)     # 18h window
    assert engagement.is_published({'published': True}) and engagement.is_published({'action': 'published'})
    assert not engagement.is_published({'action': 'published', 'published': False})


def test_day_slots_frees_expired_and_keeps_posted(tmp_path, monkeypatch):
    import daily_compose as dc
    from live import compose_inbox
    monkeypatch.setenv('FD_COMPOSE_INBOX', str(tmp_path / 'inbox'))
    day = '2026-10-10'
    for r in (row('old', 'a', age_h=13), row('posted', 'b', age_h=13), row('fresh', 'c', age_h=2)):
        p = tmp_path / 'inbox' / day / f"{r['id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(r, day=day)))
    monkeypatch.setattr(dc, 'admin_decisions', lambda d: {'posted': {'published': True}})
    monkeypatch.setattr(compose_inbox, 'rows', lambda d=None, **k: [json.loads(p.read_text())
                                                                     for p in sorted((tmp_path / 'inbox' / day).glob('*.json'))])
    real = dc.datetime

    class FakeDT(real):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(dc, 'datetime', FakeDT)
    out = dc.day_slots(day)
    assert 'a' not in out and out['b']['engage'] == 1 and out['c']['engage'] == 1
    saved = json.loads((tmp_path / 'inbox' / day / 'old.json').read_text())
    assert saved['draft_status'] == 'expired' and saved['expired']['window_close']
    assert engagement.DayState.from_rows([saved]).ready == {}
