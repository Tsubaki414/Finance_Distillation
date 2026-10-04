"""Donor roster -> persona registry -> exemplar retrieval at compose time.

live/donors/roster.json is the verified X donor roster (fd_donor_roster.json,
2026-10-04) reduced to what the pipeline needs: persona clusters with weighted
donors. A persona that names a donor_cluster gets its exemplar_accounts from
the roster. live/exemplars.py retrieves real donor posts (style only) for a
persona at compose time; COMPOSE sends them as style_exemplars with a rule
that their facts / numbers / phrases must not be used.
"""
import json
import tempfile
import unittest
from pathlib import Path

from live import compose, exemplars, qa_levels, registry
from tests.test_compose import Fake, GOOD_BODY, SOURCE


def roster():
    return json.loads(registry.DONOR_ROSTER.read_text())


class RosterTests(unittest.TestCase):
    def test_every_cluster_meets_the_donor_rule(self):
        data = roster()
        self.assertTrue(data['persona_clusters'])
        for name, cluster in data['persona_clusters'].items():
            donors = cluster['donors']
            self.assertGreaterEqual(len(donors), registry.MIN_EXEMPLARS, name)
            self.assertTrue(all(0 < d['weight'] <= registry.MAX_EXEMPLAR_WEIGHT for d in donors), name)
            self.assertAlmostEqual(sum(d['weight'] for d in donors), 1.0, places=2)
            self.assertTrue(all(data['donors'][d['handle'].lower()]['lang'] == cluster['lang'] for d in donors), name)
            self.assertTrue(all(data['donors'][d['handle'].lower()]['verified'] for d in donors), name)

    def test_roster_is_large_enough(self):
        verified = [d for d in roster()['donors'].values() if d['verified'] and d['donor_fit'] == 'voice']
        self.assertGreater(len(verified), 100)


class RegistryTests(unittest.TestCase):
    def test_persona_loads_donors_from_its_cluster(self):
        data = roster()
        for account, cluster in (('zh_macro', 'macro_zh'), ('zh_industry', 'zh_us_stock_commentary'),
                                 ('en_macro', 'macro_rates_en'), ('en_industry', 'industry_ai_capex')):
            persona = registry.persona_for_account(account)
            self.assertEqual(persona.raw['donor_cluster'], cluster)
            expected = tuple(d['handle'] for d in data['persona_clusters'][cluster]['donors'])
            self.assertEqual(persona.exemplar_accounts, expected)
            self.assertEqual(persona.donor_weights, {d['handle']: d['weight'] for d in data['persona_clusters'][cluster]['donors']})

    def test_cluster_language_must_match_persona(self):
        raw = json.loads((registry.PERSONAS / 'zh_macro.json').read_text())
        raw['donor_cluster'] = 'macro_rates_en'
        with self.assertRaises(registry.RegistryError):
            registry.validate_persona(registry.resolve_donors(raw), registry.load_post_types())

    def test_unknown_cluster_fails(self):
        raw = json.loads((registry.PERSONAS / 'zh_macro.json').read_text())
        raw['donor_cluster'] = 'nope'
        with self.assertRaises(registry.RegistryError):
            registry.resolve_donors(raw)

    def test_morris_has_no_donors(self):
        persona = registry.persona_for_account('en_morris_archive')
        self.assertNotIn('donor_cluster', persona.raw)


def posts_dir(rows):
    tmp = Path(tempfile.mkdtemp())
    for handle, posts in rows.items():
        (tmp / f'{handle.lower()}.jsonl').write_text(
            ''.join(json.dumps(p, ensure_ascii=False) + '\n' for p in posts))
    return tmp


