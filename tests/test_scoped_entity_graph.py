"""Entity graph ownership, source provenance, and temporal invalidation."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_scoped_graph_test", PLUGIN,
        submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, tool_name, **kwargs):
    return json.loads(provider.handle_tool_call(tool_name, kwargs))


def test_scoped_graph_and_source_claim_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH", raising=False)
    module = _module()
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", project_id="owner-project", agent_context="test")
    viewer.initialize("viewer-chat", hermes_home=str(tmp_path), bot_id="viewer-bot", project_id="viewer-project", agent_context="test")
    try:
        with owner._connect() as conn:
            conn.execute(
                """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                   created_at,updated_at,freshness_at,access_count,last_accessed,hash,
                   visibility_scope,origin_session_id,origin_bot_id,origin_chat_hash,project_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("c_graph_owner", "Secret atlas resides on Europa", "graph", "active", .9, .9,
                 "test", "owner evidence", module.now(), module.now(), module.now(), 0, 0,
                 "c-graph-owner", "private", "owner-chat", "owner-bot",
                 owner._chat_hash("owner-chat"), "owner-project"),
            )
            conn.execute(
                "INSERT INTO entities(id,name,entity_type,aliases,notes,updated_at,hash) VALUES(?,?,?,?,?,?,?)",
                ("ent_legacy_graph", "legacy atlas sentinel", "thing", "[]", "", module.now(), "legacy-atlas"),
            )
        assert _call(viewer, "memory_wiki_graph_query", query="legacy atlas")["entities"] == []

        private_entity = _call(owner, "memory_wiki_add_entity", name="Secret atlas", visibility_scope="private")
        assert private_entity["success"], private_entity
        private_edge = _call(owner, "memory_wiki_add_relation", subject="Secret atlas", predicate="runs_on",
                             object="Europa", source_claim_id="c_graph_owner")
        assert private_edge["success"]
        assert private_edge["source_claim_id"] == "c_graph_owner"
        assert private_edge["subject_id"] == private_entity["id"]
        assert _call(viewer, "memory_wiki_graph_query", query="Secret atlas") == {
            "success": True, "entities": [], "relations": []
        }
        assert private_edge["id"] in {row["id"] for row in _call(owner, "memory_wiki_export", limit=30)["relations"]}
        assert private_edge["id"] not in {row["id"] for row in _call(viewer, "memory_wiki_export", limit=30)["relations"]}
        assert private_edge["id"] in {row["id"] for row in _call(owner, "memory_wiki_export_bundle", limit=30, write_file=False)["payload"]["relations"]}
        assert private_edge["id"] not in {row["id"] for row in _call(viewer, "memory_wiki_export_bundle", limit=30, write_file=False)["payload"]["relations"]}
        mutation = owner._connect().execute("SELECT id FROM memory_mutations WHERE target_table='relations' AND target_id=? ORDER BY created_at DESC LIMIT 1",
                                           (private_edge["id"],)).fetchone()
        assert mutation is not None
        assert viewer._undo_last(mutation["id"], dry_run=True)["found"] is False
        assert viewer._undo_last(mutation["id"], dry_run=False)["found"] is False
        assert owner._undo_last(mutation["id"], dry_run=True)["found"] is True
        assert _call(viewer, "memory_wiki_undo_last", mutation_id=mutation["id"], dry_run=True)["found"] is False
        assert _call(viewer, "memory_wiki_undo_last", mutation_id=mutation["id"], dry_run=False)["found"] is False
        assert _call(owner, "memory_wiki_undo_last", mutation_id=mutation["id"], dry_run=True)["found"] is True
        assert not _call(viewer, "memory_wiki_add_relation", subject="Secret atlas",
                         predicate="runs_on", object="Europa", source_claim_id="c_graph_owner").get("success")

        own = _call(owner, "memory_wiki_graph_query", query="Secret atlas")
        assert {r["id"] for r in own["relations"]} == {private_edge["id"]}
        assert own["relations"][0]["source_ref"]
        with owner._connect() as conn:
            conn.execute("UPDATE claims SET status='superseded' WHERE id='c_graph_owner'")
        own_after = _call(owner, "memory_wiki_graph_query", query="Secret atlas")
        assert own_after["relations"] == []
        assert {e["id"] for e in own_after["entities"]} == {private_entity["id"]}
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_graph_validity_and_project_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    owner = module.MemoryWikiProvider()
    other = module.MemoryWikiProvider()
    owner.initialize("chat-one", hermes_home=str(tmp_path), bot_id="bot-one", project_id="p-one", agent_context="test")
    other.initialize("chat-two", hermes_home=str(tmp_path), bot_id="bot-two", project_id="p-two", agent_context="test")
    try:
        assert not _call(owner, "memory_wiki_add_entity", name="Orion", visibility_scope="project", project_id="p-two").get("success")
        edge = _call(owner, "memory_wiki_add_relation", subject="Orion", predicate="hosts", object="Beacon",
                     visibility_scope="project", valid_from=module.now() + 3600)
        assert edge["success"], edge
        assert _call(owner, "memory_wiki_graph_query", query="Orion")["relations"] == []
        assert _call(other, "memory_wiki_graph_query", query="Orion")["relations"] == []
        with owner._connect() as conn:
            conn.execute("UPDATE relations SET valid_from=0 WHERE id=?", (edge["id"],))
        second = _call(owner, "memory_wiki_add_relation", subject="Beacon", predicate="hosts", object="Signal",
                       visibility_scope="project")
        assert second["success"], second
        assert {r["id"] for r in _call(owner, "memory_wiki_graph_query", query="Orion")["relations"]} == {edge["id"], second["id"]}
        assert _call(other, "memory_wiki_graph_query", query="Orion")["relations"] == []
    finally:
        for provider in (owner, other):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_legacy_graph_requires_explicit_per_row_owner_migration(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH", raising=False)
    module = _module()
    migration_spec = importlib.util.spec_from_file_location(
        "memory_wiki_graph_migration_test", PLUGIN.parent / "tools" / "migrate_legacy_graph.py")
    assert migration_spec and migration_spec.loader
    migration = importlib.util.module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    viewer.initialize("viewer-chat", hermes_home=str(tmp_path), bot_id="viewer-bot", agent_context="test")
    try:
        with owner._connect() as conn:
            conn.execute("INSERT INTO entities(id,name,entity_type,aliases,notes,updated_at,hash) VALUES(?,?,?,?,?,?,?)",
                         ("legacy_row", "Migrate me sentinel", "thing", "[]", "", module.now(), "legacy-migrate"))
        mapping = {"records": [{"table": "entities", "id": "legacy_row",
                                "visibility_scope": "chat", "origin_session_id": "owner-chat", "origin_bot_id": "owner-bot"}]}
        import pytest
        without_bot = {"records": [{k: v for k, v in mapping["records"][0].items() if k != "origin_bot_id"}]}
        with pytest.raises(ValueError, match="origin_bot_id"):
            migration.prepare(owner._connect(), without_bot)
        plan = migration.prepare(owner._connect(), mapping)
        assert owner._connect().execute("SELECT visibility_scope FROM entities WHERE id='legacy_row'").fetchone()[0] == "legacy"
        assert migration.apply(owner._connect(), plan) == 1
        assert {e["id"] for e in _call(owner, "memory_wiki_graph_query", query="Migrate me")["entities"]} == {"legacy_row"}
        assert _call(viewer, "memory_wiki_graph_query", query="Migrate me")["entities"] == []
        with pytest.raises(ValueError, match="no longer legacy"):
            migration.prepare(owner._connect(), mapping)
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None
