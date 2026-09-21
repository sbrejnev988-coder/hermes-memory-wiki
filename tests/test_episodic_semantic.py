"""Episode vectors stay asynchronous, scoped, disposable, and FTS optional."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SEMANTIC", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "chat")
    monkeypatch.setenv("MEMORY_WIKI_OUTBOX_EMBED_DELAY_SECONDS", "0")
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # Tests drain the durable outbox explicitly. No background thread may race
    # the assertions or perform real network calls.
    monkeypatch.setattr(module, "_start_outbox_worker", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda *args, **kwargs: None)
    return module


def _provider(module, home: Path, *, bot: str = "bot-a", chat: str = "chat-a"):
    provider = module.MemoryWikiProvider()
    provider.initialize(chat, hermes_home=str(home), bot_id=bot, agent_context="primary")
    provider._ingest_text = lambda *args, **kwargs: None
    return provider


def _episode_id(provider, text: str) -> str:
    row = provider._connect().execute(
        "SELECT id FROM episodic_turns WHERE content=?", (text,),
    ).fetchone()
    assert row
    return str(row[0])


def test_capture_enqueues_canonical_episode_payload_and_worker_upserts(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_outbox", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        # Capture must never wait for an embedding request.
        monkeypatch.setattr(
            module, "_embed_document",
            lambda _text: (_ for _ in ()).throw(AssertionError("capture embedded synchronously")),
        )
        text = "The cobalt compass is kept in the eastern observatory."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        row = provider._connect().execute(
            "SELECT * FROM index_outbox WHERE object_type='episode' AND object_id=?",
            (episode_id,),
        ).fetchone()
        assert row and row["operation"] == "embed_and_upsert" and row["status"] == "pending"
        queued = json.loads(row["payload_json"])
        episode = provider._connect().execute(
            "SELECT * FROM episodic_turns WHERE id=?", (episode_id,),
        ).fetchone()
        assert queued["text"] == text
        assert queued["role"] == episode["role"] == "user"
        assert queued["turn_id"] == episode["turn_id"]
        assert queued["owner_bot_id"] == "bot-a"
        assert queued["owner_chat_hash"] == episode["owner_chat_hash"]
        assert queued["visibility_scope"] == "chat"
        assert queued["created_at"] == episode["created_at"]
        assert queued["expires_at"] == episode["expires_at"]
        assert queued["collection"] == module._episodic_collection_name()
        assert queued["manifest_hash"] == module._manifest_hash(module._embedding_manifest())
        assert queued["vector_target_hash"] == module._episodic_vector_target_hash()
        assert queued["collection"] != module._active_collection_name()

        vector = [0.0] * module.QDRANT_VECTOR_SIZE
        monkeypatch.setattr(module, "_embed_document", lambda _text: vector)
        captured = {}

        def upsert(object_id, actual_vector, payload, collection=None):
            captured.update({
                "id": object_id, "vector": actual_vector,
                "payload": dict(payload), "collection": collection,
            })
            return True

        monkeypatch.setattr(module, "_qdrant_upsert", upsert)
        outcome = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="episode-test",
        )
        assert outcome["ok"] == 1 and outcome["fail"] == 0
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode' AND object_id=?",
            (episode_id,),
        ).fetchone() is None
        indexed = provider._connect().execute(
            "SELECT vector_manifest_hash,vector_target_hash FROM episodic_turns WHERE id=?",
            (episode_id,),
        ).fetchone()
        assert indexed[0] == module._manifest_hash(module._embedding_manifest())
        assert indexed[1] == module._episodic_vector_target_hash()
        payload = captured["payload"]
        assert captured["id"] == episode_id
        assert captured["collection"] == module._episodic_collection_name()
        assert payload["id"] == payload["episode_id"] == episode_id
        assert payload["object_type"] == "episode"
        assert payload["vector_text_hash"] == module.sha(text)
        assert payload["manifest_hash"] == queued["manifest_hash"]
        assert payload["vector_target_hash"] == queued["vector_target_hash"]
        for field in (
            "role", "turn_id", "owner_bot_id", "owner_chat_hash",
            "visibility_scope", "created_at", "expires_at",
        ):
            assert payload[field] == queued[field]
        assert "claim_id" not in payload
    finally:
        provider.shutdown()


def test_enabling_semantic_backfills_existing_safe_episodes_once(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_backfill", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SEMANTIC", "0")
        text = "The legacy star chart marks Vega with a cobalt ring."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode'",
        ).fetchone() is None

        monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SEMANTIC", "1")
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 1
        queued = provider._connect().execute(
            "SELECT payload_json FROM index_outbox WHERE object_type='episode' AND object_id=?",
            (episode_id,),
        ).fetchone()
        assert queued
        payload = json.loads(queued[0])
        assert payload["text"] == text
        assert payload["manifest_hash"] == module._manifest_hash(module._embedding_manifest())
        assert payload["vector_target_hash"] == module._episodic_vector_target_hash()

        monkeypatch.setattr(module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)
        monkeypatch.setattr(module, "_qdrant_upsert", lambda *args, **kwargs: True)
        outcome = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="backfill-test",
        )
        assert outcome["ok"] == 1
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 0
    finally:
        provider.shutdown()


def test_vector_target_schema_migrates_legacy_episode_table(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_target_schema", tmp_path, monkeypatch)
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE episodic_turns(
        id TEXT PRIMARY KEY,content TEXT NOT NULL,role TEXT NOT NULL,
        turn_id TEXT NOT NULL DEFAULT '',owner_bot_id TEXT NOT NULL,
        owner_chat_hash TEXT NOT NULL,visibility_scope TEXT NOT NULL,
        created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
        vector_manifest_hash TEXT NOT NULL DEFAULT '')""")
    module._episodic_memory.install_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(episodic_turns)")}
    assert "vector_manifest_hash" in columns
    assert "vector_target_hash" in columns
    assert "vector_collection" in columns
    assert "vector_endpoint" in columns
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='episodic_vector_targets'"
    ).fetchone()


