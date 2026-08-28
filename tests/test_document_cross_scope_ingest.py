#!/usr/bin/env python3
"""Regression: one scope cannot relabel an existing document source owned by another."""
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
    spec = importlib.util.spec_from_file_location("memory_wiki_document_cross_scope_ingest_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    def __init__(self, conn: sqlite3.Connection, scope: str) -> None:
        self.conn = conn
        self.project_scope = scope

    def _connect(self):
        return self.conn


def test_cross_scope_ingest_cannot_transfer_existing_source_ownership() -> None:
    keys = ("HERMES_HOME", "MEMORY_WIKI_DOCUMENT_CACHE_DIR", "HERMES_DOCUMENT_CACHE_DIR", "MEMORY_WIKI_DOCUMENT_ROOTS", "MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE", "MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-cross-scope-ingest-") as tmp:
            home = Path(tmp)
            docs = home / "cache" / "documents"
            docs.mkdir(parents=True)
            source = docs / "shared.md"
            body = "# Scope isolation\n\nSame file must retain its owner."
            source.write_text(body, encoding="utf-8")
            os.environ["HERMES_HOME"] = str(home)
            for key in keys[1:]:
                os.environ.pop(key, None)
            module = load_module()
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row

            def fake_extract(path: Path, _args):
                data = path.read_bytes()
                return {
                    "file_name": path.name, "extension": path.suffix, "mime_type": "text/markdown",
                    "title": path.stem, "file_hash": hashlib.sha256(data).hexdigest(),
                    "mtime_ns": 1, "file_size": len(data), "parser": "fixture",
                    "parser_version": "fixture", "status": "ok", "metadata": {}, "warnings": [],
                    "units": [{"kind": "paragraph", "anchor": "p:1", "text": body}], "edges": [],
                    "security_status": "no_detected_secret", "secret_redactions": 0, "secret_categories": {},
                }

            module._extract = fake_extract
            first = module.ingest_document(Provider(conn, "scope-A"), {"path": str(source)})
            assert first["status"] == "indexed"
            try:
                module.ingest_document(Provider(conn, "scope-B"), {"path": str(source)})
            except PermissionError:
                pass
            else:
                raise AssertionError("scope B was able to relabel scope A document")
            stored = conn.execute("SELECT scope_id,repository_id FROM document_sources WHERE source_id=?", (first["source_id"],)).fetchone()
            assert dict(stored) == {"scope_id": "scope-A", "repository_id": "scope-A"}
            conn.close()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_cross_scope_ingest_cannot_transfer_existing_source_ownership()
    print("PASS test_cross_scope_ingest_cannot_transfer_existing_source_ownership")
