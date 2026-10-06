"""Oct 6 v10: 7x24 flashes (B, cheap batched extract, ring-fenced budget), tier-C headline leads,
timely-first / transcripts-last extract order."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from live.adapters import flashes
from ml import budget

NOW = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)


def _flash(cid, i, text, minutes=10, outlet=None):
    f = {'id': f'{cid}-{i}', 'text': text, 'title': '', 'published': NOW - timedelta(minutes=minutes),
         'url': f'https://example.test/{cid}/{i}', 'score': 1}
    return flashes.to_source(cid, f)


# ---------- adapter ----------

def test_parsers_and_original_outlet():
    wscn = json.dumps({'data': {'items': [
        {'id': 1, 'content_text': '美国9月非农就业人口增加25.4万人，预期14万人。', 'display_time': int(NOW.timestamp()), 'score': 2},
        {'id': 2, 'content_text': '付费内容', 'display_time': int(NOW.timestamp()), 'is_priced': True}]}})
    items = list(flashes._parse_wscn(wscn))
    assert [x['id'] for x in items] == ['wscn-flash-1'] and items[0]['score'] == 2
    em = 'var ajaxResult={"LivesList":[{"newsid":"9","digest":"【央行】今日开展1000亿元逆回购操作。","showtime":"2026-10-06 09:20:00"}]};'
    e = list(flashes._parse_eastmoney(em))[0]
    assert e['published'] == datetime(2026, 10, 6, 1, 20, tzinfo=timezone.utc)
    sina = json.dumps({'result': {'data': {'feed': {'list': [
        {'id': 5, 'rich_text': '<b>英伟达</b>盘后涨3%。（新浪财经）', 'create_time': '2026-10-06 08:00:00', 'docurl': 'u'}]}}}})
    s = list(flashes._parse_sina(sina))[0]
    assert s['text'] == '英伟达盘后涨3%。（新浪财经）'
    assert flashes.original_outlet('【快讯】新华社10月6日电，国务院……', '东方财富7x24') == '新华社'
    assert flashes.original_outlet('据彭博社报道，苹果将推迟发布。', '华尔街见闻7x24') == '彭博社'
    assert flashes.original_outlet('普通快讯没有来源。', '新浪财经7x24') is None
    src = flashes.to_source('ch144_sina_flash', dict(s, published=NOW))
    assert src['no_reproduction'] is True and src['source_id'] == 'ch144_sina_flash'
    assert src['adapter'] == 'flash:ch144_sina_flash' and src['published_at'].startswith('2026-10-06')


def test_fetch_filters_promo_short_and_old():
    body = json.dumps({'data': {'items': [
        {'id': 1, 'content_text': '美联储理事称12月降息仍有可能，通胀回落速度快于预期。', 'display_time': int(NOW.timestamp())},
        {'id': 2, 'content_text': '下载APP查看更多实时快讯，开户立享优惠活动。', 'display_time': int(NOW.timestamp())},
        {'id': 3, 'content_text': '太短', 'display_time': int(NOW.timestamp())},
        {'id': 4, 'content_text': '昨天的旧闻：欧洲央行维持利率不变，符合市场预期。', 'display_time': int((NOW - timedelta(days=3)).timestamp())}]}})
    out = flashes.fetch('ch141_wscn_flash', since=NOW - timedelta(hours=26), now=NOW,
                        transport=lambda url, headers: (200, body))
    assert [s['id'] for s in out['sources']] == ['wscn-flash-1']


def test_dedupe_same_event_across_outlets():
    a = _flash('ch141_wscn_flash', 1, '美国9月非农就业人口增加25.4万人，预期增加14万人，失业率4.1%。')
    b = _flash('ch143_eastmoney_flash', 1, '【美国9月非农】美国9月非农就业人口增加25.4万人，预期14万人；失业率4.1%，前值4.2%。')
    c = _flash('ch144_sina_flash', 1, '英伟达盘后上涨3%，此前公司宣布新一代GPU提前出货。')
    kept, dropped = flashes.dedupe([a, b, c], hours=6)
    assert len(kept) == 2 and dropped[0]['reason'] == 'duplicate'
    rep = next(k for k in kept if '非农' in k['original_text'])
    assert rep['id'] == b['id'] and rep['also_reported_by'][0]['source_id'] == 'ch141_wscn_flash'   # longest wins
    kept2, dropped2 = flashes.dedupe([_flash('ch144_sina_flash', 2, c['original_text'])], hours=6,
                                     recent=[{'id': 'old', 'text': c['original_text'], 'published_at': c['published_at']}])
    assert not kept2 and dropped2[0]['reason'] == 'seen_earlier'
    far = _flash('ch144_sina_flash', 3, a['original_text'], minutes=60 * 10)
    assert len(flashes.dedupe([a, far], hours=6)[0]) == 2   # same text 10h apart = a new event window


# ---------- cheap batched extract ----------

def _unit(text, span):
    return {'kind': 'fact', 'statement': text, 'source_spans': [{'paragraph_id': 'P1', 'exact_text': span}],
            'numbers': [], 'speaker': '美联储', 'speaker_type': 'official', 'freshness_class': 'breaking'}


class FakeLLM:
    def __init__(self, fail_first=False):
        self.calls, self.fail_first = [], fail_first

    def __call__(self, stage, messages, max_tokens):
        self.calls.append((stage, max_tokens))
        text = messages[-1]['content']
        if self.fail_first and len(self.calls) == 1:
            return {'text': '{"flashes": [', 'finish_reason': 'length', 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}
        ids = [f'F{i}' for i in range(1, 30) if f'"F{i}"' in text]
        flashes_out = []
        for fid in ids:
            flashes_out.append({'flash_id': fid, 'units': [_unit('美联储理事表示12月仍可能降息', '美联储理事称12月降息仍有可能')]})
        return {'text': json.dumps({'flashes': flashes_out}, ensure_ascii=False), 'finish_reason': 'stop',
                'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}


def _fed(i):
    return _flash('ch141_wscn_flash', i, f'美联储理事称12月降息仍有可能，第{i}条快讯补充说明。')


def test_extract_batch_same_schema_and_no_reproduction():
    from live import flash_extract
    stats = {}
    out = flash_extract.extract_batch([_fed(1), _fed(2)], FakeLLM(), stats=stats)
    assert stats['calls'] == 1 and set(out) == {'ch141_wscn_flash-1', 'ch141_wscn_flash-2'}
    u = out['ch141_wscn_flash-1'][0]
    assert u['licence_tier'] == 'B' and u['usage'] == 'paraphrase'
    assert u['no_reproduction'] is True and u['quote_allowed'] is False
    assert u['extract_version'].endswith('+flash-batch-v1') and u['source_spans'][0]['exact_text'] in _fed(1)['original_text']


def test_extract_batch_bisects_and_refuses_tier_c():
    from live import flash_extract
    from live.content_units import LicenceRefused
    llm, stats = FakeLLM(fail_first=True), {}
    out = flash_extract.extract_batch([_fed(i) for i in range(1, 5)], llm, stats=stats)
    assert stats['calls'] == 3 and all(out.values())
    with pytest.raises(LicenceRefused):
        flash_extract.extract_batch([_fed(1)], llm, licence_tier='C')


# ---------- channels / licence ----------

def test_channels_new_modes_and_tier_c_only_for_leads(tmp_path):
    from live.adapters import channels
    rows = {c['channel_id']: c for c in channels.load_channels('live/channels.json')}
    assert rows['ch141_wscn_flash']['mode'] == 'flash_json' and rows['ch141_wscn_flash']['licence_tier'] == 'B'
    assert all(rows[c]['licence_tier'] == 'C' and rows[c]['mode'] == 'headline_lead'
               for c in ('ch145_cnbc_rss', 'ch146_marketwatch_rss', 'ch147_bloomberg_rss', 'ch148_ft_rss', 'ch149_nasdaq_rss'))
    assert 'flash_json' not in channels.DEFAULT_MODES and 'headline_lead' not in channels.DEFAULT_MODES
    data = json.loads(open('live/channels.json').read())
    bad = dict(data, channels=[dict(data['channels'][-1], channel_id='ch999_x', mode='feed_fulltext')])
    p = tmp_path / 'c.json'
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        channels.load_channels(p)   # tier C outside headline_lead is rejected
    from live import registry
    lic = json.loads(open('live/source_licence.json').read())['tiers']
    assert lic['ch145_cnbc_rss']['usage'] == 'topic_only' and lic['ch145_cnbc_rss']['quote_allowed'] is False
    assert registry.source_licence_tier('ch143_eastmoney_flash') == 'B' and lic['ch143_eastmoney_flash']['credit_original_outlet']


def test_store_rejects_tier_c_and_credits_original_outlet(tmp_path):
    from live.content_store import ContentStore, attribution
    src = _fed(1)
    src['original_outlet'] = '彭博社'
    unit = {'unit_id': 'u1', 'licence_tier': 'B', 'usage': 'paraphrase', 'speaker': '美联储', 'speaker_type': 'official'}
    assert attribution(src, unit)['original_outlet'] == '彭博社'


def test_news_leads_are_tier_c_with_hooks(monkeypatch, tmp_path):
    from live import news
    rss = ('<rss><channel><item><title>Fed minutes show officials split on December cut</title>'
           '<link>https://example.test/a</link><description>FOMC minutes</description>'
           f'<pubDate>{NOW.strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate></item></channel></rss>')
    monkeypatch.setattr(news, 'fetch', lambda name, cfg: {'ok': True, 'body': rss, 'seconds': 0, 'status': 200})
    monkeypatch.setattr(news, '_seen', lambda: (set(), set()))
    monkeypatch.setattr(news.datetime, 'datetime', type('D', (news.datetime.datetime,), {'now': classmethod(lambda c, tz=None: NOW)}))
    out = news.collect(only=['cnbc_economy'], dry_run=True, gap_seconds=0)
    assert out['new_items'] == 1 and out['failing'] == []
    for name in ('cnbc_economy', 'cnbc_markets', 'marketwatch', 'bloomberg_markets', 'ft_markets', 'nasdaq_markets'):
        assert news.SOURCES[name]['channel_id']
    assert news.LEAD_TIER == 'C'


# ---------- extract order ----------

def _task(channel, sid, rank=0, title=''):
    return ({'id': channel}, {'id': sid, 'source_id': channel, 'title': title}, None, channel, [sid], rank)


def test_timely_first_transcripts_last(monkeypatch):
    from live import ingest_priority as ip
    assert ip.timeliness('ch019_www_fool_com') == 'transcript'
    assert ip.timeliness('ch021_news_alphastreet_com') == 'transcript'
    assert ip.timeliness('newsletters:x', {'title': 'NVDA Q3 2026 Earnings Call Transcript'}) == 'transcript'
    assert ip.timeliness('ch098_ritholtz_com', {'title': 'Transcript: Jane Doe on bonds'}) == 'standard'
    assert ip.timeliness('ch044_www_bankofengland_co_uk') == 'timely'
    assert ip.timeliness('ch109_www_theblock_co') == 'timely'
    assert ip.timeliness('ch142_wscn_global') == 'timely'
    assert ip.timeliness('ch098_ritholtz_com') == 'standard'
    hints = {'ch019_www_fool_com': ['single_stock_deepdive_en'], 'ch044_www_bankofengland_co_uk': ['macro_rates_en'],
             'ch098_ritholtz_com': ['investing_philosophy'], 'ch109_www_theblock_co': ['crypto_macro_en']}
    monkeypatch.setattr(ip, 'channel_personas', lambda cid, s=None: hints.get(cid, [ip.UNKNOWN]))
    tasks = [_task('ch019_www_fool_com', 'f1'), _task('ch098_ritholtz_com', 'r1'),
             _task('ch044_www_bankofengland_co_uk', 'b1'), _task('ch109_www_theblock_co', 't1')]
    fresh = {'single_stock_deepdive_en': 0, 'investing_philosophy': 1, 'macro_rates_en': 60, 'crypto_macro_en': 20}
    order, plan = ip.order_tasks(tasks, fresh, {'f1'}, floor=2)
    assert [t[1]['id'] for t in order] == ['t1', 'b1', 'r1', 'f1']   # even a prior-deferred transcript goes last
    assert [r['phase'] for r in plan] == ['timely', 'timely', 'fair_share_floor', 'transcripts_last']


# ---------- daily ingest: flash fence ----------

def _setup(tmp_path, **kw):
    return dict(store=tmp_path / 'store', runs_dir=tmp_path / 'runs', inbox=tmp_path / 'inbox',
                state_path=tmp_path / 'state.json', no_dashboard=True, **kw)


def _fake_fetch(texts):
    def fetch(cid, n=100, since=None, transport=None):
        if cid != 'ch141_wscn_flash':
            return {'status': 'no_new_flashes', 'sources': []}
        return {'status': 'ok', 'sources': [_flash(cid, i, t, minutes=5 + i) for i, t in enumerate(texts)]}
    return fetch


def _costly_batch(per_call):
    from live import flash_extract
    calls = []

    def extract_batch(group, client, *, licence_tier='B', stats=None):
        budget.reserve('erisedai_relay/claude-sonnet-5', [], 10, f'flash-{len(calls)}')
        budget.settle(f'flash-{len(calls)}', {'prompt_tokens': int(per_call / 3e-6), 'completion_tokens': 0})
        calls.append([s['id'] for s in group])
        stats['calls'] = stats.get('calls', 0) + 1
        return {s['id']: [] for s in group}
    return extract_batch, calls


def test_daily_ingest_flash_fence_and_docs_after(tmp_path, monkeypatch):
    from live.daily_ingest import run
    monkeypatch.setitem(budget.PRICES, 'erisedai_relay/claude-sonnet-5', (3.0, 15.0))
    texts = ['美联储理事沃勒表示12月降息仍有可能，通胀回落速度快于预期。', '欧洲央行管委称10月维持利率不变是合适选择。',
             '日本央行行长植田和男称将继续审视工资与物价走势。', '英伟达盘后上涨3%，新一代GPU提前出货给云厂商。',
             '国家统计局：9月制造业PMI为49.8，前值49.4。', '比特币突破12万美元，现货ETF单日净流入5亿美元。']
    extract_batch, calls = _costly_batch(0.40)
    seen_docs = []

    def extract(s):
        seen_docs.append(s['id'])
        return []
    from tests.test_daily_ingest import source
    r = run(**_setup(tmp_path, cost_cap_usd=8.0, flash_budget_usd=0.70, flash_batch_size=2),
            fetchers={'doc': lambda: {'sources': [source('d1')]}}, extract=extract, backup=lambda: None,
            refresh=lambda: None, flash_fetch=_fake_fetch(texts), flash_extract_batch=extract_batch,
            flash_llm=object(), news_collect=lambda dry_run=False: {'new_items': 0, 'lead_hooks': {}})
    f = r['flashes']
    # 2 batches fit the $0.70 fence ($0.40 each: the second one crosses after reserve -> its settle may exceed);
    assert f['budget_usd'] == 0.70 and f['extracted'] >= 2 and f['deferred_flash_budget'] >= 1
    assert f['cost_usd'] <= 0.70 + 0.40 + 1e-6
    assert seen_docs == ['d1']                       # docs still run on the rest of the cap
    st = json.loads((tmp_path / 'state.json').read_text())
    assert st['flashes']['pending'] and st['flashes']['seen']
    assert r['ordering']['budget_split']['flash_ring_fence_usd'] == 0.70


def test_daily_ingest_dry_run_previews_flashes(tmp_path):
    from live.daily_ingest import run
    texts = ['美国9月CPI同比上涨2.9%，预期3.0%，核心CPI环比0.2%。', '【美国9月CPI】美国9月CPI同比2.9%，预期3.0%；核心CPI环比上涨0.2%。',
             '英伟达盘后上涨3%，公司宣布新一代GPU提前出货给云厂商。']
    r = run(**_setup(tmp_path, dry_run=True), fetchers={}, backup=lambda: None, refresh=lambda: None,
            flash_fetch=_fake_fetch(texts), news_collect=lambda dry_run=False: {'new_items': 3, 'lead_hooks': {'cpi': 2}})
    f = r['flashes']
    assert r['status'] == 'dry_run' and f['selected'] == 2 and f['duplicates'] == 1
    assert f['lead_hook_boosted'] == 1 and f['preview'][0]['lead_hook'] is True
    assert r['news_leads']['licence_tier'] == 'C'


def test_cron_wrapper_uses_script_defaults():
    import re
    sh = open('scripts/cron/daily_ingest.sh').read()
    assert 'scripts/daily_ingest.py' in sh and '--no-flashes' not in sh and '--flash-budget-usd' not in sh
    cli = open('scripts/daily_ingest.py').read()
    assert re.search(r"--flash-budget-usd',type=float,default=1\.75", cli)


def test_similar_live_pool_pairs():
    """Pairs from the live 10/6 pool: re-worded copies merge, look-alike templates with different numbers don't."""
    dup = [("月之暗面已经完成最后一轮私募融资，估值约500亿美元，并正推进明年第一季度在香港进行首次公开募股（IPO）。",
            "月之暗面即将完成Pre-IPO融资，估值将达500亿美元，计划于2027年第一季度在香港上市。（新浪）"),
           ("据知情人士称，快手科技旗下可灵AI已选定银行筹备香港首次公开募股，此次上市可能募资至少10亿美元。"
            "知情人士表示，这家人工智能视频生成服务商正与中金公司、高盛和瑞银合作推进潜在的股票发行。",
            "快手旗下视频生成大模型可灵AI据悉计划最早明年赴港上市，至少融资10亿美元。")]
    distinct = [("泰国9月消费者价格指数同比上涨2.82%，预估为3.10%。",
                 "【土耳其9月通胀率降至30%以下 连续四个月回落】土耳其5日公布的官方数据显示，9月消费者价格指数同比上涨29.8%。"),
                ("印度9月综合PMI终值 55.9，初值 56.5。", "印度9月服务业PMI终值 55.2，初值 55.8。"),
                ("杰富瑞将宝马目标价从70欧元下调至60欧元。", "杰富瑞将高盛目标价从1299美元下调至1124美元。")]
    assert all(flashes.similar(a, b) for a, b in dup)
    assert not any(flashes.similar(a, b) for a, b in distinct)
    assert flashes._numbers('9月6日，2026年CPI涨2.9%，报70欧元') == {'2.9', '70'}
