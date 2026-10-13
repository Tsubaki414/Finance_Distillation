"""Admin write token for /api/decisions (Oct 13, Fiona: lock the review backend).

FD_ADMIN_TOKEN from the environment, else ~/.secrets/fd_admin.env (FD_ADMIN_ENV overrides the path). Never printed
or logged; callers only learn set / missing."""
import os
from pathlib import Path


def admin_token():
    t = os.environ.get('FD_ADMIN_TOKEN', '').strip()
    if t:
        return t
    p = Path(os.environ.get('FD_ADMIN_ENV', str(Path.home() / '.secrets/fd_admin.env')))
    try:
        for line in p.read_text().splitlines():
            k, _, v = line.partition('=')
            if k.strip() == 'FD_ADMIN_TOKEN':
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ''


def auth_headers():
    t = admin_token()
    return {'Authorization': f'Bearer {t}'} if t else {}
