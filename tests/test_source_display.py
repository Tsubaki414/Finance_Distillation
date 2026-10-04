from live import attribution_frame, source_display


def test_clean_names_and_english_names_on_en_posts():
    assert source_display.display({'source_id': 'ch096_spotgamma_com', 'publisher': 'SpotGamma 免费内容'}, 'en')['name'] == 'SpotGamma'
    zh = source_display.display({'source_id': 'ch065_www_stats_gov_cn', 'publisher': '国家统计局 数据发布'}, 'zh')
    assert zh['ok'] and zh['name'] == '国家统计局'
    en = source_display.display({'source_id': 'ch065_www_stats_gov_cn', 'publisher': '国家统计局 数据发布'}, 'en')
    assert en['ok'] and en['name'] == 'China NBS'


def test_pure_chinese_name_without_english_override_fails_gate_on_en():
    g = source_display.display({'source_id': 'ch127_wechat2rss_xlab_app', 'publisher': '长赢指数投资（ETF拯救世界·E大）'}, 'en')
    assert not g['ok'] and 'name' in g['reason']


def test_licence_gate_blocks_unknown_tier():
    g = source_display.display({'source_id': 'not_a_source', 'publisher': 'Somebody'}, 'en')
    assert not g['ok'] and 'licence' in g['reason']


def test_sell_side_via_reportgem_credited_generically_and_bank_never_named():
    src = {'source_id': 'reportgem_goldman_sachs', 'publisher': 'Goldman Sachs', 'author_name': 'Jane Analyst', 'adapter': 'reportgem'}
    g = source_display.display(src, 'en')
    assert g['ok'] and g['name'] == 'sell-side research' and g['policy'] == 'generic_sell_side'
    assert 'Goldman Sachs' in g['never_name'] and '高盛' in g['never_name'] and 'ReportGem' in g['never_name']
    frame = attribution_frame.render('data_take', src, lang='zh')
    assert '券商研报' in frame['text'] and '高盛' not in frame['text'] and 'Jane' not in frame['text']
    hits = source_display.never_name_findings('高盛认为需求会回升。', frame['never_name'])
    assert hits and hits[0]['code'] == 'never_name_in_post'


def test_sec_filer_names_are_clean():
    assert source_display.display({'source_id': 'sec_edgar', 'publisher': 'Amazon Com'}, 'zh', check_licence=False)['name'] == 'Amazon 公告'
    assert source_display.display({'source_id': 'sec_edgar', 'publisher': 'Micron Technology'}, 'en', check_licence=False)['name'] == 'Micron Technology filing'