def test_collection_endpoint_and_payload_version_changes_requeue_backfill(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_target_backfill", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The target fingerprint note references the northern astrolabe."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        monkeypatch.setattr(
            module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE,
        )
        monkeypatch.setattr(module, "_qdrant_upsert", lambda *args, **kwargs: True)

        initial_target = module._episodic_vector_target_hash()
        first = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="target-initial",
        )
        assert first["ok"] == 1
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 0

        monkeypatch.setattr(module, "EPISODIC_QDRANT_COLLECTION", "episodes-relocated")
        collection_target = module._episodic_vector_target_hash()
        assert collection_target != initial_target
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 1
        queued = provider._connect().execute(
            "SELECT payload_json FROM index_outbox WHERE object_type='episode' AND object_id=?",
            (episode_id,),
        ).fetchone()
        collection_payload = json.loads(queued[0])
        assert collection_payload["collection"] == module._episodic_collection_name()
        assert collection_payload["vector_target_hash"] == collection_target
        second = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="target-collection",
        )
        assert second["ok"] == 1

        monkeypatch.setattr(module, "QDRANT_URL", "HTTP://qdrant-alt.example:7333///")
        endpoint_target = module._episodic_vector_target_hash()
        assert endpoint_target != collection_target
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 1
        third = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="target-endpoint",
        )
        assert third["ok"] == 1

        old_payload_version = module.QDRANT_EPISODE_PAYLOAD_VERSION
        monkeypatch.setattr(
            module, "QDRANT_EPISODE_PAYLOAD_VERSION", old_payload_version + 1,
        )
        payload_target = module._episodic_vector_target_hash()
        assert payload_target != endpoint_target
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 1
    finally:
        provider.shutdown()


