"""Model-facing tools must honor the same visibility boundary as recall."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_model_acl_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, tool_name: str, **arguments):
    return json.loads(provider.handle_tool_call(tool_name, arguments))


def test_foreign_claim_guard_reads_only_acl_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("viewer-session", hermes_home=str(tmp_path),
                        bot_id="viewer-bot", project_id="viewer-project",
                        agent_context="test")
    try:
        conn = provider._connect()
        with conn:
            for id_, scope, bot, project in (
                ("visible-global", "global", "", ""),
                ("hidden-project", "project", "owner-bot", "other-project"),
            ):
                conn.execute(
                    """INSERT INTO claims(id,claim,topic,status,confidence,salience,
                       source,evidence,created_at,updated_at,freshness_at,access_count,
                       last_accessed,hash,scope,visibility_scope,origin_session_id,
                       origin_bot_id,project_id,quality,risk,quarantined_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (id_, "unread sentinel", "acl-test", "active", .9, .9,
                     "test", "private evidence sentinel", module.now(), module.now(),
                     module.now(), 0, 0, id_, "global", scope, "owner-session",
                     bot, project, .9, "low", 0),
                )
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            assert provider._has_foreign_claims() is True
        finally:
            conn.set_trace_callback(None)
        selects = [s.lower() for s in statements if "from claims" in s.lower()]
        assert len(selects) == 1
        projection = selects[0].split("from claims", 1)[0]
        assert "*" not in projection
        assert "claim," not in projection and "normalized_claim" not in projection
        assert "evidence" not in projection
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_bulk_and_direct_reads_do_not_cross_visibility(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    owner = module.MemoryWikiProvider()
    owner.initialize("owner-session", hermes_home=str(tmp_path), bot_id="owner-bot", project_id="owner-project", agent_context="test")
    viewer = module.MemoryWikiProvider()
    viewer.initialize("viewer-session", hermes_home=str(tmp_path), bot_id="viewer-bot", project_id="viewer-project", agent_context="test")
    try:
        with owner._connect() as conn:
            for claim_id, visibility, text in (
                ("c_acl_private", "private", "Owner private lunar orchid sentinel"),
                ("c_acl_project", "project", "Owner project lunar orchid sentinel"),
                ("c_acl_global", "global", "Shared global lunar orchid sentinel"),
            ):
                conn.execute(
                    """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                       created_at,updated_at,freshness_at,access_count,last_accessed,hash,scope,
                       visibility_scope,origin_session_id,origin_bot_id,project_id,quality,risk,quarantined_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (claim_id,text,"acl-test","active",.9,.9,"test","evidence " + text,
                     module.now(),module.now(),module.now(),0,0,claim_id,"global",visibility,
                     "owner-session","owner-bot","owner-project",.9,"low",0),
                )
                conn.execute("INSERT INTO evidence(id,claim_id,kind,text,source,created_at) VALUES(?,?,?,?,?,?)",
                             ("e_" + claim_id,claim_id,"support","evidence " + text,"test",module.now()))
            conn.execute("INSERT INTO project_profiles(project_id,root,purpose,commands,services,notes,updated_at) VALUES(?,?,?,?,?,?,?)",
                         ("owner-project","/owner/private","Owner profile lunar orchid sentinel","[]","[]","",module.now()))
            conn.execute("INSERT INTO task_capsules(id,intent,topic,created_at,hash) VALUES(?,?,?,?,?)",
                         ("task_acl","Owner task lunar orchid sentinel","acl-test",module.now(),"task-acl"))
            conn.execute("INSERT INTO preference_rules(id,rule,priority,scope,source,status,created_at,updated_at,hash) VALUES(?,?,?,?,?,?,?,?,?)",
                         ("pref_custom_acl","Owner preference lunar orchid sentinel",900,"global","user","active",module.now(),module.now(),"pref-acl"))

        for name, arguments in (
            ("memory_wiki_export", {"limit": 20}),
            ("memory_wiki_export_bundle", {"limit": 20, "write_file": False}),
            ("memory_wiki_dashboard", {"limit": 20}),
            ("memory_wiki_active_dashboard", {"limit": 80}),
            ("memory_wiki_get_page", {"topic": "acl-test"}),
            ("memory_wiki_summarize_topic", {"topic": "acl-test"}),
            ("memory_wiki_preference_layer", {"query": "lunar orchid sentinel"}),
            ("memory_wiki_pack_context", {"query": "lunar orchid sentinel", "coverage_manifest": {"repository_id": "repo", "covered": []}}),
        ):
            output = json.dumps(_call(viewer,name,**arguments),ensure_ascii=False)
            assert "Owner private lunar orchid sentinel" not in output, name
            assert "Owner project lunar orchid sentinel" not in output, name
            assert "Owner profile lunar orchid sentinel" not in output, name
            assert "Owner task lunar orchid sentinel" not in output, name
            assert "Owner preference lunar orchid sentinel" not in output, name

        assert "Owner preference lunar orchid sentinel" not in viewer.system_prompt_block()

        for name, arguments in (
            ("memory_wiki_why_believe", {"claim_id": "c_acl_private"}),
            ("memory_wiki_claim_history", {"claim_id": "c_acl_private"}),
        ):
            assert _call(viewer,name,**arguments).get("success") is False, name

        exported = _call(viewer,"memory_wiki_export",limit=20)
        assert "c_acl_global" in {row["id"] for row in exported["claims"]}
        assert "c_acl_private" not in {row["id"] for row in exported["claims"]}
    finally:
        for provider in (owner,viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_direct_mutations_cannot_change_foreign_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    owner = module.MemoryWikiProvider()
    owner.initialize("owner-session", hermes_home=str(tmp_path), bot_id="owner-bot", project_id="owner-project", agent_context="test")
    viewer = module.MemoryWikiProvider()
    viewer.initialize("viewer-session", hermes_home=str(tmp_path), bot_id="viewer-bot", project_id="viewer-project", agent_context="test")
    try:
        with owner._connect() as conn:
            conn.execute(
                """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                   created_at,updated_at,freshness_at,access_count,last_accessed,hash,scope,
                   visibility_scope,origin_session_id,origin_bot_id,project_id,quality,risk,quarantined_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("c_acl_mutation","Private ownership sentinel","acl-test","active",.9,.9,"test","",
                 module.now(),module.now(),module.now(),0,0,"acl-mutation","global","private",
                 "owner-session","owner-bot","owner-project",.9,"low",0),
            )
        for name, arguments in (
            ("memory_wiki_update_claim", {"claim_id":"c_acl_mutation","status":"deleted"}),
            ("memory_wiki_pin_claim", {"claim_id":"c_acl_mutation","pinned":True}),
            ("memory_wiki_add_evidence", {"claim_id":"c_acl_mutation","text":"foreign"}),
            ("memory_wiki_mark_used", {"claim_ids":["c_acl_mutation"]}),
            ("memory_wiki_transaction", {"mode":"apply","operations":[{"tool":"update_claim","args":{"claim_id":"c_acl_mutation","status":"deleted"}}]}),
        ):
            result = _call(viewer,name,**arguments)
            assert result.get("success") is False, (name,result)
        row = owner._connect().execute("SELECT status,pinned FROM claims WHERE id='c_acl_mutation'").fetchone()
        assert row["status"] == "active" and row["pinned"] == 0
        monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_RECOVERY", raising=False)
        monkeypatch.setattr(viewer, "_backup", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("shared backup invoked")))
        result = _call(viewer, "memory_wiki_transaction", mode="apply_with_backup", operations=[])
        assert not result.get("success") and "shared_recovery" in str(result.get("error")), result
    finally:
        for provider in (owner,viewer):
            if provider._conn is not None:
                provider._conn.close()
                provider._conn = None


