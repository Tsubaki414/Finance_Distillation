#!/usr/bin/env python3
"""Persona factory for the daily-drafting accounts (Oct 7: the 20 mains; Oct 8: + 6 spares + 10 new = 36, the gated
roster of live/fd_accounts.py - FD_ACCOUNTS_EXTRA=0 / FD_ACCOUNTS_NEW=0 leave a group out).

For every account it makes sure the compose chain has what it needs, with no model calls:
  1. donor cluster  roster.persona_clusters['acct_<id>'] from the row's donors (spares / new, Oct 8) or
                    /workspace/x/bios/plan_crypto.json main (5 donors, equal weight; every donor must be a verified
                    voice donor of the account language). New-account donors (rows with donor_evidence: verified
                    active on twitter241, aggregates only) are added to the roster first.
  2. persona file   live/personas/<id>.json (new accounts only; existing personas are never rewritten)
  3. emotion tier   live/emotion_tiers.json personas[<id>] (crypto may be emotional, zh restrained = low)
  4. habit card     live/personas/posting_habits/<id>.json (post-type mix, length per type, topics, posting
                    hours) + language habits card (aggregates only; built from the local donor corpus)
  5. universe       live/store/fd20/universes.json: retrieval beats (crypto accounts: own lanes crypto_meme / perp /
                    defi / airdrop / onchain first, Oct 7), the A/B sources that actually feed them
                    (unit counts, last 45 days), the account-scoped X sources, donor post counts and the account's
                    angle mix (live/angles.py)

Donor merge (Oct 7): live/fd20_donor_merge.json adds adopted donors (Mango Labs following graph + 1-hop gap
fill) to each acct_<id> cluster and lists the account's X sources. Merged donors must be same-language, have
>= MERGE_MIN_POSTS deep-scraped originals, promo_share <= MERGE_MAX_PROMO, and sit in at most
MERGE_MAX_ACCOUNTS clusters. The cluster's base donors keep their relative weights inside BASE_SHARE; merged
donors split the rest equally. Re-running is idempotent (merged entries carry 'merged': <version>).

X sources of spare / new rows come from the row's x_sources (CORE = its donors) and are registered tier B in
live/source_licence.json (individual analysts, paraphrase only) when missing.

Cards and the universe file are aggregates, but they are learned from donor text: they stay out of git
(.gitignore). Re-run after a donor backfill to rebuild cards (--rebuild-cards also rebuilds existing accounts'
cards).

  python scripts/persona_factory.py [--accounts a,b] [--rebuild-cards] [--dry-run]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live import angles, fd_accounts, registry  # noqa: E402
from live.jev_front import LANE_BEATS  # noqa: E402

CONFIG = ROOT / 'live' / 'fd20_accounts.json'   # read through live/fd_accounts.rows (36-account roster)
LICENCE = ROOT / 'live' / 'source_licence.json'
PLAN = Path('/workspace/x/bios/plan_crypto.json')
ROSTER = ROOT / 'live' / 'donors' / 'roster.json'
PERSONAS = ROOT / 'live' / 'personas'
EMOTION = ROOT / 'live' / 'emotion_tiers.json'
ACCOUNTS = ROOT / 'live' / 'accounts.json'
UNIVERSES = ROOT / 'live' / 'store' / 'fd20' / 'universes.json'
POSTS = ROOT / 'live' / 'donors' / 'posts'
MERGE = ROOT / 'live' / 'fd20_donor_merge.json'
MERGE_MIN_POSTS, MERGE_MAX_PROMO, MERGE_MAX_ACCOUNTS, BASE_SHARE = 150, 0.25, 3, 0.5
MIN_DONORS = 3
POST_TYPE_MIX = {'judgment_take': 0.4, 'contrarian_take': 0.2, 'data_take': 0.1, 'mechanism_explainer': 0.15,
                 'view_relay': 0.15}
BANNED = ['claimed_employer', 'claimed_positions', 'claimed_returns', 'price_targets_and_trade_calls',
          'source_author_experience', 'template_phrases', 'copied_signature_phrases', 'advertising',
          'invented_credentials']
VOICE = {'zh': {'draft': True, 'note': 'fd20 factory placeholder; voice comes from the donor cluster cards. Not approved.',
                'sentence_len_band': [12, 30], 'first_person_rate': 'low', 'jargon_density': 'mid', 'humor': 'none',
                'emoji': False},
         'en': {'draft': True, 'note': 'fd20 factory placeholder; voice comes from the donor cluster cards. Not approved.',
                'sentence_len_band': [10, 26], 'first_person_rate': 'low', 'jargon_density': 'mid', 'humor': 'none',
                'emoji': False}}


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def post_count(handle):
    path = POSTS / f'{handle.lower()}.jsonl'
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text().split('\n'):
        try:
            p = json.loads(line)
        except ValueError:
            continue
        n += bool(p.get('text')) and not p.get('rt')
    return n


def ensure_cluster(roster, account, donors):
    """acct_<id> cluster from the plan donors (existing clusters are kept as they are)."""
    name = 'acct_' + account['id']
    if name in roster['persona_clusters']:
        return name, False
    ok = []
    for h in donors:
        info = roster['donors'].get(h.lower()) or {}
        if info.get('verified') and info.get('donor_fit') == 'voice' and info.get('lang') == account['lang'] and post_count(h):
            ok.append(h)
    if len(ok) < max(MIN_DONORS, registry.MIN_EXEMPLARS):
        raise SystemExit(f'{account["id"]}: only {len(ok)} usable donors ({ok}); need {registry.MIN_EXEMPLARS}')
    w = round(1.0 / len(ok), 4)
    roster['persona_clusters'][name] = {
        'lang': account['lang'], 'donors': [{'handle': h, 'weight': w} for h in ok],
        'origin': ('fd20 persona_factory 2026-10-07 from plan_crypto.json main (equal weights)' if account.get('group', 'main') == 'main'
                   else f"persona_factory 2026-10-08 from the {account['group']} account row donors (equal weights)"),
        # the topic cluster whose content tags feed this account (its primary retrieval beat)
        'previous_cluster': account['retrieval_beats'][0]}
    return name, True


def ensure_roster_donors(roster, account):
    """Oct 8: a new account's donors (row donor_evidence: twitter241-verified, active in the last 30 days) become
    roster voice donors of the account language. Existing roster entries are left as they are. True when changed."""
    changed = False
    for h, ev in (account.get('donor_evidence') or {}).items():
        if h.lower() in roster['donors']:
            continue
        roster['donors'][h.lower()] = {
            'handle': h, 'lang': account['lang'], 'category': (account.get('retrieval_beats') or ['?'])[0],
            'persona_cluster': 'acct_' + account['id'], 'verified': True, 'donor_fit': 'voice', 'promo_heavy': False,
            'followers': ev.get('followers'), 'latest_post': ev.get('last_post'),
            'posts_per_day': ev.get('posts_per_day_30d'), 'promo_share': ev.get('promo_share_regex'),
            'added': '2026-10-08', 'origin': f"accounts36 slate: {account['id']} donor",
            'verify_note': (f"{account.get('donors_checked') or 'twitter241'}; {ev.get('originals_scraped')} originals "
                            f"scraped; promo_share = regex share of the 40 newest originals")}
        changed = True
    return changed


def register_x_sources(accounts):
    """Oct 8: the spare / new rows' X sources (row x_sources) get a tier B licence entry when they have none
    (individual analysts: paraphrase with attribution, same basis as the fd20 account-scoped sources). Returns the
    handles added."""
    raw = load_json(LICENCE)
    added = []
    for a in accounts:
        for role in ('CORE', 'SECONDARY'):
            for h in (a.get('x_sources') or {}).get(role) or []:
                sid = 'x_' + h
                if sid in raw['tiers']:
                    continue
                raw['tiers'][sid] = {'tier': 'B', 'basis': f"X analyst posts ({a['group']} account-scoped source, 2026-10-08)",
                                     'aliases': [h]}
                added.append(h)
    if added:
        LICENCE.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + '\n')
    return added


def x_sources_of(account, merge):
    """{'CORE': [...], 'SECONDARY': [...]}: the merge file's (main accounts) or the row's own (spare / new)."""
    merged = ((merge.get('accounts') or {}).get(account['id']) or {}).get('x_sources')
    return merged or account.get('x_sources') or {}


def merge_cluster(roster, account, merge):
    """Add the merge file's adopted donors to acct_<id>; True when the cluster changed."""
    adds = (merge.get('accounts') or {}).get(account['id'], {}).get('donors') or []
    cluster = roster['persona_clusters'].get('acct_' + account['id'])
    if cluster is None:
        return False
    base = [d for d in cluster['donors'] if not d.get('merged')]
    usage = collections.Counter(d['handle'].lower() for name, c in roster['persona_clusters'].items()
                                if name.startswith('acct_') and name != 'acct_' + account['id']
                                for d in c['donors'])
    have = {d['handle'].lower() for d in base}
    new = []
    meta_of = merge.get('donors') or {}
    for h in adds:
        meta = meta_of.get(h)
        if meta is None:   # account list names a donor with no donors{} entry: skip it, don't sink the nightly
            print(f'WARN {account["id"]}: merged donor {h} has no donors{{}} meta in {MERGE.name}; skipped',
                  file=sys.stderr)
            continue
        if meta['lang'] != account['lang']:
            raise SystemExit(f'{account["id"]}: merged donor {h} is {meta["lang"]}, account is {account["lang"]}')
        if meta['promo_share'] > MERGE_MAX_PROMO:
            raise SystemExit(f'{account["id"]}: merged donor {h} promo_share {meta["promo_share"]} > {MERGE_MAX_PROMO}')
        if post_count(h) < MERGE_MIN_POSTS:
            raise SystemExit(f'{account["id"]}: merged donor {h} has {post_count(h)} originals < {MERGE_MIN_POSTS}')
        if usage[h.lower()] + 1 > MERGE_MAX_ACCOUNTS:
            raise SystemExit(f'{account["id"]}: merged donor {h} would sit in more than {MERGE_MAX_ACCOUNTS} accounts')
        if h.lower() in have:
            continue
        info = roster['donors'].setdefault(h.lower(), {'handle': h, 'added': merge['version']})
        info.update({'lang': meta['lang'], 'category': meta['category'], 'verified': True, 'donor_fit': 'voice',
                     'promo_heavy': False, 'followers': meta.get('followers'), 'promo_share': meta['promo_share'],
                     'origin': meta['origin'], 'verify_note': meta.get('verify_note')})
        info.setdefault('persona_cluster', 'acct_' + account['id'])
        new.append(h)
    total = sum(d['weight'] for d in base) or 1.0
    share = BASE_SHARE if new else 1.0
    donors = [{**d, 'weight': round(d['weight'] / total * share, 4)} for d in base]
    donors += [{'handle': h, 'weight': round((1 - BASE_SHARE) / len(new), 4), 'merged': merge['version'],
                'why': meta_of[h]['origin']} for h in new]
    if donors == cluster['donors']:
        return False
    cluster['donors'] = donors
    cluster['merge'] = {'version': merge['version'], 'base_share': share, 'added': new}
    return True


