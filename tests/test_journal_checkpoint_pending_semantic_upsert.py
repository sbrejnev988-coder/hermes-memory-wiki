"""An acknowledged logical rebuild must not silently strand a pending claim embed."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
RETAINED_UNKNOWN = []  # Native negative controls retain owners to interpreter exit.


def test_checkpoint_rebuild_preserves_or_reports_pending_semantic_upsert(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")  # No bootstrap/network activity.
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_COLLECTION", "memory_wiki_claims_recovery_test")

    name = "memory_wiki_pending_upsert_checkpoint_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    unexpected_io = []

    def no_external_io(*args, **kwargs):
        unexpected_io.append((args, kwargs))
        raise AssertionError("synthetic recovery must not contact Qdrant or an embedding API")

    monkeypatch.setattr(module, "_qdrant_req", no_external_io)
    monkeypatch.setattr(module, "_embed_document", no_external_io)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda refresh=False: False)
    monkeypatch.setattr(module, "_discover_managed_claim_collections", lambda: [])
    monkeypatch.setattr(
        module, "_qdrant_resolved_active_collection",
        lambda: module._physical_collection_name(),
    )
    monkeypatch.setattr(module, "_start_outbox_worker", lambda _path: None)
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda _path: None)

    provider = module.MemoryWikiProvider()
    provider.initialize("pending-upsert-recovery", hermes_home=str(tmp_path), agent_context="test")
    assert provider.db_path.resolve().is_relative_to(tmp_path.resolve())
    try:
        # Enable only the local enqueue/recovery path, without starting a worker.
        module.SEMANTIC_ENABLED = True
        with provider._connect() as conn:
            conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        claim_id = provider._add_claim(
            "Atlas gateway service uses port 5678 for local requests.",
            topic="server", source="memory_tool:test", confidence=0.9, salience=0.9,
        )
        assert claim_id.startswith("c_"), claim_id
        live_claim = provider._connect().execute(
            "SELECT status,normalized_claim FROM claims WHERE id=?", (claim_id,),
        ).fetchone()
        assert live_claim and live_claim["status"] == "active"
        before = provider._connect().execute(
            "SELECT id,operation,status,payload_json FROM index_outbox "
            "WHERE object_type='claim' AND object_id=?", (claim_id,),
        ).fetchall()
        assert len(before) == 1, before
        assert before[0]["operation"] == "embed_and_upsert"
        assert before[0]["status"] == "pending"
        assert json.loads(before[0]["payload_json"])["text"] == live_claim["normalized_claim"]

        # At the logical checkpoint boundary both the source and its only
        # retryable delivery intent exist, regardless of serializer coverage.
        checkpoint = provider._journal_checkpoint("pending-semantic-upsert")
        still_pending = provider._connect().execute(
            "SELECT status FROM index_outbox WHERE id=?", (before[0]["id"],),
        ).fetchone()
        assert still_pending and still_pending["status"] == "pending"
        saved = provider._load_verified_checkpoint(Path(checkpoint["path"]))
        assert saved["semantic_outbox_intents"] == {
            "schema": "claim_upsert_intents/v1",
            "claim_ids": [claim_id],
            "pending_episode_jobs": 0,
        }
        assert any(
            row["id"] == claim_id and row["status"] == "active"
            for row in saved["tables"]["claims"]
        ), "the signed checkpoint must actually contain the active source claim"
        plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
        assert plan["events_to_replay"] == 0, plan

        result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        assert result["applied"] is True
        assert result["recovered_claim_upserts"] == 1
        assert not unexpected_io, unexpected_io
        restored_claim = provider._connect().execute(
            "SELECT status FROM claims WHERE id=?", (claim_id,),
        ).fetchone()
        assert restored_claim and restored_claim["status"] == "active", result
        retryable = provider._connect().execute(
            "SELECT id,operation,status,payload_json,worker_id,lease_until,attempts,next_retry_at "
            "FROM index_outbox WHERE object_type='claim' AND object_id=?",
            (claim_id,),
        ).fetchall()
        assert len(retryable) == 1, (
            "rebuild acknowledged restoration but lost the only pending semantic upsert",
            result,
        )
        assert retryable[0]["operation"] == "embed_and_upsert"
        assert retryable[0]["status"] == "pending"
        assert json.loads(retryable[0]["payload_json"]) == {}
        assert retryable[0]["worker_id"] == "" and retryable[0]["lease_until"] == 0
        assert retryable[0]["attempts"] == 0
        assert retryable[0]["next_retry_at"] <= int(time.time())
        assert not result.get("outbox_recovery_error"), result
        assert provider._owned_conn is provider._conn
        assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
        assert provider._transaction_quarantine is None
        assert provider._lifecycle_state == "ready" and not provider._conn.in_transaction
        public = provider.handle_tool_call("memory_wiki_query", {"query": "Atlas gateway", "limit": 5})
        public = json.loads(public) if isinstance(public, str) else public
        assert claim_id in [row["id"] for row in public.get("claims", [])], public
    finally:
        if provider._transaction_quarantine is not None:
            RETAINED_UNKNOWN.append(provider)
        else:
            provider.shutdown()
            assert provider._conn is None and provider._owned_conn is None
        sys.modules.pop(name, None)


@pytest.fixture
def recovery(tmp_path_factory, monkeypatch, request):
    # Own explicit non-numbered root: pytest's optional current symlink is not
    # part of this isolated no-links native packet or its resource contract.
    token = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    tmp_path = tmp_path_factory.mktemp('journal-recovery-' + token, numbered=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_COLLECTION", "memory_wiki_claims_recovery_test")
    name = "memory_wiki_pending_upsert_checkpoint_fixture"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    unexpected_io = []

    def no_external_io(*args, **kwargs):
        unexpected_io.append((args, kwargs))
        raise AssertionError("recovery must not contact Qdrant or embedding API")

    monkeypatch.setattr(module, "_qdrant_req", no_external_io)
    monkeypatch.setattr(module, "_embed_document", no_external_io)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda refresh=False: False)
    monkeypatch.setattr(module, "_discover_managed_claim_collections", lambda: [])
    monkeypatch.setattr(
        module, "_qdrant_resolved_active_collection",
        lambda: module._physical_collection_name(),
    )
    worker_paths = []
    monkeypatch.setattr(module, "_start_outbox_worker", lambda path: worker_paths.append(path))
    monkeypatch.setattr(module, "_wake_outbox_worker", lambda _path: None)
    provider = module.MemoryWikiProvider()
    provider.initialize("pending-upsert-recovery", hermes_home=str(tmp_path), agent_context="test")
    assert not worker_paths and not unexpected_io
    try:
        module.SEMANTIC_ENABLED = True
        with provider._connect() as c:
            c.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        yield module, provider, unexpected_io, worker_paths
    finally:
        if provider._transaction_quarantine is not None:
            RETAINED_UNKNOWN.append(provider)
        else:
            provider.shutdown()
            assert provider._conn is None and provider._owned_conn is None
        sys.modules.pop(name, None)


def _pending_claim(provider):
    claim_id = provider._add_claim(
        "Atlas gateway service uses port 5678 for local requests.",
        topic="server", source="memory_tool:test", confidence=0.9, salience=0.9,
    )
    row = provider._connect().execute(
        "SELECT id,status,operation,payload_json FROM index_outbox "
        "WHERE object_type='claim' AND object_id=?", (claim_id,),
    ).fetchone()
    assert row and row["status"] == "pending" and row["operation"] == "embed_and_upsert"
    return claim_id, row


def _resign_checkpoint(checkpoint, payload):
    """Simulate an older *validly signed* local checkpoint, not a corrupt digest."""
    path = Path(checkpoint["path"])
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = Path(checkpoint["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_rebuild_keeps_canonical_upsert_when_historical_target_delete_resumes(recovery):
    module, provider, unexpected_io, worker_paths = recovery
    claim_id, _job = _pending_claim(provider)
    worker_paths.clear()
    old_collection = module._qdrant_collection()
    current_collection = module._physical_collection_name()
    assert old_collection != current_collection
    with provider._connect() as c:
        historical = module._record_claim_vector_target(
            c, claim_id, endpoint=module._normalized_qdrant_endpoint(),
            collection=old_collection, status="delete_pending", indexed_at=1,
        )
    checkpoint = provider._journal_checkpoint("pending-upsert-with-old-target-delete")
    saved = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    assert saved["semantic_outbox_intents"]["claim_ids"] == [claim_id]
    assert any(
        row["claim_id"] == claim_id and row["collection"] == old_collection
        and row["status"] == "delete_pending"
        for row in saved["tables"]["claim_vector_targets"]
    )

    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["applied"] is True and result["recovered_claim_upserts"] == 1
    assert not result.get("outbox_recovery_error"), result
    c = provider._connect()
    assert c.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "active"
    rows = c.execute(
        "SELECT operation,status,payload_json,worker_id,lease_until,attempts "
        "FROM index_outbox WHERE object_type='claim' AND object_id=?",
        (claim_id,),
    ).fetchall()
    upserts = [row for row in rows if row["operation"] == "embed_and_upsert"]
    deletes = [row for row in rows if row["operation"] == "delete"]
    assert len(upserts) == 1, ("canonical upsert lost to old-target cleanup", result, rows)
    assert (upserts[0]["status"], upserts[0]["worker_id"], upserts[0]["lease_until"],
            upserts[0]["attempts"]) == ("pending", "", 0, 0)
    assert json.loads(upserts[0]["payload_json"]) == {}
    assert len(deletes) == 1, rows
    assert deletes[0]["status"] == "pending"
    assert json.loads(deletes[0]["payload_json"])["collection"] == old_collection
    target = c.execute(
        "SELECT status,vector_target_hash FROM claim_vector_targets "
        "WHERE claim_id=? AND collection=? AND endpoint=?",
        (claim_id, old_collection, historical["endpoint"]),
    ).fetchone()
    assert target and target["status"] == "delete_pending"
    assert json.loads(deletes[0]["payload_json"])["vector_target_hash"] == target["vector_target_hash"]
    assert worker_paths == [str(provider.db_path)]
    assert not unexpected_io


def test_inactive_claim_target_recovery_cancels_orphaned_pending_upsert(recovery):
    module, provider, unexpected_io, worker_paths = recovery
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()
    old_collection = module._qdrant_collection()
    with provider._connect() as c:
        c.execute("UPDATE claims SET status='retired' WHERE id=?", (claim_id,))
        historical = module._record_claim_vector_target(
            c, claim_id, endpoint=module._normalized_qdrant_endpoint(),
            collection=old_collection, status="delete_pending",
        )
        # Model a stale delivery hint that escaped normal retirement's trigger.
        c.execute(
            """INSERT INTO index_outbox(id,operation,object_type,object_id,payload_json,
                   created_at,updated_at,next_retry_at)
               VALUES(?,'embed_and_upsert','claim',?,?,1,1,1)""",
            (job["id"], claim_id, job["payload_json"]),
        )
    result = module._migrate_and_resume_claim_vector_targets(str(provider.db_path))
    rows = provider._connect().execute(
        "SELECT operation,payload_json FROM index_outbox WHERE object_type='claim' AND object_id=?",
        (claim_id,),
    ).fetchall()
    assert result["queued"] >= 1
    assert not any(row["operation"] in ("embed_and_upsert", "upsert") for row in rows)
    assert any(
        row["operation"] == "delete"
        and json.loads(row["payload_json"]).get("collection") == old_collection
        and json.loads(row["payload_json"]).get("vector_target_hash") == historical["vector_target_hash"]
        for row in rows
    )
    assert not worker_paths and not unexpected_io


def test_processing_claim_requeues_without_worker_lease_or_retained_payload(recovery):
    _, provider, unexpected_io, worker_paths = recovery
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()  # The synthetic add may have requested its normal worker.
    with provider._connect() as c:
        c.execute(
            """UPDATE index_outbox SET status='processing',worker_id='old-worker',
                 lease_until=9999999999,attempts=7 WHERE id=?""",
            (job["id"],),
        )
    checkpoint = provider._journal_checkpoint("processing-semantic-upsert")
    saved = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    assert saved["semantic_outbox_intents"]["claim_ids"] == [claim_id]
    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["recovered_claim_upserts"] == 1
    rows = provider._connect().execute(
        "SELECT status,worker_id,lease_until,attempts,payload_json FROM index_outbox "
        "WHERE object_type='claim' AND object_id=?", (claim_id,),
    ).fetchall()
    assert len(rows) == 1
    assert (rows[0]["status"], rows[0]["worker_id"], rows[0]["lease_until"], rows[0]["attempts"]) == ("pending", "", 0, 0)
    assert json.loads(rows[0]["payload_json"]) == {}
    assert worker_paths == [str(provider.db_path)]
    assert not unexpected_io


def test_retired_claim_with_stale_upsert_is_not_republished(recovery):
    _, provider, unexpected_io, worker_paths = recovery
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()
    with provider._connect() as c:
        c.execute("UPDATE claims SET status='retired' WHERE id=?", (claim_id,))
        # Normal retirement cancels the job; model an orphaned historical hint.
        c.execute(
            """INSERT INTO index_outbox(id,operation,object_type,object_id,payload_json,
                   created_at,updated_at,next_retry_at)
               VALUES(?,'embed_and_upsert','claim',?,?,1,1,1)""",
            (job["id"], claim_id, job["payload_json"]),
        )
    checkpoint = provider._journal_checkpoint("retired-claim-stale-upsert")
    assert provider._load_verified_checkpoint(Path(checkpoint["path"]))["semantic_outbox_intents"]["claim_ids"] == [claim_id]
    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["recovered_claim_upserts"] == 0
    c = provider._connect()
    assert c.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "retired"
    assert c.execute(
        "SELECT count(*) FROM index_outbox WHERE object_type='claim' AND object_id=? "
        "AND operation IN ('upsert','embed_and_upsert')", (claim_id,),
    ).fetchone()[0] == 0
    assert worker_paths == [str(provider.db_path)]
    assert not unexpected_io


@pytest.mark.parametrize("manifest_change", ["missing", "unsupported_schema", "invalid_ids"])
def test_legacy_or_invalid_semantic_manifest_refuses_before_live_swap(recovery, manifest_change):
    _, provider, unexpected_io, worker_paths = recovery
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()
    original_path = provider.db_path
    checkpoint = provider._journal_checkpoint("legacy-outbox-intents")
    payload = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    if manifest_change == "missing":
        payload.pop("semantic_outbox_intents")
    elif manifest_change == "unsupported_schema":
        payload["semantic_outbox_intents"]["schema"] = "claim_upsert_intents/v999"
    else:
        payload["semantic_outbox_intents"]["claim_ids"] = ["claim text is not an ID"]
    _resign_checkpoint(checkpoint, payload)
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["semantic_outbox_recovery"]["status"] == "blocked"
    with pytest.raises(RuntimeError, match="semantic outbox"):
        provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert provider.db_path == original_path
    assert provider._connect().execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,),
    ).fetchone()[0] == "active"
    assert provider._connect().execute(
        "SELECT status FROM index_outbox WHERE id=?", (job["id"],),
    ).fetchone()[0] == "pending"
    assert not unexpected_io and not worker_paths


def test_requeue_failure_on_temporary_database_aborts_without_swapping(recovery, monkeypatch):
    _, provider, unexpected_io, worker_paths = recovery
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()
    checkpoint = provider._journal_checkpoint("inject-requeue-failure")
    original_path = provider.db_path
    original_restore = provider._restore_checkpoint_claim_upserts
    observed_temp = []

    def fail_after_temp_write(ids):
        assert provider.db_path != original_path
        observed_temp.append(provider.db_path)
        assert original_restore(ids) == 1
        raise RuntimeError("injected outbox requeue validation failure")

    monkeypatch.setattr(provider, "_restore_checkpoint_claim_upserts", fail_after_temp_write)
    with pytest.raises(RuntimeError, match="injected outbox requeue"):
        provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert len(observed_temp) == 1
    assert provider.db_path == original_path
    assert provider._connect().execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,),
    ).fetchone()[0] == "active"
    assert provider._connect().execute(
        "SELECT id,status FROM index_outbox WHERE id=?", (job["id"],),
    ).fetchone()["status"] == "pending"
    assert not unexpected_io and not worker_paths


def test_native_ready_migration_reenters_connect_under_exact_owner(recovery, monkeypatch):
    """Prepared native control; SOURCE must not execute or substitute this SDK."""
    sdk = pytest.importorskip("agent.memory_provider")
    _, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    c = provider._connect()
    original_cols = provider._cols
    witnessed = []

    def observe_cols(table):
        result = original_cols(table)  # Real nested _connect/identity admission.
        if c.in_transaction:
            assert provider._conn is c and provider._owned_conn is c
            assert provider._claim_tx_connection is c
            assert provider._claim_tx_thread == threading.get_ident()
            witnessed.append(table)
        return result

    monkeypatch.setattr(provider, "_cols", observe_cols)
    provider._migrate()
    assert witnessed
    assert provider._conn is c and provider._owned_conn is c
    assert not c.in_transaction and provider._transaction_quarantine is None
    assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
    assert provider._lifecycle_state == "ready" and not unexpected_io


@pytest.mark.parametrize("rollback_unknown", [False, True])
def test_native_rebuild_migration_failure_preserves_primary_and_exact_owner(recovery, monkeypatch, rollback_unknown):
    """Prepared real rebuild/rollback controls, not generic SQLite authority."""
    sdk = pytest.importorskip("agent.memory_provider")
    _, provider, unexpected_io, worker_paths = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()
    checkpoint = provider._journal_checkpoint("migration-owner-fault")
    original_path = provider.db_path
    original_cols = provider._cols
    primary = ValueError("owned migration primary")
    observed = []

    def deny_rollback(action, first, second, database, trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK" else sqlite3.SQLITE_OK

    def fail_after_owned_write(table):
        result = original_cols(table)
        c = provider._conn
        if provider.db_path != original_path and c.in_transaction and not observed:
            assert provider._claim_tx_connection is c
            assert provider._claim_tx_thread == threading.get_ident()
            observed.append(c)
            if rollback_unknown:
                c.set_authorizer(deny_rollback)
            raise primary
        return result

    monkeypatch.setattr(provider, "_cols", fail_after_owned_write)
    with pytest.raises(ValueError) as caught:
        provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert caught.value is primary and len(observed) == 1
    temp = observed[0]
    if rollback_unknown:
        assert provider._conn is temp and provider._owned_conn is temp
        assert provider._transaction_quarantine is temp
        assert provider._transaction_primary is primary
        assert provider._claim_tx_connection is temp
        assert provider._claim_tx_thread == threading.get_ident()
        assert provider.db_path != original_path and temp.in_transaction
        assert provider._lifecycle_state == "quarantined"
        for action in (provider._connect, provider.shutdown):
            with pytest.raises(RuntimeError):
                action()
        assert not provider._release_connection_for_retry(primary)
        assert provider._conn is temp and provider._transaction_primary is primary
    else:
        assert provider.db_path == original_path
        assert provider._owned_conn is provider._conn
        assert provider._transaction_quarantine is None
        assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
        assert not provider._conn.in_transaction and provider._lifecycle_state == "ready"
        with pytest.raises(sqlite3.ProgrammingError):
            temp.execute("SELECT 1")
        assert provider._connect().execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "active"
        assert provider._connect().execute("SELECT status FROM index_outbox WHERE id=?", (job["id"],)).fetchone()[0] == "pending"
    assert not unexpected_io and not worker_paths


def test_checkpoint_retains_only_id_not_outbox_text_lease_or_endpoint(recovery):
    _, provider, unexpected_io, _ = recovery
    claim_id, job = _pending_claim(provider)
    outbox_only = "OUTBOX_ONLY_PRIVATE_SENTINEL_6a3b"
    with provider._connect() as c:
        payload = json.loads(job["payload_json"])
        payload.update({"text": outbox_only, "endpoint": "http://outbox-only.invalid/secret"})
        c.execute(
            "UPDATE index_outbox SET payload_json=?,worker_id=?,lease_until=? WHERE id=?",
            (json.dumps(payload), "OUTBOX_ONLY_LEASE_OWNER_6a3b", 9876543210, job["id"]),
        )
    checkpoint = provider._journal_checkpoint("no-retained-outbox-payload")
    raw = Path(checkpoint["path"]).read_text(encoding="utf-8")
    assert claim_id in raw
    assert outbox_only not in raw
    assert "OUTBOX_ONLY_LEASE_OWNER_6a3b" not in raw
    assert "outbox-only.invalid" not in raw
    saved = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    assert "index_outbox" not in saved["tables"]
    assert saved["semantic_outbox_intents"]["claim_ids"] == [claim_id]
    assert not unexpected_io


def test_pending_episode_outbox_job_is_explicitly_unsupported(recovery):
    _, provider, unexpected_io, worker_paths = recovery
    c = provider._connect()
    with c:
        c.execute(
            """INSERT INTO index_outbox(id,operation,object_type,object_id,payload_json,
                   created_at,updated_at,next_retry_at)
               VALUES('episode-job','embed_and_upsert','episode','ep_test','{}',1,1,1)"""
        )
    checkpoint = provider._journal_checkpoint("episode-job-not-recoverable")
    saved = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    assert saved["semantic_outbox_intents"]["pending_episode_jobs"] == 1
    with pytest.raises(RuntimeError, match="episode outbox jobs"):
        provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert provider._connect().execute(
        "SELECT status FROM index_outbox WHERE id='episode-job'"
    ).fetchone()[0] == "pending"
    assert not unexpected_io and not worker_paths


def test_checkpoint_reads_claims_and_outbox_intent_from_one_sqlite_snapshot(recovery, monkeypatch):
    _, provider, unexpected_io, _ = recovery
    claim_id, job = _pending_claim(provider)
    original_json_safe = provider._json_safe
    changed_live_job = []

    def complete_job_while_serializing_claim(*args, **kwargs):
        serialized = original_json_safe(*args, **kwargs)
        if isinstance(args[0], dict) and args[0].get("id") == claim_id and not changed_live_job:
            with sqlite3.connect(str(provider.db_path), timeout=10) as other:
                other.execute("UPDATE index_outbox SET status='completed' WHERE id=?", (job["id"],))
            changed_live_job.append(True)
        return serialized

    monkeypatch.setattr(provider, "_json_safe", complete_job_while_serializing_claim)
    checkpoint = provider._journal_checkpoint("snapshot-consistency")
    assert changed_live_job
    assert provider._connect().execute(
        "SELECT status FROM index_outbox WHERE id=?", (job["id"],),
    ).fetchone()[0] == "completed"
    saved = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    assert saved["semantic_outbox_intents"]["claim_ids"] == [claim_id]
    assert not unexpected_io


def test_pending_claim_created_after_checkpoint_is_not_silently_lost(recovery):
    module, provider, unexpected_io, worker_paths = recovery
    module.SEMANTIC_ENABLED = False
    claim_id = provider._add_claim(
        "Aster service offers local requests on port 9223.",
        topic="server", source="memory_tool:test", confidence=0.9, salience=0.9,
    )
    module.SEMANTIC_ENABLED = True
    worker_paths.clear()
    checkpoint = provider._journal_checkpoint("before-new-outbox-job")
    assert provider._load_verified_checkpoint(Path(checkpoint["path"]))["semantic_outbox_intents"]["claim_ids"] == []
    with provider._connect() as c:
        module._outbox_enqueue("embed_and_upsert", "claim", claim_id, {}, conn=c)
    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["applied"]
    assert provider._connect().execute(
        "SELECT count(*) FROM index_outbox WHERE object_type='claim' AND object_id=? "
        "AND operation='embed_and_upsert' AND status='pending'", (claim_id,),
    ).fetchone()[0] == 1
    assert worker_paths == [str(provider.db_path)]
    assert not unexpected_io


def test_episode_job_added_after_checkpoint_refuses_before_swap(recovery):
    _, provider, unexpected_io, worker_paths = recovery
    checkpoint = provider._journal_checkpoint("before-episode-job")
    assert provider._load_verified_checkpoint(Path(checkpoint["path"]))["semantic_outbox_intents"]["pending_episode_jobs"] == 0
    with provider._connect() as c:
        c.execute(
            """INSERT INTO index_outbox(id,operation,object_type,object_id,payload_json,
                   created_at,updated_at,next_retry_at)
               VALUES('late-episode-job','embed_and_upsert','episode','ep_late','{}',1,1,1)"""
        )
    with pytest.raises(RuntimeError, match="episode outbox jobs"):
        provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert provider._connect().execute(
        "SELECT status FROM index_outbox WHERE id='late-episode-job'"
    ).fetchone()[0] == "pending"
    assert not unexpected_io and not worker_paths


def test_recovered_id_only_job_uses_canonical_claim_for_stubbed_delivery(recovery, monkeypatch):
    module, provider, unexpected_io, worker_paths = recovery
    claim_id, _ = _pending_claim(provider)
    worker_paths.clear()
    checkpoint = provider._journal_checkpoint("id-only-delivery")
    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    live_text = provider._connect().execute(
        "SELECT COALESCE(NULLIF(normalized_claim,''),claim) FROM claims WHERE id=?", (claim_id,),
    ).fetchone()[0]
    embedded = []
    published = []

    def fake_embed(text):
        embedded.append(text)
        return [0.0] * module.QDRANT_VECTOR_SIZE

    def fake_upsert(cid, vector, payload, collection=None):
        published.append((cid, payload, collection))
        return True

    monkeypatch.setattr(module, "_embed_document", fake_embed)
    monkeypatch.setattr(module, "_qdrant_upsert", fake_upsert)
    result = module._outbox_process_scoped(1, db_path=str(provider.db_path))
    assert result["processed"] == 1 and result["ok"] == 1 and result["fail"] == 0, result
    assert embedded == [live_text]
    assert len(published) == 1 and published[0][0] == claim_id
    assert published[0][1]["claim"] == live_text
    assert provider._connect().execute(
        "SELECT count(*) FROM index_outbox WHERE object_type='claim' AND object_id=?", (claim_id,),
    ).fetchone()[0] == 0
    assert worker_paths == [str(provider.db_path)]
    assert not unexpected_io


def test_replayed_retirement_cancels_checkpointed_claim_upsert(recovery):
    _, provider, unexpected_io, worker_paths = recovery
    claim_id, _ = _pending_claim(provider)
    worker_paths.clear()
    checkpoint = provider._journal_checkpoint("before-retirement")
    args = {"claim_id": claim_id, "status": "retired"}
    provider._journal_operation(
        "memory_wiki_update_claim", args,
        lambda: json.dumps({"success": True, **provider._update_claim(args)}),
    )
    assert provider._connect().execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,),
    ).fetchone()[0] == "retired"
    plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
    assert plan["events_to_replay"] == 1, plan
    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["replayed"] == 1 and result["recovered_claim_upserts"] == 0, result
    c = provider._connect()
    assert c.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "retired"
    assert c.execute(
        "SELECT count(*) FROM index_outbox WHERE object_type='claim' AND object_id=? "
        "AND operation IN ('upsert','embed_and_upsert')", (claim_id,),
    ).fetchone()[0] == 0
    assert not unexpected_io


def test_checkpoint_with_failed_claim_serialization_refuses_outbox_rebuild(recovery):
    _, provider, unexpected_io, worker_paths = recovery
    claim_id, job = _pending_claim(provider)
    worker_paths.clear()
    checkpoint = provider._journal_checkpoint("damaged-claim-table")
    payload = provider._load_verified_checkpoint(Path(checkpoint["path"]))
    payload["tables"]["claims"] = [{"checkpoint_error": "injected serialization error"}]
    payload["counts"]["claims"] = -1
    _resign_checkpoint(checkpoint, payload)
    with pytest.raises(RuntimeError, match="checkpoint.*claims"):
        provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert provider._connect().execute(
        "SELECT status FROM claims WHERE id=?", (claim_id,),
    ).fetchone()[0] == "active"
    assert provider._connect().execute(
        "SELECT status FROM index_outbox WHERE id=?", (job["id"],),
    ).fetchone()[0] == "pending"
    assert not unexpected_io and not worker_paths


# Genuine SDK/provider/native correction regressions: prepared, NOT_RUN in SOURCE.


def test_native_checkpoint_apply_owns_nested_reads_through_full_rebuild(recovery, monkeypatch):
    sdk = pytest.importorskip("agent.memory_provider")
    _, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    claim_id, _ = _pending_claim(provider)
    checkpoint = provider._journal_checkpoint("checkpoint-apply-owner-correction")
    original_apply, original_cols = provider._apply_checkpoint_payload, provider._cols
    applying, observed = [], []

    def observe_apply(payload):
        applying.append(True)
        try:
            return original_apply(payload)
        finally:
            applying.pop()

    def observe_cols(table):
        result = original_cols(table)  # Real pending/identity/owner admission.
        c = provider._conn
        if applying and c.in_transaction:
            assert provider._owned_conn is c and provider._claim_tx_connection is c
            assert provider._claim_tx_thread == threading.get_ident()
            observed.append(table)
        return result

    monkeypatch.setattr(provider, "_apply_checkpoint_payload", observe_apply)
    monkeypatch.setattr(provider, "_cols", observe_cols)
    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["applied"] and result["recovered_claim_upserts"] == 1
    assert "claims" in observed and "evidence" in observed
    assert provider._conn is provider._owned_conn
    assert not provider._conn.in_transaction and provider._transaction_quarantine is None
    assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
    assert provider._lifecycle_state == "ready"
    public = provider.handle_tool_call("memory_wiki_query", {"query": "Atlas gateway", "limit": 5})
    public = json.loads(public) if isinstance(public, str) else public
    assert claim_id in [row["id"] for row in public.get("claims", [])], public
    assert not unexpected_io


@pytest.mark.parametrize("rollback_unknown", [False, True])
def test_native_migrate_implicit_script_commit_delivers_original_cancellation(recovery, rollback_unknown):
    sdk = pytest.importorskip("agent.memory_provider")
    module, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    c = provider._connect()
    assert type(c) is module._GraphCommitConnection
    original = KeyboardInterrupt("JRO actual authorizer COMMIT cancellation")
    observed = []

    def authorizer(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT":
            observed.append("commit")
            raise original
        if rollback_unknown and action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK":
            observed.append("rollback-denied")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    c.set_authorizer(authorizer)  # Real callback, never disabled during the call.
    with pytest.raises(KeyboardInterrupt) as caught:
        provider._migrate()  # Genuine migration up to its actual implicit batch COMMIT.
    assert caught.value is original and observed[0] == "commit"
    assert isinstance(original.__cause__, sqlite3.DatabaseError)
    assert c._graph_commit_error is None  # Delivered once, before owner cleanup.
    assert provider._conn is c and provider._owned_conn is c
    if rollback_unknown:
        assert observed == ["commit", "rollback-denied"]
        assert provider._transaction_primary is original and provider._transaction_quarantine is c
        assert provider._claim_tx_connection is c and provider._claim_tx_thread == threading.get_ident()
        assert c.in_transaction and provider._lifecycle_state == "quarantined"
        with pytest.raises(RuntimeError):
            provider._close_journal_rebuild_connection(original)
        assert not provider._release_connection_for_retry(original)
    else:
        assert not c.in_transaction and provider._transaction_quarantine is None
        assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
        healthy = []

        def allow(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT":
                healthy.append(first)
            return sqlite3.SQLITE_OK

        c.set_authorizer(allow)
        provider._migrate()
        assert healthy and c._graph_user_authorizer is allow
        assert provider._connect().execute("SELECT 1").fetchone()[0] == 1
        c.set_authorizer(None)
        assert provider._lifecycle_state == "ready"
    assert not unexpected_io


def test_native_batch_cancellation_keeps_prior_committed_prefix_only(recovery):
    sdk = pytest.importorskip("agent.memory_provider")
    module, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    c = provider._connect()
    assert type(c) is module._GraphCommitConnection
    original = KeyboardInterrupt("JRO second batch cancellation")
    commits = []

    def authorizer(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT":
            commits.append(first)
            if len(commits) == 2:
                raise original
        return sqlite3.SQLITE_OK

    c.set_authorizer(authorizer)
    with pytest.raises(KeyboardInterrupt) as caught:
        with provider._migration_connection() as owned:
            owned.execute("CREATE TABLE jro_partial_batches(value TEXT)")
            owned.execute("INSERT INTO jro_partial_batches VALUES('prefix')")
            owned.executescript("SELECT 1;")  # Real first implicit COMMIT.
            owned.execute("INSERT INTO jro_partial_batches VALUES('suffix')")
            owned.executescript("SELECT 2;")
    assert caught.value is original and len(commits) == 2
    assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
    assert provider._transaction_quarantine is None and not c.in_transaction
    assert c._graph_commit_error is None
    c.set_authorizer(None)
    other = sqlite3.connect(str(provider.db_path))
    try:
        assert other.execute("SELECT value FROM jro_partial_batches").fetchall() == [("prefix",)]
    finally:
        other.close()
    assert provider._connect() is c and not unexpected_io


@pytest.mark.parametrize("disclosure", [False, True])
def test_native_reader_issuance_registry_excludes_concurrent_rebuild(recovery, monkeypatch, disclosure):
    sdk = pytest.importorskip("agent.memory_provider")
    _, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    graph = sys.modules[provider.__class__.__module__ + ".code_knowledge_graph"]
    checkpoint = provider._journal_checkpoint("reader-issuance-exclusion")
    shared, original_path = provider._connect(), provider.db_path
    original_connect = provider._connect
    connected, release, issued, close_reader = (threading.Event() for _ in range(4))
    rebuilding, rebuilt = threading.Event(), threading.Event()
    reader_ids, handles, reader_errors, rebuild_errors = [], [], [], []

    def observe_connect():
        result = original_connect()
        if reader_ids == [threading.get_ident()] and not connected.is_set():
            connected.set()  # Actual _connect returned; registry is still empty.
            assert release.wait(10), "reader issuance barrier expired"
        return result

    monkeypatch.setattr(provider, "_connect", observe_connect)

    def read():
        try:
            reader_ids.append(threading.get_ident())
            reader, owned = graph._open_graph_reader_connection(provider, disclosure=disclosure)
            handles.append(reader)
            assert owned and graph._owns_graph_reader(provider, reader)
            assert reader._graph_read_shared is shared
            assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
            issued.set()
            assert close_reader.wait(30), "reader cleanup barrier expired"
            graph._close_graph_writer_connection(reader, owned)
            assert reader._graph_read_state == "closed"
        except BaseException as error:
            reader_errors.append(error)
            issued.set()

    def rebuild():
        rebuilding.set()
        try:
            provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        except BaseException as error:
            rebuild_errors.append(error)
        finally:
            rebuilt.set()

    reader_thread = sdk.spawn_context_thread(read, name="jro-actual-reader", daemon=False)
    rebuild_thread = None
    try:
        assert connected.wait(10)
        acquired = provider._lock.acquire(blocking=False)
        if acquired:
            provider._lock.release()
        assert not acquired, "factory released lock before reader publication"
        assert not provider._graph_reader_connections
        rebuild_thread = sdk.spawn_context_thread(rebuild, name="jro-actual-rebuild", daemon=False)
        assert rebuilding.wait(10)
        release.set()
        assert issued.wait(10) and not reader_errors
        assert rebuilt.wait(20), "actual rebuild did not finish its refusal"
        # It sees the exact live reader, refuses close and never rebinds path or
        # strands a reader against a stale shared handle. Cleanup is still owned.
        assert len(rebuild_errors) == 1
        assert str(rebuild_errors[0]) == "journal_rebuild_connection_owner_pending"
        assert provider._conn is shared and provider._owned_conn is shared
        assert provider.db_path == original_path and handles[0] in provider._graph_reader_connections
        assert provider._transaction_primary is rebuild_errors[0]
        assert provider._transaction_quarantine is shared
    finally:
        release.set()
        close_reader.set()
        reader_thread.join(20)
        if rebuild_thread is not None:
            rebuild_thread.join(20)
    assert not reader_thread.is_alive() and rebuild_thread is not None and not rebuild_thread.is_alive()
    assert not reader_errors and not provider._graph_reader_connections
    assert provider._conn is shared and provider._transaction_primary is rebuild_errors[0]
    assert not unexpected_io


def test_native_healthy_private_reader_then_rebuild_and_public_read(recovery):
    sdk = pytest.importorskip("agent.memory_provider")
    _, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    graph = sys.modules[provider.__class__.__module__ + ".code_knowledge_graph"]
    claim_id, _ = _pending_claim(provider)
    checkpoint = provider._journal_checkpoint("healthy-reader-then-rebuild")
    shared = provider._connect()
    for disclosure in (False, True):
        reader, owned = graph._open_graph_reader_connection(provider, disclosure=disclosure)
        try:
            assert owned and graph._owns_graph_reader(provider, reader)
            assert reader._graph_read_shared is shared
            assert reader.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "active"
            if disclosure:
                assert reader._graph_read_fence.source_conn is reader
        finally:
            graph._close_graph_writer_connection(reader, owned)
        assert not provider._graph_reader_connections
    assert provider._transaction_quarantine is None and provider._lifecycle_state == "ready"
    result = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
    assert result["applied"] and result["recovered_claim_upserts"] == 1
    public = provider.handle_tool_call("memory_wiki_query", {"query": "Atlas gateway", "limit": 5})
    public = json.loads(public) if isinstance(public, str) else public
    assert claim_id in [row["id"] for row in public.get("claims", [])], public
    assert provider._transaction_quarantine is None and not unexpected_io


@pytest.mark.parametrize("operation", ["execute", "executemany", "executescript"])
def test_native_direct_sql_keeps_restricting_authorizer_and_healthy_positive(recovery, operation):
    sdk = pytest.importorskip("agent.memory_provider")
    module, provider, unexpected_io, _ = recovery
    assert provider.__class__.__bases__ == (sdk.MemoryProvider,)
    c = provider._connect()
    assert type(c) is module._GraphCommitConnection
    c.execute("CREATE TABLE jro_direct_authorizer(value TEXT)")
    denied = []

    def authorizer(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_INSERT and first == "jro_direct_authorizer":
            denied.append(first)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def insert(owned):
        if operation == "execute":
            owned.execute("INSERT INTO jro_direct_authorizer VALUES(?)", ("positive",))
        elif operation == "executemany":
            owned.executemany("INSERT INTO jro_direct_authorizer VALUES(?)", [("positive",)])
        else:
            owned.executescript("INSERT INTO jro_direct_authorizer VALUES('positive');")

    c.set_authorizer(authorizer)
    with pytest.raises(sqlite3.DatabaseError):
        with provider._migration_connection() as owned:
            insert(owned)
    assert denied == ["jro_direct_authorizer"] and c._graph_user_authorizer is authorizer
    assert c._graph_commit_error is None and provider._transaction_quarantine is None
    assert provider._claim_tx_connection is None and not c.in_transaction
    assert c.execute("SELECT value FROM jro_direct_authorizer").fetchall() == []
    c.set_authorizer(None)
    with provider._migration_connection() as owned:
        insert(owned)
    assert [row[0] for row in c.execute("SELECT value FROM jro_direct_authorizer")] == ["positive"]
    assert provider._transaction_quarantine is None and not unexpected_io