def test_qdrant_episode_query_uses_isolated_collection_and_exact_filter(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_filter", tmp_path, monkeypatch)
    query_filter = module._qdrant_episode_filter(
        bot_id="bot-a", chat_hash="chat-hash-a",
        visibility_scope="chat", expires_after=1234,
    )
    captured = {}

    def request(method, path, body=None, timeout=10.0):
        captured.update({"method": method, "path": path, "body": body})
        return {"result": {"points": [{
            "id": "opaque", "score": 0.81,
            "payload": {"episode_id": "ep_visible", "object_type": "episode"},
        }]}}

    monkeypatch.setattr(module, "_qdrant_req", request)
    matches = module._qdrant_episode_search(
        [0.0] * module.QDRANT_VECTOR_SIZE, 4, query_filter=query_filter,
    )
    assert matches == [("ep_visible", 0.81)]
    assert captured["method"] == "POST"
    assert captured["path"] == f"/collections/{module._episodic_collection_name()}/points/query"
    assert captured["body"]["filter"] == query_filter
    must = query_filter["must"]
    assert {item["key"] for item in must} == {
        "object_type", "owner_bot_id", "owner_chat_hash", "visibility_scope", "expires_at",
    }
    assert {"key": "expires_at", "range": {"gt": 1234}} in must

    monkeypatch.setattr(module, "EPISODIC_QDRANT_COLLECTION", module.QDRANT_COLLECTION)
    assert module._episodic_collection_name() != module._physical_collection_name()


def test_vector_only_hit_fusion_and_sqlite_acl_are_authoritative(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_fusion", tmp_path, monkeypatch)
    own = _provider(module, tmp_path, bot="bot-a", chat="chat-a")
    foreign = _provider(module, tmp_path, bot="bot-b", chat="chat-a")
    try:
        lexical = "The Atlas launch code phrase is silver birch."
        vector_only = "Store the indigo sextant beside the western dome."
        foreign_text = "The forbidden foreign Atlas phrase is scarlet pine."
        own.sync_turn(lexical, "")
        own.sync_turn(vector_only, "")
        foreign.sync_turn(foreign_text, "")
        lexical_id = _episode_id(own, lexical)
        vector_id = _episode_id(own, vector_only)
        foreign_id = _episode_id(foreign, foreign_text)

        monkeypatch.setattr(module, "_episodic_semantic_available", lambda: True)
        embed_calls = []
        monkeypatch.setattr(
            module, "_embed_query",
            lambda text: embed_calls.append(text) or [0.0] * module.QDRANT_VECTOR_SIZE,
        )
        filters = []

        def search(_vector, _limit, *, query_filter):
            filters.append(query_filter)
            # The foreign ID models a compromised/misconfigured Qdrant result.
            # SQLite must remove it. The lexical row appears in both rank lists,
            # so deterministic RRF should place it above the vector-only row.
            return [(foreign_id, 0.99), (vector_id, 0.90), (lexical_id, 0.70)]

        monkeypatch.setattr(module, "_qdrant_episode_search", search)
        result = module._episodic_memory.query_episodes(
            own, module, "Atlas launch code phrase", limit=3, include_diagnostics=True,
        )
        contents = [row["content"] for row in result["episodes"]]
        assert contents[0] == lexical
        assert vector_only in contents
        assert foreign_text not in contents
        assert embed_calls == ["Atlas launch code phrase"]
        assert result["diagnostics"]["semantic_used"] is True
        assert result["diagnostics"]["semantic_candidates"] == 3
        serialized = json.dumps(filters[0], sort_keys=True)
        assert "bot-a" in serialized
        assert own._chat_hash("chat-a") in serialized
        assert "expires_at" in serialized
    finally:
        own.shutdown()
        foreign.shutdown()


def test_embedding_failure_falls_back_to_fts(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_fallback", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The Lyra telescope uses an amber calibration lens."
        provider.sync_turn(text, "")
        monkeypatch.setattr(module, "_episodic_semantic_available", lambda: True)
        monkeypatch.setattr(
            module, "_embed_query",
            lambda _text: (_ for _ in ()).throw(TimeoutError("synthetic timeout")),
        )
        result = module._episodic_memory.query_episodes(
            provider, module, "Lyra amber lens", limit=2, include_diagnostics=True,
        )
        assert [row["content"] for row in result["episodes"]] == [text]
        assert result["diagnostics"]["semantic_error"] == "TimeoutError"
        assert result["diagnostics"]["lexical_candidates"] == 1
    finally:
        provider.shutdown()


def test_delete_and_quota_prune_enqueue_episode_point_deletes(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_delete", tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_MAX_ROWS", "1")
    provider = _provider(module, tmp_path)
    try:
        first_text = "The first observatory marker is cobalt."
        second_text = "The second observatory marker is amber."
        provider.sync_turn(first_text, "")
        first_id = _episode_id(provider, first_text)
        provider.sync_turn(second_text, "")
        second_id = _episode_id(provider, second_text)

        rows = provider._connect().execute(
            "SELECT operation,object_id,payload_json FROM index_outbox "
            "WHERE object_type='episode' AND status='pending' ORDER BY created_at,id"
        ).fetchall()
        state = {(str(row["operation"]), str(row["object_id"])) for row in rows}
        assert ("delete", first_id) in state
        assert ("embed_and_upsert", second_id) in state
        assert ("embed_and_upsert", first_id) not in state

        assert module._episodic_memory.delete_episodes(provider, module=module) == 1
        rows = provider._connect().execute(
            "SELECT operation,object_id,payload_json FROM index_outbox "
            "WHERE object_type='episode' AND status='pending' ORDER BY object_id"
        ).fetchall()
        assert {(row["operation"], row["object_id"]) for row in rows} == {
            ("delete", first_id), ("delete", second_id),
        }
        assert all(
            json.loads(row["payload_json"])["collection"] == module._episodic_collection_name()
            for row in rows
        )

        deleted = []
        monkeypatch.setattr(
            module, "_qdrant_delete",
            lambda object_id, collection=None: deleted.append((object_id, collection)) or True,
        )
        outcome = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="delete-test",
        )
        assert outcome["ok"] == 2 and outcome["fail"] == 0
        assert set(deleted) == {
            (first_id, module._episodic_collection_name()),
            (second_id, module._episodic_collection_name()),
        }
    finally:
        provider.shutdown()


def test_failed_processing_embed_cannot_resurrect_deleted_episode(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_delete_retry_race", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The transient observatory note names a cobalt meridian."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        collection = module._episodic_collection_name()
        embed_calls = []

        def delete_during_embed(document):
            embed_calls.append(document)
            assert module._episodic_memory.delete_episodes(
                provider, module=module,
            ) == 1
            raise TimeoutError("synthetic embedding timeout after privacy delete")

        monkeypatch.setattr(module, "_embed_document", delete_during_embed)
        first = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="race-first",
        )
        assert first["fail"] == 1 and first["ok"] == 0
        assert embed_calls == [text]
        rows = provider._connect().execute(
            "SELECT operation,status FROM index_outbox "
            "WHERE object_type='episode' AND object_id=? ORDER BY operation",
            (episode_id,),
        ).fetchall()
        assert {(row["operation"], row["status"]) for row in rows} == {
            ("delete", "pending"), ("embed_and_upsert", "pending"),
        }

        deleted = []
        monkeypatch.setattr(
            module, "_qdrant_delete_target",
            lambda object_id, *, collection, endpoint="":
                deleted.append((object_id, collection, endpoint)) or True,
        )
        second = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="race-delete",
        )
        assert second["ok"] == 1 and second["fail"] == 0
        with provider._connect() as conn:
            conn.execute(
                "UPDATE index_outbox SET next_retry_at=0 "
                "WHERE object_type='episode' AND object_id=?",
                (episode_id,),
            )
        monkeypatch.setattr(
            module, "_embed_document",
            lambda _text: (_ for _ in ()).throw(
                AssertionError("deleted episode was embedded on retry")
            ),
        )
        monkeypatch.setattr(
            module, "_qdrant_upsert",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("deleted episode was re-upserted")
            ),
        )
        third = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="race-retry",
        )
        assert third["ok"] == 1 and third["fail"] == 0
        assert [item[1] for item in deleted] == [collection, collection]
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode' "
            "AND object_id=?", (episode_id,),
        ).fetchone() is None
        assert provider._connect().execute(
            "SELECT 1 FROM episodic_turns WHERE id=?", (episode_id,),
        ).fetchone() is None
    finally:
        provider.shutdown()


