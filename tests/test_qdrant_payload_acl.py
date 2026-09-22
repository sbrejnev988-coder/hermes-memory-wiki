from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_provider(module, tmp_path: Path):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "chat-a", hermes_home=str(tmp_path), bot_id="bot-a", project_id="project-a",
    )
    return provider


def add_chat_claim(provider) -> str:
    value = provider._add_claim(
        "Atlas gateway service uses port 5678 for local requests.",
        topic="server",
        source="memory_tool:test",
        confidence=0.9,
        salience=0.9,
        visibility_scope="chat",
    )
    assert value.startswith("c_")
    return value


def allow_historical_targets(module, tmp_path: Path, collections: str, endpoints: str = "") -> None:
    """Declare synthetic legacy targets as owned by this isolated test profile."""
    (tmp_path / ".env").write_text(
        f"MEMORY_WIKI_QDRANT_URL={module.QDRANT_URL}\n"
        f"MEMORY_WIKI_QDRANT_COLLECTION={module.QDRANT_COLLECTION}\n"
        f"MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION={module.EPISODIC_QDRANT_COLLECTION}\n"
        f"MEMORY_WIKI_QDRANT_ALIAS={module.QDRANT_ALIAS}\n"
        f"MEMORY_WIKI_QDRANT_HISTORICAL_COLLECTIONS={collections}\n"
        f"MEMORY_WIKI_QDRANT_HISTORICAL_ENDPOINTS={endpoints}\n",
        encoding="utf-8",
    )


def test_initialize_preserves_populated_alias_when_manifest_target_changes(
    tmp_path, monkeypatch,
):
    module = load_module("memory_wiki_qdrant_bootstrap_alias_guard", tmp_path, monkeypatch)
    module.SEMANTIC_ENABLED = True
    alias = {"target": "memory_wiki_claims_v7_populated"}
    ensured = []
    switched = []
    monkeypatch.setattr(
        module, "_physical_collection_name", lambda manifest=None: "memory_wiki_claims_new_empty",
    )
    monkeypatch.setattr(
        module, "_ensure_collection",
        lambda collection=None: ensured.append(collection) or True,
    )
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda refresh=False: True)
    monkeypatch.setattr(
        module, "_qdrant_req",
        lambda method, path, body=None, timeout=10.0: {
            "status": "ok",
            "result": {"aliases": [{
                "alias_name": module.QDRANT_ALIAS,
                "collection_name": alias["target"],
            }]},
        } if method == "GET" and path == "/aliases" else None,
    )
    monkeypatch.setattr(
        module, "_switch_alias",
        lambda collection: switched.append(collection) or alias.update(target=collection) is None,
    )
    monkeypatch.setattr(
        module, "_migrate_and_resume_claim_vector_targets",
        lambda _path: {"seeded": 0, "queued": 0, "collections": 1},
    )
    monkeypatch.setattr(module, "_start_outbox_worker", lambda _path: None)
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda _path: None)

    provider = module.MemoryWikiProvider()
    provider.initialize(
        "chat-a", hermes_home=str(tmp_path), bot_id="bot-a", project_id="project-a",
    )
    assert ensured == ["memory_wiki_claims_new_empty"]
    assert switched == []
    assert alias["target"] == "memory_wiki_claims_v7_populated"


