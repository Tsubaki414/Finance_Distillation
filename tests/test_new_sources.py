"""Offline contracts for the dedicated public source adapters."""
import importlib
import ctypes
import json
from decimal import Decimal
from pathlib import Path

import pytest

from live.adapters import common
from live import content_units, registry

FIX = Path(__file__).parent / 'fixtures/sources'


def fixture(name):
    if name == 'berkshire_letters.html':
        # Captured HTTP body is Brotli-compressed Windows-1252 HTML. The Python
        # Brotli package is absent from the offline venv; use the system decoder.
        body = (FIX / name).read_bytes()
        decoder = ctypes.CDLL('libbrotlidec.so.1').BrotliDecoderDecompress
        decoder.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
        decoder.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(1024 * 1024)
        size = ctypes.c_size_t(len(buffer))
        assert decoder(len(body), body, ctypes.byref(size), buffer) == 1
        return buffer.raw[:size.value].decode('cp1252')
    return (FIX / name).read_text()


def transport(url, headers):
    if 'cftc.gov' in url:
        name = 'cftc_tff.json'
    elif 'cboe.com' in url:
        name = url.split('/')[-1].lower()
    elif 'farside' in url:
        name = 'farside_btc.html' if 'bitcoin' in url else 'farside_eth.html'
    elif 'llama.fi' in url:
        name = 'defillama_stablecoincharts_all.json'
    elif 'oaktree' in url:
        name = 'oaktree_index.html' if url.endswith('/memos') else 'oaktree_memo.html'
    elif 'glassnode' in url:
        name = 'glassnode.rss'
    elif url.endswith('.pdf'):
        return 200, b'%PDF-test'
    else:
        name = 'berkshire_letters.html'
    return 200, fixture(name)


@pytest.mark.parametrize('name,count,tier', [('cftc', 15, 'A'), ('cboe', 5, 'B'),
                                            ('farside', 14, 'B'), ('defillama', 3, 'B')])
def test_data_fixtures(name, count, tier):
    out = importlib.import_module('live.adapters.' + name).fetch(transport=transport)
    assert out['status'] == 'ok'
    assert out['requests'] > 0
    assert len(out['units']) == count
    for src in out['sources']:
        units = [u for u in out['units'] if u['source_hash'] == src['source_hash']]
        assert units
        # Revalidate the raw contract rather than relying on returned metadata.
        raws = [{k: u[k] for k in ('kind', 'statement', 'speaker', 'speaker_type', 'freshness_class', 'source_spans', 'numbers')} for u in units]
        valid, dropped = content_units.validate_units_partial(src, {'units': raws}, tier)
        assert not dropped
        assert len(valid) == len(units)
        for u in units:
            assert u['licence_tier'] == tier
            for n in u['numbers']:
                assert n['text'] in u['statement']
                assert n['period'] in u['statement']
    text = '\n'.join(s['original_text'] for s in out['sources'])
    if name == 'cftc':
        assert 'week ending 2026-09-29' in text
        assert '-2036432' in text
        assert '-109485' in text
    elif name == 'cboe':
        assert '15.310000' in text
        assert '0.44' in text
        assert 'contango' in text
    elif name == 'farside':
        assert '-148.7' in text and '82.9' in text and '-118.0' in text
        assert 'FBTC' in text and 'FETH' in text
    else:
        assert '312.0' in text


def test_farside_missing_is_not_zero():
    from live.adapters import farside
    assert farside.flow_value('(10.9)') == Decimal('-10.9')
    assert farside.flow_value('-') is None
    rows = farside.parse_table(fixture('farside_btc.html'))
    assert len(rows) == 11
    assert rows[-1]['funds']['IBIT'] is None
    assert rows[-1]['total'] == Decimal('31.7')


@pytest.mark.parametrize('kind,source_id', [('oaktree', 'oaktree_memos'), ('berkshire', 'berkshire_letters'),
                                          ('glassnode', 'glassnode_research')])
def test_longform_fixtures(kind, source_id):
    from live.adapters import longform
    kwargs = {'transport': transport}
    if kind == 'berkshire':
        kwargs['converter'] = lambda body: fixture('berkshire_2025ltr.txt')
    else:
        kwargs['limit'] = 1
    out = getattr(longform, 'fetch_' + kind)(**kwargs)
    assert out['status'] == 'ok'
    assert out['sources']
    assert all(s['source_id'] == source_id and len(s['original_text']) <= common.MAX_CHARS for s in out['sources'])
    text = '\n\n'.join(s['original_text'] for s in out['sources'])
    if kind == 'oaktree':
        assert out['sources'][0]['author_name'] == 'Howard Marks'
        assert out['sources'][0]['published_at'].startswith('2026-09-22')
        assert 'Legal Information and Disclosures' not in text
        assert 'Client Login' not in text
    elif kind == 'berkshire':
        assert out['sources'][0]['published_at'].startswith('2026-02')
        assert out['sources'][0]['published_at_approximate']
        assert 'Operational Excellence' in text
        assert len(out['sources']) > 1
    else:
        assert 'Bitcoin' in text
        assert len(text) > 3000


def test_chunking():
    kwargs = dict(id='test', source_id='test', publisher='Test', title='Title', url='https://test',
                  published_at='2026-10-04', adapter='test')
    parts = common.make_sources_chunked(text='aaaa\n\nbbbb\n\ncccc', max_chars=10, **kwargs)
    assert [s['id'] for s in parts] == ['test-p1', 'test-p2']
    assert [s['title'] for s in parts] == ['Title (part 1/2)', 'Title (part 2/2)']
    assert '\n\n'.join(s['original_text'] for s in parts) == 'aaaa\n\nbbbb\n\ncccc'
    capped = common.make_sources_chunked(text='a' * 40, max_chars=10, max_parts=3, **kwargs)
    assert len(capped) == 3 and capped[-1]['truncated']


