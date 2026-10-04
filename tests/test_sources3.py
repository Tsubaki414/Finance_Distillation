import json
from pathlib import Path
from unittest.mock import patch
from live.adapters import fed, feeds

FIX = Path('tests/fixtures/sources3')
def transport(file):
    return lambda url, headers: (200, (FIX / file).read_text())


def test_wallstreetcn_public_only():
    from live.adapters import wallstreetcn
    def get(url, headers):
        return 200, (FIX / ('wscn_us.json' if 'information-flow' in url else 'wscn_article.json')).read_text()
    out = wallstreetcn.fetch(limit=1, transport=get)
    assert out['sources'][0]['source_language'] == 'zh'
    assert out['sources'][0]['no_reproduction'] is True
    assert '<p' not in out['sources'][0]['original_text']
    assert wallstreetcn.is_paid({'vip': True})
    assert wallstreetcn.is_paid({'is_priced': True})


def test_nyfed_numbers():
    from live.adapters import nyfed
    out = nyfed.fetch(transport=transport('nyfed_sofr.json'))
    assert len(out['units']) == 5
    assert out['sources'][0]['source_id'] == 'primary_nyfed'
    assert {n['text'] for u in out['units'] for n in u['numbers']} >= {'3.87 percent', '3.83 percent', '3.97 percent', '3067 $bn', '-0.03 percentage points'}
    assert all(u['licence_tier'] == 'A' for u in out['units'])


def test_fomc_public_statement():
    def get(url, headers):
        return (200, (FIX / 'www_federalreserve_gov_feeds_press_monetary_xml.xml').read_text()) if 'feeds/' in url else (200, '<div id="article"><p>The Committee decided to maintain the target range.</p></div>')
    out = fed.fetch('fomc', limit=1, transport=get)
    assert out['sources'][0]['fed_kind'] == 'fomc'
    assert 'Committee decided' in out['sources'][0]['original_text']


def test_radar_titles_never_extracted():
    with patch('live.analysis_corpus.fetch_feed', return_value=([{'text': 'x'*900, 'content_complete': False, 'extraction_status': 'feed_title', 'title': 'x'*900}], None)):
        out = feeds.fetch_newsletter({'id': 'test', 'feed_url': 'https://example.com/feed'})
    assert out['status'] == 'radar_only'; assert not out['sources']


def test_retry_split_preserves_contract():
    from scripts.rerun_failed_extracts import split_source
    from tests.test_content_store import source
    s = source('First paragraph.\n\nSecond paragraph.\n\nThird paragraph.')
    a, b = split_source(s)
    assert [a['id'], b['id']] == [s['id']+'-a', s['id']+'-b']
    assert a['original_text']+'\n\n'+b['original_text'] == s['original_text']
    assert a['source_hash'] != b['source_hash']


def test_six_fulltext_fixtures():
    from scripts.run_content_adapters import newsletter_feeds, RSS_FULLTEXT
    filenames = {'apricitas':'www_apricitas_io_feed.xml', 'employ_america':'www_employamerica_org_feed_.xml',
                 'daily_shot_brief':'dailyshotbrief_substack_com_feed.xml', 'chipstrat':'www_chipstrat_com_feed.xml',
                 'wu_blockchain':'wublock_substack_com_feed.xml', 'coinshares_research':'blog_coinshares_com_feed.xml'}
    rows = [r for r in newsletter_feeds() if r['id'] in RSS_FULLTEXT]
    assert len(rows) == 6
    for row in rows:
        out = feeds.fetch_newsletter(row, limit=1, transport=transport(filenames[row['id']]))
        if row['id'] == 'chipstrat':
            # Captured article ends in Read more: preserve the existing completeness gate.
            assert out['status'] == 'radar_only' and not out['sources']
            continue
        assert out['status'] == 'ok', (row['id'], out)
        assert len(out['sources'][0]['original_text']) >= 800


def test_title_only_fixtures():
    filenames = ['hedgopia_com_feed_.xml', 'spotgamma_com_feed_.xml', 'seekingalpha_com_market_currents_xml.xml',
                 'www_techflowpost_com_rss_aspx.xml', 'www_federalreserve_gov_feeds_press_monetary_xml.xml',
                 'www_ecb_europa_eu_rss_press_html.xml']
    for file in filenames:
        out = feeds.fetch_newsletter({'id': file, 'feed_url': 'https://example.com/feed'}, transport=transport(file))
        assert out['status'] == 'radar_only', (file, out)
        assert not out['sources']


