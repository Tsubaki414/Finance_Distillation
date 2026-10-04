"""Offline contract tests for legacy view enrichment."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live import view_enrich
from live.content_store import ContentStore
from live.distillation import ContractError
from scripts import voice_relay_check as voice


def view(reason='Demand is slowing'):
    return dict(direction='bearish', subject='Demand', conviction='medium',
                reasoning=[reason], horizon='months')


def row(i=0, kind='view', structured=None):
    unit = dict(unit_id=f'u{i}', kind=kind, statement='Demand is slowing.',
                source_spans=[dict(exact_text='Demand is slowing as rates rise.')],
                numbers=[], licence_tier='B', usage='paraphrase')
    if structured is not None:
        unit['view'] = structured
    return dict(unit_id=unit['unit_id'], unit=unit, licence_tier='B',
                source=dict(adapter='research', id=f's{i}', source_hash=f'h{i}'), personas=[])


class FakeClient:
    def __init__(self, reason='Demand is slowing'):
        self.calls = []
        self.reason = reason

    def __call__(self, stage, messages, max_tokens):
        self.calls.append((stage, json.loads(messages[-1]['content'])))
        return dict(text=json.dumps({'views': [dict(unit_id=u['unit_id'], view=view(self.reason))
                    for u in self.calls[-1][1]['units']]}), finish_reason='stop', model='fake')


class EnrichTests(unittest.TestCase):
    def test_valid_only_eligible_and_evidence_only(self):
        rows = [row(), row(1, 'fact'), row(2, structured=view()), row(3, structured={})]
        original = copy.deepcopy(rows)
        client = FakeClient()
        out = view_enrich.enrich_views(rows, client)
        self.assertEqual([e['unit_id'] for e in out['enriched']], ['u0', 'u3'])
        self.assertEqual(out['invalid'], [])
        self.assertEqual(rows, original)
        self.assertEqual(client.calls[0][0], 'view_enrich')
        self.assertEqual(set(client.calls[0][1]['units'][0]), {'unit_id', 'statement', 'source_spans'})
        self.assertEqual(client.calls[0][1]['units'][0]['source_spans'], [{'exact_text': 'Demand is slowing as rates rise.'}])

    def test_ungrounded_reasoning_rejected(self):
        out = view_enrich.enrich_views([row()], FakeClient('Profits will double'))
        self.assertEqual(out['enriched'], [])
        self.assertIn('grounded', out['invalid'][0]['reason'])

    def test_batches_and_call_limit(self):
        client = FakeClient()
        out = view_enrich.enrich_views([row(i) for i in range(17)], client)
        self.assertEqual([len(p['units']) for _, p in client.calls], [8, 8, 1])
        self.assertEqual(len(out['enriched']), 17)
        client = FakeClient()
        out = view_enrich.enrich_views([row(i) for i in range(17)], client, max_calls=1)
        self.assertEqual(len(out['enriched']), 8)
        self.assertEqual(out['deferred'], 9)
        self.assertEqual(view_enrich.enrich_views([row()], FakeClient(), max_calls=0)['calls'], 0)

    def test_response_contract_and_missing_ids(self):
        for response in [dict(text='{}', finish_reason='stop'),
                         dict(text='{}', finish_reason='length'),
                         dict(text='{}', finish_reason='stop', refusal='no')]:
            out = view_enrich.enrich_views([row()], lambda *args: response)
            self.assertEqual(out['enriched'], [])
            self.assertEqual(len(out['invalid']), 1)

    def test_sidecar_persistence_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'units.jsonl'
            path.write_text(json.dumps(row()) + '\n')
            original = path.read_bytes()
            store = ContentStore(directory)
            entries = view_enrich.enrich_views(store.units(), FakeClient())['enriched']
            self.assertEqual(store.set_view_enrichments(entries), 1)
            self.assertEqual(path.read_bytes(), original)
            loaded = ContentStore(directory).units()[0]['unit']
            self.assertEqual(loaded['view'], view())
            self.assertEqual(loaded['view_source'], 'enriched')
            self.assertEqual(store.set_view_enrichments(entries), 0)
            bad = dict(entries[0], view=view('Made up'))
            with self.assertRaises(ContractError):
                ContentStore(directory).set_view_enrichments([bad])
            with (Path(directory) / 'suppressed.jsonl').open('w') as fh:
                fh.write(json.dumps({'unit_id': 'u0'}) + '\n')
            self.assertEqual(ContentStore(directory).units(), [])

    def test_voice_group_ranking_stable_and_grounded(self):
        groups = [[row(0, 'fact')], [row(1, structured=view())],
                  [row(2, structured=view('Invented')), row(3, 'fact')],
                  [row(4, structured=view()), row(5, 'fact')],
                  [row(6, structured=view()), row(7, 'fact')]]
        self.assertEqual(voice.rank_evidence_groups(groups), [groups[3], groups[4], *groups[:3]])

    def test_voice_report_fields(self):
        from types import SimpleNamespace
        persona = SimpleNamespace(raw={'donor_cluster': 'test'}, account_id='a', lang='en', voice_card={})
        records = [row(0, 'fact'), row(1, structured=view()), row(2, 'fact')]
        records[2]['source'] = records[1]['source']
        result = dict(text='Draft', post_type='judgment_take', stance={'decision': 'adapt'})
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(voice.registry, 'load_personas', return_value={'a': persona}), \
             patch.object(voice, 'units_for_persona', return_value=records), \
             patch.object(voice, 'evidence_source', return_value=({}, [])), \
             patch.object(voice.compose, 'compose_source', return_value=result), \
             patch.object(voice.exemplars, 'retrieve', return_value=[]), \
             patch.object(voice, 'compact_summary', return_value={}), \
             patch.object(voice, 'judge', return_value={}):
            draft = voice.run(None, directory, n=1)[0]['drafts'][0]
        self.assertEqual(draft['stored_unit_ids'], ['u1', 'u2'])
        self.assertTrue(draft['view_available'])
        self.assertEqual(draft['post_type'], 'judgment_take')
        self.assertEqual(draft['stance']['decision'], 'adapt')

    def test_offline_voice_client_composes_structured_view(self):
        from live import compose, content_units
        from tests.test_compose import SOURCE, UNITS
        raw = copy.deepcopy(UNITS['units'][2])
        raw.update(kind='view', view=view(raw['source_spans'][0]['exact_text']))
        response = dict(text=json.dumps({'units': [UNITS['units'][0], raw]}), finish_reason='stop')
        units = content_units.extract(SOURCE, lambda *args: response, licence_tier='B')['units']
        result = compose.compose_source(SOURCE, 'en_industry', voice.StoreClient(units, 'en'), exemplars=False)
        self.assertEqual(result['post_type'], 'judgment_take')
        self.assertEqual(result['stance']['decision'], 'take')
        self.assertTrue(result['text'])
        self.assertNotIn('no_judgment', {f['code'] for f in result['post_checks']})


class RunnerTests(unittest.TestCase):
    def test_run_budget_additive_and_report_by_adapter(self):
        from scripts.enrich_store_views import enrich_store
        from ml import budget
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store_dir = root / 'store'
            store_dir.mkdir()
            (store_dir / 'units.jsonl').write_text(json.dumps(row()) + '\n')
            run = root / 'run'
            ledger = run / 'ledger'
            ledger.mkdir(parents=True)
            (ledger / 'spend.json').write_text(json.dumps({'spent_usd': 2.0}))
            with patch.object(budget, 'STORE', budget.STORE), \
                 patch.object(budget, 'LEDGER', budget.LEDGER), \
                 patch.object(budget, 'DISTILLATION_RUNS', budget.DISTILLATION_RUNS), \
                 patch.object(budget, 'RUNS', budget.RUNS), \
                 patch.object(budget, 'set_cap') as cap:
                report = enrich_store(store_dir, run, client=FakeClient(), cap_usd=3, max_calls=1)
                cap.assert_called_once_with(5.0)
                self.assertEqual(budget.LEDGER, ledger / 'spend.json')
            self.assertEqual(report['by_adapter'], {'research': {'enriched': 1, 'invalid': 0}})
            self.assertTrue((run / 'view_enrich_report.json').exists())

    def test_completed_batches_persist_if_next_call_fails(self):
        from scripts.enrich_store_views import enrich_store
        from ml import budget
        client = FakeClient()
        def fail_second(*args):
            if client.calls:
                raise RuntimeError('transport failed')
            return client(*args)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ContentStore(root / 'store')
            store.path.write_text(''.join(json.dumps(row(i)) + '\n' for i in range(9)))
            with patch.multiple(budget, STORE=budget.STORE, LEDGER=budget.LEDGER,
                                DISTILLATION_RUNS=budget.DISTILLATION_RUNS, RUNS=budget.RUNS), \
                 patch.object(budget, 'set_cap'):
                with self.assertRaisesRegex(RuntimeError, 'transport failed'):
                    enrich_store(store.root, root / 'run', client=fail_second)
            loaded = ContentStore(store.root).units()
            self.assertEqual(sum('view' in r['unit'] for r in loaded), 8)
            report = json.loads((root / 'run/view_enrich_report.json').read_text())
            self.assertEqual(report['deferred'], 1)
            self.assertEqual(len(report['enriched']), 8)
