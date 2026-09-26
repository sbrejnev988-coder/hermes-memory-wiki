#!/usr/bin/env python3
"""Regression coverage for code-graph event identity and lifecycle atomicity."""
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
REPOSITORY_ID = "repo-code-graph-atomicity"


def load_provider(module_name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "0")
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(module_name, hermes_home=str(tmp_path),
                        project_id=REPOSITORY_ID, agent_context="test")
    return module, provider


def snapshot(event_id: str, name: str, *, snapshot_hash: str = "producer-controlled-snapshot-hash"):
    file_hash = hashlib.sha256((name + " source").encode()).hexdigest()
    return {
        "event_version": 2,
        "type": "code_graph_snapshot",
        "graph_schema_version": 1,
        "producer": "code-shrinker",
        "repository_id": REPOSITORY_ID,
        "event_id": event_id,
        "snapshot_mode": "full",
        # The two concurrent payloads deliberately reuse this attacker-controlled
        # value.  Deduplication must still bind to their actual normalized body.
        "snapshot_hash": snapshot_hash,
        "commit_sha": hashlib.sha1((name + " commit").encode()).hexdigest(),
        "files": [{
            "file_path": f"src/{name}.py",
            "file_hash": file_hash,
            "language": "python",
            "line_count": 1,
        }],
    }


def graph_paths(provider) -> set[str]:
    rows = provider._connect().execute(
        "SELECT file_path FROM code_graph_files WHERE repository_id=?", (REPOSITORY_ID,)
    ).fetchall()
    return {str(row[0]) for row in rows}


def chunk_snapshot(event_id: str, name: str):
    event = snapshot(event_id, name)
    chunk_text = (
        f"The {name} semantic implementation has a deterministic regression test, "
        "an explicit transaction boundary, and a source-level provenance contract."
    )
    event["chunks"] = [{
        "chunk_id": "shared-chunk",
        "file_path": event["files"][0]["file_path"],
        "symbol_id": "shared-symbol",
        "qualified_name": "shared.symbol",
        "start_line": 1,
        "end_line": 1,
        "chunk_text": chunk_text,
        "embedding_text": chunk_text,
        "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
    }]
    return event


