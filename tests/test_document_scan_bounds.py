#!/usr/bin/env python3
"""Regression: document scanning has a bounded streaming traversal budget."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_scan_bounds_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    project_scope = "scan-test-scope"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_scan_stops_at_entry_budget_and_reports_truncation() -> None:
    keys = ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-scan-bounds-") as tmp:
            home = Path(tmp)
            docs = home / "cache" / "documents"
            docs.mkdir(parents=True)
            for name in ("a.txt", "b.txt", "c.txt"):
                (docs / name).write_text(name, encoding="utf-8")
            os.environ["HERMES_HOME"] = str(home)
            for key in keys[1:]:
                os.environ.pop(key, None)
            module = load_module()
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            provider = Provider(conn)
            calls = []
            module.ingest_document = lambda _provider, item: calls.append(item["path"]) or {"status": "indexed"}
            result = module.scan_documents(provider, {
                "root": str(docs), "max_files": 20, "max_changed": 20,
                "max_entries": 1, "scan_max_seconds": 10,
            })
            assert result["traversal_truncated"] is True
            assert result["entries_seen"] == 1
            assert len(calls) <= 1
            conn.close()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_scan_stops_at_entry_budget_and_reports_truncation()
    print("PASS test_scan_stops_at_entry_budget_and_reports_truncation")
