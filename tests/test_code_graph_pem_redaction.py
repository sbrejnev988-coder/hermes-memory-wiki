#!/usr/bin/env python3
"""Regression: PEM-shaped source is never persisted by code-graph ingestion."""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "code_knowledge_graph.py"


def load_module():
    spec = importlib.util.spec_from_file_location("memory_wiki_code_graph_pem_test", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _connect(self) -> sqlite3.Connection:
        return self.conn


def test_code_graph_redacts_pem_blocks_before_sqlite_and_fts_storage() -> None:
    module = load_module()
    pem = "-----BEGIN PRIVATE KEY-----\nvery-sensitive-material\n-----END PRIVATE KEY-----"
    with tempfile.TemporaryDirectory(prefix="mw-code-pem-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        try:
            provider = Provider(conn)
            module.ingest_code_graph_event(
                provider,
                {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": "repo-test",
                    "event_id": "pem-regression-event",
                    "snapshot_mode": "full",
                    "snapshot_hash": "pem-regression-hash",
                    "lines": [
                        {
                            "file_path": "src/secret.py",
                            "line_no": 1,
                            "line_id": "line:repo-test:src/secret.py:1",
                            "line_text": f"PRIVATE = '''{pem}'''",
                        }
                    ],
                },
            )
            stored = conn.execute(
                "SELECT line_text FROM code_graph_lines WHERE repository_id=?", ("repo-test",)
            ).fetchone()[0]
            assert pem not in stored
            assert "<REDACTED_PEM_BLOCK>" in stored
            fts = conn.execute(
                "SELECT line_text FROM code_graph_lines_fts WHERE repository_id=?", ("repo-test",)
            ).fetchone()[0]
            assert pem not in fts
        finally:
            conn.close()


if __name__ == "__main__":
    test_code_graph_redacts_pem_blocks_before_sqlite_and_fts_storage()
    print("PASS test_code_graph_redacts_pem_blocks_before_sqlite_and_fts_storage")
