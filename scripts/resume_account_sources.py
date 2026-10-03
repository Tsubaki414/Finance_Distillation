"""Resume quota-stopped fixtures using verified completed responses, no prompt edits.

python -m scripts.resume_account_sources --run RUN_ID [--provider relay|apify]
Only source.snapshot_at (normalizer observation time) is ignored for comparison;
all source text, publication/capture dates, as-of, account state and instructions
must still match. Cached responses are recorded as replayed, never as new calls.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from live.account_intelligence import Store, ROOT, require
from live.account_sources import SourcePipeline
from live.distillation_client import RelayClient
from live.distillation_source import digest, now


def comparable(messages):
    value = copy.deepcopy(messages)
    for message in value:
        if message.get('role') != 'user':
            continue
        payload = json.loads(message['content'])
        if isinstance(payload.get('source'), dict):
            payload['source'].pop('snapshot_at', None)
        message['content'] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return value


class CompletedResponses:
    def __init__(self, records, client, replay_path, expected_model=None):
        self.cached, self.requests = {}, {}
        for path, record in records:
            require(record.get('stage') and isinstance(record.get('messages'), list), 'Invalid checkpoint call record')
            require(record.get('status') in ('completed', 'failed'),
                    'Checkpoint call is still in flight or has unknown settlement; do not retry')
            require(type(record.get('max_tokens')) is int and record['max_tokens'] > 0,
                    'Checkpoint max_tokens is invalid')
            require(record.get('prompt_hash') == digest(record['messages']), 'Checkpoint prompt hash is stale')
            if expected_model:
                require(record.get('model') == expected_model and record.get('temperature') == 0,
                        'Checkpoint model/temperature changed')
            request = (record.get('max_tokens'), comparable(record['messages']))
            previous = self.requests.get(record['stage'])
            require(previous is None or previous == request, 'Checkpoint inputs changed across continuations')
            self.requests[record['stage']] = request
            if record['status'] == 'completed':
                require(record['stage'] not in self.cached, 'Ambiguous cached stage; do not guess a continuation')
                require(isinstance(record.get('response'), dict) and record['response'].get('finish_reason') == 'stop'
                        and not record['response'].get('refusal'), 'Checkpoint response is not a complete usable response')
                self.cached[record['stage']] = (path, record)
        self.client, self.path, self.calls = client, Path(replay_path), []
        self.used, self.called = set(), set()

    def __call__(self, stage, messages, max_tokens):
        require(stage not in self.called, 'Continuation stage invoked more than once')
        previous_request = self.requests.get(stage)
        require(previous_request is None or previous_request == (max_tokens, comparable(messages)),
                'Checkpoint inputs changed; refuse cached response and new charge')
        if stage not in self.cached:
            require(self.used == set(self.cached), 'Unreplayed completed stages remain; refuse a new charge')
            self.called.add(stage)
            return self.client(stage, messages, max_tokens)
        path, previous = self.cached[stage]
        require(stage not in self.used, 'Completed stage reused more than once')
        self.called.add(stage)
        self.used.add(stage)
        record = {'stage': stage, 'replayed_at': now(), 'kind': 'completed_response_replay',
                  'original_call': str(path), 'original_call_hash': digest(previous),
                  'comparison': 'Exact inputs except source.snapshot_at; semantic timestamps retained', 'new_model_call': False}
        self.calls.append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        return {**previous['response'], 'checkpoint_replay': str(path)}


def _record_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def collect_records(store, parent, root, expected_model=None):
    """Collect actual calls along this source attempt's explicit continuation chain.

    A continuation's transport logs live under its parent ID, whereas its normal
    adaptation artifacts live under its own ID. Stop at the old event pipeline;
    its different prompts are not valid translation-first checkpoints.
    """
    root = Path(root)
    chain, seen, current = [], set(), parent
    while current.get('pipeline') == 'account_source':
        require(current['id'] not in seen, 'Continuation ancestry contains a cycle')
        require(current['account_id'] == parent['account_id']
                and current['inbox_candidate_id'] == parent['inbox_candidate_id']
                and current.get('fixture_id') == parent.get('fixture_id'), 'Continuation source/account identity changed')
        seen.add(current['id'])
        chain.append(current)
        if not current.get('follow_up_of'):
            break
        current = store.get('runs', current['follow_up_of'])
    chain.reverse()
    records, paths, directories = [], set(), []
    chain_ids = {row['id'] for row in chain}
    for run in chain:
        call_directories = [root / 'adaptations' / run['id'] / 'calls']
        if run.get('follow_up_of') in chain_ids:
            directory = root / 'continuations' / run['follow_up_of']
            directories.append((directory, run))
            call_directories.append(directory / 'calls')
        for directory in call_directories:
            for path in sorted(directory.glob('*.json')):
                path = path.resolve()
                if path in paths:
                    continue
                record = json.loads(path.read_text())
                paths.add(path)
                records.append((path, record))
    require(records, 'Original and ancestral call records missing')
    by_path = dict(records)
    for directory, run in directories:
        manifest = directory / 'continuation.json'
        if manifest.exists():
            meta = json.loads(manifest.read_text())
            require(meta.get('parent_run_id') == run['follow_up_of']
                    and meta.get('child_run_id') in (None, run['id']), 'Continuation manifest identity changed')
            for saved in meta.get('checkpoint_records', []):
                path = _record_path(saved['path'])
                require(path in by_path and digest(by_path[path]) == saved['record_hash'],
                        'Ancestral checkpoint record hash is stale')
        replay_path = directory / 'replayed_stages.jsonl'
        if replay_path.exists():
            for line in replay_path.read_text().split('\n'):
                if not line.strip():
                    continue
                replay = json.loads(line)
                path = _record_path(replay['original_call'])
                require(replay.get('kind') == 'completed_response_replay' and replay.get('new_model_call') is False,
                        'Invalid ancestral replay record')
                require(path in by_path and by_path[path]['status'] == 'completed'
                        and digest(by_path[path]) == replay['original_call_hash'], 'Ancestral replay hash is stale')
    # Validate all record contracts before constructing a provider that could charge.
    CompletedResponses(records, None, root / 'unused.jsonl', expected_model)
    return chain, records


def provider_client(provider, directory):
    if provider == 'apify':
        from live.apify_distillation_client import ApifyClient
        return ApifyClient(directory)
    require(provider == 'relay', 'Unknown continuation provider')
    return RelayClient(directory)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--provider', choices=('relay', 'apify'), default='relay')
    args = parser.parse_args()
    store = Store()
    parent = store.get('runs', args.run)
    attempt = parent.get('source_adaptation', {}).get('attempt', {})
    require(parent.get('pipeline') == 'account_source' and attempt.get('external_block') == 'provider_quota',
            'Only a recorded account-source provider quota stop may resume here')
    root = ROOT / 'runs/account_sources_v1'
    manifest = json.loads((root / 'evaluation_manifest.json').read_text())
    require(all(hashlib.sha256((ROOT / r['path']).read_bytes()).hexdigest() == r['sha256'] for r in manifest['files']),
            'Frozen evaluation code changed; stop before charging relay')
    # Refuse repeated continuation of the same parent; select its failed child explicitly.
    require(not any(r.get('follow_up_of') == parent['id'] for r in store.rows('runs')), 'Parent already has a follow-up')
    directory = root / 'continuations' / parent['id']
    chain, records = collect_records(store, parent, root, manifest['model'])
    require(not directory.exists() or not any(directory.iterdir()),
            'Continuation directory already exists without a linked child; inspect its transport logs before resuming')
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {'parent_run_id': parent['id'], 'child_run_id': None, 'provider': args.provider,
                'model': manifest['model'], 'temperature': 0, 'started_at': now(),
                'account_id': parent['account_id'], 'inbox_candidate_id': parent['inbox_candidate_id'],
                'fixture_id': parent.get('fixture_id'), 'ancestry': [r['id'] for r in chain],
                'checkpoint_records': [{'path': str(p), 'record_hash': digest(r)} for p, r in records]}
    metadata_path = directory / 'continuation.json'
    with metadata_path.open('x') as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    client = CompletedResponses(records, provider_client(args.provider, directory / 'calls'),
                                directory / 'replayed_stages.jsonl', manifest['model'])
    result = SourcePipeline(store, client=client).run(parent['account_id'], parent['inbox_candidate_id'], parent['id'])
    metadata.update(child_run_id=result['id'], finished_at=now(), status=result['status'])
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(json.dumps({'run_id': result['id'], 'follow_up_of': parent['id'], 'status': result['status'],
                      'provider': args.provider, 'ancestry': metadata['ancestry'],
                      'replayed_stages': sorted(client.used)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
