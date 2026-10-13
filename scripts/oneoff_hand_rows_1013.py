"""Fiona-approved 10-13 hand rows: 4 strategy explainers (in-house backtest numbers) + Morris_LT translations.
Each row runs the deterministic gates (opener fix, first-hand, depth, fresh_hold, lane) and is written via
compose_inbox.add (sync_hold_status). --dry prints only."""
import sys, json
sys.path.insert(0, '/workspace/fd_new/Finance_Distillation')
from live import compose_inbox as ci, opener_mix, depth_check, fresh_hold, lane_fit, fd_accounts
DAY = '2026-10-13'
NOW = '2026-10-13T07:20:00+00:00'
BT = {'id': 'inhouse-carry-backtest-20261013', 'source_id': 'inhouse_backtest', 'publisher': 'in-house backtest',
      'title': 'HL cash-and-carry / funding strategies backtest (carry_repro_zh.ipynb, strategies.md)',
      'url': None, 'published_at': NOW, 'lang': 'zh', 'same_language': False,
      'path': '/workspace/ai_trading/strategies_deep/carry_repro_zh.ipynb'}
EXPL = [
 ('crypto_research_zh', 'zh', '13:30', '''把 Hyperliquid 上的 BTC 现货多 + 永续空一直挂着，能拿到多少资金费？我们内部回测给了一组数：

过去 12 个月（2025-10-13 至 2026-10-12），扣费后约 5.5%
2025 全年约 10.6%（未扣费）
2026 年初至今约 5.2%
最近 90 天（7/15–10/12）8.4%（未扣费），扣一次开平仓手续费后 7.3%；同期 ETH 为 9.1%

这笔钱来自多头付给空头的资金费。收益正在收窄，这一点值得关注

不构成投资建议'''),
 ('crypto_perp_dex_en', 'en', '14:10', '''Timing funding on Hyperliquid looks clever and costs you money

In our in-house backtest of BTC spot long + perp short over the last 12 months (2025-10-13 to 2026-10-12), the best funding-signal version made 3.2%, compared with about 5.5% after fees for simply staying on. The timed version also took roughly 10x the drawdown

Why: HL funding has a floor of about 0.01% per 8 hours, roughly 11% a year. Negative days are rare and brief, and every switch in and out pays fees

Not financial advice'''),
 ('crypto_stable_yield_en', 'en', '15:20', '''Same carry trade, two venues, very different yield

Binance majors funding follows sentiment. In our in-house backtest it went negative from February to April, and the BTC carry there is about 2.4% so far this year (simple, before fees)

On Hyperliquid, BTC spot long + perp short held always-on made about 5.2% so far in 2026, and about 5.5% after fees over the last 12 months (2025-10-13 to 2026-10-12)

That gap means you are being paid for venue and liquidity risk. Size it like compensation

Not financial advice'''),
 ('crypto_alt_trader_en', 'en', '16:40', '''New perp listings often pay eye-catching funding. Harvesting it is a worse trade than it looks

In our in-house backtest, the hedged version (short the new perp, hedge the exposure, 14-day hold, about 0.17% in fees) had a median return of only +0.56%

If you drop the hedge, it becomes a directional bet on the new coin falling. The worst 5% of those unhedged shorts lost about 41%

A thin edge on one side, a fat tail on the other

Not financial advice'''),
]
MORRIS = json.load(open('/workspace/fd_new/Finance_Distillation/runs/content_batch_v2/source_selection/en_morris_archive/selected_sources.json'))['sources']
MORRIS = {s['selection_id'].split('-')[0]: s['source'] for s in MORRIS}
TR = [
 ('investing_philosophy', 'M01', '12:10', '''In a linear world, effort matters more than direction. In a power-law world, direction matters more than effort

In the real world, direction × method × execution × luck decide the result together

(translated from @Morris_LT)'''),
 ('investing_philosophy', 'M05', '17:30', '''The first principle of wealth is accumulation
Of opportunity, insight
Of getting things done, focus
Of success, trial and error
Of competition, difference
Of profit, cost control
Of management, drawing out people's potential

(translated from @Morris_LT)'''),
 ('longterm_investing_en', 'M08', '12:40', '''For most people, getting rich once in a lifetime is enough

So once your age and your savings have built up, put risk control first. You can slow down how fast you earn, but never let an appetite for gambling make you poor again after the accumulation is done

(translated from @Morris_LT)'''),
]
accts = {a['id']: a for a in fd_accounts.rows('/workspace/fd_new/Finance_Distillation/live/fd20_accounts.json')}
dry = '--dry' in sys.argv
existing = {r['id'] for r in ci.rows(DAY)}
def gate(row, lang):
    nb, ch = opener_mix.fix_opener(row['body'], lang)
    if ch:
        row['body'] = row['text'] = nb; row['opener_fix'] = ch
    f = opener_mix.first_hand_findings(row['body'], lang) + depth_check.findings(row['body'], lang, row.get('post_kind'))
    if row.get('post_kind') != 'archive_lookback' and any(x in row['body'] for x in ('不是', '而是')) and '不是' in row['body'] and '而是' in row['body']:
        f.append({'code': 'not_x_but_y'})
    if f:
        row.update(held=True, hold_reason='hand gate: ' + ','.join(x.get('code', '?') for x in f), post_checks=f)
    acc = accts.get(row['account_id'])
    if acc is None:
        row.update(held=True, hold_reason='hand gate: unknown account')
    else:
        lf = lane_fit.macro_draft_check(acc, row['body'])
        if not lf['ok'] and not row.get('held'):
            row.update(held=True, hold_reason='off_lane: ' + str(lf.get('detail')), lane_fit=lf)
    fresh_hold.apply(row)
    return row
