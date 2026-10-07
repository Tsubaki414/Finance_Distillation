"""Re-fetch and re-render the charts of today's and tomorrow's ready drafts, rebuild the pages, redeploy on change.

Candlestick charts are refetched every run; data charts (FRED / DefiLlama) at most every --data-every-h hours (6).
A chart is replaced only when what it shows changed (charts.attach's data_sha: plotted rows + levels, not the fetch
stamp); then the row's media gets the new sha256 / fetched_at / levels and refreshed_at, which the dashboard card
shows as 「图更新于 北京时间 HH:MM」. Every checked chart gets checked_at. Text is never touched.

Both pages (/ and /admin) are rebuilt when any chart was checked; `vercel deploy --prod --yes` runs only when at
least one image changed (or an earlier change was never deployed: the deploy_pending marker in the state dir).
Days are inbox days (Beijing calendar date, the drafting day since Oct 7): today and tomorrow in 北京时间.

  python3 scripts/refresh_charts.py [--day 2026-10-07 ...] [--no-build] [--no-deploy] [--force-data]
Scheduled hourly by scripts/cron/refresh_charts.sh (lockfile, log, 08:00-23:59 Beijing time).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live import charts, compose_inbox, draft_media  # noqa: E402

BJT = ZoneInfo('Asia/Shanghai')
DATA_EVERY_H = 6
# Written when images changed but were not deployed (--no-deploy, deploy failure); the next run deploys then.
PENDING = Path(os.environ.get('FD_CHART_STATE', '/workspace/x/chart_refresh')) / 'deploy_pending'


def default_days(now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(BJT).date()
    return [today.isoformat(), (today + timedelta(days=1)).isoformat()]


def _age_h(stamp, now):
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
    except (TypeError, ValueError):
        return float('inf')


def refresh_row(row, account, out_dir, now, data_every_h=DATA_EVERY_H, force_data=False):
    """Refresh the row's chart in place. Returns 'changed' | 'same' | 'skipped' | 'failed' | None (no chart)."""
    media = next((m for m in row.get('media') or [] if m.get('kind') == 'chart' and m.get('path')), None)
    if not media or not account:
        return None
    if media.get('chart_type') == 'data' and not force_data:
        last = media.get('checked_at') or media.get('refreshed_at') or \
            ((media.get('data_sources') or [{}])[0].get('fetched_at'))
        if _age_h(last, now) < data_every_h:
            return 'skipped'
    stamp = now.isoformat(timespec='seconds')
    with tempfile.TemporaryDirectory(prefix='fd_chart_') as tmp:
        try:
            new, _plan = charts.attach(row, account, tmp, ttl=0)
        except Exception as exc:   # noqa: BLE001 - a failed refresh keeps the old chart
            new, _plan = None, None
            media['refresh_error'] = f'{type(exc).__name__}: {str(exc)[:160]}'
        if not new or new['path'] != media['path']:
            media.setdefault('refresh_error', 'no data from any provider' if not new else 'path moved')
            media['checked_at'] = stamp
            return 'failed'
        media.pop('refresh_error', None)
        if new.get('data_sha') and new['data_sha'] == media.get('data_sha'):
            media['checked_at'] = stamp
            return 'same'
        src = Path(tmp) / new['path']
        dst = Path(out_dir) / new['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src.with_suffix('.json'), dst.with_suffix('.json'))
        shutil.copyfile(src, dst.with_suffix('.png.tmp'))
        dst.with_suffix('.png.tmp').replace(dst)
    media.update(new, checked_at=stamp)
    return 'changed'


def refresh_days(days, out_dir=None, base=None, accounts=None, now=None, data_every_h=DATA_EVERY_H,
                 force_data=False):
    out_dir = Path(out_dir or draft_media.MEDIA_OUT)
    base = Path(base or compose_inbox.root())
    accounts = accounts or draft_media.load_accounts()
    now = now or datetime.now(timezone.utc)
    summary = {'at': now.isoformat(timespec='seconds'), 'days': days, 'changed': 0, 'same': 0, 'skipped': 0,
               'failed': 0, 'charts': [], 'levels_drawn': 0}
    for day in days:
        for path in sorted((base / day).glob('*.json')) if (base / day).is_dir() else []:
            row = json.loads(path.read_text())
            if not draft_media.is_ready(row):
                continue
            text_before = row.get('text')
            res = refresh_row(row, accounts.get(row.get('account_id')), out_dir, now, data_every_h, force_data)
            if res is None:
                continue
            assert row.get('text') == text_before
            summary[res] += 1
            m = row['media'][0]
            summary['levels_drawn'] += len(m.get('levels') or []) if m.get('chart_type') == 'candle' else 0
            summary['charts'].append({'id': row['id'], 'type': m.get('chart_type'), 'result': res,
                                      'levels': m.get('levels') or [], 'refreshed_at': m.get('refreshed_at'),
                                      **({'error': m['refresh_error']} if m.get('refresh_error') else {})})
            if res != 'skipped':
                tmp = path.with_suffix('.json.tmp')
                tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str) + '\n')
                tmp.replace(path)
    return summary


def rebuild_pages():
    r = subprocess.run(['python3', str(ROOT / 'scripts/build_ops_dashboard.py')], cwd=ROOT, capture_output=True,
                       text=True, timeout=600)
    print((r.stdout + r.stderr).strip()[-800:])
    return r.returncode == 0


def deploy(out_dir):
    vercel = shutil.which('vercel') or str(Path.home() / '.local/bin/vercel')
    if not (Path(vercel).exists() and (Path(out_dir) / '.vercel').is_dir()):
        print(f'deploy skipped: vercel CLI or {out_dir}/.vercel missing')
        return False
    r = subprocess.run([vercel, 'deploy', '--prod', '--yes'], cwd=out_dir, capture_output=True, text=True, timeout=300)
    print((r.stdout + r.stderr).strip()[-600:])
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--day', action='append', help='inbox day (repeatable); default Beijing today + tomorrow')
    ap.add_argument('--out', type=Path, default=draft_media.MEDIA_OUT)
    ap.add_argument('--data-every-h', type=float, default=DATA_EVERY_H)
    ap.add_argument('--force-data', action='store_true', help='refresh data charts regardless of age')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--no-deploy', action='store_true')
    args = ap.parse_args()
    summary = refresh_days(args.day or default_days(), args.out, data_every_h=args.data_every_h,
                           force_data=args.force_data)
    checked = summary['changed'] + summary['same'] + summary['failed']
    summary['built'] = bool(checked) and not args.no_build and rebuild_pages()
    if summary['changed']:
        PENDING.parent.mkdir(parents=True, exist_ok=True)
        PENDING.write_text(summary['at'] + '\n')
    summary['deployed'] = PENDING.exists() and not args.no_deploy and (summary['built'] or rebuild_pages()) \
        and deploy(args.out)
    if summary['deployed']:
        PENDING.unlink(missing_ok=True)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
