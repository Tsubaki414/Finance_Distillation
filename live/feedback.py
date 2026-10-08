"""Review feedback -> soft priors for the next day (Oct 8, Sirius borrow: hotspot item 5).

Input (local, no model calls): the /admin decisions pulled by scripts/apply_admin_decisions.py
(live/store/admin_decisions/<day>.json, one latest decision per draft: approve / published / hold / rewrite / edit)
joined with that day's inbox rows (live/store/compose_inbox/<day>/) for the account, angle and 母题 type.

Output (live/store/feedback/, gitignored):
- priors.json: per account, approve rate by angle id and by 母题 type (hotspot topic, or 'regular' for non-hotspot
  drafts), Beta(1, 1)-smoothed, with n. approve / published = approved; hold / rewrite = not approved; edit alone
  (text changed, no verdict) is not counted in the rate.
- style_examples/<account>.jsonl: one row per edited draft (before, after, unified diff), as a local style example.
  Never committed (live/store is gitignored); nothing here is sent anywhere.

Use next day: `angle_multiplier` / `motif_multiplier` give a soft multiplier in [1-MAX_SHIFT, 1+MAX_SHIFT] when an
(account, key) has at least MIN_N decided drafts; otherwise 1.0. A multiplier only reorders; it never adds a topic.

Oct 8 v2 (PM item 5, FD_FEEDBACK_V2=1 default; 0 = the v1 rule above): what ops actually publish teaches the
pipeline. Every draft of a day with decisions gets one outcome (`outcome()`):
  published_asis    已发 flag, text unchanged          score 1.0
  published_edited  已发 flag, posted after an edit    score 0.85 (the diff stays local: style_examples/)
  approved          approved / edited, never posted    score 0.6
  unpicked          ready, no decision, on a closed day on which ops posted another draft of the same account  0.35
  held              hold / 要求重写                    score 0.1
  rejected          compose-inbox reject                score 0.0
  edit_only / none  no verdict: not scored
priors.json then holds, per account and per angle / 母题 type / post_kind / format / media style, the Beta(1,1)-
smoothed mean score with n; a key moves selection only when the account has MIN_ACCOUNT_N scored drafts and the key
MIN_N, by at most +-MAX_SHIFT (same soft re-rank as v1). stats.json (counts, publish / edit / hold rates, hold
reasons; no draft text) feeds the /admin 反馈闭环 panel.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED = {'approve', 'published'}
REJECTED = {'hold', 'rewrite'}
MIN_N = 3
MAX_SHIFT = 0.15
MIN_ACCOUNT_N = 6            # v2: scored drafts an account needs before any of its keys moves selection
SCORE = {'published_asis': 1.0, 'published_edited': 0.85, 'approved': 0.6, 'unpicked': 0.35, 'held': 0.1,
         'rejected': 0.0}
OUTCOMES = ('published_asis', 'published_edited', 'approved', 'edit_only', 'unpicked', 'held', 'rejected', 'none')
DIMS = ('angle', 'motif', 'post_kind', 'format', 'media')
BJT_OFFSET_H = 8


def v2():
    return os.environ.get('FD_FEEDBACK_V2', '1') != '0'


def store_dir():
    return Path(os.environ.get('FD_FEEDBACK_STORE') or ROOT / 'live' / 'store' / 'feedback')


def decisions_dir():
    return Path(os.environ.get('FD_ADMIN_DECISIONS') or ROOT / 'live' / 'store' / 'admin_decisions')


def inbox_dir():
    return Path(os.environ.get('FD_COMPOSE_INBOX') or ROOT / 'live' / 'store' / 'compose_inbox')


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def motif_type(row):
    hot = row.get('hotspot') or {}
    return f"hot:{hot.get('type') or 'other'}" if hot else 'regular'


def angle_of(row):
    a = row.get('angle')
    return (a or {}).get('id') if isinstance(a, dict) else a


def collect(decisions_root=None, inbox_root=None):
    """[(day, row, decision)] for every decided draft found in both stores."""
    out = []
    root = Path(decisions_root or decisions_dir())
    for f in sorted(root.glob('????-??-??.json')):
        data = _read(f) or {}
        day = data.get('day') or f.stem
        rows = {}
        for p in sorted((Path(inbox_root or inbox_dir()) / day).glob('*.json')):
            r = _read(p)
            if isinstance(r, dict) and r.get('id'):
                rows[r['id']] = r
        for did, d in (data.get('decisions') or {}).items():
            if did in rows and isinstance(d, dict):
                out.append((day, rows[did], d))
    return out


def _rate(a, n):
    return round((a + 1) / (n + 2), 4)


def build(decided):
    """{'accounts': {acct: {'overall', 'angle': {id: {...}}, 'motif': {type: {...}}}}, 'edits': [...]}"""
    acc, edits = {}, []
    for day, row, d in decided:
        action = d.get('action')
        a = row.get('account_id')
        if not a:
            continue
        body = (row.get('body') or row.get('text') or '').strip()
        text = (d.get('text') or '').strip()
        if text and text != body:
            edits.append({'day': day, 'account_id': a, 'draft_id': row.get('id'), 'action': action,
                          'angle': angle_of(row), 'motif_type': motif_type(row), 'before': body, 'after': text,
                          'diff': '\n'.join(difflib.unified_diff(body.splitlines(), text.splitlines(), 'draft', 'edited',
                                                                 lineterm='')),
                          'note': d.get('note') or '', 'at': d.get('at') or ''})
        if action not in APPROVED | REJECTED:
            continue
        ok = action in APPROVED
        e = acc.setdefault(a, {'overall': [0, 0], 'angle': {}, 'motif': {}})
        e['overall'][0] += ok
        e['overall'][1] += 1
        for kind, key in (('angle', angle_of(row) or 'none'), ('motif', motif_type(row))):
            c = e[kind].setdefault(key, [0, 0])
            c[0] += ok
            c[1] += 1
    out = {}
    for a, e in acc.items():
        out[a] = {'overall': {'approve_rate': _rate(*e['overall']), 'n': e['overall'][1]},
                  **{kind: {k: {'approve_rate': _rate(*v), 'n': v[1]} for k, v in sorted(e[kind].items())}
                     for kind in ('angle', 'motif')}}
    return {'accounts': out, 'edits': edits}


def write(result, store=None):
    store = Path(store or store_dir())
    store.mkdir(parents=True, exist_ok=True)
    priors = {'version': 'feedback-v1', 'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'rule': 'approve|published = approved; hold|rewrite = not; Beta(1,1) smoothing; soft prior only',
              'accounts': result['accounts']}
    (store / 'priors.json').write_text(json.dumps(priors, ensure_ascii=False, indent=2) + '\n')
    ex = store / 'style_examples'
    ex.mkdir(exist_ok=True)
    by_acct = {}
    for e in result['edits']:
        by_acct.setdefault(e['account_id'], []).append(e)
    for a, rows in by_acct.items():   # rewritten whole each night: the newest decision per draft wins
        (ex / f'{a}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    return priors


def load(store=None):
    return (_read(Path(store or store_dir()) / 'priors.json') or {}).get('accounts') or {}


def _mult(entry, overall):
    if not entry or entry.get('n', 0) < MIN_N or not overall:
        return 1.0
    if 'score' in overall and overall.get('n', 0) < MIN_ACCOUNT_N:   # v2: the account needs a minimum sample first
        return 1.0
    rate = lambda e: e['score'] if 'score' in e else e['approve_rate']   # noqa: E731 - v2 score / v1 approve rate
    shift = rate(entry) - rate(overall)
    return round(1 + max(-MAX_SHIFT, min(MAX_SHIFT, shift)), 4)


def angle_multiplier(priors, account, angle):
    return multiplier(priors, account, 'angle', angle)


def motif_multiplier(priors, account, mtype):
    return multiplier(priors, account, 'motif', f'hot:{mtype}')


# ------------------------------------------------------------------ v2: publish-aware outcomes, stats, priors

def is_published(d):
    """scripts/ops_admin/api/decisions.js isPublished: the `published` flag on newer blobs; on blobs written before
    the flag existed (or pulled by an older apply_admin_decisions.clean that dropped it) action 'published' alone."""
    return bool(d) and (d.get('published') is True or (d.get('published') is not False and d.get('action') == 'published'))


def pipeline_status(row):
    """The ops page's status (scripts/build_ops_dashboard.py status_of): what ops saw before any decision."""
    if row.get('superseded'):
        return 'superseded'
    if row.get('held') or (row.get('arbitration') or {}).get('status') == 'HOLD':
        return 'HOLD'
    return row.get('draft_status') or row.get('status') or 'unknown'


