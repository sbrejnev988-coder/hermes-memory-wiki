"""Real subprocess regressions for bounded worker output and Windows Job cleanup."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'document_knowledge_graph.py'


def load_worker_module(tmp_path, monkeypatch, code):
    spec = importlib.util.spec_from_file_location('worker_lifecycle_regression', MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'document_worker.py').write_text(code, encoding='utf-8')
    monkeypatch.setattr(module, '__file__', str(tmp_path / MODULE.name))
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB', '8')
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT', '30')
    return module


def test_stderr_flood_is_terminated_promptly(tmp_path, monkeypatch):
    module = load_worker_module(tmp_path, monkeypatch,
        'import sys,time\n'
        'sys.stdin.buffer.read()\n'
        'for _ in range(20):\n'
        '    sys.stderr.buffer.write(b"x" * (1024 * 1024))\n'
        '    sys.stderr.buffer.flush()\n'
        '    time.sleep(0.20)\n')
    began = time.monotonic()
    with pytest.raises(RuntimeError, match='output exceeds configured limit'):
        module._extract(tmp_path / 'fixture.txt', {})
    assert time.monotonic() - began < 2.2


def test_normal_json_at_exact_output_limits_on_both_channels(tmp_path, monkeypatch):
    module = load_worker_module(tmp_path, monkeypatch,
        'import json,sys\n'
        'sys.stdin.buffer.read()\n'
        'response = json.dumps({"ok":True,"document":{"text":"Проверка ✓"}}, ensure_ascii=False).encode("utf-8")\n'
        'sys.stderr.buffer.write(b"x" * (8 * 1024 * 1024))\n'
        'sys.stderr.buffer.flush()\n'
        'sys.stdout.buffer.write(response + b" " * (8 * 1024 * 1024 - len(response)))\n'
        'sys.stdout.buffer.flush()\n')
    assert module._extract(tmp_path / 'fixture.txt', {}) == {'text': 'Проверка ✓'}


def test_real_worker_timeout_terminates_promptly(tmp_path, monkeypatch):
    module = load_worker_module(tmp_path, monkeypatch,
        'import sys,time\n'
        'sys.stdin.buffer.read()\n'
        'sys.stdout.buffer.write(b"partial")\n'
        'sys.stdout.buffer.flush()\n'
        'time.sleep(30)\n')
    monkeypatch.setenv('MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT', '10')
    began = time.monotonic()
    with pytest.raises(RuntimeError, match=r'exceeded timeout \(10s\)'):
        module._extract(tmp_path / 'fixture.txt', {})
    elapsed = time.monotonic() - began
    assert 10 <= elapsed < 11.5


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object inherited pipe lifecycle')
def test_exited_worker_descendant_pipes_are_closed_before_reader_join(tmp_path, monkeypatch):
    module = load_worker_module(tmp_path, monkeypatch,
        'import json,subprocess,sys\n'
        'request = json.loads(sys.stdin.buffer.read())\n'
        'child = subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"], stdin=subprocess.DEVNULL)\n'
        'with open(request["path"], "w") as output:\n'
        '    output.write(str(child.pid))\n'
        'sys.stdout.buffer.write(b\'{"ok":true,"document":{"status":"ok"}}\')\n'
        'sys.stdout.buffer.flush()\n')
    pid_file = tmp_path / 'child.pid'
    began = time.monotonic()
    assert module._extract(pid_file, {}) == {'status': 'ok'}
    assert time.monotonic() - began < 2.2
    # A PID disappearing also proves termination; otherwise query the real OS handle.
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, int(pid_file.read_text()))
    if not handle:
        assert ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: PID gone.
    else:
        try:
            assert kernel32.WaitForSingleObject(handle, 1000) == 0  # WAIT_OBJECT_0.
        finally:
            kernel32.CloseHandle(handle)
