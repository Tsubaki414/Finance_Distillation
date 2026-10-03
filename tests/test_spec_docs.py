"""P0-4a: current-state docs describe post_type products; translation + light
edit only as aphorism_translation (Morris)."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_spec_docs', ROOT / 'scripts' / 'check_spec_docs.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class SpecDocsTests(unittest.TestCase):
    def test_no_violations(self):
        self.assertEqual(check.hits(), [])

    def test_checker_flags_light_edit_outside_aphorism(self):
        self.assertTrue(check.LIGHT_EDIT.search('翻译 → 最小轻编'))
        self.assertTrue(check.LIGHT_EDIT.search('translation → light-localization'))


if __name__ == '__main__':
    unittest.main()
