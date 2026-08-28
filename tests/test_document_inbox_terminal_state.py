#!/usr/bin/env python3
"""Regression: terminal document inbox manifests are never claimed a second time."""
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
    spec = importlib.util.spec_from_file_location("memory_wiki_document_inbox_terminal_test", MODULE)
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


def test_processed_manifest_is_not_reingested_or_renamed_again() -> None:
    before = os.environ.get("HERMES_HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="mw-inbox-terminal-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            inbox = Path(tmp) / "context-coordination" / "inbox" / "documents"
            inbox.mkdir(parents=True)
            event = inbox / "once.json"
            event.write_text(json.dumps({
                "event_type": "document_manifest", "scope_id": "inbox-scope",
                "repository_id": "inbox-scope", "documents": [{"path": "fixture.txt"}],
            }), encoding="utf-8")
            module = load_module()
            provider = Provider()
            calls = []
            module.ingest_document = lambda _provider, item: calls.append(item) or {"status": "indexed", "source_id": "fixture"}
            first = module.ingest_document_inbox(provider, {"limit": 10})
            second = module.ingest_document_inbox(provider, {"limit": 10})
            assert len(first["processed"]) == 1
            assert second["processed"] == []
            assert len(calls) == 1
            assert (inbox / "once.processed.json").is_file()
            assert not (inbox / "once.processed.processed.json").exists()
            provider.conn.close()
    finally:
        if before is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = before


if __name__ == "__main__":
    test_processed_manifest_is_not_reingested_or_renamed_again()
    print("PASS test_processed_manifest_is_not_reingested_or_renamed_again")