def test_earnings_age_and_megacap(tmp_path):
    from datetime import date
    from live.adapters import edgar
    from scripts.run_content_adapters import MEGACAP, gather
    from types import SimpleNamespace
    assert set(MEGACAP) <= set(edgar.WATCHLIST)
    submissions = {'name':'Apple', 'cik':320193, 'filings':{'recent':{'form':['8-K'], 'items':['2.02'],
                  'filingDate':['2025-01-01'], 'accessionNumber':['a'], 'primaryDocument':['a.htm']}}}
    calls = []
    def get(url, headers):
        calls.append(url); return 200, json.dumps(submissions)
    assert not edgar.fetch('AAPL', max_age_days=120, as_of=date(2026,10,4), transport=get)['sources']
    assert len(calls) == 1
    args = SimpleNamespace(adapters=['edgar'], tickers=['MU','NVDA'], earnings_tickers=['megacap'], max_age_days=120, oaktree_n=3, glassnode_n=3)
    with patch.object(edgar, 'fetch', return_value={'status':'ok','sources':[]}) as fetch:
        gather(args, {'adapters':{}})
    assert fetch.call_count == 11
    assert all(c.kwargs['earnings_only'] and c.kwargs['limit'] == 1 and c.kwargs['max_age_days'] == 120 for c in fetch.call_args_list)


def test_retry_budget_split_and_resume(tmp_path, monkeypatch):
    from scripts.rerun_failed_extracts import retry_run
    from live.content_store import ContentStore
    from tests.test_content_store import source
    from ml import budget
    run = tmp_path/'run'; run.mkdir()
    s = source('Payrolls rose 22,000.\n\nPayrolls rose 23,000.'); s['id'] = 'failed'
    (run/'sources.json').write_text(json.dumps({'text':[s]}))
    (run/'report.json').write_text(json.dumps({'sources':[{'id':'failed','status':'extract_failed','error':'ContractError: extract: Expecting value: line 1 column 1 (char 0)'}]}))
    for name in ('STORE','LEDGER','RUNS','DISTILLATION_RUNS'):
        monkeypatch.setattr(budget, name, getattr(budget,name))
    calls=[]
    def client(stage, messages, limit):
        calls.append(messages)
        return {'finish_reason':'stop', 'text':'{"units":[]}', 'refusal':False}
    store=ContentStore(tmp_path/'store')
    result=retry_run(run,store,cap_usd=6,client=client)
    assert len(calls)==2
    assert budget.cap()==6
    assert [r['id'] for r in result['failed']['attempts']]==['failed-a','failed-b']
    retry_run(run,store,cap_usd=6,client=client)
    assert len(calls)==2


def test_retry_does_not_relax_contract(tmp_path, monkeypatch):
    from scripts.rerun_failed_extracts import retry_run
    from tests.test_content_store import source
    from live.content_store import ContentStore
    from ml import budget
    for name in ('STORE','LEDGER','RUNS','DISTILLATION_RUNS'):
        monkeypatch.setattr(budget,name,getattr(budget,name))
    s=source(); run=tmp_path/'run'; run.mkdir()
    (run/'sources.json').write_text(json.dumps({'text':[s]}))
    (run/'report.json').write_text(json.dumps({'sources':[{'id':s['id'],'status':'extract_failed','error':'BudgetExceeded: cap'}]}))
    def client(*args): return {'finish_reason':'stop','text':'{"units":[{"statement":"invented"}]}'}
    store=ContentStore(tmp_path/'store'); result=retry_run(run,store,client=client)
    assert result[s['id']]['attempts'][0]['status']=='extract_failed'
    assert not store.units()


def test_wu_language_and_wallstreetcn_licence():
    from scripts.run_content_adapters import newsletter_feeds
    from live import registry
    row=next(r for r in newsletter_feeds() if r['id']=='wu_blockchain')
    out=feeds.fetch_newsletter(row,transport=transport('wublock_substack_com_feed.xml'))
    assert out['sources'][0]['source_language']=='zh'
    assert registry.source_no_reproduction('wallstreetcn') is True
    assert registry.source_licence_tier('wallstreetcn')=='B'


