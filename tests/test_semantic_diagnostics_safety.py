"""Offline regressions for read-only diagnostics and confirmed vector deletion."""
from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import sys
import urllib.error
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_plugin(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "1")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_PROVIDER", "openrouter")
    monkeypatch.setenv("MEMORY_WIKI_EMBED_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MEMORY_WIKI_RERANK_ENABLED", "0")
    for key in ("MEMORY_WIKI_DOCUMENT_ROOTS", "MEMORY_WIKI_DOCUMENT_CACHE_DIR"):
        monkeypatch.delenv(key, raising=False)
    name = "mw_diagnostics_safety_" + tmp_path.name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def empty_provider(module, tmp_path, monkeypatch):
    provider = object.__new__(module.MemoryWikiProvider)
    provider.home = tmp_path
    provider._last_prefetch_diagnostics = {}
    monkeypatch.setattr(module.MemoryWikiProvider, "_rerank_status", lambda _self: {})
    monkeypatch.setattr(module, "_secret_context_bridge_status", lambda **kw: {})
    return provider


def test_semantic_status_does_not_create_missing_collection(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    provider = empty_provider(module, tmp_path, monkeypatch)
    monkeypatch.setattr(module, "_openrouter_health_swr", lambda: True)
    monkeypatch.setattr(module, "_openrouter_available", lambda **kwargs: True)
    seen = []

    def qdrant(method, path, body=None, **kwargs):
        seen.append((method, path))
        if method == "GET" and path in ("/collections", "/aliases"):
            return {"status": "ok", "result": {"collections": [], "aliases": []}}
        if method == "GET" and path.startswith("/collections/"):
            return None
        if method == "PUT" and path.startswith("/collections/"):
            return {"status": "ok", "result": True}
        raise AssertionError("Unexpected Qdrant call")

    monkeypatch.setattr(module, "_qdrant_req", qdrant)
    result = provider._semantic_status()
    assert result["embedding_ok"] is False
    assert seen
    assert all(method == "GET" for method, _path in seen)


def test_semantic_status_never_starts_billable_embedding_on_model_list_outage(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    provider = empty_provider(module, tmp_path, monkeypatch)
    calls = []

    def failed_model_list(request, timeout):
        calls.append(request.get_method())
        raise urllib.error.HTTPError(request.full_url, 503, "synthetic outage", {}, None)

    monkeypatch.setattr(module, "_urlopen_no_redirect", failed_model_list)
    monkeypatch.setattr(module, "_openrouter_health_swr", lambda: module._openrouter_available())
    monkeypatch.setattr(module, "_openrouter_embed", lambda *a, **kw: calls.append("POST /embeddings") or None)
    monkeypatch.setattr(module, "_qdrant_req", lambda method, path, *a, **kw: None)
    result = provider._semantic_status()
    assert result["embedding_ok"] is False
    assert "POST /embeddings" not in calls
    assert not any(value.startswith("POST") for value in calls)


def test_delete_rejects_qdrant_error_envelope(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_qdrant_req", lambda *a, **kw: {
        "status": "error", "result": {"operation_id": 101, "status": "completed"},
    })
    assert module._qdrant_delete("synthetic-id", collection="synthetic") is False
    assert module._qdrant_delete_many(["synthetic-id"], collection="synthetic") is False


@pytest.mark.parametrize("operation", [
    {"operation_id": 101, "status": "acknowledged"},
    {"operation_id": 101},
])
def test_delete_rejects_unfinished_qdrant_operation(tmp_path, monkeypatch, operation):
    module = load_plugin(monkeypatch, tmp_path)
    calls = []

    def qdrant(method, path, body=None, **kwargs):
        calls.append((method, path))
        return {"status": "ok", "result": operation}

    monkeypatch.setattr(module, "_qdrant_req", qdrant)
    assert module._qdrant_delete("synthetic-id", collection="synthetic") is False
    assert module._qdrant_delete_many(["synthetic-id"], collection="synthetic") is False
    assert calls == [("POST", "/collections/synthetic/points/delete?wait=true")] * 2


@pytest.mark.parametrize("operation", [
    {"operation_id": 101, "status": "acknowledged"},
    {"operation_id": 101},
])
def test_unfinished_claim_delete_keeps_outbox_and_target_retryable(tmp_path, monkeypatch, operation):
    module = load_plugin(monkeypatch, tmp_path)
    path = tmp_path / "memory-wiki" / "memory_wiki.sqlite3"
    module._ensure_outbox(str(path))
    endpoint = module._normalized_qdrant_endpoint()
    claim_id = "synthetic-id"
    collection = module._physical_collection_name()
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE claims(
            id TEXT PRIMARY KEY, status TEXT, normalized_claim TEXT, claim TEXT,
            topic TEXT, memory_revision INTEGER, updated_at INTEGER,
            visibility_scope TEXT, origin_bot_id TEXT, origin_session_id TEXT,
            origin_chat_hash TEXT, project_id TEXT, event_at INTEGER)""")
        target = module._record_claim_vector_target(
            db, claim_id, collection=collection, endpoint=endpoint, status="active",
        )
        module._outbox_enqueue("delete", "claim", claim_id, target, conn=db)

    response = {"operation_id": 101, "status": operation.get("status")}
    requests = []

    def qdrant(method, path, body=None, **kwargs):
        requests.append((method, path))
        assert method == "POST" and path.endswith("/points/delete?wait=true")
        return {"status": "ok", "result": {
            "operation_id": response["operation_id"],
            **({"status": response["status"]} if response["status"] else {}),
        }}

    monkeypatch.setattr(module, "_qdrant_req", qdrant)
    # A non-404 collection check cannot substitute for completion.
    monkeypatch.setattr(module, "_qdrant_collection_confirmed_absent", lambda *a: False)
    first = module._outbox_process(batch_size=1, db_path=str(path), worker_id="delete-first")
    assert first["ok"] == 0 and first["fail"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT status,attempts FROM index_outbox WHERE object_id=?",
                          (claim_id,)).fetchone() == ("pending", 1)
        assert db.execute("SELECT status FROM claim_vector_targets WHERE claim_id=?",
                          (claim_id,)).fetchone() == ("delete_pending",)
        db.execute("UPDATE index_outbox SET next_retry_at=0 WHERE object_id=?", (claim_id,))

    response["status"] = "completed"
    second = module._outbox_process(batch_size=1, db_path=str(path), worker_id="delete-retry")
    assert second["ok"] == 1 and second["fail"] == 0
    assert len(requests) == 2
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM index_outbox WHERE object_id=?",
                          (claim_id,)).fetchone() is None
        assert db.execute("SELECT status FROM claim_vector_targets WHERE claim_id=?",
                          (claim_id,)).fetchone() == ("deleted",)


def test_completed_delete_is_accepted_for_active_batch_and_historical(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    completed = {"status": "ok", "result": {"operation_id": 101, "status": "completed"}}
    monkeypatch.setattr(module, "_qdrant_req", lambda *a, **kw: completed)
    assert module._qdrant_delete("synthetic-id", collection="synthetic") is True
    assert module._qdrant_delete_many(["synthetic-id"], collection="synthetic") is True

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    monkeypatch.setattr(module, "_urlopen_no_redirect",
                        lambda *a, **kw: Response(json.dumps(completed).encode()))
    assert module._qdrant_delete_target(
        "synthetic-id", collection="synthetic", endpoint="http://127.0.0.1:6334",
    ) is True


def test_historical_delete_rejects_qdrant_error_envelope(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_qdrant_req", lambda *a, **kw: None)
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
    monkeypatch.setattr(module, "_urlopen_no_redirect", lambda *a, **kw: Response(
        b'{"status":"error","result":{"operation_id":101,"status":"completed"}}'
    ))
    assert module._qdrant_delete_target("synthetic-id", collection="synthetic",
                                          endpoint="http://127.0.0.1:6334") is False


@pytest.mark.parametrize("operation", [
    {"operation_id": 101, "status": "acknowledged"},
    {"operation_id": 101},
])
def test_historical_delete_rejects_unfinished_qdrant_operation(tmp_path, monkeypatch, operation):
    module = load_plugin(monkeypatch, tmp_path)
    requests = []

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    def old_endpoint(request, timeout):
        requests.append(request)
        return Response(json.dumps({"status": "ok", "result": operation}).encode())

    monkeypatch.setattr(module, "_urlopen_no_redirect", old_endpoint)
    assert module._qdrant_delete_target(
        "synthetic-id", collection="synthetic", endpoint="http://127.0.0.1:6334",
    ) is False
    assert len(requests) == 1
    assert requests[0].get_method() == "POST"
    assert requests[0].full_url.endswith("/collections/synthetic/points/delete?wait=true")


def test_rerank_circuit_isolated_between_profile_homes(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "RERANK_ENABLED", True)
    monkeypatch.setattr(module, "RERANK_CIRCUIT_FAILURES", 1)
    monkeypatch.setattr(module, "RERANK_RETRY_COUNT", 1)
    monkeypatch.setattr(module, "RERANK_RULES_ENABLED", False)
    monkeypatch.setattr(module, "RERANK_SKIP_EXACT_TECHNICAL", False)
    monkeypatch.setattr(module, "RERANK_ENDPOINT_VALID", True)
    monkeypatch.setattr(module, "RERANK_MIN_CANDIDATES", 3)
    monkeypatch.setattr(module, "RERANK_TOP_K", 3)
    class Cursor:
        def fetchall(self): return []
    class Conn:
        def execute(self, *args): return Cursor()
    monkeypatch.setattr(module.MemoryWikiProvider, "_connect", lambda self: Conn())
    rows = [
        {"id": f"case-{i}", "claim": f"Synthetic service preference case number {i} is documented.",
         "status": "active", "topic": "testing", "updated_at": i, "risk": "low",
         "trust_class": "fact", "score_parts": {"bm25": 0.2}}
        for i in range(3)
    ]
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
    requests = []
    def fake_urlopen(req, timeout):
        home = module._QDRANT_PROFILE_SCOPE.get()["__home"]
        requests.append(Path(home).name)
        if home.endswith("profile-a"):
            raise urllib.error.HTTPError(req.full_url, 401, "synthetic unauthorized", {}, None)
        return Response(json.dumps({"results": [
            {"index": i, "relevance_score": 0.9 - i * 0.1} for i in range(3)
        ]}).encode())
    monkeypatch.setattr(module, "_urlopen_no_redirect", fake_urlopen)
    provider = object.__new__(module.MemoryWikiProvider)
    for profile in ("profile-a", "profile-b"):
        token = module._QDRANT_PROFILE_SCOPE.set({
            "__home": str(tmp_path / profile), "__semantic_compatible": "1",
            "MEMORY_WIKI_RERANK_API_KEY": "synthetic-test-key",
        })
        try:
            assert module._rerank_api_key()
            result = module.MemoryWikiProvider._rerank_rows.__wrapped__(
                provider, "synthetic service preference query", rows, "semantic",
            )
            if profile == "profile-b":
                assert all("rerank_rank" in item for item in result)
        finally:
            module._QDRANT_PROFILE_SCOPE.reset(token)
    assert requests == ["profile-a", "profile-b"]


def test_legacy_completed_outbox_text_removed_on_schema_open(tmp_path, monkeypatch):
    module = load_plugin(monkeypatch, tmp_path)
    path = tmp_path / "memory-wiki" / "memory_wiki.sqlite3"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.executescript(module._OUTBOX_TABLE)
            conn.execute("INSERT INTO index_outbox(id,object_id,status,operation,object_type,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         ("old-completed", "synthetic-id", "completed", "embed_and_upsert", "claim", json.dumps({"text": "synthetic canary only"}), 1, 1))
    finally:
        conn.close()
    module._ensure_outbox(str(path))
    conn = sqlite3.connect(path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM index_outbox WHERE status='completed' AND json_type(payload_json,'$.text') IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
