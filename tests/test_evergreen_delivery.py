"""Delivery constraints for the Evergreen artifacts.

These are the promises the deliverables make on their face — no author's words are reproduced,
compilation-sourced material is held, every claim opens at a character range in a file that
exists, and nothing claims human approval. Each is checked against the files as written, not
against the generator's own report.

Run: .venv/bin/python -B -m unittest tests.test_evergreen_delivery
"""
from pathlib import Path
import sys, json, re, unicodedata, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evergreen.deliver import classify_counterexample, locate_in_raw
from evergreen.output_gate import scan as gate_scan

OUT = ROOT / 'evergreen/deliverables'


def norm(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s or ''))


class Deliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((OUT / 'index.json').read_text())
        cls.manifest = json.loads((ROOT / 'evergreen/corpus_manifest_v2.json').read_text())
        cls.cand = {x['id']: x for x in json.loads(
            (ROOT / 'evergreen/principles/candidates.json').read_text())['items']}

    def test_no_author_sentence_is_reproduced(self):
        """Every candidate is direct_quote_allowed=false, so no evidence quote may appear in a
        delivered file."""
        delivered = ([p.read_text() for p in (OUT / 'cards').glob('*.svg')]
                     + [p.read_text() for p in (OUT / 'explainers').glob('*.md')]
                     + [(OUT / 'chapter_01.md').read_text()])
        blob = norm('\n'.join(delivered))
        leaked = [x['id'] for x in self.cand.values()
                  if len(norm(x['evidence_quote'])) >= 12
                  and norm(x['evidence_quote']) in blob]
        self.assertEqual(leaked, [], f'author wording reproduced verbatim: {leaked}')

    def test_compilation_sourced_material_is_held(self):
        secondary = {d['id'] for d in self.manifest['items'] if d['secondary_compilation']}
        held_ids = {h['principle_id'] for h in self.index['held_back_detail']}
        should_hold = {x['id'] for x in self.cand.values()
                       if x['source']['document_id'] in secondary}
        self.assertTrue(should_hold)
        self.assertEqual(should_hold - held_ids, set())
        shipped = ({c['principle_id'] for c in self.index['cards']}
                   | {e['principle_id'] for e in self.index['explainers']})
        self.assertEqual(shipped & should_hold, set())

    def test_the_named_compilation_is_classified_as_one(self):
        """剑客文摘合录 was the file singled out as needing human confirmation, and the original
        detector matched 摘录 and 合集 but not 文摘 or 合录."""
        hit = [d for d in self.manifest['items'] if '剑客文摘合录' in d['zip_path']]
        self.assertEqual(len(hit), 1)
        self.assertTrue(hit[0]['secondary_compilation'])

    def test_every_shipped_span_opens_in_a_file_on_disk(self):
        docs = {d['id']: d for d in self.manifest['items']}
        shipped = [c['principle_id'] for c in self.index['cards']]
        self.assertTrue(shipped)
        for pid in shipped:
            x = self.cand[pid]
            d = docs[x['source']['document_id']]
            raw = (ROOT / d['extracted_path']).read_text(encoding='utf-8', errors='replace')
            span = locate_in_raw(x['evidence_quote'], raw)
            self.assertIsNotNone(span, pid)
            self.assertEqual(norm(raw[span['start']:span['end']]),
                             norm(x['evidence_quote']), pid)

    def test_nothing_claims_human_approval(self):
        self.assertIn('pending_human_review', self.index['review_status'])
        for e in self.index['explainers'] + self.index['cards']:
            self.assertEqual(e['review'], 'pending_human_review')
        text = (OUT / 'chapter_01.md').read_text()
        self.assertIn('待人工审核', text)
        self.assertNotIn('human_approved', text)

    def test_output_gate_passes_on_every_delivered_file(self):
        for p in list(OUT.rglob('*.md')) + list(OUT.rglob('*.svg')):
            self.assertEqual(gate_scan(p.read_text()), [], f'{p} carries private data')

    def test_output_gate_would_block_a_local_path(self):
        """The gate is only meaningful if it fires; the corpus embeds a third party's home dir."""
        self.assertTrue(gate_scan('见 /Users/chenboyu/Documents/research/reads 的原文'))
        self.assertTrue(gate_scan('file:///Users/someone/a.md'))


class CounterexampleClassification(unittest.TestCase):
    """A 反例 has to be a case where the principle fails. One extracted field ended
    「属于符合该规律的交易」 — a conforming case filed as a counterexample."""

    def test_conforming_example_is_not_a_counterexample(self):
        self.assertEqual(classify_counterexample(
            '在利好尚未发酵时买入，在利好即将落地前卖出。', None,
            '原文提到在官方投票拆分时买入，公告后卖出，属于符合该规律的交易'),
            'conforming_example')

    def test_echoing_the_passage_is_not_a_counterexample(self):
        self.assertEqual(classify_counterexample(
            '在大幅下跌后开始震荡，震荡一个月以后可以开始慢慢买入。',
            '若跌破新低则应止损', '原文提到若跌破新低就止损'),
            'echoes_the_passage')

    def test_a_real_failure_case_is_kept(self):
        self.assertEqual(classify_counterexample(
            '重仓风险大，建议采用轻仓策略。', '若行情单边则轻仓收益有限',
            '2021 年 519 当天满仓合约的账户在半小时内归零'),
            'counterexample')

    def test_missing_field(self):
        self.assertEqual(classify_counterexample('任意原则', None, None), 'missing')

    def test_only_genuine_counterexamples_reach_the_explainers(self):
        index = json.loads((OUT / 'index.json').read_text())
        cand = {x['id']: x for x in json.loads(
            (ROOT / 'evergreen/principles/candidates.json').read_text())['items']}
        for e in index['explainers']:
            x = cand[e['principle_id']]
            self.assertEqual(classify_counterexample(
                x['statement'], x.get('invalidation'), x.get('counterexample')),
                'counterexample', e['principle_id'])
