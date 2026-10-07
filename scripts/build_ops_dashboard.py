#!/usr/bin/env python3
"""Operator copy-paste dashboard for the fd20 compose inbox (static HTML, no model calls, no publishing).

Reads every live/store/compose_inbox/<day>/*.json row plus live/fd20_accounts.json (names) and
assets/persona_avatars (avatars, embedded). Writes a self-contained index.html and one <day>.csv per day
(account, time, text) to --out. Every time shown (post times, updated stamp, today/tomorrow labels, CSV) is
China time (Asia/Shanghai, labelled 北京时间); the inbox stores London-time ISO stamps with offsets. Inbox days
(<day> dirs, CSV names, the date selector) are Beijing calendar dates since Oct 7 (earlier days were London dates
of a 05:13 London run, which is the same calendar date in Beijing). The post text is the draft body only: no source/attribution line, no notes.
Suggested post times are spread here (display only, the inbox and pipeline are untouched) over 08:00-22:59
北京时间 on the inbox day: each account's distinct slots keep their order, take one equal segment of the window
each and stay at least 30 minutes apart (drafts sharing one original slot - rewrites / alternatives - keep sharing it).
Review-console decisions (/admin, scripts/build_admin_console.py) are overlaid here: the newest days are pulled
from the console API into live/store/admin_decisions/<day>.json first (scripts/apply_admin_decisions.py; non-fatal,
FD_ADMIN_PULL=0 or --no-pull skips it), then approve -> ready with the edited text, hold / rewrite -> HOLD,
edit -> edited text. The admin console is rebuilt alongside (--no-admin skips it).
Idempotent: files are rewritten only when their content changes.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / 'live/store/compose_inbox'
ACCOUNTS = ROOT / 'live/fd20_accounts.json'
AVATARS = ROOT / 'assets/persona_avatars'
DECISIONS = ROOT / 'live/store/admin_decisions'
PULL_DAYS = 3
OUT = Path('/workspace/x/dashboard/ops')
BJT = ZoneInfo('Asia/Shanghai')
POST_START, POST_END, POST_GAP = (8, 0), (22, 59), timedelta(minutes=30)
DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
URL_RE = re.compile(r'https?://\S+')
# twitter-text v3 weighting: these code point ranges weigh 1, everything else (CJK, full-width punctuation, …, emoji)
# weighs 2; a URL weighs 23.
X_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))


def x_weight(text):
    """X weighted length (limit 280): twitter-text v3 ranges, URLs 23. Emoji count 2 per code point (X counts a
    ZWJ sequence once, so multi-part emoji read slightly high - the safe side)."""
    urls = URL_RE.findall(text)
    rest = URL_RE.sub('', text)
    return 23 * len(urls) + sum(1 if any(lo <= ord(c) <= hi for lo, hi in X_LIGHT) else 2 for c in rest)


def to_bjt(stamp):
    """ISO stamp with offset (London post time / UTC stored_at) -> China-time ISO string; '' when missing/bad."""
    try:
        return datetime.fromisoformat(stamp).astimezone(BJT).isoformat() if stamp else ''
    except (TypeError, ValueError):
        return ''


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
    if row.get('superseded'):
        return 'superseded'
    if row.get('held') or (row.get('arbitration') or {}).get('status') == 'HOLD':
        return 'HOLD'
    return row.get('draft_status') or row.get('status') or 'unknown'


def note_of(row):
    """Why a draft is not ready (audit reason / hold reason / hard QA codes); '' for ready drafts."""
    status = status_of(row)
    triage = row.get('triage') or {}
    if status == 'draft_ready':
        moved = triage.get('from') if triage.get('action') == 'reassign' else None
        return f"改派自 {moved.get('name') or moved.get('account_id')}" if moved else ''
    if triage.get('action') in ('hold', 'reassign'):   # Oct 7 relax re-triage outranks the older audit / holds
        return row.get('hold_reason') or triage.get('reason') or ''
    audit = row.get('audit') or {}
    if audit.get('verdict') in ('rewrite', 'drop'):
        return f"审稿{'重写' if audit['verdict'] == 'rewrite' else '弃用'}：{audit.get('reason') or ''}"
    if (row.get('arbitration') or {}).get('status') == 'HOLD':
        return '跨号仲裁暂缓：同一观点已给其他账号'
    hard = sorted({f.get('code') for f in row.get('findings') or [] if f.get('level') == 'hard'} - {None})
    return row.get('hold_reason') or ('硬性检查未过：' + ', '.join(hard) if hard else '')


def media_of(row):
    """post_mode / target and chart images set by live/draft_media.py (absent = plain original post, no image)."""
    mode = row.get('post_mode') or 'original'
    return {'mode': mode, 'target': row.get('quote_target_url') or row.get('reply_to_url') or '',
            'heat_led': bool(row.get('heat_led')),
            # 回看 (live/archive_lookback.py): label + the old post it looks back at
            'archive': row.get('post_kind') == 'archive_lookback',
            'archive_url': (row.get('archive') or {}).get('original_url') or '',
            'media': [{'path': m['path'], 'alt': m.get('alt') or '',
                       # ?v=<sha> so a chart refreshed in place (scripts/refresh_charts.py) is not served from cache
                       'src': m['path'] + (f"?v={m['sha256'][:12]}" if m.get('sha256') else ''),
                       'updated': chart_time(m),
                       'credit': ', '.join(s.get('name') or '' for s in m.get('data_sources') or [])}
                      for m in row.get('media') or [] if m.get('path')]}


def chart_time(m):
    """'HH:MM' Beijing time the chart image was last re-rendered with new data (refreshed_at, else fetched_at)."""
    stamp = m.get('refreshed_at') or next((s.get('fetched_at') for s in m.get('data_sources') or []
                                           if s.get('fetched_at')), '')
    return to_bjt(stamp)[11:16]


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
            'time': to_bjt(row.get('suggested_post_time_london')), 'stored': to_bjt(row.get('stored_at')),
            'status': status_of(row),
            'note': note_of(row), **media_of(row)})
    drafts.sort(key=lambda d: (d['time'], d['id']))
    return drafts


def load_decisions(day, store=None):
    try:
        return json.loads(((store or DECISIONS) / f'{day}.json').read_text()).get('decisions') or {}
    except (OSError, ValueError):
        return {}


def apply_decisions(drafts, decisions):
    """Overlay Fiona's /admin decisions: approve -> ready (+ edited text), hold / rewrite -> HOLD, edit -> text."""
    for d in drafts:
        x = decisions.get(d['id']) or {}
        act, text = x.get('action'), x.get('text')
        if act not in ('approve', 'hold', 'rewrite', 'edit'):
            continue
        if text and text.strip() != d['text']:
            d['text'] = text.strip()
            if d['parts']:
                d['parts'] = [p.strip() for p in re.split(r'\n\s*\n', d['text']) if p.strip()]
                d['parts_w'] = [x_weight(p) for p in d['parts']]
            d['chars'], d['xw'] = len(d['text']), x_weight(d['text'])
        if act == 'approve':
            d['status'], d['note'] = 'draft_ready', ''
        elif act in ('hold', 'rewrite'):
            label = 'HOLD' if act == 'hold' else '要求重写'
            d['status'], d['note'] = 'HOLD', f"Fiona {label}{'：' + x['note'] if x.get('note') else ''}"
    return drafts


