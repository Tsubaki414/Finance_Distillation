"""Offline contract for the planned channel ingestion layer."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from live.adapters import channels
from scripts.sync_channels_registry import sync
from scripts import source_utilization as utilization

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures/channels'
BODY = 'Public research explains financial markets and economic developments. ' * 40

def channel(mode='feed_linkfollow', **kw):
    return dict(channel_id='test_channel', name='Research', mode=mode, url='https://example.com/index/',
                feed_url='https://example.com/feed', lang='en', licence_tier='B', no_reproduction=True, **kw)

@pytest.mark.parametrize('prefix', ['ch021_', 'ch076_', 'ch078_'])
def test_fulltext_fixtures(prefix):
    ch = next(c for c in channels.load_channels(ROOT/'live/channels.json') if c['channel_id'].startswith(prefix))
    fixture = (FIX/(ch['channel_id']+'.xml')).read_text()
    calls = []
    def transport(url, headers):
        calls.append(url)
        return 200, fixture if url == ch['feed_url'] else '<article>'+BODY+'</article>'
    out = channels.fetch_channel(ch, transport=transport)
    assert out['status'] == 'ok' and len(out['sources']) == 1
    assert out['sources'][0]['source_id'] == ch['channel_id']
    assert len(out['sources'][0]['original_text']) >= 1500
    assert out['requests'] == len(calls) == 1

@pytest.mark.parametrize('prefix', ['ch043_', 'ch044_', 'ch059_'])
def test_linkfollow_fixtures(prefix):
    ch = next(c for c in channels.load_channels(ROOT/'live/channels.json') if c['channel_id'].startswith(prefix))
    fixture = (FIX/(ch['channel_id']+'.xml')).read_text()
    out = channels.fetch_channel(ch, transport=lambda u,h: (200, fixture if u == ch['feed_url'] else '<article>'+BODY+'</article>'))
    assert out['status'] == 'ok' and out['requests'] == 2

@pytest.mark.parametrize('prefix', ['ch019_', 'ch026_', 'ch056_'])
def test_index_fixtures(prefix):
    ch = next(c for c in channels.load_channels(ROOT/'live/channels.json') if c['channel_id'].startswith(prefix))
    fixture = (FIX/(ch['channel_id']+'.html')).read_text()
    out = channels.fetch_channel(ch, transport=lambda u,h: (200, fixture if u == ch['url'] else '<article>'+BODY+'</article>'))
    assert out['sources'] and out['requests'] >= 2

FEED = '<rss><channel><item><title>Research</title><link>https://example.com/article/research</link></item></channel></rss>'
@pytest.mark.parametrize('page,reason', [('<article>'+BODY+' Subscribe to continue</article>', 'paywall'), ('<p>short</p>', 'short')])
def test_rejected_text_is_only_radar(page, reason):
    out = channels.fetch_channel(channel(), transport=lambda u,h: (200, FEED if u.endswith('feed') else page))
    assert not out['sources'] and out['status'] == 'radar'
    assert reason in out['radar'][0]['reason']

def test_newest_and_fulltext_fallback():
    feed = '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'+''.join(
        f'<item><title>{day}</title><link>https://example.com/a/{day}</link><pubDate>{day} Oct 2026 00:00:00 GMT</pubDate><content:encoded><![CDATA[<p>short</p>]]></content:encoded></item>' for day in ('01','03'))+'</channel></rss>'
    out = channels.fetch_channel(channel('feed_fulltext'), transport=lambda u,h: (200, feed if u.endswith('feed') else '<p>'+BODY+'</p>'))
    assert out['sources'][0]['url'].endswith('/03')
    assert out['sources'][0]['no_reproduction'] is True

@pytest.mark.parametrize('cid,body', [('ch001_data_eastmoney_com', {'data':[{'title':'Report', 'orgSName':'Broker','ratingName':'Buy'}]}), ('ch064_www1_hkexnews_hk', {'data':[{'TITLE':'Announcement'}]})])
def test_json_titles_are_not_units(cid, body):
    ch = channel('json_api'); ch['channel_id'] = cid
    out = channels.fetch_channel(ch, transport=lambda u,h: (200,json.dumps(body)))
    assert out['status'] == 'radar' and not out['sources'] and out['radar']

def test_validation(tmp_path):
    for bad in [dict(channel(),mode='invalid'), dict(channel(),mode='excluded',reason=''), dict(channel(),mode='podcast_audio',reason='')]:
        p=tmp_path/'channels.json'; p.write_text(json.dumps({'channels':[bad]}))
        with pytest.raises(ValueError): channels.load_channels(p)
    assert len(channels.load_channels(ROOT/'live/channels.json')) == 138

def test_batching():
    rows = [dict(channel(),channel_id=str(i)) for i in range(11)]
    batches = [channels.select_channels(rows, batch=f'{k}/3') for k in (1,2,3)]
    assert [c for b in batches for c in b] == rows
    assert max(map(len,batches))-min(map(len,batches)) <= 1
    with pytest.raises(ValueError): channels.select_channels(rows,batch='0/3')

def test_sync_idempotent(tmp_path):
    reg=tmp_path/'registry.json'; lic=tmp_path/'licence.json'
    reg.write_text('{"sources": []}'); lic.write_text('{"tiers": {}}')
    sync(ROOT/'live/channels.json',reg,lic)
    first=(reg.read_bytes(),lic.read_bytes()); sync(ROOT/'live/channels.json',reg,lic)
    assert first == (reg.read_bytes(),lic.read_bytes())
    planned=[c for c in channels.load_channels(ROOT/'live/channels.json') if c['mode']!='excluded']
    assert len(json.loads(reg.read_text())['sources']) == len(planned)
    assert all(json.loads(lic.read_text())['tiers'][c['channel_id']]['no_reproduction']==c['no_reproduction'] for c in planned)

def test_utilization_reasons(tmp_path):
    cs=channels.load_channels(ROOT/'live/channels.json')
    result=utilization.audit({'sources':cs},{'sources':[]},{'tiers':{}},{},tmp_path/'store',tmp_path/'tags',
                             runs=[{'adapters':{'channels':[{'channel_id':cs[1]['channel_id'],'status':'radar','reason':'titles only'}]}}])
    assert len(result['channels'])==138
    assert result['channels'][1]['fetch_outcome']=='radar'
    assert result['channels'][1]['reason']=='titles only'
    assert all(r['reason'] for r in result['channels'] if r['units']==0)

def test_hkex_actual_fixture():
    ch=next(c for c in channels.load_channels(ROOT/'live/channels.json') if c['channel_id'].startswith('ch064_'))
    out=channels.fetch_channel(ch,transport=lambda u,h:(200,(FIX/(ch['channel_id']+'.json')).read_text()))
    assert out['status']=='radar' and out['radar'][0]['reason']=='titles only'
    assert not out['sources']

def test_eastmoney_public_detail():
    ch=channel('json_api');ch['channel_id']='ch001_data_eastmoney_com'
    calls=[]
    def transport(url,headers):
        calls.append(url)
        return 200,json.dumps({'data':[{'title':'Research','infoCode':'AP20261004001'}]}) if 'reportapi' in url else '<article>'+BODY+'</article>'
    out=channels.fetch_channel(ch,transport=transport)
    assert out['status']=='ok' and len(calls)==2
    assert calls[1]=='https://data.eastmoney.com/report/info/AP20261004001.html'

def test_cninfo_post():
    ch=channel('json_api');ch['channel_id']='ch063_www_cninfo_com_cn'
    calls=[]
    def transport(url,headers,**kwargs):
        calls.append(kwargs)
        return 200,json.dumps({'announcements':[{'announcementTitle':'Annual report'}]})
    out=channels.fetch_channel(ch,transport=transport)
    assert calls[0]['method']=='POST' and calls[0]['data']['pageNum']==1
    assert out['status']=='radar' and not out['sources']

def test_index_order_filters_and_retry():
    ch=channel('html_index')
    index=''.join(f'<div><a href="{href}">{label}</a></div>' for href,label in [
        ('https://evil-example.com/a/b','A long headline from another domain'),
        ('/tag/markets','A long tag navigation label'),
        ('/2026/10/01/old','An older public research article'),
        ('/2026/10/04/new','最新经济研究分析报告标题'),
        ('/2026/10/03/next','The next newest public research article')])
    calls=[]
    def transport(url,headers):
        calls.append(url)
        return 200,index if url==ch['url'] else '<p>short</p>' if url.endswith('/new') else '<article>'+BODY+'</article>'
    out=channels.fetch_channel(ch,transport=transport)
    assert out['status']=='ok' and calls[1].endswith('/new') and calls[2].endswith('/next')
    assert len(calls)==3 and len(out['radar'])==1

@pytest.mark.parametrize('official',[True,False])
def test_pdf_converter_and_access(official):
    ch=channel();ch['feed_url']='https://agency.gov/feed' if official else ch['feed_url']
    feed=FEED.replace('https://example.com/article/research','https://agency.gov/reports/study.pdf' if official else 'https://example.com/reports/study.pdf')
    calls=[]
    def transport(url,headers):
        calls.append(url);return 200,feed if url==ch['feed_url'] else b'%PDF stub'
    out=channels.fetch_channel(ch,transport=transport,converter=lambda raw:BODY)
    assert bool(out['sources']) == official
    assert len(calls)==(2 if official else 1)

def test_gather_channels_reports_outcome(monkeypatch):
    from scripts import run_content_adapters as runner
    ch=channels.load_channels(ROOT/'live/channels.json')[1]
    monkeypatch.setattr(channels,'fetch_channel',lambda ch,**kw:dict(status='radar',requests=1,sources=[],radar=[{'reason':'titles only'}],reason='titles only'))
    args=SimpleNamespace(adapters=['channels'],channel_modes=['json_api'],channel_ids=[ch['channel_id']],channel_batch=None,channel_limit=1)
    report={'adapters':{}}
    sources,data=runner.gather(args,report)
    assert sources==data==[]
    assert report['adapters']['channels'][0]['channel_id']==ch['channel_id']
    assert report['adapters']['channels'][0]['status']=='radar'

def test_planned_ids_do_not_share_units():
    first=channel();second=dict(first,channel_id='different_channel')
    stored={'source':{'source_id':first['channel_id'],'publisher':first['name'],'url':'https://example.com/article/research'}}
    assert utilization.match_channel(first,stored)
    assert not utilization.match_channel(second,stored)

def test_registrable_domain_and_central_bank_pdf():
    assert channels._domain('https://news.example.co.nz/a') == channels._domain('https://www.example.co.nz/b')
    assert channels._domain('https://example.co.nz/a') != channels._domain('https://evil.co.nz/b')
    ch=next(c for c in channels.load_channels(ROOT/'live/channels.json') if c['channel_id'].startswith('ch045_'))
    assert channels._pdf_allowed(ch,'https://www.boj.or.jp/en/research/paper.pdf')
    assert not channels._pdf_allowed(ch,'https://unrelated.com/research/paper.pdf')

def test_utilization_cli_runs_directory(tmp_path):
    import subprocess
    import sys
    run=tmp_path/'runs'/'batch1';run.mkdir(parents=True)
    (run/'report.json').write_text(json.dumps({'adapters':{'channels':[{'channel_id':'ch001_data_eastmoney_com','status':'radar','reason':'titles only'}]}}))
    roster=tmp_path/'roster.json';roster.write_text('{}')
    output=tmp_path/'audit.json'
    subprocess.run([sys.executable,str(ROOT/'scripts/source_utilization.py'),'--store',str(tmp_path/'store'),
                    '--roster',str(roster),'--runs',str(tmp_path/'runs'),'--out-md',str(tmp_path/'audit.md'),
                    '--out-json',str(output)],check=True,capture_output=True)
    result=json.loads(output.read_text())
    assert len(result['channels'])==138
    assert result['channels'][1]['fetch_outcome']=='radar'
    assert result['channels'][1]['reason']=='titles only'
