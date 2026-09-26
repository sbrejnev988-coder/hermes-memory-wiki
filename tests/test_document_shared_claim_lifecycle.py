#!/usr/bin/env python
"""Regression: reindexing one document must not archive a shared active chunk claim."""
from __future__ import annotations

import importlib.util
import hashlib
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
            conn.execute("UPDATE document_chunks SET active=0 WHERE source_id='retiring'")
            archived = module._archive_claims(
                conn, ["c_shared", "c_solo"]
            )
            statuses = dict(conn.execute("SELECT id,status FROM claims").fetchall())
        finally:
            conn.close()
        assert archived == 1
        assert statuses == {"c_shared": "active", "c_solo": "archived"}


def test_shared_document_claim_survives_new_revision_of_same_source(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "graph.sqlite3"))
    conn.row_factory = sqlite3.Row
    try:
        module.install_document_graph_schema(conn)
        conn.execute("CREATE TABLE claims(id TEXT PRIMARY KEY,status TEXT,updated_at INTEGER)")
        conn.executemany("INSERT INTO claims VALUES(?,?,?)",
                         [("c_shared", "active", 0), ("c_solo", "active", 0)])
        conn.executemany(
            """INSERT INTO document_chunks(
                chunk_id,source_id,revision_id,scope_id,repository_id,
                content_hash,embedding_claim_id,active,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
            [("retiring-shared", "same-source", "rev-old", "scope", "repo",
              "hash-a", "c_shared", 1, 0),
             ("retiring-solo", "same-source", "rev-old", "scope", "repo",
              "hash-b", "c_solo", 1, 0),
             ("still-active", "same-source", "rev-new", "scope", "repo",
              "hash-c", "c_shared", 1, 0)],
        )
        conn.commit()
        conn.execute("UPDATE document_chunks SET active=0 WHERE revision_id='rev-old'")
        archived = module._archive_claims(conn, ["c_shared", "c_solo"])
        statuses = dict(conn.execute("SELECT id,status FROM claims").fetchall())
        assert archived == 1
        assert statuses == {"c_shared": "active", "c_solo": "archived"}
    finally:
        conn.close()


def test_reingest_does_not_leave_active_claim_without_active_chunk(tmp_path, monkeypatch) -> None:
    """Archive after retiring all source chunks, including a stray newer rev."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ROOTS", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", raising=False)
    monkeypatch.delenv("HERMES_DOCUMENT_CACHE_DIR", raising=False)
    docs = tmp_path / "cache" / "documents"
    docs.mkdir(parents=True)
    source = docs / "fixture.txt"
    source.write_text("first revision", encoding="utf-8")

    def extract(snapshot, _args):
        raw = snapshot.read_bytes()
        return {
            "file_name": snapshot.name, "extension": ".txt", "mime_type": "text/plain",
            "title": "fixture", "file_hash": hashlib.sha256(raw).hexdigest(),
            "mtime_ns": 1, "file_size": len(raw), "parser": "fixture",
            "parser_version": "fixture", "status": "ok", "metadata": {},
            "warnings": [], "security_status": "no_detected_secret",
            "units": [{"anchor": "paragraph:1", "kind": "paragraph", "title": "fixture",
                       "text": "synthetic " * 40}], "edges": [],
        }

    monkeypatch.setattr(module, "_extract", extract)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    class Provider:
        project_scope = "fixture-scope"
        bot_id = "fixture-bot"

        def _connect(self):
            return conn

        def _claim_visible(self, row):
            return row["visibility_scope"] == "bot" and row["origin_bot_id"] == self.bot_id

    try:
        module.install_document_graph_schema(conn)
        conn.execute("""CREATE TABLE claims(
            id TEXT PRIMARY KEY, status TEXT, updated_at INTEGER,
            topic TEXT, source TEXT, evidence TEXT,
            visibility_scope TEXT, origin_bot_id TEXT, origin_chat_hash TEXT,
            origin_session_id TEXT, project_id TEXT)""")
        first = module.ingest_document(Provider(), {"path": str(source), "embed": False})
        source_id = first["source_id"]
        old_rev = first["revision_id"]
        content_hash = conn.execute(
            "SELECT content_hash FROM document_chunks WHERE source_id=? AND active=1",
            (source_id,),
        ).fetchone()[0]
        evidence = (
            "document_chunk_ref:" + module._evidence_ref(f"{source_id}\0{content_hash}")
            + "; source_ref:" + module._evidence_ref(source_id)
            + "; revision_ref:" + module._evidence_ref(old_rev)
        )
        conn.execute(
            """INSERT INTO claims(id,status,updated_at,topic,source,evidence,
                                  visibility_scope,origin_bot_id)
               VALUES(?,?,?,?,?,?,?,?)""",
            ("c_retired", "active", 0, module._TOPIC, "artifact:document-index",
             evidence, "bot", "fixture-bot"),
        )
        conn.execute("UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=? AND active=1",
                     ("c_retired", source_id))
        conn.execute("""INSERT INTO document_chunks(
            chunk_id,source_id,revision_id,scope_id,repository_id,
            content_hash,embedding_claim_id,active,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            ("stray-newer", source_id, "rev-stray", "fixture-scope", "fixture-scope",
             "synthetic-hash", "c_retired", 1, 0),
        )
        conn.commit()
        source.write_text("second revision", encoding="utf-8")
        second = module.ingest_document(Provider(), {"path": str(source), "embed": False})
        assert second["revision_id"] != old_rev
        assert conn.execute("SELECT status FROM claims WHERE id='c_retired'").fetchone()[0] == "archived"
        assert conn.execute("""SELECT COUNT(*) FROM document_chunks
                               WHERE active=1 AND embedding_claim_id='c_retired'""").fetchone()[0] == 0
    finally:
        conn.close()


if __name__ == "__main__":
    test_shared_document_claim_survives_other_source_reindex()
    print("PASS test_shared_document_claim_survives_other_source_reindex")