def test_canonical_payload_contains_hash_and_complete_acl(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_payload_unit", tmp_path, monkeypatch)
    payload = module._qdrant_claim_payload(
        "c_123", "durable claim text", {
            "topic": "server", "memory_revision": 7, "updated_at": 11,
            "visibility_scope": "private", "origin_bot_id": "bot-a",
            "origin_session_id": "chat-a", "origin_chat_hash": "hash-a",
            "project_id": "project-a", "event_at": 13,
        }, manifest_hash="manifest-a",
    )
    assert payload["payload_version"] == module.QDRANT_CLAIM_PAYLOAD_VERSION
    assert payload["claim_id"] == payload["id"] == "c_123"
    assert payload["vector_text_hash"] == module.sha("durable claim text")
    assert payload["origin_session_id"] == "chat-a"
    assert payload["visibility_scope"] == "private"
    assert payload["manifest_hash"] == "manifest-a"

    missing_scope = module._qdrant_claim_payload(
        "c_legacy", "legacy text", {"topic": "server"},
    )
    assert missing_scope["visibility_scope"] == "invalid"
    assert missing_scope["visibility_scope"] != "global"


def test_reconciliation_rejects_correct_hash_with_legacy_acl_payload(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_reconcile_contract", tmp_path, monkeypatch)
    canonical = module._qdrant_claim_payload(
        "c_legacy", "same vector text", {
            "topic": "server", "memory_revision": 4, "updated_at": 10,
            "visibility_scope": "chat", "origin_bot_id": "bot-a",
            "origin_session_id": "chat-a", "origin_chat_hash": "hash-a",
            "project_id": "", "event_at": 12,
        },
    )
    legacy = dict(canonical)
    legacy.pop("payload_version")
    legacy.pop("manifest_hash")
    legacy.pop("origin_chat_hash")

    def request(_method, _path, _body=None, timeout=10.0):
        return {"result": {"points": [
            {"id": "opaque", "payload": legacy},
        ], "next_page_offset": None}}

    monkeypatch.setattr(module, "_qdrant_req", request)
    state = module._qdrant_claim_state("claims")
    assert state is not None
    actual = state["c_legacy"]
    expected = module._qdrant_claim_reconciliation_state(canonical)
    assert actual["vector_text_hash"] == expected["vector_text_hash"]
    assert actual["payload_version"] == 0
    assert actual != expected


def test_reindex_repairs_matching_vector_with_outdated_payload_contract(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_reconcile_repair", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    row = provider._connect().execute(
        "SELECT * FROM claims WHERE id=?", (claim_id,),
    ).fetchone()
    manifest_hash = module._manifest_hash(module._embedding_manifest())
    target = module._physical_collection_name(module._embedding_manifest())
    legacy = module._qdrant_claim_payload(
        claim_id, str(row["normalized_claim"]), row, manifest_hash=manifest_hash,
    )
    legacy.pop("payload_version")
    legacy.pop("origin_chat_hash")
    points = {target: {claim_id: legacy}}
    upserts = []

    module.SEMANTIC_ENABLED = True
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_ensure_collection", lambda collection=None: True)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda: True)
    monkeypatch.setattr(module, "_qdrant_alias_target", lambda alias=module.QDRANT_ALIAS: target)
    monkeypatch.setattr(module, "_switch_alias", lambda collection: collection == target)
    monkeypatch.setattr(module, "_qdrant_count", lambda collection=None: len(points.get(collection, {})))
    monkeypatch.setattr(module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)
    monkeypatch.setattr(
        module, "_qdrant_claim_state",
        lambda collection, max_points=200000: {
            cid: module._qdrant_claim_reconciliation_state(payload)
            for cid, payload in points.get(collection, {}).items()
        },
    )

    def upsert(cid, _vector, payload, collection=None):
        upserts.append(cid)
        points.setdefault(collection, {})[cid] = dict(payload)
        return True

    monkeypatch.setattr(module, "_qdrant_upsert", upsert)
    result = provider._reindex()
    assert result["status"] == "completed"
    assert upserts == [claim_id]
    repaired = points[target][claim_id]
    assert repaired["payload_version"] == module.QDRANT_CLAIM_PAYLOAD_VERSION
    assert repaired["visibility_scope"] == "chat"
    assert repaired["origin_chat_hash"] == row["origin_chat_hash"]


def test_reindex_fast_path_completes_matching_running_job(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_fast_path_job", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    manifest = module._embedding_manifest()
    manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    stored_manifest = dict(manifest)
    stored_manifest["query_instruction_hash"] = "different-but-ignored-by-hash"
    stored_manifest_json = json.dumps(stored_manifest, ensure_ascii=False, sort_keys=True)
    assert stored_manifest_json != manifest_json
    assert module._manifest_hash(stored_manifest) == module._manifest_hash(manifest)
    manifest_hash = module._manifest_hash(manifest)
    target = module._physical_collection_name(manifest)
    job_id = f"reindex_{manifest_hash}_{module.hashlib.sha256(target.encode()).hexdigest()[:8]}"
    row = provider._connect().execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    expected = module._expected_qdrant_claim_state(
        claim_id, row["normalized_claim"], row, manifest_hash,
    )
    with provider._connect() as conn:
        conn.execute(
            """INSERT INTO reindex_jobs(id,source_collection,target_collection,
                   manifest_json,total_count,processed_count,failed_count,status,
                   started_at,updated_at,failed_ids_json,last_error)
               VALUES(?,?,?, ?,1,0,1,'running',1,1,'["synthetic"]','retry')""",
            (job_id, "old-target", target, stored_manifest_json),
        )
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_ensure_collection", lambda collection=None: True)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda: True)
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: target)
    monkeypatch.setattr(module, "_qdrant_count", lambda collection=None: 1)
    actual = {"state": expected}
    monkeypatch.setattr(
        module, "_qdrant_claim_state",
        lambda collection: {claim_id: actual["state"]},
    )
    stale_payload = module._qdrant_claim_payload(
        claim_id, row["normalized_claim"], row, manifest_hash=manifest_hash,
    )
    stale_payload["topic"] = "synthetic-stale-topic"
    actual["state"] = module._qdrant_claim_reconciliation_state(stale_payload)
    monkeypatch.setattr(module, "_embed_document", lambda _text: None)
    incomplete = provider._reindex(limit=1)
    assert incomplete["status"] != "already_complete"
    assert provider._connect().execute(
        "SELECT status FROM reindex_jobs WHERE id=?", (job_id,),
    ).fetchone()[0] == "running"
    actual["state"] = expected
    result = provider._reindex()
    assert result["status"] == "already_complete"
    job = provider._connect().execute(
        "SELECT status,processed_count,total_count,failed_count,failed_ids_json,last_error "
        "FROM reindex_jobs WHERE id=?", (job_id,),
    ).fetchone()
    assert tuple(job) == ("completed", 1, 1, 0, "[]", "")


def test_qdrant_query_sends_exact_visibility_filter(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_filter_unit", tmp_path, monkeypatch)
    query_filter = module._qdrant_visibility_filter(
        bot_id="bot-a", chat_hash="hash-a", session_id="chat-a",
        project_id="project-a", include_all_projects=False,
    )
    captured = {}

    def request(method, path, body=None, timeout=10.0):
        captured.update({"method": method, "path": path, "body": body})
        return {"result": {"points": [{"id": "fallback", "score": 0.8,
                                         "payload": {"claim_id": "c_visible"}}]}}

    monkeypatch.setattr(module, "_qdrant_req", request)
    monkeypatch.setattr(module, "_active_collection_name", lambda: "claims-active")
    matches = module._qdrant_search(
        [0.0] * module.QDRANT_VECTOR_SIZE, 5, query_filter=query_filter,
    )
    assert matches == [("c_visible", 0.8)]
    assert captured["body"]["filter"] == query_filter
    serialized = str(query_filter)
    assert "bot-a" in serialized and "hash-a" in serialized and "chat-a" in serialized
    assert "project-a" in serialized
    assert "project-b" not in serialized


def test_provider_vector_search_uses_current_consumer_acl(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_filter_wiring", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    captured = {}
    module.SEMANTIC_ENABLED = True
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_embed_query", lambda text: [0.0] * module.QDRANT_VECTOR_SIZE)

    def search(vector, limit=20, *, query_filter=None):
        captured["filter"] = query_filter
        return []

    monkeypatch.setattr(module, "_qdrant_search", search)
    provider._search(
        "Which Atlas port is current?", retrieval_mode="vector",
        record_retrieval=False, session_id="chat-a",
    )
    serialized = str(captured["filter"])
    assert "bot-a" in serialized
    assert provider._chat_hash("chat-a") in serialized
    assert "chat-a" in serialized
    assert "project-a" in serialized


def test_incremental_outbox_and_reindex_share_payload_contract(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_payload_parity", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    row = provider._connect().execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    expected_base = module._qdrant_claim_payload(
        claim_id, str(row["normalized_claim"]), row,
    )

    captured_incremental = {}
    monkeypatch.setattr(module, "_embed_document", lambda text: [0.0] * module.QDRANT_VECTOR_SIZE)

    def capture_incremental(cid, vector, payload, collection=None):
        captured_incremental.update({"id": cid, "payload": dict(payload), "collection": collection})
        return True

    monkeypatch.setattr(module, "_qdrant_upsert", capture_incremental)
    with provider._connect() as conn:
        module._outbox_enqueue("embed_and_upsert", "claim", claim_id, {
            "text": row["normalized_claim"], "topic": row["topic"],
            "collection": "incremental-collection",
            "memory_revision": row["memory_revision"], "updated_at": row["updated_at"],
            "visibility_scope": row["visibility_scope"], "origin_bot_id": row["origin_bot_id"],
            "origin_session_id": row["origin_session_id"],
            "origin_chat_hash": row["origin_chat_hash"], "project_id": row["project_id"],
            "event_at": row["event_at"],
        }, conn=conn)
    outcome = module._outbox_process(db_path=str(provider.db_path), worker_id="test-worker")
    assert outcome["ok"] == 1 and outcome["fail"] == 0
    assert captured_incremental["payload"] == expected_base

    points = {}
    switched = []
    module.SEMANTIC_ENABLED = True
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_ensure_collection", lambda collection=None: True)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda: True)
    monkeypatch.setattr(
        module, "_qdrant_alias_target",
        lambda alias=module.QDRANT_ALIAS: switched[-1] if switched else "old-collection",
    )
    monkeypatch.setattr(module, "_switch_alias", lambda collection: switched.append(collection) or True)
    monkeypatch.setattr(module, "_qdrant_count", lambda collection=None: len(points.get(collection, {})))
    monkeypatch.setattr(
        module, "_qdrant_claim_state",
        lambda collection, max_points=200000: {
            cid: module._qdrant_claim_reconciliation_state(payload)
            for cid, payload in points.get(collection, {}).items()
        },
    )

    def capture_reindex(cid, vector, payload, collection=None):
        points.setdefault(collection, {})[cid] = dict(payload)
        return True

    monkeypatch.setattr(module, "_qdrant_upsert", capture_reindex)
    result = provider._reindex(force=True)
    assert result["status"] == "completed"
    indexed = points[result["collection"]][claim_id]
    assert {key: indexed[key] for key in expected_base} == expected_base
    assert indexed["manifest_hash"]


def test_legacy_claim_job_hydrates_authoritative_text_and_acl(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_outbox_hydration", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    row = provider._connect().execute(
        "SELECT * FROM claims WHERE id=?", (claim_id,),
    ).fetchone()

    with provider._connect() as conn:
        module._outbox_enqueue("embed_and_upsert", "claim", claim_id, {
            "text": "stale attacker-controlled text",
            "collection": "claims-active",
            "visibility_scope": "global",
        }, conn=conn)

    embedded = []
    captured = {}
    monkeypatch.setattr(
        module, "_embed_document",
        lambda text: embedded.append(text) or [0.0] * module.QDRANT_VECTOR_SIZE,
    )

    def upsert(object_id, vector, payload, collection=None):
        captured.update({
            "id": object_id, "payload": dict(payload), "collection": collection,
        })
        return True

    monkeypatch.setattr(module, "_qdrant_upsert", upsert)
    outcome = module._outbox_process(
        db_path=str(provider.db_path), worker_id="hydrate-worker",
    )
    assert outcome["ok"] == 1 and outcome["fail"] == 0
    assert embedded == [str(row["normalized_claim"])]
    assert captured["id"] == claim_id
    assert captured["collection"] == "claims-active"
    assert captured["payload"]["visibility_scope"] == "chat"
    assert captured["payload"]["origin_bot_id"] == row["origin_bot_id"]
    assert captured["payload"]["origin_chat_hash"] == row["origin_chat_hash"]
    assert captured["payload"]["vector_text_hash"] == module.sha(row["normalized_claim"])
    assert captured["payload"]["manifest_hash"] == module._manifest_hash(
        module._embedding_manifest()
    )


def test_delete_scrubs_inflight_upsert_text_and_error(tmp_path, monkeypatch):
    module = load_module("memory_wiki_inflight_delete_scrub", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    sensitive = "private amber checklist body"
    with provider._connect() as conn:
        upsert_id = module._outbox_enqueue(
            "embed_and_upsert", "claim", claim_id,
            {"text": sensitive, "collection": "claims-active", "endpoint": "local"},
            conn=conn,
        )
        conn.execute(
            "UPDATE index_outbox SET status='processing',last_error=? WHERE id=?",
            (sensitive, upsert_id),
        )
        module._outbox_enqueue(
            "delete", "claim", claim_id,
            {"collection": "claims-active", "endpoint": "local"}, conn=conn,
        )
        row = conn.execute(
            "SELECT payload_json,last_error,status FROM index_outbox WHERE id=?",
            (upsert_id,),
        ).fetchone()
    assert row["status"] == "processing"
    assert sensitive not in row["payload_json"]
    assert row["last_error"] == ""
    assert json.loads(row["payload_json"]) == {
        "collection": "claims-active", "endpoint": "local",
    }


def test_inactive_or_deleted_claim_job_cleans_point_without_upsert(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_outbox_inactive", tmp_path, monkeypatch)
    allow_historical_targets(module, tmp_path, "claims-active")
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: module._physical_collection_name())
    provider = make_provider(module, tmp_path)
    inactive_id = add_chat_claim(provider)
    with provider._connect() as conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (inactive_id,))
        module._outbox_enqueue(
            "embed_and_upsert", "claim", inactive_id,
            {"text": "obsolete", "collection": "claims-active"}, conn=conn,
        )
        module._outbox_enqueue(
            "embed_and_upsert", "claim", "c_deleted",
            {"text": "deleted", "collection": "claims-active"}, conn=conn,
        )

    deleted = []
    monkeypatch.setattr(
        module, "_embed_document",
        lambda _text: (_ for _ in ()).throw(AssertionError("inactive claim was embedded")),
    )
    monkeypatch.setattr(
        module, "_qdrant_upsert",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("inactive claim was upserted")),
    )
    monkeypatch.setattr(
        module, "_qdrant_delete",
        lambda object_id, collection=None: deleted.append((object_id, collection)) or True,
    )
    outcome = module._outbox_process(
        batch_size=10, db_path=str(provider.db_path), worker_id="inactive-worker",
    )
    assert outcome["ok"] == 2 and outcome["fail"] == 0
    assert set(deleted) == {
        (inactive_id, "claims-active"), ("c_deleted", "claims-active"),
    }


def test_claim_archived_during_remote_upsert_is_immediately_deleted(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_outbox_post_upsert", tmp_path, monkeypatch)
    allow_historical_targets(module, tmp_path, "claims-active")
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: module._physical_collection_name())
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    with provider._connect() as conn:
        module._outbox_enqueue(
            "embed_and_upsert", "claim", claim_id,
            {"collection": "claims-active"}, conn=conn,
        )

    monkeypatch.setattr(
        module, "_embed_document",
        lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE,
    )
    upserts = []

    def racing_upsert(object_id, _vector, payload, collection=None):
        upserts.append((object_id, dict(payload), collection))
        with provider._connect() as conn:
            conn.execute(
                "UPDATE claims SET status='archived',memory_revision=memory_revision+1 "
                "WHERE id=?", (claim_id,),
            )
        return True

    deleted = []
    monkeypatch.setattr(module, "_qdrant_upsert", racing_upsert)
    monkeypatch.setattr(
        module, "_qdrant_delete",
        lambda object_id, collection=None: deleted.append((object_id, collection)) or True,
    )
    outcome = module._outbox_process(
        db_path=str(provider.db_path), worker_id="post-upsert-worker",
    )
    assert outcome["ok"] == 1 and outcome["fail"] == 0
    assert len(upserts) == 1
    assert deleted == [(claim_id, upserts[0][2])]


def test_versioned_reindex_then_claim_delete_removes_every_physical_copy(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_target_fanout", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    with provider._connect() as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")

    active = {"collection": ""}
    points = {}
    manifest = {"generation": "v1"}
    # Preserve a complete, deterministic contract while changing one field.
    base_manifest = {
        "manifest_version": 2, "provider": "test", "model": "test-v1",
        "dimensions": module.QDRANT_VECTOR_SIZE,
        "vector_size": module.QDRANT_VECTOR_SIZE,
        "embedding_input_max_chars": 1000,
        "query_instruction_hash": "none", "document_prefix_hash": "none",
        "document_template_version": 3, "normalization_version": 1,
    }
    monkeypatch.setattr(
        module, "_embedding_manifest",
        lambda: {**base_manifest, "model": f"test-{manifest['generation']}"},
    )
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_ensure_collection", lambda collection=None: True)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda refresh=False: True)
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: active["collection"])
    monkeypatch.setattr(module, "_qdrant_alias_target", lambda alias=module.QDRANT_ALIAS: active["collection"])
    monkeypatch.setattr(
        module, "_switch_alias",
        lambda collection: active.update(collection=collection) is None,
    )
    monkeypatch.setattr(module, "_qdrant_count", lambda collection=None: len(points.get(collection, {})))
    monkeypatch.setattr(module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)
    monkeypatch.setattr(
        module, "_qdrant_claim_state",
        lambda collection, max_points=200000: {
            cid: module._qdrant_claim_reconciliation_state(payload)
            for cid, payload in points.get(collection, {}).items()
        },
    )

    def upsert(cid, _vector, payload, collection=None):
        points.setdefault(collection, {})[cid] = dict(payload)
        return True

    def delete_target(cid, *, collection, endpoint=""):
        points.setdefault(collection, {}).pop(cid, None)
        return True

    monkeypatch.setattr(module, "_qdrant_upsert", upsert)
    monkeypatch.setattr(module, "_qdrant_delete_target", delete_target)

    first = provider._reindex()
    assert first["status"] == "completed"
    manifest["generation"] = "v2"
    second = provider._reindex()
    assert second["status"] == "completed"
    assert first["collection"] != second["collection"]
    assert claim_id in points[first["collection"]]
    assert claim_id in points[second["collection"]]
    assert provider._connect().execute(
        "SELECT count(*) FROM claim_vector_targets WHERE claim_id=? AND status='active'",
        (claim_id,),
    ).fetchone()[0] == 2

    with provider._connect() as conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id=?", (claim_id,))
    result = module._outbox_process(
        batch_size=20, db_path=str(provider.db_path), worker_id="fanout-worker",
    )
    assert result["fail"] == 0
    assert claim_id not in points[first["collection"]]
    assert claim_id not in points[second["collection"]]
    assert provider._connect().execute(
        "SELECT count(*) FROM claim_vector_targets WHERE claim_id=? AND status!='deleted'",
        (claim_id,),
    ).fetchone()[0] == 0


def test_reindex_repairs_write_that_lands_during_alias_switch(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_post_switch_fence", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    with provider._connect() as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        conn.execute("DELETE FROM index_outbox")

    active = {"collection": "old-live-collection"}
    points = {active["collection"]: {}}
    switch_observation = {}
    upsert_calls = []
    module.SEMANTIC_ENABLED = True
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_ensure_collection", lambda collection=None: True)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda refresh=False: True)
    monkeypatch.setattr(
        module, "_qdrant_resolved_active_collection", lambda: active["collection"],
    )
    monkeypatch.setattr(
        module, "_qdrant_alias_target",
        lambda alias=module.QDRANT_ALIAS: active["collection"],
    )
    monkeypatch.setattr(
        module, "_qdrant_count", lambda collection=None: len(points.get(collection, {})),
    )
    monkeypatch.setattr(
        module, "_qdrant_claim_state",
        lambda collection, max_points=200000: {
            cid: module._qdrant_claim_reconciliation_state(payload)
            for cid, payload in points.get(collection, {}).items()
        },
    )
    monkeypatch.setattr(
        module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE,
    )

    def upsert(cid, _vector, payload, collection=None):
        destination = (
            active["collection"]
            if collection in {None, "", module.QDRANT_ALIAS}
            else collection
        )
        points.setdefault(destination, {})[cid] = dict(payload)
        upsert_calls.append((destination, cid, dict(payload)))
        return True

    def delete_target(cid, *, collection, endpoint=""):
        points.setdefault(collection, {}).pop(cid, None)
        return True

    monkeypatch.setattr(module, "_qdrant_upsert", upsert)
    monkeypatch.setattr(module, "_qdrant_delete_target", delete_target)
    monkeypatch.setattr(
        module, "_qdrant_delete_many",
        lambda ids, collection=None: all(
            points.setdefault(collection, {}).pop(cid, None) is not None
            or True for cid in ids
        ),
    )

    new_text = "Atlas gateway service now uses port 6789 for local requests."

    def switch_alias(collection):
        # The update commits after the pre-switch fence.  Its durable outbox
        # resolves the still-old alias, so the new target must be repaired only
        # by the post-switch reconciliation pass.
        with provider._connect() as conn:
            conn.execute(
                "UPDATE claims SET claim=?,normalized_claim=?,updated_at=? WHERE id=?",
                (new_text, new_text, module.now(), claim_id),
            )
        outbox = module._outbox_process(
            batch_size=50, db_path=str(provider.db_path),
            worker_id="alias-switch-race",
        )
        assert outbox["fail"] == 0, outbox
        old_writes = [
            payload for destination, cid, payload in upsert_calls
            if destination == active["collection"] and cid == claim_id
        ]
        assert old_writes
        switch_observation["old_payload"] = old_writes[-1]
        active["collection"] = collection
        return True

    monkeypatch.setattr(module, "_switch_alias", switch_alias)
    result = provider._reindex(force=True)
    assert result["status"] == "completed", result
    assert result["alias_switched"] is True
    assert result["post_switch_revision"] > result["pre_switch_revision"]
    target_payload = points[result["collection"]][claim_id]
    assert target_payload["vector_text_hash"] == module.sha(new_text)
    assert switch_observation["old_payload"]["vector_text_hash"] == module.sha(new_text)
    assert provider._connect().execute(
        "SELECT normalized_claim FROM claims WHERE id=?", (claim_id,),
    ).fetchone()[0] == new_text


def test_historical_endpoint_outage_keeps_retry_through_checkpoint_recovery(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_endpoint_retry", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    current_endpoint = module._normalized_qdrant_endpoint()
    old_endpoint = "https://old-qdrant.example"
    with provider._connect() as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        module._record_claim_vector_target(
            conn, claim_id, endpoint=old_endpoint, collection="claims-v1",
            manifest_hash="v1", status="active", indexed_at=1,
        )
        module._record_claim_vector_target(
            conn, claim_id, endpoint=current_endpoint, collection="claims-v2",
            manifest_hash="v2", status="active", indexed_at=2,
        )
        conn.execute("UPDATE claims SET status='retired' WHERE id=?", (claim_id,))

    points = {(old_endpoint, "claims-v1"), (current_endpoint, "claims-v2")}

    def partially_unavailable(cid, *, collection, endpoint=""):
        location = (module._normalized_qdrant_endpoint(endpoint or None), collection)
        if location[0] == old_endpoint:
            return False
        points.discard(location)
        return True

    monkeypatch.setattr(module, "_qdrant_delete_target", partially_unavailable)
    first = module._outbox_process(
        batch_size=20, db_path=str(provider.db_path), worker_id="outage-worker",
    )
    assert first["fail"] >= 1
    assert (old_endpoint, "claims-v1") in points
    pending = provider._connect().execute(
        "SELECT count(*) FROM index_outbox WHERE object_type='claim' "
        "AND object_id=? AND operation='delete' AND status='pending'",
        (claim_id,),
    ).fetchone()[0]
    assert pending >= 1
    assert provider._connect().execute(
        "SELECT status FROM claim_vector_targets WHERE claim_id=? AND endpoint=? "
        "AND collection='claims-v1'",
        (claim_id, old_endpoint),
    ).fetchone()[0] == "delete_pending"

    checkpoint = provider._journal_checkpoint("claim-target-retry")
    checkpoint_payload = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))
    assert checkpoint_payload["counts"]["claim_vector_targets"] == 2

    restored_home = tmp_path / "restored"
    restored_home.mkdir()
    (restored_home / ".env").write_text(
        f"MEMORY_WIKI_QDRANT_URL={module.QDRANT_URL}\n"
        f"MEMORY_WIKI_QDRANT_COLLECTION={module.QDRANT_COLLECTION}\n"
        f"MEMORY_WIKI_QDRANT_ALIAS={module.QDRANT_ALIAS}\n"
        f"MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION={module.EPISODIC_QDRANT_COLLECTION}\n"
        "MEMORY_WIKI_QDRANT_HISTORICAL_COLLECTIONS=claims-v1,claims-v2\n"
        "MEMORY_WIKI_QDRANT_HISTORICAL_ENDPOINTS=https://old-qdrant.example\n"
        "MEMORY_WIKI_EMBED_API_KEY=synthetic-restore-key\n",
        encoding="utf-8",
    )
    module.SEMANTIC_ENABLED = False
    restored = make_provider(module, restored_home)
    restored._apply_checkpoint_payload(checkpoint_payload)
    module.SEMANTIC_ENABLED = True
    monkeypatch.setattr(module, "_discover_managed_claim_collections", lambda: [])
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: "claims-v2")
    recovery = module._migrate_and_resume_claim_vector_targets(str(restored.db_path))
    assert recovery["queued"] >= 1
    recovered_payloads = [
        json.loads(row[0]) for row in restored._connect().execute(
            "SELECT payload_json FROM index_outbox WHERE object_type='claim' "
            "AND object_id=? AND operation='delete'",
            (claim_id,),
        ).fetchall()
    ]
    assert any(
        payload.get("endpoint") == old_endpoint
        and payload.get("collection") == "claims-v1"
        for payload in recovered_payloads
    )

    monkeypatch.setattr(
        module, "_qdrant_delete_target",
        lambda cid, *, collection, endpoint="": points.discard(
            (module._normalized_qdrant_endpoint(endpoint or None), collection)
        ) is None,
    )
    with restored._connect() as conn:
        conn.execute(
            "UPDATE index_outbox SET next_retry_at=0,status='pending' "
            "WHERE object_type='claim' AND object_id=? AND operation='delete'",
            (claim_id,),
        )
    final = module._outbox_process(
        batch_size=20, db_path=str(restored.db_path), worker_id="recovered-worker",
    )
    assert final["fail"] == 0
    assert not points
    assert restored._connect().execute(
        "SELECT count(*) FROM claim_vector_targets WHERE claim_id=? AND status!='deleted'",
        (claim_id,),
    ).fetchone()[0] == 0


def test_active_claim_scrub_deletes_old_targets_before_republishing_redacted_text(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_scrub_fanout", tmp_path, monkeypatch)
    allow_historical_targets(module, tmp_path, "claims-v1,claims-v2")
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    endpoint = module._normalized_qdrant_endpoint()
    points = {
        "claims-v1": {claim_id: {"claim": "credential=old-secret"}},
        "claims-v2": {claim_id: {"claim": "credential=old-secret"}},
    }
    with provider._connect() as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        for index, collection in enumerate(points, start=1):
            module._record_claim_vector_target(
                conn, claim_id, endpoint=endpoint, collection=collection,
                manifest_hash=f"v{index}", status="active", indexed_at=index,
            )
        conn.execute(
            "UPDATE claims SET claim=?,normalized_claim=? WHERE id=?",
            ("Credential removed from memory.", "Credential removed from memory.", claim_id),
        )

    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: "claims-v2")
    monkeypatch.setattr(module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)

    def delete_target(cid, *, collection, endpoint=""):
        points.setdefault(collection, {}).pop(cid, None)
        return True

    def upsert(cid, _vector, payload, collection=None):
        points.setdefault(collection, {})[cid] = dict(payload)
        return True

    monkeypatch.setattr(module, "_qdrant_delete_target", delete_target)
    monkeypatch.setattr(module, "_qdrant_upsert", upsert)
    monkeypatch.setattr(
        module, "_qdrant_claim_point_state",
        lambda cid, collection: (
            points[collection][cid]
            if cid in points.get(collection, {}) else {}
        ),
    )
    for run in range(3):
        result = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id=f"scrub-worker-{run}",
        )
        assert result["fail"] == 0

    assert claim_id not in points["claims-v1"]
    assert points["claims-v2"][claim_id]["claim"] == "Credential removed from memory."
    assert "old-secret" not in json.dumps(points, sort_keys=True)