def test_legacy_unscoped_graph_and_secret_bridge_are_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA", raising=False)
    module = _module()
    monkeypatch.setattr(module, "_external_secret_context_search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unscoped secret bridge called")))
    provider = module.MemoryWikiProvider()
    provider.initialize("viewer", hermes_home=str(tmp_path), agent_context="test")
    try:
        with provider._connect() as conn:
            conn.execute("INSERT INTO entities(id,name,entity_type,aliases,notes,updated_at,hash) VALUES(?,?,?,?,?,?,?)",
                         ("ent_acl","legacy graph sentinel","thing","[]","private legacy note",module.now(),"legacy-graph"))
            conn.execute("INSERT INTO review_queue(id,candidate,topic,source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         ("rq_legacy_acl","legacy review sentinel","general","test","pending",module.now(),module.now()))
        assert _call(provider,"memory_wiki_graph_query",query="legacy graph sentinel")["entities"] == []
        assert _call(provider,"memory_wiki_query_secrets",query="ssh")["secrets"] == []
        assert _call(provider,"memory_wiki_review_queue",mode="list")["items"] == []
        assert not _call(provider,"memory_wiki_review_queue",mode="reject",item_id="rq_legacy_acl").get("success")
        assert _call(provider,"memory_wiki_audit_log",limit=5)["events"] == []
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_session_history_and_path_bundle_require_separate_host_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK", "1")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_SESSION_HISTORY", raising=False)
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_PATH_BUNDLE_IMPORT", raising=False)
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("viewer", hermes_home=str(tmp_path), agent_context="test")
    try:
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        (session_dir / "session_foreign.json").write_text(json.dumps({
            "session_id": "foreign", "messages": [{"role": "user", "content": "Foreign chat lunar orchid sentinel"}],
        }), encoding="utf-8")
        assert provider._session_context_candidates("lunar orchid") == []
        packed = _call(provider, "memory_wiki_pack_context", query="lunar orchid", max_tokens=300)
        assert "Foreign chat lunar orchid sentinel" not in json.dumps(packed, ensure_ascii=False)

        bundle = tmp_path / "foreign-bundle.json"
        bundle.write_text(json.dumps({"format":"memory-wiki-sync-bundle/v1","claims":[]}), encoding="utf-8")
        denied = _call(provider,"memory_wiki_import_bundle",path=str(bundle),mode="suggest")
        assert denied.get("success") is False, denied

        monkeypatch.setenv("MEMORY_WIKI_ALLOW_SHARED_SESSION_HISTORY", "1")
        assert "Foreign chat lunar orchid sentinel" in json.dumps(provider._session_context_candidates("lunar orchid"),ensure_ascii=False)
        monkeypatch.setenv("MEMORY_WIKI_ALLOW_PATH_BUNDLE_IMPORT", "1")
        allowed = _call(provider,"memory_wiki_import_bundle",path=str(bundle),mode="suggest")
        assert allowed.get("success") is True, allowed
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_recovery_tools_require_trusted_host_even_with_empty_claim_table(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_RECOVERY", raising=False)
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("viewer", hermes_home=str(tmp_path), agent_context="test")
    calls = []
    monkeypatch.setattr(provider, "_backup", lambda reason: calls.append(("backup", reason)) or {"id": "stub"})
    monkeypatch.setattr(provider, "_list_backups", lambda limit: calls.append(("list", limit)) or [])
    monkeypatch.setattr(provider, "_restore", lambda path: calls.append(("restore", path)) or {"restored_from": path})
    monkeypatch.setattr(provider, "_rebuild_from_journal", lambda apply, checkpoint, max_events: calls.append(("rebuild", apply)) or {"applied": apply})
    monkeypatch.setattr(provider, "_journal_checkpoint", lambda name, include_secret_values: calls.append(("checkpoint", name)) or {"path": str(tmp_path / "checkpoint.json")})
    operations = (
        ("memory_wiki_backup", {"reason": "test"}),
        ("memory_wiki_list_backups", {"limit": 5}),
        ("memory_wiki_restore", {"backup": str(tmp_path / "untrusted.zip")}),
        ("memory_wiki_rebuild_from_journal", {"apply": True}),
        ("memory_wiki_journal_checkpoint", {"name": "test"}),
    )
    try:
        assert provider._connect().execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        for name, arguments in operations:
            denied = _call(provider, name, **arguments)
            assert denied == {"success": False, "error": "shared_recovery_requires_trusted_host"}, (name, denied)
        assert calls == []

        # A host that owns the entire Hermes home may explicitly enable
        # recovery. Test the dispatch path without replacing a live database.
        monkeypatch.setenv("MEMORY_WIKI_ALLOW_SHARED_RECOVERY", "1")
        for name, arguments in operations:
            assert _call(provider, name, **arguments)["success"] is True, name
        assert {item[0] for item in calls} == {"backup", "list", "restore", "rebuild", "checkpoint"}

        # The explicit host authorization also covers a shared store whose
        # existing claims have different model-level visibility.
        monkeypatch.setattr(provider, "_has_foreign_claims", lambda: True)
        for name, arguments in operations:
            assert _call(provider, name, **arguments)["success"] is True, name

        # Trusted internal recovery/replay calls retain access without the
        # model-facing host opt-in.
        monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_RECOVERY")
        calls.clear()
        for name, arguments in operations:
            internal = provider.handle_tool_call(
                name, {**arguments, "__journaled_skip": True},
                **module._internal_journal_call_kwargs(),
            )
            assert json.loads(internal)["success"] is True, name
        assert {item[0] for item in calls} == {"backup", "list", "restore", "rebuild", "checkpoint"}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None
