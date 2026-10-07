"""P0 crypto pilot universes (zh_airdrop_diary, zh_airdrop_tutorial, en_airdrop_farmer).

Stub subscriptions must resolve to registry entries, stay out of the global intake,
and leave the three existing account universes untouched.
"""
import json
from pathlib import Path
import unittest

from live.account_sources import ROLES, admission, registry, source_key, universe, universes
from live.analysis_corpus import subscriptions

ROOT = Path(__file__).resolve().parents[1]
PILOTS = ('zh_airdrop_diary', 'zh_airdrop_tutorial', 'en_airdrop_farmer')
BASE = {'content_complete': True, 'source_type': 'web', 'platform': 'web',
        'published_at': '2026-10-06T12:00:00Z', 'fetched_at': '2026-10-06T12:30:00Z'}


class CryptoPilotUniverses(unittest.TestCase):
    def test_each_pilot_has_a_fetchable_core_feed(self):
        catalog = registry()
        for account_id in PILOTS:
            subs = universe(account_id)['subscriptions']
            self.assertTrue(all(s['role'] in ROLES and s['source_id'] in catalog for s in subs), account_id)
            core = [s for s in subs if s['role'] == 'CORE' and s['enabled']]
            self.assertTrue(any(catalog[s['source_id']].get('adapter') == 'feed' for s in core), account_id)

    def test_pilot_sources_stay_out_of_global_intake(self):
        ids = {s['source_id'] for u in universes() if u['account_id'] in PILOTS for s in u['subscriptions']}
        catalog = registry()
        self.assertTrue(all(catalog[i].get('enabled') is False for i in ids))
        handles, feeds = subscriptions()
        self.assertFalse(ids & ({'x_' + h for h in handles} | {f['id'] for f in feeds}))

    def test_existing_universes_unchanged(self):
        rows = {u['account_id']: u for u in universes()}
        self.assertEqual([s['id'] for s in rows['en_morris_archive']['subscriptions']], ['x_Morris_LT'])
        pilot_ids = {s['source_id'] for a in PILOTS for s in rows[a]['subscriptions']}
        for account_id in ('en_morris_archive', 'zh_macro', 'zh_industry'):
            self.assertNotIn('pilot', rows[account_id])
            self.assertFalse(pilot_ids & {s['source_id'] for s in rows[account_id]['subscriptions']})
        monitor = json.loads((ROOT / 'live/account_monitor.json').read_text())
        self.assertFalse(set(PILOTS) & set(monitor['accounts']))

    def test_config_stubs_match_accounts(self):
        from live.account_intelligence import account
        from live import registry as persona_registry
        configs = json.loads((ROOT / 'live/pilot_account_configs.json').read_text())['accounts']
        self.assertEqual([c['account_id'] for c in configs], list(PILOTS))
        types = json.loads((ROOT / 'live/post_types.json').read_text())['post_types']
        for c in configs:
            self.assertEqual(c['lang'], account(c['account_id'])['language'])
            self.assertEqual(c['source_universe_id'], c['account_id'])
            self.assertTrue(set(c['post_type_mix']) <= set(types))
            self.assertAlmostEqual(sum(c['post_type_mix'].values()), 1.0)
            self.assertNotIn('text', json.dumps(c['exemplar_accounts']))
            persona_registry.validate_persona(c, {'post_types': types})

    def test_link_hosts_resolve_odaily_articles(self):
        row = {'source_id': 'crypto_odaily_post', 'url': 'https://www.odaily.news/zh-CN/post/5200000'}
        self.assertEqual(source_key(row), 'crypto_odaily_post')
        with self.assertRaises(ValueError):
            source_key({'source_id': 'crypto_odaily_post', 'url': 'https://example.com/post/1'})

    def test_admission_both_languages(self):
        zh = {**BASE, 'id': 'od-1', 'source_id': 'crypto_odaily_post', 'source_language': 'zh',
              'url': 'https://www.odaily.news/zh-CN/post/5200000', 'title': '项目发币在即，积分怎么算',
              'original_text': '项目宣布将于下周 TGE，积分快照已完成，用户可查询额度。'}
        en = {**BASE, 'id': 'ai-1', 'source_id': 'crypto_airdrops_io', 'source_language': 'en',
              'url': 'https://airdrops.io/some-project/', 'title': 'Some Project airdrop guide',
              'original_text': 'Some Project confirmed a points season and a testnet airdrop for early users.'}
        # Pilots carry allow_same_language (user decision 2026-10-07): both languages admit.
        for account_id in PILOTS:
            self.assertTrue(admission(account_id, zh)['admitted'], account_id)
            self.assertTrue(admission(account_id, en)['admitted'], account_id)

    def test_same_language_sources_are_candidate_roles(self):
        from live.account_intelligence import account
        catalog = registry()
        for account_id in PILOTS:
            lang = account(account_id)['language']
            self.assertIs(account(account_id).get('allow_same_language'), True)
            roles = {s['source_id']: s['role'] for s in universe(account_id)['subscriptions']}
            core = [sid for sid, r in roles.items() if r == 'CORE']
            self.assertTrue(core and all(catalog[sid]['lang'] == lang for sid in core), account_id)
            cross = [sid for sid, r in roles.items() if catalog[sid].get('lang') not in (None, lang)
                     and r not in ('EVENT_ONLY', 'WATCHLIST')]
            self.assertTrue(cross and all(roles[sid] == 'SECONDARY' for sid in cross), account_id)
        for account_id in ('zh_airdrop_diary', 'zh_airdrop_tutorial'):
            roles = {s['source_id']: s['role'] for s in universe(account_id)['subscriptions']}
            self.assertEqual(roles['crypto_wscn_blockchain'], 'SECONDARY')

    def test_wscn_blockchain_flash_refresh_without_network(self):
        from unittest import mock
        from live.account_sources import fetch_flash_json
        body = json.dumps({'data': {'items': [
            {'id': 1, 'content_text': '【某项目宣布空投】某项目宣布第二季积分快照完成，空投申领将于下周开放。', 'display_time': 1791100000,
             'uri': 'https://wallstreetcn.com/livenews/1'},
            {'id': 2, 'content_text': '太短', 'display_time': 1791100000}]}})
        config = {**registry()['crypto_wscn_blockchain'], 'id': 'crypto_wscn_blockchain'}
        rows, error = fetch_flash_json(config, 5, transport=lambda url, headers: (200, body))
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source_language'], 'zh')
        self.assertEqual(source_key(rows[0]), 'crypto_wscn_blockchain')
        self.assertTrue(admission('zh_airdrop_diary', {**rows[0]})['admitted'])
        with mock.patch('live.adapters.flashes.OUTLETS', {}):  # global flash outlets are not consulted
            self.assertEqual(len(fetch_flash_json(config, 5, transport=lambda u, h: (200, body))[0]), 1)

if __name__ == '__main__':
    unittest.main()
