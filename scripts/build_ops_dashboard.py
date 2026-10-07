#!/usr/bin/env python3
"""Operator copy-paste dashboard for the fd20 compose inbox (static HTML, no model calls, no publishing).

Reads every live/store/compose_inbox/<day>/*.json row plus live/fd20_accounts.json (names) and
assets/persona_avatars (avatars, embedded). Writes a self-contained index.html and one <day>.csv per day
(account, time, text) to --out. The post text is the draft body only: no source/attribution line, no notes.
Idempotent: files are rewritten only when their content changes.
"""
import argparse
import base64
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / 'live/store/compose_inbox'
ACCOUNTS = ROOT / 'live/fd20_accounts.json'
AVATARS = ROOT / 'assets/persona_avatars'
OUT = Path('/workspace/x/dashboard/ops')
DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
CJK_RE = re.compile(r'[ᄀ-ᇿ⺀-꓏가-힣豈-﫿︰-﹏＀-￯\U00020000-\U0003ffff]')
URL_RE = re.compile(r'https?://\S+')


def x_weight(text):
    """Approximate X weighted length: CJK/full-width chars count 2, URLs count 23."""
    urls = URL_RE.findall(text)
    rest = URL_RE.sub('', text)
    return 23 * len(urls) + len(rest) + len(CJK_RE.findall(rest))


def avatar_uri(path, size=96):
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=82)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()


def load_accounts():
    accounts = json.loads(ACCOUNTS.read_text())['accounts'] if ACCOUNTS.exists() else []
    out = []
    for a in accounts:
        found = sorted(AVATARS.glob(f"*_{a['id']}.png")) if AVATARS.is_dir() else []
        out.append({'id': a['id'], 'no': a.get('no'), 'name': a.get('name') or a['id'], 'lang': a.get('lang'),
                    'beat': a.get('beat'), 'handle': a.get('handle') or '',
                    'avatar': avatar_uri(found[0]) if found else ''})
    return out


def parts_of(row, body):
    if isinstance(row.get('thread'), list) and row['thread']:
        return [str(p).strip() for p in row['thread'] if str(p).strip()]
    if ((row.get('post_format') or {}).get('type') == 'thread'):
        # same fallback compose uses: thread parts are the body's blank-line separated blocks
        return [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
    return None


def status_of(row):
    if row.get('held') or (row.get('arbitration') or {}).get('status') == 'HOLD':
        return 'HOLD'
    return row.get('draft_status') or row.get('status') or 'unknown'


def load_day(day_dir):
    drafts = []
    for f in sorted(day_dir.glob('*.json')):
        try:
            row = json.loads(f.read_text())
        except (OSError, ValueError) as exc:
            print(f'skip {f}: {exc}', file=sys.stderr)
            continue
        body = (row.get('body') or '').strip()
        parts = parts_of(row, body)
        drafts.append({
            'id': row.get('id') or f.stem, 'account_id': row.get('account_id'), 'name': row.get('name'),
            'lang': row.get('lang'), 'text': body, 'parts': parts,
            'parts_w': [x_weight(p) for p in parts] if parts else None,
            'chars': len(body), 'xw': x_weight(body),
            'time': row.get('suggested_post_time_london') or '', 'post_type': row.get('post_type') or '',
            'format': (row.get('post_format') or {}).get('type') or '', 'status': status_of(row)})
    drafts.sort(key=lambda d: (d['time'], d['id']))
    return drafts


def write_if_changed(path, data):
    if path.exists() and path.read_bytes() == data:
        return False
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(data)
    tmp.replace(path)
    return True


def day_csv(drafts, names):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['account', 'time', 'text'])
    for d in drafts:
        if d['status'] == 'draft_ready' and d['text']:
            w.writerow([names.get(d['account_id'], d['account_id']), d['time'][11:16], d['text']])
    return ('﻿' + buf.getvalue()).encode('utf-8')


PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>星轨 · FD 发帖看板</title>
<style>
:root{--ink:#14161f;--mute:#6b7085;--line:#e6e9f4;--blue:#3b5bdb;--ok:#1f9d55;--okbg:#e3f7ea;--warn:#b7791f;--warnbg:#fdf3dc;--card:#fff;--sub:#f7f8fd}
*{box-sizing:border-box}
html{min-height:100%;background:linear-gradient(160deg,#c9d3fb 0%,#e3e8fc 28%,#eef2fd 55%,#dff2fb 100%)}
body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif;color:var(--ink)}
.wrap{max-width:1280px;margin:0 auto;padding:22px 18px 40px}
header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:10px}
.logo{width:58px;height:58px;border-radius:18px;background:rgba(255,255,255,.75);display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;color:var(--blue);box-shadow:0 4px 14px rgba(59,91,219,.12);flex:none}
.ttl{flex:1;min-width:220px}.ttl h1{margin:0;font-size:26px;letter-spacing:.5px}.ttl p{margin:2px 0 0;color:var(--mute);font-size:14px}
.stats{display:flex;gap:10px}
.stat{background:rgba(255,255,255,.85);border-radius:20px;padding:8px 18px;text-align:center;min-width:70px;box-shadow:0 2px 10px rgba(40,60,140,.07)}
.stat small{display:block;font-size:12px;color:var(--mute)}.stat b{font-size:24px;line-height:1.2}
.stat.s-done b{color:var(--ok)}.stat.s-todo b{color:var(--warn)}
.bar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:13px;color:var(--mute);background:rgba(255,255,255,.5);border-radius:14px;padding:8px 14px;margin:6px 0 18px}
.bar select{font:inherit;padding:3px 8px;border:1px solid var(--line);border-radius:8px;background:#fff}
.bar label{white-space:nowrap;cursor:pointer}.bar a{color:var(--blue);text-decoration:none}.bar .sp{flex:1}
.acct{display:flex;gap:18px;background:rgba(255,255,255,.72);border:1px solid rgba(255,255,255,.9);border-radius:26px;padding:20px;margin-bottom:22px;box-shadow:0 6px 24px rgba(40,60,140,.08)}
.side{width:210px;flex:none;border-right:1px solid var(--line);padding-right:16px}
.av{width:72px;height:72px;border-radius:50%;object-fit:cover;display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px;font-weight:700;margin-bottom:12px}
.side h2{margin:0;font-size:19px;line-height:1.3}.side .pf{font-size:13px;color:var(--mute);margin-top:4px}.side .hd{font-size:13.5px;color:#454a5e}
.side .bt{font-size:12px;color:var(--mute);margin-top:6px}
.pill{display:inline-block;margin-top:14px;background:#e7ecfe;color:var(--blue);font-weight:600;font-size:13px;border-radius:999px;padding:3px 14px}
.more{display:block;margin-top:12px;background:none;border:0;padding:0;font:inherit;font-size:14px;color:#454a5e;font-weight:600;cursor:pointer}
.grid{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:16px;align-content:start;min-width:0}
.grid .none{color:var(--mute);font-size:13px;padding:10px}
.post{background:var(--card);border-radius:20px;padding:16px 18px;display:flex;flex-direction:column;box-shadow:0 1px 4px rgba(40,60,140,.05);min-width:0}
.post.posted{opacity:.55}.post.hide{display:none}
.ph{display:flex;align-items:baseline;gap:8px;margin-bottom:8px}.ph small{font-size:12px;color:var(--mute)}
.ph .tm{color:var(--blue);font-weight:700;font-size:19px}.ph .st{margin-left:auto;font-size:12px;font-weight:600;border-radius:8px;padding:1px 9px;background:var(--warnbg);color:var(--warn);align-self:center}
.ph .st.ok{background:var(--okbg);color:var(--ok)}.ph .st.hold{background:#fde8e8;color:#c53030}
.meta{font-size:11.5px;color:#a0a5b8;margin-bottom:6px}
.txt{white-space:pre-wrap;word-break:break-word;font-size:15px;line-height:1.7;flex:1}
.part{border-top:1px dashed var(--line);padding-top:8px;margin-top:8px}.part:first-of-type{border-top:0;margin-top:0;padding-top:0}
.part .pr{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--mute)}
.cnt{font-size:11.5px;color:#a8adbf;margin-top:6px}.over{color:#d64545;font-weight:600}
.cp1{background:none;border:1px solid var(--line);border-radius:999px;font:inherit;font-size:12px;padding:1px 10px;cursor:pointer;color:#454a5e}.cp1.done{color:var(--ok);border-color:var(--ok)}
.foot{display:flex;align-items:center;justify-content:space-between;margin-top:14px;gap:10px}
.done-l{display:inline-flex;align-items:center;gap:8px;background:var(--okbg);color:var(--ok);font-weight:600;border-radius:999px;padding:6px 16px;cursor:pointer;font-size:14px;user-select:none}
.done-l input{width:18px;height:18px;margin:0;accent-color:var(--ok)}
.cp{display:inline-flex;align-items:center;gap:6px;background:#161a26;color:#fff;border:0;border-radius:999px;padding:8px 18px;font:inherit;font-size:14px;font-weight:600;cursor:pointer}
.cp.done{background:var(--ok)}.cp svg{width:15px;height:15px}
.empty{text-align:center;color:var(--mute);padding:40px}
@media (max-width:820px){
 .wrap{padding:14px 10px 30px}.ttl h1{font-size:21px}.logo{width:46px;height:46px;font-size:20px;border-radius:14px}
 .stats{width:100%}.stat{flex:1;padding:6px 8px}
 .acct{flex-direction:column;padding:14px;gap:12px;border-radius:22px}
 .side{width:auto;border-right:0;border-bottom:1px solid var(--line);padding:0 0 12px;display:grid;grid-template-columns:auto 1fr;column-gap:12px}
 .side .av{width:56px;height:56px;font-size:22px;margin:0;grid-row:span 4}
 .side .pill{margin-top:8px;justify-self:start;grid-column:2}.side .more{grid-column:2}
 .grid{grid-template-columns:1fr}
}
</style></head><body><div class="wrap">
<header><div class="logo">星</div>
<div class="ttl"><h1>星轨 · FD 发帖看板</h1><p>内容已备好 · 复制 → 粘贴 → 发布 → 勾选已发</p></div>
<div class="stats"><div class="stat"><small>全部</small><b id="nAll">0</b></div><div class="stat s-done"><small>已发</small><b id="nDone">0</b></div><div class="stat s-todo"><small>待发</small><b id="nTodo">0</b></div></div>
</header>
<div class="bar"><label>日期 <select id="day"></select></label>
<span id="flt"></span>
<label><input type="checkbox" id="hidePosted"> 隐藏已发</label>
<label><input type="checkbox" id="hideEmpty" checked> 隐藏无稿账号</label>
<span class="sp"></span><a id="csv" href="#" download>下载 CSV</a></div>
<main id="main"></main></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const ST_LABEL={draft_ready:'可发',HOLD:'HOLD（仲裁暂缓）',needs_review:'待复核',blocked:'失败',skipped:'跳过'};
const COLORS=['#6c5ce7','#e17055','#00a085','#2d7be0','#a68a00','#d63384','#0984e3','#e84393','#16a085','#8e44ad'];
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LS='fdops:posted:';const isPosted=id=>localStorage.getItem(LS+id)==='1';
const shown=new Set(JSON.parse(localStorage.getItem('fdops:statuses')||'["draft_ready"]'));
const expanded=new Set();
const days=Object.keys(D.days).sort().reverse();
const daySel=$('#day');daySel.innerHTML=days.map(d=>`<option>${d}</option>`).join('');
const want=location.hash.slice(1);if(days.includes(want))daySel.value=want;
$('#hidePosted').checked=localStorage.getItem('fdops:hidePosted')==='1';
const COPY_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
const londonDay=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
function when(t){
  if(!t)return '—';const day=t.slice(0,10),hm=t.slice(11,16);
  const today=londonDay(new Date()),diff=Math.round((Date.parse(day)-Date.parse(today))/864e5);
  const lbl={'-2':'前天','-1':'昨天','0':'今天','1':'明天','2':'后天'}[diff]||day.slice(5);
  return `${lbl} ${hm}`;
}
function cnt(t,w){return `${t.length} 字 · X计 ${w}${w>280?' <span class="over">超 280</span>':''}`}
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))>>>0;return COLORS[h%COLORS.length]}
function avatar(a){
  if(a.avatar)return `<img class="av" src="${a.avatar}" alt="">`;
  const ch=[...String(a.name||a.id).replace(/^[^\p{L}\p{N}]+/u,'')][0]||'?';
  return `<div class="av" style="background:linear-gradient(135deg,${hue(a.id)},${hue(a.id+'x')})">${esc(ch.toUpperCase())}</div>`;
}
function card(d,hidden){
  const p=isPosted(d.id),hold=d.status==='HOLD';
  const st=p?'<span class="st ok">已发</span>':hold?'<span class="st hold">HOLD</span>':d.status==='draft_ready'?'<span class="st">待发出</span>':`<span class="st">${esc(ST_LABEL[d.status]||d.status)}</span>`;
  let body;
  if(d.parts&&d.parts.length>1){
    body=d.parts.map((t,i)=>`<div class="part"><div class="pr"><span>${i+1}/${d.parts.length}</span><button class="cp1" data-t="${esc(t)}">复制</button></div><div class="txt">${esc(t)}</div><div class="cnt">${cnt(t,d.parts_w[i])}</div></div>`).join('');
  }else body=`<div class="txt">${esc(d.text)}</div><div class="cnt">${cnt(d.text,d.xw)}</div>`;
  const meta=[d.post_type,d.format].filter(Boolean).map(esc).join(' · ');
  return `<div class="post${p?' posted':''}${hidden?' hide':''}"><div class="ph"><small>建议发出</small><span class="tm">${when(d.time)}</span>${st}</div>${meta?`<div class="meta">${meta}</div>`:''}${body}
<div class="foot"><label class="done-l"><input type="checkbox" data-p="${esc(d.id)}" ${p?'checked':''}> 已发</label><button class="cp" data-t="${esc(d.text)}">${COPY_SVG}<span>一键复制</span></button></div></div>`;
}
function render(){
  const day=daySel.value;location.hash=day;const drafts=D.days[day]||[];
  $('#csv').href=day+'.csv';$('#csv').setAttribute('download','fd_'+day+'.csv');
  const sts=[...new Set(drafts.map(d=>d.status))].sort();
  $('#flt').innerHTML='状态 '+sts.map(s=>`<label><input type="checkbox" data-s="${esc(s)}" ${shown.has(s)?'checked':''}> ${esc(ST_LABEL[s]||s)} (${drafts.filter(d=>d.status===s).length})</label>`).join(' ');
  const hideP=$('#hidePosted').checked,hideE=$('#hideEmpty').checked;
  let all=0,done=0;const out=[];
  for(const a of D.accounts){
    const mine=drafts.filter(d=>d.account_id===a.id&&shown.has(d.status));
    const nDone=mine.filter(d=>isPosted(d.id)).length;all+=mine.length;done+=nDone;
    const cards=mine.filter(d=>!(hideP&&isPosted(d.id)));
    if(!cards.length&&hideE)continue;
    const open=expanded.has(a.id),lim=2;
    const more=cards.length>lim?`<button class="more" data-x="${esc(a.id)}">${open?'收起 ︿':`展开全部 ${cards.length} 条 ﹀`}</button>`:'';
    out.push(`<section class="acct"><div class="side">${avatar(a)}<h2>${esc(a.name)}</h2><div class="pf">X${a.lang?` · ${a.lang==='zh'?'中文':'English'}`:''}</div><div class="hd">${esc(a.handle?(a.handle.startsWith('@')?a.handle:'@'+a.handle):'@待填')}</div>${a.beat?`<div class="bt">${esc(a.beat)}</div>`:''}<span class="pill">待发 ${mine.length-nDone}/${mine.length}</span>${more}</div>
<div class="grid">${cards.length?cards.map((d,i)=>card(d,!open&&i>=lim)).join(''):'<div class="none">今日无可显示稿件</div>'}</div></section>`);
  }
  $('#main').innerHTML=out.join('')||'<p class="empty">无稿件</p>';
  $('#nAll').textContent=all;$('#nDone').textContent=done;$('#nTodo').textContent=all-done;
}
async function copy(t){try{await navigator.clipboard.writeText(t)}catch(_){const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}}
document.addEventListener('click',async e=>{
  const x=e.target.closest('.more');if(x){expanded.has(x.dataset.x)?expanded.delete(x.dataset.x):expanded.add(x.dataset.x);render();return}
  const b=e.target.closest('.cp,.cp1');if(!b)return;
  await copy(b.dataset.t);
  const lab=b.querySelector('span')||b,old=lab.textContent;
  lab.textContent='已复制';b.classList.add('done');setTimeout(()=>{lab.textContent=old;b.classList.remove('done')},1500);
});
document.addEventListener('change',e=>{
  const el=e.target;
  if(el.dataset.p){el.checked?localStorage.setItem(LS+el.dataset.p,'1'):localStorage.removeItem(LS+el.dataset.p)}
  else if(el.dataset.s){el.checked?shown.add(el.dataset.s):shown.delete(el.dataset.s);localStorage.setItem('fdops:statuses',JSON.stringify([...shown]))}
  else if(el.id==='hidePosted')localStorage.setItem('fdops:hidePosted',el.checked?'1':'0');
  render();
});
daySel.onchange=render;render();
</script></body></html>
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inbox', type=Path, default=INBOX)
    ap.add_argument('--out', type=Path, default=OUT)
    args = ap.parse_args()
    accounts = load_accounts()
    names = {a['id']: a['name'] for a in accounts}
    days = {}
    if args.inbox.is_dir():
        for d in sorted(p for p in args.inbox.iterdir() if p.is_dir() and DAY_RE.match(p.name)):
            days[d.name] = load_day(d)
    known = {a['id'] for a in accounts}
    for drafts in days.values():   # inbox accounts missing from fd20_accounts.json still get a section
        for d in drafts:
            if d['account_id'] not in known:
                known.add(d['account_id'])
                accounts.append({'id': d['account_id'], 'no': '', 'name': d['name'] or d['account_id'],
                                 'lang': d['lang'], 'beat': '', 'handle': '', 'avatar': ''})
    args.out.mkdir(parents=True, exist_ok=True)
    data = json.dumps({'accounts': accounts, 'days': days}, ensure_ascii=False, sort_keys=True)
    page = PAGE.replace('__DATA__', data.replace('</', '<\\/'))
    changed = [p.name for p, b in [(args.out / 'index.html', page.encode('utf-8'))] +
               [(args.out / f'{day}.csv', day_csv(dr, names)) for day, dr in days.items()]
               if write_if_changed(p, b)]
    total = sum(len(v) for v in days.values())
    print(f'ops dashboard: {len(days)} day(s), {total} draft(s) -> {args.out} (changed: {", ".join(changed) or "none"})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