def sync_accounts(roster, merged):
    """live/accounts.json mirrors the donor list of the legacy accounts' clusters; keep it equal after a merge."""
    raw = load_json(ACCOUNTS)
    changed = False
    for acc in raw['accounts']:
        dc = acc.get('donor_cluster') or {}
        if dc.get('cluster') in merged:
            cluster = roster['persona_clusters'][dc['cluster']]
            dc['donors'] = [{k: d[k] for k in ('handle', 'weight', 'why', 'merged') if k in d} for d in cluster['donors']]
            dc['merge'] = cluster['merge']
            changed = True
    if changed:
        write_json(ACCOUNTS, raw)


def persona_raw(account, cluster):
    return {
        'persona_id': account['id'], 'version': '1', 'status': 'draft', 'account_id': account['id'],
        'lang': account['lang'],
        'focus': {'lang': account['lang'], 'description': account['focus']},
        'stance': account['stance'],
        'voice': dict(VOICE[account['lang']]),
        'post_type_mix': dict(POST_TYPE_MIX),
        'source_affinity': {'licence_tiers': ['A', 'B']},
        'donor_cluster': cluster,
        'exemplar_retrieval': {'enabled': True, 'k': 4, 'use': 'style only; facts, numbers and phrases never'},
        'banned': list(BANNED),
        'display': {'name': account['name'], 'beat': account['beat']},
        'lineage': ({'created_by': 'scripts/persona_factory.py', 'created': '2026-10-07',
                     'from': 'FD_accounts_final_v2.xlsx main row %d; plan_crypto.json donors' % account['no']}
                    if account.get('group', 'main') == 'main' else
                    {'created_by': 'scripts/persona_factory.py', 'created': '2026-10-08', 'status': account.get('status'),
                     'from': f"account no {account['no']} ({account['group']}): live/fd_accounts_{'extra' if account['group'] == 'spare' else 'new'}.json donors"}),
    }


