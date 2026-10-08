#!/usr/bin/env python3
"""Private review console for the fd20 compose inbox (static HTML + Vercel function; no model calls, no publishing).

Writes <out>/admin/index.html (served at /admin of the fd-ops-dashboard Vercel project; no auth, the site is unlisted
and both pages are noindex) and copies the deploy assets from scripts/ops_admin (api/decisions.js, package.json,
.vercelignore) into <out>. The public dashboard at / (scripts/build_ops_dashboard.py) is a separate page.

Per draft of the day: account, status (ready / HOLD / replaced / superseded / other), reasons, hard fails and
warnings (with detail from the run record), source link, the source spans of the units it was written from and its
claim ledger, reassignment / rewrite history, run id, model and spend. Plus per-run spend and model, per-account
ready counts against the target, and filters.

Actions (approve, HOLD, edit text, rewrite with note, 已发布 on / off) are POSTed to /api/decisions, stored one private
Vercel Blob per draft. The page polls the API every 60 s and after each action (another admin's changes, the ops
page's 已发 ticks), shows the last sync time, and never re-renders under an open edit / note panel. If the API is unreachable the page keeps them in localStorage; "导出决定 JSON" downloads every decision
of the day either way. scripts/apply_admin_decisions.py pulls them (API or exported file) into
live/store/admin_decisions/<day>.json, which build_ops_dashboard.py overlays on the next rebuild.
Idempotent: files are rewritten only when their content changes.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_ops_dashboard as ops  # noqa: E402

ROOT = ops.ROOT
RUNS = Path('/workspace/x/compose_runs')
ASSETS = Path(__file__).resolve().parent / 'ops_admin'
DECISIONS = ROOT / 'live/store/admin_decisions'
TARGET = 2   # ready drafts per account per day (daily_compose --per-account default)
MAX_UNITS, MAX_SPAN = 8, 600


def admin_status(row, replaced_by):
    s = ops.status_of(row)
    if s == 'superseded' and replaced_by:
        return 'replaced'
    return 'ready' if s == 'draft_ready' else s


def run_record(day, run_id, draft_id):
    p = RUNS / day / str(run_id) / 'drafts' / f'{draft_id}.json'
    if not p.exists():
        hits = sorted((RUNS / day).glob(f'*/drafts/{draft_id}.json')) if (RUNS / day).is_dir() else []
        p = hits[-1] if hits else None
    try:
        return json.loads(p.read_text()) if p else {}
    except (OSError, ValueError):
        return {}


def spans_of(rec):
    out = []
    for u in (rec.get('units') or [])[:MAX_UNITS]:
        spans = [{'p': s.get('paragraph_id'), 'start': s.get('start'), 'end': s.get('end'),
                  'text': (s.get('exact_text') or '')[:MAX_SPAN]} for s in u.get('source_spans') or []]
        out.append({'id': u.get('unit_id'), 'kind': u.get('kind'), 'statement': u.get('statement'), 'spans': spans})
    return out


def findings_of(row, rec):
    """Hard fails and warnings: the run record's post_checks carry detail; the inbox row (re-checked after relax /
    triage) decides which codes are current."""
    detail = {}
    for f in rec.get('post_checks') or []:
        detail.setdefault(f.get('code'), f.get('detail') or '')
    seen, out = set(), []
    for f in row.get('findings') or []:
        key = (f.get('code'), f.get('level'))
        if key in seen or not f.get('code'):
            continue
        seen.add(key)
        out.append({'code': f['code'], 'level': 'hard' if f.get('level') == 'hard' else 'warn',
                    'detail': detail.get(f['code'], '')})
    out.sort(key=lambda f: (f['level'] != 'hard', f['code']))
    return out


def reasons_of(row):
    out = []
    note = ops.note_of(row)
    if note:
        out.append(note)
    for r in (row.get('hold_reason'), (row.get('triage') or {}).get('reason')):
        if r and r not in out and not any(r in o for o in out):
            out.append(r)
    audit = row.get('audit') or {}
    if audit.get('reason') and not any(audit['reason'] in o for o in out):
        out.append(f"审稿 {audit.get('verdict')}：{audit['reason']}")
    if row.get('why') and row.get('why') not in ('ok', '') and ops.status_of(row) != 'draft_ready':
        out.append(f"pipeline：{row['why']}")
    if row.get('error'):
        out.append(f"错误：{row['error']}")
    return out


def history_of(row, replaced_by, names):
    h = []
    t = row.get('triage') or {}
    old = t.get('old') or {}
    if t.get('action'):
        moved = t.get('from') or ({'account_id': old.get('account_id'), 'name': old.get('name')}
                                  if old.get('account_id') and old.get('account_id') != row.get('account_id') else None)
        h.append({'at': ops.to_bjt(t.get('at')), 'kind': t['action'],
                  'text': (f"改派：{moved.get('name') or moved.get('account_id')} → {row.get('name')}" if moved else
                           {'hold': 'HOLD', 'release': '放行', 'reassign': '改派'}.get(t['action'], t['action'])) +
                          (f"（原状态 {old.get('draft_status')}{'，HOLD' if old.get('held') else ''}）" if old else ''),
                  'by': t.get('reviewer') or ''})
    arb = row.get('arbitration') or {}
    if arb.get('reassigned_to'):
        to = arb['reassigned_to']
        h.append({'at': '', 'kind': 'arbitration', 'by': 'arbitration',
                  'text': f"仲裁改派给 {names.get(to, to)}（{arb.get('reason_code') or ''}）"})
    if row.get('rewrite_of'):
        h.append({'at': '', 'kind': 'rewrite_of', 'by': '', 'text': f"重写自 {row['rewrite_of']}", 'ref': row['rewrite_of']})
    if replaced_by:
        h.append({'at': '', 'kind': 'replaced_by', 'by': '', 'text': f"已被 {replaced_by} 取代", 'ref': replaced_by})
    for rc in [row.get('recheck'), row.get('requalified')]:
        if rc:
            h.append({'at': ops.to_bjt(rc.get('at')), 'kind': 'recheck', 'by': rc.get('version') or '',
                      'text': f"规则复检（原 {rc.get('old_draft_status') or '-'}，原硬伤 {', '.join(rc.get('old_hard') or []) or '无'}）"})
    if row.get('note'):
        h.append({'at': '', 'kind': 'note', 'by': '', 'text': row['note']})
    return h


def load_day(day_dir, names):
    day = day_dir.name
    rows = []
    for f in sorted(day_dir.glob('*.json')):
        try:
            rows.append(json.loads(f.read_text()))
        except (OSError, ValueError) as exc:
            print(f'skip {f}: {exc}', file=sys.stderr)
    for r in rows:
        r.setdefault('id', '')
    replaced = {r['rewrite_of']: r['id'] for r in rows if r.get('rewrite_of')}
    times = {d['id']: d['time'] for d in ops.clamp_times(ops.load_day(day_dir), day)}
    drafts = []
    for row in rows:
        rec = run_record(day, row.get('run_id'), row['id'])
        body = (row.get('body') or '').strip()
        src = row.get('source') or {}
        rb = replaced.get(row['id'])
        drafts.append({
            'id': row['id'], 'run': row.get('run_id') or '', 'account_id': row.get('account_id'),
            'name': row.get('name') or names.get(row.get('account_id'), row.get('account_id')), 'lang': row.get('lang'),
            'status': admin_status(row, rb), 'raw_status': row.get('draft_status') or row.get('status') or '',
            'text': body, 'xw': ops.x_weight(body),
            'time': times.get(row['id'], ''), 'stored': ops.to_bjt(row.get('stored_at')),
            'post_type': row.get('post_type') or '', 'format': (row.get('post_format') or {}).get('type') or '',
            'angle': (row.get('angle') or {}).get('id') or '',
            'view': (row.get('stance') or {}).get('account_view') or '',
            'reasons': reasons_of(row), 'findings': findings_of(row, rec),
            'source': {k: src.get(k) for k in ('url', 'title', 'publisher', 'published_at', 'lang')},
            'attribution': row.get('attribution_line') or '',
            'spans': spans_of(rec),
            'claims': [{'claim': c.get('claim'), 'unit': c.get('unit_id')} for c in rec.get('claim_ledger') or []][:12],
            'history': history_of(row, rb, names),
            'models': row.get('models') or [], 'spend': round(float(row.get('spend_usd') or 0), 4),
            **ops.media_of(row), 'mode_why': row.get('post_mode_why') or '',
        })
    drafts.sort(key=lambda d: (d['account_id'] or '', d['time'], d['id']))
    return drafts


def load_runs(day, drafts):
    by_run = {}
    for d in drafts:
        r = by_run.setdefault(d['run'], {'run': d['run'], 'drafts': 0, 'ready': 0, 'row_spend': 0.0, 'models': set()})
        r['drafts'] += 1
        r['ready'] += d['status'] == 'ready'
        r['row_spend'] += d['spend']
        r['models'].update(d['models'])
    out = []
    run_dirs = sorted(p for p in (RUNS / day).iterdir() if p.is_dir()) if (RUNS / day).is_dir() else []
    for p in run_dirs:
        try:
            s = json.loads((p / 'summary.json').read_text())
        except (OSError, ValueError):
            s = None
        r = by_run.pop(p.name, {'run': p.name, 'drafts': 0, 'ready': 0, 'row_spend': 0.0, 'models': set()})
        if s is None and not r['drafts']:
            continue   # aborted / select-only run with nothing in the inbox
        out.append(_run_row(r, s))
    out += [_run_row(r, None) for r in by_run.values()]   # e.g. smoke runs stored elsewhere
    out.sort(key=lambda r: r['run'])
    return out


def _run_row(r, s):
    s = s or {}
    models = sorted(set(s.get('models') or []) | r['models'])
    return {'run': r['run'], 'spend': round(float(s['spend_usd']) if 'spend_usd' in s else r['row_spend'], 4),
            'spend_src': 'summary' if 'spend_usd' in s else 'drafts', 'budget': s.get('budget_usd'),
            'models': models, 'compose_model': s.get('compose_model') or '',
            'composed': s.get('composed'), 'held': s.get('held'), 'errors': len(s.get('errors') or []),
            'drafts': r['drafts'], 'ready': r['ready']}


def local_decisions(day):
    p = DECISIONS / f'{day}.json'
    try:
        return json.loads(p.read_text()).get('decisions') or {}
    except (OSError, ValueError):
        return {}


STALE = ('middleware.js',)   # deploy assets that were removed from scripts/ops_admin


def copy_assets(out):
    changed = []
    for name in STALE:
        if (out / name).exists():
            (out / name).unlink()
            changed.append(f'-{name}')
    for src in sorted(p for p in ASSETS.rglob('*') if p.is_file()):
        dst = out / src.relative_to(ASSETS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if ops.write_if_changed(dst, src.read_bytes()):
            changed.append(str(src.relative_to(ASSETS)))
    return changed


PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>星轨 · FD 审稿台</title>
<style>
__ROOTVARS__
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;font:14.5px/1.6 var(--sans);color:var(--ink);-webkit-font-smoothing:antialiased}
.wrap{max-width:1320px;margin:0 auto;padding:28px 24px 64px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.logo{width:40px;height:40px;border-radius:10px;background:var(--btn);color:var(--btn-ink);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:600;flex:none}
.ttl{flex:1;min-width:220px}.ttl h1{margin:0;font-size:20px;font-weight:650;letter-spacing:-.01em;line-height:1.3}.ttl p{margin:2px 0 0;color:var(--mute);font-size:13px}
.stats{display:flex;gap:8px;flex-wrap:wrap}
.stat{display:inline-flex;align-items:baseline;gap:8px;background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:5px 14px}
.stat small{font-size:12px;color:var(--mute)}.stat b{font:600 16px/1.2 var(--mono);font-variant-numeric:tabular-nums}
.stat.ok b{color:var(--accent)}.stat.hd b{color:var(--hold)}.stat.wn b{color:var(--warn)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:16px}
.panel h2{margin:0 0 10px;font-size:14px;font-weight:620;color:var(--ink2)}
.cols{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:600;color:var(--mute);font-size:12px;border-bottom:1px solid var(--line);padding:4px 8px 6px}
td{border-bottom:1px solid var(--line2);padding:5px 8px;vertical-align:top}
td.n,th.n{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
tr.short td.n.r{color:var(--warn);font-weight:600}tr.met td.n.r{color:var(--accent);font-weight:600}
tr.clk{cursor:pointer}tr.clk:hover td{background:var(--sunk)}
.mono{font-family:var(--mono);font-size:12px}
#runs td.mono{white-space:nowrap;font-size:11.5px}
.panel{overflow-x:auto}
.bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;font-size:13px;color:var(--mute);padding:12px 0 14px;margin:0 0 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
.bar select,.bar input[type=search]{font:inherit;color:var(--ink);padding:4px 10px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
.bar input[type=search]{min-width:180px}
.bar label{white-space:nowrap;cursor:pointer;display:inline-flex;align-items:center;gap:5px}.bar .sp{flex:1}
input[type=checkbox]{accent-color:var(--accent)}
.btn{display:inline-flex;align-items:center;gap:6px;background:var(--surface);color:var(--ink2);border:1px solid var(--line);border-radius:8px;padding:5px 12px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--faint)}.btn:active{transform:translateY(1px)}.btn:disabled{color:var(--faint);cursor:default}
.btn.pri{background:var(--btn);color:var(--btn-ink);border-color:var(--btn)}.btn.pri:hover{opacity:.88}
.btn.ok{color:var(--accent)}.btn.hd{color:var(--hold)}
.btn.on.ok{background:var(--accent);border-color:var(--accent);color:#fafafa}.btn.on.hd{background:var(--hold);border-color:var(--hold);color:#fafafa}.btn.on.rw{background:var(--info);border-color:var(--info);color:#fafafa}
.sync{font-size:12px;color:var(--mute)}.sync.bad{color:var(--hold)}
.list{display:grid;gap:12px}
.d{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.95fr);gap:18px}
.d.hide{display:none}
.dh{grid-column:1/-1;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--mute)}
.dh b{color:var(--ink);font-size:15px;font-weight:620}
.tag{display:inline-block;font-size:11.5px;font-weight:600;border-radius:999px;padding:1px 9px;white-space:nowrap;background:var(--sunk);color:var(--ink2);border:1px solid var(--line2)}
.tag.ready{background:var(--accent-bg);color:var(--accent);border-color:transparent}.tag.HOLD{background:var(--holdbg);color:var(--hold);border-color:transparent}
.tag.replaced,.tag.superseded{background:var(--infobg);color:var(--info);border-color:transparent}
.tag.dec{border-style:dashed}
.meta{margin-left:auto;font:12px var(--mono);color:var(--faint);font-variant-numeric:tabular-nums}
.txt{white-space:pre-wrap;word-break:break-word;font-size:15px;line-height:1.72;color:var(--ink);background:var(--sunk);border:1px solid var(--line2);border-radius:10px;padding:14px}
.txt:lang(en){font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,"Helvetica Neue",Arial,sans-serif;line-height:1.62}
.txt.edited{border-color:var(--accent)}
textarea{width:100%;font:15px/1.65 var(--sans);color:var(--ink);background:var(--surface);border:1px solid var(--accent);border-radius:10px;padding:12px;resize:vertical;min-height:150px}
textarea.note{min-height:64px;font-size:13.5px;border-color:var(--line)}
.cnt{font:11.5px/1.5 var(--mono);color:var(--faint);margin-top:6px}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center}
.edit{margin-top:10px;display:none}.edit.open{display:block}.edit .acts{margin-top:8px}
.side{display:grid;gap:10px;align-content:start;min-width:0;font-size:13px}
.blk h3{margin:0 0 4px;font-size:12px;font-weight:600;color:var(--mute)}
.why{color:var(--warn);background:var(--warnbg);border-radius:8px;padding:6px 10px;font-size:12.5px;line-height:1.5;margin-bottom:4px}
.why.dec{color:var(--info);background:var(--infobg)}
.fd{display:flex;gap:6px;align-items:baseline;font-size:12.5px;line-height:1.5}.fd .c{font:600 11.5px var(--mono);border-radius:999px;padding:0 8px;white-space:nowrap}
.fd.hard .c{background:var(--holdbg);color:var(--hold)}.fd.warn .c{background:var(--warnbg);color:var(--warn)}.fd span.dt{color:var(--ink2)}
.src a{color:var(--ink);font-weight:600;text-decoration:underline;text-underline-offset:3px;text-decoration-color:var(--line)}
.src .sm{color:var(--mute);font-size:12px}
.tag.mode{background:var(--infobg);color:var(--info)}.tag.mode.hot{background:var(--holdbg);color:var(--hold)}
.mtgt{font-size:12.5px;margin-top:8px}.mtgt a{color:var(--ink);font-weight:600;text-decoration:underline;text-underline-offset:3px;text-decoration-color:var(--line)}
.img{margin:10px 0 0;max-width:560px}.img img{display:block;width:100%;height:auto;border-radius:8px;border:1px solid var(--line2);background:#131722}
.img figcaption{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:6px;font-size:11.5px;color:var(--faint)}
.img .dl{color:var(--ink);text-decoration:none;font-weight:600;font-size:12.5px;border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:2px 10px;white-space:nowrap}
details{border-top:1px solid var(--line2);padding-top:6px}
summary{cursor:pointer;color:var(--ink2);font-weight:600;font-size:12.5px}
.u{margin:8px 0}.u .st{color:var(--ink2)}.u .k{font:11px var(--mono);color:var(--faint);margin-right:6px}
.u blockquote{margin:4px 0 0;padding:4px 10px;border-left:2px solid var(--line);color:var(--mute);font-size:12.5px;white-space:pre-wrap;word-break:break-word}
.u blockquote .pos{font:10.5px var(--mono);color:var(--faint);display:block}
.cl{margin:4px 0;font-size:12.5px;color:var(--ink2)}.cl .mono{color:var(--faint)}
.hi{font-size:12.5px;color:var(--ink2);line-height:1.5;margin:3px 0}.hi .mono{color:var(--faint)}
.hi a{color:var(--ink2)}
.empty{text-align:center;color:var(--mute);padding:48px 16px}
button:focus-visible,select:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:900px){.cols{grid-template-columns:1fr}.d{grid-template-columns:1fr}.wrap{padding:16px 12px 40px}.bar{position:static}}
__NAVCSS__
</style></head><body><div class="wrap">
__NAV__
<header><div class="logo">审</div>
<div class="ttl"><h1>星轨 · FD 审稿台</h1><p>仅限内部 · 批准 / HOLD / 改稿 / 要求重写 / 已发布；决定实时同步到运营看板（每 60 秒刷新） · <span id="upd"></span></p></div>
<div class="stats" id="stats"></div></header>
<div class="cols">
<section class="panel"><h2>各账号 vs 目标（每号 <span id="tgt"></span> 篇可发）</h2><table id="accts"></table></section>
<section class="panel"><h2>运行记录：花费与模型</h2><table id="runs"></table></section>
</div>
<div class="bar">
<label>日期 <select id="day"></select></label>
<label>账号 <select id="fAcct"></select></label>
<label>状态 <select id="fSt"></select></label>
<label>语言 <select id="fLang"><option value="">全部</option><option value="zh">中文</option><option value="en">English</option></select></label>
<label>运行 <select id="fRun"></select></label>
<label>决定 <select id="fDec"><option value="">全部</option><option value="none">未处理</option><option value="approve">已批准</option><option value="published">已发布</option><option value="hold">已 HOLD</option><option value="rewrite">待重写</option><option value="edit">仅改稿</option><option value="edited">有改稿</option></select></label>
<label><input type="checkbox" id="fHard"> 有硬伤</label>
<label><input type="checkbox" id="fWarn"> 有警告</label>
<input type="search" id="fQ" placeholder="搜索正文 / 来源 / ID">
<span class="sp"></span><span class="sync" id="sync"></span>
<button class="btn" id="rf" title="重新读取最新稿件和所有人的决定">刷新</button><button class="btn" id="exp">导出决定 JSON</button>
</div>
<div id="shown" class="sync" style="margin:-6px 0 10px"></div>
<main class="list" id="list"></main></div>
<script id="data" type="application/json">__DATA__</script>
<script>
let D=JSON.parse(document.getElementById('data').textContent),RAW=document.getElementById('data').textContent;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ST={ready:'可发',HOLD:'HOLD',replaced:'已替换',superseded:'已作废',needs_review:'待复核',blocked:'失败',skipped:'跳过'};
const DEC={approve:'已批准',published:'已发布',unpublish:'撤销已发布',hold:'已 HOLD',rewrite:'待重写',edit:'改稿'};
__SHARED__
let days=[];
const latest=()=>days.find(d=>(D.days[d]||[]).length)||days[0]||'';   // newest day with drafts (Beijing dates)
function fillDays(keep){days=Object.keys(D.days).sort().reverse();$('#day').innerHTML=days.map(d=>`<option>${d}</option>`).join('');$('#day').value=days.includes(keep)?keep:latest()}
fillDays(location.hash.slice(1));
let follow=$('#day').value===latest();   // follow the newest day until someone picks another one
$('#tgt').textContent=D.target;
const bjtTime=d=>d.toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
let dec={},syncAt=null,dirty=false;   // dec: id -> decision (server, then local pending on top)
const pendKey=day=>'fdadmin:pending:'+day;
const pending=day=>JSON.parse(localStorage.getItem(pendKey(day))||'{}');
function setPending(day,p){Object.keys(p).length?localStorage.setItem(pendKey(day),JSON.stringify(p)):localStorage.removeItem(pendKey(day))}
function sync(msg,bad){const s=$('#sync');s.textContent=msg;s.classList.toggle('bad',!!bad)}
// another admin's changes arrive by polling (every 60 s, after each action, on 刷新); an open edit / note panel is
// never re-rendered under the typist: the refresh waits until it closes
const editing=()=>!!document.querySelector('.edit.open');
async function load(){
  const day=$('#day').value,next=Object.assign({},D.local[day]||{});
  try{
    const r=await fetch('/api/decisions?day='+encodeURIComponent(day),{credentials:'same-origin',cache:'no-store'});
    if(!r.ok)throw new Error(r.status);
    Object.assign(next,(await r.json()).decisions||{});
    const p=pending(day);
    for(const id of Object.keys(p)){const j=await post(p[id]);if(j){next[id]=j;delete p[id]}}
    setPending(day,p);syncAt=new Date();
    const n=Object.keys(p).length;
    sync(n?`${n} 条决定未同步（已存本机）`:`已同步到云端 · 最后更新 北京时间 ${bjtTime(syncAt)}`,n>0);
  }catch(e){sync('云端不可用，决定存本机，记得导出 JSON'+(syncAt?` · 上次同步 ${bjtTime(syncAt)}`:''),true)}
  if(day!==$('#day').value)return;
  dec=Object.assign(next,pending(day));
  if(editing())dirty=true;else render();
}
async function post(d){
  try{
    const r=await fetch('/api/decisions',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
    if(!r.ok)throw new Error(r.status);
    return (await r.json()).decision||null;
  }catch(e){return null}
}
async function decide(d,action,extra){
  const day=$('#day').value,prev=dec[d.id]||null,flag=action==='published'||action==='unpublish';
  const body={day,id:d.id,account_id:d.account_id,action};
  // published / unpublish leave text and note to the server (kept); other actions carry the current ones
  if(extra&&'text' in extra)body.text=extra.text;else if(!flag)body.text=(prev&&prev.text)||null;
  if(extra&&'note' in extra)body.note=extra.note;else if(!flag)body.note=(prev&&prev.note)||'';
  const local=nextDecision(prev,body,new Date().toISOString());   // the server's own rule (api/decisions.js)
  dec[d.id]=local;render();
  const j=await post(body);
  if(j){dec[d.id]=j;const p=pending(day);delete p[d.id];setPending(day,p);sync('已保存 北京时间 '+bjtTime(new Date()));render();load()}
  else{const p=pending(day);p[d.id]=local;setPending(day,p);sync('保存失败，已存本机（可导出 JSON）',true);render()}
}
async function refreshData(cache){   // new days / rebuilt drafts: re-read this page's own data block
  try{
    const r=await fetch(location.pathname,{cache});if(!r.ok)throw new Error(r.status);
    const m=(await r.text()).match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/);
    if(!m||m[1]===RAW)return;
    D=JSON.parse(m[1]);RAW=m[1];fillDays(follow?'':$('#day').value);follow=$('#day').value===latest();upd();
  }catch(e){sync('页面数据刷新失败',true)}
}
function effStatus(d){const x=dec[d.id];if(!x||x.action==='clear'||x.action==='edit')return d.status;return x.action==='approve'||x.action==='published'?'ready':'HOLD'}
function counts(day){
  const ds=D.days[day]||[],acc={};
  for(const a of D.accounts)acc[a.id]={a,ready:0,eff:0,hold:0,total:0,dec:0};
  for(const d of ds){const c=acc[d.account_id]||(acc[d.account_id]={a:{id:d.account_id,name:d.name},ready:0,eff:0,hold:0,total:0,dec:0});
    c.total++;if(d.status==='ready')c.ready++;if(d.status==='HOLD')c.hold++;if(effStatus(d)==='ready')c.eff++;if(dec[d.id]&&dec[d.id].action!=='clear')c.dec++}
  return Object.values(acc);
}
function tables(day){
  const cs=counts(day);
  $('#accts').innerHTML='<tr><th>账号</th><th class="n">可发</th><th class="n">审后可发</th><th class="n">HOLD</th><th class="n">全部</th><th class="n">已处理</th></tr>'+
    cs.map(c=>`<tr class="clk ${c.eff>=D.target?'met':'short'}" data-a="${esc(c.a.id)}"><td>${esc(c.a.name)} <span class="mono" style="color:var(--faint)">${esc(c.a.lang||'')}${{new:' · 新号',spare_active:' · 备用号'}[c.a.status]||''}</span></td><td class="n">${c.ready}</td><td class="n r">${c.eff}/${D.target}</td><td class="n">${c.hold}</td><td class="n">${c.total}</td><td class="n">${c.dec}</td></tr>`).join('');
  const rs=D.runs[day]||[];const tot=rs.reduce((s,r)=>s+r.spend,0);
  $('#runs').innerHTML='<tr><th>run</th><th>模型</th><th class="n">花费 $</th><th class="n">稿/可发</th><th class="n">HOLD</th><th class="n">错误</th></tr>'+
    rs.map(r=>`<tr class="clk" data-r="${esc(r.run)}"><td class="mono">${esc(r.run)}</td><td class="mono">${esc((r.compose_model?[r.compose_model]:r.models).join(', ')||'-')}</td><td class="n">${r.spend.toFixed(2)}${r.spend_src==='drafts'?'*':''}${r.budget?` <span style="color:var(--faint)">/ ${r.budget}</span>`:''}</td><td class="n">${r.drafts}/${r.ready}</td><td class="n">${r.held??'-'}</td><td class="n">${r.errors||''}</td></tr>`).join('')+
    `<tr><td><b>合计</b></td><td></td><td class="n"><b>${tot.toFixed(2)}</b></td><td class="n">${rs.reduce((s,r)=>s+r.drafts,0)}</td><td></td><td></td></tr>`+
    (rs.some(r=>r.spend_src==='drafts')?'<tr><td colspan="6" style="color:var(--faint);font-size:12px">* 无 summary.json 的运行按稿件 spend_usd 合计</td></tr>':'');
  const ds=D.days[day]||[],n=s=>ds.filter(d=>effStatus(d)===s).length;
  $('#stats').innerHTML=`<div class="stat"><small>全部</small><b>${ds.length}</b></div><div class="stat ok"><small>审后可发</small><b>${n('ready')}</b></div><div class="stat hd"><small>HOLD</small><b>${n('HOLD')}</b></div><div class="stat wn"><small>未处理</small><b>${ds.filter(d=>!dec[d.id]||dec[d.id].action==='clear').length}</b></div><div class="stat"><small>花费</small><b>$${tot.toFixed(2)}</b></div>`;
}
function filters(day){
  const ds=D.days[day]||[],keep=(sel,html)=>{const v=$(sel).value;$(sel).innerHTML=html;if([...$(sel).options].some(o=>o.value===v))$(sel).value=v};
  const accts=[...new Map(ds.map(d=>[d.account_id,d.name])).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
  keep('#fAcct','<option value="">全部</option>'+accts.map(([id,n])=>`<option value="${esc(id)}">${esc(n)}</option>`).join(''));
  const sts=[...new Set(ds.map(d=>d.status))].sort();
  keep('#fSt','<option value="">全部</option>'+sts.map(s=>`<option value="${esc(s)}">${esc(ST[s]||s)} (${ds.filter(d=>d.status===s).length})</option>`).join(''));
  keep('#fRun','<option value="">全部</option>'+[...new Set(ds.map(d=>d.run))].sort().map(r=>`<option>${esc(r)}</option>`).join(''));
}
function match(d){
  const x=dec[d.id],a=x&&x.action!=='clear'?x.action:'none';
  if($('#fAcct').value&&d.account_id!==$('#fAcct').value)return false;
  if($('#fSt').value&&d.status!==$('#fSt').value)return false;
  if($('#fLang').value&&d.lang!==$('#fLang').value)return false;
  if($('#fRun').value&&d.run!==$('#fRun').value)return false;
  const fd=$('#fDec').value;if(fd&&(fd==='edited'?!(x&&x.text):fd==='published'?!isPublished(x):a!==fd))return false;
  if($('#fHard').checked&&!d.findings.some(f=>f.level==='hard'))return false;
  if($('#fWarn').checked&&!d.findings.some(f=>f.level==='warn'))return false;
  const q=$('#fQ').value.trim().toLowerCase();
  if(q&&![d.text,d.id,d.name,d.source.title,d.source.publisher,d.source.url,d.reasons.join(' ')].join(' ').toLowerCase().includes(q))return false;
  return true;
}
function card(d){
  const x=dec[d.id],act=x&&x.action!=='clear'?x.action:'',pub=isPublished(x),text=x&&x.text?x.text:d.text,lg=d.lang==='en'?'en':'zh-CN';
  const n=[...text].length;
  const fnd=d.findings.length?`<div class="blk"><h3>硬伤 / 警告</h3>${d.findings.map(f=>`<div class="fd ${f.level}"><span class="c">${f.level==='hard'?'硬':'警'} ${esc(f.code)}</span>${f.detail?`<span class="dt">${esc(f.detail)}</span>`:''}</div>`).join('')}</div>`:'';
  const why=(d.reasons.length||act)?`<div class="blk"><h3>原因</h3>${d.reasons.map(r=>`<div class="why">${esc(r)}</div>`).join('')}${act?`<div class="why dec">Fiona：${esc(DEC[act]||act)}${pub&&act!=='published'?' · 已发布':''}${x.note?' · '+esc(x.note):''}${x.text?' · 已改稿':''}</div>`:''}</div>`:'';
  const s=d.source;
  const src=`<div class="blk src"><h3>来源</h3>${s.url?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title||s.url)}</a>`:esc(s.title||'-')}<div class="sm">${esc(s.publisher||'')}${s.published_at?' · '+esc(s.published_at.slice(0,16).replace('T',' '))+' UTC':''}${s.lang?' · '+esc(s.lang):''}${d.attribution?' · 署名：'+esc(d.attribution):''}</div>
${d.spans.length?`<details><summary>原文片段（${d.spans.length} 个内容单元）</summary>${d.spans.map(u=>`<div class="u"><span class="k">${esc(u.kind||'')}</span><span class="st">${esc(u.statement||'')}</span>${u.spans.map(p=>`<blockquote><span class="pos">${esc(p.p||'')} [${p.start??''}–${p.end??''}]</span>${esc(p.text)}</blockquote>`).join('')}</div>`).join('')}</details>`:'<div class="sm">无片段记录</div>'}
${d.claims.length?`<details><summary>论断 → 单元（${d.claims.length}）</summary>${d.claims.map(c=>`<div class="cl">${esc(c.claim)} <span class="mono">${esc(c.unit||'无出处')}</span></div>`).join('')}</details>`:''}</div>`;
  const hist=[...d.history.map(h=>`<div class="hi"><span class="mono">${esc((h.at||'').slice(5,16).replace('T',' '))}</span> ${h.ref?`<a href="#" data-goto="${esc(h.ref)}">${esc(h.text)}</a>`:esc(h.text)}${h.by?` <span class="mono">· ${esc(h.by.slice(0,60))}</span>`:''}</div>`),
    ...((x&&x.history)||[]).map(h=>`<div class="hi"><span class="mono">${esc(new Date(h.at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}).slice(5,16))}</span> Fiona：${esc(DEC[h.action]||(h.action==='clear'?'撤销':h.action))}${h.note?' · '+esc(h.note):''}${h.text?' · 改稿':''}</div>`)];
  const histB=hist.length?`<div class="blk"><h3>改派 / 重写 / 决定记录</h3>${hist.join('')}</div>`:'';
  return `<article class="d" id="d-${esc(d.id)}" data-id="${esc(d.id)}">
<div class="dh"><b>${esc(d.name)}</b><span class="tag ${esc(d.status)}">${esc(ST[d.status]||d.status)}</span>${{quote:'<span class="tag mode">引用</span>',reply:'<span class="tag mode">回复</span>'}[d.mode]||''}${d.heat_led?'<span class="tag mode">热度</span>':''}${d.archive?`<span class="tag mode">${d.archive_variant==='evergreen'?'常青':'回看'}</span>`:''}${d.hotspot?'<span class="tag mode hot">热点</span>':''}${act&&act!=='published'?`<span class="tag dec ${act==='approve'?'ready':act==='edit'?'':'HOLD'}">${esc(DEC[act])}</span>`:''}${pub?'<span class="tag dec ready">已发布</span>':''}<span>${esc(d.lang==='en'?'English':'中文')} · ${esc(d.format||d.post_type)}${d.angle?' · '+esc(d.angle):''}</span><span class="meta">${esc(d.time.slice(11,16))} 北京 · ${esc(d.run)} · ${esc(d.models.join(', ')||'-')} · $${d.spend.toFixed(3)} · ${esc(d.id)}</span></div>
<div><div class="txt${x&&x.text?' edited':''}" lang="${lg}">${esc(text)}</div><div class="cnt">${n} ${d.lang==='en'?'字符':'字'}${x&&x.text?' · 已改稿（原稿 '+[...d.text].length+'）':''}${d.view?' · 观点：'+esc(d.view):''}</div>
${d.hotspot?`<div class="mtgt">热点母题：${esc(d.hotspot)}${d.hotspot_meta?` <span class="sm">· ${esc(d.hotspot_meta)}</span>`:''}</div>`:''}${d.archive&&d.archive_url?`<div class="mtgt">${d.archive_variant==='evergreen'?'常青原帖':'回看原帖'}：<a href="${esc(d.archive_url)}" target="_blank" rel="noopener noreferrer">打开原帖</a></div>`:''}${d.target&&d.mode!=='original'?`<div class="mtgt">${d.mode==='reply'?'回复':'引用'}：<a href="${esc(d.target)}" target="_blank" rel="noopener noreferrer">打开原帖</a>${d.mode_why?` <span class="sm">· ${esc(d.mode_why)}</span>`:''}</div>`:''}
${(d.media||[]).map(m=>`<figure class="img"><a href="/${esc(m.src||m.path)}" target="_blank" rel="noopener"><img src="/${esc(m.src||m.path)}" alt="${esc(m.alt)}" loading="lazy"></a><figcaption><span>${esc([m.credit?'数据：'+m.credit:'',m.updated?'图更新于 北京时间 '+m.updated:''].filter(Boolean).join(' · '))}</span><a class="dl" href="/${esc(m.src||m.path)}" download="${esc(m.path.split('/').pop())}">下载图片</a></figcaption></figure>`).join('')}
<div class="acts"><button class="btn ok${act==='approve'?' on':''}" data-a="approve">批准</button><button class="btn hd${act==='hold'?' on':''}" data-a="hold">HOLD</button><button class="btn" data-a="edit">改稿</button><button class="btn${pub?' on ok':''}" data-a="published" title="人工发出后标记（不会自动发帖）；再点一次撤销">已发布</button><button class="btn${act==='rewrite'?' on rw':''}" data-a="rewrite">要求重写</button>${act||pub||x&&x.text?'<button class="btn" data-a="clear">撤销决定</button>':''}</div>
<div class="edit" data-panel="edit"><textarea data-f="text" lang="${lg}">${esc(text)}</textarea><div class="acts"><button class="btn pri" data-a="save-approve">保存并批准</button><button class="btn" data-a="save">只保存改稿</button>${x&&x.text?'<button class="btn" data-a="revert">恢复原稿</button>':''}<button class="btn" data-a="cancel">取消</button></div></div>
<div class="edit" data-panel="note"><textarea class="note" data-f="note" placeholder="HOLD 原因 / 给重写的具体意见"></textarea><div class="acts"><button class="btn pri" data-a="note-ok">提交</button><button class="btn" data-a="cancel">取消</button></div></div></div>
<div class="side">${why}${fnd}${src}${histB}</div></article>`;
}
function render(){
  const day=$('#day').value;dirty=false;
  history.replaceState(null,'',location.pathname+location.search+(follow||!day?'':'#'+day));
  filters(day);tables(day);
  const ds=(D.days[day]||[]),vis=ds.filter(match);
  $('#list').innerHTML=vis.map(card).join('')||'<p class="empty">当前筛选下没有稿件</p>';
  $('#shown').textContent=`显示 ${vis.length} / ${ds.length} 篇`;
}
let noteFor=null;
document.addEventListener('click',async e=>{
  const g=e.target.closest('[data-goto]');if(g){e.preventDefault();for(const s of ['#fAcct','#fSt','#fRun','#fDec','#fLang'])$(s).value='';$('#fHard').checked=$('#fWarn').checked=false;$('#fQ').value='';render();const el=document.getElementById('d-'+g.dataset.goto);if(el)el.scrollIntoView({behavior:'smooth',block:'start'});return}
  const tr=e.target.closest('tr.clk');if(tr){if(tr.dataset.a)$('#fAcct').value=$('#fAcct').value===tr.dataset.a?'':tr.dataset.a;if(tr.dataset.r)$('#fRun').value=$('#fRun').value===tr.dataset.r?'':tr.dataset.r;render();return}
  const b=e.target.closest('button[data-a]');if(!b)return;
  const card=b.closest('.d'),day=$('#day').value,d=(D.days[day]||[]).find(x=>x.id===card.dataset.id),a=b.dataset.a;
  const panel=n=>card.querySelector(`[data-panel="${n}"]`);
  const close=()=>card.querySelectorAll('.edit').forEach(p=>p.classList.remove('open'));
  if(a==='approve')return decide(d,'approve');
  if(a==='published')return decide(d,isPublished(dec[d.id])?'unpublish':'published');
  if(a==='clear')return decide(d,'clear',{text:null,note:''});
  if(a==='edit'){close();panel('edit').classList.add('open');panel('edit').querySelector('textarea').focus();return}
  if(a==='hold'||a==='rewrite'){close();noteFor=a;const p=panel('note');p.classList.add('open');const t=p.querySelector('textarea');t.placeholder=a==='hold'?'HOLD 原因（可空）':'给重写的具体意见：哪里错、要怎么改';t.value=(dec[d.id]&&dec[d.id].note)||'';t.focus();return}
  if(a==='cancel'){close();if(dirty)render();return}
  if(a==='note-ok'){const note=panel('note').querySelector('textarea').value.trim();if(noteFor==='rewrite'&&!note){panel('note').querySelector('textarea').focus();return}return decide(d,noteFor,{note})}
  const t=panel('edit').querySelector('textarea').value.trim();
  const edited=t&&t!==d.text?t:null;
  if(a==='save-approve')return decide(d,'approve',{text:edited});
  const cur=dec[d.id]&&dec[d.id].action!=='clear'?dec[d.id].action:'';
  if(a==='save')return decide(d,cur||'edit',{text:edited});
  if(a==='revert')return decide(d,cur&&cur!=='edit'?cur:'clear',{text:null});
});
$('#exp').onclick=()=>{
  const day=$('#day').value,out={day,exported_at:new Date().toISOString(),decisions:dec};
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,2)],{type:'application/json'}));
  a.download=`fd_admin_decisions_${day}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);
};
for(const s of ['#fAcct','#fSt','#fLang','#fRun','#fDec','#fHard','#fWarn'])$(s).onchange=render;
$('#fQ').oninput=render;$('#day').onchange=()=>{follow=$('#day').value===latest();load()};
function upd(){$('#upd').textContent=D.updated?`数据更新于 北京时间 ${D.updated.slice(5,10)} ${D.updated.slice(11,16)}`:''}
$('#rf').onclick=async()=>{const b=$('#rf');b.disabled=true;b.textContent='刷新中…';await refreshData('no-store');await load();b.disabled=false;b.textContent='刷新'};
let tick=0;   // decisions every 60 s; the page data (new days / rebuilt drafts) every 5 min
setInterval(async()=>{if(document.hidden)return;if(++tick%5===0)await refreshData('no-cache');load()},60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load()});
upd();render();load();
</script></body></html>
'''


def root_vars():
    """The public dashboard's palette (light + dark :root blocks), so both pages share one taste-skill style."""
    m = re.search(r':root\{.*?\}\}', ops.PAGE, re.S)
    return m.group(0) if m else ''


