"""Offline durability tests with explicitly synthetic adapter outputs.

These tests exercise real Store/SQLite/admission/dashboard plumbing. They are not
claims of real model generation, human acceptance, or live source coverage.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, PropertyMock

from backend import account_intelligence as api
from backend.content_dashboard import app
from fastapi.testclient import TestClient
from live.account_intelligence import Store, digest
from live.account_monitor import ACCOUNTS, Monitor, State, configuration, monitor_status, daily_draft_count
from live.account_sources import SourcePipeline, ingest, universes
from live.monitor_intake import FetchResult, IntakeFailure
from ml import budget


DATES = ('2026-09-27T12:00:00+00:00', '2026-09-28T12:00:00+00:00', '2026-09-29T12:00:00+00:00')
SOURCE_IDS = {'en_morris_archive': 'x_Morris_LT', 'zh_macro': 'overshoot', 'zh_industry': 'semianalysis'}


def source(account, key, published=None, **extra):
    sid = SOURCE_IDS[account]
    if account == 'en_morris_archive':
        url, author, text, lang = ('https://x.com/Morris_LT/status/' + str(key), 'Morris_LT',
            '先记录判断，再反复检验条件。保留案例与反馈。测试样本' + str(key), 'zh')
    else:
        host = 'theovershoot.co' if account == 'zh_macro' else 'newsletter.semianalysis.com'
        url, author, text, lang = ('https://' + host + '/p/test-' + str(key), sid,
            'TEST SOURCE: ' + ('Inflation and rates' if account == 'zh_macro' else 'GPU and memory') +
            ' require checking conditions and examples. Case ' + str(key), 'en')
    return {'id': 'test-' + account + '-' + str(key), 'source_id': sid, 'url': url,
            'author_name': author, 'author_handle': author if account == 'en_morris_archive' else None,
            'original_text': text, 'source_language': lang, 'published_at': published or DATES[0],
            'fetched_at': DATES[0], 'content_complete': True, 'synthetic': True, **extra}


class Poller:
    """Deliberately repeats prior rows to test durable downstream dedup."""
    def __init__(self, pages=None):
        self.pages, self.calls = pages or {}, []

    def fetch(self, account, sub, cursor, *, as_of, limit):
        self.calls.append((account, sub['source_id'], copy.deepcopy(cursor), as_of))
        value = self.pages.get((account, sub['source_id'], as_of), [])
        if isinstance(value, Exception):
            raise value
        if isinstance(value, FetchResult):
            return value
        return FetchResult(copy.deepcopy(value), {'account_id': account,
            'source_id': sub['source_id'], 'checked_at': as_of}, True, {})


class Adapter:
    def __init__(self):
        self.calls, self.outcomes = [], {}

    def __call__(self, row, account, directory, **kwargs):
        self.calls.append((account, row, kwargs))
        planned = self.outcomes.get(row['url'], [])
        outcome = planned.pop(0) if planned else 'draft'
        route = {'decision': 'MOVE', 'reason': 'TEST DOUBLE, not editorial evidence'}
        if outcome == 'skip':
            return {'status': 'skipped', 'draft_status': 'skipped', 'final_draft': '',
                    'route': {'decision': 'SKIP', 'reason': 'TEST DOUBLE: not worthwhile'}}
        if outcome != 'draft':
            return {'status': 'held', 'draft_status': 'blocked', 'final_draft': '', 'route': route,
                    'execution_failure': {'code': outcome, 'stage': 'translation'}}
        return {'status': 'draft_ready', 'draft_status': 'draft_ready',
                'final_draft': 'TEST DOUBLE: Recheck the conditions.' if account == 'en_morris_archive' else '测试替身：重新检查条件。',
                'route': route, 'selection': {'passages': []}, 'machine_fidelity': {'status': 'pass'}}


class MonitorTests(unittest.TestCase):
    def test_new_capacity_repair_rearms_exhausted_execution_once_without_resetting_counter(self):
        from live.content_stages import follow_up_repairs
        monitor = self.monitor()
        candidate_id = 'saved-capacity-candidate'
        parent = {'id':'old-localization-length','pipeline':'account_source','account_id':'zh_industry',
            'inbox_candidate_id':candidate_id,'recorded_at':DATES[0], 'status':'execution_failed','candidates':[],
            'stage_configuration':{'provider':'same-provider','execution_repairs':[]},
            'source_adaptation':{'draft_status':'blocked',
                'execution_failure':{'stage':'localization','code':'response_incomplete'},
                'attempt':{'model_responses':[{'stage':'localization','finish_reason':'length','text':''}]}}}
        self.store.append('runs',parent)
        key,_ = monitor.state.enqueue('zh_industry','semianalysis',source('zh_industry','capacity'),DATES[0],
            status='blocked_execution',candidate_id=candidate_id,last_run=parent['id'])
        monitor.state.update(key,retry_failures=3,attempts=10)
        summary = monitor.counters('zh_industry')
        monitor._reconcile('zh_industry',DATES[1],summary)
        item = monitor.state.rows('items')[0]
        self.assertEqual((item['status'],item['next_retry'],item['last_run']),('retry',DATES[1],parent['id']))
        self.assertEqual((item['retry_failures'],item['attempts']),(3,10))
        self.assertEqual(len(summary['execution_recoveries']),1)
        self.assertEqual(summary['execution_recoveries'][0]['repairs'][0]['name'],'localization_capacity')
        self.assertEqual(self.store.get('runs',parent['id']),parent)
        # A durable receipt prevents rearming that same parent/repair again.
        monitor.state.update(key,status='blocked_execution',next_retry=None)
        again = monitor.counters('zh_industry')
        monitor._reconcile('zh_industry',DATES[1],again)
        self.assertEqual(again['execution_recoveries'],[])
        self.assertEqual(monitor.state.rows('items')[0]['status'],'blocked_execution')
        applied = {**copy.deepcopy(parent),'id':'new-already-applied','recorded_at':DATES[1],
                   'stage_configuration':{'provider':'same-provider','execution_repairs':follow_up_repairs(parent)}}
        self.store.append('runs',applied)
        monitor.state.update(key,last_run=applied['id'])
        monitor._reconcile('zh_industry',DATES[2],monitor.counters('zh_industry'))
        self.assertEqual(monitor.state.rows('items')[0]['status'],'blocked_execution')
        self.assertFalse(self.adapter.calls)

    def test_capacity_availability_cannot_reopen_semantic_hold_or_skip(self):
        monitor = self.monitor()
        for aid,status in (('zh_macro','machine_hold'),('zh_industry','ignore')):
            result = {'draft_status':'needs_review' if status=='machine_hold' else 'not_suitable',
                'machine_fidelity':{'qa_status':'failed_or_uncertain'},
                'execution_failure':{'stage':'localization','code':'response_incomplete'},
                'attempt':{'model_responses':[{'stage':'localization','finish_reason':'length'}]}}
            run={'id':'semantic-'+aid,'pipeline':'account_source','account_id':aid,'inbox_candidate_id':'inbox-'+aid,
                 'recorded_at':DATES[0],'status':status,'source_adaptation':result,
                 'candidates':[{'id':'existing-held-body','text':'Held original draft'}] if status=='machine_hold' else []}
            self.store.append('runs',run)
            monitor.state.enqueue(aid,SOURCE_IDS[aid],source(aid,'semantic'),DATES[0],status='blocked_execution',
                                  candidate_id=run['inbox_candidate_id'],last_run=run['id'])
            report=monitor.counters(aid)
            monitor._reconcile(aid,DATES[1],report)
            item=next(i for i in monitor.state.rows('items') if i['account']==aid)
            self.assertEqual(item['status'],'drafted' if status=='machine_hold' else 'skipped')
            self.assertFalse(report['execution_recoveries'])
        self.assertFalse(self.adapter.calls)

    def test_unused_json_execution_repair_is_immediate_once_then_backoff_and_bound(self):
        from live.content_stages import follow_up_repairs
        from live.account_intelligence import time
        monitor = self.monitor()
        key,_ = monitor.state.enqueue('zh_macro','overshoot',source('zh_macro','format-repair'),DATES[0])
        failed = {'id':'format-first','status':'execution_failed','candidates':[],
            'stage_configuration':{'execution_repairs':[]},
            'source_adaptation':{'draft_status':'blocked',
                'execution_failure':{'stage':'translation','code':'invalid_json'},
                'attempt':{'model_responses':[{'stage':'translation','finish_reason':'stop'}]}}}
        def record(run):
            monitor._record_run(monitor.state.rows('items')[0],run,set(),DATES[0],monitor.counters('zh_macro'))
            return monitor.state.rows('items')[0]
        first = record(failed)
        self.assertEqual((first['status'],first['next_retry']),('retry',DATES[0]))
        applied = copy.deepcopy(failed)
        applied.update(id='format-already-applied',stage_configuration={'execution_repairs':follow_up_repairs(failed)})
        second = record(applied)
        self.assertEqual(second['status'],'retry')
        self.assertEqual((time(second['next_retry'])-time(DATES[0])).total_seconds(),self.config['retry_seconds'])
        third = record({**applied,'id':'format-exhausted'})
        self.assertEqual(third['status'],'blocked_execution')
        self.assertIsNone(third['next_retry'])
        funding = copy.deepcopy(failed)
        funding['id']='funding-wait'
        funding['source_adaptation']['execution_failure']['code']='budget_exhausted'
        external = record(funding)
        self.assertGreaterEqual((time(external['next_retry'])-time(DATES[0])).total_seconds(),3600)

    def test_historical_qa_only_ancestry_does_not_consume_new_post_quota(self):
        parent = {'id':'parent', 'account_id':'zh_industry', 'inbox_candidate_id':'original-inbox',
            'recorded_at':DATES[0], 'status':'machine_hold', 'candidates':[{'text':'Original completed draft'}],
            'source_adaptation':{'draft_status':'blocked','final_draft':'Original completed draft',
                'attempt':{'stage':'qa','why':'qa: ContractError',
                    'model_responses':[{'stage':'qa','finish_reason':'length'}]}}}
        child = {'id':'child','account_id':'zh_industry','inbox_candidate_id':'original-inbox',
            'follow_up_of':'parent','recorded_at':DATES[1],'status':'machine_hold',
            'candidates':[{'text':'Original completed draft'}]}
        grandchild = {**child,'id':'grandchild','follow_up_of':'child'}
        fresh = {**child,'id':'fresh','inbox_candidate_id':'new-inbox','follow_up_of':None,
                 'candidates':[{'text':'Actually new content'}]}
        rows = [parent,child,grandchild,fresh]
        frozen = copy.deepcopy(rows)
        self.assertEqual(daily_draft_count(rows,'zh_industry',DATES[1]),1)
        self.assertEqual(rows,frozen)
        # Same lineage with changed prose is a new content version, not QA-only.
        self.assertEqual(daily_draft_count([parent,{**child,'candidates':[{'text':'Different new draft'}]}],
                                          'zh_industry',DATES[1]),1)
        # Missing parents or identity changes cannot borrow another draft's exemption.
        self.assertEqual(daily_draft_count([child],'zh_industry',DATES[1]),1)
        self.assertEqual(daily_draft_count([parent,{**child,'inbox_candidate_id':'other-inbox'}],
                                          'zh_industry',DATES[1]),1)
        # Old ingestion created a second inbox for one saved source. An explicit
        # QA parent plus exact source provenance/body can still identify it.
        provenance = {'original_text':'Immutable original source', 'source_hash':digest('Immutable original source'),
                      'url':'https://newsletter.semianalysis.com/p/qa-fixture','author_name':'Fixture author'}
        parent['source_adaptation']['source'] = provenance
        legacy = {**child,'inbox_candidate_id':'legacy-duplicate-inbox','source_adaptation':{'source':provenance}}
        self.assertEqual(daily_draft_count([parent,legacy],'zh_industry',DATES[1]),0)
        foreign = copy.deepcopy(legacy)
        foreign['source_adaptation']['source']['url'] = 'https://newsletter.semianalysis.com/p/other'
        self.assertEqual(daily_draft_count([parent,foreign],'zh_industry',DATES[1]),1)

    def test_material_revision_recovers_undrafted_execution_failure_with_same_ancestry(self):
        for status in ('retry', 'blocked_execution'):
            with self.subTest(status=status):
                row = source('zh_macro','execution-revision-' + status,
                    recovery={'at':DATES[0], 'actions':[{'kind':'full_body','document_ref':'old-capture'}]})
                self.adapter.outcomes[row['url']] = ['provider_timeout']
                candidate = ingest(self.store,'zh_macro',row)['candidate']
                parent = SourcePipeline(self.store,adapter=self.adapter).run('zh_macro',candidate['id'])
                monitor = self.monitor()
                key,_ = monitor.state.enqueue('zh_macro','overshoot',row,DATES[0],status=status,
                    candidate_id=candidate['id'],last_run=parent['id'])
                observed = {**row,'fetched_at':DATES[1],'recovery':{'at':DATES[1],
                    'actions':[{'kind':'full_body','document_ref':'new-capture'}]}}
                self.assertEqual(monitor.state.enqueue('zh_macro','overshoot',observed,DATES[1]),(key,True))
                revised = {**observed,'original_text':row['original_text'] + '\n\nThe next original paragraph.'}
                self.assertEqual(monitor.state.enqueue('zh_macro','overshoot',revised,DATES[1]),(key,False))
                item = next(i for i in monitor.state.rows('items') if i['id']==key)
                self.assertEqual((item['status'],item['candidate_id'],item['last_run']),('pending',None,parent['id']))
                summary = monitor.counters('zh_macro')
                monitor._generate('zh_macro',next(w for w in self.worlds if w['account_id']=='zh_macro'),
                    DATES[1],summary,'revision-test','replay')
                child = self.store.rows('runs')[-1]
                self.assertEqual(child['source_revision_of'],parent['id'])
                self.assertEqual(self.store.get('runs',parent['id']),parent)

    def test_execution_revision_never_changes_identity_or_reopens_draft_none_skip(self):
        row = source('zh_macro','revision-guards',thread_id='same-thread')
        candidate = ingest(self.store,'zh_macro',row)['candidate']
        self.adapter.outcomes[row['url']] = ['provider_timeout']
        parent = SourcePipeline(self.store,adapter=self.adapter).run('zh_macro',candidate['id'])
        monitor = self.monitor()
        key,_ = monitor.state.enqueue('zh_macro','overshoot',row,DATES[0],status='blocked_execution',
            candidate_id=candidate['id'],last_run=parent['id'])
        revised = {**row,'original_text':row['original_text'] + '\n\nAdditional original reasoning.'}
        for changed in ({'author_name':'another author'}, {'url':'https://theovershoot.co/p/other'}, {'source_id':'another-source'}):
            # Keep the original alias so identity rejection, rather than a new
            # isolated source, is what this test exercises.
            altered = {**revised,**changed,'thread_id':'same-thread'}
            self.assertEqual(monitor.state.enqueue('zh_macro','overshoot',altered,DATES[1]),(key,True))
            self.assertEqual(next(i for i in monitor.state.rows('items') if i['id']==key)['status'],'blocked_execution')
        for status in ('drafted','skipped','historical_processed'):
            monitor.state.update(key,status=status)
            self.assertEqual(monitor.state.enqueue('zh_macro','overshoot',revised,DATES[1]),(key,True))
        for decision in ('NONE','SKIP'):
            stopped = copy.deepcopy(parent)
            stopped.update(id='stopped-' + decision, status='ignore')
            stopped['source_adaptation'].update(draft_status='not_suitable',status='skipped',
                execution_failure=None,route={'decision':decision})
            self.store.append('runs',stopped)
            monitor.state.update(key,status='blocked_execution',last_run=stopped['id'])
            self.assertEqual(monitor.state.enqueue('zh_macro','overshoot',revised,DATES[1]),(key,True))
        # QA execution failure has a candidate body even though queue status retry.
        held = copy.deepcopy(parent)
        held.update(id='qa-body-guard',candidates=[{'id':'existing-body','text':'Existing draft'}])
        held['source_adaptation'].update(final_draft='Existing draft',execution_failure={'stage':'qa','code':'provider_timeout'})
        self.store.append('runs',held)
        monitor.state.update(key,status='retry',last_run=held['id'])
        self.assertEqual(monitor.state.enqueue('zh_macro','overshoot',revised,DATES[1]),(key,True))

    def test_corrected_source_language_reopens_hold_but_observation_time_does_not(self):
        monitor = self.monitor()
        row = source('zh_macro','language-only',source_language='unknown')
        key,_ = monitor.state.enqueue('zh_macro','overshoot',row,DATES[0],status='blocked_source',last_run='original-held-run')
        _,duplicate = monitor.state.enqueue('zh_macro','overshoot',{**row,'fetched_at':DATES[1]},DATES[1])
        self.assertTrue(duplicate)
        _,duplicate = monitor.state.enqueue('zh_macro','overshoot',{**row,'source_language':'en'},DATES[1])
        self.assertFalse(duplicate)
        item = monitor.state.rows('items')[0]
        self.assertEqual((item['id'],item['status'],item['last_run']), (key,'pending','original-held-run'))

    def test_saved_followup_reconciles_provider_block_without_regeneration_or_hold_override(self):
        row = source('zh_macro', 'reconcile')
        candidate = ingest(self.store, 'zh_macro', row)['candidate']
        self.adapter.outcomes[row['url']] = ['content_filter']
        pipeline = SourcePipeline(self.store, adapter=self.adapter)
        parent = pipeline.run('zh_macro', candidate['id'])
        monitor = self.monitor()
        monitor.seed_consumed()
        item = monitor.state.rows('items')[0]
        self.assertEqual(item['status'], 'blocked_execution')
        def held(*args, **kwargs):
            result = self.adapter(*args, **kwargs)
            result.update(draft_status='blocked', status='held',
                execution_failure={'stage': 'localization', 'code': 'invalid_response'},
                machine_fidelity={'status': 'not_passed', 'qa_status': 'failed', 'qa': {'findings': [{'code': 'numeric'}]}})
            return result
        child = SourcePipeline(self.store, adapter=held).run('zh_macro', candidate['id'], parent['id'])
        self.assertEqual(child['status'], 'machine_hold')
        saved = copy.deepcopy(child)
        count = len(self.adapter.calls)
        report = self.accounts(monitor.run_cycle(as_of=DATES[0], mode='replay'))['zh_macro']
        updated = monitor.state.rows('items')[0]
        self.assertEqual((updated['status'], updated['last_run']), ('drafted', child['id']))
        self.assertEqual(report['generated'], 0)
        self.assertEqual(report['reused_dashboard_ids'], [child['candidates'][0]['id']])
        self.assertEqual(report['reconciled_runs'], [child['id']])
        self.assertEqual(len(self.adapter.calls), count)
        self.assertEqual(self.store.get('runs', child['id']), saved)
        monitor.run_cycle(as_of=DATES[1], mode='replay')
        self.assertEqual(len(self.adapter.calls), count)

    def test_explicit_provider_change_recovers_original_failure_once(self):
        row = source('zh_macro', 'provider')
        candidate = ingest(self.store, 'zh_macro', row)['candidate']
        provider = ['old_provider']
        def refused(*args, **kwargs):
            return {'status':'held', 'draft_status':'blocked', 'final_draft':'',
                'execution_failure':{'stage':'localization', 'code':'content_filter'},
                'stage_configuration': {'provider':provider[0], 'execution_repairs':[]}}
        pipeline = SourcePipeline(self.store, adapter=refused)
        parent = pipeline.run('zh_macro', candidate['id'])
        monitor = Monitor(self.store, poller=Poller(), pipeline=pipeline, config=self.config)
        monitor.seed_consumed()
        with patch.object(SourcePipeline, 'generation_configuration', new_callable=PropertyMock) as config:
            config.return_value = {'provider':'old_provider'}
            monitor.run_cycle(as_of=DATES[0], mode='replay')
            self.assertEqual(len(self.store.rows('runs')), 1)
            provider[0] = 'new_provider'
            config.return_value = {'provider':'new_provider'}
            report = self.accounts(monitor.run_cycle(as_of=DATES[1], mode='replay'))['zh_macro']
            self.assertEqual(len(report['provider_recoveries']), 1)
            child = self.store.rows('runs')[-1]
            self.assertEqual(child['follow_up_of'], parent['id'])
            monitor.run_cycle(as_of=DATES[2], mode='replay')
            self.assertEqual(len(self.store.rows('runs')), 2)
            self.assertEqual(monitor.state.rows('items')[0]['status'], 'blocked_execution')

    def test_qa_execution_failure_resumes_original_body_despite_quota_and_age(self):
        row = source('zh_macro', 'qa-retry')
        candidate = ingest(self.store, 'zh_macro', row)['candidate']
        calls = []
        def adapter(*args, **kwargs):
            calls.append(kwargs)
            result = self.adapter(*args, **kwargs)
            result['attempt'] = {'account_context':kwargs['account_context']}
            if len(calls) == 1:
                result.update(status='held', draft_status='blocked',
                    execution_failure={'stage':'qa','code':'response_incomplete'})
            return result
        pipeline = SourcePipeline(self.store, adapter=adapter)
        parent = pipeline.run('zh_macro', candidate['id'])
        self.assertEqual(parent['status'], 'execution_failed')
        config = {**self.config, 'max_drafts_per_account_day':0, 'max_source_age_hours':1}
        monitor = Monitor(self.store, poller=Poller(), pipeline=pipeline, config=config)
        from live import source_hygiene
        annotate = source_hygiene.annotate
        with patch('live.source_hygiene.annotate', side_effect=lambda source: {
                **annotate(source), 'version':'TEST_UPDATED_ANNOTATION_VERSION'}):
            report = self.accounts(monitor.run_cycle(as_of=DATES[1], mode='replay'))['zh_macro']
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['checkpoint']['id'], parent['id'])
        self.assertEqual(calls[1]['account_context'], calls[0]['account_context'])
        child = self.store.rows('runs')[-1]
        self.assertEqual(child['inbox_candidate_id'], parent['inbox_candidate_id'])
        self.assertEqual(len(self.store.rows('inbox')), 1)
        self.assertEqual(child['candidates'][0]['text'], parent['candidates'][0]['text'])
        self.assertEqual(report['generated'], 0)
        self.assertEqual(report['reused_dashboard_ids'], [child['candidates'][0]['id']])

    def test_full_source_revision_retains_ancestor_without_reusing_old_prefix(self):
        preview = source('zh_macro', 'body-revision', content_complete=False)
        full = {**preview, 'content_complete':True, 'original_text':preview['original_text'] + ' Additional complete original context.'}
        first = self.monitor(Poller({('zh_macro','overshoot',DATES[0]):[preview]}))
        first.run_cycle(as_of=DATES[0], mode='replay')
        parent = self.store.rows('runs')[-1]
        original = copy.deepcopy(parent)
        second = self.monitor(Poller({('zh_macro','overshoot',DATES[1]):[full]}))
        second.run_cycle(as_of=DATES[1], mode='replay')
        child = self.store.rows('runs')[-1]
        self.assertEqual(child['source_revision_of'], parent['id'])
        self.assertIsNone(child['follow_up_of'])
        self.assertNotEqual(child['inbox_candidate_id'], parent['inbox_candidate_id'])
        self.assertNotIn('checkpoint', self.adapter.calls[-1][2])
        self.assertEqual(self.store.get('runs', parent['id']), original)
        self.assertEqual(second.state.rows('items')[0]['status'], 'drafted')

    def test_source_revision_keeps_ancestor_after_crash_before_generation(self):
        preview = source('zh_macro', 'revision-crash', content_complete=False)
        full = {**preview,'content_complete':True,'original_text':preview['original_text'] + ' Complete body recovered.'}
        self.monitor(Poller({('zh_macro','overshoot',DATES[0]):[preview]})).run_cycle(as_of=DATES[0],mode='replay')
        parent = copy.deepcopy(self.store.rows('runs')[-1])
        monitor = self.monitor(Poller({('zh_macro','overshoot',DATES[1]):[full]}))
        with patch.object(monitor.pipeline,'run',side_effect=KeyboardInterrupt('TEST: before pipeline')), self.assertRaises(KeyboardInterrupt):
            monitor.run_cycle(as_of=DATES[1],mode='replay')
        item = monitor.state.rows('items')[0]
        self.assertEqual(item['status'],'executing')
        self.assertIsNotNone(item['candidate_id'])
        self.monitor().run_cycle(as_of=DATES[1],mode='replay')
        child = self.store.rows('runs')[-1]
        self.assertEqual(child['source_revision_of'],parent['id'])
        self.assertNotIn('execution_checkpoint',child)
        self.assertEqual(self.store.get('runs',parent['id']),parent)

    def test_foreign_feed_row_quarantines_without_poisoning_valid_rows(self):
        valid=source('zh_industry',888)
        foreign={**valid,'url':'https://other-publisher.example/article','original_text':'foreign article'}
        poller=Poller({('zh_industry','semianalysis',DATES[0]):[foreign,valid]})
        monitor=Monitor(self.store,poller=poller,pipeline=SourcePipeline(self.store,adapter=self.adapter),config=self.config)
        result=monitor.run_cycle(as_of=DATES[0],mode='replay')
        industry=result['accounts'][2]
        self.assertEqual(industry['generated'],1)
        self.assertEqual(industry['new_sources'],1)
        self.assertEqual(industry['failures'][0]['code'],'source_identity_rejected')
        self.assertEqual(len(monitor.state.rows('items')),1)
        checkpoint=next(r for r in monitor.state.rows('sources') if r['account']=='zh_industry')
        self.assertEqual(checkpoint['status'],'checked')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'store')
        self.config = {**configuration(), 'allow_paid_x': False}
        self.worlds = copy.deepcopy(universes())
        for world in self.worlds:
            world['subscriptions'] = [s for s in world['subscriptions']
                                      if s['source_id'] == SOURCE_IDS[world['account_id']]]
        for name in ('live.account_monitor.universes', 'live.account_sources.universes'):
            patched = patch(name, return_value=self.worlds)
            patched.start()
            self.addCleanup(patched.stop)
        self.adapter = Adapter()

    def monitor(self, poller=None):
        # A new Store, Monitor and SQLite connection simulate a process restart.
        store = Store(self.store.root)
        return Monitor(store, poller=poller or Poller(),
                       pipeline=SourcePipeline(store, adapter=self.adapter), config=self.config)

    @staticmethod
    def accounts(report):
        return {r['account_id']: r for r in report['accounts']}

    def test_three_cycles_persist_cursors_queues_failures_and_account_isolation(self):
        rows = {aid: [source(aid, 100), source(aid, 200, DATES[1])] for aid in ACCOUNTS}
        rows['en_morris_archive'][0]['published_at'] = '2020-01-01T00:00:00+00:00'
        pages = {(aid, SOURCE_IDS[aid], day): rows[aid][:1 if day == DATES[0] else 2]
                 for aid in ACCOUNTS for day in DATES}
        self.adapter.outcomes[rows['zh_macro'][0]['url']] = ['provider_error', 'draft']
        spent = budget.spent()
        reports, pollers = [], []
        for day in DATES:
            poller = Poller(pages)
            reports.append(self.monitor(poller).run_cycle(as_of=day, mode='replay'))
            pollers.append(poller)
        first, second, third = map(self.accounts, reports)
        self.assertEqual([first[a]['generated'] for a in ACCOUNTS], [1, 0, 1])
        self.assertEqual(first['zh_macro']['failures'][0]['code'], 'provider_error')
        self.assertEqual([second[a]['generated'] for a in ACCOUNTS], [1, 2, 1])
        self.assertTrue(all(third[a]['no_post'] for a in ACCOUNTS))
        self.assertTrue(all(third[a]['generated'] == 0 for a in ACCOUNTS))
        self.assertEqual(len({c['id'] for r in self.store.rows('runs') for c in r['candidates']}), 6)
        self.assertTrue(all(call[2]['checked_at'] == DATES[0] for call in pollers[1].calls))
        self.assertTrue(all(row['source_id'] == SOURCE_IDS[aid] for aid, row, _ in self.adapter.calls))
        self.assertEqual(budget.spent(), spent)
        with patch.object(api, 'STORE', self.store):
            client = TestClient(app)
            for aid in ACCOUNTS:
                payload = client.get('/api/account-intelligence/accounts/' + aid + '/inbox').json()
                self.assertEqual(sum(r['draft_count'] for c in payload['candidates'] for r in c['runs']), 2)
        source_states = State(self.store.root).rows('sources')
        self.assertEqual(len(source_states), 3)
        self.assertEqual({row['last_checked'] for row in source_states}, {DATES[2]})

    def test_crash_after_store_commit_recovers_without_call_even_when_daily_quota_full(self):
        row = source('en_morris_archive', 101)
        pages = {('en_morris_archive', SOURCE_IDS['en_morris_archive'], DATES[0]): [row]}
        self.config['max_drafts_per_account_day'] = 1
        monitor = self.monitor(Poller(pages))
        update = monitor.state.update
        def crash(item_id, **values):
            if values.get('status') == 'drafted':
                raise KeyboardInterrupt('TEST crash after immutable Store write')
            return update(item_id, **values)
        with patch.object(monitor.state, 'update', side_effect=crash), self.assertRaises(KeyboardInterrupt):
            monitor.run_cycle(as_of=DATES[0], mode='replay')
        self.assertEqual(len(self.store.rows('runs')), 1)
        report = self.monitor(Poller(pages)).run_cycle(as_of=DATES[0], mode='replay')
        morris = self.accounts(report)['en_morris_archive']
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(morris['generated'], 0)
        self.assertEqual(morris['selected'], 0)
        self.assertEqual(morris['dashboard_ids'], [])
        self.assertEqual(len(morris['reused_dashboard_ids']), 1)
        self.assertEqual(State(self.store.root).rows('items')[0]['status'], 'drafted')
        self.assertIn('interrupted', {r['status'] for r in State(self.store.root).rows('cycles')})

    def test_failed_source_does_not_lose_other_sources_or_accounts(self):
        extra = copy.deepcopy(self.worlds[1]['subscriptions'][0])
        extra.update(id='libertystreet', source_id='libertystreet')
        self.worlds[1]['subscriptions'].append(extra)
        good = source('zh_macro', 112, source_id='libertystreet',
                      url='https://libertystreeteconomics.newyorkfed.org/test-112')
        pages = {('zh_macro', 'overshoot', DATES[0]): IntakeFailure('TEST_fetch_outage'),
                 ('zh_macro', 'libertystreet', DATES[0]): [good],
                 ('zh_industry', 'semianalysis', DATES[0]): [source('zh_industry', 113)]}
        report = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=DATES[0], mode='replay'))
        self.assertEqual(report['zh_macro']['generated'], 1)
        self.assertEqual(report['zh_macro']['sources_checked'], 2)
        self.assertEqual(report['zh_industry']['generated'], 1)
        self.assertEqual(report['zh_macro']['failures'][0]['code'], 'TEST_fetch_outage')
        self.assertEqual(len(State(self.store.root).rows('sources')), 4)

    def test_skip_stale_and_consumed_archive_never_force_output(self):
        morris = source('en_morris_archive', 120, '2020-01-01T00:00:00+00:00')
        self.adapter.outcomes[morris['url']] = ['skip']
        pages = {('en_morris_archive', 'x_Morris_LT', DATES[0]): [morris],
                 ('en_morris_archive', 'x_Morris_LT', DATES[1]): [morris],
                 ('zh_macro', 'overshoot', DATES[0]): [source('zh_macro', 121, '2020-01-01T00:00:00+00:00')]}
        first = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=DATES[0], mode='replay'))
        second = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=DATES[1], mode='replay'))
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(first['en_morris_archive']['no_post_reason'], 'no_worthwhile_content')
        self.assertEqual(first['zh_macro']['stale_skipped'], 1)
        self.assertTrue(second['en_morris_archive']['no_post'])
        self.assertEqual(sum(len(r['candidates']) for r in self.store.rows('runs')), 0)

    def test_pending_identity_bridge_consumes_extra_entry_and_prefers_existing_draft(self):
        state = State(self.store.root)
        a, _ = state.enqueue('zh_macro', 'overshoot', source('zh_macro', 130, thread_id='thread-x'), DATES[0])
        b, _ = state.enqueue('zh_macro', 'overshoot', source('zh_macro', 131, event_id='event-y'), DATES[0])
        state.update(b, status='drafted', last_run='existing')
        selected, duplicate = state.enqueue('zh_macro', 'overshoot', source('zh_macro', 132,
                                           thread_id='thread-x', event_id='event-y'), DATES[1])
        self.assertTrue(duplicate)
        self.assertEqual(selected, b)
        self.assertEqual({r['id']: r['status'] for r in state.rows('items')}, {a: 'duplicate', b: 'drafted'})
        self.assertEqual(state.enqueue('zh_macro', 'overshoot', source('zh_macro', 130), DATES[2]), (b, True))

    def test_budget_block_remains_retryable_after_max_attempts_and_later_recovers(self):
        row = source('en_morris_archive', 140)
        self.adapter.outcomes[row['url']] = ['budget_exhausted'] * 3 + ['draft']
        days = (*DATES, '2026-09-30T12:00:00+00:00')
        pages = {('en_morris_archive', 'x_Morris_LT', day): [row] for day in days}
        spent = budget.spent()
        for day in days[:3]:
            report = self.monitor(Poller(pages)).run_cycle(as_of=day, mode='replay')
            self.assertEqual(State(self.store.root).rows('items')[0]['status'], 'retry')
            self.assertFalse(self.accounts(report)['en_morris_archive']['no_post'])
        final = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=days[3], mode='replay'))
        self.assertEqual(final['en_morris_archive']['generated'], 1)
        self.assertEqual(budget.spent(), spent)
        runs = self.store.rows('runs')
        self.assertEqual(len(runs), 4)
        self.assertEqual(runs[-1]['follow_up_of'], runs[-2]['id'])

    def test_first_deployment_seeds_failed_run_as_retry_not_consumed(self):
        row = source('en_morris_archive', 150)
        self.adapter.outcomes[row['url']] = ['provider_error', 'draft']
        candidate = ingest(self.store, 'en_morris_archive', row)['candidate']
        run = SourcePipeline(self.store, adapter=self.adapter).run('en_morris_archive', candidate['id'])
        self.assertEqual(run['status'], 'execution_failed')
        report = self.accounts(self.monitor().run_cycle(as_of=DATES[1], mode='replay'))
        self.assertEqual(report['en_morris_archive']['generated'], 1)
        self.assertEqual(self.store.rows('runs')[-1]['follow_up_of'], run['id'])

    def test_funding_wait_does_not_exhaust_later_json_retry_allowance(self):
        row = source('en_morris_archive', 151)
        self.adapter.outcomes[row['url']] = ['budget_exhausted'] * 3 + ['invalid_json', 'draft']
        days = (*DATES, '2026-09-30T12:00:00+00:00', '2026-10-01T12:00:00+00:00')
        pages = {('en_morris_archive', 'x_Morris_LT', day): [row] for day in days}
        for day in days[:4]:
            self.monitor(Poller(pages)).run_cycle(as_of=day, mode='replay')
        item = State(self.store.root).rows('items')[0]
        self.assertEqual(item['status'], 'retry')
        self.assertEqual(item['attempts'], 4)
        self.assertEqual(item['retry_failures'], 1)
        result = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=days[4], mode='replay'))
        self.assertEqual(result['en_morris_archive']['generated'], 1)
        item = State(self.store.root).rows('items')[0]
        self.assertEqual(item['attempts'], 5)
        self.assertEqual(item['retry_failures'], 0)
        runs = self.store.rows('runs')
        self.assertTrue(all(runs[i]['follow_up_of'] == runs[i-1]['id'] for i in range(1,5)))

    def test_actual_repeated_execution_failures_still_stop_at_retry_limit(self):
        row = source('en_morris_archive', 152)
        self.adapter.outcomes[row['url']] = ['invalid_json'] * 3
        pages = {('en_morris_archive', 'x_Morris_LT', day): [row] for day in DATES}
        for day in DATES:
            self.monitor(Poller(pages)).run_cycle(as_of=day, mode='replay')
        item = State(self.store.root).rows('items')[0]
        self.assertEqual(item['status'], 'blocked_execution')
        self.assertEqual(item['retry_failures'], 3)
        self.assertIsNone(item['next_retry'])

    def test_unused_supported_repair_gets_one_chance_after_other_stage_failures(self):
        monitor = self.monitor()
        key, _ = monitor.state.enqueue('en_morris_archive', 'x_Morris_LT',
                                        source('en_morris_archive', 153), DATES[0])
        monitor.state.update(key, attempts=8, retry_failures=2, status='retry')
        run = {'id':'qa-length-parent', 'status':'execution_failed', 'candidates':[],
               'stage_configuration':{'execution_repairs':[]},
               'source_adaptation':{'draft_status':'blocked',
                   'execution_failure':{'code':'response_incomplete','stage':'qa'},
                   'attempt':{'model_responses':[{'stage':'qa','finish_reason':'length'}]}}}
        item = monitor.state.rows('items')[0]
        monitor._record_run(item, run, set(), DATES[1], monitor.counters('en_morris_archive'))
        item = monitor.state.rows('items')[0]
        self.assertEqual(item['status'], 'retry')
        self.assertEqual(item['retry_failures'], 3)
        self.assertEqual(item['attempts'], 9)
        run['id'] = 'qa-length-after-repair'
        run['stage_configuration']['execution_repairs'] = [{'name':'qa_capacity'}]
        monitor._record_run(item, run, set(), DATES[2], monitor.counters('en_morris_archive'))
        self.assertEqual(monitor.state.rows('items')[0]['status'], 'blocked_execution')

    def test_uncertain_media_is_annotated_before_generation(self):
        row = source('zh_industry', 160, original_text='GPU results depend on memory. See the chart below.',
                     media=[{'url': 'https://example.test/chart.png'}])
        pages = {('zh_industry', 'semianalysis', DATES[0]): [row]}
        self.monitor(Poller(pages)).run_cycle(as_of=DATES[0], mode='replay')
        self.assertEqual(self.adapter.calls[0][1]['media_dependencies'][0]['status'], 'uncertain_dependency')

    def test_status_read_does_not_initialize_or_mutate_database(self):
        self.monitor().run_cycle(as_of=DATES[0], mode='replay')
        path = self.store.root / 'monitor.sqlite3'
        before = path.read_bytes()
        with patch('live.account_monitor.State', side_effect=AssertionError('Read must not initialize State')):
            result = monitor_status(self.store.root)
        self.assertEqual(result['last_cycle']['status'], 'completed')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['budget']['cap_usd'], budget.cap())

    def test_source_hold_only_reopens_after_material_context_change(self):
        state = State(self.store.root)
        row = source('zh_industry', 170)
        key, _ = state.enqueue('zh_industry', 'semianalysis', row, DATES[0], status='blocked_source')
        self.assertEqual(state.enqueue('zh_industry', 'semianalysis',
            {**row, 'fetched_at': DATES[1], 'raw_import_ref': 'different-capture'}, DATES[1]), (key, True))
        self.assertEqual(state.rows('items')[0]['status'], 'blocked_source')
        resolved = {**row, 'context_items': [{'kind': 'verified_chart_context', 'text': 'TEST: supplied actual values'}]}
        self.assertEqual(state.enqueue('zh_industry', 'semianalysis', resolved, DATES[2]), (key, False))
        self.assertEqual(state.rows('items')[0]['status'], 'pending')

    def test_json_failure_retries_are_bounded_and_block_is_not_reported_as_no_post(self):
        row = source('en_morris_archive', 180)
        self.adapter.outcomes[row['url']] = ['invalid_response'] * 3
        pages = {('en_morris_archive', 'x_Morris_LT', day): [row] for day in DATES}
        for day in DATES:
            self.monitor(Poller(pages)).run_cycle(as_of=day, mode='replay')
        self.assertEqual(State(self.store.root).rows('items')[0]['status'], 'blocked_execution')
        report = self.accounts(self.monitor().run_cycle(as_of='2026-09-30T12:00:00+00:00', mode='replay'))
        self.assertEqual(len(self.adapter.calls), 3)
        self.assertEqual(report['en_morris_archive']['open_blocks'], 1)
        self.assertFalse(report['en_morris_archive']['no_post'])

    def test_bounded_backlog_is_not_a_fetch_failure_and_bad_row_is_quarantined(self):
        aid, sid = 'zh_macro', 'overshoot'
        good = source(aid, 190)
        pages = {(aid, sid, DATES[0]): FetchResult([good], {'checked_at': DATES[0]}, False,
                                                {'backlog': 1, 'retrieval_saturated': False}),
                 (aid, sid, DATES[1]): [source('zh_industry', 191)]}
        first = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=DATES[0], mode='replay'))
        self.assertEqual(first[aid]['source_checks'][0]['status'], 'catchup_pending')
        self.assertEqual(first[aid]['failures'], [])
        second = self.accounts(self.monitor(Poller(pages)).run_cycle(as_of=DATES[1], mode='replay'))
        self.assertEqual(second[aid]['failures'][0]['code'], 'source_identity_rejected')
        saved = next(r for r in State(self.store.root).rows('sources') if r['account'] == aid)
        self.assertEqual(json.loads(saved['cursor'])['checked_at'], DATES[1])
        self.assertEqual(len(self.adapter.calls), 1)

    def test_existing_dashboard_draft_for_other_candidate_is_not_new_generation(self):
        aid='en_morris_archive'
        row=source(aid,811)
        monitor=self.monitor()
        monitor.state.meta('seeded',{'at':DATES[0]})
        candidate=ingest(self.store,aid,row)['candidate']
        old=SourcePipeline(self.store,adapter=self.adapter).run(aid,candidate['id'])
        revised={**row,'original_text':row['original_text']+' 保留同一帖子的更新。'}
        monitor=self.monitor(Poller({(aid,'x_Morris_LT',DATES[0]):[revised]}))
        result=self.accounts(monitor.run_cycle(as_of=DATES[0],mode='replay'))[aid]
        self.assertEqual(result['generated'],0)
        self.assertEqual(result['selected'],0)
        self.assertEqual(result['dashboard_ids'],[])
        self.assertEqual(result['reused_dashboard_ids'],[old['candidates'][0]['id']])
        self.assertEqual(len(self.adapter.calls),1)


if __name__ == '__main__':
    unittest.main()
