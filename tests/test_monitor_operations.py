"""Service safety and automatic review-queue refresh without external calls."""
import json
import io
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import manage_monitor as services
from scripts import run_monitor as runner


class MonitorServicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'project with spaces'
        (self.root / '.venv/bin').mkdir(parents=True)
        (self.root / '.venv/bin/python').touch()
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/run_monitor.py').touch()
        self.target = Path(self.temp.name) / 'LaunchAgents'

    def test_prepare_is_repo_local_and_uses_current_entrypoints(self):
        with patch.object(services, 'launchctl', side_effect=AssertionError('prepare must not start jobs')):
            result = services.prepare(self.root)
        self.assertFalse(self.target.exists())
        self.assertFalse(result['installed'])
        monitor = plistlib.loads(Path(result['prepared']['monitor']).read_bytes())
        dashboard = plistlib.loads(Path(result['prepared']['dashboard']).read_bytes())
        self.assertEqual(monitor['ProgramArguments'][2], str(self.root / 'scripts/run_monitor.py'))
        self.assertEqual(monitor['ProgramArguments'][3:], ['--continuous', '--interval-seconds', '1800'])
        self.assertIn('backend.content_dashboard:app', dashboard['ProgramArguments'])
        self.assertEqual(dashboard['ProgramArguments'][-4:], ['--host', '127.0.0.1', '--port', '8684'])
        self.assertEqual(monitor['WorkingDirectory'], str(self.root))
        self.assertEqual(set(monitor['EnvironmentVariables']), {'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE'})
        self.assertTrue(monitor['RunAtLoad'] and monitor['KeepAlive'])

    def test_busy_unowned_port_never_writes_or_stops_service(self):
        with patch.object(services.sys, 'platform', 'darwin'), \
             patch.object(services, 'launchctl') as launch, \
             patch.object(services, 'listener_exists', return_value=True), \
             patch.object(services, 'service_status', return_value={'loaded': False}):
            with self.assertRaisesRegex(ValueError, 'occupied outside'):
                services.install(self.root, agents_dir=self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual([call.args[0] for call in launch.call_args_list], ['print'])

    def test_foreign_workspace_plist_is_preserved(self):
        self.target.mkdir()
        path = self.target / f'{services.label("monitor")}.plist'
        content = plistlib.dumps({'Label': services.label('monitor'), 'WorkingDirectory': '/another/project'})
        path.write_bytes(content)
        with patch.object(services.sys, 'platform', 'darwin'), \
             patch.object(services, 'launchctl'), \
             patch.object(services, 'listener_exists', return_value=False):
            with self.assertRaisesRegex(ValueError, 'another workspace'):
                services.install(self.root, agents_dir=self.target)
            with self.assertRaisesRegex(ValueError, 'another workspace'):
                services.uninstall(self.root, agents_dir=self.target)
        self.assertEqual(path.read_bytes(), content)

    def test_status_never_returns_launchd_environment(self):
        output = 'state = running\npid = 123\nruns = 2\nenvironment = {\nAPI_KEY = secret-token\n}\n'
        with patch.object(services, 'launchctl', return_value=subprocess.CompletedProcess([], 0, output, '')):
            state = services.service_status('monitor')
        self.assertTrue(state['running'])
        self.assertEqual(state['pid'], '123')
        self.assertNotIn('secret', json.dumps(state))

    def test_install_waits_for_exact_bootout_job_before_bootstrap(self):
        events = []
        state = {service: {'loaded': True, 'remaining': 0} for service in services.SERVICES}

        def check(service):
            job = state[service]
            events.append(('status', service))
            if job['remaining']:
                job['remaining'] -= 1
                return {'loaded': True}
            return {'loaded': job['loaded']}

        def launch(command, *args, **kwargs):
            events.append((command, args))
            if command == 'bootout':
                service = args[0].rsplit('.', 1)[-1]
                state[service].update(loaded=False, remaining=2)
            elif command == 'bootstrap':
                service = Path(args[1]).stem.rsplit('.', 1)[-1]
                self.assertEqual(state[service]['remaining'], 0)
                self.assertFalse(state[service]['loaded'])
                state[service]['loaded'] = True
            return subprocess.CompletedProcess([], 0, '', '')

        with patch.object(services.sys, 'platform', 'darwin'), \
                patch.object(services, 'launchctl', side_effect=launch), \
                patch.object(services, 'listener_exists', return_value=False), \
                patch.object(services, 'service_status', side_effect=check), \
                patch.object(services.time, 'sleep') as sleep:
            result = services.install(self.root, agents_dir=self.target)
        self.assertEqual(set(result['installed']), {'dashboard', 'monitor'})
        self.assertEqual(sleep.call_count, 4)
        boots = [row for row in events if row[0] == 'bootstrap']
        self.assertIn('dashboard', boots[0][1][1])
        self.assertIn('monitor', boots[1][1][1])

    def test_bootout_timeout_prevents_bootstrap_or_further_service_changes(self):
        with patch.object(services.sys, 'platform', 'darwin'), \
                patch.object(services, 'launchctl') as launch, \
                patch.object(services, 'listener_exists', return_value=False), \
                patch.object(services, 'service_status', return_value={'loaded': True}), \
                patch.object(services.time, 'monotonic', side_effect=[0, 16]), \
                patch.object(services.time, 'sleep'), \
                self.assertRaisesRegex(RuntimeError, 'did not unload.*dashboard'):
            services.install(self.root, agents_dir=self.target)
        commands = [call.args[0] for call in launch.call_args_list]
        self.assertEqual(commands, ['print', 'bootout'])

    def test_bootstrap_retries_only_transient_unloaded_exit_five(self):
        failure = subprocess.CompletedProcess([], 5, '', 'Bootstrap failed: 5: Input/output error')
        success = subprocess.CompletedProcess([], 0, '', '')
        with patch.object(services, 'launchctl', side_effect=[failure, success]) as launch, \
                patch.object(services, 'service_status', return_value={'loaded': False}), \
                patch.object(services.time, 'sleep') as sleep:
            services.bootstrap_service('dashboard', 'gui/123', '/owned/dashboard.plist')
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(launch.call_args_list[0], launch.call_args_list[1])
        sleep.assert_called_once_with(0.5)

    def test_bootstrap_race_retry_is_bounded_and_never_overwrites_loaded_job(self):
        for code, loaded, calls in [(5, False, 3), (5, True, 1), (13, False, 1)]:
            with self.subTest(code=code, loaded=loaded), \
                    patch.object(services, 'launchctl', return_value=subprocess.CompletedProcess(
                        [], code, '', 'bootstrap failed')) as launch, \
                    patch.object(services, 'service_status', return_value={'loaded': loaded}), \
                    patch.object(services.time, 'sleep'), \
                    self.assertRaisesRegex(RuntimeError, 'bootstrap failed'):
                services.bootstrap_service('monitor', 'gui/123', '/owned/monitor.plist')
            self.assertEqual(launch.call_count, calls)


@unittest.skipUnless(shutil.which('node'), 'Node required for browser refresh contract test')
class MonitorRefreshTests(unittest.TestCase):
    def test_background_refresh_preserves_editing_and_account_isolation(self):
        source = (services.ROOT / 'frontend/account-intelligence.js').read_text()
        function = source[source.index('async function refreshAutomatically(){'):source.index('setInterval(refreshAutomatically,30000);')]
        harness = """
const assert=require('assert');
let refreshing=false,loading=false,selectedAccount='zh_macro',loadEpoch=1;
let dirty=true,selectedRun='draft-being-edited',selectedCandidate=null,data={},inbox={},monitor={};
let document={hidden:false},shows=0,errors=0,rendered=0;
let renderOverview=()=>rendered++,renderQueues=()=>rendered++,renderMonitor=()=>rendered++;
let renderMonitorError=()=>errors++,showRun=async()=>shows++,activeRuns=()=>[{id:'new-draft',draft_count:1}],draftCount=r=>r.draft_count;
let api=async(path)=>path.endsWith('inbox')?{account:'zh_macro',candidates:[]}:{fresh:true};
""" + function + """
(async()=>{
 await refreshAutomatically();
 assert.equal(shows,0);assert.equal(selectedRun,'draft-being-edited');assert.equal(dirty,true);
 assert.equal(rendered,3);assert.equal(inbox.account,'zh_macro');
 let prior=data;api=async()=>{selectedAccount='zh_industry';return {wrongAccount:true};};
 await refreshAutomatically();assert.equal(data,prior);assert.equal(shows,0);
 api=async()=>{throw Error('offline');};await refreshAutomatically();assert.equal(errors,1);
 assert.equal(refreshing,false);assert.equal(data,prior);
 dirty=false;selectedRun=null;selectedCandidate=null;api=async()=>({});
 await refreshAutomatically();assert.equal(shows,1);
})().catch(error=>{console.error(error);process.exit(1);});
"""
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MonitorProcessTests(unittest.TestCase):
    def test_second_cli_does_not_construct_client_or_overwrite_daemon_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory, runner.process_lock(directory) as acquired:
            self.assertTrue(acquired)
            with patch.object(runner, 'Monitor', side_effect=AssertionError('Must not create client')), \
                 patch.object(runner.signal, 'signal'), patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(runner.main(['--once', '--store', directory]), 0)
            self.assertEqual(json.loads(output.getvalue())['status'], 'already_running')
        with tempfile.TemporaryDirectory() as directory:
            with runner.process_lock(directory) as acquired:
                self.assertTrue(acquired)
            with runner.process_lock(directory) as restarted:
                self.assertTrue(restarted)

    @staticmethod
    def fake_monitor(enabled=True, fail=False, replace_owner=False):
        state={}
        heartbeat_written=threading.Event()
        calls=[]
        def meta(key,value=None):
            if value is not None:
                state[key]=value
            return state.get(key)
        def heartbeat(daemon):
            meta('heartbeat',{'pid':os.getpid(),'daemon':daemon})
            heartbeat_written.set()
        def cycle():
            heartbeat_written.wait(1)
            calls.append('cycle')
            if replace_owner:
                meta('heartbeat',{'pid':987654321,'daemon':True})
            if fail:
                raise RuntimeError('synthetic test error')
            return {'status':'complete'}
        return SimpleNamespace(state=SimpleNamespace(meta=meta),config={'enabled':enabled},
                               heartbeat=heartbeat,run_cycle=cycle),state,calls

    def test_disabled_monitor_keeps_status_but_never_polls_or_calls_models(self):
        monitor,state,calls=self.fake_monitor(enabled=False)
        with patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(runner.run_loop(monitor,continuous=False,interval_seconds=60,stop=threading.Event()),0)
        self.assertEqual(calls,[])
        self.assertEqual(json.loads(output.getvalue())['status'],'monitor_disabled')
        self.assertEqual(state['heartbeat']['pid'],0)

    def test_failed_once_returns_nonzero_and_clears_own_heartbeat(self):
        monitor,state,calls=self.fake_monitor(fail=True)
        with patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(runner.run_loop(monitor,continuous=False,interval_seconds=60,stop=threading.Event()),1)
        self.assertEqual(calls,['cycle'])
        self.assertFalse(state['heartbeat']['daemon'])

    def test_shutdown_does_not_clear_a_different_process_owner(self):
        monitor,state,calls=self.fake_monitor(replace_owner=True)
        with patch('sys.stdout',new_callable=io.StringIO):
            runner.run_loop(monitor,continuous=False,interval_seconds=60,stop=threading.Event())
        self.assertEqual(state['heartbeat']['pid'],987654321)


if __name__ == '__main__':
    unittest.main()
