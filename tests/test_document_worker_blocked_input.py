"""Real pipe regressions; an outer Job/session bounds intentionally stuck callers."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

if os.name == 'nt':
    # Warm stdlib FFI before launching venv redirectors; post-Popen Job
    # assignment's pre-existing startup race is not the regression under test.
    import ctypes
    from ctypes import wintypes

MODULE = Path(__file__).resolve().parents[1] / 'document_knowledge_graph.py'


def load_module():
    sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location('blocked_input_regression', MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_process_stopped(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            assert ctypes.get_last_error() == 87
        else:
            try:
                assert kernel32.WaitForSingleObject(handle, 1000) == 0
            finally:
                kernel32.CloseHandle(handle)
    else:
        # A terminated descendant can briefly remain a zombie until reaped.
        state = Path(f'/proc/{pid}/stat')
        deadline = time.monotonic() + 1
        while state.exists() and state.read_text().split(') ', 1)[1][0] != 'Z':
            assert time.monotonic() < deadline, f'process {pid} remains alive'
            time.sleep(0.01)


def run_bounded_case(tmp_path, mode, budget):
    module = load_module()
    gate = tmp_path / 'assigned.gate'
    for name in ('home', 'temp', 'appdata', 'localappdata'):
        (tmp_path / name).mkdir()
    env = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'LANG') if key in os.environ}
    env.update({
        'HOME': str(tmp_path / 'home'), 'USERPROFILE': str(tmp_path / 'home'),
        'HERMES_HOME': str(tmp_path / 'home/hermes'), 'APPDATA': str(tmp_path / 'appdata'),
        'LOCALAPPDATA': str(tmp_path / 'localappdata'), 'TEMP': str(tmp_path / 'temp'),
        'TMP': str(tmp_path / 'temp'), 'TMPDIR': str(tmp_path / 'temp'),
        'PYTHON_DOTENV_DISABLED': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'MEMORY_WIKI_DOCUMENT_AUTO_EMBED': '0', 'MEMORY_WIKI_DOCUMENT_PREFETCH': '0',
        'MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB': '8', 'MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT': '10',
    })
    command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker-case', mode, str(tmp_path), str(gate)]
    proc = subprocess.Popen(command, cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name == 'posix')
    job = None
    timed_out = False

    def kill_posix_case():
        # _extract starts its worker in a separate session from this caller.
        # Contain both groups when an intentionally broken candidate hangs.
        worker_pid = tmp_path / 'worker.pid'
        if worker_pid.exists():
            try:
                os.killpg(int(worker_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        if os.name == 'nt':
            job = module._assign_windows_worker_job(proc)
            assert job is not None
        gate.write_text('contained', encoding='ascii')
        try:
            stdout, stderr = proc.communicate(timeout=budget)
        except subprocess.TimeoutExpired:
            timed_out = True
            if job:
                module._close_windows_worker_job(job)
                job = None
            else:
                kill_posix_case()
            stdout, stderr = proc.communicate(timeout=5)
    finally:
        # Interrupt the tree before waiting; never wait on a blocked stdin lock.
        if job:
            module._close_windows_worker_job(job)
        elif proc.poll() is None:
            if os.name == 'posix':
                kill_posix_case()
            else:
                proc.kill()
        proc.wait(timeout=5)
    # Check actual fault worker/descendant identity even in the RED timeout path.
    for filename in ('worker.pid', 'descendant.pid'):
        path = tmp_path / filename
        if path.exists():
            assert_process_stopped(int(path.read_text()))
    evidence = {'outer_deadline_hit': timed_out, 'budget': budget, 'returncode': proc.returncode,
                'stdout': stdout.decode('utf-8', 'replace'), 'stderr': stderr.decode('utf-8', 'replace')}
    (tmp_path / 'case-result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence), flush=True)
    assert not timed_out, f'termination controller blocked past outer {budget}s deadline: {stderr.decode("utf-8", "replace")}'
    assert proc.returncode == 0, evidence
    return json.loads(stdout)


def worker_case(mode, root, gate):
    deadline = time.monotonic() + 10
    while not gate.exists():
        assert time.monotonic() < deadline, 'external containment not assigned'
        time.sleep(0.01)
    module = load_module()
    code = (
        'import os,sys,time\n'
        'from pathlib import Path\n'
        f'Path({str(root / "worker.pid")!r}).write_text(str(os.getpid()))\n'
        'try:\n'
        '    for _ in range(20):\n'
        '        sys.stderr.buffer.write(b"x" * (1024 * 1024))\n'
        '        sys.stderr.buffer.flush()\n'
        '        time.sleep(0.20)\n'
        'except (BrokenPipeError,OSError):\n'
        f'    Path({str(root / "broken-pipe.marker")!r}).write_text("overflow")\n'
        '    time.sleep(30)\n'
    )
    if mode == 'silent':
        code = (
            'import os,subprocess,sys,time\n'
            'from pathlib import Path\n'
            f'Path({str(root / "worker.pid")!r}).write_text(str(os.getpid()))\n'
            'child = subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
            f'Path({str(root / "descendant.pid")!r}).write_text(str(child.pid))\n'
            'time.sleep(30)\n'
        )
    elif mode == 'closed-stdin':
        code = (
            'import os,sys\n'
            'from pathlib import Path\n'
            f'Path({str(root / "worker.pid")!r}).write_text(str(os.getpid()))\n'
            'os.close(0)\n'
            'sys.exit(7)\n'
        )
    elif mode == 'exited-parent':
        code = (
            'import os,subprocess,sys\n'
            'from pathlib import Path\n'
            f'Path({str(root / "worker.pid")!r}).write_text(str(os.getpid()))\n'
            'child = subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
            f'Path({str(root / "descendant.pid")!r}).write_text(str(child.pid))\n'
            'sys.stdout.buffer.write(b\'{"ok":true,"document":{"status":"ok"}}\')\n'
            'sys.stdout.buffer.flush()\n'
        )
    else:
        assert mode == 'overflow'
    (root / 'document_worker.py').write_text(code, encoding='utf-8')
    module.__file__ = str(root / MODULE.name)
    threads_before = set(threading.enumerate())
    import faulthandler
    faulthandler.dump_traceback_later(11.6 if mode == 'silent' else 3)
    began = time.monotonic()
    try:
        module._extract(root / 'fixture.txt', {'ocr_language': 'x' * (256 * 1024)})
    except Exception as exc:
        elapsed = time.monotonic() - began
        result = {'exception': type(exc).__name__, 'message': str(exc), 'elapsed': elapsed,
                  'new_threads': [t.name for t in threading.enumerate() if t not in threads_before]}
    else:
        raise AssertionError('fault worker unexpectedly accepted')
    finally:
        faulthandler.cancel_dump_traceback_later()
    result['stopped_processes'] = []
    for filename in ('worker.pid', 'descendant.pid'):
        pid_file = root / filename
        if pid_file.exists():
            # Observe termination before the outer test containment is closed.
            assert_process_stopped(int(pid_file.read_text()))
            result['stopped_processes'].append(filename)
    print(json.dumps(result), flush=True)


def test_overflow_interrupts_worker_before_stdin_write_finishes(tmp_path):
    result = run_bounded_case(tmp_path, 'overflow', 4)
    assert result['exception'] == 'RuntimeError'
    assert 'output exceeds configured limit' in result['message']
    assert result['elapsed'] < 2.2
    assert result['new_threads'] == []


def test_silent_nonreader_timeout_covers_stdin_transfer(tmp_path):
    result = run_bounded_case(tmp_path, 'silent', 12)
    assert result['exception'] == 'RuntimeError'
    assert 'exceeded timeout (10s)' in result['message']
    assert 10 <= result['elapsed'] < 11.5
    assert result['new_threads'] == []
    assert result['stopped_processes'] == ['worker.pid', 'descendant.pid']


def test_closed_stdin_writer_error_remains_visible(tmp_path):
    result = run_bounded_case(tmp_path, 'closed-stdin', 4)
    assert result['exception'] == 'BrokenPipeError'
    assert result['elapsed'] < 2.2
    assert result['new_threads'] == []


def test_exited_worker_job_unblocks_inherited_stdin_writer(tmp_path):
    if os.name != 'nt':
        import pytest
        pytest.skip('Windows kill-on-close Job after root worker exits')
    result = run_bounded_case(tmp_path, 'exited-parent', 4)
    assert result['exception'] == 'BrokenPipeError'
    assert result['elapsed'] < 2.2
    assert result['new_threads'] == []
    assert result['stopped_processes'] == ['worker.pid', 'descendant.pid']


def test_large_utf8_request_is_delivered_without_writer_thread_leak(tmp_path, monkeypatch):
    module = load_module()
    (tmp_path / 'document_worker.py').write_text(
        'import json,sys\n'
        'request = json.loads(sys.stdin.buffer.read())\n'
        'sys.stdout.buffer.write(json.dumps({"ok":True,"document":{"language":request["options"]["ocr_language"]}},ensure_ascii=False).encode("utf-8"))\n',
        encoding='utf-8')
    monkeypatch.setattr(module, '__file__', str(tmp_path / MODULE.name))
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT', '10')
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB', '8')
    threads_before = set(threading.enumerate())
    language = 'Я✓' * (64 * 1024)
    assert module._extract(tmp_path / 'fixture.txt', {'ocr_language': language}) == {'language': language}
    assert not [t for t in threading.enumerate() if t not in threads_before]


if __name__ == '__main__':
    assert sys.argv[1] == '--worker-case'
    worker_case(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
