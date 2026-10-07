"""Four Pillars (public research, tier B, account-scoped) and Delphi Digital (browser digest, inspiration_only)."""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from live.adapters import delphi_digest, fourpillars
from live.licence_rules import inspiration_findings

ROUTED = ['crypto_research_en', 'crypto_research_zh', 'defi_narratives_en', 'crypto_thesis_en']
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _issue(title, link, date, articles):
    body = '<h2><strong>1. Main News</strong></h2><h3><strong>[Institution] News item</strong></h3><p>x</p>'
    body += '<h2><strong>2. Four Pillars Weekly</strong></h2>'
    for t, url, claims in articles:
        body += f'<h3><strong>: : {t} (<a href="{url}">Link</a>)</strong></h3><div><figure>img</figure></div>'
        body += '<ul>' + ''.join(f'<li><p>{c}</p></li>' for c in claims) + '</ul>'
    return (f'<item><title>{title}</title><link>{link}</link><pubDate>{date}</pubDate>'
            f'<content:encoded><![CDATA[{body}]]></content:encoded></item>')


FEED = ('<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
        + _issue('Weekly 39', 'https://fourpillarsfp.substack.com/p/w39', 'Mon, 21 Sep 2026 05:38:30 GMT', [
            ('All about x402', 'https://research.4pillars.io/en/research/all-about-x402',
             ['x402 turns HTTP 402 into a payment rail for agents.', 'Adoption is still mostly test traffic.']),
            ('Chart only', 'https://research.4pillars.io/en/data/content/chart-only', [])])
        + _issue('Weekly 38', 'https://fourpillarsfp.substack.com/p/w38', 'Mon, 14 Sep 2026 02:17:36 GMT', [
            ('All about x402', 'https://research.4pillars.io/en/research/all-about-x402', ['earlier listing']),
            ('Old &amp; piece', 'https://research.4pillars.io/en/research/old-piece', ['An old claim.'])])
        + _issue('Weekly 20', 'https://fourpillarsfp.substack.com/p/w20', 'Mon, 11 May 2026 04:35:08 GMT', [
            ('Stale', 'https://research.4pillars.io/en/research/stale', ['Too old for the window.'])])
        + '</channel></rss>').encode()


# ---------------------------------------------------------------- Four Pillars

def test_articles_parse_title_url_date_summary_claims_and_dedupe_earliest_issue():
    arts = {a['url'].rsplit('/', 1)[1]: a for a in fourpillars.articles(FEED)}
    assert set(arts) == {'all-about-x402', 'chart-only', 'old-piece', 'stale'}
    x = arts['all-about-x402']
    assert (x['title'], x['date'], x['issue_title']) == ('All about x402', '2026-09-14', 'Weekly 38')
    assert x['key_claims'] == ['earlier listing'] and x['summary'] == 'earlier listing'
    assert arts['old-piece']['title'] == 'Old & piece'
    assert arts['chart-only']['key_claims'] == []


def test_fetch_window_and_sources():
    out = fourpillars.fetch(transport=lambda url: FEED, now=NOW)
    assert out['status'] == 'ok' and len(out['articles']) == 4
    assert [s['title'] for s in out['sources']] == ['All about x402', 'Old & piece']   # no chart-only, no stale
    s = out['sources'][0]
    assert s['source_id'] == 'fourpillars_research' and s['adapter'] == 'fourpillars'
    assert s['url'] == 'https://research.4pillars.io/en/research/all-about-x402'
    assert s['published_at'].startswith('2026-09-14') and s['key_claims'] == ['earlier listing']
    assert s['original_text'] == 'All about x402\n\nearlier listing'


def test_fetch_failure_is_a_status_not_a_crash():
    def boom(url):
        raise OSError('429 checkpoint')
    out = fourpillars.fetch(transport=boom)
    assert out['status'].startswith('failed') and out['sources'] == []


def test_fourpillars_registry_licence_and_routes():
    from live import registry, source_routes
    assert registry.source_licence_tier('fourpillars_research') == 'B'
    assert registry.source_licence_tier('x_FourPillarsFP') == 'B'
    assert registry.source_licence_tier('delphi_digital') == 'C'
    rows = {r['id']: r for r in json.loads(Path('live/source_registry.json').read_text())['sources']}
    assert rows['delphi_digital']['type'] == 'research' and rows['delphi_digital']['adapter'] == 'browser_digest'
    assert rows['x_FourPillarsFP']['handle'] == 'FourPillarsFP'
    r = source_routes.route('fourpillars_research')
    assert sorted(r['accounts']) == sorted(ROUTED) and r['beats'] == ('crypto_defi',)
    for a in ROUTED:
        assert source_routes.allowed({'source_id': 'fourpillars_research'}, a)
    assert not source_routes.allowed({'source_id': 'fourpillars_research'}, 'crypto_macro_zh')
    assert source_routes.allowed({'source_id': 'sec_edgar'}, 'crypto_macro_zh')
    tags = source_routes.tags_for([{'unit_id': 'u1'}], 'fourpillars_research', {'u1': {'old': {'x': 1}}})
    assert set(tags['u1']) == {'old', 'crypto_defi'} and tags['u1']['crypto_defi']['confidence'] >= .7
    merge = json.loads(Path('live/fd20_donor_merge.json').read_text())
    subscribed = [a for a, v in merge['accounts'].items() if 'FourPillarsFP' in sum(v['x_sources'].values(), [])]
    assert sorted(subscribed) == sorted(ROUTED)
    assert 'FourPillarsFP' in merge['sources_only']


