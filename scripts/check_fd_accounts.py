#!/usr/bin/env python3
"""Offline pipeline check for roster accounts (Oct 8, 36 accounts). No model calls, no network, no writes to the store.

For each checked account (default: the spare + new groups of live/fd_accounts.py):
  config      roster row, persona resolves, donor cluster (donors with scraped posts, newest donor post), emotion tier,
              posting-habit / language-habit / voice cards, media profile, universe entry, X sources and their tier
  topic       the donor topic spread live/topic_div uses at pick time (last 7 days of donor originals)
  candidates  per retrieval beat: tagged A/B units in the selection window; the account's packet pool after every
              compose gate (scripts/daily_compose.candidates: X scoping, beat gate, precheck)
  plan        one offline selection over the whole enabled roster (daily_compose.select, allow_model=False) and the
              ops-page post times (08:00-22:59 Beijing, >= 30 min apart)
Exit 1 when a checked account has no candidates or a missing config piece.

  python scripts/check_fd_accounts.py [--accounts a,b] [--day 2026-10-09] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT)]

from live import fd_accounts, registry, topic_div  # noqa: E402

LONDON = ZoneInfo('Europe/London')
# the check only: registry.persona_for_account reloads every persona file per packet (0.4 s each; the nightly select
# pays that too), cache it so 36 accounts check in minutes. Production code is untouched.
_load_personas, _personas_cache = registry.load_personas, {}


def _cached_personas(*args, **kwargs):
    key = (args, tuple(sorted(kwargs.items())))
    if key not in _personas_cache:
        _personas_cache[key] = _load_personas(*args, **kwargs)
    return _personas_cache[key]


registry.load_personas = _cached_personas


def _exists(path):
    return Path(path).exists()


def config_row(a, roster, emotion, media, universes, personas):
    from live import posting_habits as ph
    aid = a['id']
    cluster = roster['persona_clusters'].get('acct_' + aid) or {}
    donors = {}
    for d in cluster.get('donors') or []:
        path = ROOT / 'live/donors/posts' / f"{d['handle'].lower()}.jsonl"
        n, newest = 0, None
        if path.exists():
            for line in path.read_text().split('\n'):
                try:
                    p = json.loads(line)
                except ValueError:
                    continue
                if p.get('text') and not p.get('rt'):
                    n += 1
                    t = topic_div._created(p)
                    newest = max(newest, t) if newest and t else (t or newest)
        donors[d['handle']] = {'originals': n, 'newest': newest.date().isoformat() if newest else None}
    try:
        persona = registry.persona_for_account(aid, personas).persona_id
    except Exception as exc:   # noqa: BLE001
        persona = f'ERROR {exc}'
    uni = universes.get(aid) or {}
    xs = uni.get('x_sources') or []
    row = {
        'group': a.get('group'), 'status': a.get('status'), 'lang': a['lang'], 'name': a['name'], 'kind': a.get('kind'),
        'retrieval_beats': a['retrieval_beats'], 'persona': persona, 'donors': donors,
        'emotion_tier': emotion['personas'].get(aid),
        'cards': {'posting_habits': _exists(ph.CARDS_DIR / f'{aid}.json'),
                  'language_habits': _exists(ROOT / 'live/personas/language_habits' / f'{aid}.json'),
                  'voice_card': _exists(ROOT / 'live/personas/voice_cards' / f'acct_{aid}.json'),
                  'signature_card': _exists(ROOT / 'live/personas/signature_cards' / f'{aid}.json')},
        'media_profile': (media['accounts'].get(aid) or {}).get('p_image'),
        'universe': bool(uni), 'x_sources': len(xs), 'x_sources_tier_b': sum(x.get('tier') == 'B' for x in xs),
    }
    missing = [k for k in ('emotion_tier', 'media_profile') if row[k] is None]
    missing += [k for k in ('posting_habits', 'language_habits', 'voice_card') if not row['cards'][k]]
    missing += ['universe'] if not row['universe'] else []
    missing += ['persona'] if str(persona).startswith('ERROR') else []
    missing += ['donors'] if sum(v['originals'] > 0 for v in donors.values()) < registry.MIN_EXEMPLARS else []
    row['missing'] = missing
    return row


def lane_counts(store, a, ref):
    from live.retrieval import units_for_persona
    import daily_compose as dc
    out = {}
    for beat in a['retrieval_beats']:
        rows = [r for r in units_for_persona(store, beat, max_age_days=dc.MAX_AGE_DAYS, as_of=ref)
                if r.get('licence_tier') in ('A', 'B')]
        out[beat] = len(rows)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--accounts', help='comma-separated ids (default: the spare + new groups)')
    ap.add_argument('--day', default=None, help='drafting day (Beijing date), default tomorrow')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    import daily_compose as dc
    from live.content_store import ContentStore
    from scripts.build_ops_dashboard import clamp_times, to_bjt
    from live.x_daily import x_handle
    roster_all = fd_accounts.load()
    checked = ([a for a in roster_all if a['id'] in set(args.accounts.split(','))] if args.accounts
               else [a for a in roster_all if a.get('group') in ('spare', 'new')])
    day = date.fromisoformat(args.day) if args.day else date.today() + timedelta(days=1)
    now = datetime(day.year, day.month, day.day, 0, 13, tzinfo=LONDON) - timedelta(hours=1)   # the 23:13 London run
    ref = dc.selection_ref(day, now)
    roster = json.loads((ROOT / 'live/donors/roster.json').read_text())
    emotion = json.loads((ROOT / 'live/emotion_tiers.json').read_text())
    media = json.loads((ROOT / 'live/media_profiles.json').read_text())
    universes = json.loads(dc.UNIVERSES.read_text())
    personas = registry.load_personas()
    store = ContentStore()
    report = {'day': day.isoformat(), 'selection_ref': ref.isoformat(), 'accounts': {}}
    profs = topic_div.profiles([a['id'] for a in checked], ref, day.isoformat(), cache=False)
    for a in checked:
        row = config_row(a, roster, emotion, media, universes, personas)
        prof = profs.get(a['id']) or {}
        mix = prof.get('mix') or prof.get('theme_mix') or {}
        row['topic_spread'] = {'donor_posts_7d': prof.get('posts'), 'distinct_themes': prof.get('distinct_themes'),
                               'top_themes': sorted(mix, key=lambda k: -mix[k])[:5] if isinstance(mix, dict) else mix}
        row['lane_units'] = lane_counts(store, a, ref)
        x_of = [x['handle'] for x in (universes.get(a['id']) or {}).get('x_sources') or [] if x.get('enabled', True)]
        pool = dc.candidates(store, a['id'], a['retrieval_beats'], (universes.get(a['id']) or {}).get('angle_lead') or {},
                             ref, x_handles=x_of, account_cfg=a)
        lanes = {b for b in a['retrieval_beats'] if b in dc_lanes()}
        row['candidates'] = {'packets': len(pool),
                             'own_x_packets': sum(bool(x_handle(g[0]['source'])) for g in pool),
                             'own_lane_packets': sum(any(lanes & set(r.get('tag_personas') or []) for r in g) for g in pool),
                             'sample': [str(g[0]['source'].get('title') or '')[:70] for g in pool[:3]]}
        report['accounts'][a['id']] = row
    # one offline selection over the whole enabled roster (selection is cross-account: event takers, hotspot)
    info = {}
    plan, order = dc.select(roster_all, universes, day, 2, done={}, now=now, allow_model=False, info=info)
    drafts = [{'id': f"{aid}-{i}", 'account_id': aid, 'time': to_bjt(p.get('suggested_post_time_london'))}
              for aid, picks in plan.items() for i, p in enumerate(picks)]
    clamp_times([d for d in drafts if d['time']], day.isoformat())
    for aid, row in report['accounts'].items():
        picks = plan.get(aid) or []
        times = sorted(d['time'][11:16] for d in drafts if d['account_id'] == aid and d['time'])
        row['plan'] = {'picks': len(picks), 'pool': (info.get('pool_sizes') or {}).get(aid),
                       'post_times_bjt': times,
                       'picked': [f"{p['post_format']['type']} {p['angle']} {str(p['title'])[:50]}" for p in picks]}
    bad = {aid: r['missing'] for aid, r in report['accounts'].items() if r['missing']}
    empty = [aid for aid, r in report['accounts'].items() if not r['candidates']['packets']]
    report['summary'] = {'checked': len(report['accounts']), 'missing_config': bad, 'no_candidates': empty,
                         'roster_size': len(roster_all),
                         'planned_drafts_all_accounts': sum(len(v) for v in plan.values())}
    for aid, r in report['accounts'].items():
        c, p = r['candidates'], r['plan']
        print(f"{aid:24} {r['group']:5} donors {sum(v['originals'] > 0 for v in r['donors'].values())}/{len(r['donors'])} "
              f"x {r['x_sources_tier_b']}/{r['x_sources']}B  pool {c['packets']:3} (own-lane {c['own_lane_packets']}, own-X "
              f"{c['own_x_packets']})  picks {p['picks']} @ {', '.join(p['post_times_bjt']) or '-'}  "
              f"themes {r['topic_spread']['top_themes'][:3]}  missing {r['missing'] or '-'}")
    print(json.dumps(report['summary'], ensure_ascii=False))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if bad or empty else 0


def dc_lanes():
    from live.jev_front import LANE_BEATS
    return LANE_BEATS


if __name__ == '__main__':
    sys.exit(main())
