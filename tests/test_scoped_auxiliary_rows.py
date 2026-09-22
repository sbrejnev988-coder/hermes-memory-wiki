"""New auxiliary records are scoped; legacy rows require attested migration."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    spec = importlib.util.spec_from_file_location("memory_wiki_scoped_aux_test", PLUGIN,
                                                  submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, tool_name, **kwargs):
    return json.loads(provider.handle_tool_call(tool_name, kwargs))


def test_preferences_and_review_queue_obey_chat_acl(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_PREFERENCES", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_REVIEW_QUEUE", raising=False)
    module = _module()
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    viewer.initialize("viewer-chat", hermes_home=str(tmp_path), bot_id="viewer-bot", agent_context="test")
    try:
        rule = _call(owner, "memory_wiki_add_preference_rule", rule="Always use lunar violet headings",
                     source="explicit", visibility_scope="chat")
        assert rule["success"], rule
        assert rule["id"] not in {r["id"] for r in _call(owner, "memory_wiki_preference_layer")["rules"]}
        assert rule["id"] not in {r["id"] for r in _call(viewer, "memory_wiki_preference_layer")["rules"]}
        assert rule["id"] in {r["id"] for r in _call(owner, "memory_wiki_export", limit=30)["preference_rules"]}
        assert rule["id"] not in {r["id"] for r in _call(viewer, "memory_wiki_export", limit=30)["preference_rules"]}
        assert rule["id"] in {r["id"] for r in _call(owner, "memory_wiki_export_bundle", limit=30, write_file=False)["payload"]["preference_rules"]}
        assert rule["id"] not in {r["id"] for r in _call(viewer, "memory_wiki_export_bundle", limit=30, write_file=False)["payload"]["preference_rules"]}
        assert "lunar violet headings" not in owner.system_prompt_block()
        assert "lunar violet headings" not in viewer.system_prompt_block()
        candidate = owner._connect().execute("SELECT visibility_scope,status FROM preference_rules WHERE id=?", (rule["id"],)).fetchone()
        assert candidate and tuple(candidate) == ("chat", "pending")

        queued = owner._enqueue_review("Remember the lunar violet review item", "general", "", "turn:user:owner-chat",
                                       "manual queue", visibility_scope="chat")
        assert queued in {r["id"] for r in _call(owner, "memory_wiki_review_queue", mode="list")["items"]}
        assert queued not in {r["id"] for r in _call(viewer, "memory_wiki_review_queue", mode="list")["items"]}
        assert not _call(viewer, "memory_wiki_review_queue", mode="reject", item_id=queued).get("success")
        rejected = _call(owner, "memory_wiki_review_queue", mode="reject", item_id=queued)
        assert rejected["success"] and rejected["status"] == "rejected"
        to_approve = owner._enqueue_review("User prefers clear amber headings in reports", "preferences", "",
                                           "curated", "manual review", visibility_scope="chat")
        approved = _call(owner, "memory_wiki_review_queue", mode="approve", item_id=to_approve)
        assert approved["success"], approved
        approved_claim = owner._connect().execute("SELECT visibility_scope FROM claims WHERE id=?", (approved["claim_id"],)).fetchone()
        assert approved_claim and approved_claim[0] == "chat"

        with owner._connect() as conn:
            conn.execute("""INSERT INTO preference_rules(id,rule,priority,scope,source,status,created_at,updated_at,hash)
                            VALUES(?,?,?,?,?,?,?,?,?)""",
                         ("pref_legacy_aux", "Legacy lavender instruction", 900, "global", "explicit",
                          "active", module.now(), module.now(), "legacy-lavender"))
            conn.execute("INSERT INTO review_queue(id,candidate,topic,source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         ("rq_legacy_aux", "Legacy lavender queue", "general", "test", "pending", module.now(), module.now()))
        assert "pref_legacy_aux" not in {r["id"] for r in _call(owner, "memory_wiki_preference_layer")["rules"]}
        assert "rq_legacy_aux" not in {r["id"] for r in _call(owner, "memory_wiki_review_queue", mode="list")["items"]}
        assert "Legacy lavender instruction" not in owner.system_prompt_block()
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_legacy_preference_and_queue_migration_requires_explicit_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    migration_spec = importlib.util.spec_from_file_location("memory_wiki_aux_migration_test",
                                                        PLUGIN.parent / "tools" / "migrate_legacy_graph.py")
    assert migration_spec and migration_spec.loader
    migration = importlib.util.module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    viewer.initialize("viewer-chat", hermes_home=str(tmp_path), bot_id="viewer-bot", agent_context="test")
    try:
        with owner._connect() as conn:
            conn.execute("""INSERT INTO preference_rules(id,rule,priority,scope,source,status,created_at,updated_at,hash)
                            VALUES(?,?,?,?,?,?,?,?,?)""",
                         ("pref_migrate_aux", "Only owner sees amber glyph", 700, "global", "explicit",
                          "active", module.now(), module.now(), "legacy-amber"))
            conn.execute("INSERT INTO review_queue(id,candidate,topic,source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         ("rq_migrate_aux", "Only owner sees amber review", "general", "test", "pending", module.now(), module.now()))
        mapping = {"records": [
            {"table": "preference_rules", "id": "pref_migrate_aux", "visibility_scope": "chat", "origin_session_id": "owner-chat", "origin_bot_id": "owner-bot"},
            {"table": "review_queue", "id": "rq_migrate_aux", "visibility_scope": "chat", "origin_session_id": "owner-chat", "origin_bot_id": "owner-bot"},
        ]}
        plan = migration.prepare(owner._connect(), mapping)
        assert migration.apply(owner._connect(), plan) == 2
        assert "pref_migrate_aux" not in {r["id"] for r in _call(owner, "memory_wiki_preference_layer")["rules"]}
        assert "pref_migrate_aux" not in {r["id"] for r in _call(viewer, "memory_wiki_preference_layer")["rules"]}
        assert "rq_migrate_aux" in {r["id"] for r in _call(owner, "memory_wiki_review_queue", mode="list")["items"]}
        assert "rq_migrate_aux" not in {r["id"] for r in _call(viewer, "memory_wiki_review_queue", mode="list")["items"]}
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_new_secret_metadata_is_private_and_external_registry_stays_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_ENABLE_LEGACY_SECRET_INDEX", "1")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA", raising=False)
    module = _module()
    monkeypatch.setattr(module, "_external_secret_context_search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external registry accessed")))

    class FakeStore:
        def wrapped_snapshot(self, _): return ""
        def has_secret(self, _): return False
        def put_secret(self, *_): return ""

    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-chat", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    viewer.initialize("viewer-chat", hermes_home=str(tmp_path), bot_id="viewer-bot", agent_context="test")
    monkeypatch.setattr(owner, "_get_secret_store", lambda: FakeStore())
    monkeypatch.setattr(viewer, "_get_secret_store", lambda: FakeStore())
    try:
        created = owner._add_secret({"_trusted_local_write": True, "subject": "amber vault index",
                                     "scope": "operations", "purpose": "safe metadata", "value": "",
                                     "visibility_scope": "private"})
        assert created["id"]
        monkeypatch.setattr(module, "_SECRET_CORE_AVAILABLE", True)
        assert created["id"] in {row["id"] for row in owner._query_secrets("amber", 10)}
        assert created["id"] not in {row["id"] for row in viewer._query_secrets("amber", 10)}
        with owner._connect() as conn:
            conn.execute("""INSERT INTO secret_index(id,subject,scope,created_at,updated_at,hash)
                            VALUES(?,?,?,?,?,?)""",
                         ("sec_legacy_aux", "amber legacy secret", "operations", module.now(), module.now(), "legacy-secret-amber"))
        assert "sec_legacy_aux" not in {row["id"] for row in owner._query_secrets("amber", 10)}
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None
