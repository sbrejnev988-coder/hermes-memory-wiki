"""Fail-closed document embedding regressions on an isolated synthetic provider."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


@pytest.fixture
def graph(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    name = f"mw_embed_pending_safety_{tmp_path.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, plugin)
    spec.loader.exec_module(plugin)
    doc = importlib.import_module(f"{name}.document_knowledge_graph")
    provider = plugin.MemoryWikiProvider()
    provider.initialize("synthetic-session", hermes_home=str(tmp_path),
                        bot_id="synthetic-bot", project_id="default")
    try:
        yield doc, provider
    finally:
        if provider._conn is not None:
            provider._conn.close()


def insert_chunk(doc, provider, *, project, source_id="docsrc_synthetic",
                 chunk_id="docchunk_synthetic", text=None, link=""):
    conn = provider._connect()
    doc.install_document_graph_schema(conn)
    text = text or ("The synthetic operations manual specifies daily backups at 09:00 UTC "
                    "and requires a verification checkpoint before deployment.")
    with conn:
        conn.execute("""INSERT INTO document_sources(
            source_id,scope_id,repository_id,source_path,display_name,extension,title,
            file_hash,parser,parser_version,revision_id,status,active,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, project, project, f"C:/fixture/{source_id}.txt", "fixture.txt",
             ".txt", "synthetic", "hash", "fixture", "test", "revision-1", "ok", 1, 1, 1),
        )
        conn.execute("""INSERT INTO document_chunks(
            chunk_id,source_id,revision_id,scope_id,repository_id,start_anchor,end_anchor,
            chunk_kind,title,chunk_text,embedding_text,content_hash,embedding_claim_id,
            token_estimate,active,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (chunk_id, source_id, "revision-1", project, project, "paragraph:1",
             "paragraph:1", "semantic", "synthetic", text, text,
             "content-hash-1", link, 20, 1, 1),
        )
    return text


def test_document_access_override_cannot_create_invisible_project_claim(graph, monkeypatch):
    doc, provider = graph
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", "hermes-state-db")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID", "hermes-state-db")
    insert_chunk(doc, provider, project="hermes-state-db")
    conn = provider._connect()

    result = doc.embed_pending_documents(provider, {})

    assert result["pending_before"] == result["pending_after"] == 1
    assert result["created"] == result["reused"] == 0
    assert result["skipped_reasons"] == {"project_claim_not_visible": 1}
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE source='artifact:document-index'").fetchone()[0] == 0
    assert conn.execute("SELECT embedding_claim_id FROM document_chunks").fetchone()[0] == ""


def test_archived_link_is_not_repaired_by_reviving_claim(graph):
    doc, provider = graph
    text = ("The synthetic operations manual specifies daily backups at 09:00 UTC "
            "and requires a verification checkpoint before deployment.")
    claim_id = provider._add_claim(
        text, topic=doc._TOPIC, source="artifact:document-index",
        visibility_scope="project", project_id="default",
        evidence="synthetic archived document claim",
    )
    assert claim_id.startswith("c_")
    conn = provider._connect()
    with conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (claim_id,))
    insert_chunk(doc, provider, project="default", text=text, link=claim_id)

    result = doc.embed_pending_documents(provider, {})

    assert result["pending_before"] == result["pending_after"] == 1
    assert result["created"] == result["reused"] == 0
    assert result["skipped_reasons"] == {"linked_claim_inactive": 1}
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "archived"
    assert conn.execute("SELECT embedding_claim_id FROM document_chunks").fetchone()[0] == claim_id


def test_unlinked_chunk_does_not_revive_archived_claim_with_same_text(graph):
    doc, provider = graph
    text = insert_chunk(doc, provider, project="default")
    claim_id = provider._add_claim(
        text, topic=doc._TOPIC, source="artifact:document-index",
        visibility_scope="project", project_id="default",
        evidence="different synthetic source, not this chunk",
    )
    assert claim_id.startswith("c_")
    conn = provider._connect()
    with conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (claim_id,))

    result = doc.embed_pending_documents(provider, {})

    assert result["pending_before"] == result["pending_after"] == 1
    assert result["created"] == result["reused"] == result["failed"] == 0
    assert result["skipped_reasons"] == {"archived_hash_collision": 1}
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "archived"
    assert conn.execute("SELECT embedding_claim_id FROM document_chunks").fetchone()[0] == ""


def test_removed_link_is_replaced_for_matching_project(graph):
    doc, provider = graph
    insert_chunk(doc, provider, project="default", link="c_removed")
    conn = provider._connect()

    result = doc.embed_pending_documents(provider, {})

    claim_id = conn.execute("SELECT embedding_claim_id FROM document_chunks").fetchone()[0]
    assert result["pending_before"] == 1 and result["pending_after"] == 0
    assert result["created"] == 1 and result["skipped_reasons"] == {}
    assert claim_id != "c_removed"
    claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    assert claim["status"] == "active" and provider._claim_visible(claim)


def test_owned_connector_keeps_bot_claim_visible_when_document_project_differs(graph, monkeypatch):
    doc, provider = graph
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID", "hermes-state-db")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID", "hermes-state-db")
    insert_chunk(doc, provider, project="hermes-state-db")
    conn = provider._connect()
    with conn:
        conn.execute("""INSERT INTO external_sources(
            source_key,owner_bot_id,source_type,display_uri,scope_id,repository_id,
            document_source_id,revision_key,content_hash,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("synthetic-owned", provider.bot_id, "record", "urn:fixture:owned",
             "hermes-state-db", "hermes-state-db", "docsrc_synthetic", "revision-1", "hash", 1, 1),
        )

    result = doc.embed_pending_documents(provider, {})

    claim_id = conn.execute("SELECT embedding_claim_id FROM document_chunks").fetchone()[0]
    claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    assert result["pending_before"] == 1 and result["pending_after"] == 0
    assert result["created"] == 1 and result["skipped_reasons"] == {}
    assert claim["visibility_scope"] == "bot" and provider._claim_visible(claim)
