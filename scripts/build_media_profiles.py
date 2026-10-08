"""Build live/media_profiles.json: per fd20 account, how often its donors attach an image and what kind.

Inputs (local only, never committed):
  - donor posts (live/donors/posts): the photo flag on each donor's 40 most recent original posts -> image_rate.
  - an image classification file (--classes, from the Oct 8 donor image sample: one record per sampled donor image
    with category / theme / annotations / aspect) -> chart_share (share of donor images that are charts at all;
    memes, photos, X screenshots and text cards are not charts) and the style mix.
Output: aggregate numbers only (rates, shares, weights). No donor text, handles, ids or image URLs.

Donor image category -> our media style:
  tradingview_chart        -> tv (annotated share -> tv_drawn, plain -> tv_widget capture)
  exchange_app / broker / pnl screenshots -> mobile when shot on a phone (or taller than wide), else tv
  derivatives_dashboard, table_or_data_screenshot -> table (perp funding / OI table)
  onchain_analytics_panel, research_report_chart, macro_data_chart -> panel (data series panel; FRED capture for
                                                                       FRED series)
Per-account shares are the account's own sample blended with its family (crypto/stocks x zh/en), PRIOR_N pseudo
images of the family, because 6 images per account is thin.

  python3 scripts/build_media_profiles.py --classes /workspace/x/charts_real/classes.json \
      --meta /workspace/x/charts_real/donor_meta.json

Media v3 (Oct 8, --attribution): every sampled donor image traced to its source (site / app / page, see
docs/MEDIA_SOURCES.md), one record per image: {accounts, style, theme, tall}. style is the media style that source
maps to (TradingView -> tv_drawn / tv_widget, exchange / broker apps -> mobile, data sites / research / own charts ->
panel, tables -> table, X post screenshots -> x_post, news / flash screenshots -> article, ETF flow dashboards ->
etf_flows, Polymarket -> polymarket) or null (photos, memes, promos, chats: nothing we post). The account's current
numbers are kept under "v2" so FD_MEDIA_SOURCES=0 restores them exactly.

  python3 scripts/build_media_profiles.py --attribution /workspace/x/media_sources/attribution.json

--only-missing (Oct 8, 36 accounts): keep every account (and family) already in the output file and add only the
roster accounts it lacks. A new account has no classified image sample yet (n = 0), so its chart share / styles are
its family's; image_rate is measured from its own donors as usual. Re-run without the flag after classifying a
sample of the new donors' images to give them their own shares.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / 'live/media_profiles.json'
PRIOR_N = 12
RECENT = 40
STYLE_OF = {'tradingview_chart': 'tv', 'exchange_app_screenshot': 'mobile', 'terminal_or_broker_chart': 'mobile',
            'pnl_or_position_screenshot': 'mobile', 'derivatives_dashboard': 'table',
            'table_or_data_screenshot': 'table', 'onchain_analytics_panel': 'panel',
            'research_report_chart': 'panel', 'macro_data_chart': 'panel'}
STYLES = ('tv_drawn', 'tv_widget', 'mobile', 'table', 'panel')
STYLES_V3 = STYLES + ('x_post', 'article', 'etf_flows', 'polymarket')
# styles that count towards p_image: article screenshots mostly come from sites we may not load (manual only), so
# they get a weight (used when the draft's source is an allow-listed site) but do not raise how often we post images
PRODUCIBLE = set(STYLES_V3) - {'article'}


def family(acct):
    return ('crypto' if acct['kind'] == 'crypto' else 'stocks') + '_' + acct['lang']


def image_rate(acct_id, roster, posts_dir):
    from live.voice_cards import load_posts
    orig = photo = 0
    for d in roster['persona_clusters']['acct_' + acct_id]['donors']:
        ps = [p for p in load_posts(d['handle'], posts_dir) if not p.get('rt') and not p.get('reply')]
        ps = sorted(ps, key=lambda p: int(p['id']), reverse=True)[:RECENT]
        orig += len(ps)
        photo += sum('photo' in (p.get('media') or []) for p in ps)
    return photo / orig if orig else 0.0, orig


def tally(records):
    """records: [(class dict, width, height)] -> counts used by the profile."""
    c = collections.Counter()
    for cl, w, h in records:
        c['images'] += 1
        style = STYLE_OF.get(cl.get('category'))
        if not style:
            continue
        if style == 'mobile' and cl.get('device') != 'phone_screenshot' and not (w and h and w / h < 0.8):
            style = 'tv'   # desktop broker / terminal / exchange web screenshots read like a TradingView chart
        c['charts'] += 1
        if style == 'tv':
            ann = [a for a in cl.get('annotations') or [] if a not in ('none', 'indicator_panels')]
            style = 'tv_drawn' if ann else 'tv_widget'
        c['style:' + style] += 1
        c['light' if cl.get('theme') == 'light' else 'dark'] += 1
        if w and h:
            c['tall' if w / h < 0.8 else 'wide'] += 1
    return c


def shares(c):
    charts = max(c['charts'], 1)
    return {'chart_share': c['charts'] / max(c['images'], 1),
            'styles': {s: c['style:' + s] / charts for s in STYLES},
            'light_share': c['light'] / max(c['light'] + c['dark'], 1),
            'tall_share': c['tall'] / max(c['tall'] + c['wide'], 1), 'n': c['images']}


def blend(own, fam):
    n = own['n']
    w = n / (n + PRIOR_N)
    mix = lambda a, b: round(w * a + (1 - w) * b, 3)   # noqa: E731
    return {'chart_share': mix(own['chart_share'], fam['chart_share']),
            'styles': {s: mix(own['styles'][s], fam['styles'][s]) for s in STYLES},
            'light_share': mix(own['light_share'], fam['light_share']),
            'tall_share': mix(own['tall_share'], fam['tall_share'])}


def tally_v3(records):
    c = collections.Counter()
    for r in records:
        c['images'] += 1
        st = r.get('style')
        if not st:
            continue
        c['styled'] += 1
        c['style:' + st] += 1
        if st in PRODUCIBLE:
            c['producible'] += 1
            c['light' if r.get('theme') == 'light' else 'dark'] += 1
            c['tall' if r.get('tall') else 'wide'] += 1
    return c


def shares_v3(c):
    styled = max(c['styled'], 1)
    return {'chart_share': c['producible'] / max(c['images'], 1),
            'styles': {s: c['style:' + s] / styled for s in STYLES_V3},
            'light_share': c['light'] / max(c['light'] + c['dark'], 1),
            'tall_share': c['tall'] / max(c['tall'] + c['wide'], 1), 'n': c['images']}


def blend_v3(own, fam):
    w = own['n'] / (own['n'] + PRIOR_N)
    mix = lambda a, b: round(w * a + (1 - w) * b, 3)   # noqa: E731
    return {'chart_share': mix(own['chart_share'], fam['chart_share']),
            'styles': {s: mix(own['styles'][s], fam['styles'][s]) for s in STYLES_V3},
            'light_share': mix(own['light_share'], fam['light_share']),
            'tall_share': mix(own['tall_share'], fam['tall_share'])}


def main_v3(args):
    recs = json.loads(args.attribution.read_text())
    roster = json.loads(args.roster.read_text())
    from live import fd_accounts
    accounts = fd_accounts.rows(args.accounts)   # the gated 36-account roster (Oct 8: v3 used to read fd20 only)
    fam_of = {a['id']: family(a) for a in accounts}
    old = json.loads(args.out.read_text()) if args.out.exists() else {'accounts': {}}
    by_acct, by_fam = collections.defaultdict(list), collections.defaultdict(list)
    for r in recs:
        for a in r['accounts']:
            by_acct[a].append(r)
        by_fam[fam_of[r['accounts'][0]]].append(r)
    fam_shares = {f: shares_v3(tally_v3(r)) for f, r in by_fam.items()}
    rnd = lambda d: {k: (round(v, 3) if isinstance(v, float) else {s: round(x, 3) for s, x in v.items()}   # noqa: E731
                         if isinstance(v, dict) else v) for k, v in d.items()}
    out = {'version': 3, 'built': date.today().isoformat(),
           'method': ('media v3: image_rate = photo share of the donors\' 40 most recent original posts; styles = the '
                      'attributed source mix of a sample of recent donor images (each image traced to the site / app / '
                      f'page it came from), blended with the account family at {PRIOR_N} pseudo images. '
                      'p_image = image_rate x share of donor images in a source we can produce (non-charts and '
                      'article screenshots excluded). v2 = the Oct 8 numbers (FD_MEDIA_SOURCES=0). Aggregates only.'),
           'families': {f: rnd(s) for f, s in sorted(fam_shares.items())},
           'families_v2': old.get('families_v2') or old.get('families') or {}, 'accounts': {}}
    for a in accounts:
        prev = old['accounts'].get(a['id']) or {}
        v2 = prev.get('v2') or {k: prev[k] for k in ('p_image', 'chart_share', 'styles', 'light_share', 'tall_share')
                                if k in prev}
        rate, n_posts = image_rate(a['id'], roster, args.posts)
        b = blend_v3(shares_v3(tally_v3(by_acct[a['id']])), fam_shares[fam_of[a['id']]])
        out['accounts'][a['id']] = {'family': fam_of[a['id']], 'image_rate': round(rate, 3), 'posts_seen': n_posts,
                                    'sampled_images': len(by_acct[a['id']]), **b,
                                    'p_image': round(rate * b['chart_share'], 3), 'v2': v2}
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + '\n')
    for k, v in out['accounts'].items():
        top = sorted(v['styles'].items(), key=lambda x: -x[1])[:5]
        print(f"{k:26} rate {v['image_rate']:.2f} producible {v['chart_share']:.2f} p {v['p_image']:.2f} "
              f"(v2 {v['v2'].get('p_image')}) light {v['light_share']:.2f} {top}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--attribution', type=Path, help='media v3: per-image source attribution records')
    ap.add_argument('--classes', type=Path)
    ap.add_argument('--meta', type=Path)
    ap.add_argument('--posts', type=Path, default=ROOT / 'live/donors/posts')
    ap.add_argument('--roster', type=Path, default=ROOT / 'live/donors/roster.json')
    ap.add_argument('--accounts', type=Path, default=ROOT / 'live/fd20_accounts.json')
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--only-missing', action='store_true', help='add accounts missing from --out, keep the rest')
    args = ap.parse_args()
    if args.attribution:
        return main_v3(args)
    if not (args.classes and args.meta):
        ap.error('--classes and --meta (v2) or --attribution (v3)')
    classes = json.loads(args.classes.read_text())
    meta = json.loads(args.meta.read_text())['images']
    roster = json.loads(args.roster.read_text())
    from live import fd_accounts
    accounts = fd_accounts.rows(args.accounts)
    by_acct, by_fam = collections.defaultdict(list), collections.defaultdict(list)
    fam_of = {a['id']: family(a) for a in accounts}
    for img_id, m in meta.items():
        if img_id not in classes:
            continue
        rec = (classes[img_id], m.get('w'), m.get('h'))
        for a in m['accounts']:
            by_acct[a].append(rec)
        by_fam[fam_of[m['accounts'][0]]].append(rec)
    fam_shares = {f: shares(tally(r)) for f, r in by_fam.items()}
    out = {'version': 1, 'built': date.today().isoformat(),
           'method': ('image_rate = photo share of the donors\' 40 most recent original posts each; chart_share and '
                      'styles from a classified sample of recent donor images (6 per account), blended with the '
                      f'account family at {PRIOR_N} pseudo images. p_image = image_rate x chart_share. '
                      'Aggregates only.'),
           'families': {f: {k: (round(v, 3) if isinstance(v, float) else
                                 {s: round(x, 3) for s, x in v.items()} if isinstance(v, dict) else v)
                             for k, v in s.items()} for f, s in sorted(fam_shares.items())},
           'accounts': {}}
    keep = json.loads(args.out.read_text()) if args.only_missing and args.out.exists() else None
    if keep:
        out['families'] = keep['families']
        fam_shares = {f: {**v, 'styles': dict(v['styles'])} for f, v in keep['families'].items()}
        out['accounts'] = dict(keep['accounts'])
        out['built'] = keep.get('built')
        today = date.today().isoformat()   # a second run on the same day appends (Oct 8 b)
        out['added'] = {**(keep.get('added') or {}), today: ((keep.get('added') or {}).get(today) or []) +
                        [a['id'] for a in accounts if a['id'] not in keep['accounts']]}
    for a in accounts:
        if keep and a['id'] in keep['accounts']:
            continue
        rate, n_posts = image_rate(a['id'], roster, args.posts)
        b = blend(shares(tally(by_acct[a['id']])), fam_shares[fam_of[a['id']]])
        out['accounts'][a['id']] = {'family': fam_of[a['id']], 'image_rate': round(rate, 3), 'posts_seen': n_posts,
                                    **b, 'p_image': round(rate * b['chart_share'], 3)}
    args.out.write_text(json.dumps(out, indent=1) + '\n')
    for k, v in out['accounts'].items():
        if keep and k in keep['accounts']:
            continue
        print(f"{k:26} rate {v['image_rate']:.2f} chart {v['chart_share']:.2f} p {v['p_image']:.2f} "
              f"light {v['light_share']:.2f} tall {v['tall_share']:.2f} {v['styles']}")


if __name__ == '__main__':
    main()
