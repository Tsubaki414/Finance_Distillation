"""Prepare, install and inspect this repo's two macOS user LaunchAgents.

Preparation only writes inside the repository. Installation persists across
terminal exits and starts again at user login. It neither publishes posts nor
changes the monitor's model/budget/source settings. A sleeping or logged-out Mac
does not run a user LaunchAgent; the persisted cursor is resumed on wake/login.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
LABEL_PREFIX = 'com.mangoworks.finance-distillation'
SERVICES = ('monitor', 'dashboard')


def label(service):
    if service not in SERVICES:
        raise ValueError('Unknown service')
    return f'{LABEL_PREFIX}.{service}'


def service_spec(service, root=ROOT, port=8684, interval=1800):
    root = Path(root).resolve()
    python = root / '.venv/bin/python'
    if service == 'monitor':
        arguments = [str(python), '-B', str(root / 'scripts/run_monitor.py'),
                     '--continuous', '--interval-seconds', str(interval)]
    elif service == 'dashboard':
        arguments = [str(python), '-B', '-m', 'uvicorn',
                     'backend.content_dashboard:app', '--host', '127.0.0.1',
                     '--port', str(port)]
    else:
        raise ValueError('Unknown service')
    return {'Label': label(service), 'ProgramArguments': arguments,
            'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True,
            'ThrottleInterval': 30, 'ProcessType': 'Background',
            'EnvironmentVariables': {'PYTHONUNBUFFERED': '1',
                                     'PYTHONDONTWRITEBYTECODE': '1'},
            'StandardOutPath': str(root / f'runs/account_monitor/{service}.stdout.log'),
            'StandardErrorPath': str(root / f'runs/account_monitor/{service}.stderr.log')}


def prepare(root=ROOT, port=8684, interval=1800):
    root = Path(root).resolve()
    if not (root / '.venv/bin/python').exists():
        raise ValueError('Repository Python is missing')
    if not (root / 'scripts/run_monitor.py').is_file():
        raise ValueError('Monitor entrypoint is missing')
    if interval < 60 or not 1024 <= port <= 65535:
        raise ValueError('Interval must be at least 60 seconds; choose a non-privileged port')
    directory = root / 'runs/account_monitor/launchd'
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for service in SERVICES:
        path = directory / f'{label(service)}.plist'
        path.write_bytes(plistlib.dumps(service_spec(service, root, port, interval)))
        files[service] = str(path)
    return {'prepared': files, 'installed': False,
            'dashboard_url': f'http://127.0.0.1:{port}/account-intelligence',
            'interval_seconds': interval, 'publishing_enabled': False}


def launchctl(*args, required=False):
    result = subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True)
    if required and result.returncode:
        raise RuntimeError(f'launchctl {args[0]} failed: {result.stderr.strip()}')
    return result


def service_status(service):
    result = launchctl('print', f'gui/{os.getuid()}/{label(service)}')
    if result.returncode:
        return {'loaded': False, 'running': False}
    # Do not expose a launchd environment dump: it can contain user credentials.
    values = {}
    for key in ('state', 'pid', 'runs', 'last exit code'):
        match = re.search(r'^\s*' + re.escape(key) + r' = (.+)$', result.stdout, re.M)
        if match:
            values[key.replace(' ', '_')] = match.group(1).strip()
    return {'loaded': True, 'running': values.get('state') == 'running', **values}


def wait_for_unload(service, timeout=15.0):
    """bootout can return while launchd still owns the previous job label."""
    deadline = time.monotonic() + timeout
    while service_status(service)['loaded']:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f'launchctl bootout did not unload {label(service)} within {timeout:g}s')
        time.sleep(min(0.25, remaining))


def bootstrap_service(service, domain, destination):
    """Retry only the short launchd removal race, never another job or provider."""
    for attempt in range(3):
        result = launchctl('bootstrap', domain, str(destination))
        if result.returncode == 0:
            return
        # EIO (5) can persist briefly after print first reports the old job gone.
        # Refuse to bootstrap over any now-loaded job, and do not retry other errors.
        if result.returncode != 5 or service_status(service)['loaded'] or attempt == 2:
            raise RuntimeError(f'launchctl bootstrap failed: {result.stderr.strip()}')
        time.sleep(0.5 * (attempt + 1))


def listener_exists(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def read_local_json(port, path):
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}{path}', timeout=5) as response:
            return json.load(response)
    except (OSError, URLError, ValueError):
        return None


def status(root=ROOT, port=8684):
    if sys.platform != 'darwin':
        raise ValueError('This service manager requires macOS')
    services = {name: service_status(name) for name in SERVICES}
    return {'services': services,
            'dashboard_url': f'http://127.0.0.1:{port}/account-intelligence',
            'dashboard_health': read_local_json(port, '/health'),
            'monitor': read_local_json(port, '/api/account-intelligence/monitor-status'),
            'publishing_enabled': False,
            'runtime_limit': 'Requires this Mac to be awake and the user logged in.'}


def install(root=ROOT, port=8684, interval=1800, agents_dir=None):
    if sys.platform != 'darwin':
        raise ValueError('This service manager requires macOS')
    root = Path(root).resolve()
    target = Path(agents_dir) if agents_dir else Path.home() / 'Library/LaunchAgents'
    domain = f'gui/{os.getuid()}'
    launchctl('print', domain, required=True)
    # Refuse a busy port owned outside these jobs. Never kill an unrelated server.
    if listener_exists(port) and not service_status('dashboard')['loaded']:
        raise ValueError(f'Port {port} is occupied outside this launchd job. '
                         'Identify and stop only the existing project dashboard before installation.')
    prepared = prepare(root, port, interval)
    # Preflight every destination before modifying any installed service.
    for service in SERVICES:
        destination = target / f'{label(service)}.plist'
        if destination.exists():
            existing = plistlib.loads(destination.read_bytes())
            if (existing.get('Label') != label(service)
                    or existing.get('WorkingDirectory') != str(root)):
                raise ValueError(f'Refusing to replace a service belonging to another workspace: {destination}')
    target.mkdir(parents=True, exist_ok=True)
    installed = {}
    # Bring up the review server before work starts arriving.
    for service in ('dashboard', 'monitor'):
        destination = target / f'{label(service)}.plist'
        if service_status(service)['loaded']:
            launchctl('bootout', f'{domain}/{label(service)}', required=True)
            wait_for_unload(service)
        content = Path(prepared['prepared'][service]).read_bytes()
        staging = destination.with_suffix('.plist.tmp')
        staging.write_bytes(content)
        staging.chmod(0o600)
        staging.replace(destination)
        launchctl('enable', f'{domain}/{label(service)}', required=True)
        bootstrap_service(service, domain, destination)
        installed[service] = str(destination)
    return {**prepared, 'installed': installed, 'services': {s: service_status(s) for s in SERVICES}}


def uninstall(root=ROOT, agents_dir=None):
    if sys.platform != 'darwin':
        raise ValueError('This service manager requires macOS')
    root = Path(root).resolve()
    target = Path(agents_dir) if agents_dir else Path.home() / 'Library/LaunchAgents'
    for service in SERVICES:
        path = target / f'{label(service)}.plist'
        if path.exists():
            spec = plistlib.loads(path.read_bytes())
            if spec.get('WorkingDirectory') != str(root) or spec.get('Label') != label(service):
                raise ValueError(f'Refusing to remove another workspace service: {path}')
    for service in SERVICES:
        path = target / f'{label(service)}.plist'
        if path.exists():
            if service_status(service)['loaded']:
                launchctl('bootout', f'gui/{os.getuid()}/{label(service)}', required=True)
            path.unlink()
    return {'installed': False, 'records_preserved': True, 'publishing_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'install', 'status', 'uninstall'))
    parser.add_argument('--port', type=int, default=8684)
    parser.add_argument('--interval-seconds', type=int, default=1800)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            result = prepare(port=args.port, interval=args.interval_seconds)
        elif args.action == 'install':
            result = install(port=args.port, interval=args.interval_seconds)
        elif args.action == 'status':
            result = status(port=args.port)
        else:
            result = uninstall()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({'error': str(exc), 'action': args.action}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
