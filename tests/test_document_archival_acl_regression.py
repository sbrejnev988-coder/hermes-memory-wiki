"""Document retirement must not archive a claim hidden from the acting provider."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


@pytest.fixture
def graph(tmp_path, monkeypatch):
    # Entire provider (including the real claim ACL and index triggers) uses a
    # disposable home. Semantic workers are disabled; Qdrant is never contacted.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_ROOTS", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_DOCUMENT_CACHE_DIR", raising=False)
    monkeypatch.delenv("HERMES_DOCUMENT_CACHE_DIR", raising=False)
    name = "mw_document_archival_acl_fixture"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    plugin = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, plugin)
    spec.loader.exec_module(plugin)
    doc = importlib.import_module(f"{name}.document_knowledge_graph")
    provider = plugin.MemoryWikiProvider()
    provider.initialize(
        "owner-session", hermes_home=str(tmp_path), bot_id="owner-bot", project_id="project-a"
    )
    conn = provider._connect()
    assert conn.execute("""SELECT 1 FROM sqlite_master
                           WHERE name='trg_claims_deactivate_indexes'""").fetchone()

    def extract(snapshot, _args):
        data = snapshot.read_bytes()
        return {
            "file_name": snapshot.name, "extension": ".txt", "mime_type": "text/plain",
            "title": "synthetic", "file_hash": hashlib.sha256(data).hexdigest(),
            "parser": "fixture", "parser_version": "1", "status": "ok",
            "units": [{"anchor": "paragraph:1", "kind": "paragraph",
                       "text": ("The project-a operations manual specifies a daily backup at "
                                "09:00 UTC, a 21-day retention period, and verification "
                                "by the site reliability team before deployment.")}],
            "edges": [], "metadata": {}, "warnings": [],
        }

    monkeypatch.setattr(doc, "_extract", extract)
    document = tmp_path / "cache" / "documents" / "source.txt"
    document.parent.mkdir(parents=True)
    document.write_text("original revision", encoding="utf-8")
    ingested = doc.ingest_document(provider, {"path": str(document), "embed": False})
    source_id, revision_id = ingested["source_id"], ingested["revision_id"]
    assert ingested["chunks"] == 1
    ids = {
        "foreign_private": "fixture_foreign_private",
        "foreign_project": "fixture_foreign_project",
        "own_bot": "fixture_own_bot",
        "shared_project": "fixture_shared_project",
    }
    specs = [
        (ids["foreign_private"], "private", "other-bot", "other-session", ""),
        (ids["foreign_project"], "project", "other-bot", "", "project-b"),
        (ids["own_bot"], "bot", "owner-bot", "owner-session", ""),
        (ids["shared_project"], "project", "other-bot", "", "project-a"),
    ]
    with conn:
        # Exercise the real FTS/outbox/target lifecycle trigger on archival.
        conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        for claim_id, visibility, bot, session, project in specs:
            text = f"Synthetic indexed content for {claim_id}."
            suffix = "own_bot" if claim_id == ids["own_bot"] else "shared_project"
            legitimate = claim_id in (ids["own_bot"], ids["shared_project"])
            evidence = (
                "document_chunk_ref:" + doc._evidence_ref(f"{source_id}\0hash-{suffix}")
                + "; source_ref:" + doc._evidence_ref(source_id)
                + "; revision_ref:" + doc._evidence_ref(revision_id)
            ) if legitimate else ""
            conn.execute(
                """INSERT INTO claims(
                    id,claim,topic,status,hash,created_at,updated_at,freshness_at,source,evidence,
                    visibility_scope,origin_bot_id,origin_session_id,project_id
                ) VALUES(?,?,?,'active',?,1,1,1,?,?,?,?,?,?)""",
                (claim_id, text, doc._TOPIC, f"hash-{claim_id}",
                 "artifact:document-index" if legitimate else "", evidence,
                 visibility, bot, session, project),
            )
            conn.execute(
                """INSERT INTO claims_fts(id,claim,normalized,topic,evidence,search_text)
                   VALUES(?,?,?,?,?,?)""",
                (claim_id, text, text, doc._TOPIC, "", text),
            )
            conn.execute(
                """INSERT INTO claim_vector_targets(
                    claim_id,endpoint,collection,vector_target_hash,manifest_hash,
                    status,indexed_at,updated_at
                ) VALUES(?,?,?,?,?,'active',1,1)""",
                (claim_id, "http://127.0.0.1:6333", "synthetic_claims",
                 f"vector-{claim_id}", "synthetic-manifest"),
            )
        # One legitimate document chunk is cross-linked to a private foreign
        # claim; the remaining links have bot/project authorization.
        conn.execute(
            "UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=? AND active=1",
            (ids["foreign_private"], source_id),
        )
        for suffix in ("foreign_project", "own_bot", "shared_project"):
            conn.execute(
                """INSERT INTO document_chunks(
                    chunk_id,source_id,revision_id,scope_id,repository_id,
                    content_hash,embedding_claim_id,active,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (f"fixture-{suffix}", source_id, revision_id, "project-a", "project-a",
                 f"hash-{suffix}", ids[suffix], 1, 1),
            )
    assert not provider._claim_visible(conn.execute(
        "SELECT visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id "
        "FROM claims WHERE id=?", (ids["foreign_private"],)
    ).fetchone())
    assert provider._claim_visible(conn.execute(
        "SELECT visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id "
        "FROM claims WHERE id=?", (ids["shared_project"],)
    ).fetchone())
    try:
        yield doc, provider, document, source_id, ids
    finally:
        if provider._conn is not None:
            provider._conn.close()


