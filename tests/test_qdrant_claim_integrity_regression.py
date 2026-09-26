"""Qdrant claims require physical-ID and ACL-payload proof before indexing."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    name = "memory_wiki_claim_qdrant_integrity_regression"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_claim_upsert_needs_exact_payload_readback(tmp_path, monkeypatch):
    module = _module(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "QDRANT_VECTOR_SIZE", 3)
    monkeypatch.setattr(module, "_ensure_collection", lambda *_args: True)
    calls = []

    def fake_qdrant(method, path, body=None, timeout=10.0):
        calls.append((method, path))
        if method == "PUT":
            return {"status": "ok", "result": {"status": "completed"}}
        if method == "POST" and path.endswith("/points"):
            return {"status": "ok", "result": []}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(module, "_qdrant_req", fake_qdrant)
    ok = module._qdrant_upsert(
        "c_synthetic_missing_payload", [0.0, 1.0, 0.0],
        {"id": "c_synthetic_missing_payload", "visibility_scope": "private",
         "origin_bot_id": "bot-a", "origin_session_id": "chat-a"},
        collection="synthetic_claims",
    )
    assert ok is False
    assert any(method == "POST" and path.endswith("/points") for method, path in calls)
    assert not any(path.endswith("/points/delete?wait=true") for _, path in calls)


def test_reconciliation_rejects_payload_at_wrong_physical_id(tmp_path, monkeypatch):
    module = _module(tmp_path, monkeypatch)
    claim_id = "c_synthetic_wrong_point"
    expected_id = str(module._qdrant_point_id(claim_id))
    wrong_id = "00000000-0000-4000-8000-000000000001"
    assert wrong_id != expected_id

    def fake_qdrant(method, path, body=None, timeout=10.0):
        assert method == "POST" and path.endswith("/points/scroll")
        return {"status": "ok", "result": {
            "points": [{"id": wrong_id, "payload": {
                "claim_id": claim_id, "id": claim_id,
                "visibility_scope": "private", "origin_bot_id": "bot-a",
                "origin_session_id": "chat-a", "project_id": "",
                "manifest_hash": "synthetic-manifest",
            }}],
            "next_page_offset": None,
        }}

    monkeypatch.setattr(module, "_qdrant_req", fake_qdrant)
    assert module._qdrant_claim_state("synthetic_claims") is None
