"""Linux limited-SID cleanup: admission, non-reaping anchor and FD lifecycle."""
import errno
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import threading
import time

import pytest
from test_document_worker_exited_root import load_module

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux pidfd/session contract')


@pytest.mark.parametrize('missing', ['pidfd_open', 'pidfd_send_signal', 'waitid', 'WNOWAIT', 'proc', 'sigchld'])
def test_capability_failure_before_parser_launch_or_input(tmp_path, monkeypatch, missing):
    m = load_module()
    monkeypatch.setattr(m, '__file__', str(tmp_path / 'document_knowledge_graph.py'))
    marker = tmp_path / 'parser.marker'
    (tmp_path / 'document_worker.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    launched = []
    def reject_launch(*a, **k):
        launched.append(a)
        raise AssertionError('launch reached before capability failure')
    monkeypatch.setattr(m.subprocess, 'Popen', reject_launch)
    if missing in ('pidfd_open', 'waitid', 'WNOWAIT'):
        monkeypatch.delattr(os, missing)
    elif missing == 'pidfd_send_signal':
        monkeypatch.delattr(signal, missing)
    elif missing == 'proc':
        read_text = Path.read_text
        def denied(p, *a, **k):
            if str(p).startswith('/proc/'):
                raise PermissionError(errno.EACCES, 'injected proc denial')
            return read_text(p, *a, **k)
        monkeypatch.setattr(Path, 'read_text', denied)
    else:
        monkeypatch.setattr(signal, 'getsignal', lambda s: signal.SIG_IGN)
    with pytest.raises(RuntimeError, match='Linux document worker cleanup unavailable'):
        m._extract(tmp_path / 'fixture.txt', {})
    assert launched == []
    assert not marker.exists()


def test_root_remains_waitable_until_final_scan_and_fds_close(tmp_path, monkeypatch):
    m = load_module()
    monkeypatch.setattr(m, '__file__', str(tmp_path / 'document_knowledge_graph.py'))
    (tmp_path / 'document_worker.py').write_text('import sys\nsys.stdin.buffer.read()\nprint(\'{"ok":true,"document":{"status":"ok"}}\')\n')
    opened = []
    closed = []
    live_pidfds = set()
    events = []
    real_open, real_close = os.pidfd_open, os.close
    def pin(pid, *a):
        fd = real_open(pid, *a)
        opened.append(fd)
        assert fd not in live_pidfds
        live_pidfds.add(fd)
        events.append(('pin', pid))
        return fd
    def close(fd):
        # Popen also closes anonymous-pipe FDs via the shared os module. Count
        # only identities actually returned by pidfd_open, not every os.close.
        if fd in live_pidfds:
            closed.append(fd)
            live_pidfds.remove(fd)
        return real_close(fd)
    monkeypatch.setattr(os, 'pidfd_open', pin)
    monkeypatch.setattr(os, 'close', close)
    real_wait, real_poll = subprocess.Popen.wait, subprocess.Popen.poll
    def poll(p, *a, **k):
        if getattr(p, 'args', [])[-1:] == [str(tmp_path / 'document_worker.py')]:
            raise AssertionError('Popen.poll would reap the Linux root')
        return real_poll(p, *a, **k)
    monkeypatch.setattr(subprocess.Popen, 'poll', poll)
    original_scan = m._LinuxWorkerSession.cleanup
    def scan(owner, deadline):
        try:
            return original_scan(owner, deadline)
        finally:
            info = os.waitid(os.P_PID, owner.proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            assert info and info.si_pid == owner.proc.pid
            events.append(('final-unreaped', owner.proc.pid))
    monkeypatch.setattr(m._LinuxWorkerSession, 'cleanup', scan)
    def wait(p, *a, **k):
        if getattr(p, 'args', [])[-1:] == [str(tmp_path / 'document_worker.py')]:
            assert ('final-unreaped', p.pid) in events
            events.append(('reap', p.pid))
        return real_wait(p, *a, **k)
    monkeypatch.setattr(subprocess.Popen, 'wait', wait)
    assert m._extract(tmp_path / 'fixture.txt', {}) == {'status': 'ok'}
    assert len(opened) == len(closed)
    assert sorted(opened) == sorted(closed)
    (tmp_path / 'lifecycle.json').write_text(json.dumps({'events': events, 'pidfds_opened': len(opened), 'pidfds_closed': len(closed)}, indent=2), encoding='utf-8')


def test_proc_stat_parentheses_and_spaces(tmp_path):
    m = load_module()
    assert m._linux_stat_session('123 (name ) with ( spaces)) S 4 5 678 0 0') == 678


def _exercise_native_cleanup_fault(tmp_path, monkeypatch, failure, *, timeout=False):
    m = load_module()
    monkeypatch.setattr(m, '__file__', str(tmp_path / 'document_knowledge_graph.py'))
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT', '10')
    # A timeout nonreader MUST retain fd0; closing stdin tests BrokenPipe instead.
    code = ('import time\ntime.sleep(90)\n' if timeout else
            'import sys\nsys.stdin.buffer.read()\nprint(\'{"ok":true,"document":{"status":"ok"}}\')\n')
    (tmp_path / 'document_worker.py').write_text(code, encoding='utf-8')
    before_threads = set(threading.enumerate())
    before_fds = set(os.listdir('/proc/self/fd'))
    original = m._LinuxWorkerSession.cleanup
    native_error = (ChildProcessError(errno.ECHILD, 'injected lost anchor') if failure == 'ECHILD'
                    else PermissionError(errno.EACCES, 'injected proc read denial'))
    observations = {'failure': failure, 'timeout_fixture': timeout, 'fault_calls': 0}
    owners = []
    pins = []
    def fault(owner, deadline):
        owners.append(owner)
        observations['pid'] = owner.proc.pid
        pins.append(os.pidfd_open(owner.proc.pid))
        def unavailable(*a, **k):
            observations['fault_calls'] += 1
            raise native_error
        # Inject only the unavailable native observation, AFTER real admission.
        # The production cleanup implementation still signals/closes real pins.
        with monkeypatch.context() as scoped:
            if failure == 'ECHILD':
                scoped.setattr(os, 'waitid', unavailable)
            else:
                scoped.setattr(m, '_linux_process_session', unavailable)
            return original(owner, deadline)
    monkeypatch.setattr(m._LinuxWorkerSession, 'cleanup', fault)
    caught = None
    started = time.monotonic()
    try:
        try:
            m._extract(tmp_path / 'fixture.txt', {'ocr_language': 'x' * (256 * 1024)} if timeout else {})
        except Exception as exc:
            caught = exc
            observations.update(exception=type(exc).__name__, message=str(exc),
                                cause_type=type(exc.__cause__).__name__ if exc.__cause__ else None,
                                cause_errno=getattr(exc.__cause__, 'errno', None),
                                cause_is_native_error=exc.__cause__ is native_error)
        else:
            observations['unexpected_success'] = True
        # All verdict facts are frozen BEFORE any reviewer kill/reap/join/close.
        observations.update(
            elapsed=time.monotonic() - started,
            stopped_before_safety_cleanup=bool(pins and select.select(pins, [], [], 0)[0]),
            new_threads_before_safety_cleanup=[t.name for t in threading.enumerate() if t not in before_threads],
            fds_before=sorted(before_fds),
            fds_before_safety_cleanup=sorted(os.listdir('/proc/self/fd')),
            production_pins_empty=bool(owners) and all(not owner.pins for owner in owners),
            processes=[{'returncode': owner.proc.returncode,
                        'stdin_closed': owner.proc.stdin.closed,
                        'stdout_closed': owner.proc.stdout.closed,
                        'stderr_closed': owner.proc.stderr.closed} for owner in owners])
    finally:
        for fd in pins:
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for owner in owners:
            owner.proc.wait(timeout=1)
        for thread in list(threading.enumerate()):
            if thread not in before_threads:
                thread.join(timeout=1)
        for fd in pins:
            os.close(fd)
        observations['fds_after_safety_cleanup'] = sorted(os.listdir('/proc/self/fd'))
        (tmp_path / 'fault-result.json').write_text(json.dumps(observations, indent=2), encoding='utf-8')
        print(json.dumps(observations), flush=True)
    assert observations['fault_calls'] == 1, observations  # no unsafe SID retry after native failure
    assert observations['stopped_before_safety_cleanup'], observations
    assert not observations['new_threads_before_safety_cleanup'], observations
    assert observations['production_pins_empty'], observations
    assert all(p['returncode'] is not None and p['stdin_closed'] and p['stdout_closed'] and p['stderr_closed']
               for p in observations['processes']), observations
    assert len(observations['fds_before_safety_cleanup']) == len(before_fds) + len(pins), observations
    assert observations['fds_after_safety_cleanup'] == observations['fds_before'], observations
    return caught, native_error, observations


@pytest.mark.parametrize('failure', ['ECHILD', 'proc-denied'])
def test_runtime_failure_is_error_without_unsafe_sid_rescan(tmp_path, monkeypatch, failure):
    caught, native_error, observations = _exercise_native_cleanup_fault(tmp_path, monkeypatch, failure)
    assert type(caught) is RuntimeError, observations
    assert str(caught) == 'document worker cleanup failed', observations
    assert caught.__cause__ is native_error, observations
    assert type(caught.__cause__) is (ChildProcessError if failure == 'ECHILD' else PermissionError)
    assert caught.__cause__.errno == (errno.ECHILD if failure == 'ECHILD' else errno.EACCES)


def test_timeout_remains_primary_with_linux_cleanup_failure(tmp_path, monkeypatch):
    caught, native_error, observations = _exercise_native_cleanup_fault(tmp_path, monkeypatch, 'proc-denied', timeout=True)
    assert type(caught) is RuntimeError, observations
    assert str(caught) == 'document worker exceeded timeout (10s)', observations
    assert caught.__cause__ is native_error, observations
    assert type(caught.__cause__) is PermissionError and caught.__cause__.errno == errno.EACCES
    assert 10 <= observations['elapsed'] < 11.5, observations
