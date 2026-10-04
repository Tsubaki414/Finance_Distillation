import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import backup_live

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / 'live/donors/posts'


@pytest.mark.skipif(os.environ.get('FD_SKIP_DATA_GUARD') == '1', reason='data-less checkout')
def test_donor_posts_is_a_real_nonempty_directory():
    assert not POSTS.is_symlink(), 'live/donors/posts must never be a symlink'
    assert POSTS.is_dir() and any(POSTS.glob('*.jsonl')), 'live/donors/posts is missing or empty'


def test_live_data_dirs_are_not_tracked_by_git():
    tracked = subprocess.run(['git', 'ls-files', 'live/donors/posts', 'live/donors/tags', 'live/store'],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert tracked == []
    for path in ('live/donors/posts', 'live/donors/posts/x.jsonl', 'live/donors/tags/x.json', 'live/store/x'):
        r = subprocess.run(['git', 'check-ignore', '-q', '--no-index', path], cwd=ROOT)
        assert r.returncode == 0, path + ' must be gitignored'


def test_backup_writes_archive_and_keeps_last_n(tmp_path):
    live = tmp_path / 'live'; (live / 'donors/posts').mkdir(parents=True)
    (live / 'donors/posts/a.jsonl').write_text('{"id": 1}\n')
    out = tmp_path / 'backups'
    for day in ('20260901', '20260902', '20260903', '20260904'):
        backup_live.backup(live, out, stamp=day, keep=2)
    names = sorted(p.name for p in out.iterdir())
    assert len(names) == 2 and names[-1].startswith('fd_live_20260904')
    path = out / names[-1]
    assert backup_live.list_members(path) and any(m.endswith('a.jsonl') for m in backup_live.list_members(path))


def test_backup_refuses_symlinked_posts(tmp_path):
    live = tmp_path / 'live'; (live / 'donors').mkdir(parents=True)
    (live / 'donors/posts').symlink_to(tmp_path)
    with pytest.raises(SystemExit):
        backup_live.backup(live, tmp_path / 'b', stamp='20260901')
