#!/usr/bin/env python
"""Regressions for document search scope and rerank observability."""
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
        self.rerank_calls: list[tuple[str, str, int]] = []
        self.rerank_inputs: list[list[str]] = []

    def _connect(self) -> sqlite3.Connection:
        return self.conn

    def _search(self, query: str, **kwargs):
        self.search_kwargs = {**kwargs, "include_all_projects": bool(kwargs.get("include_all_projects", False))}
        return []

    def _rerank_rows(self, query: str, rows: list[dict], query_mode: str):
        self.rerank_calls.append((query, query_mode, len(rows)))
        self.rerank_inputs.append([str(row.get("id") or "") for row in rows])
        return [
            {**row, "rerank_rank": rank, "rerank_score": round(1.0 - rank / 10.0, 3)}
            for rank, row in enumerate(reversed(rows), 1)
        ]


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
            assert provider.search_kwargs["record_retrieval"] is False
            assert provider.search_kwargs["apply_rerank"] is False
        finally:
            conn.close()


def test_document_query_exposes_applied_rerank_metadata() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-document-rerank-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        module.install_document_graph_schema(conn)
        provider = Provider(conn)
        try:
            conn.execute(
                """INSERT INTO document_sources(
                    source_id,scope_id,repository_id,source_path,display_name,extension,
                    status,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("source-rerank", "hermes-state-db", "hermes-state-db", "rerank.md", "rerank.md", ".md", "ok", 1, 1, 1),
            )
            unit_rows = [
                (f"unit-{index}", "source-rerank", "rev-1", "paragraph", f"p:{index}", index,
                 f"Unit {index}", "rerank telemetry sentinel", f"{index:064x}", "{}", "{}", 1, 1)
                for index in range(1, 4)
            ]
            conn.executemany(
                """INSERT INTO document_units(
                    unit_id,source_id,revision_id,unit_type,anchor,ordinal,title,unit_text,
                    content_hash,locator_json,metadata_json,active,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                unit_rows,
            )
            conn.executemany(
                "INSERT INTO document_units_fts(source_id,unit_id,unit_type,title,anchor,unit_text) VALUES(?,?,?,?,?,?)",
                [("source-rerank", f"unit-{index}", "paragraph", f"Unit {index}", f"p:{index}", "rerank telemetry sentinel") for index in range(1, 4)],
            )
            conn.commit()

            result = module.query_documents(
                provider,
                {
                    "query": "rerank telemetry sentinel",
                    "scope_id": "hermes-state-db",
                    "repository_id": "hermes-state-db",
                    "limit": 3,
                },
            )
            assert provider.rerank_calls == [("rerank telemetry sentinel", "technical", 3)]
            assert provider.rerank_inputs == [[
                "docgraph:unit:unit-1",
                "docgraph:unit:unit-2",
                "docgraph:unit:unit-3",
            ]]
            assert result["retrieval"]["reranked"] is True
            assert [item["rerank_rank"] for item in result["results"]] == [1, 2, 3]
            assert [item["rerank_score"] for item in result["results"]] == [0.9, 0.8, 0.7]
        finally:
            conn.close()


if __name__ == "__main__":
    test_document_query_searches_selected_project_even_when_not_current()
    print("PASS test_document_query_searches_selected_project_even_when_not_current")
    test_document_query_exposes_applied_rerank_metadata()
    print("PASS test_document_query_exposes_applied_rerank_metadata")