def test_mapped_code_identity_does_not_exempt_adjacent_secret_metadata(tmp_path, monkeypatch) -> None:
    """Only exact mapper-created IDs and validated digests bypass entropy scanning."""
    _module, provider = load_provider("memory_wiki_mapped_identity_secret_guard", tmp_path, monkeypatch)
    token = "ghp_" + "a" * 36
    payload = {
        "claim": "A verified code procedure retains a safe graph identifier.",
        "topic": "code-intelligence",
        "repository_id": f"repo-{token}",
        "file_path": "src/safe.py",
        "symbol_id": "safe_symbol",
        "content_hash": hashlib.sha256(b"safe source revision").hexdigest(),
    }
    try:
        prepared = provider._prepare_code_claim(payload)
        assert isinstance(prepared, dict)
        assert str(prepared["repository_id"]).startswith("redacted-graph-id-")
        with pytest.raises(ValueError, match="secret in claim metadata"):
            provider._prepare_code_claim({
                **payload,
                "symbol_revision": "OPENAI_API_KEY=sk-proj-" + "b" * 40,
            })
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_concurrent_same_event_id_binds_graph_to_winning_payload_across_providers(tmp_path, monkeypatch) -> None:
    """A same-id collision cannot leave graph B behind event metadata for A."""
    module_a, provider_a = load_provider("memory_wiki_atomicity_a", tmp_path, monkeypatch)
    module_b, provider_b = load_provider("memory_wiki_atomicity_b", tmp_path, monkeypatch)
    first = snapshot("shared-event-id", "winner_a")
    second = snapshot("shared-event-id", "winner_b")
    start = threading.Barrier(3)
    outcomes = []
    outcomes_lock = threading.Lock()

    def ingest(module, provider, event) -> None:
        start.wait(timeout=10)
        try:
            outcome = ("completed", module._ingest_code_graph_event(provider, event))
        except Exception as exc:  # The losing payload must be rejected, not applied.
            outcome = ("error", exc)
        with outcomes_lock:
            outcomes.append(outcome)

    workers = [
        threading.Thread(target=ingest, args=(module_a, provider_a, first), daemon=True),
        threading.Thread(target=ingest, args=(module_b, provider_b, second), daemon=True),
    ]
    try:
        for worker in workers:
            worker.start()
        start.wait(timeout=10)
        for worker in workers:
            worker.join(timeout=30)
        assert all(not worker.is_alive() for worker in workers)
        completed = [value for kind, value in outcomes if kind == "completed"]
        failures = [value for kind, value in outcomes if kind == "error"]
        assert len(completed) == 1, outcomes
        assert len(failures) == 1 and isinstance(failures[0], ValueError), outcomes
        assert "event_id reuse" in str(failures[0])

        row = provider_a._connect().execute(
            "SELECT payload_hash,payload_hash_version,stats_json FROM code_graph_events WHERE event_id=?",
            ("shared-event-id",),
        ).fetchone()
        assert row is not None
        graph_module_a = sys.modules[module_a.__name__ + ".code_knowledge_graph"]
        graph_module_b = sys.modules[module_b.__name__ + ".code_knowledge_graph"]
        expected = {
            graph_module_a._sha(graph_module_a._json(graph_module_a._normalize_code_graph_event(first))): "src/winner_a.py",
            graph_module_b._sha(graph_module_b._json(graph_module_b._normalize_code_graph_event(second))): "src/winner_b.py",
        }
        assert str(row[0]) in expected
        assert int(row[1]) == 3
        assert graph_paths(provider_a) == {expected[str(row[0])]}
        stored = json.loads(row[2])
        assert stored["event_id"] == "shared-event-id"
        assert stored["counts"]["files"] == 1
        winning_event = first if expected[str(row[0])] == "src/winner_a.py" else second
        winning_module = module_a if winning_event is first else module_b
        winning_provider = provider_a if winning_event is first else provider_b
        repeated = winning_module._ingest_code_graph_event(winning_provider, winning_event)
        assert repeated["deduplicated"] is True
        assert graph_paths(provider_a) == {expected[str(row[0])]}
    finally:
        for provider in (provider_a, provider_b):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_graph_lifecycle_failure_rolls_back_claims_rows_and_event_reservation(tmp_path, monkeypatch) -> None:
    """A failure after reservation cannot archive claims or leave a partial event."""
    module, provider = load_provider("memory_wiki_atomicity_rollback", tmp_path, monkeypatch)
    base = snapshot("atomic-base", "keep")
    removed = snapshot("atomic-base-removed", "gone")
    try:
        module._ingest_code_graph_event(provider, {
            **base,
            "files": [*base["files"], *removed["files"]],
        })
        claim = provider._code_claim_add({
            "claim": "Verified atomic graph lifecycle claim for the removed source file remains active until commit.",
            "topic": "code-shrinker",
            "repository_id": REPOSITORY_ID,
            "file_path": "src/gone.py",
            "content_hash": removed["files"][0]["file_hash"],
            "evidence": "verified graph lifecycle rollback behavior",
            "confidence": 0.95,
            "salience": 0.9,
        })
        claim_id = str(claim["id"])
        graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]

        def fail_after_reservation(*_args, **_kwargs):
            raise RuntimeError("injected graph writer failure")

        monkeypatch.setattr(graph_module, "_insert_graph_rows", fail_after_reservation)
        with pytest.raises(RuntimeError, match="injected graph writer failure"):
            module._ingest_code_graph_event(provider, snapshot("atomic-failure", "keep"))

        status = provider._connect().execute(
            "SELECT status FROM claims WHERE id=?", (claim_id,)
        ).fetchone()
        assert status is not None and str(status[0]) == "active"
        assert graph_paths(provider) == {"src/keep.py", "src/gone.py"}
        event = provider._connect().execute(
            "SELECT 1 FROM code_graph_events WHERE event_id=?", ("atomic-failure",)
        ).fetchone()
        assert event is None
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_embedding_starts_only_after_the_atomic_graph_commit(tmp_path, monkeypatch) -> None:
    """Slow embedding work never extends the graph/claim transaction."""
    module, provider = load_provider("memory_wiki_atomicity_embedding", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    observed = {}

    def assert_committed(target, repository_id, _commit_sha, event_id, _files, **_kwargs):
        conn = target._connect()
        assert not conn.in_transaction
        state = conn.execute(
            "SELECT status FROM code_graph_events WHERE event_id=?", (event_id,)
        ).fetchone()
        assert state is not None and str(state[0]) == "completed"
        assert graph_paths(target) == {"src/embedded.py"}
        observed["repository_id"] = repository_id
        return {"enabled": True, "processed": 0, "created": 0, "reused": 0, "failed": 0}

    try:
        monkeypatch.setattr(graph_module, "_embed_graph_chunks", assert_committed)
        result = module._ingest_code_graph_event(provider, snapshot("atomic-embedding", "embedded"))
        assert result["embedding"]["failed"] == 0
        assert observed == {"repository_id": REPOSITORY_ID}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_private_graph_writer_survives_concurrent_shared_audit_and_query(tmp_path, monkeypatch) -> None:
    """A shared-connection helper cannot commit a paused graph transaction."""
    module, provider = load_provider("memory_wiki_private_writer", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    base = snapshot("private-base", "keep")
    base["lines"] = [{
        "file_path": "src/keep.py", "line_no": 1,
        "line_id": "line:private:keep:1", "line_text": "def keep_transaction(): pass",
    }]
    gone = snapshot("private-gone", "gone")
    entered = threading.Event()
    release = threading.Event()
    audit_done = threading.Event()
    reader_done = threading.Event()
    reader_errors = []
    outcome = {}
    try:
        module._ingest_code_graph_event(provider, {**base, "files": [*base["files"], *gone["files"]]})
        claim_id = str(provider._code_claim_add({
            "claim": "A code claim remains active unless the private graph transaction commits its deletion.",
            "topic": "code-shrinker",
            "repository_id": REPOSITORY_ID,
            "file_path": "src/gone.py",
            "content_hash": gone["files"][0]["file_hash"],
            "evidence": "private connection atomicity regression",
            "confidence": 0.95,
            "salience": 0.9,
        })["id"])
        def fail_while_reserved(*args, **kwargs):
            entered.set()
            assert release.wait(timeout=10)
            raise RuntimeError("injected private writer failure")

        monkeypatch.setattr(graph_module, "_insert_graph_rows", fail_while_reserved)

        def ingest() -> None:
            try:
                module._ingest_code_graph_event(provider, snapshot("private-fail", "keep"))
            except Exception as exc:
                outcome["error"] = exc

        def unrelated_shared_write() -> None:
            provider._audit("concurrent_graph_test", "ok", "must not commit graph writer")
            audit_done.set()

        worker = threading.Thread(target=ingest, daemon=True)
        worker.start()
        assert entered.wait(timeout=10)
        auditor = threading.Thread(target=unrelated_shared_write, daemon=True)
        auditor.start()
        # The private BEGIN IMMEDIATE holds the database writer lock.  A
        # read-path schema check uses another private connection as well and
        # must neither finish a mutation nor commit the failed graph write.
        def independent_read_paths() -> None:
            try:
                graph_module.query_code_graph(provider, {
                    "query": "private transaction", "repository_id": REPOSITORY_ID,
                })
                graph_module.code_graph_status(provider, {"repository_id": REPOSITORY_ID})
                graph_module.code_line_context(provider, {
                    "repository_id": REPOSITORY_ID, "line_id": "line:private:keep:1",
                })
                graph_module.code_graph_neighbors(provider, {
                    "repository_id": REPOSITORY_ID, "node_id": "missing-symbol",
                })
                graph_module.maybe_prefetch_code_context(
                    provider, f"{REPOSITORY_ID} function transaction"
                )
            except Exception as exc:  # pragma: no cover - asserted below
                reader_errors.append(exc)
            finally:
                reader_done.set()

        reader = threading.Thread(target=independent_read_paths, daemon=True)
        reader.start()
        # `_audit` can either wait for the private writer or return after
        # swallowing SQLITE_BUSY. Neither outcome may commit or expose the
        # private reservation before the writer reaches its rollback path.
        assert worker.is_alive()
        with sqlite3.connect(str(provider.db_path), timeout=1.0) as observer:
            assert observer.execute(
                "SELECT 1 FROM code_graph_events WHERE event_id=?", ("private-fail",)
            ).fetchone() is None
        release.set()
        worker.join(timeout=20)
        auditor.join(timeout=20)
        reader.join(timeout=20)
        assert not worker.is_alive() and not auditor.is_alive() and not reader.is_alive()
        assert reader_done.is_set() and not reader_errors
        assert isinstance(outcome.get("error"), RuntimeError)
        assert "private writer failure" in str(outcome["error"])
        assert provider._connect().execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "active"
        assert graph_paths(provider) == {"src/keep.py", "src/gone.py"}
        assert provider._connect().execute(
            "SELECT 1 FROM code_graph_events WHERE event_id=?", ("private-fail",)
        ).fetchone() is None
    finally:
        # Restore explicitly so failures do not leave the imported module
        # monkeypatched for another test in the same process.
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_newer_snapshot_cannot_receive_a_stale_embedding_claim(tmp_path, monkeypatch) -> None:
    """Embedding A holds the write lock; B cannot inherit/link A's claim."""
    module, provider = load_provider("memory_wiki_snapshot_bound_embedding", tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    first = chunk_snapshot("embedding-a", "first")
    second = chunk_snapshot("embedding-b", "second")
    entered = threading.Event()
    release = threading.Event()
    outcomes = {}
    original_add = provider._code_claim_add

    def paused_add(payload, *args, **kwargs):
        if "graph event embedding-a" in str(payload.get("evidence") or ""):
            entered.set()
            assert release.wait(timeout=15)
        return original_add(payload, *args, **kwargs)

    monkeypatch.setattr(provider, "_code_claim_add", paused_add)
    try:
        first_worker = threading.Thread(
            target=lambda: outcomes.setdefault("first", module._ingest_code_graph_event(provider, first)), daemon=True
        )
        first_worker.start()
        assert entered.wait(timeout=15)
        second_worker = threading.Thread(
            target=lambda: outcomes.setdefault("second", module._ingest_code_graph_event(provider, second)), daemon=True
        )
        second_worker.start()
        time.sleep(0.15)
        assert second_worker.is_alive(), "new snapshot wrote while stale embedding held the private writer lock"
        release.set()
        first_worker.join(timeout=30)
        second_worker.join(timeout=30)
        assert not first_worker.is_alive() and not second_worker.is_alive()
        assert outcomes["first"]["embedding"]["failed"] == 0
        assert outcomes["second"]["embedding"]["failed"] == 0
        row = provider._connect().execute(
            "SELECT c.embedding_claim_id,m.commit_sha,m.content_hash,c.graph_event_id "
            "FROM code_graph_chunks c JOIN code_claim_metadata m ON m.claim_id=c.embedding_claim_id "
            "WHERE c.repository_id=? AND c.chunk_id='shared-chunk'",
            (REPOSITORY_ID,),
        ).fetchone()
        assert row is not None
        assert str(row[0])
        assert str(row[1]) == second["commit_sha"]
        assert str(row[2]) == second["chunks"][0]["content_hash"]
        assert str(row[3]) == "embedding-b"
        active = provider._connect().execute(
            "SELECT COUNT(*) FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id "
            "WHERE c.status='active' AND m.repository_id=? AND m.file_path=? AND m.claim_type='code_graph_chunk'",
            (REPOSITORY_ID, second["files"][0]["file_path"]),
        ).fetchone()
        assert int(active[0]) == 1
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_repeated_unchanged_full_snapshot_reuses_active_chunk_claim(tmp_path, monkeypatch) -> None:
    """A file hash match must not archive its own chunk-level content claim."""
    module, provider = load_provider("memory_wiki_unchanged_chunk_claim", tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    first = chunk_snapshot("unchanged-a", "same")
    second = chunk_snapshot("unchanged-b", "same")
    try:
        initial = module._ingest_code_graph_event(provider, first)
        first_claim = provider._connect().execute(
            "SELECT embedding_claim_id FROM code_graph_chunks WHERE repository_id=? AND chunk_id='shared-chunk'",
            (REPOSITORY_ID,),
        ).fetchone()[0]
        assert first_claim and initial["embedding"]["created"] == 1
        repeated = module._ingest_code_graph_event(provider, second)
        row = provider._connect().execute(
            "SELECT embedding_claim_id FROM code_graph_chunks WHERE repository_id=? AND chunk_id='shared-chunk'",
            (REPOSITORY_ID,),
        ).fetchone()
        assert repeated["invalidated_claims"] == 0
        assert repeated["embedding"]["reused"] == 1
        assert str(row[0]) == str(first_claim)
        assert provider._connect().execute("SELECT status FROM claims WHERE id=?", (first_claim,)).fetchone()[0] == "active"
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_secret_chunk_preparation_happens_before_private_embedding_writer(tmp_path, monkeypatch) -> None:
    """A secret quarantine never tries to open a second writer under graph BEGIN."""
    module, provider = load_provider("memory_wiki_secret_chunk_writer", tmp_path, monkeypatch)
    event = chunk_snapshot("secret-chunk-writer", "secret")
    raw_secret = "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    # First create a normal pending graph row, then model a legacy database
    # containing raw text from a release before ingress redaction.
    initial = module._ingest_code_graph_event(provider, event)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    payload_hash = str(provider._connect().execute(
        "SELECT payload_hash FROM code_graph_events WHERE event_id=?", (event["event_id"],)
    ).fetchone()[0])
    provider._connect().execute(
        "UPDATE code_graph_chunks SET embedding_text=? WHERE repository_id=? AND chunk_id=?",
        (raw_secret, REPOSITORY_ID, "shared-chunk"),
    )
    provider._connect().commit()
    assert initial["embedding"]["enabled"] is False
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_EMBED", "1")
    # The graph writer uses a private 30-second busy timeout.  Make the shared
    # connection fail quickly so the old graph-BEGIN -> quarantine-writer order
    # is deterministically observable rather than delaying this regression test.
    provider._connect().execute("PRAGMA busy_timeout=100")
    observed = []
    original_quarantine = provider._quarantine_secret

    def quarantine_probe(*args, **kwargs):
        probe = module.sqlite3.connect(str(provider.db_path), timeout=0.1)
        try:
            probe.execute("PRAGMA busy_timeout=100")
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
            observed.append("writer_available")
        finally:
            probe.close()
        return original_quarantine(*args, **kwargs)

    try:
        monkeypatch.setattr(provider, "_quarantine_secret", quarantine_probe)
        # This test isolates the quarantine writer; the secret-index path has
        # its own local-vault dependency and is not needed to prove lock order.
        monkeypatch.setattr(provider, "_make_secret_index_from_raw", lambda *_args, **_kwargs: "")
        result = graph_module._embed_graph_chunks(
            provider, REPOSITORY_ID, event["commit_sha"], event["event_id"], [],
            pending_only=True, expected_event_id=event["event_id"], expected_payload_hash=payload_hash,
        )
        assert result["created"] == 1, result
        assert observed == ["writer_available"]
        claim = provider._connect().execute(
            "SELECT claim,evidence FROM claims WHERE topic='code-intelligence'"
        ).fetchone()
        assert claim is not None
        assert raw_secret not in str(claim["claim"]) + str(claim["evidence"])
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_graph_redacts_source_before_sqlite_fts_output_and_reranking(tmp_path, monkeypatch) -> None:
    """Code graph is navigation-only and never becomes a credential copy."""
    module, provider = load_provider("memory_wiki_graph_secret_boundary", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_RERANK", "1")
    monkeypatch.setenv("MEMORY_WIKI_CODE_GRAPH_PREFETCH", "1")
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    marker = "graph-secret-boundary-marker"
    event = chunk_snapshot("graph-secret-boundary", "secret-boundary")
    event["root"] = f"C:/repos/{marker}/{token}"
    event["files"][0]["imports"] = [f"Bearer {token} {marker}"]
    event["symbols"] = [{
        "symbol_id": "secret_symbol", "file_path": event["files"][0]["file_path"],
        "qualified_name": marker, "signature": f"def {marker}(token='{token}')",
        "contract": {"description": marker, "credential": token}, "search_text": f"{marker} {token}",
        "start_line": 1, "end_line": 1,
    }]
    raw_chunk = f"{marker} token={token}"
    event["chunks"][0]["symbol_id"] = "secret_symbol"
    event["chunks"][0]["chunk_text"] = raw_chunk
    event["chunks"][0]["embedding_text"] = raw_chunk
    event["chunks"][0]["search_text"] = raw_chunk
    event["chunks"][0].pop("content_hash", None)
    event["lines"] = [{
        "file_path": event["files"][0]["file_path"], "line_no": 1,
        "line_text": f"{marker} {token}", "symbol_id": "secret_symbol", "chunk_id": "shared-chunk",
        "flags": f"token={token}",
    }]
    event["edges"] = [{
        "edge_id": "secret-edge", "source_id": "secret_symbol", "target_id": "secret_symbol",
        "predicate": "references", "source_file": event["files"][0]["file_path"],
        "target_file": event["files"][0]["file_path"], "evidence": f"{marker} {token}",
    }]
    rerank_inputs = []

    def capture_rerank(_query, rows, _mode):
        rerank_inputs.extend(rows)
        return rows

    try:
        monkeypatch.setattr(provider, "_rerank_rows", capture_rerank)
        raw_hash = hashlib.sha256(raw_chunk.encode()).hexdigest()
        result = module._ingest_code_graph_event(provider, event)
        assert result["status"] == "completed"
        stored = provider._connect()
        for table in (
            "code_graph_repositories", "code_graph_files", "code_graph_symbols", "code_graph_chunks",
            "code_graph_lines", "code_graph_edges", "code_graph_events", "code_graph_symbols_fts",
            "code_graph_chunks_fts", "code_graph_lines_fts",
        ):
            rows = stored.execute(f"SELECT * FROM {table}").fetchall()
            assert token not in repr([dict(row) for row in rows]), table
        row = stored.execute("SELECT content_hash FROM code_graph_chunks").fetchone()
        assert row is not None and str(row[0]) == raw_hash
        graph_result = graph_module.query_code_graph(provider, {
            "query": marker, "repository_id": REPOSITORY_ID, "limit": 12,
        })
        line_result = graph_module.code_line_context(provider, {
            "repository_id": REPOSITORY_ID, "file_path": event["files"][0]["file_path"], "line_no": 1,
        })
        neighbour_result = graph_module.code_graph_neighbors(provider, {
            "repository_id": REPOSITORY_ID, "node_id": "secret_symbol",
        })
        status_result = graph_module.code_graph_status(provider, {"repository_id": REPOSITORY_ID})
        prefetch = graph_module.maybe_prefetch_code_context(provider, f"{REPOSITORY_ID} {marker}")
        assert token not in repr((graph_result, line_result, neighbour_result, status_result, prefetch))
        assert rerank_inputs and token not in repr(rerank_inputs)
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_v1_raw_payload_digest_replay_and_line_only_snapshot_lifecycle(tmp_path, monkeypatch) -> None:
    """Legacy raw v1 events deduplicate, and synthetic file ownership expires claims."""
    module, provider = load_provider("memory_wiki_legacy_raw_and_line_only", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    legacy = snapshot("legacy-raw-event", "legacy")
    legacy["files"][0]["file_path"] = r".\src\legacy.py"
    raw_digest = graph_module._sha(graph_module._json(legacy))
    line_only = {
        "event_version": 2,
        "type": "code_graph_snapshot",
        "graph_schema_version": 1,
        "producer": "code-shrinker",
        "repository_id": REPOSITORY_ID,
        "event_id": "line-only-before",
        "snapshot_mode": "full",
        "commit_sha": hashlib.sha1(b"line-only-before").hexdigest(),
        "lines": [{"file_path": "src/orphan.py", "line_no": 1, "line_text": "def orphan(): pass"}],
    }
    try:
        provider._connect().execute(
            "INSERT INTO code_graph_events(event_id,repository_id,payload_hash,payload_hash_version,snapshot_mode,status,stats_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("legacy-raw-event", REPOSITORY_ID, raw_digest, 1, "full", "completed", '{"legacy":true}', 1),
        )
        provider._connect().commit()
        deduplicated = module._ingest_code_graph_event(provider, legacy)
        assert deduplicated["deduplicated"] is True and deduplicated["legacy"] is True

        module._ingest_code_graph_event(provider, line_only)
        assert graph_paths(provider) == {"src/orphan.py"}
        claim_id = str(provider._code_claim_add({
            "claim": "Line-only snapshots own their synthetic file path and archive stale repository claims.",
            "topic": "code-shrinker",
            "repository_id": REPOSITORY_ID,
            "file_path": "src/orphan.py",
            "content_hash": hashlib.sha256(b"orphan claim").hexdigest(),
            "evidence": "full snapshot lifecycle regression",
            "confidence": 0.95,
            "salience": 0.9,
        })["id"])
        empty = {**line_only, "event_id": "line-only-after", "commit_sha": hashlib.sha1(b"line-only-after").hexdigest(), "lines": []}
        result = module._ingest_code_graph_event(provider, empty)
        assert result["invalidated_claims"] == 1
        assert provider._connect().execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()[0] == "archived"
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_graph_redacts_secret_bearing_identity_and_untrusted_hash_fields(tmp_path, monkeypatch) -> None:
    """Relational keys stay usable without becoming a secret-bearing graph copy."""
    module, provider = load_provider("memory_wiki_graph_identity_redaction", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repo = f"repo-{token}"
    raw_path = f"src/{token}.py"
    raw_symbol = f"symbol-{token}"
    try:
        result = module._ingest_code_graph_event(provider, {
            "event_version": 2,
            "type": "code_graph_snapshot",
            "graph_schema_version": 1,
            "producer": "code-shrinker",
            "repository_id": raw_repo,
            "event_id": f"event-{token}",
            "snapshot_mode": "full",
            # These names are producer metadata, not proof of a digest.  They
            # must receive the same redaction treatment as ordinary text.
            "snapshot_hash": token,
            "files": [{"file_path": raw_path, "file_hash": token, "line_count": 1}],
            "symbols": [{
                "symbol_id": raw_symbol, "file_path": raw_path,
                "qualified_name": "identity_redaction", "start_line": 1, "end_line": 1,
            }],
            "chunks": [{
                "chunk_id": f"chunk-{token}", "file_path": raw_path, "symbol_id": raw_symbol,
                "qualified_name": "identity_redaction", "start_line": 1, "end_line": 1,
                "chunk_text": "identity redaction navigation text",
            }],
            "lines": [{
                "file_path": raw_path, "line_no": 1, "line_id": f"line-{token}",
                "anchor_hash": token, "line_text": "identity redaction navigation text",
                "symbol_id": raw_symbol, "chunk_id": f"chunk-{token}",
            }],
            "edges": [{
                "edge_id": f"edge-{token}", "source_id": raw_symbol, "target_id": raw_symbol,
                "source_file": raw_path, "target_file": raw_path, "predicate": "references",
                "evidence": "identity redaction navigation text",
            }],
        })
        stored = provider._connect()
        for table in (
            "code_graph_repositories", "code_graph_files", "code_graph_symbols", "code_graph_chunks",
            "code_graph_lines", "code_graph_edges", "code_graph_events", "code_graph_symbols_fts",
            "code_graph_chunks_fts", "code_graph_lines_fts",
        ):
            rows = stored.execute(f"SELECT * FROM {table}").fetchall()
            assert token not in repr([dict(row) for row in rows]), table

        # The caller may still address the graph with its source-side identity;
        # lookup maps it to the deterministic opaque storage key.
        status = graph_module.code_graph_status(provider, {"repository_id": raw_repo})
        # The project scope uses the source-side key; the query boundary maps
        # both it and the request to the same opaque storage identity.
        provider.project_scope = raw_repo
        query = graph_module.query_code_graph(provider, {
            "query": "identity redaction", "repository_id": raw_repo, "limit": 3,
        })
        context = graph_module.code_line_context(provider, {
            "repository_id": raw_repo, "file_path": raw_path, "line_no": 1,
        })
        assert status["totals"]["files"] == 1
        assert query["results"]
        assert len(context["lines"]) == 1
        assert token not in repr((result, status, query, context))

        # A delta delete uses the same opaque path mapping as the snapshot;
        # otherwise a secret-bearing filename would become undeletable.
        module._ingest_code_graph_event(provider, {
            "event_version": 2,
            "type": "code_graph_snapshot",
            "graph_schema_version": 1,
            "producer": "code-shrinker",
            "repository_id": raw_repo,
            "event_id": f"delete-{token}",
            "snapshot_mode": "delta",
            "deleted_files": [raw_path],
        })
        assert graph_module.code_graph_status(provider, {"repository_id": raw_repo})["totals"]["files"] == 0
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_secret_scrub_migrates_legacy_graph_identity_columns(tmp_path, monkeypatch) -> None:
    """The maintenance scrub removes historic raw graph keys and rebuilds FTS."""
    module, provider = load_provider("memory_wiki_legacy_graph_identity_scrub", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repo = f"repo-{token}"
    raw_path = f"src/{token}.py"
    raw_symbol = f"symbol-{token}"
    try:
        module._ingest_code_graph_event(provider, {
            "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
            "producer": "code-shrinker", "repository_id": "legacy-repo", "event_id": "legacy-event",
            "snapshot_mode": "full",
            "files": [{"file_path": "src/legacy.py", "file_hash": hashlib.sha256(b"legacy").hexdigest(), "line_count": 1}],
            "symbols": [{"symbol_id": "legacy-symbol", "file_path": "src/legacy.py", "qualified_name": "legacy", "start_line": 1, "end_line": 1}],
            "chunks": [{"chunk_id": "legacy-chunk", "file_path": "src/legacy.py", "symbol_id": "legacy-symbol", "start_line": 1, "end_line": 1, "chunk_text": "legacy navigation text"}],
            "lines": [{"file_path": "src/legacy.py", "line_no": 1, "line_id": "legacy-line", "line_text": "legacy navigation text", "symbol_id": "legacy-symbol", "chunk_id": "legacy-chunk"}],
            "edges": [{"edge_id": "legacy-edge", "source_id": "legacy-symbol", "target_id": "legacy-symbol", "source_file": "src/legacy.py", "target_file": "src/legacy.py", "predicate": "references"}],
        })
        conn = provider._connect()
        # Model a database written before graph-identity ingress redaction.
        conn.execute("UPDATE code_graph_repositories SET repository_id=?", (raw_repo,))
        conn.execute("UPDATE code_graph_files SET repository_id=?,file_path=?", (raw_repo, raw_path))
        conn.execute("UPDATE code_graph_symbols SET repository_id=?,symbol_id=?,file_path=?", (raw_repo, raw_symbol, raw_path))
        conn.execute("UPDATE code_graph_chunks SET repository_id=?,chunk_id=?,file_path=?,symbol_id=?,graph_event_id=?", (raw_repo, f"chunk-{token}", raw_path, raw_symbol, f"event-{token}"))
        conn.execute("UPDATE code_graph_lines SET repository_id=?,file_path=?,line_id=?,symbol_id=?,chunk_id=?", (raw_repo, raw_path, f"line-{token}", raw_symbol, f"chunk-{token}"))
        conn.execute("UPDATE code_graph_edges SET repository_id=?,edge_id=?,source_id=?,target_id=?,source_file=?,target_file=?", (raw_repo, f"edge-{token}", raw_symbol, raw_symbol, raw_path, raw_path))
        conn.execute("UPDATE code_graph_events SET event_id=?,repository_id=?", (f"event-{token}", raw_repo))
        conn.commit()

        with conn:
            scrubbed = graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
        assert scrubbed["fields"] >= 9
        for table in (
            "code_graph_repositories", "code_graph_files", "code_graph_symbols", "code_graph_chunks",
            "code_graph_lines", "code_graph_edges", "code_graph_events", "code_graph_symbols_fts",
            "code_graph_chunks_fts", "code_graph_lines_fts",
        ):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            assert token not in repr([dict(row) for row in rows]), table
        # Lookups still accept a caller's source-side identity after migration.
        context = graph_module.code_line_context(provider, {
            "repository_id": raw_repo, "file_path": raw_path, "line_no": 1,
        })
        assert len(context["lines"]) == 1
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_opaque_graph_identity_migrates_once_then_survives_repeated_secret_scrubs(tmp_path, monkeypatch) -> None:
    """Maintenance upgrades v1 once and never hashes its registered v2 alias again."""
    module, provider = load_provider("memory_wiki_opaque_identity_idempotence", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repo = f"repo-{token}"
    raw_path = f"src/{token}.py"
    try:
        module._ingest_code_graph_event(provider, {
            "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
            "producer": "code-shrinker", "repository_id": raw_repo, "event_id": f"event-{token}",
            "snapshot_mode": "full",
            "files": [{"file_path": raw_path, "file_hash": hashlib.sha256(b"source").hexdigest()}],
        })
        conn = provider._connect()
        before = str(conn.execute("SELECT repository_id FROM code_graph_repositories").fetchone()[0])
        with conn:
            first = graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=7)
        after_first = str(conn.execute("SELECT repository_id FROM code_graph_repositories").fetchone()[0])
        with conn:
            second = graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=7)
        after_second = str(conn.execute("SELECT repository_id FROM code_graph_repositories").fetchone()[0])

        assert before != after_first
        assert after_first == after_second
        assert first["complete"] is True and second["complete"] is True
        assert graph_module.code_graph_status(provider, {"repository_id": raw_repo})["totals"]["files"] == 1
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_live_raw_reingest_after_v2_migration_reuses_the_existing_graph_namespace(tmp_path, monkeypatch) -> None:
    """A fresh raw snapshot after scrub cannot fork v1 rows from their v2 aliases."""
    module, provider = load_provider("memory_wiki_v2_live_reingest", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repo = f"repo-{token}"
    raw_path = f"src/{token}.py"
    raw_symbol = f"symbol-{token}"
    raw_event = f"event-{token}"
    try:
        first = {
            "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
            "producer": "code-shrinker", "repository_id": raw_repo, "event_id": raw_event,
            "snapshot_mode": "full", "commit_sha": hashlib.sha1(b"v2-first").hexdigest(),
            "files": [{"file_path": raw_path, "file_hash": hashlib.sha256(b"v2-first").hexdigest(), "line_count": 1}],
            "symbols": [{"symbol_id": raw_symbol, "file_path": raw_path, "qualified_name": "v2.live", "start_line": 1, "end_line": 1}],
        }
        module._ingest_code_graph_event(provider, first)
        conn = provider._connect()
        v1_repository_id = str(conn.execute(
            "SELECT repository_id FROM code_graph_repositories"
        ).fetchone()[0])
        with conn:
            graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
        v2_repository_id = str(conn.execute(
            "SELECT repository_id FROM code_graph_repositories"
        ).fetchone()[0])
        assert v1_repository_id != v2_repository_id
        assert provider._code_graph_identity(raw_repo) == v2_repository_id

        # This is deliberately a new event ID: it exercises a real post-scrub
        # live write, not only the original event's deduplication path.
        second = {
            **first,
            "event_id": f"reingest-{token}",
            "commit_sha": hashlib.sha1(b"v2-second").hexdigest(),
            "files": [{"file_path": raw_path, "file_hash": hashlib.sha256(b"v2-second").hexdigest(), "line_count": 1}],
        }
        result = module._ingest_code_graph_event(provider, second)
        assert result["deduplicated"] is False
        rows = conn.execute(
            "SELECT repository_id FROM code_graph_repositories"
        ).fetchall()
        assert [str(row[0]) for row in rows] == [v2_repository_id]
        assert conn.execute(
            "SELECT COUNT(*) FROM code_graph_files WHERE repository_id=?",
            (v2_repository_id,),
        ).fetchone()[0] == 1
        event_repositories = {
            str(row[0]) for row in conn.execute(
                "SELECT repository_id FROM code_graph_events"
            ).fetchall()
        }
        assert event_repositories == {v2_repository_id}
        assert graph_module.code_graph_status(provider, {
            "repository_id": raw_repo,
        })["totals"]["files"] == 1
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_graph_secret_scrub_pages_past_first_5000_legacy_rows(tmp_path, monkeypatch) -> None:
    """A legacy raw identity after the first batch must not be stranded forever."""
    module, provider = load_provider("memory_wiki_graph_scrub_paging", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    try:
        conn = provider._connect()
        conn.executemany(
            "INSERT INTO code_graph_files(repository_id,file_path,updated_at) VALUES(?,?,?)",
            [("legacy-paging", f"src/{index}.py", 1) for index in range(5000)],
        )
        conn.execute(
            "INSERT INTO code_graph_files(repository_id,file_path,updated_at) VALUES(?,?,?)",
            ("legacy-paging", f"src/{token}.py", 1),
        )
        conn.commit()

        with conn:
            scrubbed = graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=97)
        last_path = str(conn.execute(
            "SELECT file_path FROM code_graph_files WHERE rowid=5001"
        ).fetchone()[0])
        assert scrubbed["complete"] is True
        assert scrubbed["batches"] > 2
        assert token not in last_path
        assert last_path.startswith("redacted-graph-id-")
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_code_claim_and_patch_event_identity_mapping_stays_consistent(tmp_path, monkeypatch) -> None:
    """Raw source-side keys must address opaque code-claim metadata everywhere."""
    module, provider = load_provider("memory_wiki_code_claim_identity_mapping", tmp_path, monkeypatch)
    # The fixture deliberately uses a credential-shaped value to exercise the
    # redaction/opaque-ID boundary.  Secret-broker persistence is a separate
    # integration contract and is absent from this hermetic graph test.
    provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repo = f"repo-{token}"
    raw_path = f"src/{token}.py"
    raw_symbol = f"symbol-{token}"
    try:
        def add_active_claim(claim_id: str, content: bytes) -> None:
            conn = provider._connect()
            timestamp = int(time.time())
            content_hash = hashlib.sha256(content).hexdigest()
            safe_repo = provider._code_graph_identity(raw_repo)
            safe_path = provider._code_graph_identity(raw_path)
            safe_symbol = provider._code_graph_identity(raw_symbol)
            conn.execute(
                "INSERT INTO claims(id,claim,topic,created_at,updated_at,freshness_at,hash) VALUES(?,?,?,?,?,?,?)",
                (claim_id, f"Persisted code claim {claim_id}", "code-intelligence", timestamp, timestamp, timestamp, claim_id),
            )
            conn.execute(
                "INSERT INTO code_claim_metadata(claim_id,repository_id,file_path,symbol_id,content_hash) VALUES(?,?,?,?,?)",
                (claim_id, safe_repo, safe_path, safe_symbol, content_hash),
            )
            conn.commit()

        first_id = "claim-identity-first"
        add_active_claim(first_id, b"first")
        assert len(provider._code_claim_query({
            "repository_id": raw_repo, "file_path": raw_path, "symbol_id": raw_symbol,
        })["claims"]) == 1
        assert provider._symbol_history({
            "repository_id": raw_repo, "symbol_id": raw_symbol,
        })["history"]
        assert provider._repository_context({"repository_id": raw_repo})["claims"]

        invalidated = provider._invalidate_revision({
            "repository_id": raw_repo, "file_path": raw_path,
            "new_content_hash": hashlib.sha256(b"first-new").hexdigest(),
        })
        assert invalidated["invalidated"] == 1

        # Model the deployed upgrade boundary before a fresh live patch: the
        # historic manually-written v1 rows become registered v2 aliases and
        # later raw source input must address those exact rows.
        with provider._connect() as conn:
            graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
            graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)

        second_id = "claim-identity-second"
        add_active_claim(second_id, b"second")
        inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
        inbox.mkdir(parents=True, exist_ok=True)
        patch = {
            "event_version": 1, "type": "patch_applied", "producer": "code-shrinker",
            "event_id": "patch-identity-event", "repository_id": raw_repo, "patch_id": "patch-identity",
            # This fixture verifies the accepted patch/ledger path.  A plain
            # low-context outcome is intentionally review-queued and must not
            # invalidate code claims before it is made durable.
            "outcome": "verified applied", "changed_files": [raw_path], "changed_symbols": [raw_symbol],
            "new_content_hash": hashlib.sha256(b"second-new").hexdigest(),
        }
        (inbox / "identity-patch.json").write_text(json.dumps(patch), encoding="utf-8")
        drained = provider._drain_code_shrinker_events(limit=1)

        assert drained["processed"] == 1 and drained["failed"] == 0, drained
        assert provider._connect().execute(
            "SELECT status FROM claims WHERE id=?", (second_id,)
        ).fetchone()[0] == "archived"
        stored = provider._connect().execute(
            "SELECT repository_id,file_path,symbol_id FROM code_claim_metadata WHERE claim_id=?",
            (second_id,),
        ).fetchone()
        assert token not in repr(tuple(stored))
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_source_event_id_migrates_with_code_claim_exactly_once_ledger(tmp_path, monkeypatch) -> None:
    """Raw source input must still reach its migrated v2 collision guard."""
    module, provider = load_provider("memory_wiki_source_event_v2_ledger", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    imitation = "redacted-graph-id-" + "e" * 64
    request = {
        "claim": "The source-event ledger preserves exactly-once code claim processing across graph alias migration.",
        "topic": "code-intelligence",
        "repository_id": "repo-source-event-ledger",
        "file_path": "src/source_event.py",
        "symbol_id": "source_event_guard",
        "content_hash": hashlib.sha256(b"source-event-ledger").hexdigest(),
        "source_event_id": imitation,
    }
    try:
        first = provider._code_claim_add(request)
        assert first.get("deduplicated") is False, first
        v1_event_id = str(provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='code-shrinker'"
        ).fetchone()[0])
        assert v1_event_id != imitation

        with provider._connect() as conn:
            graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
        v2_event_id = str(provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='code-shrinker'"
        ).fetchone()[0])
        assert v2_event_id != v1_event_id
        assert provider._code_graph_identity(imitation) == v2_event_id

        duplicate = provider._code_claim_add(request)
        assert duplicate.get("deduplicated") is True, duplicate
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM integration_events WHERE producer='code-shrinker'"
        ).fetchone()[0] == 1

        checkpoint = provider._journal_checkpoint("source-event-v2-ledger")
        rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        assert rebuilt["failed"] == 0, rebuilt
        assert provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='code-shrinker'"
        ).fetchone()[0] == v2_event_id

        changed = {**request, "claim": request["claim"] + " Changed payload."}
        with pytest.raises(ValueError, match="source_event_id was already used"):
            provider._code_claim_add(changed)
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_live_patch_inbox_aliases_match_raw_code_claim_before_and_after_migration(tmp_path, monkeypatch) -> None:
    """The internal sanitized patch handoff must not double-alias an ID."""
    module, provider = load_provider("memory_wiki_live_patch_alias_handoff", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    fake = "redacted-graph-id-" + "f" * 64
    expected_v1 = graph_module._opaque_graph_id_v1(fake)
    patch = {
        "event_version": 1,
        "type": "patch_applied",
        "producer": "code-shrinker",
        "event_id": fake,
        "repository_id": "repo-live-patch-alias",
        # ``verified`` is a durable-quality hint so this fixture exercises the
        # committed patch/ledger path instead of the separate review queue.
        "patch_id": "patch-live-patch-alias-verified",
        "outcome": "applied",
        "changed_files": [fake],
        "changed_symbols": ["live_patch_symbol"],
    }
    try:
        inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "first-patch.json").write_text(json.dumps(patch), encoding="utf-8")
        first = provider._drain_code_shrinker_events(limit=1)
        assert first["processed"] == 1 and first["failed"] == 0, first

        patch_row = provider._connect().execute(
            "SELECT repository_id,patch_id,source_event_id,changed_files_json,changed_symbols_json "
            "FROM patch_outcomes"
        ).fetchone()
        assert patch_row is not None
        assert tuple(patch_row[:3]) == (
            "repo-live-patch-alias", "patch-live-patch-alias-verified", expected_v1,
        )
        assert json.loads(patch_row[3]) == [expected_v1]
        assert json.loads(patch_row[4]) == ["live_patch_symbol"]
        assert provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='mcp-code-shrinker'"
        ).fetchone()[0] == expected_v1

        claim = provider._code_claim_add({
            "claim": "A direct code claim shares the patch inbox identity namespace before alias migration.",
            "topic": "code-intelligence",
            "repository_id": "repo-live-patch-alias",
            "file_path": fake,
            "symbol_id": "live_patch_symbol",
            "content_hash": hashlib.sha256(b"claim-alias").hexdigest(),
            "source_event_id": fake,
        })
        assert claim.get("deduplicated") is False, claim
        metadata = provider._connect().execute(
            "SELECT repository_id,file_path,symbol_id FROM code_claim_metadata WHERE claim_id=?",
            (claim["id"],),
        ).fetchone()
        assert tuple(metadata) == (
            "repo-live-patch-alias", expected_v1, "live_patch_symbol",
        )

        with provider._connect() as conn:
            graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
        expected_v2 = graph_module._opaque_graph_id_v2(expected_v1)
        assert provider._code_graph_identity(fake) == expected_v2
        assert provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='mcp-code-shrinker'"
        ).fetchone()[0] == expected_v2

        # A live raw caller still resolves F → v1(F) → v2(v1(F)); it must
        # reuse the migrated code-claim ledger instead of inserting a second
        # metadata row under an alias derived from v1(F) a second time.
        reingested_claim = provider._code_claim_add({
            "claim": "A direct code claim shares the patch inbox identity namespace before alias migration.",
            "topic": "code-intelligence",
            "repository_id": "repo-live-patch-alias",
            "file_path": fake,
            "symbol_id": "live_patch_symbol",
            "content_hash": hashlib.sha256(b"claim-alias").hexdigest(),
            "source_event_id": fake,
        })
        assert reingested_claim.get("deduplicated") is True, reingested_claim
        assert provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='code-shrinker'"
        ).fetchone()[0] == expected_v2

        (inbox / "second-patch.json").write_text(json.dumps(patch), encoding="utf-8")
        replayed = provider._drain_code_shrinker_events(limit=1)
        assert replayed["processed"] == 1 and replayed["deduplicated"] == 1, replayed
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM patch_outcomes"
        ).fetchone()[0] == 1
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM integration_events WHERE producer='mcp-code-shrinker'"
        ).fetchone()[0] == 1
        persisted = provider._connect().execute(
            "SELECT source_event_id,changed_files_json FROM patch_outcomes"
        ).fetchone()
        assert persisted is not None
        assert tuple(persisted) == (expected_v2, json.dumps([expected_v2]))
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_prepared_code_claim_recanonicalizes_after_v2_migration_before_write(tmp_path, monkeypatch) -> None:
    """A checkpoint between prepare and write cannot enroll a stale v1 alias."""
    module, provider = load_provider("memory_wiki_prepare_write_v2_toctou", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repository_id = f"repo-{token}"
    raw_file_path = f"src/{token}.py"
    raw_symbol_id = f"symbol-{token}"
    raw_source_event_id = f"event-{token}"
    request = {
        "claim": "The prepared code claim must recompute its identity after the graph migration boundary.",
        "topic": "code-intelligence",
        "repository_id": raw_repository_id,
        "file_path": raw_file_path,
        "symbol_id": raw_symbol_id,
        "content_hash": hashlib.sha256(b"prepare-write-toctou").hexdigest(),
        "source_event_id": raw_source_event_id,
        "producer": "code-shrinker",
    }
    try:
        # `_prepare_code_claim` necessarily runs before the private graph
        # writer starts, so this models a checkpoint scrub acquiring the
        # migration boundary in the otherwise-racy interval.
        prepared = provider._prepare_code_claim(request)
        old_values = (
            prepared["repository_id"],
            prepared["file_path"],
            prepared["symbol_id"],
            prepared["source_event_id"],
            prepared["prepared"]["cid"],
        )
        with provider._connect() as conn:
            graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)

        result = provider._code_claim_add(request, _prepared_code_claim=prepared)
        assert result.get("status") == "committed", result
        expected_values = (
            provider._code_graph_identity(raw_repository_id),
            provider._code_graph_identity(raw_file_path),
            provider._code_graph_identity(raw_symbol_id),
            provider._code_graph_identity(raw_source_event_id),
        )
        assert all(value not in expected_values for value in old_values[:4])
        assert result["id"] != old_values[4]
        metadata = provider._connect().execute(
            "SELECT repository_id,file_path,symbol_id FROM code_claim_metadata WHERE claim_id=?",
            (result["id"],),
        ).fetchone()
        assert metadata is not None
        assert tuple(metadata) == expected_values[:3]
        event = provider._connect().execute(
            "SELECT event_id FROM integration_events WHERE producer='code-shrinker'"
        ).fetchone()
        assert event is not None and str(event[0]) == expected_values[3]
        for value in expected_values:
            row = provider._connect().execute(
                "SELECT provenance_version FROM code_graph_identity_provenance WHERE opaque_id=?",
                (value,),
            ).fetchone()
            assert row is not None and int(row[0]) >= 2
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_patch_outcome_recanonicalizes_after_v2_migration_before_write(tmp_path, monkeypatch) -> None:
    """Patch provenance and metadata advance together at the writer boundary."""
    module, provider = load_provider("memory_wiki_patch_write_v2_toctou", tmp_path, monkeypatch)
    graph_module = sys.modules[module.__name__ + ".code_knowledge_graph"]
    provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    raw_repository_id = f"repo-{token}"
    raw_patch_id = f"patch-{token}"
    raw_source_event_id = f"event-{token}"
    raw_file_path = f"src/{token}.py"
    raw_symbol_id = f"symbol-{token}"
    request = {
        "repository_id": raw_repository_id,
        "patch_id": raw_patch_id,
        "source_event_id": raw_source_event_id,
        "outcome": "applied after verified integration and regression testing",
        "changed_files": [raw_file_path],
        "changed_symbols": [raw_symbol_id],
        "new_content_hash": hashlib.sha256(b"patch-write-toctou").hexdigest(),
        "validation_report": {"status": "valid"},
        "rollback_steps": "Restore the verified prior revision if the validation report changes.",
    }
    original_prepare = provider._prepare_claim
    migrated = False

    def migrate_after_prepare(*args, **kwargs):
        nonlocal migrated
        prepared = original_prepare(*args, **kwargs)
        if not migrated:
            migrated = True
            with provider._connect() as conn:
                graph_module.scrub_code_graph_storage(provider, conn, apply=True, limit=100)
        return prepared

    try:
        # `_patch_outcome_add` maps its request before `_prepare_claim`; this
        # hook deterministically opens the race window before its writer lock.
        provider._prepare_claim = migrate_after_prepare
        result = provider._patch_outcome_add(request)
        assert migrated and result.get("structured") is True, result
        expected_values = (
            provider._code_graph_identity(raw_repository_id),
            provider._code_graph_identity(raw_patch_id),
            provider._code_graph_identity(raw_source_event_id),
            provider._code_graph_identity(raw_file_path),
            provider._code_graph_identity(raw_symbol_id),
        )
        row = provider._connect().execute(
            "SELECT repository_id,patch_id,source_event_id,changed_files_json,changed_symbols_json "
            "FROM patch_outcomes"
        ).fetchone()
        assert row is not None
        assert tuple(row[:3]) == expected_values[:3]
        assert json.loads(row[3]) == [expected_values[3]]
        assert json.loads(row[4]) == [expected_values[4]]
        metadata = provider._connect().execute(
            "SELECT repository_id,file_path,symbol_id FROM code_claim_metadata WHERE claim_id=?",
            (result["id"],),
        ).fetchone()
        assert metadata is not None and tuple(metadata) == (
            expected_values[0], expected_values[3], expected_values[4],
        )
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None
