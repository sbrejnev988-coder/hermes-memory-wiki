from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path


def load_provider(tmp_path: Path):
    os.environ["HERMES_HOME"] = str(tmp_path)
    os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
    plugin = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("memory_wiki_under_test", plugin)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("bridge-test", hermes_home=str(tmp_path))
    provider._test_module = module
    return provider


def test_patch_event_archives_old_revision_and_is_idempotent(tmp_path):
    provider = load_provider(tmp_path)
    old_hash, new_hash = "a" * 64, "b" * 64
    result = provider._code_claim_add({
        "claim": "Verified Hermes configuration runbook: function foo returns one; source revision and restore procedure were checked.",
        "topic": "code-shrinker",
        "repository_id": "owner/repo",
        "file_path": "src/a.js",
        "content_hash": old_hash,
        "symbol_id": "sym_foo",
        "symbol_revision": "rev1",
        "evidence": "verified exact source and backup restore procedure",
        "confidence": 0.95,
        "salience": 0.9,
    })
    claim_id = result["id"]
    conn = provider._connect()
    assert conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone()
    event = {
        "event_version": 1,
        "event_id": "patch:test:event-1",
        "producer": "mcp-code-shrinker",
        "type": "patch_applied",
        "repository_id": "owner/repo",
        "patch_id": "p1",
        "outcome": "applied",
        "changed_files": ["src/a.js"],
        "changed_symbols": ["sym_foo"],
        "per_file": [{"file_path": "src/a.js", "old_content_hash": old_hash, "new_content_hash": new_hash}],
        "validation_report": {"status": "valid"},
        "rollback_steps": "restore backup",
    }
    inbox = tmp_path / "context-coordination" / "inbox" / "code-shrinker"
    (inbox / "event.json").write_text(json.dumps(event), encoding="utf-8")
    assert provider._drain_code_shrinker_events()["processed"] == 1
    assert conn.execute("SELECT status FROM claims WHERE id=?", (claim_id,)).fetchone()["status"] == "archived"
    assert not conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone()
    row = conn.execute("SELECT * FROM patch_outcomes WHERE repository_id=? AND patch_id=?", ("owner/repo", "p1")).fetchone()
    assert row and row["new_content_hash"] == new_hash
    provider._rebuild_fts()
    assert not conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (claim_id,)).fetchone()
    (inbox / "event-again.json").write_text(json.dumps(event), encoding="utf-8")
    assert provider._drain_code_shrinker_events()["deduplicated"] == 1


def test_qdrant_reindex_builds_physical_collection_before_alias_switch(tmp_path):
    provider = load_provider(tmp_path)
    module = provider._test_module
    result = provider._code_claim_add({
        "claim": "Verified Hermes configuration runbook: semantic indexing and restore procedure were checked.",
        "topic": "code-shrinker",
        "repository_id": "owner/repo",
        "file_path": "src/semantic.js",
        "content_hash": "c" * 64,
        "symbol_id": "sym_semantic",
        "symbol_revision": "rev1",
        "evidence": "verified exact source and backup restore procedure",
        "confidence": 0.95,
        "salience": 0.9,
    })
    assert result.get("id")
    points = {}
    switched = []
    created = []
    module.SEMANTIC_ENABLED = True
    module._semantic_available = lambda: True
    module._ensure_collection = lambda collection=None: created.append(collection) or True
    module._embed_document = lambda text: [0.0] * module.QDRANT_VECTOR_SIZE
    module._qdrant_upsert = lambda claim_id, vector, payload, collection=None: points.setdefault(collection, set()).add(claim_id) is None or True
    module._qdrant_count = lambda collection=None: len(points.get(collection, set()))
    module._qdrant_alias_target = lambda alias=module.QDRANT_ALIAS: switched[-1] if switched else "old_collection"
    module._switch_alias = lambda collection: switched.append(collection) or True
    first = provider._reindex()
    assert first["status"] == "completed"
    assert first["alias_switched"] is True
    assert switched[-1].startswith(module.QDRANT_COLLECTION + "_")
    assert "_force_" not in switched[-1]
    forced = provider._reindex(force=True)
    assert forced["status"] == "completed"
    assert "_force_" in switched[-1]
    assert created
