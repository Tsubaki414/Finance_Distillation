"""P0-2 acceptance: one assembly point for every model request.

1. Behaviour is preserved: the fixed case matrix produces exactly the golden
   requests captured before the refactor (tests/fixtures/p0_prompt_golden.json).
2. Every request carries an assembly record: registered template id/hash, the
   rules applied, the rules explicitly dropped, and the sha256 of the messages,
   which must equal the hash seen at the transport boundary.
3. No module outside live/prompt_assembly.py mutates the system prompt or the
   request messages (AST check, including string concatenation onto prompts).
"""
import ast
import json
from pathlib import Path
import unittest

import p0_prompt_cases as cases

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / 'tests/fixtures/p0_prompt_golden.json').read_text())


class Equivalence(unittest.TestCase):
    def test_requests_identical_to_pre_refactor_golden(self):
        for name in cases.CASES:
            with self.subTest(case=name):
                self.assertEqual(cases.run_case(name)[0], GOLDEN[name])


class AssemblyRecord(unittest.TestCase):
    def test_every_call_recorded_and_hash_matches_transport(self):
        for name in cases.CASES:
            with self.subTest(case=name):
                _, result, recorder = cases.run_case(name)
                records = result['attempt'].get('prompt_assembly')
                self.assertIsInstance(records, list)
                self.assertEqual([r['stage'] for r in records], [c['stage'] for c in recorder.sent])
                for record, sent in zip(records, recorder.sent):
                    self.assertEqual(record['messages_sha256'], sent['sha256'])
                    self.assertEqual([m['role'] for m in sent['messages']], ['system', 'user'])
                    self.assertFalse(record['template_id'].startswith('unregistered'), record)
                    self.assertEqual(len(record['template_sha256']), 64)
                    self.assertIsInstance(record['rules_applied'], list)
                    self.assertIsInstance(record['rules_dropped'], list)

    def test_overridden_stages_declare_dropped_rules(self):
        _, result, _ = cases.run_case('industry_long_selection')
        by_stage = {r['stage']: r for r in result['attempt']['prompt_assembly']}
        self.assertIn('account.MEDIA_SELECTION_BOUNDARY', by_stage['selection']['rules_dropped'])
        self.assertIn('hygiene.WRITER_BOUNDARY', by_stage['localization']['rules_dropped'])
        self.assertIn('account.MEDIA_SELECTION_BOUNDARY', by_stage['routing']['rules_applied'])


MUTATION_FILES = ['live/distillation.py', 'live/account_source_adaptation.py', 'live/content_stages.py']


def _is_messages_target(node):
    # messages[...] = ..., messages[0]['content'] = ...
    while isinstance(node, ast.Subscript):
        node = node.value
    return isinstance(node, ast.Name) and node.id == 'messages'


class NoMutationOutsideAssembly(unittest.TestCase):
    def test_no_system_or_message_mutation(self):
        offenders = []
        for rel in MUTATION_FILES:
            tree = ast.parse((ROOT / rel).read_text())
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, ast.AugAssign):
                    targets = [node.target]
                    if isinstance(node.target, ast.Name) and node.target.id == 'system':
                        offenders.append(f'{rel}:{node.lineno} system +=')
                for t in targets:
                    if isinstance(t, ast.Subscript) and _is_messages_target(t):
                        offenders.append(f'{rel}:{node.lineno} messages[...] =')
                # string concatenation onto prompt constants passed to ask()
                if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'ask' and len(node.args) >= 3:
                    if isinstance(node.args[2], ast.BinOp):
                        offenders.append(f'{rel}:{node.lineno} ask(system=<concatenation>)')
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
