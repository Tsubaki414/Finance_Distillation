from datetime import date
import pytest
from live import freshness
from live.adapters.common import make_source
from live.reportgem_daily import to_source

@pytest.fixture(autouse=True)
def fixed_today(monkeypatch): monkeypatch.setattr(freshness,'today',lambda:date(2026,10,4))


def test_empty_sources():
    assert make_source(id='x',source_id='x',text='hello',publisher='x',title='x',url='',published_at='',adapter='x')['published_at'] is None
    item={'source_id':'x','bank':'Goldman Sachs','title':'x','published_at':'','source_type':'en'}
    assert to_source(item,{'passages':[{'text':'Research evidence with sufficient length to constitute a meaningful excerpt from the source report.'}]})['published_at'] is None


@pytest.mark.parametrize('raw',['','T00:00:00Z'])
def test_missing(raw):
    flags=freshness.derive_dates({'source':{'published_at':raw},'unit':{}})['freshness_flags']
    assert 'missing_published_at' in flags and 'malformed_published_at' not in flags


def test_forward_and_future():
    r=freshness.derive_dates({'source':{'published_at':'2026-10-04'},'unit':{'numbers':[{'period':'Q4 2026'}]}})
    assert 'forward_period_skipped' in r['freshness_flags'] and 'future_date' not in r['freshness_flags']
    r=freshness.derive_dates({'source':{'published_at':'2026-11-17'},'unit':{}})
    assert 'future_published_at' in r['freshness_flags'] and r['date_unknown']


def test_backfill_recovery(tmp_path):
    import json
    from scripts.backfill_freshness import backfill
    cache=tmp_path/'cache';cache.mkdir()
    rows=[{'unit_id':'url','source':{'url':'https://example.test/2026/10/02/report','published_at':'T00:00:00Z'},'unit':{}},
          {'unit_id':'feed','source':{'id':'episode','url':'https://example.test/episode','published_at':''},'unit':{}}]
    (tmp_path/'units.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (cache/'feed.rss').write_text('<rss><channel><item><link>https://example.test/episode</link><pubDate>Sat, 03 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>')
    entries=backfill(tmp_path,True,[cache])
    assert [r['published_at'] for r in entries]==['2026-10-02','2026-10-03']
    assert all('missing_published_at' not in r['freshness_flags'] for r in entries)


def test_market_flow_ages_in_business_days():
    from datetime import datetime, timezone
    from live import freshness as f
    row = {'unit': {'kind': 'fact', 'statement': 'SPX gamma flip at 6,600', 'as_of': '2026-10-01',
                    'published_at': '2026-10-01', 'date_unknown': False},
           'source': {'adapter': 'channel:feed_linkfollow', 'source_id': 'ch096_spotgamma_com'}}
    sunday = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)   # Thu -> Sun = 1 business day
    assert f.status(row, sunday)['status'] == 'fresh'
    # Fiona's 10/5 shelf policy (market flow shelf = 1 business day): stale after 1, expired after 2.
    monday = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)   # Thu -> Mon = 2 business days
    assert f.status(row, monday)['status'] == 'stale'
    tuesday = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)  # Thu -> Tue = 3 business days
    assert f.status(row, tuesday)['status'] == 'expired'
    # commentary keeps calendar days (10/5 commentary shelf = 5 days: stale after 5, expired after 10)
    row['source'] = {'adapter': 'newsletter_rss', 'source_id': 'nl-x'}
    assert f.status(row, datetime(2026, 10, 8, tzinfo=timezone.utc))['status'] == 'stale'
    assert f.status(row, datetime(2026, 10, 20, tzinfo=timezone.utc))['status'] == 'expired'
