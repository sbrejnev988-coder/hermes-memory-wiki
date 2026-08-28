#!/usr/bin/env python3
"""Regression: automatic document ingestion is cache-only and scope-bound by default."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_auto_scope_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    pass


def test_auto_ingestion_requires_scope_and_default_roots_are_cache_only() -> None:
    keys = (
        "HERMES_HOME", "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR",
        "MEMORY_WIKI_DOCUMENT_ROOTS", "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE",
        "MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID", "MEMORY_WIKI_DOCUMENT_AUTO_REPOSITORY_ID",
        "MEMORY_WIKI_DOCUMENT_ALLOW_GLOBAL_AUTO",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-auto-scope-") as tmp:
            home = Path(tmp)
            cache = home / "cache" / "documents"
            cache.mkdir(parents=True)
            os.environ["HERMES_HOME"] = str(home)
            for key in keys[1:]:
                os.environ.pop(key, None)
            os.environ["MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE"] = "1"
            module = load_module()
            roots = module._roots()
            assert len(roots) == 1 and roots[0].resolve() == cache.resolve()

            def fail_if_scanned(*_args, **_kwargs):
                raise AssertionError("automatic ingestion ran without a scope")

            module.scan_documents = fail_if_scanned
            blocked = module.maybe_ingest_document_cache(Provider(), force=True)
            assert blocked["status"] == "blocked_missing_scope"

            captured = {}

            def capture_scan(_provider, args):
                captured.update(args)
                return {"status": "scanned"}

            module.scan_documents = capture_scan
            os.environ["MEMORY_WIKI_DOCUMENT_AUTO_SCOPE_ID"] = "profile-documents"
            result = module.maybe_ingest_document_cache(Provider(), force=True)
            assert result["status"] == "scanned"
            assert captured["scope_id"] == "profile-documents"
            assert captured["repository_id"] == "profile-documents"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_auto_ingestion_requires_scope_and_default_roots_are_cache_only()
    print("PASS test_auto_ingestion_requires_scope_and_default_roots_are_cache_only")