def post_kind_of(row):
    return row.get('post_type') or row.get('post_kind') or 'unknown'


def format_of(row):
    f = row.get('post_format')
    return (f.get('type') if isinstance(f, dict) else f) or 'unknown'


def media_of(row):
    """Image style the draft carried: media v2 plan style (tv_widget, lw_render, ...), else 'chart:<type>' for older
    charts, 'quote' for a quote post without an image, 'none' otherwise."""
    plan = row.get('media_plan') if isinstance(row.get('media_plan'), dict) else {}
    media = row.get('media') if isinstance(row.get('media'), list) else []
    if media or plan.get('status') == 'made':
        if plan.get('style'):
            return str(plan['style'])
        first = media[0] if media and isinstance(media[0], dict) else {}
        return f"chart:{first.get('chart_type') or plan.get('wanted') or 'other'}"
    return 'quote' if row.get('post_mode') == 'quote' else 'none'


def keys_of(row):
    return {'angle': angle_of(row) or 'none', 'motif': motif_type(row), 'post_kind': post_kind_of(row),
            'format': format_of(row), 'media': media_of(row)}


def _body(row):
    return (row.get('body') or row.get('text') or '').strip()


def edited_text(row, d):
    """The text a human changed the draft to (admin decision text, else the compose-inbox reviewed_text); None if
    unchanged."""
    body = _body(row)
    for t in ((d or {}).get('text'), row.get('reviewed_text')):
        if isinstance(t, str) and t.strip() and t.strip() != body:
            return t.strip()
    return None