ZH_POSTS = {
    'qinbafrank': [
        {'id': '1', 'text': '这次非农数据修订很关键：前两个月合计下修，市场对降息的预期又要重新定价。真正要看的是薪资增速和职位空缺。' * 2, 'lang': 'zh'},
        {'id': '2', 'text': '回复一下评论区', 'lang': 'zh', 'reply': True},
        {'id': '3', 'text': 'RT 别人的帖子 ' * 20, 'lang': 'zh', 'rt': True}],
    'PhyrexNi': [
        {'id': '4', 'text': '比特币今天的走势和美股科技股高度同步，流动性预期主导了价格，链上数据反而次要。' * 2, 'lang': 'zh'},
        {'id': '5', 'text': 'Fed funds futures now price two cuts; payrolls revisions matter more than the headline.' * 2, 'lang': 'en'}],
    'not_a_donor': [{'id': '6', 'text': '非农数据修订降息预期职位空缺' * 10, 'lang': 'zh'}],
}


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.dir = posts_dir(ZH_POSTS)
        self.persona = registry.persona_for_account('zh_macro')

    def test_retrieves_only_persona_donor_originals_in_language(self):
        got = exemplars.retrieve(self.persona, post_type='data_take', query='非农 修订 降息', k=3, posts_dir=self.dir)
        ids = [g['id'] for g in got]
        self.assertTrue(set(ids) <= {'1', '4'})
        self.assertEqual(ids[0], '1')  # topical overlap ranks first
        self.assertTrue(all(g['handle'] in self.persona.exemplar_accounts for g in got))

    def test_at_most_one_post_per_donor_and_deterministic(self):
        a = exemplars.retrieve(self.persona, query='非农', k=3, posts_dir=self.dir)
        b = exemplars.retrieve(self.persona, query='非农', k=3, posts_dir=self.dir)
        self.assertEqual(a, b)
        self.assertEqual(len({g['handle'] for g in a}), len(a))

    def test_no_posts_is_empty_not_an_error(self):
        self.assertEqual(exemplars.retrieve(self.persona, query='x', posts_dir=Path(tempfile.mkdtemp())), [])


class ComposeExemplarTests(unittest.TestCase):
    def setUp(self):
        self.dir = posts_dir({'wufantouzi': [{'id': '9', 'lang': 'zh', 'text': '存储周期这一轮的关键不是需求而是供给纪律，厂商宁可让价格涨也不扩产，这个判断要看资本开支指引。'}],
                              'Michael_QQQ2025': [{'id': '8', 'lang': 'zh', 'text': '美股科技财报季真正要看的不是营收，而是下一年的资本开支指引，这决定了整个链条的订单。'}]})

    def payload(self, fake):
        return json.loads(fake.messages[-1]['content'])

    def test_compose_sends_style_exemplars_with_a_no_copy_rule(self):
        fake = Recording()
        result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                        exemplars=True, exemplar_dir=self.dir)
        payload = self.payload(fake)
        self.assertTrue(payload['style_exemplars'])
        self.assertIn('style', payload['style_exemplar_rule'])
        self.assertEqual([e['id'] for e in result['exemplars']], [e['id'] for e in payload['style_exemplars']])
        self.assertTrue(all(e['handle'] in registry.persona_for_account('zh_industry').exemplar_accounts
                            for e in result['exemplars']))

    def test_exemplars_off_keeps_the_payload_unchanged(self):
        fake = Recording()
        compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take', exemplars=False)
        self.assertNotIn('style_exemplars', self.payload(fake))

    def test_copied_exemplar_phrase_is_a_soft_warning(self):
        copied = '厂商宁可让价格涨也不扩产，这个判断要看资本开支指引'
        fake = Recording(body=GOOD_BODY + copied + '。')
        result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                        exemplars=True, exemplar_dir=self.dir)
        finding = next(f for f in result['post_checks'] if f['code'] == 'exemplar_phrase_copied')
        self.assertEqual(finding['level'], 'soft')
        self.assertEqual(qa_levels.level({'code': 'exemplar_phrase_copied'}, frame_found=True), 'soft')


class VoiceVsContentRuleTests(unittest.TestCase):
    """Rule: donor exemplars teach voice and structure only; facts and numbers come from content units."""

    def setUp(self):
        self.dir = posts_dir({'wufantouzi': [{'id': '7', 'lang': 'zh', 'text': '存储涨价这一轮，三星的资本开支只增长了17%，供给纪律还在。'}]})

    def test_rule_text_is_sent_with_exemplars(self):
        for phrase in ('voice', 'structure only', 'every fact and number still comes from the units'):
            self.assertIn(phrase, compose.EXEMPLAR_RULE)

    def test_a_number_borrowed_from_an_exemplar_is_flagged_soft(self):
        # Policy 2026-10-04: untraceable numbers warn (soft) instead of blocking.
        fake = Recording(body=GOOD_BODY + '三星的资本开支只增长了17%。')
        result = compose.compose_source(SOURCE, 'zh_industry', fake, post_type='data_take',
                                        exemplars=True, exemplar_dir=self.dir)
        finding = next(f for f in result['post_checks'] if f['code'] == 'number_not_in_units')
        self.assertEqual(finding['level'], 'soft')
        self.assertIn('number_not_in_units', result['qa']['soft'])


class Recording(Fake):
    def __call__(self, stage, messages, max_tokens):
        self.messages = messages
        return super().__call__(stage, messages, max_tokens)


if __name__ == '__main__':
    unittest.main()