def test_historical_delete_rejects_credentialed_or_remote_plaintext_endpoint(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_safe_historical_endpoint", tmp_path, monkeypatch)
    monkeypatch.setattr(
        module.urllib.request, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe endpoint received a request")
        ),
    )
    assert module._qdrant_delete_target(
        "c_secret", collection="claims-v1",
        endpoint="http://qdrant.example",
    ) is False
    assert module._qdrant_delete_target(
        "c_secret", collection="claims-v1",
        endpoint="https://user:password@qdrant.example",
    ) is False


def test_missing_collection_delete_needs_authenticated_same_endpoint_404(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_missing_collection", tmp_path, monkeypatch)
    module.QDRANT_API_KEY = "synthetic-current-key"
    endpoint = module._normalized_qdrant_endpoint()
    monkeypatch.setattr(module, "_qdrant_delete", lambda *_args, **_kwargs: False)
    seen = []
    response_code = {"value": 404}

    def probe(request, **_kwargs):
        seen.append(request)
        raise urllib.error.HTTPError(
            request.full_url, response_code["value"], "synthetic", {}, None,
        )

    monkeypatch.setattr(module, "_urlopen_no_redirect", probe)
    assert module._qdrant_delete_target(
        "c_synthetic", collection="claims-old", endpoint=endpoint,
    )
    assert seen[-1].get_method() == "GET"
    assert seen[-1].get_header("Api-key") == "synthetic-current-key"
    assert seen[-1].full_url.startswith(endpoint + "/collections/")
    for code in (401, 403, 500):
        response_code["value"] = code
        assert not module._qdrant_delete_target(
            "c_synthetic", collection="claims-old", endpoint=endpoint,
        )
    monkeypatch.setattr(
        module, "_urlopen_no_redirect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("synthetic")),
    )
    assert not module._qdrant_delete_target(
        "c_synthetic", collection="claims-old", endpoint=endpoint,
    )
    historical = "https://old-qdrant.example"
    assert not module._qdrant_collection_confirmed_absent("claims-old", historical)
    module.QDRANT_API_KEY = ""
    assert not module._qdrant_collection_confirmed_absent("claims-old", historical)


def test_retried_target_delete_preserves_new_canonical_point(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_target_retry", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    endpoint = module._normalized_qdrant_endpoint()
    current = "claims-current"
    old = "claims-old"
    with provider._connect() as conn:
        for index, collection in enumerate((old, current), start=1):
            module._record_claim_vector_target(
                conn, claim_id, endpoint=endpoint, collection=collection,
                manifest_hash=f"v{index}", status="delete_pending", indexed_at=index,
            )
        conn.execute(
            "UPDATE claims SET claim=?,normalized_claim=? WHERE id=?",
            ("Canonical redacted claim.", "Canonical redacted claim.", claim_id),
        )
    row = provider._connect().execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    fresh = module._qdrant_claim_payload(
        claim_id, row["normalized_claim"], row,
        manifest_hash=module._manifest_hash(module._embedding_manifest()),
    )
    stale = dict(fresh)
    stale["topic"] = "synthetic-private-topic"
    points = {current: {claim_id: stale}}
    deletes = []
    outage = {"old": True}
    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: current)
    monkeypatch.setattr(
        module, "_qdrant_claim_point_state",
        lambda cid, collection: (
            points[collection][cid]
            if cid in points.get(collection, {}) else {}
        ),
    )

    def delete(cid, *, collection, endpoint=""):
        deletes.append(collection)
        if collection == old and outage["old"]:
            return False
        points.setdefault(collection, {}).pop(cid, None)
        return True

    monkeypatch.setattr(module, "_qdrant_delete_target", delete)
    targets = {
        row["collection"]: dict(row)
        for row in provider._connect().execute(
            "SELECT * FROM claim_vector_targets WHERE claim_id=?", (claim_id,),
        ).fetchall()
    }
    def hint(collection):
        return {
            "endpoint": endpoint, "collection": collection,
            "vector_target_hash": targets[collection]["vector_target_hash"],
            "reason": "claim_content_rewritten",
        }

    assert not module._delete_claim_vector_targets(str(provider.db_path), claim_id, hint(old))
    assert deletes == [old]
    assert claim_id in points[current]
    outage["old"] = False
    assert module._delete_claim_vector_targets(str(provider.db_path), claim_id, hint(old))
    assert deletes == [old, old]
    assert module._delete_claim_vector_targets(str(provider.db_path), claim_id, hint(old))
    assert deletes == [old, old]
    assert module._delete_claim_vector_targets(str(provider.db_path), claim_id, hint(current))
    assert deletes == [old, old, current]
    points[current][claim_id] = fresh
    with provider._connect() as conn:
        module._record_claim_vector_target(
            conn, claim_id, endpoint=endpoint, collection=current,
            manifest_hash=module._manifest_hash(module._embedding_manifest()),
            status="active", indexed_at=10,
        )
    assert module._delete_claim_vector_targets(str(provider.db_path), claim_id, hint(current))
    assert deletes == [old, old, current]
    assert claim_id in points[current]


def test_non_targeted_cleanup_rechecks_tombstone_after_late_write(tmp_path, monkeypatch):
    module = load_module("memory_wiki_qdrant_late_upsert_cleanup", tmp_path, monkeypatch)
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    endpoint = module._normalized_qdrant_endpoint()
    collection = "claims-current"
    with provider._connect() as conn:
        module._record_claim_vector_target(
            conn, claim_id, endpoint=endpoint, collection=collection,
            status="deleted", indexed_at=1,
        )
        conn.execute("UPDATE claims SET status='retired' WHERE id=?", (claim_id,))
    calls = []
    monkeypatch.setattr(
        module, "_qdrant_delete_target",
        lambda cid, *, collection, endpoint="": calls.append(collection) or True,
    )
    assert module._delete_claim_vector_targets(
        str(provider.db_path), claim_id,
        {"collection": collection, "endpoint": endpoint},
    )
    assert calls == [collection]


def test_historical_delete_does_not_send_current_server_key(tmp_path, monkeypatch):
    module = load_module("memory_wiki_old_qdrant_key_fence", tmp_path, monkeypatch)
    module.QDRANT_API_KEY = "key-for-current-server-only"
    observed = []

    def reject_old_server(request, **_kwargs):
        observed.append(request)
        raise PermissionError("historical server requires its own credential")

    monkeypatch.setattr(module, "_urlopen_no_redirect", reject_old_server)
    assert module._qdrant_delete_target(
        "c_secret", collection="claims-v1",
        endpoint="https://old-qdrant.example",
    ) is False
    assert len(observed) == 1
    assert observed[0].full_url.startswith("https://old-qdrant.example/")
    assert all(
        name.lower() != "api-key" for name, _value in observed[0].header_items()
    )


def test_stale_claim_upsert_retargets_current_endpoint_and_keeps_old_cleanup(
    tmp_path, monkeypatch,
):
    module = load_module("memory_wiki_stale_endpoint_upsert", tmp_path, monkeypatch)
    allow_historical_targets(
        module, tmp_path, "claims-old,claims-current", "https://old-qdrant.example",
    )
    provider = make_provider(module, tmp_path)
    claim_id = add_chat_claim(provider)
    module.SEMANTIC_ENABLED = True
    old_endpoint = "https://old-qdrant.example"
    current_endpoint = module._normalized_qdrant_endpoint()
    assert old_endpoint != current_endpoint
    with provider._connect() as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        conn.execute("DELETE FROM index_outbox")
        module._record_claim_vector_target(
            conn, claim_id, endpoint=old_endpoint, collection="claims-old",
            manifest_hash="old", status="active", indexed_at=1,
        )
        module._outbox_enqueue(
            "embed_and_upsert", "claim", claim_id,
            {"endpoint": old_endpoint, "collection": "claims-old"}, conn=conn,
        )

    monkeypatch.setattr(module, "_qdrant_resolved_active_collection", lambda: "claims-current")
    monkeypatch.setattr(
        module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE,
    )
    writes = []
    monkeypatch.setattr(
        module, "_qdrant_upsert",
        lambda cid, _vector, _payload, collection=None: writes.append(
            (cid, module._normalized_qdrant_endpoint(), collection)
        ) or True,
    )
    result = module._outbox_process(
        batch_size=1, db_path=str(provider.db_path), worker_id="retarget-worker",
    )
    assert result["ok"] == 1 and result["fail"] == 0
    assert writes == [(claim_id, current_endpoint, "claims-current")]
    with provider._connect() as conn:
        targets = conn.execute(
            "SELECT endpoint,collection,status FROM claim_vector_targets WHERE claim_id=?",
            (claim_id,),
        ).fetchall()
        queued = conn.execute(
            "SELECT payload_json,status FROM index_outbox WHERE object_id=? "
            "AND object_type='claim' AND operation='delete'",
            (claim_id,),
        ).fetchall()
    assert (current_endpoint, "claims-current", "active") in [tuple(row) for row in targets]
    assert (old_endpoint, "claims-old", "delete_pending") in [tuple(row) for row in targets]
    assert any(
        json.loads(row[0]).get("endpoint") == old_endpoint
        and json.loads(row[0]).get("collection") == "claims-old"
        and row[1] == "pending"
        for row in queued
    )

    # An old server that requires its own credentials must leave cleanup
    # durable; the active server's key is never copied into this request.
    module.QDRANT_API_KEY = "key-for-current-server-only"
    old_requests = []

    def reject_old_server(request, **_kwargs):
        old_requests.append(request)
        raise PermissionError("historical server requires its own credential")

    monkeypatch.setattr(module, "_urlopen_no_redirect", reject_old_server)
    retry = module._outbox_process(
        batch_size=1, db_path=str(provider.db_path), worker_id="old-cleanup-worker",
    )
    assert retry["fail"] == 1
    assert len(old_requests) == 1
    assert all(
        name.lower() != "api-key" for name, _value in old_requests[0].header_items()
    )
    with provider._connect() as conn:
        status = conn.execute(
            "SELECT status FROM claim_vector_targets WHERE claim_id=? "
            "AND endpoint=? AND collection='claims-old'",
            (claim_id, old_endpoint),
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT count(*) FROM index_outbox WHERE object_type='claim' "
            "AND object_id=? AND operation='delete' AND status='pending'",
            (claim_id,),
        ).fetchone()[0]
    assert status == "delete_pending"
    assert pending == 1
