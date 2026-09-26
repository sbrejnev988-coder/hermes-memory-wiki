"""Model-facing revision invalidation must not mutate foreign or shared claims."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_invalidate_acl_regression"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_model_revision_invalidation_changes_only_visible_owned_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("viewer-session", hermes_home=str(tmp_path),
                        bot_id="viewer-bot", project_id="viewer-project", agent_context="test")
    try:
        repo = provider._code_graph_identity("repo-acl-test")
        symbol = provider._code_graph_identity("symbol-acl-test")
        conn = provider._connect()
        with conn:
            for cid, visibility, bot, session, project in (
                ("c_own_revision", "private", "viewer-bot", "viewer-session", "viewer-project"),
                ("c_foreign_revision", "private", "foreign-bot", "foreign-session", "foreign-project"),
                ("c_shared_revision", "global", "foreign-bot", "foreign-session", ""),
                ("c_project_revision", "project", "foreign-bot", "foreign-session", "viewer-project"),
                ("c_own_project_revision", "project", "viewer-bot", "viewer-session", "viewer-project"),
                ("c_bot_revision", "bot", "viewer-bot", "viewer-session", "viewer-project"),
            ):
                conn.execute(
                    """INSERT INTO claims(id,claim,topic,status,created_at,updated_at,freshness_at,
                       hash,visibility_scope,origin_session_id,origin_bot_id,project_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, f"Synthetic revision claim for {cid} and ACL regression.", "code-shrinker",
                     "active", module.now(), module.now(), module.now(), cid,
                     visibility, session, bot, project),
                )
                conn.execute(
                    """INSERT INTO code_claim_metadata(claim_id,repository_id,file_path,symbol_id,content_hash)
                       VALUES(?,?,?,?,?)""",
                    (cid, repo, "src/test.py", symbol, "a" * 64),
                )
        for cid in ("c_own_revision", "c_foreign_revision", "c_shared_revision",
                    "c_project_revision", "c_own_project_revision", "c_bot_revision"):
            provider._upsert_fts(cid)
        result = json.loads(provider.handle_tool_call("memory_wiki_invalidate_revision", {
            "repository_id": "repo-acl-test", "symbol_id": "symbol-acl-test",
            "new_content_hash": "b" * 64,
        }))
        assert result.get("success") is True, result
        assert result["invalidated"] == 1
        assert result["ids"] == ["c_own_revision"]
        states = dict(conn.execute("SELECT id,status FROM claims"))
        assert states == {"c_own_revision": "archived", "c_foreign_revision": "active",
                          "c_shared_revision": "active", "c_project_revision": "active",
                          "c_own_project_revision": "active", "c_bot_revision": "active"}
        remaining_fts = {r[0] for r in conn.execute("SELECT id FROM claims_fts")}
        assert remaining_fts == set(states) - {"c_own_revision"}
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None
