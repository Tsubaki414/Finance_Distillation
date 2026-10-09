"""Oct 9 night: one hung / CPU-bound extract task must not stall the nightly; it fails and the run continues."""
import time
from live.adapters.common import make_source


def source(sid):
    return make_source(id=sid, source_id='sec_edgar', text=sid+' distinct evidence', publisher=sid,
                       title=sid, url='https://example.test/'+sid, published_at='2026-10-04', adapter='edgar')


def test_slow_task_times_out_and_run_continues(tmp_path, monkeypatch):
    from live.daily_ingest import run
    monkeypatch.setenv('FD_INGEST_TASK_TIMEOUT', '1')
    seen = []

    def extract(s):
        seen.append(s['id'])
        if s['id'] == 'hang':
            while True:   # CPU-bound, no I/O
                sum(range(1000))
        return [{'unit_id': s['id'], 'source_hash': s['source_hash'], 'statement': s['original_text'], 'kind': 'fact',
                 'numbers': [], 'licence_tier': 'A', 'usage': 'quote', 'speaker': s['publisher']}]
    fs = {'cboe': lambda: {'sources': [dict(source('hang'), source_id='cboe')]},
          'other': lambda: {'sources': [dict(source('good'), source_id='other')]}}
    t = time.monotonic()
    r = run(store=tmp_path/'store', runs_dir=tmp_path/'runs', inbox=tmp_path/'inbox', state_path=tmp_path/'state.json',
            no_dashboard=True, fetchers=fs, extract=extract, backup=lambda: None, refresh=lambda: None)
    assert time.monotonic() - t < 30
    st = {c['id']: c for c in r['channels']}
    assert st['cboe']['status'] == 'failed' and 'exceeded' in st['cboe']['error']
    assert st['other']['status'] == 'ok' and seen == ['hang', 'good']