def pull_decisions(days):
    """Fetch the newest days' decisions from the console API (apply_admin_decisions.py); never fatal."""
    import subprocess
    for day in days:
        try:
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/apply_admin_decisions.py'), '--day', day],
                               capture_output=True, text=True, timeout=90)
            print((r.stdout.strip().splitlines() or [f'decisions {day}: exit {r.returncode}'])[-1]
                  if r.returncode == 0 else f'decisions pull {day} failed (dashboard uses local copy): '
                  f'{(r.stderr.strip().splitlines() or ["?"])[-1]}')
        except (OSError, subprocess.SubprocessError) as exc:
            print(f'decisions pull {day} failed (dashboard uses local copy): {exc}')


def clamp_times(drafts, day):
    """Spread every account's suggested times over [08:00, 22:59] BJT on `day`, distinct slots >= 30 min apart.

    London habit times land in the Beijing night, so clamping them piled each account's last slots at 22:29/22:59.
    Instead an account's n distinct slots (in original order) get one equal segment of the window each; the spot
    inside the segment comes from the original time of day plus a stable per-account offset, so accounts differ."""
    base = datetime.fromisoformat(day).replace(tzinfo=BJT)
    lo, hi = (base.replace(hour=h, minute=m) for h, m in (POST_START, POST_END))
    span = (hi - lo).total_seconds() / 60
    by_acct = {}
    for d in drafts:
        if d['time']:
            by_acct.setdefault(d['account_id'], {}).setdefault(d['time'], []).append(d)
    for acct, slots in by_acct.items():
        orig = sorted(slots, key=datetime.fromisoformat)
        seg = span / len(orig)
        shift = int(hashlib.sha1(str(acct).encode()).hexdigest()[:8], 16) / 16 ** 8
        t = []
        for i, s in enumerate(orig):
            src = datetime.fromisoformat(s)
            frac = ((src.hour * 60 + src.minute) / 1440 + shift) % 1
            t.append(lo + timedelta(minutes=int(i * seg + frac * seg)))
        for i in range(1, len(t)):                 # forward: keep order, open the gaps
            t[i] = max(t[i], t[i - 1] + POST_GAP)
        t[-1] = min(t[-1], hi)
        for i in range(len(t) - 2, -1, -1):        # backward: pull late overflow earlier, gaps kept
            t[i] = min(t[i], t[i + 1] - POST_GAP)
        if t[0] < lo:                              # > 30 slots cannot fit; never happens at 2-5 per account
            raise ValueError(f'{len(t)} slots do not fit 08:00-22:59 at 30-minute spacing')
        for s, new in zip(orig, t):
            for d in slots[s]:
                d['time'] = new.isoformat()
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
    w.writerow(['account', 'time (北京时间)', 'text'])
    for d in drafts:
        if d['status'] == 'draft_ready' and d['text']:
            w.writerow([names.get(d['account_id'], d['account_id']), d['time'][:16].replace('T', ' '), d['text']])
    return ('﻿' + buf.getvalue()).encode('utf-8')


