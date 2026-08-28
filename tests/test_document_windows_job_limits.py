#!/usr/bin/env python3
"""Regression: Windows worker sandbox uses a kill-on-close process-memory job limit."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_windows_job_limits_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_worker_limit_contract_is_memory_bounded_and_kill_on_close() -> None:
    before = os.environ.get("MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB")
    try:
        os.environ["MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB"] = "768"
        module = load_module()
        limits = module._windows_worker_limit_config()
        assert limits["process_memory_bytes"] == 768 * 1024 * 1024
        assert limits["limit_flags"] & limits["JOB_OBJECT_LIMIT_PROCESS_MEMORY"]
        assert limits["limit_flags"] & limits["JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE"]
    finally:
        if before is None:
            os.environ.pop("MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB", None)
        else:
            os.environ["MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB"] = before


if __name__ == "__main__":
    test_windows_worker_limit_contract_is_memory_bounded_and_kill_on_close()
    print("PASS test_windows_worker_limit_contract_is_memory_bounded_and_kill_on_close")