@pytest.mark.parametrize("operation", ["delete", "rewrite"])
def test_retiring_accessible_document_preserves_foreign_claim_indexes(graph, operation):
    doc, provider, document, source_id, ids = graph
    conn = provider._connect()
    foreign_ids = (ids["foreign_private"], ids["foreign_project"])
    before = {
        cid: (
            tuple(conn.execute("SELECT * FROM claims_fts WHERE id=?", (cid,)).fetchone()),
            tuple(conn.execute(
                "SELECT status,indexed_at,updated_at FROM claim_vector_targets WHERE claim_id=?",
                (cid,),
            ).fetchone()),
        )
        for cid in foreign_ids
    }

    if operation == "delete":
        result = doc.delete_document(provider, {"source_id": source_id})
    else:
        document.write_text("revised content", encoding="utf-8")
        result = doc.ingest_document(provider, {"path": str(document), "embed": False})

    assert result["archived_claims"] == 2
    for cid in foreign_ids:
        assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "active"
        assert (
            tuple(conn.execute("SELECT * FROM claims_fts WHERE id=?", (cid,)).fetchone()),
            tuple(conn.execute(
                "SELECT status,indexed_at,updated_at FROM claim_vector_targets WHERE claim_id=?",
                (cid,),
            ).fetchone()),
        ) == before[cid]
        assert conn.execute(
            "SELECT 1 FROM index_outbox WHERE operation='delete' AND object_id=?", (cid,)
        ).fetchone() is None
    for cid in (ids["own_bot"], ids["shared_project"]):
        assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "archived"
        assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (cid,)).fetchone() is None
        assert conn.execute(
            "SELECT status FROM claim_vector_targets WHERE claim_id=?", (cid,)
        ).fetchone()[0] == "delete_pending"
        assert conn.execute(
            "SELECT 1 FROM index_outbox WHERE operation='delete' AND object_id=?", (cid,)
        ).fetchone() is not None


def test_delete_does_not_archive_global_claim_linked_by_foreign_id(graph):
    doc, provider, _document, source_id, ids = graph
    conn = provider._connect()
    victim = "fixture_global_victim"
    # This looks like a document embedding, but its provenance belongs to a
    # different document. Only the link ID points to the accessible source.
    evidence = (
        "document_chunk_ref:" + doc._evidence_ref("another-source\0different-content")
        + "; source_ref:" + doc._evidence_ref("another-source")
        + "; revision_ref:" + doc._evidence_ref("another-revision")
    )
    with conn:
        conn.execute(
            """INSERT INTO claims(id,claim,topic,status,hash,created_at,updated_at,
                                  freshness_at,source,evidence,visibility_scope,origin_bot_id)
               VALUES(?,?,?,'active',?,1,1,1,'artifact:document-index',?,'global','other-bot')""",
            (victim, "Unrelated global document claim", doc._TOPIC,
             "hash-global-victim", evidence),
        )
        conn.execute(
            """INSERT INTO claims_fts(id,claim,normalized,topic,evidence,search_text)
               VALUES(?,?,?,?,?,?)""",
            (victim, "Unrelated global document claim", "Unrelated global document claim",
             doc._TOPIC, evidence, "Unrelated global document claim"),
        )
        conn.execute(
            "UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=? AND embedding_claim_id=?",
            (victim, source_id, ids["foreign_private"]),
        )
    assert provider._claim_visible(conn.execute(
        "SELECT visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id "
        "FROM claims WHERE id=?", (victim,)
    ).fetchone())

    result = doc.delete_document(provider, {"source_id": source_id})

    assert conn.execute("SELECT status FROM claims WHERE id=?", (victim,)).fetchone()[0] == "active"
    assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (victim,)).fetchone()
    assert conn.execute(
        "SELECT 1 FROM index_outbox WHERE operation='delete' AND object_id=?", (victim,)
    ).fetchone() is None
    assert result["archived_claims"] == 2


