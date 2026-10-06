"""Sina research channel (ch008) dates: page-date parser, no malformed published_at, the
source_dates.jsonl sidecar (ContentStore + freshness backfill), backfill script. Tmp stores only."""
import json

from live import content_store as cs
from live.adapters import channels, common
from scripts import backfill_source_dates as bsd
from scripts.backfill_freshness import backfill

URL = 'https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/844590120122/index.phtml'
SID = 'ch008_stock_finance_sina_com_cn'
GBK_PAGE = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head><body>'
            '<div class="creab"><span>机构：中金公司</span><span>研究员：张三</span><span>日期：2026-10-06</span></div>'
            '<div class="blk_container"><p>正文</p></div></body></html>')


def test_page_date_patterns():
    page = GBK_PAGE.encode('gbk')
    assert channels.page_date(bsd.decode_page(page)) == '2026-10-06'
    assert channels.page_date('<p>发布时间： 2026年10月6日 08:00</p>') == '2026-10-06'
    assert channels.page_date('<p>发布日期:2026-9-30</p>') == '2026-09-30'
    assert channels.page_date('<td>日期：</td><td>2026-10-06</td>') == '2026-10-06'  # tags between label and value
    assert channels.page_date('<p>2026-10-06 no label</p>') == ''
    assert channels.page_date('<p>日期：2026-13-40</p>') == ''
    assert channels.page_date('') == ''


def test_list_row_date_and_accept_uses_page_date():
    index = ('<table><tr><td>1</td><td><a href="/stock/go.php/vReport_Show/kind/lastest/rptid/1/index.phtml">'
             '市场情绪跟踪9月报：情绪视角看节前A股市场</a></td><td>策略</td><td>2026-10-04</td></tr></table>')
    found = channels._candidates(index, 'https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/lastest/index.phtml')
    assert found[0]['published_at'] == '2026-10-04'
    ch = {'channel_id': SID, 'name': '新浪财经研报', 'url': 'https://stock.finance.sina.com.cn/x/', 'lang': 'zh',
          'mode': 'html_index', 'licence_tier': 'B'}
    body = GBK_PAGE.replace('<p>正文</p>', '<p>' + '研报正文内容。' * 200 + '</p>')
    out = channels.fetch_channel(ch, transport=lambda url, headers: (200, body if 'rptid' in url else index.replace(
        '/stock/go.php/vReport_Show/kind/lastest/rptid/1/index.phtml', URL).replace('<td>2026-10-04</td>', '<td></td>')),
        extractor=lambda page: common.html_text(page))
    assert out['sources'] and out['sources'][0]['published_at'] == '2026-10-06T00:00:00Z'


def test_make_source_never_emits_malformed_dates():
    def made(value):
        return common.make_source(id='x', source_id='s', text='t', publisher='p', title='t', url='u',
                                  published_at=value, adapter='a')['published_at']
    assert made('') is None and made(None) is None
    assert made('T00:00:00Z') is None and made('not a date') is None and made('2026-13-01') is None
    assert made('2026-10-06') == '2026-10-06T00:00:00Z'
    assert made('2026-10-06T08:30:00+08:00') == '2026-10-06T08:30:00+08:00'
    assert made('2026-10-06T00:00:00Z') == '2026-10-06T00:00:00Z'
    parts = common.make_sources_chunked(id='x', source_id='s', text='t', publisher='p', title='t', url='u',
                                        published_at='', adapter='a')
    assert parts[0]['published_at'] is None


def _row(uid, source_key, published, url=URL, statement='中金：油气化工行业首选。'):
    return {'unit_id': uid, 'licence_tier': 'B',
            'unit': {'kind': 'view', 'statement': statement, 'published_at': published, 'numbers': [],
                     'source_spans': [], 'licence_tier': 'B'},
            'attribution': {}, 'personas': ['macro_zh'],
            'source': {'id': source_key, 'source_id': SID, 'url': url, 'published_at': published,
                       'adapter': 'channel:html_index', 'source_hash': source_key}}