# Shared top nav of the public dashboard (/) and the review console (/admin); build_admin_console.py reuses it.
NAV_CSS = ('.topnav{display:inline-flex;gap:2px;background:var(--surface);border:1px solid var(--line);border-radius:10px;'
           'padding:3px;margin-bottom:20px}'
           '.topnav a{color:var(--mute);text-decoration:none;font-weight:600;font-size:13px;line-height:1.5;'
           'padding:5px 14px;border-radius:7px;transition:background .15s,color .15s}'
           '.topnav a:hover{color:var(--ink)}'
           '.topnav a[aria-current=page]{background:var(--accent-bg);color:var(--accent)}')
NAV_LINKS = (('/', '运营看板'), ('/admin', '审稿后台'))


def nav_html(current):
    links = ''.join(f'<a href="{href}"{" aria-current=page" if href == current else ""}>{label}</a>'
                    for href, label in NAV_LINKS)
    return f'<nav class="topnav" aria-label="页面">{links}</nav>'


PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>星轨 · FD 发帖看板</title>
<style>
:root{color-scheme:light dark;
 --bg:#f4f4f5;--surface:#fdfdfd;--sunk:#f8f8f9;--ink:#18181b;--ink2:#3f3f46;--mute:#6b6b75;--faint:#9a9aa3;--line:#e4e4e7;--line2:#ececef;
 --accent:#0f766e;--accent-bg:#e5f1ef;--warn:#8a5a00;--warnbg:#f7efdb;--hold:#9f2f2d;--holdbg:#fbeaea;--info:#3f4f6b;--infobg:#eceff5;
 --btn:#18181b;--btn-ink:#fafafa;
 --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
 --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
@media (prefers-color-scheme:dark){:root{
 --bg:#111113;--surface:#18181b;--sunk:#1d1d21;--ink:#ececee;--ink2:#c8c8ce;--mute:#9a9aa3;--faint:#71717a;--line:#2c2c31;--line2:#25252a;
 --accent:#5fb5aa;--accent-bg:#15302c;--warn:#e0b45c;--warnbg:#2c2414;--hold:#f0a09d;--holdbg:#341d1d;--info:#b7c2d8;--infobg:#20252f;
 --btn:#ececee;--btn-ink:#18181b}}
/* shape rule: containers 14px, posts 10px, controls 8px, status tags full pill */
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;font:15px/1.6 var(--sans);color:var(--ink);-webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:32px 24px 64px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:20px}
.logo{width:40px;height:40px;border-radius:10px;background:var(--btn);color:var(--btn-ink);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:600;flex:none}
.ttl{flex:1;min-width:220px}.ttl h1{margin:0;font-size:20px;font-weight:650;letter-spacing:-.01em;line-height:1.3}.ttl p{margin:2px 0 0;color:var(--mute);font-size:13px}
.stats{display:flex;gap:8px}
.stat{display:inline-flex;align-items:baseline;gap:8px;background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:5px 14px}
.stat small{font-size:12px;color:var(--mute)}.stat b{font:600 17px/1.2 var(--mono);font-variant-numeric:tabular-nums}
.stat.s-done b{color:var(--accent)}.stat.s-todo b{color:var(--warn)}
.bar{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;font-size:13px;color:var(--mute);padding:0 0 14px;margin:0 0 24px;border-bottom:1px solid var(--line)}
.bar select{font:inherit;color:var(--ink);padding:4px 10px;border:1px solid var(--line);border-radius:8px;background:var(--surface)}
.bar label{white-space:nowrap;cursor:pointer;display:inline-flex;align-items:center;gap:5px}.bar .sp{flex:1}
#flt{display:inline-flex;flex-wrap:wrap;gap:4px 14px;align-items:center}
input[type=checkbox]{accent-color:var(--accent)}
.bar a{color:var(--ink);text-decoration:none;font-weight:600;border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:4px 12px}
.bar a:hover{border-color:var(--faint)}
.acct{display:grid;grid-template-columns:196px minmax(0,1fr);gap:24px;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px}
.av{width:48px;height:48px;border-radius:50%;object-fit:cover;display:flex;align-items:center;justify-content:center;color:#fafafa;font-size:20px;font-weight:600;margin-bottom:12px}
.side h2{margin:0;font-size:16px;font-weight:620;line-height:1.35;letter-spacing:-.005em}
.side .pf{font-size:12.5px;color:var(--mute);margin-top:4px}.side .hd{font:12.5px/1.5 var(--mono);color:var(--ink2)}
.side .bt{font-size:12px;color:var(--faint);margin-top:6px;line-height:1.5}
.pill{display:inline-block;margin-top:14px;background:var(--sunk);border:1px solid var(--line);color:var(--ink2);font:600 12px/1.6 var(--mono);font-variant-numeric:tabular-nums;border-radius:999px;padding:1px 10px}
.more{display:block;margin-top:12px;background:none;border:0;padding:0;font:inherit;font-size:13px;color:var(--mute);font-weight:600;cursor:pointer;text-decoration:underline;text-underline-offset:3px;text-decoration-color:var(--line)}
.more:hover{color:var(--ink)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-content:start;min-width:0}
.grid .none{color:var(--faint);font-size:13px;padding:10px 0}
.post{background:var(--sunk);border:1px solid var(--line2);border-radius:10px;padding:16px;display:flex;flex-direction:column;min-width:0;transition:opacity .15s}
.post.posted{opacity:.5}.post.hide{display:none}.post.notready{background:transparent;border:1px dashed var(--line)}
.ph{display:flex;align-items:baseline;gap:8px;margin-bottom:10px}.ph small{font-size:12px;color:var(--mute)}
.ph .tm{color:var(--ink);font:600 15px/1.3 var(--mono);font-variant-numeric:tabular-nums}
.ph .st{margin-left:auto;font-size:11.5px;font-weight:600;border-radius:999px;padding:1px 9px;background:var(--warnbg);color:var(--warn);align-self:center;white-space:nowrap}
.ph .st.ok{background:var(--accent-bg);color:var(--accent)}.ph .st.hold{background:var(--holdbg);color:var(--hold)}
.txt{white-space:pre-wrap;word-break:break-word;font-size:15px;line-height:1.75;flex:1;color:var(--ink)}
.txt:lang(en){font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,"Helvetica Neue",Arial,sans-serif;line-height:1.65}
.note{font-size:12.5px;line-height:1.5;color:var(--warn);background:var(--warnbg);border-radius:8px;padding:6px 10px;margin-bottom:10px}
.note.mv{color:var(--info);background:var(--infobg);align-self:flex-start}
.part{border-top:1px dashed var(--line);padding-top:10px;margin-top:10px}.part:first-of-type{border-top:0;margin-top:0;padding-top:0}
.part .pr{display:flex;align-items:center;justify-content:space-between;font:12px var(--mono);color:var(--mute);margin-bottom:2px}
.cnt{font:11.5px/1.5 var(--mono);color:var(--faint);margin-top:8px;font-variant-numeric:tabular-nums}
.cp1{background:var(--surface);border:1px solid var(--line);border-radius:8px;font:inherit;font-family:var(--sans);font-size:12px;padding:1px 10px;cursor:pointer;color:var(--ink2)}
.cp1:hover{border-color:var(--faint)}.cp1.done{color:var(--accent);border-color:var(--accent)}
.foot{display:flex;align-items:center;justify-content:space-between;margin-top:14px;padding-top:12px;border-top:1px solid var(--line2);gap:10px}
.done-l{display:inline-flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--line);color:var(--ink2);font-weight:600;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px;user-select:none;transition:background .15s,color .15s,border-color .15s}
.done-l:has(input:checked){background:var(--accent-bg);color:var(--accent);border-color:transparent}
.done-l input{width:16px;height:16px;margin:0}
.cp{display:inline-flex;align-items:center;gap:6px;background:var(--btn);color:var(--btn-ink);border:1px solid var(--btn);border-radius:8px;padding:7px 14px;font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;white-space:nowrap;transition:background .15s,transform .1s}
.cp:hover{opacity:.88}.cp:active,.cp1:active,.done-l:active{transform:translateY(1px)}
.cp.done{background:var(--accent);border-color:var(--accent);color:#fafafa}.cp svg{width:15px;height:15px}
.post.notready .cp{background:var(--surface);color:var(--ink2);border-color:var(--line)}
.post.notready .foot .cnt{margin:0}
button:focus-visible,select:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.empty{text-align:center;color:var(--mute);padding:48px 16px}
.mode{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;font-size:12.5px}
.mode .tg{font-weight:600;border-radius:999px;padding:1px 9px;background:var(--infobg);color:var(--info)}
.mode .tg.ht{background:var(--warnbg);color:var(--warn)}
.mode a{color:var(--ink2);font-weight:600;text-decoration:underline;text-underline-offset:3px;text-decoration-color:var(--line)}
.img{margin:12px 0 0}.img img{display:block;width:100%;height:auto;border-radius:8px;border:1px solid var(--line2);background:#131722}
.img figcaption{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:6px;font-size:11.5px;color:var(--faint)}
.img .dl{color:var(--ink);text-decoration:none;font-weight:600;font-size:12.5px;border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:2px 10px;white-space:nowrap}
.img .dl:hover{border-color:var(--faint)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:820px){
 .wrap{padding:16px 12px 40px}.ttl h1{font-size:18px}
 .stats{width:100%}.stat{flex:1;justify-content:center;padding:5px 8px}
 .bar{gap:8px 14px}
 .acct{grid-template-columns:1fr;padding:14px;gap:14px}
 .side{border-bottom:1px solid var(--line2);padding:0 0 12px;display:grid;grid-template-columns:auto 1fr;column-gap:12px}
 .side .av{width:44px;height:44px;font-size:18px;margin:0;grid-row:span 4}
 .side .pill{margin-top:8px;justify-self:start;grid-column:2}.side .more{grid-column:2}
 .grid{grid-template-columns:1fr}
}
__NAVCSS__
</style></head><body><div class="wrap">
__NAV__
<header><div class="logo">星</div>
<div class="ttl"><h1>星轨 · FD 发帖看板</h1><p>复制正文，到 X 发布，再勾选已发 · <span id="upd"></span></p></div>
<div class="stats"><div class="stat"><small>可发</small><b id="nAll">0</b></div><div class="stat s-done"><small>已发</small><b id="nDone">0</b></div><div class="stat s-todo"><small>待发</small><b id="nTodo">0</b></div></div>
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
const ST_LABEL={draft_ready:'可发',HOLD:'HOLD（暂缓）',superseded:'已替换（审稿退回）',needs_review:'待复核',blocked:'失败',skipped:'跳过'};
const COLORS=['#5b6475','#7a6a58','#4f6f68','#5f6b85','#76705a','#7a5c66','#556b7d','#6b5f7a','#5d7462','#735d55'];
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LS='fdops:posted:';const isPosted=id=>localStorage.getItem(LS+id)==='1';
const shown=new Set(JSON.parse(localStorage.getItem('fdops:statuses')||'["draft_ready"]'));
const expanded=new Set();
const days=Object.keys(D.days).sort().reverse();
const daySel=$('#day');daySel.innerHTML=days.map(d=>`<option>${d}</option>`).join('');
const want=location.hash.slice(1);if(days.includes(want))daySel.value=want;
$('#hidePosted').checked=localStorage.getItem('fdops:hidePosted')==='1';
const COPY_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
const bjtDay=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
function when(t){
  if(!t)return '-';const day=t.slice(0,10),hm=t.slice(11,16);
  const today=bjtDay(new Date()),diff=Math.round((Date.parse(day)-Date.parse(today))/864e5);
  const lbl={'-2':'前天','-1':'昨天','0':'今天','1':'明天','2':'后天'}[diff]||day.slice(5);
  return `${lbl} ${hm}`;
}
function cnt(t,w,lang){const n=[...t].length;return `${n} ${lang==='en'?'字符':'字'} · X计 ${w}`}   // all accounts have X Premium: no 280 warning
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))>>>0;return COLORS[h%COLORS.length]}
function avatar(a){
  if(a.avatar)return `<img class="av" src="${a.avatar}" alt="">`;
  const ch=[...String(a.name||a.id).replace(/^[^\p{L}\p{N}]+/u,'')][0]||'?';
  return `<div class="av" style="background:${hue(a.id)}">${esc(ch.toUpperCase())}</div>`;
}
function card(d,hidden){
  const ready=d.status==='draft_ready',p=ready&&isPosted(d.id),hold=d.status==='HOLD'||d.status==='superseded',lg=d.lang==='en'?'en':'zh-CN';
  const st=p?'<span class="st ok">已发</span>':hold?`<span class="st hold">${d.status==='HOLD'?'HOLD':'已替换'}</span>`:d.status==='draft_ready'?'<span class="st">待发出</span>':`<span class="st">${esc(ST_LABEL[d.status]||d.status)}</span>`;
  let body;
  if(d.parts&&d.parts.length>1){
    body=d.parts.map((t,i)=>`<div class="part"><div class="pr"><span>${i+1}/${d.parts.length}</span><button class="cp1" data-t="${esc(t)}">复制</button></div><div class="txt" lang="${lg}">${esc(t)}</div><div class="cnt">${cnt(t,d.parts_w[i],d.lang)}</div></div>`).join('');
  }else body=`<div class="txt" lang="${lg}">${esc(d.text)}</div><div class="cnt">${cnt(d.text,d.xw,d.lang)}</div>`;
  const ML={quote:'引用',reply:'回复'};
  const mode=(ML[d.mode]||d.heat_led||d.archive)?`<div class="mode">${d.archive?'<span class="tg">回看</span>':''}${ML[d.mode]?`<span class="tg">${ML[d.mode]}</span>`:''}${d.heat_led?'<span class="tg ht">热度</span>':''}${ML[d.mode]&&d.target?`<a href="${esc(d.target)}" target="_blank" rel="noopener noreferrer">打开原帖</a>`:''}${d.archive&&d.archive_url?`<a href="${esc(d.archive_url)}" target="_blank" rel="noopener noreferrer">回看原帖</a>`:''}</div>`:'';
  const imgs=(d.media||[]).map(m=>`<figure class="img"><a href="${esc(m.src||m.path)}" target="_blank" rel="noopener"><img src="${esc(m.src||m.path)}" alt="${esc(m.alt)}" loading="lazy"></a><figcaption><span>${esc([m.credit?'数据：'+m.credit:'',m.updated?'图更新于 北京时间 '+m.updated:''].filter(Boolean).join(' · '))}</span><a class="dl" href="${esc(m.src||m.path)}" download="${esc(m.path.split('/').pop())}">下载图片</a></figcaption></figure>`).join('');
  body=mode+body+imgs;
  return `<div class="post${p?' posted':''}${ready?'':' notready'}${hidden?' hide':''}"><div class="ph"><small>建议发出（北京时间）</small><span class="tm">${when(d.time)}</span>${st}</div>${d.note?`<div class="note${d.note.startsWith('改派自')?' mv':''}">${esc(d.note)}</div>`:''}${body}
<div class="foot">${ready?`<label class="done-l"><input type="checkbox" data-p="${esc(d.id)}" ${p?'checked':''}> 已发</label>`:'<span class="cnt">不可发：先改稿或等重写</span>'}<button class="cp" data-t="${esc(d.text)}">${COPY_SVG}<span>${d.parts&&d.parts.length>1?'复制全部':'一键复制'}</span></button></div></div>`;
}
function render(){
  const day=daySel.value;
  if(!day){$('#main').innerHTML='<p class="empty">还没有任何稿件</p>';$('#csv').style.display='none';return}
  location.hash=day;const drafts=D.days[day]||[];
  $('#csv').href=day+'.csv';$('#csv').setAttribute('download','fd_'+day+'.csv');
  const sts=[...new Set(drafts.map(d=>d.status))].sort();
  $('#flt').innerHTML='状态 '+sts.map(s=>`<label><input type="checkbox" data-s="${esc(s)}" ${shown.has(s)?'checked':''}> ${esc(ST_LABEL[s]||s)} (${drafts.filter(d=>d.status===s).length})</label>`).join(' ');
  const hideP=$('#hidePosted').checked,hideE=$('#hideEmpty').checked;
  let all=0,done=0;const out=[];
  for(const a of D.accounts){
    const mine=drafts.filter(d=>d.account_id===a.id&&shown.has(d.status));
    const rd=drafts.filter(d=>d.account_id===a.id&&d.status==='draft_ready');   // counts: ready drafts only
    const nDone=rd.filter(d=>isPosted(d.id)).length;all+=rd.length;done+=nDone;
    const cards=mine.filter(d=>!(hideP&&isPosted(d.id)));
    if(!cards.length&&hideE)continue;
    const open=expanded.has(a.id),lim=2;
    const more=cards.length>lim?`<button class="more" data-x="${esc(a.id)}">${open?'收起':`展开全部 ${cards.length} 条`}</button>`:'';
    out.push(`<section class="acct"><div class="side">${avatar(a)}<h2>${esc(a.name)}</h2><div class="pf">X${a.lang?` · ${a.lang==='zh'?'中文':'English'}`:''}</div><div class="hd">${esc(a.handle?(a.handle.startsWith('@')?a.handle:'@'+a.handle):'@待填')}</div>${a.beat?`<div class="bt">${esc(a.beat)}</div>`:''}<span class="pill">待发 ${rd.length-nDone}/${rd.length}</span>${more}</div>
<div class="grid">${cards.length?cards.map((d,i)=>card(d,!open&&i>=lim)).join(''):'<div class="none">今日无可显示稿件</div>'}</div></section>`);
  }
  $('#main').innerHTML=out.join('')||(drafts.length?`<p class="empty">当前筛选下没有稿件（共 ${drafts.length} 篇，可在「状态」里勾选其他状态）</p>`:'<p class="empty">这一天没有稿件</p>');
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
$('#upd').textContent=D.updated?`数据更新于 北京时间 ${D.updated.slice(5,10)} ${D.updated.slice(11,16)}`:'';
daySel.onchange=render;render();
</script></body></html>
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inbox', type=Path, default=INBOX)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--no-pull', action='store_true', help='do not pull /admin decisions from the API first')
    ap.add_argument('--no-admin', action='store_true', help='do not rebuild the /admin review console')
    args = ap.parse_args()
    day_names = sorted(p.name for p in args.inbox.iterdir() if p.is_dir() and DAY_RE.match(p.name)) \
        if args.inbox.is_dir() else []
    if not args.no_pull and os.environ.get('FD_ADMIN_PULL', '1') != '0':
        pull_decisions(day_names[-PULL_DAYS:])
    accounts = load_accounts()
    names = {a['id']: a['name'] for a in accounts}
    days = {}
    if args.inbox.is_dir():
        for d in sorted(p for p in args.inbox.iterdir() if p.is_dir() and DAY_RE.match(p.name)):
            days[d.name] = clamp_times(apply_decisions(load_day(d), load_decisions(d.name)), d.name)
    known = {a['id'] for a in accounts}
    for drafts in days.values():   # inbox accounts missing from fd20_accounts.json still get a section
        for d in drafts:
            if d['account_id'] not in known:
                known.add(d['account_id'])
                accounts.append({'id': d['account_id'], 'no': '', 'name': d['name'] or d['account_id'],
                                 'lang': d['lang'], 'beat': '', 'handle': '', 'avatar': ''})
    args.out.mkdir(parents=True, exist_ok=True)
    # last-updated = newest inbox write (deterministic, so an unchanged inbox leaves index.html untouched)
    updated = max((d['stored'] for v in days.values() for d in v if d['stored']), default='')
    data = json.dumps({'accounts': accounts, 'days': days, 'updated': updated}, ensure_ascii=False, sort_keys=True)
    page = PAGE.replace('__NAVCSS__', NAV_CSS).replace('__NAV__', nav_html('/'))
    page = page.replace('__DATA__', data.replace('</', '<\\/'))
    changed = [p.name for p, b in [(args.out / 'index.html', page.encode('utf-8'))] +
               [(args.out / f'{day}.csv', day_csv(dr, names)) for day, dr in days.items()]
               if write_if_changed(p, b)]
    total = sum(len(v) for v in days.values())
    print(f'ops dashboard: {len(days)} day(s), {total} draft(s) -> {args.out} (changed: {", ".join(changed) or "none"})')
    if not args.no_admin:
        import build_admin_console
        build_admin_console.build(args.inbox, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
