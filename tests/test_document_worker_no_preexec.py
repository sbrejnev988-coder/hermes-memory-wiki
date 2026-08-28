#!/usr/bin/env python3
"""Regression: POSIX worker launch avoids fork-time preexec hooks in a threaded gateway."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_no_preexec_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProc:
    def __init__(self) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(json.dumps({"ok": True, "document": {"status": "ok"}}).encode("utf-8"))
        self.stderr = io.BytesIO()
        self.returncode = 0
        self.pid = 999999

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def test_posix_launch_uses_session_without_preexec_fn() -> None:
    module = load_module()
    kwargs = module._worker_launch_kwargs(Path("worker.py"), platform="posix")
    assert kwargs.get("start_new_session") is True
    assert "preexec_fn" not in kwargs


if __name__ == "__main__":
    test_posix_launch_uses_session_without_preexec_fn()
    print("PASS test_posix_launch_uses_session_without_preexec_fn")