def outcome(row, d, account_posted=False, closed=False):
    """One draft's outcome (module doc). The /admin decision (d) wins over the compose-inbox review; the 已发 flag wins
    over the verdict under it."""
    d = d or {}
    act = d.get('action')
    edited = edited_text(row, d) is not None
    if is_published(d):
        return 'published_edited' if edited else 'published_asis'
    if act in ('hold', 'rewrite'):
        return 'held'
    rs = row.get('review_status') or 'pending'
    if act == 'approve' or (act in (None, 'clear', 'edit') and rs in ('approved', 'edited')):
        return 'approved'
    if rs == 'rejected' and act in (None, 'clear', 'edit'):
        return 'rejected'
    if act == 'edit':
        return 'edit_only'
    if closed and account_posted and pipeline_status(row) == 'draft_ready':
        return 'unpicked'
    return 'none'


def hold_reason_key(text, n=24):
    """A short, countable category of a hold reason, never a quote of the draft: 'hard: a,b' / 'model_error: a' keep
    their QA codes; free text is cut at the first colon / bracket / quote mark ('喊单：「…」' -> '喊单')."""
    t = ' '.join(str(text or '').split())
    if not t:
        return ''
    head, sep, rest = t.partition(':')
    if sep and re.fullmatch(r'[a-z_]+', head.strip()) and re.fullmatch(r'[a-z_, ]+', rest.strip()):
        return f'{head.strip()}: {rest.strip()}'[:60]
    for sep in ('：', ':', '「', '“', '"', '（', '(', '；', '。', '，'):
        t = t.split(sep)[0]
    return t.strip()[:n]


