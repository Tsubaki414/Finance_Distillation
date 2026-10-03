"""Hotspots to content opportunities, per account.

A hot entity is not yet an assignment. This scores each entity for each account separately, so
the four accounts diverge by construction rather than by hoping the writer varies:

  beat fit          an account only sees entities on beats it covers
  language posture  a topic discussed only in English is an opportunity for a Chinese account
                    (import the gap) and a weak one for the English accounts (already covered)
  lane              which of the six content lanes the entity would be written under
  crowding          an entity already assigned to another account is penalised, so two accounts
                    do not spend the day on the same story

Selection may return nothing. An account with no entity above the floor publishes nothing that
day, which is the honest outcome and is recorded as such.

Run: .venv/bin/python -B live/opportunities.py [--floor=6]
"""
from pathlib import Path
import sys, json, datetime

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'

# Which entity kinds and topics belong to which beat.
TOPIC_BEAT = {
    '#fed_policy': 'fed_policy', '#inflation': 'inflation', '#jobs': 'jobs',
    '#tariffs': 'tariffs', '#yen_fx': 'yen_fx', '#ai_capex': 'ai_capex',
    '#oil': 'oil', '#crypto': 'crypto', '#china_policy': 'china_policy',
    '#earnings': 'earnings',
}

# A ticker is an industry story unless it is being discussed as a macro proxy.
TICKER_BEAT = 'ai_capex'

LANES = {
    'hot_signal': '正在加速的讨论，需要尽快给出判断与失效条件',
    'scheduled_catalyst': '已知日程上的事件，提前准备',
    'cross_language_gap': '一侧语言已在讨论、另一侧尚未，信息差本身就是内容',
    'evergreen': '与当下无关的长期原则',
    'prediction_ledger': '回看此前判断是否成立',
    'deep_research': '需要原始文件支撑的深度题',
}


def beat_of(entity):
    if entity.startswith('#'):
        return TOPIC_BEAT.get(entity)
    return TICKER_BEAT


def language_posture(account_lang, gap):
    """A gap is an opportunity for the side that has not covered it, not for the side that has.

    en_only means the English accounts are already inside that conversation; for the Chinese
    accounts it is an import. Scoring both sides the same would have every account chase the
    same English-language story.
    """
    if gap == 'en_only':
        return (1.8, 'cross_language_gap') if account_lang == 'zh' else (0.4, 'hot_signal')
    if gap == 'zh_only':
        return (1.8, 'cross_language_gap') if account_lang == 'en' else (0.4, 'hot_signal')
    return (1.0, 'hot_signal')


def score_for(account, ent):
    beat = beat_of(ent['entity'])
    if beat not in account['beats']:
        return None
    mult, lane = language_posture(account['lang'], ent['cross_language_gap'])
    if lane not in account['lanes']:
        lane = 'hot_signal' if 'hot_signal' in account['lanes'] else account['lanes'][0]
    # Acceleration only counts when it was actually measured.
    accel = ent.get('acceleration_views_per_hour') if ent.get('acceleration_available') else None
    bonus = min((accel or 0) / 4000.0, 2.0)
    return {
        'entity': ent['entity'], 'beat': beat, 'lane': lane,
        'base_hotspot_score': ent['score'],
        'language_posture': round(mult, 2),
        'acceleration_bonus': round(bonus, 2),
        'acceleration_views_per_hour': accel,
        'score': round(ent['score'] * mult + bonus, 2),
        'distinct_authors': ent['distinct_authors'],
        'languages': ent['languages'],
        'cross_language_gap': ent['cross_language_gap'],
        'new_this_window': ent['new_this_window'],
        'first_mention': ent['first_mention'],
        'evidence_post_ids': ent['post_ids'],
        'why': (f"{ent['distinct_authors']} 位关注的作者在窗口内提到，"
                f"速度为该作者自身中位数的 {ent['velocity_vs_author_median']} 倍"
                + ('，且本窗口首次出现' if ent['new_this_window'] else '')
                + ('，另一语言尚未覆盖' if ent['cross_language_gap'] in ('zh_only', 'en_only') else '')),
    }


CROWDING_PENALTY = 0.55


def assign(hot, accounts, floor=6.0, per_account=2):
    """Greedy across accounts, penalising an entity another account already took."""
    taken = {}
    out = {}
    order = sorted(accounts, key=lambda a: a['id'])
    ranked = {a['id']: sorted(
        [x for x in (score_for(a, e) for e in hot['entities']) if x],
        key=lambda x: -x['score']) for a in order}

    for _ in range(per_account):
        for a in order:
            picks = out.setdefault(a['id'], [])
            if len(picks) >= per_account:
                continue
            best, best_score = None, 0.0
            for cand in ranked[a['id']]:
                if any(p['entity'] == cand['entity'] for p in picks):
                    continue
                s = cand['score'] * (CROWDING_PENALTY if cand['entity'] in taken else 1.0)
                if s > best_score:
                    best, best_score = cand, s
            if best and best_score >= floor:
                rec = {**best, 'effective_score': round(best_score, 2),
                       'crowded_with': taken.get(best['entity'], []).copy()}
                if rec['crowded_with']:
                    rec['distinctness_requirement'] = (
                        f"{'、'.join(rec['crowded_with'])} 已认领同一实体；"
                        f"本条必须从不同角度切入，成稿后走跨账号相似度闸门")
                picks.append(rec)
                taken.setdefault(best['entity'], []).append(a['id'])

    return out


def main():
    args = {a.split('=', 1)[0][2:]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    floor = float(args.get('floor', 6.0))
    hot = json.loads((STORE / 'hotspots.json').read_text())
    cfg = json.loads((ROOT / 'live/accounts.json').read_text())
    picks = assign(hot, cfg['accounts'], floor=floor,
                   per_account=cfg['daily_target']['max'])

    out = {
        'run_id': 'opp-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S'),
        'computed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'from_hotspots': hot['run_id'], 'hotspot_window_hours': hot['window_hours'],
        'floor': floor,
        'lanes': LANES,
        'accounts': {},
        'nothing_to_say': [],
    }
    for a in cfg['accounts']:
        sel = picks.get(a['id'], [])
        out['accounts'][a['id']] = {
            'name': a['name'], 'lang': a['lang'], 'persona_id': a['persona_id'],
            'selected': sel,
            'selected_count': len(sel),
        }
        if not sel:
            out['nothing_to_say'].append(a['id'])
    out['note'] = ('an account with nothing above the floor publishes nothing; that is recorded '
                   'rather than filled with a weaker topic')
    (STORE / 'opportunities.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"floor {floor} · from {hot['run_id']} ({hot['posts_in_window']} posts in window)")
    for aid, blk in out['accounts'].items():
        print(f"\n  {blk['name']}  [{aid}]")
        if not blk['selected']:
            print('    今日无够格选题')
        for s in blk['selected']:
            print(f"    {s['effective_score']:>6}  {s['entity']:12} lane={s['lane']:20} "
                  f"{s['cross_language_gap']}")
            print(f"            {s['why']}")
            if s.get('distinctness_requirement'):
                print(f"            ⚠ {s['distinctness_requirement']}")
    return out


if __name__ == '__main__':
    main()