def test_worker_deletes_stale_episode_acl_text_and_target_payloads(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_stale_payload", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The authoritative episode keeps the amber sextant in cabinet four."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        deleted = []
        monkeypatch.setattr(
            module, "_qdrant_delete_target",
            lambda object_id, *, collection, endpoint="":
                deleted.append((object_id, collection, endpoint)) or True,
        )
        monkeypatch.setattr(
            module, "_embed_document",
            lambda _text: (_ for _ in ()).throw(
                AssertionError("stale retained payload reached embedding")
            ),
        )
        monkeypatch.setattr(
            module, "_qdrant_upsert",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("stale retained payload reached Qdrant upsert")
            ),
        )

        mutations = (
            ("owner_chat_hash", "forged-chat-partition"),
            ("text", "A stale retained copy must never be embedded."),
            ("vector_target_hash", "0" * 64),
        )
        for index, (field, value) in enumerate(mutations):
            if index:
                assert module._episodic_memory.enqueue_semantic_backfill(
                    provider, module,
                ) == 1
            row = provider._connect().execute(
                "SELECT id,payload_json FROM index_outbox "
                "WHERE object_type='episode' AND object_id=? "
                "AND operation='embed_and_upsert'",
                (episode_id,),
            ).fetchone()
            assert row
            payload = json.loads(row["payload_json"])
            payload[field] = value
            with provider._connect() as conn:
                conn.execute(
                    "UPDATE index_outbox SET payload_json=? WHERE id=?",
                    (json.dumps(payload), row["id"]),
                )
            result = module._outbox_process(
                batch_size=20, db_path=str(provider.db_path),
                worker_id=f"stale-{index}",
            )
            assert result["ok"] == 1 and result["fail"] == 0

        assert len(deleted) == len(mutations)
        stored = provider._connect().execute(
            "SELECT content,vector_manifest_hash,vector_target_hash "
            "FROM episodic_turns WHERE id=?", (episode_id,),
        ).fetchone()
        assert tuple(stored) == (text, "", "")
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode' "
            "AND object_id=?", (episode_id,),
        ).fetchone() is None
    finally:
        provider.shutdown()


