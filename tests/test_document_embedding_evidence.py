#!/usr/bin/env python
"""Regression: document embedding claims must not put raw paths in evidence."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "document_knowledge_graph.py"
sys.path.insert(0, str(MODULE_PATH.parent))
spec = importlib.util.spec_from_file_location("mw_document_evidence_test", MODULE_PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class Provider:
    project_scope = "scope"
    bot_id = "bot-a"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.evidence: list[str] = []

    def _connect(self) -> sqlite3.Connection:
        return self.conn

    def _add_claim(self, _claim: str, **kwargs) -> str:
        self.evidence.append(str(kwargs["evidence"]))
        return "c_document_embedding_test"

    def _claim_visible(self, row: sqlite3.Row) -> bool:
        return (row["visibility_scope"] == "project"
                and row["project_id"] == self.project_scope)


def test_embedding_evidence_uses_safe_refs_not_token_like_provenance() -> None:
    source_id = "docsrc_" + "a" * 24
    revision_id = "docrev_" + "c" * 28
    content_hash = "b" * 64
    with tempfile.TemporaryDirectory(prefix="mw-doc-evidence-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        mod.install_document_graph_schema(conn)
        conn.execute("CREATE TABLE claims(id TEXT, topic TEXT, status TEXT, evidence TEXT, updated_at INTEGER, visibility_scope TEXT, origin_bot_id TEXT, origin_chat_hash TEXT, origin_session_id TEXT, project_id TEXT)")
        conn.execute(
            """INSERT INTO document_sources(
                source_id, scope_id, repository_id, source_path, display_name, extension, title, file_hash,
                parser, parser_version, revision_id, status, active, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_id, "scope", "scope", "C:/fixture-root/hermes/documents/session.md",
                "session.md", ".md", "session", "hash", "stdlib-text", "test",
                revision_id, "ok", 1, 1, 1,
            ),
        )
        conn.execute(
            """INSERT INTO document_chunks(
                chunk_id, source_id, revision_id, scope_id, repository_id,
                start_anchor, end_anchor, chunk_kind, title, chunk_text,
                embedding_text, content_hash, embedding_claim_id, token_estimate,
                active, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "docchunk_test", source_id, revision_id, "scope", "scope",
                "heading:1", "heading:1", "semantic", "session", "safe text",
                "safe text", content_hash, "", 2, 1, 1,
            ),
        )
        conn.commit()
        provider = Provider(conn)
        result = mod.embed_pending_documents(provider, {})
        evidence = list(provider.evidence)
        claim_id = conn.execute(
            "SELECT embedding_claim_id FROM document_chunks WHERE chunk_id='docchunk_test'"
        ).fetchone()[0]
        conn.close()

        assert result["created"] == 1
        assert result["failed"] == 0
        assert evidence
        assert "path=" not in evidence[0]
        assert "path_sha256=" not in evidence[0]
        assert source_id not in evidence[0]
        assert revision_id not in evidence[0]
        assert content_hash not in evidence[0]
        assert "document_chunk_ref:" in evidence[0]
        assert "source_ref:" in evidence[0]
        assert "revision_ref:" in evidence[0]
        assert claim_id == "c_document_embedding_test"


def test_document_embedding_reuses_only_visible_claim() -> None:
    """A newer foreign project match cannot steal the current chunk link."""
    source_id = "docsrc_" + "d" * 24
    content_hash = "f" * 64
    evidence_key = "document_chunk_ref:" + mod._evidence_ref(
        f"{source_id}\0{content_hash}"
    )
    with tempfile.TemporaryDirectory(prefix="mw-doc-acl-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        mod.install_document_graph_schema(conn)
        conn.execute("""CREATE TABLE claims(
            id TEXT, topic TEXT, status TEXT, evidence TEXT, updated_at INTEGER,
            visibility_scope TEXT, origin_bot_id TEXT, origin_chat_hash TEXT,
            origin_session_id TEXT, project_id TEXT)""")
        conn.executemany(
            """INSERT INTO claims(id,topic,status,evidence,updated_at,
                 visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id)
                 VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [("c_visible", mod._TOPIC, "active", evidence_key, 1,
              "project", "", "", "", "scope"),
             ("c_foreign", mod._TOPIC, "active", evidence_key, 2,
              "project", "", "", "", "other")],
        )
        conn.execute("""INSERT INTO document_sources(
            source_id, scope_id, repository_id, source_path, display_name,
            extension, title, file_hash, parser, parser_version,
            revision_id, status, active, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, "scope", "scope", "C:/fixture-root/source.txt", "source.txt",
             ".txt", "fixture", "hash", "stdlib-text", "test", "rev-1", "ok", 1, 1, 1),
        )
        conn.execute("""INSERT INTO document_chunks(
            chunk_id, source_id, revision_id, scope_id, repository_id,
            start_anchor, end_anchor, chunk_kind, title, chunk_text,
            embedding_text, content_hash, embedding_claim_id, token_estimate,
            active, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("chunk-visible", source_id, "rev-1", "scope", "scope",
             "heading:1", "heading:1", "semantic", "fixture", "safe text",
             "safe text", content_hash, "", 2, 1, 1),
        )
        conn.commit()
        provider = Provider(conn)
        result = mod.embed_pending_documents(provider, {})
        linked = conn.execute(
            "SELECT embedding_claim_id FROM document_chunks WHERE chunk_id='chunk-visible'"
        ).fetchone()[0]
        conn.close()
        assert result["reused"] == 1 and result["created"] == 0
        assert linked == "c_visible"
        assert provider.evidence == []


def test_owner_embedding_repairs_archived_link_but_not_foreign_scope(tmp_path) -> None:
    """A live chunk cannot keep an archived claim after an authorized repair."""
    conn = sqlite3.connect(str(tmp_path / "graph.sqlite3"))
    conn.row_factory = sqlite3.Row
    try:
        mod.install_document_graph_schema(conn)
        conn.execute("""CREATE TABLE claims(
            id TEXT, topic TEXT, status TEXT, evidence TEXT, updated_at INTEGER,
            visibility_scope TEXT, origin_bot_id TEXT, origin_chat_hash TEXT,
            origin_session_id TEXT, project_id TEXT)""")
        for suffix, scope in (("mine", "scope"), ("foreign", "other")):
            conn.execute("""INSERT INTO document_sources(
                source_id, scope_id, repository_id, source_path, display_name,
                extension, title, file_hash, parser, parser_version,
                revision_id, status, active, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("docsrc_" + suffix, scope, scope, f"C:/fixture-root/{suffix}.txt",
                 suffix + ".txt", ".txt", suffix, "hash", "stdlib-text",
                 "test", "rev-1", "ok", 1, 1, 1),
            )
            conn.execute("""INSERT INTO claims(id,topic,status,evidence,updated_at,
                visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("c_" + suffix, mod._TOPIC, "archived", "old link", 1,
                 "project", "", "", "", scope),
            )
            conn.execute("""INSERT INTO document_chunks(
                chunk_id, source_id, revision_id, scope_id, repository_id,
                start_anchor, end_anchor, chunk_kind, title, chunk_text,
                embedding_text, content_hash, embedding_claim_id, token_estimate,
                active, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("chunk-" + suffix, "docsrc_" + suffix, "rev-1", scope, scope,
                 "heading:1", "heading:1", "semantic", suffix, "safe excerpt",
                 "safe excerpt", suffix + "hash", "c_" + suffix, 2, 1, 1),
            )
        conn.commit()

        class CreatingProvider(Provider):
            def _add_claim(self, _claim: str, **kwargs) -> str:
                self.conn.execute("""INSERT INTO claims(id,topic,status,evidence,updated_at,
                    visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    ("c_replacement", kwargs["topic"], "active", kwargs["evidence"],
                     2, kwargs["visibility_scope"], "", "", "", kwargs["project_id"]),
                )
                return "c_replacement"

        provider = CreatingProvider(conn)
        fts_before = conn.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[0]
        result = mod.embed_pending_documents(provider, {})
        owner_link = conn.execute(
            "SELECT embedding_claim_id FROM document_chunks WHERE chunk_id='chunk-mine'"
        ).fetchone()[0]
        foreign_link = conn.execute(
            "SELECT embedding_claim_id FROM document_chunks WHERE chunk_id='chunk-foreign'"
        ).fetchone()[0]
        fts_after = conn.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[0]
        assert result["pending_before"] == 1 and result["processed"] == 1
        assert result["created"] == 1 and result["failed"] == 0
        assert owner_link == "c_replacement" and foreign_link == "c_foreign"
        assert fts_after == fts_before
    finally:
        conn.close()


if __name__ == "__main__":
    test_embedding_evidence_uses_safe_refs_not_token_like_provenance()
    print("PASS test_embedding_evidence_uses_safe_refs_not_token_like_provenance")