def test_wallstreetcn_skips_nonarticles_and_paid():
    from live.adapters import wallstreetcn
    requested=[]
    def get(url, headers):
        requested.append(url)
        if 'information-flow' in url:
            return 200, json.dumps({'data':{'items':[{'resource_type':'live','resource':{'id':1}},
                {'resource_type':'article','resource':{'id':2,'is_paid':True}},
                {'resource_type':'article','resource':{'id':3}},
                {'resource_type':'article','resource':{'id':4}}]}})
        return 200, json.dumps({'data':{'content':'<p>Public fact.</p>','is_priced':url.endswith('3?extract=0')}})
    out=wallstreetcn.fetch(limit=1,transport=get)
    assert len(out['sources'])==1
    assert out['sources'][0]['id']=='wscn-4'
    assert len(requested)==3


def test_runner_new_adapters_and_feed_fetch_once():
    from scripts.run_content_adapters import gather, newsletter_feeds, RSS_FULLTEXT
    from live.adapters import wallstreetcn, nyfed
    from types import SimpleNamespace
    from tests.test_content_store import source, unit
    s=source(); u=unit(s)
    args=SimpleNamespace(adapters=['wallstreetcn','nyfed','fomc','rss_fulltext','newsletters'],
                         rss_n=1,newsletter_extract=100,oaktree_n=3,glassnode_n=3)
    fetched=[]
    def newsletter(row, limit=1):
        fetched.append(row['id']); return {'status':'ok','sources':[]}
    report={'adapters':{}}
    with patch.object(wallstreetcn,'fetch',return_value={'status':'ok','sources':[dict(s,id='wscn',adapter='wallstreetcn')]}), \
         patch.object(nyfed,'fetch',return_value={'status':'ok','sources':[s],'units':[u]}), \
         patch.object(fed,'fetch',return_value={'status':'ok','sources':[dict(s,id='fomc',adapter='fed_rss')]}), \
         patch.object(feeds,'fetch_newsletter',side_effect=newsletter):
        text,data=gather(args,report)
    assert {r['id'] for r in text}=={'wscn','fomc'}
    assert len(data)==1
    assert set(report['adapters']) >= {'wallstreetcn','nyfed','fomc','rss_fulltext'}
    assert all(fetched.count(id)==1 for id in RSS_FULLTEXT)


def test_runner_passes_wscn_n_to_wallstreetcn():
    from scripts.run_content_adapters import gather
    from live.adapters import wallstreetcn
    from types import SimpleNamespace
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {'status': 'ok', 'sources': []}
    args = SimpleNamespace(adapters=['wallstreetcn'], wscn_n=6, rss_n=1, newsletter_extract=0, oaktree_n=3, glassnode_n=3)
    with patch.object(wallstreetcn, 'fetch', side_effect=fake):
        gather(args, {'adapters': {}})
    assert seen.get('limit') == 6


def test_retry_cap_is_additional_to_prior_spend_and_budget_only_attempts_retry(tmp_path, monkeypatch):
    """A run that already spent $9.8 must get cap_usd MORE, and journal entries whose
    attempts never reached the model (BudgetExceeded) are retried."""
    from scripts.rerun_failed_extracts import retry_run
    from live.content_store import ContentStore
    from tests.test_content_store import source
    from ml import budget
    run = tmp_path / 'run'; run.mkdir(); (run / 'ledger').mkdir()
    for name in ('STORE', 'LEDGER', 'RUNS', 'DISTILLATION_RUNS'):
        monkeypatch.setattr(budget, name, getattr(budget, name))
    (run / 'ledger' / 'spend.json').write_text(json.dumps({'cap_usd': 10.0, 'spent_usd': 9.8, 'calls': 3, 'reservations': {}}))
    s = source(); s['id'] = 'f1'
    (run / 'sources.json').write_text(json.dumps({'text': [s]}))
    (run / 'report.json').write_text(json.dumps({'sources': [{'id': 'f1', 'status': 'extract_failed', 'error': 'BudgetExceeded: cap'}]}))
    (run / 'rerun_report.json').write_text(json.dumps({'f1': {'status': 'retried', 'attempts': [
        {'id': 'f1', 'status': 'extract_failed', 'error': 'BudgetExceeded: distillation call would exceed configured spending cap'}]}}))
    calls = []

    def client(stage, messages, limit):
        calls.append(stage)
        return {'finish_reason': 'stop', 'text': '{"units":[]}', 'refusal': False}
    retry_run(run, ContentStore(tmp_path / 'store'), cap_usd=6, client=client)
    assert abs(budget.cap() - 15.8) < 1e-6
    assert calls == ['extract']


def test_truncated_output_failure_is_retried_as_split_halves():
    from scripts.rerun_failed_extracts import json_decode_failure
    assert json_decode_failure('ContractError: extract: incomplete/unknown finish_reason')
    assert not json_decode_failure('ContractError: extract: spans do not match')
