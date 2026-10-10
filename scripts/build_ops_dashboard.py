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
edit -> edited text. The page also overlays the live decisions itself (GET /api/decisions on load, every 60 s, on
「刷新」), so /admin changes show without a rebuild; 「已发」 is the shared published flag (POST published / unpublish /
clear), not localStorage. It opens on the newest day with drafts and re-reads its own data block every 5 min / on 刷新.
The admin console is rebuilt alongside (--no-admin skips it).
Look (Oct 8, Fiona's Lovable design): one bordered table, account column + 帖子 1 / 帖子 2 columns (stacked on
narrow screens), post text clamped to 3 lines with 展开正文, image attachments as thumbnail rows; inline CSS / SVG only.
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
from datetime import datetime, timedelta, timezone
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
# Oct 9: a draft is never slotted before it exists. From this inbox day on, every slot is >= its draft's stored_at +
# POST_LEAD (5-minute grid), so a late run (10-09: the 23:13 London cron died with the box, compose re-run at 14:45
# Beijing) spreads over what is left of 08:00-22:59 instead of showing times that have already passed. Earlier days
# keep the plain full-window spread so published history does not move. FD_POST_NOT_BEFORE=0 turns it off.
POST_LEAD, POST_NOT_BEFORE_FROM = timedelta(minutes=30), '2026-10-09'
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
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from live import fd_accounts   # Oct 8: main + spares (FD_ACCOUNTS_EXTRA) + new (FD_ACCOUNTS_NEW)
    accounts = fd_accounts.rows(ACCOUNTS) if ACCOUNTS.exists() else []
    out = []
    for a in accounts:
        found = sorted(AVATARS.glob(f"*_{a['id']}.png")) if AVATARS.is_dir() else []
        out.append({'id': a['id'], 'no': a.get('no'), 'name': a.get('name') or a['id'], 'lang': a.get('lang'),
                    'beat': a.get('beat'), 'handle': a.get('handle') or '', 'status': a.get('status') or 'main',
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
    eng = row.get('engagement') if isinstance(row.get('engagement'), dict) else {}
    engaged = mode in ('quote', 'reply') and eng.get('mode') == mode
    target = row.get('quote_target_url') or row.get('reply_to_url') or (eng.get('url') if engaged else '') or ''
    return {'mode': mode, 'target': target,
            # Oct 9 (Fiona): ops must post a real quote / reply - CSV column + a banner on the card
            'action': action_of(mode, target),
            # live/engagement.py (FD_ENGAGE): the target's numbers at selection; its slot is pinned in clamp_times
            'engage_meta': engage_meta(eng) if engaged else '', 'pinned': engaged,
            # Oct 10: the target's reply / quote window closes here (published_at + 6h / 12h / 18h extended)
            'engage_close': engage_close(row, eng, mode) if engaged else '',
            # Oct 9 night: the target post's opening words + author, so ops can check the reply / quote fits it
            'target_text': target_text(row) if engaged else '',
            'target_author': (eng.get('author') or '') if engaged else '',
            'heat_led': bool(row.get('heat_led')),
            'lead': lead_score(row),
            # FD_HOTSPOT (live/hotspot.py): 「热点」 tag + the 母题 title
            'hotspot': (row.get('hotspot') or {}).get('title') or '',
            'hotspot_meta': (f"{(row.get('hotspot') or {}).get('publisher_count')} 家来源 · "
                             f"{(row.get('hotspot') or {}).get('account_source_count')} 个号的源里有"
                             if row.get('hotspot') else ''),
            # 回看 (live/archive_lookback.py): label + the old post it looks back at
            'archive': row.get('post_kind') == 'archive_lookback',
            'archive_url': (row.get('archive') or {}).get('original_url') or '',
            'archive_variant': (row.get('archive') or {}).get('variant') or 'then_vs_now',   # evergreen = 常青
            'media': [{'path': m['path'], 'alt': m.get('alt') or '',
                       # ?v=<sha> so a chart refreshed in place (scripts/refresh_charts.py) is not served from cache
                       'src': m['path'] + (f"?v={m['sha256'][:12]}" if m.get('sha256') else ''),
                       'updated': chart_time(m),
                       'credit': ', '.join(s.get('name') or '' for s in m.get('data_sources') or [])}
                      for m in row.get('media') or [] if m.get('path')]}


def target_text(row, limit=140):
    """The engagement target's opening words (the stored X source title; at most `limit` chars)."""
    src = row.get('source') if isinstance(row.get('source'), dict) else {}
    t = ' '.join(str(src.get('title') or '').split())
    return t if len(t) <= limit else t[:limit - 1] + '…'


ENGAGE_MARGIN = timedelta(minutes=int(os.environ.get('FD_ENGAGE_SLOT_MARGIN_MIN', '20')))   # time for ops to post


def engage_close(row, eng, mode):
    """ISO time the target's engagement window closes ('' when unknown): live/engagement.window_close."""
    from live import engagement
    t = engagement.window_close(row)
    return t.isoformat() if t else ''


def expire_engagement(d, slot):
    """Mark an unposted engagement draft whose target window closes before `slot` + ENGAGE_MARGIN as expired
    (out of the CSV / ready counts, back to the pool); True when expired."""
    if not d.get('engage_close') or d.get('decision') == 'published' or d.get('status') != 'draft_ready':
        return False
    if slot + ENGAGE_MARGIN <= datetime.fromisoformat(d['engage_close']):
        return False
    d['status'], d['expired'] = 'expired', True
    tag = f"已过期：目标帖的{'回复' if d.get('mode') == 'reply' else '引用'}窗口在北京时间 " \
          f"{datetime.fromisoformat(d['engage_close']).astimezone(BJT):%H:%M} 关闭，排不进去，不要再发"
    d['note'] = f"{tag} · {d['note']}" if d.get('note') else tag
    return True


def action_of(mode, target):
    """'回复 <url>' / '引用 <url>' for an engagement draft with a target post, else ''."""
    if mode in ('reply', 'quote') and target:
        return f"{'回复' if mode == 'reply' else '引用'} {target}"
    return ''


def lead_score(row):
    """Oct 9 perf review (/workspace/x/cc_jobs/perf_1008_REPORT.md): an account's first post of the day got ~10x the
    views of its second (10-08: median 127 vs 5), and zh posts on hot 母题 (heat >= 2.5) beat cold ones. clamp_times
    gives the account's first free slot to its strongest draft: hotspot 母题 (2 + heat) > heat-led > fresh standalone
    (0) > 回看 / 常青 (-1)."""
    hot = row.get('hotspot') or {}
    heat = hot.get('heat') if hot.get('heat') is not None else row.get('motif_heat')   # motif_heat: any 母题 pick
    if heat is not None:
        try:
            return 2.0 + float(heat)
        except (TypeError, ValueError):
            return 2.0
    if row.get('heat_led'):
        return 2.0
    if row.get('post_kind') == 'archive_lookback':
        return -1.0
    return 0.0


def lead_first(orig, nb, t, lead):
    """Reassign the spread times `t` (ascending) to the slots `orig` (with not-before `nb`, same order): each time
    goes to the highest-`lead` slot whose not-before allows it (ties keep the original order). Feasible whenever the
    original order is (slots sorted by not-before), so it never strands a slot. FD_LEAD_SLOT=0 keeps the old order."""
    if os.environ.get('FD_LEAD_SLOT', '1') == '0' or len(orig) < 2:
        return orig, nb
    left = list(range(len(orig)))
    order = []
    for ti in t:
        ok = [i for i in left if nb[i] <= ti] or left[:1]
        best = max(ok, key=lambda i: (lead.get(orig[i], 0.0), -i))
        order.append(best)
        left.remove(best)
    return [orig[i] for i in order], [nb[i] for i in order]


def _wan(n):
    return '' if n is None else f'{n / 10000:.1f}万' if n >= 10000 else str(n)


def engage_meta(e):
    """'@PhyrexNi · 40.8万粉 · 选中时 43赞 · 1.1万阅 · 发帖后 2.2h 发出' (live/engagement.py pick_record)."""
    bits = [f"@{e['author']}" if e.get('author') else '',
            f"{_wan(e.get('followers'))}粉" if e.get('followers') is not None else '',
            f"选中时 {e.get('likes')}赞" if e.get('likes') is not None else '',
            f"{_wan(e.get('views'))}阅" if e.get('views') is not None else '',
            f"发帖后 {e.get('age_h')}h 发出" if e.get('age_h') is not None else '']
    return ' · '.join(b for b in bits if b)


def load_targets(day, base=None):
    """The day's engagement targets log (live/engagement.py write_log; live/store is not in git)."""
    d = Path(base or os.environ.get('FD_ENGAGE_LOG') or ROOT / 'live' / 'store' / 'engagement')
    try:
        rows = json.loads((d / f'{day}.json').read_text()).get('targets') or []
    except (OSError, ValueError):
        return []
    keep = ('account', 'mode', 'target_url', 'author', 'author_followers', 'likes_at_selection', 'views_at_selection',
            'age_h_at_post', 'slot_bjt', 'why', 'passed_over')
    return [{k: r.get(k) for k in keep} for r in rows]


def chart_time(m):
    """'HH:MM' Beijing time the chart image was last re-rendered with new data (refreshed_at, else fetched_at)."""
    stamp = m.get('refreshed_at') or next((s.get('fetched_at') for s in m.get('data_sources') or []
                                           if s.get('fetched_at')), '')
    return to_bjt(stamp)[11:16]


def load_auto_published(day):
    """posted_at times (北京时间 HH:MM) keyed by draft id from auto_published/<day>.json."""
    p = ROOT / 'live/store/auto_published' / f'{day}.json'
    try:
        entries = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for e in (entries if isinstance(entries, list) else []):
        did = e.get('draft_id')
        if did and e.get('posted_at') and not e.get('dry_run'):
            try:
                out[did] = datetime.fromisoformat(e['posted_at']).astimezone(BJT).strftime('%H:%M')
            except (ValueError, TypeError):
                pass
    return out


def load_day(day_dir):
    auto = load_auto_published(day_dir.name)
    drafts = []
    for f in sorted(day_dir.glob('*.json')):
        try:
            row = json.loads(f.read_text())
        except (OSError, ValueError) as exc:
            print(f'skip {f}: {exc}', file=sys.stderr)
            continue
        body = (row.get('body') or '').strip()
        parts = parts_of(row, body)
        did = row.get('id') or f.stem
        drafts.append({
            'id': did, 'account_id': row.get('account_id'), 'name': row.get('name'),
            'lang': row.get('lang'), 'text': body, 'parts': parts,
            'parts_w': [x_weight(p) for p in parts] if parts else None,
            'chars': len(body), 'xw': x_weight(body),
            'time': to_bjt(row.get('suggested_post_time_london')), 'stored': to_bjt(row.get('stored_at')),
            'status': status_of(row),
            'note': note_of(row), 'auto_posted_at': auto.get(did) or '', **media_of(row)})
    drafts.sort(key=lambda d: (d['time'], d['id']))
    return drafts


def load_decisions(day, store=None):
    try:
        return json.loads(((store or DECISIONS) / f'{day}.json').read_text()).get('decisions') or {}
    except (OSError, ValueError):
        return {}


BASE_KEYS = ('text', 'parts', 'parts_w', 'chars', 'xw', 'status', 'note')


def is_published(x):
    """The 已发 flag of a decision (scripts/ops_admin/api/decisions.js isPublished): `published` (bool) on newer blobs,
    action 'published' on blobs written before the flag existed."""
    return bool(x) and (x.get('published') is True or (x.get('published') is not False and x.get('action') == 'published'))


def apply_decisions(drafts, decisions):
    """Overlay Fiona's /admin decisions: approve -> ready (+ edited text), hold / rewrite -> HOLD, edit -> text.

    A draft with a decision keeps its pre-decision fields in d['base'] so the page can re-apply live decisions
    from /api/decisions (a later 撤销 must restore the original text); d['published'] is the shared 已发 flag."""
    for d in drafts:
        x = decisions.get(d['id']) or {}
        act, text = x.get('action'), x.get('text')
        d['published'] = is_published(x)
        if act not in ('approve', 'published', 'hold', 'rewrite', 'edit'):
            continue
        d['base'] = {k: d.get(k) for k in BASE_KEYS}
        d['decision'] = act
        if text and text.strip() != d['text']:
            d['text'] = text.strip()
            if d['parts']:
                d['parts'] = [p.strip() for p in re.split(r'\n\s*\n', d['text']) if p.strip()]
                d['parts_w'] = [x_weight(p) for p in d['parts']]
            d['chars'], d['xw'] = len(d['text']), x_weight(d['text'])
            d['edited'] = True
        if act in ('approve', 'published'):   # published: marked after a human posted it (no auto-publishing)
            d['status'], d['note'] = 'draft_ready', ''
        elif act in ('hold', 'rewrite'):
            label = 'HOLD' if act == 'hold' else '要求重写'
            d['status'], d['note'] = 'HOLD', f"Fiona {label}{'：' + x['note'] if x.get('note') else ''}"
    return drafts


SHARED_JS = Path(__file__).resolve().parent / 'ops_admin/api/decisions.js'


def shared_js():
    """The <shared> block of api/decisions.js (decision rule: isPublished / nextDecision), inlined into both pages so
    the optimistic local update is the server's own rule."""
    src = SHARED_JS.read_text()
    return src[src.index('// <shared>'):src.index('// </shared>')].replace('</', '<\\/')


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


def clamp_times(drafts, day, now=None):
    """Spread every account's suggested times over [08:00, 22:59] BJT on `day`, distinct slots >= 30 min apart.

    London habit times land in the Beijing night, so clamping them piled each account's last slots at 22:29/22:59.
    Instead an account's n distinct slots (in original order) get one equal segment of the window each; the spot
    inside the segment comes from the original time of day plus a stable per-account offset, so accounts differ."""
    base = datetime.fromisoformat(day).replace(tzinfo=BJT)
    lo, hi = (base.replace(hour=h, minute=m) for h, m in (POST_START, POST_END))
    late = day >= POST_NOT_BEFORE_FROM and os.environ.get('FD_POST_NOT_BEFORE', '1') != '0'
    today_build = now is not None and now.astimezone(BJT).date() <= base.date()   # past days are history
    if late and now is not None:   # build time (main): nothing unposted is slotted before now + POST_LEAD
        today = now.astimezone(BJT).date() == base.date()   # past days' files keep their times
        now = now.astimezone(BJT) + POST_LEAD
        now = now.replace(second=0, microsecond=0) + timedelta(minutes=(-now.minute) % 5)
        if lo < now and (now <= hi or today):
            lo = now   # Oct 9: past 22:59 too (lo > hi): every unposted slot then moves to 明天
    v2 = slot_v2_on(day)
    reqs, pin_list, fixed = [], [], []   # FD_SLOT_V2: per-account requests placed globally after the loop
    by_acct = {}
    for d in drafts:
        if d['time'] and late and d.get('decision') == 'published':
            if v2:
                fixed.append((datetime.fromisoformat(d['time']).astimezone(BJT), d['account_id']))
            continue   # already posted: its time stays as recorded
        if d['time']:
            by_acct.setdefault(d['account_id'], {}).setdefault(d['time'], []).append(d)
    for acct, slots in by_acct.items():
        # engagement replies / quotes (live/engagement.py) keep their slot: it was timed to the target's hot window
        def pin_at(s, ds):
            return max(not_before(ds, lo, hi) if late else lo, min(hi, datetime.fromisoformat(s).astimezone(BJT)))
        # Oct 10: an engagement draft is only worth posting inside its target's window - at the slot it gets (the
        # earliest one, lo, when its window closes before the planned slot) it must still be open, else it expires
        def pin_eng(s, ds):
            at = pin_at(s, ds)
            closes = [datetime.fromisoformat(d['engage_close']) for d in ds if d.get('engage_close')]
            if closes and at + ENGAGE_MARGIN > min(closes):
                at = max(not_before(ds, lo, hi) if late else lo, lo)
            return at
        pins = []
        for s, ds in list(slots.items()):
            if any(d.get('pinned') for d in ds):
                new = pin_eng(s, ds)
                expired = [expire_engagement(d, new) for d in ds] if (late and today_build) else [False]
                for d in ds:
                    d['time'] = new.isoformat()
                if not all(expired):
                    pins.append(new)
                    if v2:
                        closes = [datetime.fromisoformat(d['engage_close']) for d in ds if d.get('engage_close')]
                        pin_list.append({'acct': acct, 'drafts': ds, 'at': new,
                                         'lo': max(not_before(ds, lo, hi) if late else lo, lo),
                                         'close': min(closes) - ENGAGE_MARGIN if closes else hi})
                del slots[s]
        pins = sorted(set(pins))
        if not slots:
            continue
        orig = sorted(slots, key=datetime.fromisoformat)
        nb = [not_before(slots[s], lo, hi) for s in orig] if late else [lo] * len(orig)
        if late:                                   # later-stored drafts take the later slots
            order = sorted(range(len(orig)), key=lambda i: (nb[i], datetime.fromisoformat(orig[i])))
            orig, nb = [orig[i] for i in order], [nb[i] for i in order]
        if v2:
            lang = next((d.get('lang') for ds in slots.values() for d in ds if d.get('lang')), '') or ''
            reqs.append({'acct': acct, 'lang': lang, 'orig': orig, 'nb': nb, 'slots': slots,
                         'lead': {s: max(float(d.get('lead') or 0) for d in slots[s]) for s in orig}})
            continue
        a_lo = min(nb[0], hi - POST_GAP * (len(orig) - 1)) if late else lo
        seg = (hi - a_lo).total_seconds() / 60 / len(orig)
        shift = int(hashlib.sha1(str(acct).encode()).hexdigest()[:8], 16) / 16 ** 8
        t = []
        for i, s in enumerate(orig):
            src = datetime.fromisoformat(s)
            frac = ((src.hour * 60 + src.minute) / 1440 + shift) % 1
            t.append(max(nb[i], a_lo + timedelta(minutes=int(i * seg + frac * seg))))
        for i in range(1, len(t)):                 # forward: keep order, open the gaps
            t[i] = max(t[i], t[i - 1] + POST_GAP)
        t[-1] = min(t[-1], hi)
        for i in range(len(t) - 2, -1, -1):        # backward: pull late overflow earlier, gaps kept
            t[i] = min(t[i], t[i + 1] - POST_GAP)
        lead = {s: max(float(d.get('lead') or 0) for d in slots[s]) for s in orig}
        over = []
        if t[0] < lo or lo > hi:
            # Oct 9: late in the Beijing day (lo = now + lead) an account's unposted drafts may not fit before 22:59 at
            # 30-minute spacing. Never fail the build: the best-lead drafts take the last valid slots, the rest move
            # to 明天 (next day from 08:00, flagged `overflow`, a note on the card) with a warning on stderr.
            fit = max(0, int((hi - lo) / POST_GAP) + 1) if lo <= hi else 0
            t = [hi - POST_GAP * (fit - 1 - i) for i in range(fit)]
            ext = t + [hi + POST_GAP * (j + 1) for j in range(len(orig) - fit)]
            orig, nb = lead_first(orig, nb, ext, lead)
            orig, over = orig[:fit], orig[fit:]
            a_lo = lo
            print(f'warning: {acct} on {day}: {len(orig) + len(over)} unposted slots do not fit '
                  f'{lo:%H:%M}-{hi:%H:%M} at 30-minute spacing; {len(over)} moved to 明天', file=sys.stderr)
        else:
            orig, nb = lead_first(orig, nb, t, lead)
        if pins:
            t = avoid_pins(t, pins, a_lo, hi)
        for s, new in zip(orig, t):
            for d in slots[s]:
                d['time'] = new.isoformat()
        nxt = base + timedelta(days=1)
        nxt = nxt.replace(hour=POST_START[0], minute=POST_START[1])
        for j, s in enumerate(over):
            for d in slots[s]:
                d['time'] = (nxt + POST_GAP * j).isoformat()
                d['overflow'] = True
                tag = '明天：今天剩余时段放不下（同账号需间隔 30 分钟），顺延到明天这个时间'
                d['note'] = f"{tag} · {d['note']}" if d.get('note') else tag
    if v2:
        place_v2(base, lo, hi, reqs, pin_list, fixed, day)
    drafts.sort(key=lambda d: (d['time'], d['id']))
    return drafts


# Oct 10 (Fiona item 4, FD_SLOT_V2, from inbox day SLOT_V2_FROM so published history keeps its times): EN accounts post
# in the US morning (20:00-22:59 Beijing) when they fit, ZH accounts spread over the whole 08:00-22:59 day, and across
# the matrix no more than BURST_MAX of our accounts fall inside any BURST_WIN window; minutes carry a stable per-draft
# jitter, never :00 / :30. Hard rules kept: 08:00-22:59, >= 30 min per account, never before stored_at + POST_LEAD,
# engagement slots inside their target window (expiry unchanged), overflow to 明天 only when the day cannot hold them.
SLOT_V2_FROM = os.environ.get('FD_SLOT_V2_FROM', '2026-10-11')
EN_START = (20, 0)
BURST_MAX, BURST_WIN = 3, timedelta(minutes=10)
BAD_MINUTES = (0, 30)


def slot_v2_on(day):
    return os.environ.get('FD_SLOT_V2', '1') != '0' and day >= SLOT_V2_FROM


def _h01(*parts):
    return int(hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:8], 16) / 16 ** 8


def burst_ok(c, acct, placed):
    """True when slot c for `acct` keeps every BURST_WIN window at <= BURST_MAX distinct accounts."""
    near = {(t, a) for t, a in placed if abs(t - c) < BURST_WIN and a != acct}
    if len({a for _, a in near}) < BURST_MAX:
        return True
    for k in range(int(BURST_WIN.total_seconds() // 60)):
        w0 = c - timedelta(minutes=k)
        if len({a for t, a in near if w0 <= t < w0 + BURST_WIN}) + 1 > BURST_MAX:
            return False
    return True


def _fits(c, acct, placed, mine, lo, hi):
    return (lo <= c <= hi and c.minute not in BAD_MINUTES and all(abs(c - m) >= POST_GAP for m in mine)
            and burst_ok(c, acct, placed))


def _search(target, acct, placed, mine, lo, hi, prefer_late=False):
    """Nearest feasible minute to `target` inside [lo, hi] (prefer_late: scan downward from hi first)."""
    if lo > hi:
        return None
    if prefer_late:
        c = hi
        while c >= lo:
            if _fits(c, acct, placed, mine, lo, hi):
                return c
            c -= timedelta(minutes=1)
        return None
    target = min(max(target, lo), hi)
    span = int((hi - lo).total_seconds() // 60) + 1
    for k in range(span + 1):
        for c in (target + timedelta(minutes=k), target - timedelta(minutes=k)) if k else (target,):
            if _fits(c, acct, placed, mine, lo, hi):
                return c
    return None


def place_v2(base, lo, hi, reqs, pin_list, fixed, day):
    placed = list(fixed)
    mine = {}
    for t, a in fixed:
        mine.setdefault(a, []).append(t)
    # 1. engagement pins: jitter, then the nearest feasible minute inside their own window (else keep the jittered time)
    for p in sorted(pin_list, key=lambda p: (p['at'], p['acct'])):
        acct, ds = p['acct'], p['drafts']
        j = int(_h01('pin', ds[0]['id']) * 9) - 4
        plo, phi = p['lo'], min(hi, p['close'])
        want = p['at'] + timedelta(minutes=j)
        c = _search(want, acct, placed, mine.get(acct, []), plo, phi) if plo <= phi else None
        c = c or min(max(want, plo), max(plo, phi))
        if c.minute in BAD_MINUTES and c + timedelta(minutes=1) <= max(plo, phi):
            c += timedelta(minutes=1)
        for d in ds:
            d['time'] = c.isoformat()
        placed.append((c, acct))
        mine.setdefault(acct, []).append(c)
    # 2. standalone slots: EN first (narrow evening window), then accounts with more slots, stable order by hash
    en_lo = base.replace(hour=EN_START[0], minute=EN_START[1])
    order = sorted(reqs, key=lambda r: (r['lang'] != 'en', -len(r['orig']), _h01('acct', r['acct'])))
    spilled = 0
    for r in order:
        acct, orig, nb, n = r['acct'], r['orig'], r['nb'], len(r['orig'])
        en = r['lang'] == 'en'
        wlo = max(lo, en_lo) if en else lo
        shift = _h01('shift', acct)
        times, over = [], []
        start = max(lo, nb[0]) if nb else lo
        fit = max(0, int((hi - start) / POST_GAP) + 1) if start <= hi else 0
        if fit < n:   # late build: the best-lead slots stay today (in not-before order), the rest go to 明天
            best = sorted(range(n), key=lambda i: (-r['lead'].get(orig[i], 0.0), i))[:fit]
            over = [orig[i] for i in range(n) if i not in best]
            orig, nb = [orig[i] for i in sorted(best)], [nb[i] for i in sorted(best)]
            n = len(orig)
        for i, s in enumerate(orig):
            cap = hi - POST_GAP * (n - 1 - i)   # leave room for this account's later slots
            jit = _h01('jit', r['slots'][s][0]['id'])
            seg = max(0.0, (hi - wlo).total_seconds() / 60 / n)
            target = wlo + timedelta(minutes=int(i * seg + ((shift + 0.3 * jit) % 1) * seg))
            floor_i = max(nb[i], times[-1] + POST_GAP) if times else nb[i]
            c = _search(target, acct, placed, mine.get(acct, []), max(floor_i, wlo), cap)
            if c is None and en:   # EN spill: the latest feasible minute before the evening window
                c = _search(en_lo, acct, placed, mine.get(acct, []), max(floor_i, lo), min(cap, en_lo - timedelta(minutes=1)),
                            prefer_late=True)
                spilled += c is not None
            if c is None:
                c = _search(target, acct, placed, mine.get(acct, []), max(floor_i, lo), cap)
            if c is None:   # the burst rule cannot be met: keep the hard rules, allow a 4th account in the window
                c = next((x for x in (max(floor_i, lo) + timedelta(minutes=k) for k in range(int((cap - max(floor_i, lo)).total_seconds() // 60) + 1))
                          if x.minute not in BAD_MINUTES and all(abs(x - m) >= POST_GAP for m in mine.get(acct, []))), None)
                if c is not None:
                    print(f'warning: slot v2 {day}: {acct} {c:%H:%M} breaks the {BURST_MAX}-per-10-min rule (no room)',
                          file=sys.stderr)
            if c is None:
                over.append(s)
                continue
            times.append(c)
            placed.append((c, acct))
            mine.setdefault(acct, []).append(c)
        keep = [s for s in orig if s not in over]
        knb = [nb[orig.index(s)] for s in keep]
        over = [s for s in r['orig'] if s in over]
        keep, _ = lead_first(keep, knb, times, r['lead'])
        for s, t in zip(keep, times):
            for d in r['slots'][s]:
                d['time'] = t.isoformat()
        if over:
            print(f'warning: {acct} on {day}: {len(over)} unposted slot(s) do not fit {lo:%H:%M}-{hi:%H:%M}; moved to 明天',
                  file=sys.stderr)
        nxt = (base + timedelta(days=1)).replace(hour=POST_START[0], minute=POST_START[1])
        for j, s in enumerate(over):
            t = nxt + POST_GAP * j + timedelta(minutes=1 + int(_h01('over', acct, j) * 20))
            for d in r['slots'][s]:
                d['time'] = t.isoformat()
                d['overflow'] = True
                tag = '明天：今天剩余时段放不下（同账号需间隔 30 分钟），顺延到明天这个时间'
                d['note'] = f"{tag} · {d['note']}" if d.get('note') else tag
    if spilled:
        print(f'slot v2 {day}: {spilled} EN slot(s) placed before {EN_START[0]:02d}:{EN_START[1]:02d} (evening window full)',
              file=sys.stderr)


def not_before(drafts, lo, hi):
    """Earliest slot for drafts sharing one original slot: newest stored_at + POST_LEAD, up to the next 5 minutes,
    inside [lo, hi]; no stored_at -> lo."""
    st = [datetime.fromisoformat(d['stored']).astimezone(BJT) for d in drafts if d.get('stored')]
    if not st:
        return lo
    t = max(st) + POST_LEAD
    t = t.replace(second=0, microsecond=0) + timedelta(minutes=1 if t.second or t.microsecond else 0)
    t += timedelta(minutes=(-t.minute) % 5)
    return max(lo, min(hi, t))


def avoid_pins(t, pins, lo, hi):
    """Move each spread slot to the nearest 5-minute spot in [lo, hi] that is >= POST_GAP from the pinned engagement
    slots and from the slots already placed (order kept where possible)."""
    placed, out = list(pins), []
    for x in t:
        best = None
        for k in range(0, int((hi - lo).total_seconds() // 300) + 1):
            for c in ((x + timedelta(minutes=5 * k)), (x - timedelta(minutes=5 * k))):
                if lo <= c <= hi and all(abs(c - p) >= POST_GAP for p in placed):
                    best = c
                    break
            if best:
                break
        best = best or x
        placed.append(best)
        out.append(best)
    return out


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
    w.writerow(['account', 'time (北京时间)', 'text', '引用/回复'])
    for d in drafts:
        if d['status'] == 'draft_ready' and d['text']:
            w.writerow([names.get(d['account_id'], d['account_id']), d['time'][:16].replace('T', ' '), d['text'],
                        d.get('action') or ''])
    return ('﻿' + buf.getvalue()).encode('utf-8')


# Shared look of the public dashboard (/) and the review console (/admin); build_admin_console.py reuses all of it:
# the palette (ROOT_CSS; light only, as in the Lovable design), the component styles (BASE_CSS: header, stat chips, filter bar, checkboxes,
# selects, buttons, tags) and the top nav. Light, shadcn-like: white cards, light grey borders, dark green primary.
ROOT_CSS = r''':root{color-scheme:light;
 --bg:#f1f1f3;--surface:#fcfcfc;--sunk:#f6f6f8;--ink:#131315;--ink2:#3f3f46;--mute:#6b6b75;--faint:#9a9aa3;--line:#dddde1;--line2:#ececee;
 --accent:#12645b;--accent-bg:#dfeeeb;--accent-line:#b5d6cf;--warn:#764802;--warnbg:#f5ebd3;--hold:#9f2f2d;--holdbg:#fbeaea;--info:#3f4f6b;--infobg:#eceff5;
 --btn:#131315;--btn-ink:#fafafa;--pri:#12645b;--pri-hover:#0e5149;--pri-ink:#ffffff;--shadow:0 1px 2px rgba(16,24,40,.06);
 --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
 --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}'''
CHECK_SVG = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
             "stroke='white' stroke-width='3.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M20 6 9 17l-5-5'/%3E%3C/svg%3E\")")
CHEVRON_SVG = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
               "stroke='%236b6b75' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")")
BASE_CSS = r'''*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;font:14px/1.6 var(--sans);color:var(--ink);-webkit-font-smoothing:antialiased}
.wrap{max-width:1320px;margin:0 auto;padding:24px 24px 64px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:22px}
.logo{width:44px;height:44px;border-radius:10px;background:var(--btn);color:var(--btn-ink);display:flex;align-items:center;justify-content:center;font:700 16px/1 var(--sans);letter-spacing:.03em;flex:none}
.ttl{flex:1;min-width:220px}.ttl h1{margin:0;font-size:21px;font-weight:700;letter-spacing:-.01em;line-height:1.3}
.ttl p{margin:3px 0 0;color:var(--mute);font-size:12.5px}
.stats{display:flex;gap:10px;flex-wrap:wrap}
.stat{display:inline-flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:7px 16px;box-shadow:var(--shadow)}
.stat small{font-size:12.5px;color:var(--mute);white-space:nowrap}.stat b{font:700 16px/1.2 var(--mono);font-variant-numeric:tabular-nums;color:var(--ink)}
.stat.s-done b,.stat.ok b{color:var(--accent)}.stat.s-todo b,.stat.wn b{color:var(--warn)}.stat.hd b{color:var(--hold)}
.bar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;font-size:13px;color:var(--ink2);padding:0 0 16px;margin:0 0 18px;border-bottom:1px solid var(--line)}
.bar .lbl,.bar label>.lbl{color:var(--mute)}
.bar label{white-space:nowrap;cursor:pointer;display:inline-flex;align-items:center;gap:7px}.bar .sp{flex:1}
.bar .n{color:var(--mute);font-variant-numeric:tabular-nums}
#flt{display:inline-flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
.bx{display:inline-flex;gap:10px;align-items:center}
select{appearance:none;-webkit-appearance:none;font:inherit;font-size:13px;color:var(--ink);padding:6px 30px 6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--surface) __CHEVRON__ right 9px center/14px no-repeat;box-shadow:var(--shadow);cursor:pointer;max-width:100%}
input[type=search]{font:inherit;font-size:13px;color:var(--ink);padding:6px 12px;border:1px solid var(--line);border-radius:8px;background:var(--surface);box-shadow:var(--shadow)}
input[type=checkbox]{appearance:none;-webkit-appearance:none;width:16px;height:16px;margin:0;border:1.5px solid var(--accent);border-radius:4px;background:var(--surface);cursor:pointer;flex:none;transition:background-color .15s,border-color .15s}
input[type=checkbox]:checked{background:var(--accent) __CHECK__ center/11px no-repeat;border-color:var(--accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 14px;font:inherit;font-size:13px;font-weight:600;line-height:1.5;cursor:pointer;white-space:nowrap;text-decoration:none;box-shadow:var(--shadow);transition:background-color .15s,border-color .15s,color .15s}
.btn:hover{background:var(--sunk);border-color:var(--faint)}.btn:active{transform:translateY(1px)}.btn:disabled{color:var(--faint);cursor:default}
.btn.pri{background:var(--pri);color:var(--pri-ink);border-color:var(--pri)}.btn.pri:hover{background:var(--pri-hover);border-color:var(--pri-hover)}
.ic{width:15px;height:15px;flex:none}
.tg{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:600;line-height:1.5;border-radius:6px;padding:0 7px;background:var(--infobg);color:var(--info);border:1px solid transparent;white-space:nowrap}
.tg .ic{width:12px;height:12px}
.tg.q{background:var(--accent-bg);color:var(--accent);border-color:var(--accent-line)}
.tg.ht{background:var(--warnbg);color:var(--warn)}.tg.ok{background:var(--accent-bg);color:var(--accent)}
.ext{display:inline-flex;align-items:center;gap:4px;color:var(--accent);font-weight:600;text-decoration:none}.ext:hover{text-decoration:underline;text-underline-offset:3px}
.ext .ic{width:13px;height:13px}
button:focus-visible,select:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:820px){.wrap{padding:14px 12px 40px}.ttl h1{font-size:18px}.stats{width:100%}.stat{flex:1 1 auto;justify-content:center;padding:6px 10px}
 .bar{gap:10px 14px}.bar .sp{display:none}.bx{width:100%}.bx>.btn{flex:1}}'''.replace('__CHECK__', CHECK_SVG).replace('__CHEVRON__', CHEVRON_SVG)
NAV_CSS = ('.topnav{display:inline-flex;gap:2px;background:var(--surface);border:1px solid var(--line);border-radius:10px;'
           'padding:4px;margin-bottom:22px;box-shadow:var(--shadow)}'
           '.topnav a{color:var(--ink);text-decoration:none;font-weight:600;font-size:13px;line-height:1.5;'
           'padding:6px 14px;border-radius:7px;transition:background-color .15s,color .15s}'
           '.topnav a:hover{background:var(--sunk)}'
           '.topnav a[aria-current=page]{background:var(--accent-bg);color:var(--accent)}')
NAV_LINKS = (('/', '运营看板'), ('/admin', '审稿后台'))


def nav_html(current):
    links = ''.join(f'<a href="{href}"{" aria-current=page" if href == current else ""}>{label}</a>'
                    for href, label in NAV_LINKS)
    return f'<nav class="topnav" aria-label="页面">{links}</nav>'


ICON = {   # inline SVG paths (lucide-style, 24x24 stroke icons) - no icon font / CDN at runtime
    'refresh': '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M8 16H3v5"/>',
    'download': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
}


def icon(name):
    return (f'<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICON[name]}</svg>')


PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>FD 发帖看板</title>
<style>
__ROOTVARS__
__BASECSS__
/* account x posts table: account column + two post columns, one row per account */
.tbl{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden;box-shadow:var(--shadow)}
.thead,.row{display:grid;grid-template-columns:232px minmax(0,1fr)}
.thead{background:var(--sunk);border-bottom:1px solid var(--line);font-size:12px;color:var(--mute)}
.thead>div,.thead .ph2>div{padding:11px 18px}.thead b{color:var(--ink);font-weight:650;margin-right:8px}
.thead .ph2{display:grid;grid-template-columns:1fr 1fr;padding:0}.thead .ph2>div+div{border-left:1px solid var(--line)}
.thead>div:first-child{border-right:1px solid var(--line)}
.row+.row{border-top:1px solid var(--line)}
.side{padding:20px 18px;border-right:1px solid var(--line);min-width:0}
.who{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.av{width:40px;height:40px;border-radius:50%;object-fit:cover;display:flex;align-items:center;justify-content:center;color:#fafafa;font-size:17px;font-weight:600;flex:none}
.side h2{margin:0;font-size:15px;font-weight:650;line-height:1.35;letter-spacing:-.005em;word-break:break-word}
.side .pf{font-size:12px;color:var(--mute);margin-top:1px}
.side .hd{font-size:12px;color:var(--mute);line-height:1.6}
.side .bt{font-size:12px;color:var(--mute);line-height:1.55;margin-top:2px}
.side .st{display:inline-block;font-size:11px;font-weight:600;color:var(--info);background:var(--infobg);border-radius:999px;padding:0 8px;margin-top:6px}
.pill{display:inline-block;margin-top:10px;background:var(--sunk);border:1px solid var(--line);color:var(--ink2);font:500 12px/1.6 var(--sans);font-variant-numeric:tabular-nums;border-radius:999px;padding:1px 10px}
.pill b{font:500 12px var(--mono)}
.more{display:block;margin-top:12px;background:none;border:0;padding:0;font:inherit;font-size:12.5px;color:var(--accent);font-weight:600;cursor:pointer}
.more:hover{text-decoration:underline;text-underline-offset:3px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line2);min-width:0}
.blank{background:var(--sunk);display:flex;align-items:center;justify-content:center;color:var(--faint);min-height:96px}
.post{background:var(--surface);padding:18px 18px 14px;display:flex;flex-direction:column;min-width:0}
.post.posted>:not(.foot){opacity:.5}.post.posted .foot .cp{opacity:.6}
.ph{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.ph .tm{color:var(--ink);font:700 15px/1.3 var(--mono);font-variant-numeric:tabular-nums;letter-spacing:.01em;white-space:pre}
.ph .pl{display:none;font-size:11.5px;color:var(--faint)}
.ph .st{margin-left:auto;font-size:11.5px;font-weight:600;border-radius:999px;padding:1px 9px;background:var(--warnbg);color:var(--warn);white-space:nowrap}
.ph .st.ok{background:var(--accent-bg);color:var(--accent)}.ph .st.hold{background:var(--holdbg);color:var(--hold)}
.em{color:var(--ink2);font-size:12px}
.tgt{margin:0 0 14px;font-size:13px;color:var(--ink2)}.tgt summary{cursor:pointer;font-weight:600}
.tgt table{border-collapse:collapse;margin-top:8px;width:100%}.tgt th,.tgt td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line,#e5e5e5);white-space:nowrap}
.mode{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;font-size:12.5px;color:var(--ink2)}
.act{font-size:13px;font-weight:600;line-height:1.5;color:var(--accent);border:1.5px solid var(--accent);border-radius:8px;padding:6px 10px;margin-bottom:10px;word-break:break-all}.act a{color:inherit}.act .tt{font-weight:400;color:var(--fg,inherit);opacity:.85;margin-top:4px;word-break:normal}
.note{font-size:12.5px;line-height:1.5;color:var(--warn);background:var(--warnbg);border-radius:8px;padding:6px 10px;margin-bottom:10px}
.note.mv{color:var(--info);background:var(--infobg);align-self:flex-start}
.txt{white-space:pre-wrap;word-break:break-word;font-size:14.5px;line-height:1.75;color:var(--ink)}
.txt:lang(en){font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",system-ui,"Helvetica Neue",Arial,sans-serif;line-height:1.7}
.post:not(.open) .clamp{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;line-clamp:3;overflow:hidden}
.post:not(.open) .part+.part{display:none}.post:not(.open) .part .pr{display:none}
.xp{align-self:flex-start;display:inline-flex;align-items:center;gap:6px;margin-top:6px;background:none;border:0;padding:2px 0;font:inherit;font-size:12.5px;color:var(--ink2);cursor:pointer}
.xp:hover{color:var(--ink)}.xp .ic{width:14px;height:14px;transition:transform .15s}.post.open .xp .ic{transform:rotate(180deg)}.xp[hidden]{display:none}
.part{border-top:1px dashed var(--line);padding-top:10px;margin-top:10px}.part:first-child{border-top:0;margin-top:0;padding-top:0}
.part .pr{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--mute);margin-bottom:2px}
.part .cnt{margin-top:4px}
.cp1{display:inline-flex;align-items:center;gap:5px;background:var(--surface);border:1px solid var(--line);border-radius:6px;font:inherit;font-size:12px;font-weight:600;padding:1px 9px;cursor:pointer;color:var(--ink2)}
.cp1:hover{border-color:var(--faint)}.cp1.done{color:var(--accent);border-color:var(--accent)}
.att{display:flex;align-items:center;gap:12px;margin-top:12px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--sunk)}
.att .th{display:block;width:56px;height:42px;border-radius:6px;border:2px solid var(--accent-line);overflow:hidden;flex:none;background:#131722}
.att .th img{width:100%;height:100%;object-fit:cover;display:block}
.att .lb{display:flex;flex-direction:column;min-width:0;flex:1}
.att .lb b{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:650;color:var(--ink)}.att .lb b .ic{color:var(--accent);width:15px;height:15px}
.att .lb small{font-size:11px;color:var(--faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.att .dl{display:inline-flex;color:var(--ink2);padding:7px;border-radius:8px;flex:none}.att .dl:hover{background:var(--line2);color:var(--ink)}.att .dl .ic{width:17px;height:17px}
.fill{flex:1;min-height:6px}
.cnt{font-size:11.5px;line-height:1.5;color:var(--faint);margin-top:10px;font-variant-numeric:tabular-nums}
.foot{display:flex;align-items:center;justify-content:space-between;margin-top:8px;padding-top:12px;border-top:1px solid var(--line);gap:10px;flex-wrap:wrap}
.done-l{display:inline-flex;align-items:center;gap:9px;color:var(--ink2);font-size:13px;cursor:pointer;user-select:none}
.done-l input{width:18px;height:18px;border-radius:5px}.done-l:has(input:checked){color:var(--accent);font-weight:600}
.foot-r{display:inline-flex;align-items:center;gap:8px;margin-left:auto}
.xob{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--ink2);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 12px;text-decoration:none;box-shadow:var(--shadow);white-space:nowrap;transition:background-color .15s,border-color .15s}
.xob:hover{background:var(--sunk);border-color:var(--faint);color:var(--ink)}.xob .ic{width:13px;height:13px}
.ap-time{font-size:11px;color:var(--accent);font-weight:600;white-space:nowrap}
.cp{display:inline-flex;align-items:center;gap:8px;background:var(--pri);color:var(--pri-ink);border:1px solid var(--pri);border-radius:8px;padding:7px 14px;font:inherit;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;box-shadow:0 1px 2px rgba(16,24,40,.12);transition:background-color .15s,transform .1s}
.cp:hover{background:var(--pri-hover)}.cp:active,.cp1:active{transform:translateY(1px)}
.cp.done{background:var(--accent-bg);border-color:var(--accent-line);color:var(--accent)}.cp .ic{width:15px;height:15px}
.post.notready .cp{background:var(--surface);color:var(--ink2);border-color:var(--line);box-shadow:var(--shadow)}
.post.notready .foot .cnt{margin:0}
.empty{text-align:center;color:var(--mute);padding:48px 16px;background:var(--surface);border:1px solid var(--line);border-radius:12px;margin:0}
.ttl p .sy.bad{color:var(--hold)}
@media (max-width:820px){
 .thead{display:none}
 .row{grid-template-columns:1fr}
 .side{border-right:0;border-bottom:1px solid var(--line2);padding:14px 14px 12px}
 .who{margin-bottom:6px}.pill{margin-top:8px}
 .grid{grid-template-columns:1fr}.blank{display:none}
 .post{padding:14px}.ph .pl{display:inline}
}
__NAVCSS__
</style></head><body><div class="wrap">
__NAV__
<header><div class="logo">FD</div>
<div class="ttl"><h1>FD 发帖看板</h1><p><span id="upd"></span> · <span title="复制正文，到 X 发布，再勾选已发（所有人同步可见）">已发状态：所有人同步</span> · <span class="sy" id="sync"></span></p></div>
<div class="stats"><div class="stat"><small>可发</small><b id="nAll">0</b></div><div class="stat s-done"><small>已发</small><b id="nDone">0</b></div><div class="stat s-todo"><small>待发</small><b id="nTodo">0</b></div></div>
</header>
<div class="bar"><label><span class="lbl">日期</span><select id="day"></select></label>
<span id="flt"></span>
<label><input type="checkbox" id="hidePosted"> 隐藏已发</label>
<label><input type="checkbox" id="hideEmpty" checked> 隐藏无稿账号</label>
<span class="sp"></span><span class="bx"><button class="btn rf" id="refresh" title="重新读取最新稿件和审稿决定">__I_REFRESH__<span>刷新</span></button><a class="btn" id="csv" href="#" download>__I_DOWNLOAD__<span>下载 CSV</span></a></span></div>
<main id="main"></main></div>
<script id="data" type="application/json">__DATA__</script>
<script>
let D=JSON.parse(document.getElementById('data').textContent),RAW=document.getElementById('data').textContent;
const ST_LABEL={draft_ready:'可发',expired:'已过期（窗口已关）',HOLD:'HOLD（暂缓）',superseded:'已替换（审稿退回）',needs_review:'待复核',blocked:'失败',skipped:'跳过'};
const COLORS=['#5b6475','#7a6a58','#4f6f68','#5f6b85','#76705a','#7a5c66','#556b7d','#6b5f7a','#5d7462','#735d55'];
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
__SHARED__
// 已发 is shared: /api/decisions (action published / unpublish / clear). Ticks not saved yet wait in localStorage
// (fdops:pending:<day>); the old per-browser ticks (fdops:posted:<id>) are pushed to the shared flag once.
const live={};   // day -> {id: decision} from /api/decisions; absent = not loaded, the build-time overlay stands
const PEND='fdops:pending:',LEGACY='fdops:posted:';
const pend=day=>{try{return JSON.parse(localStorage.getItem(PEND+day)||'{}')}catch(_){return {}}};
function setPend(day,p){Object.keys(p).length?localStorage.setItem(PEND+day,JSON.stringify(p)):localStorage.removeItem(PEND+day)}
const shown=new Set(JSON.parse(localStorage.getItem('fdops:statuses')||'["draft_ready"]'));
const expanded=new Set();
const daySel=$('#day');let days=[];
const latest=()=>days.find(d=>(D.days[d]||[]).length)||days[0]||'';   // newest day with drafts (Beijing dates)
function fillDays(keep){days=Object.keys(D.days).sort().reverse();daySel.innerHTML=days.map(d=>`<option>${d}</option>`).join('');daySel.value=days.includes(keep)?keep:latest()}
const want=location.hash.slice(1);fillDays(want);
let follow=daySel.value===latest();   // follow the newest day until someone picks another one
$('#hidePosted').checked=localStorage.getItem('fdops:hidePosted')==='1';
const ic=p=>`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const COPY_SVG=ic('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>');
const I={ext:ic('<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'),
  down:ic('<path d="m6 9 6 6 6-6"/>'),dl:ic('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>'),
  img:ic('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>'),
  quote:ic('<path d="M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/><path d="M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/>'),
  reply:ic('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>')};
const opened=new Set();   // posts whose full text is shown (展开正文)
const bjtDay=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
const bjtTime=d=>d.toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
function when(t){
  if(!t)return '-';const day=t.slice(0,10),hm=t.slice(11,16);
  const today=bjtDay(new Date()),diff=Math.round((Date.parse(day)-Date.parse(today))/864e5);
  const lbl={'-2':'前天','-1':'昨天','0':'今天','1':'明天','2':'后天'}[diff]||day.slice(5);
  return `${lbl} ${hm}`;
}
const X_LIGHT=[[0,4351],[8192,8205],[8208,8223],[8242,8247]],URL_RE=/https?:\/\/\S+/g;
function xw(t){return 23*(t.match(URL_RE)||[]).length+[...t.replace(URL_RE,'')].reduce((n,c)=>{const o=c.codePointAt(0);return n+(X_LIGHT.some(([lo,hi])=>o>=lo&&o<=hi)?1:2)},0)}
// live decision overlay = build_ops_dashboard.apply_decisions, on the pre-decision fields (d.base)
function eff(d,day){
  const L=live[day];if(!L)return d;
  const b=d.base||d,x=L[d.id]||null,act=x&&x.action;
  const e={...d,...b,base:undefined,published:isPublished(x),decision:'',edited:false};
  if(!['approve','published','hold','rewrite','edit'].includes(act))return e;
  e.decision=act;const t=String(x.text||'').trim();
  if(t&&t!==b.text){e.text=t;e.edited=true;e.chars=[...t].length;e.xw=xw(t);
    if(e.parts){e.parts=t.split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean);e.parts_w=e.parts.map(xw)}}
  if(act==='approve'||act==='published'){e.status='draft_ready';e.note=''}
  else if(act==='hold'||act==='rewrite'){e.status='HOLD';e.note=`Fiona ${act==='hold'?'HOLD':'要求重写'}${x.note?'：'+x.note:''}`}
  return e;
}
function cnt(t,w,lang){const n=[...t].length;return `${n} ${lang==='en'?'字符':'字'} · X计 ${w}`}   // all accounts have X Premium: no 280 warning
function hue(id){let h=0;for(const c of String(id))h=(h*31+c.charCodeAt(0))>>>0;return COLORS[h%COLORS.length]}
function avatar(a){
  if(a.avatar)return `<img class="av" src="${a.avatar}" alt="">`;
  const ch=[...String(a.name||a.id).replace(/^[^\p{L}\p{N}]+/u,'')][0]||'?';
  return `<div class="av" style="background:${hue(a.id)}">${esc(ch.toUpperCase())}</div>`;
}
// Build the x.com/intent/post URL for opening X's composer with pre-filled text.
// standalone: text only; reply: in_reply_to=<status id> + text; quote: text + "\n" + target URL.
// Uses the same body text as the copy button (draft body, no 来源 footer).
// Thread: button on part 1 only; the rest go as replies from the same account.
function intentUrl(d){
  const base='https://x.com/intent/post';
  // for threads, only part 1 is pre-filled; the others must be sent as self-replies
  const text=d.parts&&d.parts.length>1?d.parts[0]:d.text;
  const p=new URLSearchParams();
  if(d.mode==='reply'&&d.target){
    const m=d.target.match(/\/status\/(\d+)/);
    if(m)p.set('in_reply_to',m[1]);
    p.set('text',text);
  }else if(d.mode==='quote'&&d.target){
    p.set('text',text+'\n'+d.target);
  }else{
    p.set('text',text);
  }
  return base+'?'+p.toString();
}
function card(d,posted,slot){
  const ready=d.status==='draft_ready',p=ready&&posted,hold=d.status==='HOLD'||d.status==='superseded',lg=d.lang==='en'?'en':'zh-CN';
  const st=p?'<span class="st ok">已发</span>':hold?`<span class="st hold">${d.status==='HOLD'?'HOLD':'已替换'}</span>`:d.status==='draft_ready'?'<span class="st">待发出</span>':`<span class="st">${esc(ST_LABEL[d.status]||d.status)}</span>`;
  const multi=d.parts&&d.parts.length>1;
  let body;
  if(multi){
    body=`<div class="parts">${d.parts.map((t,i)=>`<div class="part"><div class="pr"><span>${i+1}/${d.parts.length}</span><button class="cp1" data-t="${esc(t)}">复制</button>${i===0?`<a class="xob" href="${esc(intentUrl(d))}" target="_blank" rel="noopener noreferrer" title="在当前登录的 X 账号里打开发帖框（第 1 段；其余段请在 X 里逐条回复）">在X打开${I.ext}</a>`:''}${d.auto_posted_at&&i===0?`<span class="ap-time">自动识别已发 ${d.auto_posted_at}</span>`:''}
</div><div class="txt${i?'':' clamp'}" lang="${lg}">${esc(t)}</div><div class="cnt">${cnt(t,d.parts_w[i],d.lang)}</div></div>`).join('')}</div>`;
  }else body=`<div class="txt clamp" lang="${lg}">${esc(d.text)}</div>`;
  const xp=`<button class="xp" data-o="${esc(d.id)}" aria-expanded="${opened.has(d.id)}"><span>${opened.has(d.id)?'收起正文':multi?`展开全部 ${d.parts.length} 段`:'展开正文'}</span>${I.down}</button>`;
  const ML={quote:'引用',reply:'回复'};
  const rv=(d.decision==='approve'||d.decision==='published'?'<span class="tg ok">审稿已批准</span>':'')+(d.edited?'<span class="tg ok">审稿已改稿</span>':'');
  const mode=(ML[d.mode]||d.heat_led||d.archive||d.hotspot||rv)?`<div class="mode">${rv}${d.hotspot?`<span class="tg ht">热点</span><span>${esc(d.hotspot)}</span>`:''}${d.archive?`<span class="tg">${d.archive_variant==='evergreen'?'常青':'回看'}</span>`:''}${ML[d.mode]?`<span class="tg q">${d.mode==='reply'?I.reply:I.quote}${ML[d.mode]}</span>${d.engage_meta?`<span class="em">${esc(d.engage_meta)}</span>`:''}`:''}${d.heat_led?'<span class="tg ht">热度</span>':''}${ML[d.mode]&&d.target?`<a class="ext" href="${esc(d.target)}" target="_blank" rel="noopener noreferrer">打开原帖${I.ext}</a>`:''}${d.archive&&d.archive_url?`<a class="ext" href="${esc(d.archive_url)}" target="_blank" rel="noopener noreferrer">${d.archive_variant==='evergreen'?'常青原帖':'回看原帖'}${I.ext}</a>`:''}</div>`:'';
  const imgs=(d.media||[]).map((m,i)=>{const u=esc(m.src||m.path),info=[m.credit?'数据：'+m.credit:'',m.updated?'图更新于 北京时间 '+m.updated:''].filter(Boolean).join(' · ');
    return `<div class="att"><a class="th" href="${u}" target="_blank" rel="noopener" title="打开大图"><img src="${u}" alt="${esc(m.alt)}" loading="lazy"></a><div class="lb"><b>${I.img}配图 ${i+1}</b>${info?`<small title="${esc(info)}">${esc(info)}</small>`:''}</div><a class="dl" href="${u}" download="${esc(m.path.split('/').pop())}" title="下载图片" aria-label="下载图片">${I.dl}</a></div>`}).join('');
  const total=multi?`共 ${d.parts.length} 段 · ${cnt(d.text,d.xw,d.lang)}`:cnt(d.text,d.xw,d.lang);
  // auto_posted_at: set by auto_published.py when it detects a matching tweet (北京时间 HH:MM)
  const apTime=d.auto_posted_at?`<span class="ap-time">自动识别已发 ${esc(d.auto_posted_at)}</span>`:'';
  const xoBtn=`<a class="xob btn" href="${esc(intentUrl(d))}" target="_blank" rel="noopener noreferrer" title="在当前登录的 X 账号里打开发帖框${multi?' （第 1 段；其余段请在 X 里逐条回复）':''}">在X打开${I.ext}</a>`;
  return `<div class="post${p?' posted':''}${ready?'':' notready'}${opened.has(d.id)?' open':''}" data-id="${esc(d.id)}"><div class="ph"><span class="pl">帖子 ${slot} ·</span><span class="tm" title="建议发出（北京时间）">${when(d.time)}</span>${st}</div>${d.note?`<div class="note${d.note.startsWith('改派自')?' mv':''}">${esc(d.note)}</div>`:''}${d.action&&d.target?`<div class="act">${d.mode==='reply'?'用 X 的「回复」发在这条帖子下面':'用 X 的「引用」转发这条帖子'}（不要单独发）：<a href="${esc(d.target)}" target="_blank" rel="noopener noreferrer">${esc(d.target)}</a>${d.target_text?`<div class="tt">原帖${d.target_author?' @'+esc(d.target_author):''}：「${esc(d.target_text)}」</div>`:''}</div>`:''}${mode}${body}${xp}${imgs}<div class="fill"></div><div class="cnt">${total}</div>
<div class="foot">${ready?`<label class="done-l"><input type="checkbox" data-p="${esc(d.id)}" ${p?'checked':''}> 已发</label>${apTime}`:'<span class="cnt">不可发：先改稿或等重写</span>'}<div class="foot-r">${ready?xoBtn:''}<button class="cp" data-t="${esc(d.text)}">${COPY_SVG}<span>${multi?'复制全部':'一键复制'}</span></button></div></div></div>`;
}
// 展开正文 only where the text is cut (3 lines) or a thread has more parts
function fitClamp(){
  for(const p of document.querySelectorAll('.post')){
    const b=p.querySelector('.xp');if(!b||p.classList.contains('open'))continue;
    const t=p.querySelector('.clamp');b.hidden=!(p.querySelector('.part+.part')||(t&&t.scrollHeight>t.clientHeight+2));
  }
}
let fitT=0;addEventListener('resize',()=>{clearTimeout(fitT);fitT=setTimeout(fitClamp,150)});
let syncAt=null,syncErr='';
function syncLine(){
  const n=Object.keys(pend(daySel.value)).length,s=$('#sync');
  s.textContent=syncErr?`审稿同步失败（${syncErr}），显示的是上次构建的数据`+(n?` · ${n} 条已发未同步（已存本机）`:''):
    (syncAt?`审稿同步于 ${bjtTime(syncAt)}`:'审稿同步中…')+(n?` · ${n} 条已发未同步（已存本机）`:'');
  s.classList.toggle('bad',!!syncErr||n>0);
}
function render(){
  const day=daySel.value;
  history.replaceState(null,'',location.pathname+location.search+(follow||!day?'':'#'+day));
  syncLine();
  if(!day){$('#main').innerHTML='<p class="empty">还没有任何稿件</p>';$('#csv').style.display='none';return}
  $('#csv').style.display='';$('#csv').href=day+'.csv';$('#csv').setAttribute('download','fd_'+day+'.csv');
  const drafts=(D.days[day]||[]).map(d=>eff(d,day)),pp=pend(day),isPosted=d=>d.id in pp?!!pp[d.id]:!!d.published;
  const sts=[...new Set(drafts.map(d=>d.status))].sort();
  $('#flt').innerHTML='<span class="lbl">状态</span>'+sts.map(s=>`<label><input type="checkbox" data-s="${esc(s)}" ${shown.has(s)?'checked':''}> ${esc(ST_LABEL[s]||s)} <span class="n">(${drafts.filter(d=>d.status===s).length})</span></label>`).join('');
  const hideP=$('#hidePosted').checked,hideE=$('#hideEmpty').checked;
  let all=0,done=0;const out=[];
  for(const a of D.accounts){
    const mine=drafts.filter(d=>d.account_id===a.id&&shown.has(d.status));
    const rd=drafts.filter(d=>d.account_id===a.id&&d.status==='draft_ready');   // counts: ready drafts only
    const nDone=rd.filter(isPosted).length;all+=rd.length;done+=nDone;
    const cards=mine.filter(d=>!(hideP&&d.status==='draft_ready'&&isPosted(d)));
    if(!cards.length&&hideE)continue;
    const open=expanded.has(a.id),lim=2,vis=open?cards:cards.slice(0,lim);
    const more=cards.length>lim?`<button class="more" data-x="${esc(a.id)}">${open?'收起':`展开全部 ${cards.length} 条`}</button>`:'';
    const cells=vis.map((d,i)=>card(d,isPosted(d),i+1)).join('')+'<div class="blank" aria-hidden="true">—</div>'.repeat(vis.length?vis.length%2:2);
    out.push(`<section class="row"><div class="side"><div class="who">${avatar(a)}<div><h2>${esc(a.name)}</h2><div class="pf">X${a.lang?` · ${a.lang==='zh'?'中文':'English'}`:''}</div></div></div><div class="hd">${esc(a.handle?(a.handle.startsWith('@')?a.handle:'@'+a.handle):'@待填')}</div>${a.beat?`<div class="bt">${esc(a.beat)}</div>`:''}${{new:'<div class="st">新号</div>',spare_active:'<div class="st">备用号启用</div>'}[a.status]||''}<span class="pill">待发 <b>${rd.length-nDone}/${rd.length}</b></span>${more}</div>
<div class="grid">${cells}</div></section>`);
  }
  const TH='<div class="thead"><div><b>账号</b></div><div class="ph2"><div><b>帖子 1</b>建议发出 · 北京时间</div><div><b>帖子 2</b>建议发出 · 北京时间</div></div></div>';
  const tg=(D.targets||{})[day]||[],nm=Object.fromEntries(D.accounts.map(a=>[a.id,a.name]));
  const TG=tg.length?`<details class="tgt"><summary>今日蹭流量目标 ${tg.length} 个（引用 / 回复大号新帖）</summary><table><tr><th>账号</th><th>方式</th><th>目标</th><th>粉丝</th><th>选中时赞 / 阅</th><th>发出时帖龄</th><th>建议发出</th><th>其他号的池里也有</th></tr>${tg.map(t=>`<tr><td>${esc(nm[t.account]||t.account)}</td><td>${t.mode==='reply'?'回复':'引用'}</td><td><a href="${esc(t.target_url||'')}" target="_blank" rel="noopener noreferrer">@${esc(t.author||'')}</a></td><td>${t.author_followers==null?'-':(t.author_followers/10000).toFixed(1)+'万'}</td><td>${t.likes_at_selection??'-'} / ${t.views_at_selection??'-'}</td><td>${t.age_h_at_post??'-'}h</td><td>${esc((t.slot_bjt||'').slice(11,16))}</td><td>${esc((t.passed_over||[]).map(x=>nm[x]||x).join('、')||'—')}</td></tr>`).join('')}</table></details>`:'';
  $('#main').innerHTML=out.length?`${TG}<div class="tbl">${TH}${out.join('')}</div>`:(drafts.length?`<p class="empty">当前筛选下没有稿件（共 ${drafts.length} 篇，可在「状态」里勾选其他状态）</p>`:'<p class="empty">这一天没有稿件</p>');
  fitClamp();
  $('#nAll').textContent=all;$('#nDone').textContent=done;$('#nTodo').textContent=all-done;
}
async function pushPosted(day,d,on){
  const L=live[day],x=L?L[d.id]||null:null;
  if(!on&&L&&!isPublished(x))return true;   // nothing shared to undo
  // unticking a decision that is only 已发 clears it; anything else (an admin's edit / approve) keeps it: unpublish
  const action=on?'published':x&&x.action==='published'&&!x.text&&!x.before_publish?'clear':'unpublish';
  try{
    const r=await fetch('/api/decisions',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({day,id:d.id,account_id:d.account_id,action})});
    if(!r.ok)throw new Error('HTTP '+r.status);
    const j=await r.json();if(live[day])live[day][d.id]=j.decision;return true;
  }catch(e){syncErr=String(e.message||e);return false}
}
async function setPosted(id,on){
  const day=daySel.value,d=(D.days[day]||[]).find(x=>x.id===id);if(!d)return;
  const p=pend(day);p[id]=on;setPend(day,p);render();
  if(await pushPosted(day,d,on)){const q=pend(day);if(q[id]===on)delete q[id];setPend(day,q);if(!live[day])await syncDecisions()}
  render();
}
async function syncDecisions(){
  const day=daySel.value;if(!day)return;
  try{
    const r=await fetch('/api/decisions?day='+encodeURIComponent(day),{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    live[day]=(await r.json()).decisions||{};syncErr='';syncAt=new Date();
    const p=pend(day);
    for(const id of Object.keys(p)){const d=(D.days[day]||[]).find(x=>x.id===id);if(!d||await pushPosted(day,d,p[id])){const q=pend(day);delete q[id];setPend(day,q)}}
    for(const d of D.days[day]||[]){
      if(localStorage.getItem(LEGACY+d.id)!=='1')continue;
      const e=eff(d,day);if(e.published||e.status!=='draft_ready'||await pushPosted(day,d,true))localStorage.removeItem(LEGACY+d.id);
    }
  }catch(e){syncErr=String(e.message||e)}
  render();
}
// new drafts arrive with the nightly rebuild: re-read this page's own data block (cache: no-store on 刷新)
async function refreshData(cache){
  try{
    const r=await fetch(location.pathname,{cache});if(!r.ok)throw new Error('HTTP '+r.status);
    const m=(await r.text()).match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/);
    if(!m||m[1]===RAW)return;
    D=JSON.parse(m[1]);RAW=m[1];fillDays(follow?'':daySel.value);follow=daySel.value===latest();upd();
  }catch(e){syncErr='页面数据刷新失败 '+String(e.message||e)}
}
async function copy(t){try{await navigator.clipboard.writeText(t)}catch(_){const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}}
document.addEventListener('click',async e=>{
  const x=e.target.closest('.more');if(x){expanded.has(x.dataset.x)?expanded.delete(x.dataset.x):expanded.add(x.dataset.x);render();return}
  const o=e.target.closest('.xp');if(o){const p=o.closest('.post'),on=!opened.has(o.dataset.o);on?opened.add(o.dataset.o):opened.delete(o.dataset.o);
    p.classList.toggle('open',on);o.setAttribute('aria-expanded',on);o.querySelector('span').textContent=on?'收起正文':p.querySelector('.part+.part')?`展开全部 ${p.querySelectorAll('.part').length} 段`:'展开正文';return}
  const b=e.target.closest('.cp,.cp1');if(!b)return;
  await copy(b.dataset.t);
  const lab=b.querySelector('span')||b,old=lab.textContent;
  lab.textContent='已复制';b.classList.add('done');setTimeout(()=>{lab.textContent=old;b.classList.remove('done')},1500);
});
document.addEventListener('change',e=>{
  const el=e.target;
  if(el.dataset.p)return setPosted(el.dataset.p,el.checked);
  if(el.dataset.s){el.checked?shown.add(el.dataset.s):shown.delete(el.dataset.s);localStorage.setItem('fdops:statuses',JSON.stringify([...shown]))}
  else if(el.id==='hidePosted')localStorage.setItem('fdops:hidePosted',el.checked?'1':'0');
  render();
});
// CSV of the shown day with the live decisions (the static <day>.csv is the build-time copy)
$('#csv').addEventListener('click',e=>{
  const day=daySel.value;if(!live[day])return;
  e.preventDefault();
  const names=Object.fromEntries(D.accounts.map(a=>[a.id,a.name])),q=v=>/[",\r\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;
  const rows=[['account','time (北京时间)','text','引用/回复'],...(D.days[day]||[]).map(d=>eff(d,day)).filter(d=>d.status==='draft_ready'&&d.text).map(d=>[names[d.account_id]??d.account_id,d.time.slice(0,16).replace('T',' '),d.text,d.action||''])];
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['﻿'+rows.map(r=>r.map(v=>q(String(v??''))).join(',')).join('\n')+'\n'],{type:'text/csv'}));
  a.download='fd_'+day+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);
});
function upd(){$('#upd').textContent=D.updated?`数据更新于 北京时间 ${D.updated.slice(5,10)} ${D.updated.slice(11,16)}`:''}
daySel.onchange=()=>{follow=daySel.value===latest();render();syncDecisions()};
$('#refresh').onclick=async()=>{
  const b=$('#refresh'),l=b.querySelector('span');b.disabled=true;l.textContent='刷新中…';
  await refreshData('no-store');await syncDecisions();b.disabled=false;l.textContent='刷新';
};
let tick=0;   // decisions every 60 s; the page data (new days / rebuilt drafts) every 5 min
setInterval(async()=>{if(document.hidden)return;if(++tick%5===0)await refreshData('no-cache');syncDecisions()},60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncDecisions()});
upd();render();syncDecisions();
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
            days[d.name] = clamp_times(apply_decisions(load_day(d), load_decisions(d.name)), d.name,
                                       now=datetime.now(BJT))
    known = {a['id'] for a in accounts}
    for drafts in days.values():   # inbox accounts missing from fd20_accounts.json still get a section
        for d in drafts:
            if d['account_id'] not in known:
                known.add(d['account_id'])
                accounts.append({'id': d['account_id'], 'no': '', 'name': d['name'] or d['account_id'],
                                 'lang': d['lang'], 'beat': '', 'handle': '', 'status': '', 'avatar': ''})
    args.out.mkdir(parents=True, exist_ok=True)
    # last-updated = newest inbox write (deterministic, so an unchanged inbox leaves index.html untouched)
    updated = max((d['stored'] for v in days.values() for d in v if d['stored']), default='')
    targets = {day: t for day in days if (t := load_targets(day))}
    data = json.dumps({'accounts': accounts, 'days': days, 'updated': updated, 'targets': targets},
                      ensure_ascii=False, sort_keys=True)
    page = (PAGE.replace('__ROOTVARS__', ROOT_CSS).replace('__BASECSS__', BASE_CSS).replace('__NAVCSS__', NAV_CSS)
            .replace('__I_REFRESH__', icon('refresh')).replace('__I_DOWNLOAD__', icon('download'))
            .replace('__NAV__', nav_html('/')).replace('__SHARED__', shared_js()))
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
