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

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.evidence: list[str] = []

    def _connect(self) -> sqlite3.Connection:
        return self.conn

    def _add_claim(self, _claim: str, **kwargs) -> str:
        self.evidence.append(str(kwargs["evidence"]))
        return "c_document_embedding_test"


def test_embedding_evidence_uses_safe_refs_not_token_like_provenance() -> None:
    source_id = "docsrc_" + "a" * 24
    revision_id = "docrev_" + "c" * 28
    content_hash = "b" * 64
    with tempfile.TemporaryDirectory(prefix="mw-doc-evidence-") as tmp:
        conn = sqlite3.connect(str(Path(tmp) / "graph.sqlite3"))
        conn.row_factory = sqlite3.Row
        mod.install_document_graph_schema(conn)
        conn.execute("CREATE TABLE claims(id TEXT, topic TEXT, status TEXT, evidence TEXT, updated_at INTEGER)")
        conn.execute(
            """INSERT INTO document_sources(
                source_id, scope_id, repository_id, source_path, display_name, extension, title, file_hash,
                parser, parser_version, revision_id, status, active, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_id, "scope", "scope", "C:/Users/Kekl/AppData/Local/hermes/documents/session.md",
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


if __name__ == "__main__":
    test_embedding_evidence_uses_safe_refs_not_token_like_provenance()
    print("PASS test_embedding_evidence_uses_safe_refs_not_token_like_provenance")
