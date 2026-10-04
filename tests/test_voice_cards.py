import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from live import registry, compose
from tests.test_donor_exemplars import Recording
from tests.test_compose import SOURCE

FIX = Path(__file__).parent / 'fixtures' / 'voice'

class VoiceTests(unittest.TestCase):
    def test_weighted_deterministic_cards_and_exclusions(self):
        from live.voice_cards import build_cards
        cards = build_cards(FIX/'posts', FIX/'tags', FIX/'roster.json')
        self.assertEqual(cards, build_cards(FIX/'posts', FIX/'tags', FIX/'roster.json'))
        c = cards['sample']
        self.assertEqual(c['sample']['posts'], 6)
        self.assertEqual(set(c['sample']['donors']), {'alpha', 'beta'})
        self.assertAlmostEqual(c['hooks']['question']['share'], 1/3)
        self.assertAlmostEqual(c['data_opinion']['data_share'], 1/3)
        self.assertEqual(c['sentence_length']['unit'], 'words')
        self.assertTrue(c['signature_phrasing'])
        self.assertTrue(all(x['do_not_copy'] for x in c['signature_phrasing']))
        for kind in ['do', 'dont']:
            self.assertTrue(c[kind])
            for rule in c[kind]:
                self.assertTrue(2 <= len(rule['evidence']) <= 4)
                for e in rule['evidence']:
                    self.assertLessEqual(len(e['text']), 140)
                    self.assertIn(e['handle'], ['alpha','beta'])
                    self.assertNotEqual(e['id'], '3')

    def test_registry_card_and_compact_compose_payload(self):
        persona = registry.persona_for_account('zh_industry')
        self.assertTrue(persona.voice_card)
        fake = Recording()
        compose.compose_source(SOURCE, persona.account_id, fake, post_type='data_take', exemplars=False)
        summary = json.loads(fake.messages[-1]['content'])['persona']['voice_card']
        self.assertIn('hooks', summary)
        self.assertNotIn('cadence', summary)
        self.assertNotIn('evidence', json.dumps(summary))
        self.assertNotIn('signature_phrasing', summary)

    def test_external_judge_tolerant_and_advisory(self):
        from scripts.voice_relay_check import judge
        result = judge("python3 -c 'import sys; sys.stdin.read(); print(\"preface ```json\\n{\\\"judgment_first\\\":4,\\\"voice_match\\\":3,\\\"reason\\\":\\\"test\\\"}\\n```\")'", {'draft':'x'})
        self.assertEqual(result['judgment_first'],4)
        self.assertEqual(result['voice_match'],3)
        self.assertEqual(judge("python3 -c 'print(\"bad\")'", {})['status'], 'unjudged')