def test_daily_ingest_routes_fourpillars_without_jev(tmp_path):
    from live.daily_ingest import run
    from live.content_store import ContentStore
    src = fourpillars.fetch(transport=lambda url: FEED, now=NOW)['sources'][0]

    class NoJev:
        def review(self, state, questions):
            pytest.fail('routed research sources must not go through Jev')

    def extract(s):
        return [{'unit_id': s['id'], 'source_hash': s['source_hash'], 'statement': 'Four Pillars argues x402 is early.',
                 'kind': 'view', 'numbers': [], 'licence_tier': 'B', 'usage': 'paraphrase', 'speaker': 'Four Pillars'}]
    r = run(store=tmp_path / 'store', runs_dir=tmp_path / 'runs', inbox=tmp_path / 'inbox',
            state_path=tmp_path / 'state.json', no_dashboard=True,
            fetchers={'research:fourpillars_research': lambda: {'sources': [src]}}, extract=extract, jev=NoJev(),
            backup=lambda: None, refresh=lambda: None)
    assert r['channels'][0]['units'] == 1, r
    row = ContentStore(tmp_path / 'store').units()[0]
    assert row['tag_personas'] == ['crypto_defi'] and row['source']['source_id'] == 'fourpillars_research'


# ---------------------------------------------------------------- Delphi digest

def _entry(**kw):
    e = {'title': 'Perp venues are eating the order book', 'url': 'https://members.delphidigital.io/reports/x',
         'date': '2026-10-07', 'kind': 'report', 'tickers': ['HYPE', '$ASTER'],
         'thesis_summary': 'Our read: on-chain perp venues keep gaining share, mostly through fee discounts.',
         'key_numbers': [{'value': '62%', 'context': 'largest venue share of on-chain perp volume, September'},
                         {'value': '$1.9 billion', 'context': 'daily on-chain perp volume'}]}
    e.update(kw)
    return e


def test_sample_file_validates():
    payload = json.loads(Path('docs/samples/delphi_digest_sample.json').read_text())
    assert delphi_digest.validate(payload) == {'ok': True, 'items': 2, 'errors': []}
    assert delphi_digest.main(['docs/samples/delphi_digest_sample.json']) == 0


@pytest.mark.parametrize('field,value,needle', [
    ('url', 'http://x', 'https'), ('date', '10/07/2026', 'YYYY-MM-DD'), ('kind', 'note', 'kind'),
    ('tickers', ['eth'], 'tickers'), ('thesis_summary', 'short', '>= 20'),
    ('thesis_summary', 'They wrote "perp volume will flip spot within a year" in the report', 'quoted'),
    ('key_numbers', [{'value': 'about half', 'context': 'share of volume'}], 'number'),
    ('key_numbers', [{'value': '62%'}], 'value'), ('key_numbers', [{'value': '62%', 'context': 'x'}], 'context')])
def test_invalid_entries_rejected(field, value, needle):
    errors = delphi_digest.validate_item(_entry(**{field: value}))
    assert errors and any(needle in e for e in errors), errors


def test_extra_fields_and_missing_fields_rejected():
    assert any('unknown fields' in e for e in delphi_digest.validate_item(_entry(body='pasted report text')))
    bad = _entry(); bad.pop('key_numbers')
    assert 'missing key_numbers' in delphi_digest.validate_item(bad)
    assert not delphi_digest.validate({'not': 'a list'})['ok']


def test_load_day_skips_invalid_entries_and_marks_licence(tmp_path):
    (tmp_path / '2026-10-07.json').write_text(json.dumps([_entry(), _entry(kind='bad', url='https://y')]))
    out = delphi_digest.load_day('2026-10-07', tmp_path)
    assert out['status'] == 'partial' and len(out['units']) == 1 and out['errors'][0]['index'] == 1
    u = out['units'][0]
    assert (u['licence'], u['licence_tier'], u['quote_allowed'], u['citable']) == ('inspiration_only', 'C', False, False)
    assert u['tickers'] == ['ASTER', 'HYPE']
    assert delphi_digest.load_day('2026-10-06', tmp_path)['status'] == 'missing'
    for now in (NOW, NOW.isoformat(), '2026-10-07', NOW.date()):
        assert [x['unit_id'] for x in delphi_digest.recent(now=now, directory=tmp_path)] == [u['unit_id']]
    assert delphi_digest.steer_tickers([u]) == {'ASTER': 1, 'HYPE': 1}
    hints = delphi_digest.stance_hints([u], ['hype'])
    assert hints and set(hints[0]) == {'tickers', 'kind', 'thesis_summary'}   # never numbers or title


