#!/usr/bin/env python3
"""Regression: document-manifest inbox consumption is bounded and atomically claimed."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_inbox_bounds_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    project_scope = "inbox-scope"

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")

    def _connect(self):
        return self.conn


def test_oversized_document_manifest_is_rejected_before_any_ingest() -> None:
    keys = ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_INBOX_MAX_DOCUMENTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-inbox-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["MEMORY_WIKI_DOCUMENT_INBOX_MAX_DOCUMENTS"] = "2"
            inbox = Path(tmp) / "context-coordination" / "inbox" / "documents"
            inbox.mkdir(parents=True)
            event = inbox / "too-many.json"
            event.write_text(json.dumps({
                "event_type": "document_manifest", "scope_id": "inbox-scope",
                "documents": [{"path": f"file-{index}.txt"} for index in range(3)],
            }), encoding="utf-8")
            module = load_module()
            provider = Provider()
            calls = []
            module.ingest_document = lambda _provider, item: calls.append(item) or {"status": "indexed"}
            result = module.ingest_document_inbox(provider, {"limit": 1})
            assert calls == []
            assert result["errors"] and "maximum" in result["errors"][0]["error"].lower()
            assert not event.exists(), "claimed rejected manifests must not be repeatedly reprocessed"
            provider.conn.close()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_oversized_document_manifest_is_rejected_before_any_ingest()
    print("PASS test_oversized_document_manifest_is_rejected_before_any_ingest")