class VoiceEdgeTests(unittest.TestCase):
    def test_weights_are_per_donor_not_per_post(self):
        from live.voice_cards import build_cards
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'voice'; shutil.copytree(FIX,root)
            beta=json.loads((root/'posts/beta.json').read_text())[:1]
            beta[0]['text']='The evidence supports a measured claim. This is a synthetic style observation.'
            (root/'posts/beta.json').write_text(json.dumps(beta))
            c=build_cards(root/'posts',root/'tags',root/'roster.json')['sample']
            self.assertAlmostEqual(c['hooks']['question']['share'],.25)
            self.assertAlmostEqual(c['hooks']['number-led']['share'],.25)
            self.assertAlmostEqual(c['hooks']['claim-led']['share'],.5)
            self.assertAlmostEqual(c['thread_rate'],.25)
            self.assertAlmostEqual(c['emoji_rate'],0)
            self.assertEqual(c['cadence']['active_hours_utc'],{'12':1.0})

    def test_hook_types_and_missing_timestamps(self):
        from live.voice_cards import hook, build_cards
        for line,kind in [('BREAKING: new release','breaking'),('🧵 Rates moved','emoji-led'),('“Liquidity matters”','quote'),('为什么需要证据？','question'),('42 basis points','number-led'),('Evidence matters','claim-led')]:
            self.assertEqual(hook(line),kind)
        roster=json.loads((FIX/'roster.json').read_text())
        roster['persona_clusters']['empty']={'lang':'zh','donors':[],'bench':['alpha']}
        c=build_cards(FIX/'posts',FIX/'tags',roster)['empty']
        self.assertIsNone(c['cadence']['posts_per_day_median'])
        self.assertIsNone(c['sentence_length']['median'])
        self.assertEqual(c['hooks']['question']['first_lines'],[])

    def test_signature_evidence_cannot_enter_summary(self):
        from live.voice_cards import build_cards,compact_summary
        c=build_cards(FIX/'posts',FIX/'tags',FIX/'roster.json')['sample']
        summary=json.dumps(compact_summary(c))
        for marker in c['signature_phrasing']:
            self.assertNotIn(marker['phrase'],summary)
        for e in c['do'][0]['evidence']:
            self.assertNotIn(e['text'],summary)

    def test_card_cli_writes_each_cluster_and_markdown(self):
        from scripts.build_voice_cards import main
        with tempfile.TemporaryDirectory() as tmp:
            main(['--posts-dir',str(FIX/'posts'),'--tags-dir',str(FIX/'tags'),'--roster',str(FIX/'roster.json'),'--out',tmp])
            self.assertTrue((Path(tmp)/'sample.json').exists())
            self.assertIn('sample',(Path(tmp)/'README.md').read_text())

class EvidencePacketTests(unittest.TestCase):
    def test_packet_preserves_store_paraphrase_restrictions(self):
        from scripts.voice_relay_check import evidence_source,StoreClient
        from live.content_units import extract
        row=json.loads((FIX/'store_record.json').read_text())
        row['source']['source_id']='bls_api'  # original registry tier A
        row['unit'].update(no_reproduction=True,quote_allowed=False)
        source,units=evidence_source([row])
        self.assertTrue(source['no_reproduction'])
        extracted=extract(source,StoreClient(units,'en'),licence_tier='A')
        self.assertTrue(all(u['licence_tier']=='B' and u['quote_allowed'] is False for u in extracted['units']))

    def test_data_opinion_ratio_is_explicit(self):
        from live.voice_cards import build_cards
        c=build_cards(FIX/'posts',FIX/'tags',FIX/'roster.json')['sample']
        self.assertAlmostEqual(c['data_opinion']['data_to_opinion'],.5)

class TagAndPromotionTests(unittest.TestCase):
    def test_explicit_promotion_flags_and_subscription_ads_are_excluded(self):
        from live.voice_cards import excluded
        self.assertTrue(excluded({'text':'Subscribe now with my discount code for a paid subscription.'},{}))
        self.assertTrue(excluded({'text':'Synthetic promotion'}, {'is_promotion':True}))
        self.assertFalse(excluded({'text':'Ad spending rose as demand improved.'}, {'post_type':'data_take'}))

    def test_compose_passes_explicit_tags_directory(self):
        with patch('live.compose.exemplar_store.retrieve',return_value=[]) as retrieve:
            compose.compose_source(SOURCE,'zh_industry',Recording(),post_type='data_take',
                                   exemplar_tags_dir=FIX/'tags')
        self.assertEqual(retrieve.call_args.kwargs['tags_dir'],FIX/'tags')

class CombinedReportTests(unittest.TestCase):
    def test_readme_combines_all_card_dimensions_and_provenance(self):
        from live.voice_cards import build_cards,write_cards
        cards=build_cards(FIX/'posts',FIX/'tags',FIX/'roster.json')
        with tempfile.TemporaryDirectory() as tmp:
            write_cards(cards,tmp)
            report=(Path(tmp)/'README.md').read_text()
            for field in ('Cadence','Signatures','Post type mix','Media','First lines','@alpha'):
                self.assertIn(field,report)
