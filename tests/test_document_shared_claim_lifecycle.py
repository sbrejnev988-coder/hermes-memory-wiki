#!/usr/bin/env python
"""Regression: reindexing one document must not archive a shared active chunk claim."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location("mw_shared_document_claim_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_shared_document_claim_survives_other_source_reindex() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-shared-claim-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        module.install_document_graph_schema(conn)
        conn.execute("CREATE TABLE claims(id TEXT PRIMARY KEY,status TEXT,updated_at INTEGER)")
        conn.executemany(
            "INSERT INTO claims VALUES(?,?,?)",
            [("c_shared", "active", 0), ("c_solo", "active", 0)],
        )
        conn.executemany(
            """INSERT INTO document_chunks(
                chunk_id,source_id,revision_id,scope_id,repository_id,
                content_hash,embedding_claim_id,active,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                ("old_shared", "retiring", "r1", "scope", "repo", "h1", "c_shared", 1, 0),
                ("keep_shared", "keeper", "r1", "scope", "repo", "h2", "c_shared", 1, 0),
                ("old_solo", "retiring", "r1", "scope", "repo", "h3", "c_solo", 1, 0),
            ],
        )
        conn.commit()
        try:
            archived = module._archive_claims(
                conn, ["c_shared", "c_solo"], retiring_source_ids={"retiring"}
            )
            statuses = dict(conn.execute("SELECT id,status FROM claims").fetchall())
        finally:
            conn.close()
        assert archived == 1
        assert statuses == {"c_shared": "active", "c_solo": "archived"}


if __name__ == "__main__":
    test_shared_document_claim_survives_other_source_reindex()
    print("PASS test_shared_document_claim_survives_other_source_reindex")