@pytest.mark.parametrize("operation", ["rewrite", "scope_change"])
def test_reingest_does_not_archive_same_project_foreign_bot_claim(graph, monkeypatch, operation):
    doc, provider, document, source_id, ids = graph
    conn = provider._connect()
    victim = "fixture_same_project_victim"
    # A project claim from the other bot is readable, but it cites a different
    # source and chunk. Updating the link cannot transfer claim ownership.
    evidence = (
        "document_chunk_ref:" + doc._evidence_ref("other-source\0other-hash")
        + "; source_ref:" + doc._evidence_ref("other-source")
        + "; revision_ref:" + doc._evidence_ref("other-revision")
    )
    with conn:
        conn.execute(
            """INSERT INTO claims(id,claim,topic,status,hash,created_at,updated_at,
                                  freshness_at,source,evidence,visibility_scope,
                                  origin_bot_id,project_id)
               VALUES(?,?,?,'active',?,1,1,1,'artifact:document-index',?,
                      'project','other-bot','project-a')""",
            (victim, "Other bot's document claim", doc._TOPIC,
             "hash-project-victim", evidence),
        )
        conn.execute(
            "UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=? AND embedding_claim_id=?",
            (victim, source_id, ids["foreign_private"]),
        )
    assert provider._claim_visible(conn.execute(
        "SELECT visibility_scope,origin_bot_id,origin_chat_hash,origin_session_id,project_id "
        "FROM claims WHERE id=?", (victim,)
    ).fetchone())

    if operation == "rewrite":
        document.write_text("changed revision", encoding="utf-8")
        result = doc.ingest_document(provider, {"path": str(document), "embed": False})
    else:
        monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE", "1")
        monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION", "1")
        result = doc.ingest_document(provider, {
            "path": str(document), "scope_id": "project-b", "repository_id": "project-b",
            "embed": False,
        })
        assert result["status"] == "scope_updated"
        assert conn.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE source_id=? AND active=1 "
            "AND embedding_claim_id<>''", (source_id,),
        ).fetchone()[0] == 0

    assert result["archived_claims"] == 2
    assert conn.execute("SELECT status FROM claims WHERE id=?", (victim,)).fetchone()[0] == "active"
    assert conn.execute(
        "SELECT 1 FROM index_outbox WHERE operation='delete' AND object_id=?", (victim,)
    ).fetchone() is None
    assert conn.execute("SELECT status FROM claims WHERE id=?", (ids["shared_project"],)).fetchone()[0] == "archived"


@pytest.mark.parametrize("operation", ["delete", "rewrite", "scope_change"])
def test_retiring_genuine_global_document_claim_archives_without_active_links(graph, monkeypatch, operation):
    doc, provider, document, source_id, ids = graph
    conn = provider._connect()
    claim_id = ids["own_bot"]
    # The same provenance was generated for this chunk; global claims remain
    # eligible even if another bot authored them.
    with conn:
        conn.execute(
            "UPDATE claims SET visibility_scope='global',origin_bot_id='other-bot' WHERE id=?",
            (claim_id,),
        )
    if operation == "delete":
        result = doc.delete_document(provider, {"source_id": source_id})
    elif operation == "rewrite":
        document.write_text("changed revision", encoding="utf-8")
        result = doc.ingest_document(provider, {"path": str(document), "embed": False})
    else:
        monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE", "1")
        monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION", "1")
        result = doc.ingest_document(provider, {
            "path": str(document), "scope_id": "project-b", "repository_id": "project-b",
            "embed": False,
        })
        assert result["status"] == "scope_updated"

    assert result["archived_claims"] == 2
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "archived"
    assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM document_chunks WHERE embedding_claim_id=? AND active=1", (claim_id,)
    ).fetchone() is None


