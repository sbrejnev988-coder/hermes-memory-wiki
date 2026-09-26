"""Reindex a shared claim store without opening another consumer's text."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _shared_reindex(tmp_path, monkeypatch, *, hashed_base=False):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    base = "fixture_claims_8278d1218cc6" if hashed_base else "fixture_claims"
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_COLLECTION", base)
    monkeypatch.setenv("MEMORY_WIKI_QDRANT_ALIAS", "fixture_active")
    (tmp_path / ".env").write_text(
        "MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333\n"
        f"MEMORY_WIKI_QDRANT_COLLECTION={base}\n"
        "MEMORY_WIKI_QDRANT_ALIAS=fixture_active\n"
        "MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION=fixture_episodes\n",
        encoding="utf-8",
    )
    name = "mw_shared_reindex_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.MemoryWikiProvider, "_sync_env_metadata", lambda self: None)
    owner = module.MemoryWikiProvider()
    owner.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot")
    viewer = module.MemoryWikiProvider()
    viewer.initialize("viewer-chat", hermes_home=str(tmp_path), bot_id="viewer-bot")
    private_text = "Owner-only nebula orchid sentence."
    visible_text = "Viewer-owned network diagram sentence."
    foreign = owner._add_claim(
        private_text, topic="private", source="memory_tool:test",
        confidence=.9, salience=.9, visibility_scope="private",
    )
    visible = viewer._add_claim(
        visible_text, topic="visible", source="memory_tool:test",
        confidence=.9, salience=.9, visibility_scope="chat",
    )
    assert foreign.startswith("c_") and visible.startswith("c_")
    foreign_row = owner._connect().execute("SELECT * FROM claims WHERE id=?", (foreign,)).fetchone()
    manifest_hash = module._manifest_hash(module._embedding_manifest())
    source = module._physical_collection_name()
    source_payload = module._qdrant_claim_payload(
        foreign, foreign_row["normalized_claim"], foreign_row, manifest_hash=manifest_hash,
    )
    with owner._connect() as conn:
        module._record_claim_vector_target(
            conn, foreign, collection=source, manifest_hash=manifest_hash,
            status="active", indexed_at=module.now(),
        )
    vector = [0.5] * module.QDRANT_VECTOR_SIZE
    points = {source: {foreign: {"vector": vector, "payload": source_payload}}}
    alias = {"target": source}
    embedded = []
    requests = []
    module.SEMANTIC_ENABLED = True
    monkeypatch.setattr(module, "_semantic_available", lambda: True)
    monkeypatch.setattr(module, "_qdrant_alias_supported", lambda **_kwargs: True)
    monkeypatch.setattr(module, "_ensure_collection", lambda coll=None: module._profile_target_allowed(coll))
    monkeypatch.setattr(module, "_embed_document", lambda text: embedded.append(text) or [0.25] * module.QDRANT_VECTOR_SIZE)
    monkeypatch.setattr(module, "_qdrant_count", lambda coll=None: len(points.get(coll, {})))
    monkeypatch.setattr(module, "_qdrant_alias_target", lambda alias_name=None: alias["target"])

    def request(method, path, body=None, timeout=10.0):
        requests.append((method, path, body))
        if path == "/collections/aliases" and method == "POST":
            alias["target"] = body["actions"][-1]["create_alias"]["collection_name"]
            return {"status": "ok"}
        if path.endswith("/points") and method == "POST":
            selected = body["with_payload"]
            assert selected is True or (isinstance(selected, list) and "claim" not in selected)
            source_coll = path.split("/")[2]
            matching = [
                {"id": module._qdrant_point_id(cid),
                 **({"vector": item["vector"]} if body.get("with_vector") else {}),
                 "payload": (dict(item["payload"]) if selected is True else
                             {k: v for k, v in item["payload"].items() if k in selected})}
                for cid, item in points.get(source_coll, {}).items()
                if module._qdrant_point_id(cid) in body["ids"]
            ]
            return {"result": matching}
        if path.endswith("/points/scroll") and method == "POST":
            assert isinstance(body["with_payload"], list) and "claim" not in body["with_payload"]
            coll = path.split("/")[2]
            items = [
                {"id": module._qdrant_point_id(cid),
                 "payload": {k: v for k, v in item["payload"].items() if k in body["with_payload"]}}
                for cid, item in points.get(coll, {}).items()
            ]
            return {"result": {"points": items, "next_page_offset": None}}
        if path.endswith("/points?wait=true") and method == "PUT":
            coll = path.split("/")[2]
            for item in body["points"]:
                cid = item["payload"]["claim_id"]
                points.setdefault(coll, {})[cid] = {"vector": item["vector"], "payload": item["payload"]}
            return {"result": {"status": "completed"}}
        raise AssertionError(f"unexpected synthetic Qdrant operation: {method} {path}")

    monkeypatch.setattr(module, "_qdrant_req", request)
    return module, viewer, foreign, visible, private_text, visible_text, points, alias, embedded, requests


@pytest.mark.parametrize("hashed_base", [False, True], ids=["plain-base", "hashed-base"])
def test_acl_aware_reindex_copies_foreign_vector_without_foreign_text(tmp_path, monkeypatch, hashed_base):
    (module, viewer, foreign, visible, private_text, visible_text,
     points, alias, embedded, requests) = _shared_reindex(tmp_path, monkeypatch, hashed_base=hashed_base)
    assert json.loads(viewer.handle_tool_call("memory_wiki_health", {}))["error"] == (
        "shared_claim_scope_unavailable"
    )
    sql = []
    viewer._connect().set_trace_callback(sql.append)
    result = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {"force": True}))
    assert result.get("error") != "shared_claim_scope_unavailable", result
    assert result.get("status") == "completed", result
    target = result["collection"]
    assert target == alias["target"] and target.startswith(module._physical_collection_name() + "_force_")
    assert target.rsplit("_force_", 1)[1].isdigit()
    assert set(points[target]) == {foreign, visible}
    assert embedded == [visible_text]
    assert points[target][foreign]["vector"] == [0.5] * module.QDRANT_VECTOR_SIZE
    assert "claim" not in points[target][foreign]["payload"]
    assert points[target][foreign]["payload"]["visibility_scope"] == "private"
    assert private_text not in json.dumps(points[target][foreign]["payload"])
    assert all(private_text not in json.dumps(body) for _, _, body in requests)
    assert any(path.endswith("/points") for _, path, _ in requests)
    assert viewer._connect().execute(
        "SELECT status FROM claim_vector_targets WHERE claim_id=? AND collection=?",
        (foreign, target),
    ).fetchone()[0] == "active"
    viewer._connect().set_trace_callback(None)
    text_reads = [statement for statement in sql if re.search(
        r"SELECT\s+normalized_claim\s+FROM\s+claims", statement, re.I,
    )]
    assert text_reads and all(visible in statement and foreign not in statement for statement in text_reads)
    assert not any(re.search(r"SELECT\s+\*\s+FROM\s+claims", statement, re.I) for statement in sql)


@pytest.mark.parametrize("untrusted_source", [
    "unregistered", "stale_revision", "wrong_manifest", "wrong_acl",
    "wrong_vector_size", "foreign_profile",
])
def test_acl_aware_reindex_keeps_alias_when_foreign_vector_is_unusable(
    tmp_path, monkeypatch, untrusted_source,
):
    (module, viewer, foreign, _visible, private_text, visible_text,
     points, alias, embedded, requests) = _shared_reindex(tmp_path, monkeypatch)
    original_alias = alias["target"]
    if untrusted_source == "unregistered":
        with viewer._connect() as db:
            db.execute("DELETE FROM claim_vector_targets WHERE claim_id=?", (foreign,))
    elif untrusted_source == "wrong_manifest":
        with viewer._connect() as db:
            db.execute(
                "UPDATE claim_vector_targets SET manifest_hash='incompatible' WHERE claim_id=?",
                (foreign,),
            )
    elif untrusted_source == "wrong_vector_size":
        points[original_alias][foreign]["vector"] = [0.5]
    elif untrusted_source == "foreign_profile":
        with viewer._connect() as db:
            db.execute("DELETE FROM claim_vector_targets WHERE claim_id=?", (foreign,))
            module._record_claim_vector_target(
                db, foreign, collection="other_claims_8278d1218cc6",
                manifest_hash=module._manifest_hash(module._embedding_manifest()),
                status="active", indexed_at=module.now(),
            )
    else:
        key = "memory_revision" if untrusted_source == "stale_revision" else "visibility_scope"
        points[original_alias][foreign]["payload"][key] = (
            -1 if key == "memory_revision" else "global"
        )
    result = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {"force": True}))
    assert result.get("error") != "shared_claim_scope_unavailable", result
    assert result["status"] == "partial", result
    assert result["alias_switched"] is False and alias["target"] == original_alias
    assert result["failed"] >= 1 and foreign in result["failed_ids"]
    assert embedded and set(embedded) == {visible_text}
    assert private_text not in json.dumps(requests)
    assert not any("other_claims_" in path for _, path, _ in requests)
    assert all(foreign not in points[coll] for coll in points if coll != original_alias)
    assert viewer._connect().execute(
        "SELECT status FROM reindex_jobs WHERE target_collection=?",
        (result["collection"],),
    ).fetchone()[0] == "running"


def test_acl_aware_reindex_resumes_same_force_target_after_limit(tmp_path, monkeypatch):
    (module, viewer, foreign, visible, private_text, visible_text,
     points, alias, embedded, requests) = _shared_reindex(tmp_path, monkeypatch)
    source = alias["target"]
    first = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {"force": True, "limit": 1}))
    assert first["status"] == "partial" and alias["target"] == source, first
    second = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {"force": True}))
    assert second["status"] == "completed", second
    assert first["collection"] == second["collection"] == alias["target"]
    assert set(points[alias["target"]]) == {foreign, visible}
    assert embedded and set(embedded) == {visible_text}
    assert private_text not in json.dumps(requests)


def test_acl_aware_reindex_fast_path_checks_metadata_without_foreign_text(
    tmp_path, monkeypatch,
):
    (module, viewer, foreign, visible, private_text, _visible_text,
     points, alias, embedded, requests) = _shared_reindex(tmp_path, monkeypatch)
    source = alias["target"]
    row = viewer._connect().execute("SELECT * FROM claims WHERE id=?", (visible,)).fetchone()
    payload = module._qdrant_claim_payload(
        visible, row["normalized_claim"], row,
        manifest_hash=module._manifest_hash(module._embedding_manifest()),
    )
    points[source][visible] = {"vector": [0.25] * module.QDRANT_VECTOR_SIZE, "payload": payload}
    sql = []
    viewer._connect().set_trace_callback(sql.append)
    result = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {}))
    viewer._connect().set_trace_callback(None)
    assert result["status"] == "already_complete", result
    assert alias["target"] == source and set(points[source]) == {foreign, visible}
    assert embedded == []
    assert private_text not in json.dumps(requests)
    assert any(re.search(r"SELECT\s+normalized_claim\s+FROM\s+claims", statement, re.I)
               and visible in statement and foreign not in statement for statement in sql)


def test_two_completed_force_reindexes_do_not_reuse_a_target_in_one_second(
    tmp_path, monkeypatch,
):
    (module, viewer, foreign, visible, _private_text, _visible_text,
     points, alias, _embedded, _requests) = _shared_reindex(tmp_path, monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 1790000000.0)
    first = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {"force": True}))
    second = json.loads(viewer.handle_tool_call("memory_wiki_reindex", {"force": True}))
    assert first["status"] == second["status"] == "completed"
    assert first["collection"] != second["collection"]
    assert alias["target"] == second["collection"]
    assert set(points[first["collection"]]) == set(points[second["collection"]]) == {foreign, visible}
