#!/usr/bin/env python3
"""Regression: an overproducing parser worker is terminated before full output buffers."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_worker_limit_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flooding_worker_is_killed_when_bounded_output_is_exceeded() -> None:
    previous = {key: os.environ.get(key) for key in ("MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB", "MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT")}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-worker-flood-") as tmp:
            root = Path(tmp)
            worker = root / "document_worker.py"
            worker.write_text(
                "import sys,time\n"
                "sys.stdin.buffer.read()\n"
                "for _ in range(20):\n"
                "    sys.stdout.buffer.write(b'x' * (1024 * 1024))\n"
                "    sys.stdout.buffer.flush()\n"
                "    time.sleep(0.20)\n",
                encoding="utf-8",
            )
            module = load_module()
            original_file = module.__file__
            module.__file__ = str(root / "document_knowledge_graph.py")
            os.environ["MEMORY_WIKI_DOCUMENT_WORKER_OUTPUT_MB"] = "8"
            os.environ["MEMORY_WIKI_DOCUMENT_WORKER_TIMEOUT"] = "30"
            began = time.monotonic()
            try:
                module._extract(root / "fixture.txt", {})
            except RuntimeError as exc:
                assert "output" in str(exc).lower()
            else:
                raise AssertionError("flooding worker unexpectedly succeeded")
            finally:
                module.__file__ = original_file
            assert time.monotonic() - began < 2.2, "worker output was buffered instead of terminated promptly"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_flooding_worker_is_killed_when_bounded_output_is_exceeded()
    print("PASS test_flooding_worker_is_killed_when_bounded_output_is_exceeded")
