"""Explicit shared blocks never turn a visible claim into an implicit global claim."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_shared_block_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, name, **arguments):
    return json.loads(provider.handle_tool_call(name, arguments))


def _provider(module, home, session, bot, project):
    provider = module.MemoryWikiProvider()
    provider.initialize(session, hermes_home=str(home), bot_id=bot,
                        project_id=project, agent_context="test")
    return provider


def test_grant_attach_detach_revoke_and_source_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    owner = _provider(module, tmp_path, "owner-session", "owner-bot", "owner-project")
    receiver = _provider(module, tmp_path, "receiver-session", "receiver-bot", "receiver-project")
    stranger = _provider(module, tmp_path, "stranger-session", "stranger-bot", "other-project")
    try:
        secret_to_other_chats = "violet atlas shared block marker"
        claim_id = "c_shared_private"
        with owner._connect() as conn:
            conn.execute("""INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                created_at,updated_at,freshness_at,hash,risk,secrecy_level,visibility_scope,
                origin_bot_id,origin_session_id,quality)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (claim_id, secret_to_other_chats, "test", "active", .8, .8, "test", "",
                 module.now(), module.now(), module.now(), "shared-private-hash", "low",
                 "public", "private", "owner-bot", "owner-session", .9))
        row = owner._connect().execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        assert row is not None and owner._claim_visible(row), dict(row) if row else None
        assert owner._inspect_recall_text(secret_to_other_chats, source="memory_wiki_shared_block", mem_type="claim", item_id=claim_id, audit=False, max_len=700).get("status") == "safe"
        assert secret_to_other_chats not in _call(receiver, "memory_wiki_pack_context", query="violet atlas")["context"]

        created = _call(owner, "memory_wiki_shared_block_create",
                        title="Atlas facts", claim_ids=[claim_id])
        assert created.get("success") is True, created
        block_id = created["block_id"]
        assert secret_to_other_chats not in owner.journal_path.read_text(encoding="utf-8")
        journal_size = owner.journal_path.stat().st_size
        assert _call(stranger, "memory_wiki_shared_block_attach",
                     block_id=block_id, principal_type="bot").get("error")
        assert owner.journal_path.stat().st_size == journal_size

        granted = _call(owner, "memory_wiki_shared_block_grant",
                        block_id=block_id, principal_type="bot", principal_id="receiver-bot")
        assert granted["status"] == "granted"
        assert secret_to_other_chats not in _call(receiver, "memory_wiki_pack_context", query="violet atlas")["context"]
        assert block_id in {item["id"] for item in _call(receiver, "memory_wiki_shared_block_list")["received"]}
        assert _call(receiver, "memory_wiki_shared_block_attach",
                     block_id=block_id, principal_type="bot")["status"] == "attached"
        assert secret_to_other_chats in _call(receiver, "memory_wiki_pack_context", query="violet atlas")["context"]
        assert secret_to_other_chats in receiver.prefetch("violet atlas")
        assert secret_to_other_chats in receiver._lexical_prefetch_fallback("violet atlas")
        assert secret_to_other_chats in receiver.prefetch("thanks")
        assert secret_to_other_chats not in _call(stranger, "memory_wiki_pack_context", query="violet atlas")["context"]
        assert secret_to_other_chats not in stranger.prefetch("violet atlas")
        checkpoint = owner._journal_checkpoint("shared-block-test")
        tables = json.loads(Path(checkpoint["path"]).read_text(encoding="utf-8"))["tables"]
        assert tables["shared_blocks"][0]["id"] == block_id
        assert tables["shared_blocks"][0]["owner_chat_hash"] == owner._chat_hash()
        assert json.loads(tables["shared_blocks"][0]["claim_refs_json"])[0]["digest80"] == module.sha(secret_to_other_chats)[:20]
        assert tables["shared_block_grants"][0]["block_id"] == block_id
        assert tables["shared_block_grants"][0]["principal_id"] == granted["principal_key"]
        assert tables["shared_block_attachments"][0]["block_id"] == block_id
        assert tables["shared_block_events"]

        assert _call(receiver, "memory_wiki_shared_block_detach",
                     block_id=block_id, principal_type="bot")["status"] == "detached"
        assert secret_to_other_chats not in _call(receiver, "memory_wiki_pack_context", query="violet atlas")["context"]
        _call(receiver, "memory_wiki_shared_block_attach", block_id=block_id, principal_type="bot")
        with owner._connect() as conn:
            conn.execute("UPDATE claims SET claim=? WHERE id=?",
                         ("violet atlas changed marker", claim_id))
        assert secret_to_other_chats not in _call(receiver, "memory_wiki_pack_context", query="violet atlas")["context"]
        assert "violet atlas changed marker" not in _call(receiver, "memory_wiki_pack_context", query="violet atlas")["context"]
        assert _call(owner, "memory_wiki_shared_block_revoke",
                     block_id=block_id, principal_type="bot", principal_id="receiver-bot")["status"] == "revoked"
        assert _call(receiver, "memory_wiki_shared_block_attach",
                     block_id=block_id, principal_type="bot").get("error")
        assert _call(stranger, "memory_wiki_shared_block_grant",
                     block_id=block_id, principal_type="bot", principal_id="stranger-bot").get("error")
    finally:
        for provider in (owner, receiver, stranger):
            if provider._conn is not None:
                provider._conn.close()


