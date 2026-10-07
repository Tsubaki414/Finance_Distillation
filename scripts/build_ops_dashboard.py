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
<title>FD 发帖台</title>
<style>
:root{--bg:#f5f5f2;--card:#fff;--ink:#1b1b1b;--mute:#6b6b6b;--line:#e2e2dc;--acc:#1d6fd6;--ok:#2e7d32;--hold:#b26a00}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 -apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif;background:var(--bg);color:var(--ink)}
header{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);padding:10px 14px;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
header h1{font-size:17px;margin:0 8px 0 0}select,button{font:inherit}select{padding:4px 6px}
.flt label{margin-right:10px;white-space:nowrap;font-size:14px}.sum{color:var(--mute);font-size:13px}
main{max-width:860px;margin:0 auto;padding:12px}
.acct{margin:16px 0}.ah{display:flex;gap:10px;align-items:center;margin-bottom:6px}
.ah img,.ah .ph{width:40px;height:40px;border-radius:50%;object-fit:cover;background:#ddd;flex:none}
.ah b{font-size:16px}.ah .meta{color:var(--mute);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:8px 0}
.card.posted{opacity:.5}.tags{display:flex;flex-wrap:wrap;gap:6px;font-size:12.5px;color:var(--mute);margin-bottom:8px;align-items:center}
.tag{background:#f0f0ea;border-radius:4px;padding:1px 6px}.tag.st-draft_ready{background:#e6f4e7;color:var(--ok)}.tag.st-HOLD{background:#fdf0dc;color:var(--hold)}
.time{font-weight:600;color:var(--ink)}
.txt{white-space:pre-wrap;word-break:break-word;background:#fafaf7;border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:6px 0}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--mute)}
.cp{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:6px 14px;cursor:pointer;min-width:72px}.cp.done{background:var(--ok)}
.part{margin-top:8px}.part h4{margin:0;font-size:13px;color:var(--mute);font-weight:500}
.posted-l{font-size:14px;color:var(--ink);cursor:pointer}.empty{color:var(--mute);font-size:13px;margin-left:50px}
.over{color:#c62828;font-weight:600}
</style></head><body>
<header><h1>FD 发帖台</h1>
<label>日期 <select id="day"></select></label>
<span class="flt" id="flt"></span>
<label class="flt"><input type="checkbox" id="hidePosted"> 隐藏已发</label>
<label class="flt"><input type="checkbox" id="hideEmpty" checked> 隐藏无稿账号</label>
<a id="csv" href="#" download>下载 CSV</a>
<span class="sum" id="sum"></span></header>
<main id="main"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const ST_LABEL={draft_ready:'可发',HOLD:'HOLD（仲裁暂缓）',needs_review:'待复核',blocked:'失败',skipped:'跳过'};
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LS='fdops:posted:';const isPosted=id=>localStorage.getItem(LS+id)==='1';
const shown=new Set(JSON.parse(localStorage.getItem('fdops:statuses')||'["draft_ready"]'));
const days=Object.keys(D.days).sort().reverse();
const daySel=$('#day');daySel.innerHTML=days.map(d=>`<option>${d}</option>`).join('');
const want=location.hash.slice(1);if(days.includes(want))daySel.value=want;
$('#hidePosted').checked=localStorage.getItem('fdops:hidePosted')==='1';
function hhmm(t){return t?t.slice(11,16):'—'}
function count(t,w,lang){return `${t.length} 字 · X计 ${w}${w>280?' <span class="over">超 280</span>':''}`}
function copyBtn(text){return `<button class="cp" data-t="${esc(text)}">复制</button>`}
function render(){
  const day=daySel.value;location.hash=day;const drafts=D.days[day]||[];
  $('#csv').href=day+'.csv';$('#csv').setAttribute('download','fd_'+day+'.csv');
  const sts=[...new Set(drafts.map(d=>d.status))].sort();
  $('#flt').innerHTML='状态 '+sts.map(s=>`<label><input type="checkbox" data-s="${esc(s)}" ${shown.has(s)?'checked':''}> ${esc(ST_LABEL[s]||s)} (${drafts.filter(d=>d.status===s).length})</label>`).join('');
  const hideP=$('#hidePosted').checked,hideE=$('#hideEmpty').checked;
  let vis=0,posted=0;const out=[];
  for(const a of D.accounts){
    const mine=drafts.filter(d=>d.account_id===a.id);
    const cards=mine.filter(d=>shown.has(d.status)&&!(hideP&&isPosted(d.id)));
    posted+=mine.filter(d=>shown.has(d.status)&&isPosted(d.id)).length;
    if(!cards.length&&hideE)continue;vis+=cards.length;
    out.push(`<section class="acct"><div class="ah">${a.avatar?`<img src="${a.avatar}" alt="">`:'<span class="ph"></span>'}<div><b>${esc(a.name)}</b> <span class="meta">${esc(a.handle||'@待填')} · ${a.lang==='zh'?'中文':'English'} · #${a.no}</span><div class="meta">${esc(a.beat||'')}</div></div></div>`);
    if(!cards.length)out.push('<div class="empty">今日无可显示稿件</div>');
    for(const d of cards){
      const p=isPosted(d.id);
      let inner=`<div class="txt">${esc(d.text)}</div><div class="row"><span>${count(d.text,d.xw)}</span>${copyBtn(d.text)}</div>`;
      if(d.parts&&d.parts.length>1){
        inner=`<div class="row"><span>整串 ${d.parts.length} 条 · ${d.chars} 字</span>${copyBtn(d.text)}</div>`+d.parts.map((t,i)=>`<div class="part"><h4>${i+1}/${d.parts.length}</h4><div class="txt">${esc(t)}</div><div class="row"><span>${count(t,d.parts_w[i])}</span>${copyBtn(t)}</div></div>`).join('');
      }
      out.push(`<div class="card${p?' posted':''}"><div class="tags"><span class="time">建议 ${hhmm(d.time)} 伦敦</span><span class="tag">${esc(d.post_type)}</span>${d.format?`<span class="tag">${esc(d.format)}</span>`:''}<span class="tag st-${esc(d.status)}">${esc(ST_LABEL[d.status]||d.status)}</span></div>${inner}<div class="row" style="margin-top:8px"><label class="posted-l"><input type="checkbox" data-p="${esc(d.id)}" ${p?'checked':''}> 已发</label></div></div>`);
    }
    out.push('</section>');
  }
  $('#main').innerHTML=out.join('')||'<p class="empty">无稿件</p>';
  $('#sum').textContent=`显示 ${vis} 条 · 已发 ${posted} · 当日共 ${drafts.length} 条`;
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('.cp');if(!b)return;
  const t=b.dataset.t;
  try{await navigator.clipboard.writeText(t)}catch(_){const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}
  b.textContent='已复制';b.classList.add('done');setTimeout(()=>{b.textContent='复制';b.classList.remove('done')},1500);
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
