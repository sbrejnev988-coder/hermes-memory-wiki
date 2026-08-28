#!/usr/bin/env python3
"""Regression: worker installs its own parser limits before it touches a document."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path


WORKER = Path(__file__).resolve().parents[1] / "document_worker.py"


def load_worker():
    if str(WORKER.parent) not in sys.path:
        sys.path.insert(0, str(WORKER.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_worker_limit_setup_test", WORKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stdin:
    def __init__(self, raw: bytes) -> None:
        self.buffer = io.BytesIO(raw)


class Stdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


def test_worker_applies_limits_before_extraction() -> None:
    module = load_worker()
    events = []
    module._apply_resource_limits = lambda: events.append("limits")
    module.extract_document = lambda _path, _options: events.append("extract") or {"status": "ok"}
    original_stdin, original_stdout = sys.stdin, sys.stdout
    try:
        sys.stdin = Stdin(json.dumps({"path": "fixture.txt", "options": {}}).encode("utf-8"))
        sink = Stdout()
        sys.stdout = sink
        assert module.main() == 0
        assert events == ["limits", "extract"]
        assert json.loads(sink.buffer.getvalue().decode("utf-8"))["ok"] is True
    finally:
        sys.stdin, sys.stdout = original_stdin, original_stdout


if __name__ == "__main__":
    test_worker_applies_limits_before_extraction()
    print("PASS test_worker_applies_limits_before_extraction")
