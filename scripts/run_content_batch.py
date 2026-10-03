"""Execute the requested KOL-only 3x5 content batch using existing account desks.

No production switch, manual prose, new service, automatic publishing or fake review.
Every transformation is a logged API call (same-language source is the baseline).
"""
import argparse
import copy
import json
from pathlib import Path
import re

from live.account_intelligence import Store, ROOT
from live.account_sources import SourcePipeline, ingest
from live.account_source_adaptation import adapt_source
from live.apify_distillation_client import ApifyClient
from live.distillation_source import digest, paragraphs, now
from live.distillation import require
from ml import budget

BASE = ROOT / 'runs/content_batch_v2'
VERSION = 'kol-single-post-batch-v2'
# Re-export historical names so saved batch tooling uses the shared runtime.
from live.content_stages import ContentStages, LOCALIZE, SELECT, MORRIS_STYLE


class ResumePrefix:
    """Reuse identical successful API stages in an explicitly linked follow-up.

    Only the source snapshot's observation timestamp is non-semantic. All other
    input changes force a new call. Saved API prose is never synthesized here.
    """
    def __init__(self, client, records, before, directory):
        self.client, self.saved, self.references = client, {}, []
        self.path = Path(directory) / 'reused_stages.json'
        order = ('routing', 'selection', 'evergreen_gate', 'source_hygiene', 'translation', 'localization', 'qa')
        prior = set(order[:order.index(before)])
        parsed = [(p, json.loads(p.read_text())) for p in records]
        parsed = [(p, r) for p, r in parsed if isinstance(r, dict) and r.get('stage') in prior]
        for record_path, record in sorted(parsed, key=lambda pair: pair[1]['started_at']):
            response = record.get('response') or {}
            if record.get('status') == 'completed' and response.get('finish_reason') == 'stop':
                self.saved[record['stage']] = (record_path, record)

    @staticmethod
    def comparable(messages):
        value = copy.deepcopy(messages)
        payload = json.loads(value[1]['content'])
        if isinstance(payload.get('source'), dict):
            payload['source'].pop('snapshot_at', None)
        value[1]['content'] = payload
        return value

    def __call__(self, stage, messages, max_tokens):
        saved = self.saved.get(stage)
        if saved and self.comparable(saved[1]['messages']) == self.comparable(messages):
            self.references.append({'stage': stage, 'original_call': str(saved[0]),
                                    'original_call_id': saved[1]['call_id'],
                                    'new_network_call': False})
            self.path.write_text(json.dumps(self.references, indent=2))
            return copy.deepcopy(saved[1]['response'])
        return self.client(stage, messages, max_tokens)


class BatchStages(ContentStages):
    """Compatibility entrypoint for explicitly requested historical batch runs."""
    def __init__(self, directory, item, baseline, provider='apify'):
        self.explicit_provider = provider
        if provider == 'openai':
            from scripts.content_batch_client import BatchClient
            factory = BatchClient
        elif provider == 'apify':
            factory = ApifyClient
        else:
            raise ValueError('Unsupported explicit batch provider')
        super().__init__(directory, item, baseline, client_factory=factory)

    @property
    def configuration(self):
        config = super().configuration
        if self.explicit_provider == 'openai':
            from scripts.content_batch_client import MODEL
            config.update(provider='openai_direct', model=MODEL)
        return config


def validate_item(account_id, item):
    source = item['source']
    require(source.get('content_complete') is True, 'Verified complete source unit required')
    require(not str(source.get('source_id', '')).startswith('primary_'), 'Official news release cannot be draft source')
    require(source.get('source_hash') in (None, digest(source['original_text'])), 'Source hash mismatch')
    if account_id == 'en_morris_archive':
        paired = re.search(r'不(?:只)?是[^。！？]{0,180}而是', source['original_text'])
        require(not paired or bool(item.get('style_exception')),
                'Morris contrast requires an explicit selected-source style exception')
    for passage in item.get('proposed_passages', []):
        require(source['original_text'][passage['start']:passage['end']] == passage['exact_text'],
                'Curation proposal is not an exact original span')
    return source


