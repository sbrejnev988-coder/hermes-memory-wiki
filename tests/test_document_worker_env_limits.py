#!/usr/bin/env python3
"""Regression: parent forwards non-secret resource-limit settings to the isolated worker."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_worker_env_limits_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parent_forwards_worker_resource_limits_without_forwarding_secrets() -> None:
    keys = ("MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB", "MEMORY_WIKI_DOCUMENT_WORKER_CPU_SECONDS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB"] = "768"
        os.environ["MEMORY_WIKI_DOCUMENT_WORKER_CPU_SECONDS"] = "90"
        module = load_module()
        env = module._worker_env(Path("worker.py"))
        assert env["MEMORY_WIKI_DOCUMENT_WORKER_MEMORY_MB"] == "768"
        assert env["MEMORY_WIKI_DOCUMENT_WORKER_CPU_SECONDS"] == "90"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_parent_forwards_worker_resource_limits_without_forwarding_secrets()
    print("PASS test_parent_forwards_worker_resource_limits_without_forwarding_secrets")