def _store(tmp_path, rows, sidecar=()):
    (tmp_path / 'units.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    if sidecar:
        (tmp_path / 'source_dates.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in sidecar))
    return tmp_path


def test_sidecar_applied_by_content_store_and_freshness_backfill(tmp_path):
    rows = [_row('u-none', 'k1-p1', None), _row('u-bad', 'k2-p1', 'T00:00:00Z', url=URL + '?b'),
            _row('u-ok', 'k3-p1', '2026-09-01T00:00:00Z', url=URL + '?c'), _row('u-miss', 'k4-p1', None, url=URL + '?d')]
    sidecar = [{'source_key': 'k1-p1', 'url': URL, 'published_at': '2026-10-04', 'method': 'page_date'},
               {'source_key': 'other', 'url': URL + '?b', 'published_at': '2026-10-05', 'method': 'page_date'},
               {'source_key': 'k3-p1', 'url': URL + '?c', 'published_at': '2026-10-05', 'method': 'page_date'}]
    store = _store(tmp_path, rows, sidecar)
    before = (store / 'units.jsonl').read_bytes()
    loaded = {r['unit_id']: r for r in cs.ContentStore(store).units()}
    assert loaded['u-none']['source']['published_at'] == '2026-10-04T00:00:00Z'
    assert loaded['u-none']['unit']['published_at'] == '2026-10-04T00:00:00Z'
    assert loaded['u-none']['source']['published_at_recovered'] == 'page_date'
    assert loaded['u-bad']['source']['published_at'] == '2026-10-05T00:00:00Z'  # matched by url
    assert loaded['u-ok']['source']['published_at'] == '2026-09-01T00:00:00Z'  # valid date untouched
    assert loaded['u-miss']['source']['published_at'] is None
    assert (store / 'units.jsonl').read_bytes() == before  # append-only store never rewritten

    entries = {e['unit_id']: e for e in backfill(store, write=False)}
    assert entries['u-none']['published_at'] == '2026-10-04' and not entries['u-none']['date_unknown']
    assert 'missing_published_at' not in entries['u-none']['freshness_flags']
    assert entries['u-bad']['published_at'] == '2026-10-05'
    assert entries['u-ok']['published_at'] == '2026-09-01'
    assert entries['u-miss']['date_unknown'] and 'missing_published_at' in entries['u-miss']['freshness_flags']
    assert not (store / 'freshness.jsonl').exists()


def test_backfill_script_dry_run_then_write(tmp_path, capsys):
    url2 = URL.replace('844590120122', '844428120101')
    rows = [_row('a1', 'ch008-a-p1', None), _row('a2', 'ch008-a-p1', None, statement='第二条'),
            _row('b1', 'ch008-b-p1', 'T00:00:00Z', url=url2),
            _row('c1', 'ch008-c-p1', '2026-10-01T00:00:00Z', url=URL + '?ok')]
    other = _row('o1', 'other-p1', None, url='https://example.com/2026/10/03/post')
    other['source']['source_id'] = 'ch099_other'
    store = _store(tmp_path, rows + [other])
    calls, sleeps = [], []

    def transport(url, headers):
        calls.append(url)
        return (200, GBK_PAGE.encode('gbk')) if url == URL else (404, b'')

    results = bsd.main(['--store', str(store)], transport=transport, sleep=sleeps.append)
    assert calls == [URL, url2] and sleeps == [1.0]  # one fetch per page, polite gap
    got = {r['source_key']: r for r in results}
    assert set(got) == {'ch008-a-p1', 'ch008-b-p1'}
    assert (got['ch008-a-p1']['published_at'], got['ch008-a-p1']['method'], got['ch008-a-p1']['units']) == ('2026-10-06', 'page_date', 2)
    assert (got['ch008-b-p1']['published_at'], got['ch008-b-p1']['method'], got['ch008-b-p1']['http']) == (None, 'not_found', 404)
    assert '| ch008-a-p1 | 2 | None | 200 | 2026-10-06 | page_date |' in capsys.readouterr().out
    assert not (store / 'source_dates.jsonl').exists()  # dry run writes nothing

    bsd.main(['--store', str(store), '--write'], transport=transport, sleep=sleeps.append)
    written = [json.loads(l) for l in (store / 'source_dates.jsonl').read_text().splitlines()]
    assert [(w['source_key'], w['url'], w['published_at'], w['method']) for w in written] == [('ch008-a-p1', URL, '2026-10-06', 'page_date')]
    assert written[0]['recovered_at']
    assert cs.ContentStore(store).units()[0]['source']['published_at'] == '2026-10-06T00:00:00Z'

    calls.clear()  # recovered sources are not fetched again
    again = bsd.main(['--store', str(store)], transport=transport, sleep=sleeps.append)
    assert [r['source_key'] for r in again] == ['ch008-b-p1'] and calls == [url2]

    # generic prefix: a URL date is used when the page has none
    url_dated = bsd.main(['--store', str(store), '--source-prefix', 'ch099_'], transport=lambda u, h: (200, b'<p>x</p>'),
                         sleep=sleeps.append)
    assert (url_dated[0]['published_at'], url_dated[0]['method']) == ('2026-10-03', 'url_date')
