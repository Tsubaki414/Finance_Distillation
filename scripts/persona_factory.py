#!/usr/bin/env python3
"""Persona factory for the 20 main accounts (live/fd20_accounts.json; Oct 7).

For every account it makes sure the compose chain has what it needs, with no model calls:
  1. donor cluster  roster.persona_clusters['acct_<id>'] from /workspace/x/bios/plan_crypto.json (5 donors,
                    equal weight; every donor must be a verified voice donor of the account language)
  2. persona file   live/personas/<id>.json (new accounts only; existing personas are never rewritten)
  3. emotion tier   live/emotion_tiers.json personas[<id>] (crypto may be emotional, zh restrained = low)
  4. habit card     live/personas/posting_habits/<id>.json (post-type mix, length per type, topics, posting
                    hours) + language habits card (aggregates only; built from the local donor corpus)
  5. universe       live/store/fd20/universes.json: retrieval beats, the A/B sources that actually feed them
                    (unit counts, last 45 days), donor post counts and the account's angle mix (live/angles.py)

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

from live import angles, registry  # noqa: E402

CONFIG = ROOT / 'live' / 'fd20_accounts.json'
PLAN = Path('/workspace/x/bios/plan_crypto.json')
ROSTER = ROOT / 'live' / 'donors' / 'roster.json'
PERSONAS = ROOT / 'live' / 'personas'
EMOTION = ROOT / 'live' / 'emotion_tiers.json'
UNIVERSES = ROOT / 'live' / 'store' / 'fd20' / 'universes.json'
POSTS = ROOT / 'live' / 'donors' / 'posts'
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
    for line in path.read_text().splitlines():
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
        'origin': 'fd20 persona_factory 2026-10-07 from plan_crypto.json main (equal weights)',
        # the topic cluster whose content tags feed this account (its primary retrieval beat)
        'previous_cluster': account['retrieval_beats'][0]}
    return name, True


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
        'lineage': {'created_by': 'scripts/persona_factory.py', 'created': '2026-10-07',
                    'from': 'FD_accounts_final_v2.xlsx main row %d; plan_crypto.json donors' % account['no']},
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
    config = load_json(CONFIG)['accounts']
    plan = {a['id']: a for a in load_json(PLAN)['main']}
    only = set(args.accounts.split(',')) if args.accounts else None
    roster = load_json(ROSTER)
    emotion = load_json(EMOTION)
    report = {}
    changed_roster = changed_emotion = False
    for account in config:
        if only and account['id'] not in only:
            continue
        aid = account['id']
        row = {'existing': bool(account.get('existing'))}
        donors = (plan.get(aid) or {}).get('donors') or []
        persona_path = PERSONAS / f'{aid}.json'
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
        if emotion['personas'].get(aid) != account['emotion_tier']:
            if aid not in emotion['personas']:   # never retune an existing account's tier here
                emotion['personas'][aid] = account['emotion_tier']
                changed_emotion = True
        report[aid] = row
    if not args.dry_run:
        if changed_roster:
            ROSTER.write_text(json.dumps(roster, ensure_ascii=False, indent=1) + "\n")   # roster layout: indent 1
        if changed_emotion:
            write_json(EMOTION, emotion)
    # offline (deterministic, no LLM) voice cards for clusters that have none yet
    missing = [c for c in {'acct_' + a['id'] for a in config if a['id'] in report}
               if not (PERSONAS / 'voice_cards' / f'{c}.json').exists() and c in roster['persona_clusters']]
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
        if args.rebuild_cards or not account.get('existing') or not card_path.exists():
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
            'beat': account['beat'], 'kind': account['kind'], 'emotion_tier': account['emotion_tier'],
            'retrieval_beats': account['retrieval_beats'], 'same_language_allowed': True,
            'attribution_line': False, **uni,
            'angle_mix': mix, 'top_angles': angles.top_angles(mix), 'angle_basis_posts': used,
            'post_type_mix': card.get('post_type_mix'), 'posting_hours_london': card.get('posting_hours_london'),
            'topic_mix': card.get('topic_mix'), 'card_posts': card.get('posts'),
            'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        row['sources'] = len(uni['sources'])
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