def beijing_today(now=None):
    from datetime import timedelta
    return ((now or datetime.now(timezone.utc)) + timedelta(hours=BJT_OFFSET_H)).date().isoformat()


def collect_days(decisions_root=None, inbox_root=None):
    """[(day, [inbox rows], {draft id: decision})] for each inbox day that has a decisions file or a compose-inbox
    review."""
    droot, iroot = Path(decisions_root or decisions_dir()), Path(inbox_root or inbox_dir())
    out = []
    days = sorted({f.stem for f in droot.glob('????-??-??.json')} |
                  {p.name for p in iroot.glob('????-??-??') if p.is_dir()}) if iroot.is_dir() or droot.is_dir() else []
    for day in days:
        data = _read(droot / f'{day}.json') or {}
        dec = {k: v for k, v in (data.get('decisions') or {}).items() if isinstance(v, dict)}
        rows = []
        for p in sorted((iroot / day).glob('*.json')):
            r = _read(p)
            if isinstance(r, dict) and r.get('id'):
                rows.append(r)
        if rows and (dec or any((r.get('review_status') or 'pending') != 'pending' for r in rows)):
            out.append((day, rows, dec))
    return out


def classify(days, now=None):
    """[(day, row, decision, outcome)] for every draft ops could see on a reviewed day (superseded drafts without a
    decision are skipped: they were never offered)."""
    today = beijing_today(now)
    out = []
    for day, rows, dec in days:
        posted = {r.get('account_id') for r in rows if is_published(dec.get(r['id']))}
        closed = day < today
        for r in rows:
            d = dec.get(r['id'])
            if r.get('superseded') and not d:
                continue
            out.append((day, r, d, outcome(r, d, r.get('account_id') in posted, closed)))
    return out


def _counter():
    return {o: 0 for o in OUTCOMES} | {'drafts': 0, 'ready': 0, 'score_sum': 0.0, 'scored': 0}


def _add(c, row, oc):
    c['drafts'] += 1
    c['ready'] += pipeline_status(row) == 'draft_ready' or oc not in ('none', 'edit_only')
    c[oc] += 1
    if oc in SCORE:
        c['score_sum'] += SCORE[oc]
        c['scored'] += 1


def _rates(c):
    pub = c['published_asis'] + c['published_edited']
    verdicts = pub + c['approved'] + c['held'] + c['rejected']
    r = lambda a, b: round(a / b, 4) if b else None   # noqa: E731
    out = {k: c[k] for k in ('drafts', 'ready') + OUTCOMES if c[k] or k in ('drafts', 'ready')}
    out.update(published=pub, publish_rate=r(pub, c['ready']), edit_rate=r(c['published_edited'], pub),
               hold_rate=r(c['held'] + c['rejected'], verdicts), n_verdicts=verdicts, n=c['scored'],
               score=round((c['score_sum'] + 1) / (c['scored'] + 2), 4))
    return out


