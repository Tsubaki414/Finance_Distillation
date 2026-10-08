"""Attach post_mode (live/post_mode.py) and a chart (live/charts.py) to inbox rows; never touches the text.

`annotate(row, account, out_dir)` mutates and returns one row: post_mode + target URL + why, and when the
account / draft is chart-eligible and a provider returned data, media=[{kind: chart, path, alt, data_sources, ...}]
with the PNG under <out_dir>/media/<day>/<id>.png. media_plan records why a draft has no chart.
`apply_day(day, ...)` does that for a day's ready inbox rows in place (scripts/apply_media.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from live import charts, compose_inbox, post_mode

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS = ROOT / 'live/fd20_accounts.json'
MEDIA_OUT = Path(os.environ.get('FD_MEDIA_OUT', '/workspace/x/dashboard/ops'))


def load_accounts(path=None):
    from live import fd_accounts
    return {a['id']: a for a in fd_accounts.rows(path or ACCOUNTS)}


def is_ready(row):
    return (row.get('draft_status') == 'draft_ready' and not row.get('held') and not row.get('superseded')
            and bool((row.get('text') or '').strip()))


def annotate(row, account, out_dir=None, replies_given=0, own_handles=(), charts_on=True):
    if row.get('post_kind') == 'archive_lookback':   # 回看 keeps its own fixed then-vs-now chart (live/archive_lookback.py)
        return row
    out_dir = Path(out_dir or MEDIA_OUT)
    row.update({k: None for k in ('quote_target_url', 'reply_to_url')})
    row.update(post_mode.decide(row, replies_given=replies_given, own_handles=own_handles))
    for k in ('quote_target_url', 'reply_to_url'):
        if row.get(k) is None:
            row.pop(k, None)
    if not charts_on or not account:
        return row
    try:
        media, plan = charts.attach(row, account, out_dir)
    except Exception as exc:   # noqa: BLE001 - a render failure means no chart, never a broken draft
        media, plan = None, {'failed': f'{type(exc).__name__}: {str(exc)[:160]}'}
    if media:
        row['media'] = [media]
        row['media_plan'] = {'wanted': plan['kind'], 'status': 'made', 'why': plan['profile']['why'],
                             **({'style': media['style']} if media.get('style') else {})}
    else:
        row.pop('media', None)
        if plan and plan.get('want') is False:   # media_real: no image by donor rate / no subject / quote post
            row['media_plan'] = {'wanted': None, 'status': 'no_image', 'why': plan.get('why'),
                                 'p_image': plan.get('p_image')}
        else:
            row['media_plan'] = ({'wanted': plan.get('kind'), 'status': 'no_data', 'detail': plan.get('failed')}
                                 if plan else {'wanted': None, 'status': 'not_eligible'})
    if plan and plan.get('manual_sources'):   # media v3: pages donors would screenshot that we may not load (terms)
        row['media_plan']['manual_sources'] = plan['manual_sources']
    return row


def apply_day(day, out_dir=None, base=None, accounts=None, only_ready=True, write=True):
    """Annotate the day's inbox rows in place (ready rows only by default). Returns a summary dict."""
    accounts = accounts or load_accounts()
    own = [a.get('handle') for a in accounts.values()]
    base = Path(base or compose_inbox.root())
    replies = {}
    summary = {'day': day, 'rows': 0, 'charts': 0, 'quote': 0, 'reply': 0, 'no_data': 0, 'samples': []}
    for path in sorted((base / day).glob('*.json')):
        row = json.loads(path.read_text())
        if only_ready and not is_ready(row):
            continue
        acct = row.get('account_id')
        text_before = row.get('text')
        annotate(row, accounts.get(acct), out_dir, replies_given=replies.get(acct, 0), own_handles=own)
        assert row.get('text') == text_before
        if row['post_mode'] == 'reply':
            replies[acct] = replies.get(acct, 0) + 1
        summary['rows'] += 1
        summary[row['post_mode']] = summary.get(row['post_mode'], 0) + 1
        if row.get('media'):
            summary['charts'] += 1
            summary['samples'].append(row['media'][0]['path'])
        elif (row.get('media_plan') or {}).get('status') == 'no_data':
            summary['no_data'] += 1
        if write:
            tmp = path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n')
            tmp.replace(path)
    return summary