def test_delphi_units_can_never_enter_the_content_store(tmp_path):
    from live.content_store import ContentStore
    u = delphi_digest.to_unit(_entry(), '2026-10-07')
    with pytest.raises(ValueError, match='not writable'):
        ContentStore(tmp_path).add({'id': 'd', 'source_id': 'delphi_digital'}, [u], adapter='browser_digest')


# ---------------------------------------------------------------- licence gate

def _public(text, numbers=()):
    return {'licence_tier': 'B', 'statement': '', 'source_spans': [{'exact_text': text}],
            'numbers': [{'text': n} for n in numbers]}


DELPHI = [delphi_digest.to_unit(_entry(), '2026-10-07')]


def codes(findings):
    return sorted(f['code'] for f in findings)


def test_delphi_number_blocked_without_public_source():
    f = inspiration_findings('The biggest perp venue now holds 62% of on-chain volume.', DELPHI, [], None)
    assert codes(f) == ['inspiration_only_number'] and f[0]['detail'] == '62%'
    assert 'September' not in json.dumps(f)   # digest context never leaks into the rewrite note
    # rounding a digest figure is still the digest figure
    assert codes(inspiration_findings('Daily perp volume is near $1.9bn.', DELPHI, [], None)) == ['inspiration_only_number']
    assert codes(inspiration_findings('Daily perp volume is near $2 billion.', DELPHI, [], None)) == ['inspiration_only_number']


def test_delphi_number_allowed_when_a_public_unit_gives_it():
    body = 'The biggest perp venue now holds 62% of on-chain volume.'
    assert inspiration_findings(body, DELPHI, [_public('DefiLlama: top venue share 62% in September', ['62%'])], None) == []
    # public source text also counts; a tier C unit does not
    assert inspiration_findings(body, DELPHI, [], {'original_text': 'Share reached 62% last month.'}) == []
    restricted = dict(_public('top venue 62%', ['62%']), licence_tier='C')
    assert codes(inspiration_findings(body, DELPHI, [restricted], None)) == ['inspiration_only_number']


def test_other_numbers_years_and_small_counts_pass():
    body = 'In 2026 three venues matter; the top one holds 48% of volume.'
    assert inspiration_findings(body, DELPHI, [_public('48% share', ['48%'])], None) == []


def test_delphi_citation_and_title_wording_blocked():
    assert codes(inspiration_findings('Per Delphi, perp venues keep winning.', DELPHI)) == ['inspiration_only_cited']
    assert codes(inspiration_findings('据德尔菲，永续合约份额继续上升。', DELPHI)) == ['inspiration_only_cited']
    f = inspiration_findings('Perp venues are eating the order book, and fees explain it.', DELPHI)
    assert codes(f) == ['inspiration_only_text']
    assert inspiration_findings('Perp venues keep gaining share through fee discounts.', DELPHI) == []
    assert inspiration_findings('anything 62%', [], []) == []


def test_compose_post_checks_hold_delphi_number(tmp_path, monkeypatch):
    from live import compose, qa_levels, registry
    from tests.test_content_store import source, unit
    today = datetime.now(timezone.utc).date().isoformat()
    (tmp_path / f'{today}.json').write_text(json.dumps([_entry(date=today)]))
    monkeypatch.setattr(delphi_digest, 'DIGEST_DIR', tmp_path)
    u = unit(source())
    text = 'Perp venues keep gaining share; the top one holds 62% of on-chain volume.'
    findings = compose.post_checks('data_take', text, text, None, 'B', [u],
                                   SimpleNamespace(lang='en', persona_id='test_persona', voice_card={}),
                                   registry.load_post_types())
    hit = [f for f in findings if f['code'] == 'inspiration_only_number']
    assert hit and hit[0]['level'] == 'hard' and qa_levels.draft_status(findings) == 'needs_review'
    assert 'inspiration_only_number' in compose.HARD_FIXES


def test_daily_compose_steer_matches_whole_tickers():
    import sys
    sys.path.insert(0, 'scripts')
    import daily_compose
    group = [{'source': {'title': 'HYPE buybacks accelerate'}, 'unit': {'statement': 'x', 'view': None}}]
    assert daily_compose.steered(group, {'HYPE'})
    assert not daily_compose.steered(group, {'HYP'}) and not daily_compose.steered(group, set())