def test_reused_project_claim_with_older_revision_provenance_archives_on_last_link(graph):
    doc, provider, _document, source_id, ids = graph
    conn = provider._connect()
    claim_id = ids["shared_project"]
    old_revision = "docrev_historical_fixture"
    content_hash = "hash-shared_project"
    with conn:
        conn.execute(
            """INSERT INTO document_revisions(revision_id,source_id,file_hash,parser,
                                               parser_version,status,created_at)
               VALUES(?,?,?,'fixture','1','superseded',1)""",
            (old_revision, source_id, "historical-file-hash"),
        )
        conn.execute(
            """INSERT INTO document_chunks(chunk_id,source_id,revision_id,scope_id,
                                            repository_id,content_hash,embedding_claim_id,
                                            active,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            ("historical-shared", source_id, old_revision, "project-a", "project-a",
             content_hash, claim_id, 0, 1),
        )
        conn.execute(
            "UPDATE claims SET evidence=? WHERE id=?",
            ("document_chunk_ref:" + doc._evidence_ref(f"{source_id}\0{content_hash}")
             + "; source_ref:" + doc._evidence_ref(source_id)
             + "; revision_ref:" + doc._evidence_ref(old_revision), claim_id),
        )
    result = doc.delete_document(provider, {"source_id": source_id})
    assert result["archived_claims"] == 2
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "archived"
    assert conn.execute(
        "SELECT 1 FROM document_chunks WHERE embedding_claim_id=? AND active=1", (claim_id,)
    ).fetchone() is None


@pytest.mark.parametrize("mismatch", [
    "chunk", "source", "revision", "topic", "claim_source", "extra_evidence",
])
def test_global_claim_requires_complete_exact_document_identity(graph, mismatch):
    doc, provider, _document, source_id, ids = graph
    conn = provider._connect()
    linked = conn.execute(
        "SELECT content_hash,revision_id FROM document_chunks WHERE source_id=? "
        "AND embedding_claim_id=?", (source_id, ids["foreign_private"]),
    ).fetchone()
    chunk_key = doc._evidence_ref(
        f"{source_id}\0{linked['content_hash']}" if mismatch != "chunk" else
        f"{source_id}\0different-content"
    )
    source_key = doc._evidence_ref(source_id if mismatch != "source" else "other-source")
    revision_key = doc._evidence_ref(
        linked["revision_id"] if mismatch != "revision" else "other-revision"
    )
    evidence = (
        f"document_chunk_ref:{chunk_key}; source_ref:{source_key}; "
        f"revision_ref:{revision_key}"
    )
    if mismatch == "extra_evidence":
        evidence += "; arbitrary:true"
    victim = "fixture_identity_mismatch"
    with conn:
        conn.execute(
            """INSERT INTO claims(id,claim,topic,status,hash,created_at,updated_at,
                                  freshness_at,source,evidence,visibility_scope)
               VALUES(?,?,?,'active',?,1,1,1,?,?,'global')""",
            (victim, "Linked global claim", "not-document-intelligence" if mismatch == "topic"
             else doc._TOPIC, "hash-identity-mismatch",
             "tool" if mismatch == "claim_source" else "artifact:document-index", evidence),
        )
        conn.execute(
            "UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=? AND embedding_claim_id=?",
            (victim, source_id, ids["foreign_private"]),
        )
    result = doc.delete_document(provider, {"source_id": source_id})
    assert conn.execute("SELECT status FROM claims WHERE id=?", (victim,)).fetchone()[0] == "active"
    assert result["archived_claims"] == 2


def test_claim_created_by_embed_pending_documents_archives_on_delete(graph):
    doc, provider, _document, source_id, ids = graph
    conn = provider._connect()
    # Restore the real ingested chunk to pending; unlike synthetic links, this
    # path exercises the provider's claim creation and evidence serialization.
    with conn:
        conn.execute(
            "UPDATE document_chunks SET embedding_claim_id='' WHERE source_id=? "
            "AND embedding_claim_id=?", (source_id, ids["foreign_private"]),
        )
    embedded = doc.embed_pending_documents(provider, {"source_id": source_id})
    assert embedded["failed"] == 0, embedded["errors"]
    assert embedded["created"] == 1, embedded
    claim_id = conn.execute(
        "SELECT embedding_claim_id FROM document_chunks WHERE source_id=? "
        "AND content_hash NOT LIKE 'hash-%' AND active=1", (source_id,),
    ).fetchone()[0]
    assert claim_id
    result = doc.delete_document(provider, {"source_id": source_id})
    assert result["archived_claims"] == 3
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "archived"


def test_shared_document_claim_stays_active_while_another_link_is_active(graph):
    doc, provider, document, source_id, ids = graph
    conn = provider._connect()
    another_document = document.with_name("another.txt")
    another_document.write_text("another source", encoding="utf-8")
    another_source = doc.ingest_document(provider, {"path": str(another_document), "embed": False})
    with conn:
        conn.execute(
            "UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=? AND active=1",
            (ids["shared_project"], another_source["source_id"]),
        )
    result = doc.delete_document(provider, {"source_id": source_id})
    assert result["archived_claims"] == 1
    assert conn.execute("SELECT status FROM claims WHERE id=?", (ids["own_bot"],)).fetchone()[0] == "archived"
    assert conn.execute("SELECT status FROM claims WHERE id=?", (ids["shared_project"],)).fetchone()[0] == "active"
    assert conn.execute(
        "SELECT 1 FROM document_chunks WHERE embedding_claim_id=? AND active=1",
        (ids["shared_project"],),
    ).fetchone() is not None