def test_retarget_history_privacy_delete_fans_out_and_survives_failure(
    tmp_path, monkeypatch
):
    module = _module("memory_wiki_episode_target_history", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The migration ledger tracks the indigo astrolabe episode."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        monkeypatch.setattr(
            module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE,
        )
        indexed = []
        monkeypatch.setattr(
            module, "_qdrant_upsert",
            lambda object_id, vector, payload, collection=None:
                indexed.append((object_id, collection, dict(payload))) or True,
        )
        old_collection = module._episodic_collection_name()
        first = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="history-old",
        )
        assert first["ok"] == 1

        monkeypatch.setattr(module, "EPISODIC_QDRANT_COLLECTION", "episodes-relocated")
        new_collection = module._episodic_collection_name()
        assert new_collection != old_collection
        assert module._episodic_memory.enqueue_semantic_backfill(
            provider, module,
        ) == 1
        second = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="history-new",
        )
        assert second["ok"] == 1
        assert [item[1] for item in indexed] == [old_collection, new_collection]
        assert {
            row[0] for row in provider._connect().execute(
                "SELECT collection FROM episodic_vector_targets WHERE episode_id=?",
                (episode_id,),
            ).fetchall()
        } == {old_collection, new_collection}

        assert module._episodic_memory.delete_episodes(
            provider, module=module,
        ) == 1
        pending = provider._connect().execute(
            "SELECT payload_json FROM index_outbox "
            "WHERE object_type='episode' AND object_id=? AND operation='delete'",
            (episode_id,),
        ).fetchall()
        assert {json.loads(row[0])["collection"] for row in pending} == {
            old_collection, new_collection,
        }

        delete_calls = []
        old_attempts = 0

        def flaky_delete(object_id, *, collection, endpoint=""):
            nonlocal old_attempts
            delete_calls.append((object_id, collection, endpoint))
            if collection == old_collection:
                old_attempts += 1
                if old_attempts == 1:
                    return False
            return True

        monkeypatch.setattr(module, "_qdrant_delete_target", flaky_delete)
        deletion = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="history-delete",
        )
        assert deletion["ok"] == 1 and deletion["fail"] == 1
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode' "
            "AND object_id=? AND operation='delete' AND status='pending'",
            (episode_id,),
        ).fetchone()
        assert provider._connect().execute(
            "SELECT 1 FROM episodic_vector_targets WHERE episode_id=? "
            "AND collection=?", (episode_id, old_collection),
        ).fetchone()

        with provider._connect() as conn:
            conn.execute(
                "UPDATE index_outbox SET next_retry_at=0 "
                "WHERE object_type='episode' AND object_id=?",
                (episode_id,),
            )
        retry = module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="history-retry",
        )
        assert retry["ok"] == 1 and retry["fail"] == 0
        assert {item[1] for item in delete_calls} == {
            old_collection, new_collection,
        }
        assert provider._connect().execute(
            "SELECT 1 FROM episodic_vector_targets WHERE episode_id=?",
            (episode_id,),
        ).fetchone() is None
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode' "
            "AND object_id=?", (episode_id,),
        ).fetchone() is None
    finally:
        provider.shutdown()


