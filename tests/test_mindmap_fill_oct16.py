"""Oct 16 mind-map fill tier + long-form source ingest (no network, no model; one real chrome render when available)."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from live import archive_fallback, compose_inbox, fresh_hold, longform_src
from live.mindmap import fill, gen, render

NOW = datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)
SOURCE = ('Index funds work because costs compound against you. A fund charging 1.5% a year gives up a third of a 30 year return. '
          'Investors who trade often earn less than the market because they buy after prices rise. ') * 14
ACCT_EN = {'id': 'investing_philosophy', 'lang': 'en', 'beat': 'Long-term investing philosophy', 'name': 'Owen', 'no': 18}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in ('FD_MINDMAP_FILL', 'FD_MINDMAP_MAX_PER_DAY', 'FD_MINDMAP_ACCOUNTS', 'FD_LONGFORM_SRC', 'FD_MINDMAP_ATTEMPTS'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('FD_MINDMAP_STORE', str(tmp_path / 'mmstore'))
    monkeypatch.setenv('FD_LONGFORM_DIR', str(tmp_path / 'lf'))
    monkeypatch.setenv('FD_VIDEO_DIR', str(tmp_path / 'novideo'))


L = 'abcdefgh'


def tree(n_branches=5, quote='costs compound against you'):
    """~40 nodes, every L2+ node quotes a real SOURCE excerpt."""
    qs = ['costs compound against you', 'gives up a third of a 30 year return', 'Investors who trade often earn less',
          'because they buy after prices rise', 'Index funds work']
    br = []
    for i in range(n_branches):
        l2 = []
        for j in range(2):
            l3 = [{'t': f'Point {L[i]}{L[j]}{L[k]}', 'q': qs[(i + j + k) % 5], 'c': [{'t': f'Detail {L[i]}{L[j]}{L[k]}', 'q': qs[k % 5]}] if k == 0 else []}
                  for k in range(2)]
            for x in l3:
                if not x['c']:
                    x.pop('c')
            l2.append({'t': f'Claim {L[i]}{L[j]}', 'q': qs[j], 'c': l3})
        br.append({'t': f'Theme {L[i]}', 'c': l2})
    return {'title': 'Fees and behaviour', 'branches': br, 'caption': 'Fees quietly eat a third of a long return. Worth knowing before you pick a fund.'}


# ---------------------------------------------------------------- render

def test_validate_flags_emoji_depth_counts():
    data = {'title': 'T', 'lang': 'en', 'footer': 'f', 'branches': [{'t': 'A', 'c': [{'t': 'B 🚀', 'c': [{'t': 'C'}]}]}]}
    errs = render.validate(data)
    assert any('unsafe glyph' in e for e in errs) and any('nodes not in' in e for e in errs)
    deep = {'title': 'T', 'lang': 'en', 'branches': [{'t': 'a', 'c': [{'t': 'b', 'c': [{'t': 'c', 'c': [{'t': 'd', 'c': [{'t': 'e'}]}]}]}]}]}
    assert any('depth 5' in e for e in render.validate(deep, strict_counts=False))
    ok = gen.strip_q(gen.prune(tree(), SOURCE)[0])
    assert render.validate({'title': 'T', 'lang': 'en', 'branches': ok}) == []
    zh = {'title': '题', 'lang': 'zh', 'branches': [{'t': '一' * 15, 'c': [{'t': '二'}]}]}
    assert any('too long' in e for e in render.validate(zh, strict_counts=False))


def test_html_structure_and_paper_style():
    data = {'title': 'T', 'subtitle': 'a\nb', 'lang': 'zh', 'footer': '整理自', 'branches': gen.strip_q(gen.prune(tree(), SOURCE)[0])}
    h = render.to_html(data)
    assert '#F4EFE6' in h and '#9C3D2E' in h and 'gradient' not in h and 'border-radius' not in h
    assert h.count('class="node l1') == 5 and 'a<br>b' in h and 'Noto Serif CJK SC' in h


@pytest.mark.skipif(not Path('/usr/bin/google-chrome').exists() or not shutil.which('/usr/bin/python3'), reason='no chrome')
def test_real_render_no_overlap(tmp_path):
    data = {'title': '费用与行为', 'subtitle': '作者', 'lang': 'zh', 'footer': '整理自文章 · 要点为转述',
            'branches': gen.strip_q(gen.prune(tree(), SOURCE)[0])}
    try:
        info = render.render_png(data, tmp_path / 'a.png')
    except RuntimeError as exc:   # python without playwright
        pytest.skip(str(exc))
    assert info['overlaps'] == 0 and info['overflow'] == 0
    assert (tmp_path / 'a.png').stat().st_size > 20000


# ---------------------------------------------------------------- gen

def test_prune_drops_unsupported_and_invented_numbers():
    t = tree()
    t['branches'][0]['c'][0]['c'][0]['q'] = 'something the source never says'
    t['branches'][1]['c'][0]['t'] = 'Claim with 99% invented'
    br, st = gen.prune(t, SOURCE)
    assert st['dropped_support'] >= 1 and st['dropped_number'] == 1
    assert gen.prune(tree(), SOURCE)[1]['dropped'] == 0
    t2 = tree()
    t2['branches'][0]['c'][0]['t'] = 'Fees of 1.5% a year'   # 1.5 is in the source
    assert gen.prune(t2, SOURCE)[1]['dropped_number'] == 0


def test_make_tree_ok_skip_and_unsupported():
    item = {'id': 'x', 'lang': 'en', 'title': 'T', 'author': 'A', 'name': 'N', 'kind': 'blog', 'url': 'https://b.com/p', 'published_at': '2026-10-01T00:00:00+00:00'}
    res = gen.make_tree(lambda m: (tree(), {}), ACCT_EN, {}, SOURCE, item)
    assert res['status'] == 'ok' and not [f for f in res['findings'] if f['level'] == 'hard'], res['findings']
    assert 'b.com' in res['data']['footer'] and res['stats']['nodes'] >= 30
    assert gen.make_tree(lambda m: ({'skip': 'dating'}, {}), ACCT_EN, {}, SOURCE, item)['status'] == 'skip'
    bad = tree()
    for b in bad['branches']:
        for c in b['c']:
            c['q'] = 'invented excerpt that is not there'
    res = gen.make_tree(lambda m: (bad, {}), ACCT_EN, {}, SOURCE, item)
    assert any(f['code'] == 'mm_unsupported' for f in res['findings'])


def test_caption_findings():
    assert gen.caption_findings('Fees quietly eat a third of a long return.', 'en') == []
    codes = [c for c, _ in gen.caption_findings('Great map #investing 🚀 via @someone, guaranteed 20% returns', 'en')]
    assert 'mm_caption_hashtag_emoji' in codes and 'mm_caption_handle_in_body' in codes
    assert gen.caption_findings('', 'en')[0][0] == 'mm_caption_empty'
    assert gen.caption_findings('x' * 400, 'en')[0][0] == 'mm_caption_long'
    assert any(c == 'mm_caption_contrast' for c, _ in gen.caption_findings('这不是运气,而是纪律', 'zh'))


# ---------------------------------------------------------------- fill tier

def _row(aid, rid, **kw):
    return {'id': rid, 'day': '2026-10-16', 'account_id': aid, 'text': 'hello world', 'draft_status': 'draft_ready',
            'held': False, 'post_format': {}, **kw}


def test_gate_tiers(tmp_path):
    base = tmp_path / 'inbox'
    aid = 'investing_philosophy'
    assert fill.gate(aid, '2026-10-16', base=base)[0] is True                         # empty day -> fill
    compose_inbox.add(_row(aid, 'reply-1', post_format={'engage': 'reply'}), base=base)
    ok, why = fill.gate(aid, '2026-10-16', base=base)
    assert ok is False and 'reply-only' in why                                        # Oct 16: reply-only account is not filled
    aid = 'btc_cycles_en'
    compose_inbox.add(_row(aid, 'compose-1', held=True, draft_status='needs_review'), base=base)
    assert fill.gate(aid, '2026-10-16', base=base)[0] is True                         # held does not count
    compose_inbox.add(_row(aid, 'arc-1', post_kind='archive_lookback'), base=base)
    ok, why = fill.gate(aid, '2026-10-16', base=base)
    assert ok is False and 'slot rule' in why                                         # archive tier fills first
    assert fill.gate(aid, '2026-10-16', base=base, made_today=4)[0] is False         # day cap


def test_fresh_standalone_blocks_and_mindmap_yields(tmp_path):
    base = tmp_path / 'inbox'
    mm = _row('x', 'mm-1', post_kind='mindmap')
    assert archive_fallback.is_archive(mm) and archive_fallback.can_yield(mm)
    assert fresh_hold.check({**mm, 'source': {'published_at': '2020-01-01T00:00:00Z'}, 'suggested_post_time_london': '2026-10-16T10:00:00+01:00'})[0] is False
    news = _row('x', 'compose-9', source={'published_at': '2020-01-01T00:00:00Z'}, suggested_post_time_london='2026-10-16T10:00:00+01:00')
    assert fresh_hold.check(news)[0] is True


def test_topic_and_video_fit():
    crypto = {'id': 'crypto_trader_en', 'beat': 'Crypto trading'}
    inv = {'id': 'investing_philosophy', 'beat': 'Long-term investing'}
    assert fill.topic_fits('crypto', crypto) and not fill.topic_fits('crypto', inv)
    assert fill.topic_fits('investing', inv) and not fill.topic_fits('investing', crypto)
    assert fill.topic_fits('general', crypto) and fill.topic_fits('general', inv)
    assert fill.topic_fits('macro', {'id': 'crypto_macro_en', 'beat': 'Crypto macro'})
    vi = {'kind': 'x_video', 'title': '30岁存款怎么攒钱'}
    assert fill.video_fits(vi, {'id': 'zh_longterm_investing'}) and not fill.video_fits(vi, {'id': 'zh_macro'})
    assert not fill.video_fits({'kind': 'x_video', 'title': '教你如何追到渣男'}, {'id': 'zh_longterm_investing'})


def _pool(tmp_path, n=2):
    d = tmp_path / 'lf' / '20261015'
    d.mkdir(parents=True)
    items = []
    for i in range(n):
        iid = f'blog-t-{i}'
        (d / f'{iid}.txt').write_text(SOURCE)
        meta = {'id': iid, 'kind': 'blog', 'source_id': 't', 'name': 'Test Blog', 'lang': 'en', 'topic': 'investing', 'title': f'Post {i}',
                'author': 'Ann', 'url': f'https://t.example/p{i}', 'published_at': f'2026-10-0{i + 1}T00:00:00+00:00', 'chars': len(SOURCE)}
        (d / f'{iid}.json').write_text(json.dumps(meta))
        items.append(iid)
    return items


def fake_render(data, png):
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    Path(png).write_bytes(b'\x89PNG fake')
    return {'path': str(png), 'css_w': 1700, 'css_h': 900, 'overlaps': 0, 'overflow': 0}


def test_run_writes_mindmap_row_and_ledger(tmp_path):
    _pool(tmp_path)
    base, calls = tmp_path / 'inbox', []

    def ask(m):
        calls.append(m)
        return tree(), {'response_model': 'gemini-test'}

    out = fill.run(['investing_philosophy'], '2026-10-16', inbox_base=base, media_out=tmp_path / 'media', runs_dir=tmp_path / 'runs',
                   ask=ask, renderer=fake_render, accounts=[ACCT_EN], pool_items=longform_src.pool(base=tmp_path / 'lf', config={}))
    assert out['made'] == 1 and len(calls) == 1
    rows = compose_inbox.rows('2026-10-16', base=base)
    assert len(rows) == 1
    r = rows[0]
    assert r['post_kind'] == 'mindmap' and r['post_type'] == 'mindmap' and r['label'] == '思维导图'
    assert r['held'] is False and r['draft_status'] == 'draft_ready' and r['publishable'] is False
    assert r['media'][0]['kind'] == 'mindmap' and r['media'][0]['path'].endswith('.png')
    assert (tmp_path / 'media' / r['media'][0]['path']).exists()
    att = r['mindmap']['attribution']
    assert att['author'] == 'Ann' and att['url'].startswith('https://t.example/') and 'Summary of' in att['footer']
    assert r['source']['id'].startswith('blog-t-') and r['mindmap']['nodes'] >= 30 and r['mindmap']['levels'] == 4
    assert r['text'].startswith('Fees quietly')
    assert fresh_hold.check(r)[0] is False
    # second run: account now has a ready standalone (its own map) -> skipped, no model call
    out2 = fill.run(['investing_philosophy'], '2026-10-16', inbox_base=base, media_out=tmp_path / 'media', runs_dir=tmp_path / 'runs',
                    ask=ask, renderer=fake_render, accounts=[ACCT_EN], pool_items=longform_src.pool(base=tmp_path / 'lf', config={}))
    assert out2['made'] == 0 and len(calls) == 1
    # next day: the used item is not reused by the same account, the other one is
    out3 = fill.run(['investing_philosophy'], '2026-10-17', inbox_base=base, media_out=tmp_path / 'media', runs_dir=tmp_path / 'runs',
                    ask=ask, renderer=fake_render, accounts=[ACCT_EN], pool_items=longform_src.pool(base=tmp_path / 'lf', config={}))
    assert out3['made'] == 1
    ids = {x['item'] for x in fill.ledger_rows() if x['status'] == 'made'}
    assert len(ids) == 2


def test_run_skip_hard_and_render_failure(tmp_path, monkeypatch):
    _pool(tmp_path, 3)
    pool = longform_src.pool(base=tmp_path / 'lf', config={})
    kw = dict(inbox_base=tmp_path / 'inbox', media_out=tmp_path / 'media', runs_dir=tmp_path / 'runs', accounts=[ACCT_EN], pool_items=pool)
    out = fill.run(['investing_philosophy'], '2026-10-16', ask=lambda m: ({'skip': 'off topic'}, {}), renderer=fake_render, **kw)
    assert out['made'] == 0 and [t['status'] for t in out['accounts']['investing_philosophy']['tries']] == ['skip'] * 3
    monkeypatch.setenv('FD_MINDMAP_STORE', str(tmp_path / 'mm2'))
    bad = tree()
    bad['caption'] = 'See #this @someone'
    out = fill.run(['investing_philosophy'], '2026-10-17', ask=lambda m: (bad, {}), renderer=fake_render, **kw)
    assert out['made'] == 0 and out['accounts']['investing_philosophy']['tries'][0]['hard']
    monkeypatch.setenv('FD_MINDMAP_STORE', str(tmp_path / 'mm3'))
    out = fill.run(['investing_philosophy'], '2026-10-18', ask=lambda m: (tree(), {}),
                   renderer=lambda d, p: {**fake_render(d, p), 'overlaps': 2}, **kw)
    assert out['made'] == 0 and not compose_inbox.rows('2026-10-18', base=tmp_path / 'inbox')


def test_off_by_default_and_hook_guard(monkeypatch):
    assert fill.enabled() is False
    assert fill.fill_gaps('2026-10-16', accounts=['x']) == {'skipped': 'FD_MINDMAP_FILL != 1'}
    monkeypatch.setenv('FD_MINDMAP_FILL', '1')
    assert fill.enabled() is True
    src = (Path(__file__).resolve().parents[1] / 'scripts' / 'daily_compose.py').read_text()
    assert "os.environ.get('FD_MINDMAP_FILL', '0') == '1'" in src and src.index('回看 hook') < src.index('mind-map hook') < src.index('final_gates')


# ---------------------------------------------------------------- longform_src

def test_vtt_and_page_text():
    vtt = 'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello <c>there</c>\n\n00:00:02.000 --> 00:00:04.000\nHello there\nfriend\n'
    assert longform_src.vtt_to_text(vtt) == 'Hello there friend'
    html = '<html><nav>menu</nav><article><p>' + 'Real paragraph text here. ' * 5 + '</p></article></html>'
    assert 'menu' not in longform_src.page_text(html) and 'Real paragraph' in longform_src.page_text(html)


RSS = '''<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>t</title>
<item><title>New post</title><link>https://b.example/new</link><pubDate>Wed, 14 Oct 2026 10:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>%s</p>]]></content:encoded></item>
<item><title>Old post</title><link>https://b.example/old</link><pubDate>Mon, 01 Jun 2026 10:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>%s</p>]]></content:encoded></item></channel></rss>''' % (SOURCE, SOURCE)


def test_collect_blog_and_pool(tmp_path):
    cfg = {'defaults': {'min_chars': 1000, 'max_age_days': 21}, 'blogs': [{'id': 'b', 'name': 'Blog', 'feed': 'https://b.example/feed', 'lang': 'en', 'topic': 'investing'}], 'youtube': []}
    calls = []

    def transport(url, headers):
        calls.append(url)
        return 200, RSS

    s = longform_src.collect(now=NOW, base=tmp_path / 'out', config=cfg, transport=transport, log=lambda *a, **k: None)
    assert s['new'] == 1 and calls == ['https://b.example/feed']
    s2 = longform_src.collect(now=NOW, base=tmp_path / 'out', config=cfg, transport=transport, log=lambda *a, **k: None)
    assert s2['new'] == 0   # already seen
    items = longform_src.pool(base=tmp_path / 'out', config=cfg, now=NOW)
    assert len(items) == 1 and items[0]['title'] == 'New post' and items[0]['url'] == 'https://b.example/new'
    assert longform_src.read_text(items[0]).startswith('Index funds')


def test_seed_config_is_sane():
    cfg = longform_src.load_config()
    ids = [s['id'] for s in cfg['blogs'] + cfg['youtube']]
    assert len(ids) == len(set(ids)) and len(cfg['blogs']) >= 8 and len(cfg['youtube']) >= 5
    assert all(b['feed'].startswith('https://') and b['lang'] in ('en', 'zh') for b in cfg['blogs'])
    assert all(len(y['channel_id']) == 24 and y['channel_id'].startswith('UC') for y in cfg['youtube'])
    raw = json.loads((Path(__file__).resolve().parents[1] / 'live/source_registry.json').read_text())
    reg = {r['id'] for r in (raw if isinstance(raw, list) else raw.get('sources') or [])}
    assert {'lynalden', 'damodaran', 'hayes'} <= reg   # seed blogs reuse the registry's feeds


def test_video_src_transcripts_enter_pool(tmp_path, monkeypatch):
    vd = tmp_path / 'video' / '20261015'
    vd.mkdir(parents=True)
    (vd / '111.txt').write_text('存钱的第一原则' * 400)
    (vd / '111.json').write_text(json.dumps({'id': '111', 'created': 'Wed Oct 14 12:23:00 +0000 2026', 'caption': '30岁存款怎么攒钱 https://t.co/x',
                                             'language': 'zh', 'transcript_chars': 2800}))
    monkeypatch.setenv('FD_VIDEO_DIR', str(tmp_path / 'video'))
    items = longform_src.pool(base=tmp_path / 'empty', config={'x_video': {'enabled': True}}, now=NOW)
    assert items and items[0]['kind'] == 'x_video' and items[0]['id'] == 'xv-111' and items[0]['title'].startswith('30岁存款')
    monkeypatch.setenv('FD_MINDMAP_VIDEO_POOL', '0')
    assert longform_src.pool(base=tmp_path / 'empty', config={'x_video': {'enabled': True}}, now=NOW) == []


def test_caption_repair_round_and_thin_repair():
    item = {'id': 'x', 'lang': 'en', 'title': 'T', 'author': 'A', 'name': 'N', 'kind': 'blog', 'url': 'https://b.com/p', 'published_at': '2026-10-01T00:00:00+00:00'}
    bad = tree()
    bad['caption'] = "It's not luck, but discipline."
    calls = []

    def ask(m):
        calls.append(m)
        return (bad, {}) if len(calls) == 1 else ({'caption': 'Fees quietly eat a third of a long return.'}, {})

    res = gen.make_tree(ask, ACCT_EN, {}, SOURCE, item)
    assert len(calls) == 2 and res['caption'].startswith('Fees quietly') and not res['findings'] and res['stats']['caption_repaired']
    thin = {'title': 'T', 'caption': 'ok caption here', 'branches': tree()['branches'][:2]}
    seq = [thin, tree()]
    res = gen.make_tree(lambda m: (seq.pop(0), {}), ACCT_EN, {}, SOURCE, item)
    assert res['stats'].get('repair_round') and res['stats']['nodes'] >= 36


def test_x_video_credit_has_no_handle(tmp_path, monkeypatch):
    vd = tmp_path / 'video' / '20261015'
    vd.mkdir(parents=True)
    (vd / '222.txt').write_text('存钱' * 900)
    (vd / '222.json').write_text(json.dumps({'id': '222', 'created': 'Wed Oct 14 12:23:00 +0000 2026', 'caption': '攒钱的方法', 'language': 'zh'}))
    monkeypatch.setenv('FD_VIDEO_DIR', str(tmp_path / 'video'))
    it = longform_src.pool(base=tmp_path / 'empty', config={'x_video': {'enabled': True, 'credit': 'X 视频'}}, now=NOW)[0]
    assert '@' not in it['author'] and 'X' in gen.credit_footer(it, 'zh') and '@' not in gen.credit_footer(it, 'zh')


def test_caption_numbers_must_be_in_source():
    assert gen.caption_findings('A fund charging 1.5% gives up a third.', 'en', SOURCE) == []
    codes = [c for c, _ in gen.caption_findings('A fund charging 9.9% gives up a third.', 'en', SOURCE)]
    assert codes == ['mm_caption_number']


def test_reply_only_not_filled_but_absent_is_(tmp_path):
    base = tmp_path / 'inbox'
    assert fill.gate('btc_cycles_en', '2026-10-16', base=base)[0] is True             # genuinely absent -> fill
    compose_inbox.add(_row('btc_cycles_en', 'q-1', post_format={'engage': 'quote'}), base=base)
    assert fill.gate('btc_cycles_en', '2026-10-16', base=base)[0] is False
    compose_inbox.add(_row('zh_macro', 'h-1', held=True, draft_status='needs_review'), base=base)
    assert fill.gate('zh_macro', '2026-10-16', base=base)[0] is True                  # only a held row: still absent


def test_tone_list_and_env_override(monkeypatch, tmp_path):
    assert fill.eligible('investing_philosophy')[0] and fill.eligible('crypto_btc_cycle_zh')[0]
    for aid in ('crypto_trader_zh', 'funding_arb_zh', 'crypto_airdrop_en', 'options_vol_en', 'exchange_perks_zh', 'brand_new_account'):
        assert fill.eligible(aid)[0] is False, aid                                      # hype / trader / unknown -> no
    monkeypatch.setenv('FD_MINDMAP_ACCOUNTS', 'crypto_trader_zh')
    assert fill.eligible('crypto_trader_zh')[0] and not fill.eligible('investing_philosophy')[0]
    monkeypatch.delenv('FD_MINDMAP_ACCOUNTS')
    assert fill.tone_accounts(tmp_path / 'missing.json') == set()
    assert fill.eligible('investing_philosophy', path=tmp_path / 'missing.json')[0] is False


def test_run_skips_ineligible_account(tmp_path):
    _pool(tmp_path)
    acct = {**ACCT_EN, 'id': 'crypto_trader_en', 'beat': 'Crypto trading'}
    out = fill.run(['crypto_trader_en'], '2026-10-16', inbox_base=tmp_path / 'inbox', media_out=tmp_path / 'm', runs_dir=tmp_path / 'r',
                   ask=lambda m: (tree(), {}), renderer=fake_render, accounts=[acct], pool_items=longform_src.pool(base=tmp_path / 'lf', config={}))
    assert out['made'] == 0 and 'tone' in out['accounts']['crypto_trader_en']['skip']


def test_off_lane_source_is_held(tmp_path):
    _pool(tmp_path, 1)
    d = tmp_path / 'lf' / '20261015' / 'blog-t-0.json'
    meta = json.loads(d.read_text())
    meta.update({'topic': 'general', 'title': '台积电：只吃饼不画饼，当得了带头大哥吗？', 'lang': 'zh'})
    d.write_text(json.dumps(meta))
    acct = {'id': 'crypto_btc_cycle_zh', 'lang': 'en', 'beat': 'Bitcoin cycles', 'name': 'B', 'no': 7}
    assert fill.lane_check(acct, meta)['ok'] is False
    assert fill.lane_check(acct, {'title': 'Bitcoin halving cycle and liquidity', 'topic': 'crypto'})['ok'] is True
    base = tmp_path / 'inbox'
    out = fill.run(['crypto_btc_cycle_zh'], '2026-10-16', inbox_base=base, media_out=tmp_path / 'm', runs_dir=tmp_path / 'r',
                   ask=lambda m: (tree(), {'response_model': 'gemini-test'}), renderer=fake_render, accounts=[acct],
                   pool_items=longform_src.pool(base=tmp_path / 'lf', config={}))
    r = compose_inbox.rows('2026-10-16', base=base)[0]
    assert out['made'] == 1 and r['held'] is True and r['hold_reason'] == 'off_lane' and r['draft_status'] == 'needs_review'