def build(inbox=ops.INBOX, out=ops.OUT, n_days=3):
    accounts = [{k: a.get(k) for k in ('id', 'no', 'name', 'lang', 'beat', 'status')} for a in ops.load_accounts()]
    names = {a['id']: a['name'] for a in accounts}
    day_dirs = sorted(p for p in inbox.iterdir() if p.is_dir() and ops.DAY_RE.match(p.name))[-n_days:] \
        if inbox.is_dir() else []
    days, runs, local = {}, {}, {}
    for d in day_dirs:
        days[d.name] = load_day(d, names)
        runs[d.name] = load_runs(d.name, days[d.name])
        local[d.name] = local_decisions(d.name)
    updated = max((d['stored'] for v in days.values() for d in v if d['stored']), default='')
    data = json.dumps({'accounts': accounts, 'days': days, 'runs': runs, 'local': local, 'target': TARGET,
                       'updated': updated}, ensure_ascii=False, sort_keys=True)
    page = PAGE.replace('__ROOTVARS__', root_vars()).replace('__NAVCSS__', ops.NAV_CSS).replace('__SHARED__', ops.shared_js())
    page = page.replace('__NAV__', ops.nav_html('/admin')).replace('__DATA__', data.replace('</', '<\\/'))
    (out / 'admin').mkdir(parents=True, exist_ok=True)
    changed = copy_assets(out)
    if ops.write_if_changed(out / 'admin/index.html', page.encode('utf-8')):
        changed.append('admin/index.html')
    total = sum(len(v) for v in days.values())
    print(f'admin console: {len(days)} day(s), {total} draft(s) -> {out}/admin (changed: {", ".join(changed) or "none"})')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inbox', type=Path, default=ops.INBOX)
    ap.add_argument('--out', type=Path, default=ops.OUT)
    ap.add_argument('--days', type=int, default=3, help='newest N inbox days to include (default 3)')
    args = ap.parse_args()
    return build(args.inbox, args.out, args.days)


if __name__ == '__main__':
    sys.exit(main())
