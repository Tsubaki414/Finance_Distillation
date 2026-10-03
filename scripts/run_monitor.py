#!/usr/bin/env python3
"""Daily account-source monitor; default one cycle, --continuous stays running."""
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live.account_monitor import Monitor, configuration
from live.account_intelligence import Store, DEFAULT
from live.account_intelligence import now
import json


def jev_advisory_enabled():
    """An unset flag never opts the monitoring service into paid advice."""
    from live.writer_backend import _dotenv
    value = os.environ.get('JEV_ADVISORY_ENABLED')
    if value is None:
        value = _dotenv().get('JEV_ADVISORY_ENABLED', '')
    return str(value).strip().lower() in {'1', 'true', 'yes'}


def advisory_after_cycle(monitor, result, stop):
    """Keep optional review failures outside the source/draft loop's outcome."""
    if stop.is_set() or result.get('status') not in {'completed', 'completed_with_blocks'}:
        return result
    try:
        if not jev_advisory_enabled():
            return result
        from live.jev_advisory import run_pending
        advisory = run_pending(monitor.store, limit=3)
    except Exception as exc:
        # Provider text or exception messages can contain request data/secrets.
        advisory = {'status': 'failed', 'error_type': type(exc).__name__,
                    'advisory_only': True, 'production_changes': False}
    return {**result, 'jev_advisory': advisory}


@contextmanager
def process_lock(store_root):
    """One CLI process owns heartbeat, including its between-cycle wait."""
    root = Path(store_root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'monitor-process.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_loop(monitor, *, continuous, interval_seconds, stop):
    heartbeat_stop=threading.Event()
    def heartbeat():
        while not heartbeat_stop.is_set():
            try:
                monitor.heartbeat(daemon=continuous)
            except Exception as exc:
                print(json.dumps({'status':'heartbeat_failed','error_type':type(exc).__name__}),
                      file=sys.stderr,flush=True)
            heartbeat_stop.wait(15)
    worker=threading.Thread(target=heartbeat,daemon=True)
    worker.start()
    exit_code=0
    try:
        while not stop.is_set():
            try:
                if monitor.config.get('enabled') is not True:
                    result={'status':'monitor_disabled','publishing_enabled':False}
                else:
                    result=monitor.run_cycle()
                    result=advisory_after_cycle(monitor,result,stop)
                print(json.dumps(result,ensure_ascii=False),flush=True)
            except Exception as exc:
                exit_code=1
                print(json.dumps({'status':'cycle_failed','error_type':type(exc).__name__}),flush=True)
            if not continuous:
                break
            stop.wait(interval_seconds)
    finally:
        # Continue heartbeats while an in-flight cycle finishes after SIGTERM.
        # Clearing another process's heartbeat would falsely mark it stopped.
        heartbeat_stop.set()
        worker.join(timeout=35)
        current=monitor.state.meta('heartbeat') or {}
        if current.get('pid')==os.getpid():
            monitor.state.meta('heartbeat',{'at':now(),'pid':0,'daemon':False})
    return exit_code


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--once',action='store_true')
    group.add_argument('--continuous',action='store_true')
    parser.add_argument('--interval-seconds',type=int,default=configuration()['interval_seconds'])
    parser.add_argument('--store',type=Path,default=DEFAULT)
    args=parser.parse_args(argv)
    if args.interval_seconds<30:
        parser.error('Interval must be at least 30 seconds')
    stop=threading.Event()
    for name in (signal.SIGTERM,signal.SIGINT):
        signal.signal(name,lambda *_:stop.set())
    with process_lock(args.store) as acquired:
        if not acquired:
            print(json.dumps({'status':'already_running','publishing_enabled':False}),flush=True)
            return 0
        monitor=Monitor(Store(args.store))
        return run_loop(monitor,continuous=args.continuous,
                        interval_seconds=args.interval_seconds,stop=stop)


if __name__=='__main__':
    raise SystemExit(main())
