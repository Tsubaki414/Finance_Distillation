import json
from pathlib import Path
from scripts.source_utilization import match_channel, audit


def test_explicit_matching_and_host_boundaries():
    assert match_channel({'name': 'Fed RSS', 'url': 'https://www.federalreserve.gov/'}, {'source': {'adapter': 'fed_rss'}})
    assert match_channel({'name': 'Apricitas', 'url': 'https://www.apricitas.io/feed'}, {'source': {'url': 'https://www.apricitas.io/p/a'}})
    assert not match_channel({'name': 'Apricitas', 'url': 'https://www.apricitas.io/feed'}, {'source': {'url': 'https://fakeapricitas.io/p/a'}})


def test_all_channels_and_voice_donors(tmp_path):
    tags = tmp_path/'tags'; tags.mkdir(); (tags/'alice.json').write_text('{}')
    out = audit(json.loads(Path('tests/fixtures/sources3/source_expansion.json').read_text()), {'sources': []}, {'sources': {}}, {'donors': {'alice': {'persona_cluster': 'zh_us_stock_commentary'}}}, tmp_path/'store', tags)
    assert len(out['channels']) == 138
    assert out['donor_count'] == 1
    assert out['donors'][0]['units'] == 0
    assert 'voice' in out['donors'][0]['usage']


def test_known_publisher_and_shared_hosts():
    assert match_channel({'name':'Oaktree Howard Marks Memos'}, {'source':{'publisher':'Oaktree Capital (Howard Marks)'}})
    assert not match_channel({'name':'SEC 新闻稿 RSS','url':'https://www.sec.gov/news/pressreleases.rss'}, {'source':{'adapter':'edgar','url':'https://www.sec.gov/Archives/edgar/data/1/a.htm'}})


def test_posts_only_donor(tmp_path):
    tags=tmp_path/'tags'; tags.mkdir(); posts=tmp_path/'posts'; posts.mkdir()
    (posts/'alice.jsonl').write_text('{}\n')
    result=audit({'sources':[]},{'sources':[]},{'tiers':{}},{'donors':{'alice':{'persona_cluster':'none'}}},tmp_path/'store',tags)
    assert result['donor_count']==1
    assert result['donors'][0]['posts_exist'] is True


def test_reportgem_built_without_store(tmp_path):
    result=audit({'sources':[{'name':'ReportGem 实时外文研报'}]}, {'sources':[]}, {'tiers':{'reportgem_goldman':{'tier':'B'}}}, {'donors':{}}, tmp_path/'store', tmp_path/'tags')
    assert result['channels'][0]['status']=='built_unused'
    assert result['channels'][0]['score_factors']['paraphrase_allowed'] is True


def test_edgar_and_fed_url_paths():
    assert match_channel({'name':'SEC EDGAR','url':'https://www.sec.gov/cgi-bin/browse-edgar'}, {'source':{'url':'https://www.sec.gov/Archives/edgar/data/1/a.htm'}})
    assert match_channel({'name':'Fed RSS','url':'https://www.federalreserve.gov/feeds/speeches.xml'}, {'source':{'url':'https://www.federalreserve.gov/newsevents/speech/powell20261002a.htm'}})


def test_markdown_shows_unused_donor_cluster_and_voice_usage():
    from scripts.source_utilization import markdown
    result={'channels':[], 'donor_count':1, 'donors':[{'name':'alice','status':'built_unused','units':0,
            'persona_cluster':'zh_us_stock_commentary','personas_fed':[],'voice_exemplar_used':False,'usage':'voice only'}],
            'summary':{'channels':{},'donors':{'built_unused':1}}, 'next_to_build':[]}
    text=markdown(result)
    assert 'zh_us_stock_commentary' in text
    assert 'Voice/exemplar used' in text
    assert '| built_unused | 0 | 1 |' in text


def test_channel_id_rows_match_legacy_newsletter_adapter_ids():
    ch = {'channel_id': 'ch089_www_apricitas_io', 'name': 'Apricitas Economics（Joseph Politano）', 'url': 'https://www.apricitas.io/feed'}
    assert match_channel(ch, {'source': {'source_id': 'apricitas', 'adapter': 'newsletter_rss', 'url': 'https://www.apricitas.io/p/x'}})
    wu = {'channel_id': 'ch121_wublock_substack_com', 'name': '吴说 Wu Blockchain（Substack）', 'url': 'https://wublock.substack.com/feed'}
    assert match_channel(wu, {'source': {'source_id': 'wu_blockchain', 'adapter': 'newsletter_rss'}})
    assert not match_channel(ch, {'source': {'source_id': 'wu_blockchain', 'adapter': 'newsletter_rss'}})