def build_v2(classified, now=None):
    """{'priors': {acct: {...}}, 'stats': {...}, 'edits': [...]} from classify() output."""
    acc, glob_, hold_review, hold_pipe, edits, days = {}, {}, {}, {}, [], {}
    for day, row, d, oc in classified:
        a = row.get('account_id') or 'unknown'
        ks = keys_of(row)
        dd = days.setdefault(day, _counter())
        _add(dd, row, oc)
        e = acc.setdefault(a, {'overall': _counter(), **{k: {} for k in DIMS}})
        _add(e['overall'], row, oc)
        for dim, key in ks.items():
            _add(e[dim].setdefault(key, _counter()), row, oc)
            _add(glob_.setdefault(dim, {}).setdefault(key, _counter()), row, oc)
        if oc == 'held':
            label = '要求重写' if (d or {}).get('action') == 'rewrite' else 'HOLD'
            k = f"{label}：{hold_reason_key((d or {}).get('note')) or '（无备注）'}"
            hold_review[k] = hold_review.get(k, 0) + 1
        elif oc == 'none' and pipeline_status(row) == 'HOLD':
            k = hold_reason_key(row.get('hold_reason') or (row.get('arbitration') or {}).get('status')) or '（未注明）'
            hold_pipe[k] = hold_pipe.get(k, 0) + 1
        after = edited_text(row, d)
        if after:
            body = _body(row)
            edits.append({'day': day, 'account_id': a, 'draft_id': row.get('id'), 'action': (d or {}).get('action'),
                          'outcome': oc, **ks, 'motif_type': ks['motif'], 'before': body, 'after': after,
                          'diff': '\n'.join(difflib.unified_diff(body.splitlines(), after.splitlines(), 'draft',
                                                                 'edited', lineterm='')),
                          'note': (d or {}).get('note') or '', 'at': (d or {}).get('at') or ''})
    priors = {}
    for a, e in sorted(acc.items()):
        p = {'overall': _rates(e['overall'])}
        for dim in DIMS:
            p[dim] = {k: _rates(v) for k, v in sorted(e[dim].items())}
        priors[a] = p
    top = lambda m: sorted(m.items(), key=lambda kv: (-kv[1], kv[0]))[:15]   # noqa: E731
    stats = {'days': {k: _rates(v) for k, v in sorted(days.items())},
             'totals': _rates(_merge([c for c in days.values()])),
             'accounts': {a: p['overall'] for a, p in priors.items()},
             'by': {dim: {k: _rates(v) for k, v in sorted(glob_.get(dim, {}).items())} for dim in DIMS},
             'hold_reasons': {'review': top(hold_review), 'pipeline': top(hold_pipe)}}
    return {'priors': priors, 'stats': stats, 'edits': edits}


def _merge(cs):
    out = _counter()
    for c in cs:
        for k in out:
            out[k] += c[k]
    return out


def _multipliers(priors):
    """{acct: {dim: {key: multiplier}}} for the keys that would move selection now (for the stats / admin page)."""
    out = {}
    for a, p in priors.items():
        for dim in DIMS:
            for k in p.get(dim) or {}:
                m = multiplier(priors, a, dim, k)
                if m != 1.0:
                    out.setdefault(a, {}).setdefault(dim, {})[k] = m
    return out


def write_v2(result, store=None, now=None):
    store = Path(store or store_dir())
    store.mkdir(parents=True, exist_ok=True)
    built = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    rule = (f'score per draft {SCORE}; Beta(1,1)-smoothed mean; a key moves selection only when the account has '
            f'>= {MIN_ACCOUNT_N} scored drafts and the key >= {MIN_N}, by at most +-{MAX_SHIFT}; soft prior only')
    priors = {'version': 'feedback-v2', 'built_at': built, 'rule': rule,
              'min': {'account': MIN_ACCOUNT_N, 'key': MIN_N, 'max_shift': MAX_SHIFT}, 'accounts': result['priors']}
    (store / 'priors.json').write_text(json.dumps(priors, ensure_ascii=False, indent=2) + '\n')
    stats = {'version': 'feedback-stats-v1', 'built_at': built, 'rule': rule, 'score': SCORE,
             **result['stats'], 'active_multipliers': _multipliers(result['priors']),
             'edit_examples': len(result['edits'])}   # counts only: edit texts stay in style_examples/ (local)
    (store / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n')
    ex = store / 'style_examples'
    ex.mkdir(exist_ok=True)
    by_acct = {}
    for e in result['edits']:
        by_acct.setdefault(e['account_id'], []).append(e)
    for a, rows in by_acct.items():   # rewritten whole each night: the newest decision per draft wins
        (ex / f'{a}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    return priors, stats


def load_stats(store=None):
    return _read(Path(store or store_dir()) / 'stats.json')


def multiplier(priors, account, dim, key):
    p = (priors or {}).get(account) or {}
    return _mult((p.get(dim) or {}).get(key), p.get('overall'))
