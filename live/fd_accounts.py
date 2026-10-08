"""The account roster for daily drafting (Oct 8: 36 accounts).

Three files, one list:
  live/fd20_accounts.json      the 20 main accounts (FD_accounts_final_v2.xlsx rows 1-20), always on
  live/fd_accounts_extra.json  the 6 spare accounts put into use (status 'spare_active'), FD_ACCOUNTS_EXTRA (default 1)
  live/fd_accounts_new.json    the 10 new accounts (status 'new'), FD_ACCOUNTS_NEW (default 1)

Every consumer that used to read fd20_accounts.json['accounts'] reads `rows()` instead; a test or a caller that
passes its own file still gets exactly that file. FD_ACCOUNTS_EXTRA=0 / FD_ACCOUNTS_NEW=0 drop a group from every
consumer at once (selection, compose, X intake, persona factory, dashboard), which is the rollback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

LIVE = Path(__file__).resolve().parent
MAIN = LIVE / 'fd20_accounts.json'
EXTRA = LIVE / 'fd_accounts_extra.json'
NEW = LIVE / 'fd_accounts_new.json'
# group -> (file, gate env var, status written on rows without one)
GROUPS = (('main', MAIN, None, 'main'),
          ('spare', EXTRA, 'FD_ACCOUNTS_EXTRA', 'spare_active'),
          ('new', NEW, 'FD_ACCOUNTS_NEW', 'new'))


def _read(path):
    try:
        return json.loads(Path(path).read_text()).get('accounts') or []
    except (OSError, ValueError):
        return []


def enabled_groups(env=None):
    env = env if env is not None else os.environ
    return [g for g, _, var, _ in GROUPS if var is None or str(env.get(var, '1')) != '0']


def load(env=None, groups=None):
    """Rows of the enabled groups in roster order (main 1-20, spares 21-26, new 27-36). Each row carries 'group' and
    'status'; a duplicate id keeps its first row."""
    groups = set(groups if groups is not None else enabled_groups(env))
    out, seen = [], set()
    for group, path, _, status in GROUPS:
        if group not in groups:
            continue
        for row in _read(path):
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            out.append({**row, 'group': group, 'status': row.get('status') or status})
    return out


def rows(path=None, env=None):
    """Accounts for a consumer. path None or the default fd20 file -> the gated 36-account roster; any other path
    (tests, --accounts FILE) -> exactly that file's rows."""
    if path is None or Path(path).resolve() == MAIN.resolve():
        return load(env)
    return _read(path)


def by_id(path=None, env=None):
    return {a['id']: a for a in rows(path, env)}
