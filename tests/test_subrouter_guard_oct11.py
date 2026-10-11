"""Oct 11: daily_compose refuses to start without SUBROUTER_API_KEY unless FD_ALLOW_NO_SUBROUTER=1."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import daily_compose as dc

ROOT = Path(__file__).resolve().parents[1]


def test_guard_logic():
    a = SimpleNamespace(select_only=False)
    assert 'SUBROUTER_API_KEY' in dc.subrouter_guard(a, env={})
    assert dc.subrouter_guard(a, env={'SUBROUTER_API_KEY': ' '}) is not None
    assert dc.subrouter_guard(a, env={'SUBROUTER_API_KEY': 'k'}) is None
    assert dc.subrouter_guard(a, env={'FD_ALLOW_NO_SUBROUTER': '1'}) is None
    assert dc.subrouter_guard(SimpleNamespace(select_only=True), env={}) is None


def test_main_exits_2_with_clear_error(tmp_path):
    env = {'PATH': '/usr/bin:/bin', 'FD_DAILY_COMPOSE': '1', 'HOME': str(tmp_path)}
    r = subprocess.run([sys.executable, 'scripts/daily_compose.py', '--day', '2026-10-12', '--accounts', 'zh_macro'],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and 'Refusing to start' in r.stderr