def test_registries():
    rows = {r['id']: r for r in json.loads(Path('live/source_registry.json').read_text())['sources']}
    for sid in ('primary_cftc', 'cboe_indices', 'farside_etf_flows', 'defillama_stablecoins',
                'oaktree_memos', 'berkshire_letters', 'glassnode_research'):
        assert registry.source_licence_tier(sid) == ('A' if sid == 'primary_cftc' else 'B')
        assert rows[sid]['enabled']
        assert rows[sid]['persona_hints']


def test_berkshire_probes_current_letter_before_stale_buffett_index():
    from datetime import date
    from live.adapters import longform
    urls = []

    def get(url, headers):
        urls.append(url)
        return transport(url, headers)

    out = longform.fetch_berkshire(transport=get, as_of=date(2026, 10, 4),
                                  converter=lambda pdf: fixture('berkshire_2025ltr.txt'))
    assert urls[-1].endswith('/2025ltr.pdf')
    assert out['sources'][0]['published_at'].startswith('2026-02')


def test_runner_routes_each_source_to_its_own_units(monkeypatch):
    from types import SimpleNamespace
    from scripts import run_content_adapters as runner
    from live.adapters import longform
    for name in ('cftc', 'cboe', 'farside', 'defillama'):
        module = importlib.import_module('live.adapters.' + name)
        original = module.fetch
        monkeypatch.setattr(module, 'fetch', lambda original=original: original(transport=transport))
    for name in ('oaktree', 'glassnode'):
        original = getattr(longform, 'fetch_' + name)
        monkeypatch.setattr(longform, 'fetch_' + name,
                            lambda original=original, **kwargs: original(transport=transport, **kwargs))
    original = longform.fetch_berkshire
    monkeypatch.setattr(longform, 'fetch_berkshire', lambda: original(transport=transport,
                        converter=lambda pdf: fixture('berkshire_2025ltr.txt')))
    args = SimpleNamespace(adapters=['cftc', 'cboe', 'farside', 'defillama', 'oaktree', 'berkshire', 'glassnode'],
                           oaktree_n=2, glassnode_n=1)
    report = {'adapters': {}}
    text, data = runner.gather(args, report)
    assert len(report['adapters']) == 7
    assert len(data) == 5
    assert {s['source_id'] for s in text} == {'oaktree_memos', 'berkshire_letters', 'glassnode_research'}
    for src, units, adapter in data:
        assert units and all(u['source_hash'] == src['source_hash'] for u in units)
        assert src['adapter'] == adapter


@pytest.mark.parametrize('name', ['cftc', 'cboe', 'farside', 'defillama'])
def test_http_failures_are_reported(name):
    module = importlib.import_module('live.adapters.' + name)
    out = module.fetch(transport=lambda url, headers: (503, 'unavailable'))
    assert out['status'] == 'http_503'
    assert out['requests'] >= 1
    assert not out['sources'] and not out['units']


def test_berkshire_404_falls_back_to_indexed_letter():
    from datetime import date
    from live.adapters import longform
    calls = []

    def get(url, headers):
        calls.append(url)
        if url.endswith('/2025ltr.pdf'):
            return 404, b''
        if url.endswith('/2024ltr.pdf'):
            return 200, b'%PDF-2024'
        return transport(url, headers)

    out = longform.fetch_berkshire(transport=get, as_of=date(2026, 10, 4), converter=lambda body: 'Actual 2024 letter.')
    assert out['requests'] == 3
    assert out['sources'][0]['url'].endswith('/2024ltr.pdf')
    assert out['sources'][0]['letter_year_from_index']


def test_pdf_converter_uses_binary_stdin(monkeypatch):
    from types import SimpleNamespace
    from live.adapters import longform
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=b'Converted letter.')

    monkeypatch.setattr(longform.subprocess, 'run', run)
    assert longform.pdf_text(b'%PDF-content') == 'Converted letter.'
    assert calls[0][0] == ['pdftotext', '-', '-']
    assert calls[0][1]['input'] == b'%PDF-content'
    assert calls[0][1]['check']


def test_berkshire_index_blocked_still_probes_letter_pdf():
    """The letters index sits behind a bot challenge (307, no Location); the PDF itself is public."""
    from datetime import date
    from live.adapters import longform
    seen = []

    def get(url, headers):
        seen.append(url)
        if url.endswith('letters.html'):
            return 307, ''
        if url.endswith('2025ltr.pdf'):
            return 200, b'%PDF'
        return 404, b''

    out = longform.fetch_berkshire(transport=get, as_of=date(2026, 10, 4),
                                   converter=lambda body: 'Letter paragraph one.\n\nLetter paragraph two.')
    assert out['status'] == 'ok' and out['sources']
    assert out['sources'][0]['url'].endswith('2025ltr.pdf')
    assert out['index_status'] == 'http_307'


def test_cftc_covers_vix_rates_fx_and_small_caps_for_two_weeks():
    from urllib.parse import parse_qs, urlsplit
    from live.adapters import cftc
    for code in ('1170E1', '042601', '239742', '097741', '13874A'):
        assert code in cftc.CODES
        assert f"'{code}'" in parse_qs(urlsplit(cftc.URL).query)['$where'][0]
    assert int(parse_qs(urlsplit(cftc.URL).query)['$limit'][0]) >= 2 * len(cftc.CODES)
