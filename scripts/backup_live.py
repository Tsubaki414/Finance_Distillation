"""Daily snapshot of live/ (store, donors, personas) to /workspace/backups/fd_live_YYYYMMDD.tar.zst.

Keeps the last N snapshots (default 7). Uses zstandard when installed, else gzip.
Refuses to run when live/donors/posts is a symlink (a sign the data was replaced).

  python scripts/backup_live.py [--live live] [--out /workspace/backups] [--keep 7]
"""
import argparse
import datetime as dt
import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = ('__pycache__', '.DS_Store')


def _filter(info):
    return None if any(part in EXCLUDE or part.startswith('._') for part in Path(info.name).parts) else info


def backup(live, out, *, stamp=None, keep=7):
    live, out = Path(live), Path(out)
    posts = live / 'donors/posts'
    if posts.is_symlink():
        sys.exit(f'refusing to back up: {posts} is a symlink')
    out.mkdir(parents=True, exist_ok=True)
    stamp = stamp or dt.date.today().strftime('%Y%m%d')
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard:
        path = out / f'fd_live_{stamp}.tar.zst'
        with open(path, 'wb') as fh, zstandard.ZstdCompressor(level=10).stream_writer(fh) as zw:
            with tarfile.open(fileobj=zw, mode='w|') as tar:
                tar.add(live, arcname='live', filter=_filter)
    else:
        path = out / f'fd_live_{stamp}.tar.gz'
        with tarfile.open(path, 'w:gz') as tar:
            tar.add(live, arcname='live', filter=_filter)
    snaps = sorted(p for p in out.glob('fd_live_*.tar.*'))
    for old in snaps[:-keep] if keep > 0 else []:
        old.unlink()
    return path


def list_members(path):
    path = Path(path)
    if path.suffix == '.zst':
        import zstandard
        with open(path, 'rb') as fh:
            data = zstandard.ZstdDecompressor().stream_reader(fh).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tar:
            return tar.getnames()
    with tarfile.open(path) as tar:
        return tar.getnames()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--live', type=Path, default=ROOT / 'live')
    ap.add_argument('--out', type=Path, default=Path('/workspace/backups'))
    ap.add_argument('--keep', type=int, default=7)
    a = ap.parse_args()
    path = backup(a.live, a.out, keep=a.keep)
    print(path, path.stat().st_size)


if __name__ == '__main__':
    main()
