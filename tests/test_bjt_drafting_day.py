"""Oct 7: the daily run moves to 23:13 London; the drafting day is the Beijing calendar date everywhere."""
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LONDON = ZoneInfo('Europe/London')


def _script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_23_13_london_drafts_for_the_next_beijing_day_bst_and_gmt():
    dc = _script('daily_compose')
    bst = datetime(2026, 10, 7, 23, 13, tzinfo=LONDON)        # 06:13 Beijing on 10-08
    gmt = datetime(2026, 10, 27, 23, 13, tzinfo=LONDON)       # after 25 Oct: 07:13 Beijing on 10-28
    assert dc.drafting_day(bst) == date(2026, 10, 8)
    assert dc.drafting_day(gmt) == date(2026, 10, 28)
    assert dc.drafting_day(datetime(2026, 10, 7, 5, 13, tzinfo=LONDON)) == date(2026, 10, 7)   # old schedule unchanged


def test_selection_ref_is_the_run_time_not_a_future_morning():
    dc = _script('daily_compose')
    now = datetime(2026, 10, 7, 23, 13, tzinfo=LONDON)
    ref = dc.selection_ref(date(2026, 10, 8), now)
    assert ref == now and ref.tzinfo == timezone.utc
    # the US session of 10-07 (13:30-20:00 UTC) is inside the 30h timely window and the UTC freshness date is 10-07
    assert ref.date() == date(2026, 10, 7)
    us_close = {'source': {'published_at': '2026-10-07T20:00:00Z'}}
    assert dc.timely([us_close], ref)
    assert dc.timely([{'source': {'published_at': '2026-10-06T17:00:00Z'}}], ref)   # previous ~24h+ still in
    # backfill of an older day: 08:00 Beijing of that day
    later = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert dc.selection_ref(date(2026, 10, 8), later) == datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc)
    # a run later on the day itself sees posts up to now
    same_day = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
    assert dc.selection_ref(date(2026, 10, 8), same_day) == same_day


def test_chart_refresh_days_are_beijing_dates():
    rc = _script('refresh_charts')
    assert rc.default_days(datetime(2026, 10, 7, 23, 30, tzinfo=LONDON)) == ['2026-10-08', '2026-10-09']
    assert rc.default_days(datetime(2026, 10, 7, 1, 0, tzinfo=LONDON)) == ['2026-10-07', '2026-10-08']


def test_ingest_summary_named_by_beijing_day():
    from live.daily_ingest import bjt_stamp
    assert bjt_stamp(datetime(2026, 10, 7, 23, 13, tzinfo=LONDON)) == '20261008'
    assert bjt_stamp(datetime(2026, 10, 7, 5, 13, tzinfo=LONDON)) == '20261007'


def test_quote_freshness_ends_with_the_beijing_day():
    from live import post_mode
    # day 10-08 ends 2026-10-08T16:00Z; 72h before that is 10-05T16:00Z
    assert post_mode._fresh({'published_at': '2026-10-05T17:00:00Z'}, '2026-10-08')
    assert not post_mode._fresh({'published_at': '2026-10-05T15:00:00Z'}, '2026-10-08')


def _digest(tmp_path, day, ticker='HYPE'):
    entry = {'title': f'Perp venues and {ticker} order flow', 'url': f'https://members.delphidigital.io/r/{day}',
             'date': day, 'kind': 'report', 'tickers': [ticker], 'thesis_summary': 'Our read: perp venues keep gaining share on fee discounts.',
             'key_numbers': [{'value': '62%', 'context': 'largest venue share of on-chain perp volume'}]}
    (tmp_path / f'{day}.json').write_text(json.dumps([entry]))


def test_delphi_latest_within_36h_not_exact_day(tmp_path):
    from live.adapters import delphi_digest as dd
    _digest(tmp_path, '2026-10-07')
    run = datetime(2026, 10, 7, 23, 13, tzinfo=LONDON)        # drafting day 10-08 has no digest of its own
    got = dd.latest(now=run, directory=tmp_path)
    assert got['day'] == '2026-10-07' and got['age_h'] == 23.2 and dd.steer_tickers(got['units']) == {'HYPE': 1}
    # a day later the 10-07 file is 47h old: no steer
    assert dd.latest(now=run + timedelta(days=1), directory=tmp_path)['units'] == []
    # a newer file wins; a Beijing-dated (one day ahead) file also counts
    _digest(tmp_path, '2026-10-08', 'ETH')
    assert dd.latest(now=run, directory=tmp_path)['day'] == '2026-10-08'
    assert dd.latest(now='2026-10-07T22:13:00Z', directory=tmp_path)['day'] == '2026-10-08'
    assert dd.latest(now=run, directory=tmp_path / 'none')['status'] == 'missing'
