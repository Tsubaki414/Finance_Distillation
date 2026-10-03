"""Output gate must block local paths and privacy leakage before any Evergreen export.

Includes real strings taken from the corpus, and unseen variants so the gate is tested for
generalisation rather than for matching the one username we happened to find.
Run: .venv/bin/python -B tests/test_evergreen_output_gate.py
"""
from pathlib import Path
import sys, json, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evergreen'))
from output_gate import scan, blocked, redact, assert_exportable


class OutputGate(unittest.TestCase):

    def test_blocks_the_real_corpus_leak(self):
        self.assertTrue(blocked('参考 /Users/chenboyu/Documents/research/reads 目录'))

    def test_blocks_unseen_usernames_not_just_the_known_one(self):
        # Generalisation: the gate must not be a denylist of names already observed.
        for p in ['/Users/someoneelse/notes.md', '/home/trader9/corpus',
                  'file:///Users/zzz/x.pdf', r'C:\Users\Bob\Desktop\a.txt',
                  r'\\server01\share\book.pdf']:
            self.assertTrue(blocked(f'见 {p} 内容'), p)

    def test_blocks_email_and_private_ip(self):
        self.assertTrue(blocked('联系 someone@example.com'))
        self.assertTrue(blocked('服务在 192.168.1.20 上'))

    def test_blocks_conversion_headers(self):
        self.assertTrue(blocked('# Tony语录\n\n- Method: `tesseract-ocr`\n- Generated: 2026-04-14'))

    def test_clean_trading_prose_passes(self):
        clean = ('趋势没有确认之前不加仓。若价格跌破前低，该判断失效，'
                 '此时应减仓而不是加仓。仓位规模由止损距离决定。')
        self.assertEqual(scan(clean), [])
        self.assertEqual(assert_exportable(clean, 'principle'), clean)

    def test_public_url_is_not_blocked(self):
        self.assertFalse(blocked('原帖 https://weibo.com/u/1234567 与 https://x.com/a/status/1'))

    def test_assert_raises_with_kind_in_message(self):
        with self.assertRaises(ValueError) as e:
            assert_exportable('见 /Users/chenboyu/x.md', 'chapter')
        self.assertIn('posix_home_path', str(e.exception))
        self.assertIn('chapter', str(e.exception))

    def test_redact_removes_the_path(self):
        r = redact('见 /Users/chenboyu/Documents/research/reads 目录')
        self.assertNotIn('chenboyu', r)
        self.assertEqual(scan(r), [])

    def test_every_flagged_corpus_file_is_actually_caught(self):
        m = json.loads((ROOT / 'evergreen/corpus_manifest.json').read_text())
        flagged = [r for r in m['items'] if r.get('third_party_local_paths')]
        self.assertGreaterEqual(len(flagged), 20, 'manifest should still flag the known leak set')
        for r in flagged:
            text = (ROOT / r['extracted_path']).read_text(encoding='utf-8', errors='replace')
            self.assertTrue(blocked(text), r['zip_path'])

    def test_production_candidate_docs_are_not_exportable_raw(self):
        # Raw corpus text carries conversion headers, so nothing may be exported verbatim
        # without passing through span selection and the gate.
        pools = json.loads((ROOT / 'evergreen/pools.json').read_text())
        prod = [d for d in pools['documents'] if d['pool'] == 'production_candidate']
        self.assertTrue(prod, 'production_candidate pool must exist after the rename')
        leaky = [d for d in prod
                 if blocked((ROOT / d['extracted_path']).read_text(encoding='utf-8', errors='replace'))]
        self.assertTrue(leaky, 'expected raw production-candidate files to be gate-blocked as-is')


if __name__ == '__main__':
    unittest.main(verbosity=2)