rows = []
for aid, lang, hhmm, body in EXPL:
    rows.append(gate({'id': f'expl-1013-{aid}', 'day': DAY, 'account_id': aid, 'lang': lang, 'text': body, 'body': body,
                      'post_kind': 'explainer', 'post_type': 'strategy_explainer', 'label': '策略讲解',
                      'post_format': {'type': 'explainer', 'explainer': True, 'length': 'single'},
                      'source': BT, 'draft_status': 'draft_ready', 'held': False, 'post_mode': 'original',
                      'suggested_post_time_london': f'{DAY}T{hhmm}:00+01:00', 'draft_origin': 'hand_fiona_1013',
                      'numbers_basis': 'Fiona-verified in-house backtest numbers (10-13 08:15)'}, lang))
for aid, mid, hhmm, body in TR:
    s = MORRIS[mid]
    rows.append(gate({'id': f'evg-1013-{aid}-{s["url"].rsplit("/",1)[-1]}', 'day': DAY, 'account_id': aid, 'lang': 'en',
                      'text': body, 'body': body, 'post_kind': 'archive_lookback', 'post_type': 'archive_evergreen',
                      'label': '常青', 'angle': {'id': 'evergreen', 'lens': '常青 translated idea'},
                      'post_format': {'type': 'archive_evergreen', 'length': 'single', 'thread_parts': 1},
                      'archive': {'variant': 'evergreen', 'original_url': s['url'], 'original_post_id': s['url'].rsplit('/',1)[-1],
                                  'handle': 'Morris_LT', 'role': 'donor', 'posted_at': s['published_at'],
                                  'original_text': s['original_text'], 'mode': 'translate_light_edit'},
                      'attribution_line': 'translated from @Morris_LT',
                      'source': {'id': s['id'], 'source_id': 'x_Morris_LT', 'publisher': '@Morris_LT', 'title': s['original_text'][:80],
                                 'url': s['url'], 'published_at': s['published_at'], 'lang': 'zh', 'same_language': False},
                      'draft_status': 'draft_ready', 'held': False, 'post_mode': 'original',
                      'suggested_post_time_london': f'{DAY}T{hhmm}:00+01:00', 'draft_origin': 'hand_fiona_1013'}, 'en'))
for r in rows:
    print(r['id'], r['account_id'], 'HELD ' + str(r.get('hold_reason')) if r.get('held') else 'ready', '| exists' if r['id'] in existing else '')
    if not dry and r['id'] not in existing:
        ci.add(r)