def execute(account_id, limit=5, provider='apify', follow_up=None, resume_stage=None, execution_repair=None):
    folder = BASE / 'source_selection' / account_id
    items = json.loads((folder / 'selected_sources.json').read_text())['sources']
    baseline = json.loads((folder / 'length_baseline.json').read_text()) if (folder / 'length_baseline.json').exists() else {}
    store = Store()
    outcomes = BASE / 'outcomes' / account_id
    outcomes.mkdir(parents=True, exist_ok=True)
    results = []
    for item in sorted(items, key=lambda x: x.get('priority', 999)):
        key = item['selection_id']
        require(re.fullmatch(r'[\w-]+', key), 'Invalid selection id')
        result_path = outcomes / (key + '.json')
        parent = json.loads(result_path.read_text()) if result_path.exists() and key == follow_up else None
        if parent and execution_repair:
            expected = {'hygiene_contract': 'source_hygiene', 'qa_capacity': 'qa', 'bounded_edits': 'translation'}
            require(resume_stage == expected[execution_repair], 'Execution repair stage mismatch')
            item = {**item, '_execution_repair': execution_repair}
        if result_path.exists() and (not parent or budget.remaining() <= 0):
            result = json.loads(result_path.read_text())
        else:
            if not parent and budget.remaining() < .5:
                # Pending reservations must not hide later completed outcomes.
                # Leave unexecuted items untouched for an explicit next run.
                continue
            source = validate_item(account_id, item)
            if parent:
                require(parent['account_id'] == account_id and parent['source_hash'] == digest(source['original_text']),
                        'Execution follow-up must preserve the original account and source')
                # Retain the exact immutable input snapshot, including its IDs.
                # Re-ingesting changes metadata and invalidates prefix replay even
                # when the source body is unchanged. valid_candidate rechecks the
                # saved subscription/source before SourcePipeline executes.
                admission = copy.deepcopy(parent['admission'])
            else:
                admission = ingest(store, account_id, source, fixture_id=key, batch_id=VERSION)
            record = {'selection_id': key, 'account_id': account_id, 'batch_id': VERSION,
                      'source_hash': digest(source['original_text']), 'started_at': now(),
                      'provider': provider, 'admission': admission,
                      'generation_origin': 'automated_pipeline', 'human_status': 'pending'}
            if not admission.get('admitted'):
                result = {**record, 'status': 'admission_stop', 'nonempty_draft': False}
            else:
                directory = BASE / 'calls' / account_id / key
                stages = BatchStages(directory, item, baseline, provider)
                original_adaptation = None
                history_path = None
                if parent:
                    require(resume_stage is not None, 'Follow-up requires its exact failed stage')
                    history = outcomes / 'history'
                    history.mkdir(exist_ok=True)
                    history_path = history / (key + '-' + parent['run_id'] + '.json')
                    if history_path.exists():
                        require(json.loads(history_path.read_text()) == parent,
                                'Saved parent differs; never overwrite follow-up history')
                    else:
                        history_path.write_text(json.dumps(parent, ensure_ascii=False, indent=2))
                    original_adaptation = json.loads(Path(parent['adaptation_path']).read_text())
                    original_directory = directory
                    directory = directory / ('followup-' + parent['run_id'])
                    stages = BatchStages(directory, item, baseline, provider)
                    stages.client = ResumePrefix(stages.client, list(original_directory.rglob('*.json')),
                                                 resume_stage, directory)
                def adapter(*args, **kwargs):
                    if original_adaptation:
                        kwargs['account_context'] = original_adaptation['attempt']['account_context']
                    value = adapt_source(*args, **kwargs)
                    value.update(generation_origin='automated_pipeline', generation_protocol=VERSION,
                                 batch_prompt_versions={'localization': digest(LOCALIZE), 'selection': digest(SELECT)},
                                 curation_reference=str(folder / 'selected_sources.json'))
                    Path(value['result_path']).write_text(json.dumps(value, ensure_ascii=False, indent=2))
                    return value
                previous = [r for r in store.rows('runs')
                            if r.get('inbox_candidate_id') == admission['candidate']['id']]
                print(json.dumps({'started': key, 'account': account_id, 'budget_remaining': budget.remaining()}), flush=True)
                # A re-ingested snapshot can receive a new inbox ID even when
                # its source identity is unchanged. Follow the explicit outcome,
                # not an empty history on that new inbox (which would dedup-return
                # the original failed run without executing the requested stage).
                parent_id = parent['run_id'] if parent else (previous[-1]['id'] if previous else None)
                run = SourcePipeline(store=store, client=stages, adapter=adapter).run(
                    account_id, admission['candidate']['id'], follow_up_of=parent_id)
                if parent:
                    require(run['id'] != parent_id and run.get('follow_up_of') == parent_id,
                            'Requested follow-up did not execute; cached parent is not a new result')
                result = {**record, 'run_id': run['id'], 'follow_up_of': run.get('follow_up_of'),
                          'status': run['status'], 'nonempty_draft': bool(run['candidates']),
                          'machine_pass': bool(run['candidates'] and run['candidates'][0]['machine_fidelity_pass']),
                          'finished_at': now(), 'final_draft': run['candidates'][0]['text'] if run['candidates'] else '',
                          'adaptation_path': run.get('source_adaptation', {}).get('result_path'),
                          'why': run.get('source_adaptation', {}).get('why', run.get('contract_error'))}
                if parent:
                    result.update(previous_outcome_path=str(history_path), resumed_at_stage=resume_stage,
                                  original_run_id=parent.get('original_run_id', parent['run_id']),
                                  execution_repair=execution_repair)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        results.append(result)
        print(json.dumps({k: result.get(k) for k in ('selection_id', 'status', 'nonempty_draft', 'machine_pass', 'why')}, ensure_ascii=False), flush=True)
        if sum(bool(r['nonempty_draft']) for r in results) >= limit and (not follow_up or any(r['selection_id'] == follow_up for r in results)):
            break
    manifest = {'version': VERSION, 'account_id': account_id, 'requested': limit, 'finished_at': now(),
                'nonempty_drafts': sum(bool(r['nonempty_draft']) for r in results),
                'machine_passes': sum(bool(r.get('machine_pass')) for r in results),
                'human_reviews': 0, 'items': results, 'publishing_enabled': False}
    (outcomes / 'summary.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--account', required=True, choices=('en_morris_archive', 'zh_macro', 'zh_industry'))
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--provider', choices=('apify', 'openai'), default='apify')
    parser.add_argument('--follow-up', help='Retain and follow up this existing selection identity')
    parser.add_argument('--resume-stage', choices=('routing', 'selection', 'evergreen_gate', 'source_hygiene', 'translation', 'localization', 'qa'))
    parser.add_argument('--execution-repair', choices=('hygiene_contract', 'qa_capacity', 'bounded_edits'))
    args = parser.parse_args()
    execute(args.account, args.limit, args.provider, args.follow_up, args.resume_stage, args.execution_repair)
