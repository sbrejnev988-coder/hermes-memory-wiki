#!/usr/bin/env python3
"""Regression: document APIs default to the caller's configured scope."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"


def load_module():
    if str(MODULE.parent) not in sys.path:
        sys.path.insert(0, str(MODULE.parent))
    spec = importlib.util.spec_from_file_location("memory_wiki_document_scope_access_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    project_scope = "scope-A"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_document_status_and_source_lookup_cannot_cross_provider_scope() -> None:
    module = load_module()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    access_keys = (
        "MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID",
        "MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID",
        "MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE",
    )
    prior_env = {key: os.environ.get(key) for key in access_keys}
    for key in access_keys:
        os.environ[key] = ""
    try:
        provider = Provider(conn)
        module.install_document_graph_schema(conn)
        conn.executemany(
            """INSERT INTO document_sources(
                source_id,scope_id,repository_id,source_path,display_name,extension,
                status,active,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                ("source-A", "scope-A", "scope-A", "A.txt", "A.txt", ".txt", "active", 1, 1, 1),
                ("source-B", "scope-B", "scope-B", "B.txt", "B.txt", ".txt", "active", 1, 1, 1),
            ],
        )
        conn.executemany(
            """INSERT INTO document_units(
                unit_id,source_id,revision_id,unit_type,anchor,ordinal,title,unit_text,
                content_hash,locator_json,metadata_json,active,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                ("unit-A", "source-A", "rev-A", "paragraph", "a", 1, "A", "scope search sentinel", "a" * 64, "{}", "{}", 1, 1),
                ("unit-B", "source-B", "rev-B", "paragraph", "b", 1, "B", "scope search sentinel", "b" * 64, "{}", "{}", 1, 1),
            ],
        )
        conn.executemany(
            "INSERT INTO document_units_fts(source_id,unit_id,unit_type,title,anchor,unit_text) VALUES(?,?,?,?,?,?)",
            [
                ("source-A", "unit-A", "paragraph", "A", "a", "scope search sentinel"),
                ("source-B", "unit-B", "paragraph", "B", "b", "scope search sentinel"),
            ],
        )
        conn.commit()
        status = module.document_status(provider, {})
        assert [row["source_id"] for row in status["sources"]] == ["source-A"]
        query = module.query_documents(provider, {"query": "scope search sentinel"})
        assert {item["source_id"] for item in query["results"]} == {"source-A"}
        try:
            module.query_documents(provider, {"query": "scope search sentinel", "scope_id": "scope-B"})
        except PermissionError:
            pass
        else:
            raise AssertionError("cross-scope document query was allowed")
        for operation in (
            lambda: module.document_source(provider, {"source_id": "source-B"}),
            lambda: module.document_unit_context(provider, {"source_id": "source-B", "anchor": "x"}),
            lambda: module.delete_document(provider, {"source_id": "source-B"}),
        ):
            try:
                operation()
            except PermissionError:
                pass
            else:
                raise AssertionError("cross-scope source operation was allowed")
    finally:
        for key, value in prior_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        conn.close()


if __name__ == "__main__":
    test_document_status_and_source_lookup_cannot_cross_provider_scope()
    print("PASS test_document_status_and_source_lookup_cannot_cross_provider_scope")
