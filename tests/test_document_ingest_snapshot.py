#!/usr/bin/env python3
"""Regression: worker extraction receives only a disposable secure snapshot."""
from __future__ import annotations

import hashlib
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
    spec = importlib.util.spec_from_file_location("memory_wiki_document_ingest_snapshot_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    project_scope = "document-test-scope"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_ingest_passes_snapshot_not_original_path_to_worker() -> None:
    keys = ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-ingest-snapshot-") as tmp:
            home = Path(tmp)
            docs = home / "cache" / "documents"
            docs.mkdir(parents=True)
            source = docs / "report.txt"
            content = "immutable snapshot fixture"
            source.write_text(content, encoding="utf-8")
            os.environ["HERMES_HOME"] = str(home)
            for key in keys[1:]:
                os.environ.pop(key, None)
            module = load_module()
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            provider = Provider(conn)
            captured = []

            def fake_extract(path: Path, _args):
                captured.append(path)
                assert path.read_text(encoding="utf-8") == content
                return {
                    "file_name": path.name,
                    "extension": path.suffix,
                    "mime_type": "text/plain",
                    "title": path.stem,
                    "file_hash": hashlib.sha256(content.encode()).hexdigest(),
                    "mtime_ns": 1,
                    "file_size": len(content.encode()),
                    "parser": "fixture",
                    "parser_version": "fixture",
                    "status": "ok",
                    "metadata": {},
                    "warnings": [],
                    "units": [],
                    "edges": [],
                    "security_status": "no_detected_secret",
                    "secret_redactions": 0,
                    "secret_categories": {},
                }

            module._extract = fake_extract
            result = module.ingest_document(provider, {"path": str(source), "embed": False})
            assert result["status"] == "indexed"
            assert captured and captured[0] != source
            assert not captured[0].exists(), "snapshot should be deleted after parsing"
            assert not captured[0].parent.exists(), "per-invocation snapshot directory should be removed"
            stored = conn.execute("SELECT display_name,title FROM document_sources").fetchone()
            assert stored["display_name"] == "report.txt"
            assert stored["title"] == "report", "snapshot pathname must not leak into stored title"
            conn.close()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_ingest_passes_snapshot_not_original_path_to_worker()
    print("PASS test_ingest_passes_snapshot_not_original_path_to_worker")