def test_retarget_delete_is_cancelled_when_configuration_rolls_back(
    tmp_path, monkeypatch
):
    module = _module("memory_wiki_episode_target_rollback", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The rollback ledger keeps the silver quadrant episode."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        monkeypatch.setattr(
            module, "_embed_document", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE,
        )
        monkeypatch.setattr(module, "_qdrant_upsert", lambda *args, **kwargs: True)
        original_base = module.EPISODIC_QDRANT_COLLECTION
        old_collection = module._episodic_collection_name()
        assert module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="rollback-old",
        )["ok"] == 1

        monkeypatch.setattr(module, "EPISODIC_QDRANT_COLLECTION", "episodes-next")
        new_collection = module._episodic_collection_name()
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 1
        assert module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="rollback-new",
        )["ok"] == 1
        assert {
            json.loads(row[0])["collection"]
            for row in provider._connect().execute(
                "SELECT payload_json FROM index_outbox "
                "WHERE object_type='episode' AND object_id=? AND operation='delete'",
                (episode_id,),
            ).fetchall()
        } == {old_collection}

        monkeypatch.setattr(module, "EPISODIC_QDRANT_COLLECTION", original_base)
        assert module._episodic_memory.enqueue_semantic_backfill(provider, module) == 1
        # Enqueuing the canonical rollback upsert cancels only the delete for
        # that exact target; no worker can later erase the republished point.
        assert provider._connect().execute(
            "SELECT 1 FROM index_outbox WHERE object_type='episode' "
            "AND object_id=? AND operation='delete'", (episode_id,),
        ).fetchone() is None
        assert module._outbox_process(
            batch_size=20, db_path=str(provider.db_path), worker_id="rollback-publish",
        )["ok"] == 1
        pending = provider._connect().execute(
            "SELECT payload_json FROM index_outbox "
            "WHERE object_type='episode' AND object_id=? AND operation='delete'",
            (episode_id,),
        ).fetchall()
        assert {json.loads(row[0])["collection"] for row in pending} == {
            new_collection,
        }
        current = provider._connect().execute(
            "SELECT vector_collection FROM episodic_turns WHERE id=?",
            (episode_id,),
        ).fetchone()
        assert current[0] == old_collection
    finally:
        provider.shutdown()


def test_expired_vector_hit_is_deleted_and_never_returned(tmp_path, monkeypatch):
    module = _module("memory_wiki_episode_semantic_expiry", tmp_path, monkeypatch)
    provider = _provider(module, tmp_path)
    try:
        text = "The expired meridian note says the dial is brass."
        provider.sync_turn(text, "")
        episode_id = _episode_id(provider, text)
        with provider._connect() as conn:
            conn.execute("UPDATE episodic_turns SET expires_at=1 WHERE id=?", (episode_id,))
        monkeypatch.setattr(module, "_episodic_semantic_available", lambda: True)
        monkeypatch.setattr(module, "_embed_query", lambda _text: [0.0] * module.QDRANT_VECTOR_SIZE)
        monkeypatch.setattr(
            module, "_qdrant_episode_search",
            lambda *_args, **_kwargs: [(episode_id, 0.99)],
        )
        result = module._episodic_memory.query_episodes(
            provider, module, "meridian brass dial", limit=2,
        )
        assert result["episodes"] == []
        assert provider._connect().execute(
            "SELECT 1 FROM episodic_turns WHERE id=?", (episode_id,),
        ).fetchone() is None
        row = provider._connect().execute(
            "SELECT operation FROM index_outbox WHERE object_type='episode' "
            "AND object_id=? AND status='pending'", (episode_id,),
        ).fetchone()
        assert row and row["operation"] == "delete"
    finally:
        provider.shutdown()
