#!/usr/bin/env python
"""Regression: document query must search its explicitly selected project scope."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

GRAPH_PATH = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"
sys.path.insert(0, str(GRAPH_PATH.parent))
spec = importlib.util.spec_from_file_location("mw_document_query_project_scope_test", GRAPH_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Provider:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.search_kwargs: dict = {}

    def _connect(self) -> sqlite3.Connection:
        return self.conn

    def _search(self, query: str, **kwargs):
        self.search_kwargs = {**kwargs, "include_all_projects": bool(kwargs.get("include_all_projects", False))}
        return []


def test_document_query_searches_selected_project_even_when_not_current() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-document-query-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        module.install_document_graph_schema(conn)
        provider = Provider(conn)
        try:
            result = module.query_documents(
                provider,
                {
                    "query": "Qdrant semantic retrieval",
                    "scope_id": "hermes-state-db",
                    "repository_id": "hermes-state-db",
                },
            )
            assert result["retrieval"]["semantic_error"] == ""
            assert provider.search_kwargs["include_all_projects"] is True
        finally:
            conn.close()


if __name__ == "__main__":
    test_document_query_searches_selected_project_even_when_not_current()
    print("PASS test_document_query_searches_selected_project_even_when_not_current")
