import copy
import json
from live.content_store import ContentStore
from tests.test_content_store import source, unit
from live.adapters import cftc
from pathlib import Path


def test_content_and_near_duplicates(tmp_path):
    s = source(); u = unit(s); store = ContentStore(tmp_path)
    store.add(s, [u], adapter='bls_api')
    v = copy.deepcopy(u); v['unit_id'] = 'new'; v['statement'] = 'PAYROLLS rose 22000!'
    assert store.add(s, [v], adapter='bls_api')['duplicate_content'] == 1
    v['numbers'][0]['period'] = 'October 2026'
    assert store.add(s, [v], adapter='bls_api')['added'] == 1


def test_cftc_refetch(tmp_path):
    data = json.loads(next(Path('tests/fixtures/sources').glob('*cftc*.json')).read_text())
    out = cftc.to_source_and_units(data); s = out['sources'][0]
    store = ContentStore(tmp_path); store.add(s, out['units'], adapter='cftc')
    units = [dict(u, unit_id='new-' + u['unit_id'], source_hash='new-hash') for u in out['units']]
    assert store.add(dict(s, source_hash='new-hash'), units, adapter='cftc')['duplicate_content'] == len(units)


def test_suppression_append_only(tmp_path):
    from scripts.dedup_store import dedup_store
    s = source(); u = unit(s); store = ContentStore(tmp_path); store.add(s, [u], adapter='bls_api')
    row = copy.deepcopy(store.units()[0]); row['unit_id'] = row['unit']['unit_id'] = 'later'
    with store.path.open('a') as f: f.write(json.dumps(row) + '\n')
    before = store.path.read_bytes()
    assert len(dedup_store(tmp_path)) == 1
    assert store.path.read_bytes() == before
    assert len(ContentStore(tmp_path).units()) == 1
    assert dedup_store(tmp_path) == []


def test_near_duplicate_threshold_and_publishers(tmp_path):
    s=source(); u=unit(s); u['statement']='Payroll employment rose steadily across the country this September'
    store=ContentStore(tmp_path); store.add(s,[u],adapter='bls_api')
    v=copy.deepcopy(u); v['unit_id']='near'; v['statement']='Payroll employment rose steadily across the country this September report'
    assert store.add(s,[v],adapter='bls_api')['duplicate_content']==1
    assert store.add(dict(s,publisher='Other publisher'),[v],adapter='other')['added']==1
    w=copy.deepcopy(u); w['unit_id']='different'; w['statement']='Job losses accelerated across two industries'
    assert store.add(s,[w],adapter='bls_api')['added']==1
