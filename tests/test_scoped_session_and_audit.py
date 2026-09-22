"""Session history and audit log may expose only host-bound current context by default."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_scoped_session_audit_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, name, **kwargs):
    return json.loads(provider.handle_tool_call(name, kwargs))


def test_session_history_reads_only_exact_current_session_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_SESSION_HISTORY", raising=False)
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("own-session", hermes_home=str(tmp_path), bot_id="own-bot", project_id="own-project", agent_context="test")
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    (session_dir / "session_own-session.json").write_text(json.dumps({
        "session_id": "own-session", "bot_id": "own-bot", "project_id": "own-project",
        "messages": [{"role": "user", "content": "Own lunar orchid history"}],
    }), encoding="utf-8")
    (session_dir / "session_foreign-session.json").write_text(json.dumps({
        "session_id": "foreign-session", "bot_id": "foreign-bot", "project_id": "foreign-project",
        "messages": [{"role": "user", "content": "Foreign lunar orchid history"}],
    }), encoding="utf-8")
    try:
        own = provider._session_context_candidates("lunar orchid")
        assert "Own lunar orchid history" in json.dumps(own)
        assert "Foreign lunar orchid history" not in json.dumps(own)
        # Even an exact filename cannot authorize a transcript that declares
        # another session or bot.
        own_path = session_dir / "session_own-session.json"
        own_path.write_text(json.dumps({
            "session_id": "foreign-session", "messages": [{"role": "user", "content": "Spoofed lunar orchid history"}],
        }), encoding="utf-8")
        assert provider._session_context_candidates("lunar orchid") == []
        monkeypatch.setenv("MEMORY_WIKI_ALLOW_SHARED_SESSION_HISTORY", "1")
        shared = provider._session_context_candidates("lunar orchid")
        assert "Foreign lunar orchid history" in json.dumps(shared)
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_audit_log_defaults_to_owner_tagged_events(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_AUDIT_LOG", raising=False)
    module = _module()
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-session", hermes_home=str(tmp_path), bot_id="owner-bot", agent_context="test")
    viewer.initialize("viewer-session", hermes_home=str(tmp_path), bot_id="viewer-bot", agent_context="test")
    try:
        with owner._connect() as conn:
            conn.execute("INSERT INTO audit_log(id,op,status,detail,created_at) VALUES(?,?,?,?,?)",
                         ("aud_legacy_test", "legacy", "ok", "Legacy foreign sentinel", 1))
        own_backup = _call(owner, "memory_wiki_scoped_backup")
        assert own_backup["success"] is True
        added = _call(owner, "memory_wiki_add_claim", claim="The owner deployment runbook is stored in docs and should be consulted before deployment",
                      topic="operations")
        assert added["success"] is True and added["state"] == "stored", added
        assert _call(owner, "memory_wiki_update_claim", claim_id=added["id"], status="uncertain")["success"] is True
        assert _call(owner, "memory_wiki_add_evidence", claim_id=added["id"], text="Owner verified docs location")["success"] is True
        foreign_identity = viewer._scoped_backup_owner()
        with owner._connect() as conn:
            conn.execute("""INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                           created_at,updated_at,freshness_at,hash,origin_bot_id,origin_session_id,
                           origin_chat_hash,visibility_scope) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         ("c_foreign_audit", "Foreign global claim", "audit", "active", .8, .8, "test", "",
                          1, 1, 1, "foreign-audit-hash", foreign_identity["bot_id"],
                          foreign_identity["session_id"], foreign_identity["chat_hash"], "global"))
        owner._audit_owned_claim_action("claim_update", "c_foreign_audit")
        own_events = _call(owner, "memory_wiki_audit_log", limit=20)
        viewer_events = _call(viewer, "memory_wiki_audit_log", limit=20)
        assert own_events["success"] is True
        assert {event["op"] for event in own_events["events"]} == {
            "scoped_backup", "claim_add", "claim_update", "claim_evidence_add"}
        assert "Legacy foreign sentinel" not in json.dumps(own_events)
        assert viewer_events == {"success": True, "events": []}
        monkeypatch.setenv("MEMORY_WIKI_ALLOW_SHARED_AUDIT_LOG", "1")
        shared = _call(viewer, "memory_wiki_audit_log", limit=20)
        assert "Legacy foreign sentinel" in json.dumps(shared)
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()
