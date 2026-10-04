import json
import tempfile
import unittest
from pathlib import Path
from live import exemplars, registry
from tests.test_voice_cards import FIX

class AllExemplarsTests(unittest.TestCase):
    def test_all_ten_clusters_have_personas_and_donors(self):
        personas = registry.load_personas()
        clusters = registry.load_donor_roster()['persona_clusters']
        self.assertEqual({p.raw.get('donor_cluster') for p in personas.values()} - {None}, set(clusters))
        for p in personas.values():
            if p.raw.get('donor_cluster'):
                self.assertGreaterEqual(len(p.donor_weights),3)
                self.assertTrue(p.voice_card)
                self.assertFalse(p.publishable)

    def test_each_cluster_retrieves_same_type_first_and_falls_back(self):
        for name,c in registry.load_donor_roster()['persona_clusters'].items():
            with self.subTest(cluster=name), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); posts=root/'posts'; tags=root/'tags'; posts.mkdir(); tags.mkdir()
                p=next(p for p in registry.load_personas().values() if p.raw.get('donor_cluster')==name)
                text='利率变化需要更多证据支持，市场流动性正在改变，投资者需要关注数据背后的机制。'*3 if c['lang']=='zh' else 'Rates and liquidity require careful evidence before drawing conclusions about the next market cycle. '*3
                for h in list(p.donor_weights)[:3]:
                    (posts/f'{h.lower()}.json').write_text(json.dumps([{'id':'a','text':text,'lang':c['lang']},{'id':'z','text':text,'lang':c['lang']},{'id':'ad','text':text,'lang':c['lang']}]))
                    (tags/f'{h.lower()}.json').write_text(json.dumps({'a':{'post_type':'hot_take'},'z':{'post_type':'data_take'},'ad':{'post_type':'ad'}}))
                got=exemplars.retrieve(p,post_type='data_take',posts_dir=posts,tags_dir=tags)
                self.assertEqual(len(got),3)
                self.assertTrue(all(x['id']=='z' for x in got))
                self.assertEqual(got,exemplars.retrieve(p,post_type='data_take',posts_dir=posts,tags_dir=tags))
                self.assertEqual(len(exemplars.retrieve(p,post_type='view_relay',posts_dir=posts,tags_dir=tags)),3)

    def test_new_accounts_are_disabled(self):
        accounts=json.loads(Path('live/accounts.json').read_text())['accounts']
        for name in ['single_stock_deepdive_en','trading_shortterm','market_data_charts','investing_philosophy','crypto_macro_en','crypto_macro_zh']:
            a=next(a for a in accounts if a['id']==name)
            self.assertFalse(a['enabled'])
            self.assertEqual(a['binding_status'],'logical_account_only')

class RunnerTests(unittest.TestCase):
    def test_offline_runner_uses_tagged_store_and_reports_all_ten(self):
        from live.content_store import ContentStore
        from scripts.voice_relay_check import main
        import copy
        import sys
        import shlex
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=ContentStore(root/'store')
            base=json.loads((FIX/'store_record.json').read_text())
            tags={}
            for i,name in enumerate(registry.load_donor_roster()['persona_clusters']):
                row=copy.deepcopy(base); uid=f'synthetic-{i}'
                row['unit_id']=row['unit']['unit_id']=uid
                row['source']['id']=uid; row['source']['source_hash']=uid
                with store.path.open('a') as f: f.write(json.dumps(row)+'\n')
                store._rows[uid]=row
                tags[uid]={name:{'verdict':'relevant','confidence':.95}}
            # A high-confidence but irrelevant extra source must never be selected.
            bad=copy.deepcopy(base); bad['unit_id']='off-beat'; bad['source']['id']='off-beat'
            with store.path.open('a') as f: f.write(json.dumps(bad)+'\n')
            store.set_persona_tags(tags)
            cmd=shlex.join([sys.executable,str(FIX/'fake_judge.py')])
            main(['--accounts','all','--n','2','--store',str(store.root),'--output',str(root/'out'),'--judge-cmd',cmd,'--posts-dir',str(FIX/'posts'),'--tags-dir',str(FIX/'tags')])
            results=json.loads((root/'out/results.json').read_text())
            self.assertEqual(len(results),10)
            for row in results:
                self.assertEqual(row['status'],'completed',row)
                self.assertEqual(len(row['drafts']),1,row)
                d=row['drafts'][0]
                self.assertEqual(d['judge']['voice_match'],3,row)
                self.assertEqual(d['mode'],'offline_fake')
                self.assertFalse(d['compose']['publishable'])
                self.assertNotEqual(d['source']['id'],'off-beat')
            self.assertIn('Advisory only',(root/'out/results.md').read_text())

    def test_empty_store_and_failed_judge_remain_advisory(self):
        from scripts.voice_relay_check import run,judge
        from live.content_store import ContentStore
        with tempfile.TemporaryDirectory() as tmp:
            rows=run(ContentStore(Path(tmp)/'store'),Path(tmp)/'out')
            self.assertEqual(len(rows),10)
            self.assertTrue(all(r['status']=='no_suitable_tagged_units' for r in rows))
        self.assertEqual(judge('nonexistent-voice-test-judge',{})['status'],'unjudged')

class OperationalAccountsTests(unittest.TestCase):
    def test_disabled_logical_accounts_are_opt_in_for_operations(self):
        from live.distillation import accounts_from_file
        active=accounts_from_file()
        self.assertTrue(all(a['enabled'] for a in active))
        all_accounts=accounts_from_file(include_disabled=True)
        self.assertEqual(len(all_accounts),len(active)+6)
        self.assertTrue(all(a['binding_status']=='logical_account_only' for a in all_accounts))

    def test_registry_without_cards_preserves_historical_payload(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            for p in registry.PERSONAS.glob('*.json'):
                shutil.copy(p,tmp)
            personas=registry.load_personas(tmp)
            self.assertTrue(all(p.voice_card=={} for p in personas.values()))
            self.assertEqual(len(personas),11)