def source_universe(store, beats, max_age_days=45, top=12):
    from live.retrieval import units_for_persona
    by_source, units = collections.Counter(), 0
    names = {}
    for beat in beats:
        for r in units_for_persona(store, beat, max_age_days=max_age_days):
            if r.get('licence_tier') not in ('A', 'B'):
                continue
            src = r.get('source') or {}
            sid = src.get('source_id') or src.get('id')
            by_source[sid] += 1
            names.setdefault(sid, src.get('publisher') or src.get('author_name'))
            units += 1
    return {'units_45d': units,
            'sources': [{'source_id': s, 'publisher': names.get(s), 'units': n,
                         'tier': registry.source_licence_tier(s)} for s, n in by_source.most_common(top)]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--accounts')
    ap.add_argument('--rebuild-cards', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    config = fd_accounts.rows(CONFIG)
    plan = {a['id']: a for a in load_json(PLAN)['main']} if PLAN.exists() else {}
    only = set(args.accounts.split(',')) if args.accounts else None
    roster = load_json(ROSTER)
    merge = load_json(MERGE) if MERGE.exists() else {}
    merged = set()
    emotion = load_json(EMOTION)
    report = {}
    changed_roster = changed_emotion = False
    for account in config:
        if only and account['id'] not in only:
            continue
        aid = account['id']
        row = {'existing': bool(account.get('existing'))}
        donors = account.get('donors') or (plan.get(aid) or {}).get('donors') or []
        persona_path = PERSONAS / f'{aid}.json'
        if account.get('donor_evidence'):
            changed_roster |= ensure_roster_donors(roster, account)
        if not account.get('existing'):
            cluster, made = ensure_cluster(roster, account, donors)
            changed_roster |= made
            row['cluster'] = cluster + (' (new)' if made else '')
            if not persona_path.exists():
                raw = persona_raw(account, cluster)
                registry.validate_persona(registry.resolve_donors(raw, roster), registry.load_post_types())
                if not args.dry_run:
                    write_json(persona_path, raw)
                row['persona'] = 'written'
            else:
                row['persona'] = 'kept'
        else:
            row['persona'] = 'existing'
        if merge and merge_cluster(roster, account, merge):
            changed_roster = True
            merged.add('acct_' + aid)
            row['merged'] = ((merge.get('accounts') or {}).get(aid) or {}).get('donors') or []
        if emotion['personas'].get(aid) != account['emotion_tier']:
            if aid not in emotion['personas']:   # never retune an existing account's tier here
                emotion['personas'][aid] = account['emotion_tier']
                changed_emotion = True
        report[aid] = row
    if not args.dry_run:
        added = register_x_sources([a for a in config if a['id'] in report and a.get('group', 'main') != 'main'])
        if added:
            print('x sources registered tier B:', ', '.join(added))
        if changed_roster:
            ROSTER.write_text(json.dumps(roster, ensure_ascii=False, indent=1) + "\n")   # roster layout: indent 1
        if changed_emotion:
            write_json(EMOTION, emotion)
        sync_accounts(roster, merged)
    # offline (deterministic, no LLM) voice cards for clusters that have none yet
    missing = [c for c in {'acct_' + a['id'] for a in config if a['id'] in report}
               if c in roster['persona_clusters'] and (c in merged or not (PERSONAS / 'voice_cards' / f'{c}.json').exists())]
    if missing and not args.dry_run:
        from scripts.build_voice_cards import main as build_voice_cards
        build_voice_cards(['--posts-dir', str(POSTS), '--tags-dir', str(ROOT / 'live' / 'donors' / 'tags'),
                           '--clusters', ','.join(sorted(missing)), '--no-llm'])
    # cards + universe need the persona registry with the new files
    from live import posting_habits as ph, language_habits as lh
    from live.content_store import ContentStore
    personas = registry.load_personas()
    store = ContentStore()
    universes = load_json(UNIVERSES) if UNIVERSES.exists() else {}
    for account in config:
        aid = account['id']
        if aid not in report:
            continue
        persona = registry.persona_for_account(aid, personas)
        weights = persona.donor_weights
        row = report[aid]
        row['donors'] = {h: post_count(h) for h in weights}
        row['donors_ge_150'] = sum(n >= 150 for n in row['donors'].values())
        card_path = ph.CARDS_DIR / f'{aid}.json'
        if args.rebuild_cards or not account.get('existing') or not card_path.exists() or 'acct_' + aid in merged:
            if not args.dry_run:
                card = ph.write_card(persona, POSTS)
                lh.write_card(persona, POSTS)
            row['habit_card'] = 'built'
        else:
            row['habit_card'] = 'kept'
        card = ph.load_card(persona)
        mix, used = angles.donor_angle_mix(weights, persona.lang, POSTS)
        row['angles'] = angles.top_angles(mix, 4)
        uni = source_universe(store, account['retrieval_beats'])
        universes[aid] = {
            'account_id': aid, 'no': account['no'], 'lang': account['lang'], 'name': account['name'],
            'group': account.get('group', 'main'), 'status': account.get('status', 'main'),
            'beat': account['beat'], 'kind': account['kind'], 'emotion_tier': account['emotion_tier'],
            'retrieval_beats': account['retrieval_beats'], 'same_language_allowed': True,
            'lanes': [b for b in account['retrieval_beats'] if b in LANE_BEATS],
            # tier B handles are fetched daily into units (live/x_daily.py); C = topic lead only; None = unregistered
            'x_sources': [{'handle': h, 'source_id': 'x_' + h, 'enabled': True, 'role': role,
                           'tier': registry.source_licence_tier('x_' + h)}
                          for role in ('CORE', 'SECONDARY')
                          for h in x_sources_of(account, merge).get(role, [])],
            'attribution_line': False, **uni,
            'angle_mix': mix, 'top_angles': angles.top_angles(mix), 'angle_basis_posts': used,
            'post_type_mix': card.get('post_type_mix'), 'posting_hours_london': card.get('posting_hours_london'),
            'topic_mix': card.get('topic_mix'), 'card_posts': card.get('posts'),
            'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        row['sources'] = len(uni['sources'])
        row['x_sources_unregistered'] = [x['handle'] for x in universes[aid]['x_sources'] if x['tier'] is None]
        row['units_45d'] = uni['units_45d']
        row['card_posts'] = card.get('posts')
    lead = angles.distinctive({a: u['angle_mix'] for a, u in universes.items() if u.get('angle_mix')})
    for aid, mix in lead.items():
        universes[aid]['angle_lead'] = mix
        universes[aid]['top_angles'] = angles.top_angles(mix)
        if aid in report:
            report[aid]['angles'] = angles.top_angles(mix, 4)
    if not args.dry_run:
        write_json(UNIVERSES, universes)
    for aid, row in report.items():
        print(aid, json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
