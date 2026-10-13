#!/usr/bin/env python3
"""数据监测: track what our own X accounts actually posted (Oct 13, Fiona).

1. fetch: one twitter241 /user-tweets call (count 40) per own account with a handle (live/fd20_accounts.json),
   user ids cached in live/store/auto_published/uids.json (shared with auto_published.py, so no /user calls).
   Posts merge into live/store/post_monitor/posts/<handle>.json (history accumulates past the 40-tweet window).
   Skipped when the last fetch is younger than FD_POSTMON_MIN_AGE_MIN (default 25) unless --force, so the engage
   pull + the compose run it triggers spend one round. FD_POSTMON=0 off; FD_POSTMON_MAX_CALLS cap (default 40).
2. match: each real post vs our drafts of the last 8 Beijing inbox days (same account; auto_published.similarity,
   >= 0.88 matched, 0.60-0.88 'edited'), drafts get posted / pending. Local records only:
   live/store/post_monitor/latest.json. Admin 已发 decisions stay with auto_published.py (it POSTs those).
3. build_page(out): writes <out>/monitor/index.html (called from build_ops_dashboard.py).
Cost: RapidAPI twitter241 subscription calls (~35 per run), no model calls.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
BJT, LON = ZoneInfo('Asia/Shanghai'), ZoneInfo('Europe/London')
STORE = ROOT / 'live/store/post_monitor'
POSTS = STORE / 'posts'
LATEST = STORE / 'latest.json'
CALLLOG = STORE / 'calls.json'
INBOX = ROOT / 'live/store/compose_inbox'
UIDS = ROOT / 'live/store/auto_published/uids.json'
MATCH, EDITED = 0.88, 0.60
WINDOW_DAYS = 7


def utc_now():
    return datetime.now(timezone.utc)


def parse_created(s):
    try:
        return datetime.strptime(s, '%a %b %d %H:%M:%S %z %Y').astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def accounts():
    from live import fd_accounts
    return [a for a in fd_accounts.rows(ROOT / 'live/fd20_accounts.json')]


def _raw_bookmarks(obj):
    """id -> (bookmark_count, quote_count) from the raw timeline (normalise() drops them)."""
    out = {}
    def walk(x):
        if isinstance(x, dict):
            leg = x.get('legacy')
            if isinstance(leg, dict) and x.get('rest_id') and 'bookmark_count' in leg:
                out[x['rest_id']] = (leg.get('bookmark_count'), leg.get('quote_count'))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return out


def load_posts(handle):
    try:
        return json.loads((POSTS / f'{handle.lower()}.json').read_text())
    except (OSError, ValueError):
        return {}


def cached_timeline(handle, max_age_min=20):
    """Fresh fetched posts for auto_published.py (saves its /user-tweets call); None when stale/missing."""
    d = load_posts(handle)
    try:
        age = utc_now() - datetime.fromisoformat(d.get('fetched_at', ''))
    except (ValueError, TypeError):
        return None
    if age > timedelta(minutes=max_age_min):
        return None
    return sorted(d.get('posts', {}).values(), key=lambda p: -int(p['id']))


def fetch(force=False):
    if os.environ.get('FD_POSTMON', '1') == '0':
        print('FD_POSTMON=0: skip fetch'); return 0
    min_age = float(os.environ.get('FD_POSTMON_MIN_AGE_MIN', '25'))
    try:
        last = datetime.fromisoformat(json.loads(LATEST.read_text())['fetched_at'])
        if not force and utc_now() - last < timedelta(minutes=min_age):
            print(f'post_monitor: last fetch {last:%H:%M}Z < {min_age:.0f} min ago: no fetch'); return 0
    except (OSError, ValueError, KeyError, TypeError):
        pass
    key = os.environ.get('RAPID_X_API_KEY')
    if not key:
        print('RAPID_X_API_KEY missing: no fetch', file=sys.stderr); return 1
    from live.x_daily import RapidClient
    from scrape_donor_posts import timeline_posts
    client = RapidClient(key, max_requests=int(os.environ.get('FD_POSTMON_MAX_CALLS', '40')))
    try:
        uids = json.loads(UIDS.read_text())
    except (OSError, ValueError):
        uids = {}
    n0 = len(uids)
    POSTS.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, []
    for a in accounts():
        h = a.get('handle')
        if not h:
            continue
        try:
            uid = uids.get(h.lower())
            if not uid:
                from auto_published import perf_raw_uid
                uid = perf_raw_uid(h)
            if not uid:
                u = client.get('/user', username=h)['result']['data']['user']['result']
                uid = u['rest_id']
            uids[h.lower()] = uid
            obj = client.get('/user-tweets', user=uid, count=40)
            extra = _raw_bookmarks(obj)
            prev = load_posts(h)
            store = prev.get('posts', {})
            now = utc_now().isoformat()
            for p in timeline_posts(obj):
                if p.get('uid') not in (None, uid) or not p.get('id'):
                    continue
                bm, qc = extra.get(p['id'], (None, None))
                p.update(bookmarks=bm, quotes=qc, seen_at=now)
                store[p['id']] = {**store.get(p['id'], {}), **p}
            cutoff = utc_now() - timedelta(days=30)
            store = {k: v for k, v in store.items() if (parse_created(v.get('created')) or utc_now()) >= cutoff}
            (POSTS / f'{h.lower()}.json').write_text(json.dumps(
                {'handle': h, 'uid': uid, 'fetched_at': now, 'posts': store}, ensure_ascii=False, indent=1))
            ok += 1
        except Exception as exc:
            failed.append(f'{h}: {str(exc)[:120]}')
            if 'budget exhausted' in str(exc):
                break
    if len(uids) > n0:
        UIDS.write_text(json.dumps(uids, indent=1, sort_keys=True) + '\n')
    try:
        log = json.loads(CALLLOG.read_text())
    except (OSError, ValueError):
        log = []
    log.append({'at': utc_now().isoformat(), 'calls': client.made, 'accounts_ok': ok, 'failed': failed})
    CALLLOG.write_text(json.dumps(log[-500:], indent=1) + '\n')
    print(f'post_monitor fetch: {ok} account(s), {client.made} twitter241 call(s), failed {len(failed)} {failed[:3]}')
    return 0


def load_drafts(days):
    from auto_published import load_decisions, is_published
    out = []
    for day in days:
        dec = load_decisions(day)
        for f in sorted((INBOX / day).glob('*.json')):
            try:
                r = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            body = (r.get('body') or r.get('text') or '').strip()
            if not body:
                continue
            did = r.get('id') or f.stem
            status = r.get('draft_status') or r.get('status') or ''
            ready = status == 'draft_ready' and not r.get('superseded') and not r.get('held') \
                and (r.get('arbitration') or {}).get('status') != 'HOLD'
            out.append({'day': day, 'id': did, 'account_id': r.get('account_id') or '', 'body': body,
                        'stored_at': r.get('stored_at') or '', 'slot': r.get('suggested_post_time_london') or '',
                        'mode': r.get('post_mode') or 'original', 'type': r.get('label') or r.get('post_type') or '',
                        'ready': ready, 'superseded': bool(r.get('superseded')),
                        'published_flag': is_published(dec.get(did) or {}),
                        'target': r.get('quote_target_url') or r.get('reply_to_url') or ''})
    return out


def compute():
    from auto_published import similarity, strip_target_url
    now = utc_now()
    today = now.astimezone(BJT).date()
    days7 = [(today - timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS - 1, -1, -1)]
    inbox_days = sorted(p.name for p in INBOX.iterdir() if p.is_dir())[-8:] if INBOX.is_dir() else []
    drafts = load_drafts(inbox_days)
    by_acc = {}
    for d in drafts:
        by_acc.setdefault(d['account_id'], []).append(d)
    fetched = []
    rows, all_posts = [], []
    for a in accounts():
        h = a.get('handle') or ''
        pd = load_posts(h) if h else {}
        if pd.get('fetched_at'):
            fetched.append(pd['fetched_at'])
        mine = by_acc.get(a['id'], [])
        posts = []
        for p in pd.get('posts', {}).values():
            c = parse_created(p.get('created'))
            if not c or p.get('rt') or c < now - timedelta(days=WINDOW_DAYS + 1):
                continue
            best, bs, second = None, 0.0, 0.0
            for d in mine:
                if d['stored_at']:
                    try:
                        if c < datetime.fromisoformat(d['stored_at']).astimezone(timezone.utc) - timedelta(hours=1):
                            continue
                    except ValueError:
                        pass
                txt = strip_target_url(p.get('text') or '', d['target']) if d['mode'] == 'quote' else p.get('text') or ''
                s = similarity(d['body'], txt)
                if s > bs:
                    best, bs, second = d, s, bs
                elif s > second:
                    second = s
            m = best if best and bs >= EDITED else None
            kind = 'reply' if p.get('reply') else 'quote' if p.get('quote') else 'thread' if p.get('self_thread') else 'original'
            delay = None
            if m and m['slot']:
                try:
                    delay = round((c - datetime.fromisoformat(m['slot']).astimezone(timezone.utc)).total_seconds() / 60)
                except ValueError:
                    pass
            row = {'id': p['id'], 'handle': h, 'account_id': a['id'], 'created_utc': c.isoformat(),
                   'bjt': c.astimezone(BJT).strftime('%m-%d %H:%M'), 'lon': c.astimezone(LON).strftime('%m-%d %H:%M'),
                   'day': c.astimezone(BJT).date().isoformat(), 'kind': kind, 'text': (p.get('text') or '')[:280],
                   'views': p.get('views'), 'likes': p.get('likes'), 'replies': p.get('replies'),
                   'reposts': p.get('reposts'), 'bookmarks': p.get('bookmarks'), 'quotes': p.get('quotes'),
                   'url': f'https://x.com/{h}/status/{p["id"]}',
                   'match': ('matched' if bs >= MATCH else 'edited') if m else 'unmatched',
                   'score': round(bs, 3), 'draft_id': m['id'] if m else '', 'draft_type': (m['type'] or m['mode']) if m else '',
                   'draft_day': m['day'] if m else '', 'slot_lon': m['slot'][11:16] if m and m['slot'] else '',
                   'delay_min': delay}
            if m:
                m.setdefault('posted', row['url'])
            posts.append(row)
        posts.sort(key=lambda r: r['created_utc'], reverse=True)
        counted = [r for r in posts if r['kind'] != 'thread']
        per_day = {d: sum(1 for r in counted if r['day'] == d) for d in days7}
        idle = 0
        for d in reversed(days7):
            if per_day[d]:
                break
            idle += 1
        tdrafts = [d for d in mine if d['day'] == today.isoformat() and (d['ready'] or d.get('posted') or d['published_flag'])]
        posted_today = [d for d in tdrafts if d.get('posted') or d['published_flag']]
        last = posts[0] if posts else None
        rows.append({'id': a['id'], 'name': a.get('name') or a['id'], 'handle': h, 'lang': a.get('lang') or '',
                     'fetched_at': pd.get('fetched_at') or '',
                     'last_bjt': last['bjt'] if last else '', 'last_lon': last['lon'] if last else '',
                     'per_day': [per_day[d] for d in days7], 'idle_days': idle if h else None,
                     'today_posts': per_day[days7[-1]], 'yesterday_posts': per_day[days7[-2]],
                     'drafts_today': len(tdrafts), 'drafts_posted': len(posted_today),
                     'drafts_pending': len(tdrafts) - len(posted_today),
                     'unmatched_7d': sum(1 for r in counted if r['match'] == 'unmatched'),
                     'views_24h': sum(r['views'] or 0 for r in posts if r['created_utc'] >= (now - timedelta(hours=24)).isoformat()),
                     'views_7d': sum(r['views'] or 0 for r in posts if r['day'] in days7)})
        all_posts += posts
    with_h = [r for r in rows if r['handle'] and r['fetched_at']]
    summary = {'accounts': len(with_h), 'posted_today': sum(1 for r in with_h if r['today_posts']),
               'posted_yesterday': sum(1 for r in with_h if r['yesterday_posts']),
               'idle': [r['handle'] for r in with_h if (r['idle_days'] or 0) >= 2],
               'views_24h': sum(r['views_24h'] for r in with_h), 'views_7d': sum(r['views_7d'] for r in with_h),
               'posts_7d': sum(sum(r['per_day']) for r in with_h),
               'matched_7d': sum(1 for p in all_posts if p['match'] != 'unmatched' and p['kind'] != 'thread'),
               'drafts_today': sum(r['drafts_today'] for r in rows), 'drafts_posted_today': sum(r['drafts_posted'] for r in rows),
               'no_handle': [r['id'] for r in rows if not r['handle']]}
    try:
        log = json.loads(CALLLOG.read_text())
        week = [x for x in log if x['at'] >= (now - timedelta(days=7)).isoformat()]
        summary['calls_7d'] = sum(x['calls'] for x in week)
        summary['calls_last_run'] = log[-1]['calls']
    except (OSError, ValueError, KeyError, IndexError):
        pass
    out = {'fetched_at': max(fetched, default=''), 'built_at': now.isoformat(), 'days': days7,
           'summary': summary, 'accounts': rows, 'posts': all_posts,
           'drafts_posted': [{'id': d['id'], 'day': d['day'], 'account_id': d['account_id'], 'url': d['posted']}
                             for d in drafts if d.get('posted')]}
    STORE.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


PAGE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FD 数据监测</title><style>__ROOTVARS__
__BASECSS__
__NAVCSS__
table{border-collapse:collapse;width:100%;background:var(--surface);border:1px solid var(--line);border-radius:10px;font-size:12.5px}
th,td{padding:5px 8px;border-bottom:1px solid var(--line2);text-align:left;vertical-align:top;white-space:nowrap}
th{color:var(--mute);font-weight:600;background:var(--sunk);position:sticky;top:0}
td.n{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
.g{display:inline-block;width:24px;text-align:center;border-radius:4px;margin-right:2px;font-family:var(--mono);background:var(--accent-bg);color:var(--accent)}
.g.z{background:var(--sunk);color:var(--faint)}.g.gap{background:#f8d4d2;color:var(--hold);font-weight:700}
.idle{color:var(--hold);font-weight:700}.um{color:var(--warn);font-weight:600}.mt{color:var(--accent)}
.tx{max-width:360px;white-space:normal;color:var(--ink2)}h2{font-size:15px;margin:26px 0 10px}
.scroll{overflow-x:auto}a{color:var(--accent)}</style></head><body><div class="wrap">__NAV__
<header><div class="logo">FD</div><div class="ttl"><h1>数据监测 · 账号实际发帖</h1><p id="sub"></p></div><div class="stats" id="stats"></div></header>
<div id="idle"></div><h2>账号（近 7 天，北京日）</h2><div class="scroll"><table id="acc"></table></div>
<h2>帖子明细 <select id="fa"><option value="">全部账号</option></select> <select id="fm"><option value="">全部</option><option value="matched">匹配草稿</option><option value="unmatched">非我们草稿</option></select></h2>
<div class="scroll"><table id="posts"></table></div></div>
<script>const D=__DATA__;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=n=>n==null?'-':n>=10000?(n/10000).toFixed(1)+'万':String(n);
const S=D.summary,t=s=>s?new Date(s).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}).slice(0,-3):'-';
document.getElementById('sub').textContent=`数据来源 X 公开时间线（twitter241，每号最新 40 条）· 抓取于 ${t(D.fetched_at)} 北京时间 · 每 2 小时随蹭流量拉取 + 夜间生成自动更新`;
document.getElementById('stats').innerHTML=[['今日已发账号',S.posted_today+'/'+S.accounts,'ok'],['昨日已发账号',S.posted_yesterday+'/'+S.accounts,''],['闲置 2 天+',S.idle.length,S.idle.length?'hd':'ok'],['24h 浏览',fmt(S.views_24h),''],['7 天浏览',fmt(S.views_7d),''],['今日草稿已发',S.drafts_posted_today+'/'+S.drafts_today,'wn']].map(([a,b,c])=>`<span class="stat ${c}"><small>${a}</small><b>${b}</b></span>`).join('');
document.getElementById('idle').innerHTML=S.idle.length?`<p class="idle">闲置（今天和昨天都没发）：${S.idle.map(h=>'@'+esc(h)).join('、')}</p>`:'';
const days=D.days.map(d=>d.slice(5));
const grid=r=>{const p=r.per_day;return p.map((n,i)=>{let gap=false;if(!n){let a=i,b=i;while(a>0&&!p[a-1])a--;while(b<p.length-1&&!p[b+1])b++;gap=b-a>=1}return `<span class="g${n?'':gap?' gap':' z'}" title="${D.days[i]}">${n}</span>`}).join('')};
const A=[...D.accounts].sort((a,b)=>(b.idle_days??-1)-(a.idle_days??-1)||a.handle.localeCompare(b.handle));
document.getElementById('acc').innerHTML=`<tr><th>账号</th><th>handle</th><th>最后发帖 北京 / 伦敦</th><th>${days.map(d=>`<span class="g z" style="background:none">${d.slice(3)}</span>`).join('')}</th><th>连续未发(天)</th><th>今日草稿 已发/待发</th><th>非草稿帖 7d</th><th>浏览 24h</th><th>浏览 7d</th></tr>`+A.map(r=>`<tr><td>${esc(r.name)}</td><td>${r.handle?`<a href="https://x.com/${esc(r.handle)}" target="_blank" rel="noopener">@${esc(r.handle)}</a>`:'<span class="idle">无 handle</span>'}</td><td>${esc(r.last_bjt||'-')} / ${esc(r.last_lon||'-')}</td><td>${grid(r)}</td><td class="n ${r.idle_days>=2?'idle':''}">${r.idle_days??'-'}</td><td class="n">${r.drafts_posted} / ${r.drafts_pending}</td><td class="n">${r.unmatched_7d}</td><td class="n">${fmt(r.views_24h)}</td><td class="n">${fmt(r.views_7d)}</td></tr>`).join('');
const fa=document.getElementById('fa'),fm=document.getElementById('fm');fa.innerHTML+=A.filter(r=>r.handle).map(r=>`<option value="${esc(r.handle)}">@${esc(r.handle)}</option>`).join('');
const KD={original:'原创',reply:'回复',quote:'引用',thread:'串'};
function rp(){const P=D.posts.filter(p=>(!fa.value||p.handle===fa.value)&&(!fm.value||(fm.value==='unmatched'?p.match==='unmatched':p.match!=='unmatched'))).sort((a,b)=>b.created_utc.localeCompare(a.created_utc));
document.getElementById('posts').innerHTML=`<tr><th>发出 北京</th><th>伦敦</th><th>账号</th><th>类型</th><th>建议(伦敦)</th><th>延迟</th><th>浏览</th><th>赞</th><th>回复</th><th>转发</th><th>收藏</th><th>匹配草稿</th><th>内容</th><th>X</th></tr>`+P.map(p=>`<tr><td>${p.bjt}</td><td>${p.lon}</td><td>@${esc(p.handle)}</td><td>${KD[p.kind]||p.kind}</td><td>${esc(p.slot_lon||'-')}</td><td class="n">${p.delay_min==null?'-':(p.delay_min>=0?'+':'')+(Math.abs(p.delay_min)>=90?(p.delay_min/60).toFixed(1)+'h':p.delay_min+'m')}</td><td class="n">${fmt(p.views)}</td><td class="n">${fmt(p.likes)}</td><td class="n">${fmt(p.replies)}</td><td class="n">${fmt(p.reposts)}</td><td class="n">${fmt(p.bookmarks)}</td><td>${p.match==='unmatched'?'<span class="um">非草稿</span>':`<span class="mt" title="${esc(p.draft_id)} 相似度 ${p.score}">${p.match==='edited'?'改后发 ':''}${esc(p.draft_type)} · ${esc(p.draft_id.slice(0,26))}</span>`}</td><td class="tx">${esc(p.text.slice(0,120))}</td><td><a href="${esc(p.url)}" target="_blank" rel="noopener">打开</a></td></tr>`).join('')}
fa.onchange=fm.onchange=rp;rp();</script></body></html>'''


def build_page(out_dir):
    import build_ops_dashboard as ops
    data = compute()
    pub = {k: v for k, v in data.items() if k != 'drafts_posted'}
    page = (PAGE.replace('__ROOTVARS__', ops.ROOT_CSS).replace('__BASECSS__', ops.BASE_CSS)
            .replace('__NAVCSS__', ops.NAV_CSS).replace('__NAV__', ops.nav_html('/monitor')))
    page = page.replace('__DATA__', json.dumps(pub, ensure_ascii=False).replace('</', '<\\/'))
    (Path(out_dir) / 'monitor').mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / 'monitor/index.html').write_text(page)
    s = data['summary']
    print(f"monitor page: {s['accounts']} accounts, posted today {s['posted_today']}, idle {len(s['idle'])}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fetch', action='store_true'); ap.add_argument('--force', action='store_true')
    ap.add_argument('--page', type=Path, help='also write <dir>/monitor/index.html')
    a = ap.parse_args(argv)
    rc = fetch(a.force) if a.fetch else 0
    if a.page:
        build_page(a.page)
    else:
        s = compute()['summary']; print(json.dumps(s, ensure_ascii=False))
    return rc


if __name__ == '__main__':
    sys.exit(main())
