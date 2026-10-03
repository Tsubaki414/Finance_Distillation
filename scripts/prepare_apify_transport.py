"""Build one private, pinned, limited-permission transport; never publishes it."""
import json
import time
import uuid
from live.apify_distillation_client import api, CONFIG, TRANSPORT, ROOT, source_hashes
from ml import budget


def main():
    TRANSPORT.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        config = json.loads(CONFIG.read_text())
        if config['source_hashes'] != source_hashes():
            raise ValueError('Existing private Actor source differs; no silent rebuild')
        print(json.dumps({'actor_id': config['actor_id'], 'build_id': config['build_id'], 'reused': True}))
        return
    version = {'versionNumber': '0.0', 'sourceType': 'SOURCE_FILES', 'sourceFiles': [
        {'name': name, 'format': 'TEXT', 'content': (ROOT / 'scripts/apify_passthrough' / name).read_text()}
        for name in ('main.py', 'Dockerfile')]}
    payload = {'name': 'account-source-passthrough-' + source_hashes()['main.py'][:8],
               'isPublic': False, 'versions': [version],
               'defaultRunOptions': {'build': 'evaluation-v1', 'timeoutSecs': 240, 'memoryMbytes': 256,
                                     'forcePermissionLevel': 'LIMITED_PERMISSIONS', 'restartOnError': False}}
    manifest = {'create_payload': payload, 'source_hashes': source_hashes(), 'status': 'prepared'}
    log = TRANSPORT / 'private_actor_build.json'
    log.write_text(json.dumps(manifest, indent=2) + '\n')
    reservation_id = 'apify-build-' + uuid.uuid4().hex
    budget.reserve('apify/build', [], 0, reservation_id, overhead_usd=0.25)
    build = None
    cost = None
    try:
        actor = api('/acts', payload)['data']
        manifest['actor_id'] = actor['id']
        log.write_text(json.dumps(manifest, indent=2) + '\n')
        actor = api('/acts/' + actor['id'], {'actorPermissionLevel': 'LIMITED_PERMISSIONS'}, 'PUT')['data']
        if actor.get('isPublic') is not False or actor.get('actorPermissionLevel') != 'LIMITED_PERMISSIONS':
            raise ValueError('Actor privacy/permissions verification failed')
        build = api('/acts/' + actor['id'] + '/builds?version=0.0&tag=evaluation-v1&waitForFinish=1',
                    method='POST')['data']
        manifest['build_id'] = build['id']
        log.write_text(json.dumps(manifest, indent=2) + '\n')
        deadline = time.monotonic() + 240
        while build['status'] not in {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}:
            if time.monotonic() > deadline:
                raise TimeoutError('Build deadline')
            time.sleep(3)
            build = api('/actor-builds/' + build['id'])['data']
        if build['status'] != 'SUCCEEDED':
            raise RuntimeError('Private transport build failed: ' + build['status'])
        config = {'actor_id': actor['id'], 'build_id': build['id'], 'build_number': build['buildNumber'],
                  'source_hashes': source_hashes(), 'is_public': False, 'permissions': 'LIMITED_PERMISSIONS'}
        CONFIG.write_text(json.dumps(config, indent=2) + '\n')
        manifest.update(status='succeeded', config=config)
        print(json.dumps(config))
    finally:
        if build:
            try:
                if build['status'] not in {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}:
                    api('/actor-builds/' + build['id'] + '/abort', method='POST')
                time.sleep(3)
                final = api('/actor-builds/' + build['id'])['data']
                cost = final.get('usageTotalUsd') or None
                manifest['build_status'] = final['status']
            except Exception as exc:
                manifest['accounting_error'] = type(exc).__name__
        manifest['usage_usd'] = cost
        manifest['budget_estimate_usd'] = budget.settle(reservation_id, {'prompt_tokens': 0, 'completion_tokens': 0},
                                                       overhead_actual_usd=cost)
        log.write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