def test_nonpublic_claim_cannot_enter_shared_block(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    owner = _provider(module, tmp_path, "session-a", "bot-a", "project-a")
    try:
        with owner._connect() as conn:
            conn.execute("""INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                created_at,updated_at,freshness_at,hash,risk,secrecy_level,visibility_scope,
                origin_bot_id,origin_session_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("secret-claim", "A sensitive token is present", "test", "active", .8, .8,
                 "test", "", module.now(), module.now(), module.now(), "secret-claim-hash",
                 "secret", "secret", "private", "bot-a", "session-a"))
            conn.execute("""INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                created_at,updated_at,freshness_at,hash,risk,secrecy_level,visibility_scope,
                origin_bot_id,origin_session_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("internal-claim", "Internal planning notes", "test", "active", .8, .8,
                 "test", "", module.now(), module.now(), module.now(), "internal-claim-hash",
                 "low", "internal", "private", "bot-a", "session-a"))
        for claim_id in ("secret-claim", "internal-claim"):
            result = _call(owner, "memory_wiki_shared_block_create",
                           title="Sensitive", claim_ids=[claim_id])
            assert result.get("error") == "shared_block_access_denied", result
        assert owner._connect().execute("SELECT count(*) FROM shared_blocks").fetchone()[0] == 0
    finally:
        if owner._conn is not None:
            owner._conn.close()


def test_project_grant_is_bounded_to_named_project(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    owner = _provider(module, tmp_path, "owner", "owner-bot", "owner-project")
    project_member = _provider(module, tmp_path, "member", "member-bot", "target-project")
    second_member = _provider(module, tmp_path, "member-2", "another-bot", "target-project")
    outsider = _provider(module, tmp_path, "outsider", "outside-bot", "other-project")
    try:
        text = "copper lantern authorized project context"
        with owner._connect() as conn:
            conn.execute("""INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
                created_at,updated_at,freshness_at,hash,risk,secrecy_level,visibility_scope,
                origin_bot_id,origin_session_id,quality)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("c_project_share", text, "test", "active", .8, .8, "test", "",
                 module.now(), module.now(), module.now(), "project-share-hash", "low",
                 "public", "private", "owner-bot", "owner", .9))
        block_id = _call(owner, "memory_wiki_shared_block_create",
                         title="Project context", claim_ids=["c_project_share"])["block_id"]
        _call(owner, "memory_wiki_shared_block_grant", block_id=block_id,
              principal_type="project", principal_id="target-project")
        assert text not in _call(second_member, "memory_wiki_pack_context", query="copper lantern")["context"]
        assert _call(project_member, "memory_wiki_shared_block_attach",
                     block_id=block_id, principal_type="project")["status"] == "attached"
        assert text in _call(second_member, "memory_wiki_pack_context", query="copper lantern")["context"]
        assert text not in _call(outsider, "memory_wiki_pack_context", query="copper lantern")["context"]
        _call(owner, "memory_wiki_shared_block_revoke", block_id=block_id,
              principal_type="project", principal_id="target-project")
        assert text not in _call(second_member, "memory_wiki_pack_context", query="copper lantern")["context"]
    finally:
        for provider in (owner, project_member, second_member, outsider):
            if provider._conn is not None:
                provider._conn.close()
