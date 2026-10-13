"""Fiona-approved 10-13 (09:01) hand rows: LITE (Lumentum) single-stock takes for single_stock_deepdive_en and
zh_us_stocks. Numbers verified against the cited public URLs on 10-13. Same gates as oneoff_hand_rows_1013.py,
written via compose_inbox.add. --dry prints only."""
import sys
sys.path.insert(0, '/workspace/fd_new/Finance_Distillation')
from live import compose_inbox as ci, opener_mix, depth_check, fresh_hold, lane_fit, fd_accounts
DAY = '2026-10-13'
PR = 'https://investor.lumentum.com/financial-news-releases/news-details/2026/Lumentum-Announces-Fourth-Quarter-and-Full-Fiscal-Year-2026-Results/default.aspx'
# Hook event = the 10-12 close (AI-infra selloff); earnings figures are background facts in fact_refs.
SRC = {'id': 'yahoo-lite-close-20261012', 'source_id': 'yahoo_finance_quote', 'publisher': 'Yahoo Finance',
       'title': 'Lumentum Holdings (LITE) closes 995.41, -9.78% on Oct 12 amid AI infrastructure selloff',
       'url': 'https://finance.yahoo.com/quote/LITE/', 'published_at': '2026-10-12T20:00:02+00:00',
       'lang': 'en', 'same_language': True}
REFS = [
 {'claim': 'close $995.41, -9.78% on 2026-10-12; AI-infra funding selloff', 'url': 'https://finance.yahoo.com/quote/LITE/'},
 {'claim': 'FQ4 revenue $1.01B; FQ1 guide $1.225-1.275B', 'url': PR},
 {'claim': 'FQ1 midpoint >130% YoY (CFO)', 'url': 'https://www.fool.com/earnings/call-transcripts/2026/08/18/lumentum-lite-q4-2026-earnings-call-transcript/'},
 {'claim': 'next earnings call 2026-11-05 5pm ET', 'url': 'https://investor.lumentum.com/events-and-presentations/Events/event-details/2026/Q1-2027-Lumentum-Earnings-Conference-Call/default.aspx'},
]
ROWS = [
 ('single_stock_deepdive_en', 'en', '14:30', '''LITE dropped almost 10% yesterday and closed at $995.41

The selloff hit the whole AI infrastructure group on worries about funding, and Lumentum got dragged down with it

That stings, because this business just put up $1.01B in quarterly revenue and guided this quarter to more than 130% growth year over year

The part that's hard to get past is the multiple. One ugly day doesn't make it cheap

Nov 5 earnings is the next real test

Anyone add on this drop, or did you step aside?'''),
 ('zh_us_stocks', 'zh', '13:00', '''LITE 昨天一天跌了快 10%，收在 995

翻了一圈新闻，整个 AI 基建板块都在被砸，市场在担心融资，LITE 跟着一起挨了这一刀

可它上季度刚交了 10 亿美元收入，这季度指引同比翻一倍多，这组数看着还是很硬

真正让我犹豫的是估值，跌了一天它也算不上便宜

11 月 5 号财报前我大概会一直盯着

你们这次跌是加了还是跑了？'''),
]
accts = {a['id']: a for a in fd_accounts.rows('/workspace/fd_new/Finance_Distillation/live/fd20_accounts.json')}
dry = '--dry' in sys.argv
existing = {r['id'] for r in ci.rows(DAY)}
BANNED = ('不是', '而是', '原因不在', "not financial advice", '不构成投资建议', "it's not", 'it is not')
def gate(row, lang):
    nb, ch = opener_mix.fix_opener(row['body'], lang)
    if ch:
        row['body'] = row['text'] = nb; row['opener_fix'] = ch
    f = opener_mix.first_hand_findings(row['body'], lang) + depth_check.findings(row['body'], lang, row.get('post_kind'))
    if any(b in row['body'].lower() for b in BANNED):
        f.append({'code': 'banned_phrase'})
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
for aid, lang, hhmm, body in ROWS:
    r = gate({'id': f'hand-1013-lite-{aid}', 'day': DAY, 'account_id': aid, 'lang': lang, 'text': body, 'body': body,
              'post_kind': 'earnings_take', 'post_type': 'judgment_take', 'label': '个股',
              'post_format': {'type': 'single', 'length': 'single'}, 'source': dict(SRC), 'fact_refs': REFS,
              'draft_status': 'draft_ready', 'held': False, 'post_mode': 'original',
              'suggested_post_time_london': f'{DAY}T{hhmm}:00+01:00', 'draft_origin': 'hand_fiona_1013_lite',
              'numbers_basis': 'verified against cited public URLs 2026-10-13 09:10 London'}, lang)
    print(r['id'], 'HELD ' + str(r.get('hold_reason')) if r.get('held') else 'ready', '| exists' if r['id'] in existing else '', r.get('opener_fix') or '')
    if not dry and r['id'] not in existing:
        ci.add(r)
