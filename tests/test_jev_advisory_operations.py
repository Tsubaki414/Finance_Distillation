"""Jev is opt-in advice: outages must never change source monitoring outcomes."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from scripts import jev_advisory_review as cli
from scripts import run_monitor as runner


def fake_advisory(**overrides):
    module = types.ModuleType('live.jev_advisory')
    module.run_pending = Mock(return_value={'status': 'completed', 'reviewed': 1})
    module.pending_runs = Mock(return_value=[{'id': 'run-one'}])
    module.packet_for_run = Mock(side_effect=lambda store, run: {'run_id': run['id'], 'requests': []})
    module.review_run = Mock(side_effect=lambda store, rid, retry=False:
                             {'run_id': rid, 'status': 'completed', 'advisory_only': True})
    for key, value in overrides.items():
        setattr(module, key, value)
    return module


class MonitorAdvisoryTests(unittest.TestCase):
    def test_flag_requires_explicit_enable_and_process_env_wins(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch('live.writer_backend._dotenv', return_value={}):
            self.assertFalse(runner.jev_advisory_enabled())
        with patch.dict(os.environ, {'JEV_ADVISORY_ENABLED': 'false'}, clear=True), \
             patch('live.writer_backend._dotenv', return_value={'JEV_ADVISORY_ENABLED': '1'}):
            self.assertFalse(runner.jev_advisory_enabled())
        with patch.dict(os.environ, {}, clear=True), \
             patch('live.writer_backend._dotenv', return_value={'JEV_ADVISORY_ENABLED': 'true'}):
            self.assertTrue(runner.jev_advisory_enabled())

    def test_opt_in_advice_is_bounded_and_does_not_modify_source_report(self):
        module = fake_advisory()
        store = object()
        original = {'status': 'completed_with_blocks', 'accounts': [{'blocked': 1}]}
        with patch.dict('sys.modules', {'live.jev_advisory': module}), \
             patch.object(runner, 'jev_advisory_enabled', return_value=True):
            result = runner.advisory_after_cycle(types.SimpleNamespace(store=store), original,
                                                  threading.Event())
        module.run_pending.assert_called_once_with(store, limit=3)
        self.assertNotIn('jev_advisory', original)
        self.assertEqual(result['status'], original['status'])
        self.assertEqual(result['accounts'], original['accounts'])

    def test_advice_failure_is_sanitized_and_does_not_fail_the_cycle(self):
        module = fake_advisory(run_pending=Mock(side_effect=RuntimeError('secret request body')))
        original = {'status': 'completed'}
        with patch.dict('sys.modules', {'live.jev_advisory': module}), \
             patch.object(runner, 'jev_advisory_enabled', return_value=True):
            result = runner.advisory_after_cycle(types.SimpleNamespace(store=object()), original,
                                                  threading.Event())
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['jev_advisory']['error_type'], 'RuntimeError')
        self.assertNotIn('secret', json.dumps(result))

    def test_disabled_contended_incomplete_and_stopping_cycles_never_call(self):
        module = fake_advisory()
        with patch.dict('sys.modules', {'live.jev_advisory': module}), \
             patch.object(runner, 'jev_advisory_enabled', return_value=True):
            for status in ('already_running', 'running', 'monitor_disabled', 'cycle_failed'):
                original = {'status': status}
                self.assertIs(runner.advisory_after_cycle(object(), original, threading.Event()), original)
            stop = threading.Event()
            stop.set()
            runner.advisory_after_cycle(object(), {'status': 'completed'}, stop)
        module.run_pending.assert_not_called()

    def test_unset_flag_never_constructs_advice_client(self):
        module = fake_advisory()
        with patch.dict('sys.modules', {'live.jev_advisory': module}), \
             patch.object(runner, 'jev_advisory_enabled', return_value=False):
            runner.advisory_after_cycle(object(), {'status': 'completed'}, threading.Event())
        module.run_pending.assert_not_called()

    def test_run_loop_keeps_success_and_heartbeat_when_sidecar_fails(self):
        state = {}
        def meta(key, value=None):
            if value is not None:
                state[key] = value
            return state.get(key)
        monitor = types.SimpleNamespace(
            store=object(), state=types.SimpleNamespace(meta=meta), config={'enabled': True},
            heartbeat=lambda daemon: meta('heartbeat', {'pid': os.getpid(), 'daemon': daemon}),
            run_cycle=lambda: {'status': 'completed'})
        module = fake_advisory(run_pending=Mock(side_effect=ValueError('secret')))
        with patch.dict('sys.modules', {'live.jev_advisory': module}), \
             patch.object(runner, 'jev_advisory_enabled', return_value=True), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            result = runner.run_loop(monitor, continuous=False, interval_seconds=60,
                                     stop=threading.Event())
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'completed')
        self.assertEqual(state['heartbeat']['pid'], 0)


class AdvisoryCLITests(unittest.TestCase):
    def run_cli(self, args, module, root):
        store = types.SimpleNamespace(get=lambda kind, rid: {'id': rid})
        output = root / 'receipt'
        with patch.dict('sys.modules', {'live.jev_advisory': module}), \
             patch.object(cli, 'Store', return_value=store), \
             patch('sys.stdout', new_callable=io.StringIO) as stdout:
            code = cli.main([*args, '--output-dir', str(output)])
        return code, json.loads(stdout.getvalue()), output

    def test_default_is_a_read_only_preview_using_shared_pending_selector(self):
        module = fake_advisory()
        with tempfile.TemporaryDirectory() as directory:
            code, summary, output = self.run_cli([], module, Path(directory))
            self.assertEqual(code, 0)
            self.assertEqual(summary['mode'], 'preview')
            self.assertEqual(json.loads((output / 'review_packets.json').read_text())[0]['run_id'], 'run-one')
        module.pending_runs.assert_called_once()
        self.assertEqual(module.pending_runs.call_args.kwargs['limit'], 3)
        module.review_run.assert_not_called()

    def test_frozen_packet_keeps_original_ids_and_deduplicates(self):
        module = fake_advisory()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / 'packet.json'
            packet.write_text(json.dumps({'accounts': [
                {'account_id': 'zh_macro', 'drafts': [{'run_id': 'first'}, {'run_id': 'first'}]},
                {'account_id': 'zh_industry', 'drafts': [{'run_id': 'second'}]}]}))
            code, summary, _ = self.run_cli(['--live', '--packet', str(packet)], module, root)
        self.assertEqual(code, 0)
        self.assertEqual(summary['record_count'], 2)
        self.assertEqual([call.args[1] for call in module.review_run.call_args_list], ['first', 'second'])
        self.assertTrue(all(call.kwargs == {'retry': False} for call in module.review_run.call_args_list))

    def test_one_failure_does_not_skip_other_selected_records_or_expose_message(self):
        module = fake_advisory(review_run=Mock(side_effect=[RuntimeError('secret'), {'status': 'completed'}]))
        with tempfile.TemporaryDirectory() as directory:
            code, summary, output = self.run_cli(
                ['--live', '--run-id', 'first', '--run-id', 'second'], module, Path(directory))
            receipt = json.loads((output / 'result.json').read_text())
        self.assertEqual(code, 2)
        self.assertEqual(summary['issue_count'], 1)
        self.assertEqual(module.review_run.call_count, 2)
        self.assertNotIn('secret', json.dumps(receipt))

    def test_running_and_interrupted_results_are_incomplete_not_success(self):
        for status in ('running', 'interrupted', 'pending'):
            with self.subTest(status=status):
                module = fake_advisory(review_run=Mock(return_value={'status': status}))
                with tempfile.TemporaryDirectory() as directory:
                    code, summary, output = self.run_cli(
                        ['--live', '--run-id', 'first'], module, Path(directory))
                    receipt = json.loads((output / 'result.json').read_text())
                self.assertEqual(code, 2)
                self.assertEqual(summary['status'], 'incomplete')
                self.assertEqual(summary['issue_count'], 1)
                self.assertEqual(receipt['records'][0]['result']['status'], status)

    def test_preview_reports_blocked_requests_and_exact_coverage_gaps(self):
        module = fake_advisory(packet_for_run=Mock(return_value={
            'run_id': 'first', 'requests': [
                {'id': 'selection', 'blocked_reason': 'request_contract_or_payload_limit',
                 'coverage': 'whole original source and every selected passage; no truncation'},
                {'id': 'copy', 'blocked_reason': None, 'coverage': 'full translation and draft'}]}))
        with tempfile.TemporaryDirectory() as directory:
            code, summary, output = self.run_cli(['--run-id', 'first'], module, Path(directory))
            receipt = json.loads((output / 'result.json').read_text())
        self.assertEqual(code, 2)
        self.assertEqual(summary['status'], 'prepared_with_gaps')
        self.assertEqual(summary['request_count'], 2)
        self.assertEqual(summary['blocked_request_count'], 1)
        self.assertEqual(summary['coverage_gaps'][0]['request_id'], 'selection')
        self.assertEqual(summary['coverage_gaps'][0]['run_id'], 'first')
        self.assertEqual(receipt['records'][0]['status'], 'prepared_with_gaps')
        module.review_run.assert_not_called()

    def test_unknown_live_status_is_not_silently_successful(self):
        module = fake_advisory(review_run=Mock(return_value={'status': 'unexpected'}))
        with tempfile.TemporaryDirectory() as directory:
            code, summary, _ = self.run_cli(['--live', '--run-id', 'first'], module, Path(directory))
        self.assertEqual(code, 2)
        self.assertEqual(summary['issue_count'], 1)

    def test_retry_requires_named_live_target(self):
        module = fake_advisory()
        for arguments in (['--retry'], ['--retry', '--live'], ['--retry', '--run-id', 'first'],
                          ['--pending-limit', '4']):
            with patch.dict('sys.modules', {'live.jev_advisory': module}), \
                 patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(arguments)
        module.review_run.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            code, _, _ = self.run_cli(['--live', '--retry', '--run-id', 'first'], module, Path(directory))
        self.assertEqual(code, 0)
        self.assertTrue(module.review_run.call_args.kwargs['retry'])

    def test_empty_or_malformed_packet_fails_before_any_call(self):
        module = fake_advisory()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / 'packet.json'
            packet.write_text(json.dumps({'accounts': [{'drafts': [{'id': 'not-a-run-id'}]}]}))
            code, summary, output = self.run_cli(['--live', '--packet', str(packet)], module, root)
            self.assertFalse(output.exists())
        self.assertEqual(code, 2)
        self.assertEqual(summary['error_type'], 'ValueError')
        module.review_run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
