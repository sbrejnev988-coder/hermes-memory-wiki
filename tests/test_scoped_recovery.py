"""Logical snapshots must restore only the exact creator's claims."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_scoped_recovery_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _call(provider, name, **kwargs):
    return json.loads(provider.handle_tool_call(name, kwargs))


def _insert_claim(provider, claim_id, text, visibility="private"):
    owner = provider._scoped_backup_owner()
    with provider._connect() as conn:
        conn.execute(
            """INSERT INTO claims(id,claim,topic,status,confidence,salience,source,evidence,
               created_at,updated_at,freshness_at,hash,origin_bot_id,origin_session_id,
               origin_chat_hash,visibility_scope,project_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claim_id, text, "recovery", "active", .9, .9, "test", "", 1, 1, 1,
             "hash_" + claim_id, owner["bot_id"], owner["session_id"],
             owner["chat_hash"], visibility, owner["project_id"]),
        )
        conn.execute("INSERT INTO evidence(id,claim_id,kind,text,source,created_at) VALUES(?,?,?,?,?,?)",
                     ("ev_" + claim_id, claim_id, "support", "Evidence for " + text, "test", 1))


def test_signed_scoped_backup_isolated_and_restores_own_deleted_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.delenv("MEMORY_WIKI_ALLOW_SHARED_RECOVERY", raising=False)
    module = _module()
    owner = module.MemoryWikiProvider()
    viewer = module.MemoryWikiProvider()
    owner.initialize("owner-session", hermes_home=str(tmp_path), bot_id="owner-bot", project_id="owner-project", agent_context="test")
    viewer.initialize("viewer-session", hermes_home=str(tmp_path), bot_id="viewer-bot", project_id="viewer-project", agent_context="test")
    try:
        _insert_claim(owner, "c_scoped_owner", "Owner recovery sentinel")
        _insert_claim(viewer, "c_scoped_viewer", "Viewer recovery sentinel", visibility="global")
        created = _call(owner, "memory_wiki_scoped_backup", reason="test")
        assert created["success"] is True and created["claims"] == 1
        backup_id = created["id"]
        payload = owner._load_scoped_backup(backup_id)
        assert [row["id"] for row in payload["claims"]] == ["c_scoped_owner"]
        assert [row["claim_id"] for row in payload["evidence"]] == ["c_scoped_owner"]
        assert [row["id"] for row in _call(owner, "memory_wiki_list_scoped_backups")["backups"]] == [backup_id]
        assert _call(viewer, "memory_wiki_list_scoped_backups")["backups"] == []
        assert _call(viewer, "memory_wiki_restore_scoped_backup", backup_id=backup_id).get("success") is not True
        assert _call(owner, "memory_wiki_restore_scoped_backup", backup_id=str(tmp_path / "legacy.zip")).get("success") is not True
        assert _call(owner, "memory_wiki_restore", backup=backup_id)["error"] == "shared_recovery_requires_trusted_host"

        with owner._connect() as conn:
            conn.execute("DELETE FROM claims WHERE id='c_scoped_owner'")
            conn.execute("UPDATE claims SET claim='Viewer changed sentinel' WHERE id='c_scoped_viewer'")
        restored = _call(owner, "memory_wiki_restore_scoped_backup", backup_id=backup_id)
        assert restored["success"] is True and restored["claims_restored"] == 1
        claims = {row["id"]: row["claim"] for row in owner._connect().execute("SELECT id,claim FROM claims")}
        assert claims == {"c_scoped_owner": "Owner recovery sentinel", "c_scoped_viewer": "Viewer changed sentinel"}
        assert owner._connect().execute("SELECT text FROM evidence WHERE claim_id='c_scoped_owner'").fetchone()[0] == "Evidence for Owner recovery sentinel"
    finally:
        for provider in (owner, viewer):
            if provider._conn is not None:
                provider._conn.close()


def test_scoped_backup_rejects_tamper_and_foreign_id_collision(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    owner = module.MemoryWikiProvider()
    foreign = module.MemoryWikiProvider()
    owner.initialize("owner", hermes_home=str(tmp_path), bot_id="owner", agent_context="test")
    foreign.initialize("foreign", hermes_home=str(tmp_path), bot_id="foreign", agent_context="test")
    try:
        _insert_claim(owner, "c_scoped_collision", "Before collision")
        backup_id = _call(owner, "memory_wiki_scoped_backup")["id"]
        path = owner._scoped_backup_dir() / (backup_id + ".json")
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace("Before collision", "Tampered claim"), encoding="utf-8")
        assert _call(owner, "memory_wiki_restore_scoped_backup", backup_id=backup_id).get("success") is not True
        path.write_text(original, encoding="utf-8")
        with owner._connect() as conn:
            conn.execute("DELETE FROM claims WHERE id='c_scoped_collision'")
        _insert_claim(foreign, "c_scoped_collision", "Foreign ID collision")
        denied = _call(owner, "memory_wiki_restore_scoped_backup", backup_id=backup_id)
        assert denied.get("success") is not True
        assert owner._connect().execute("SELECT claim FROM claims WHERE id='c_scoped_collision'").fetchone()[0] == "Foreign ID collision"
    finally:
        for provider in (owner, foreign):
            if provider._conn is not None:
                provider._conn.close()


def test_scoped_restore_is_journal_replayable(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("session", hermes_home=str(tmp_path), bot_id="bot", agent_context="test")
    try:
        assert "memory_wiki_restore_scoped_backup" in provider._replayable_journal_ops()
        assert "memory_wiki_list_scoped_backups" in provider._nonmutating_journal_tools()
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_scoped_restore_survives_journal_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("session", hermes_home=str(tmp_path), bot_id="bot", agent_context="test")
    try:
        _insert_claim(provider, "c_scoped_replay", "Original replay value")
        checkpoint = provider._journal_checkpoint("before-scoped-restore")
        backup_id = _call(provider, "memory_wiki_scoped_backup")["id"]
        updated = _call(provider, "memory_wiki_update_claim", claim_id="c_scoped_replay", claim="Changed replay value")
        assert updated["success"] is True, updated
        assert _call(provider, "memory_wiki_restore_scoped_backup", backup_id=backup_id)["success"] is True
        assert provider._connect().execute("SELECT claim FROM claims WHERE id='c_scoped_replay'").fetchone()[0] == "Original replay value"
        plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
        assert plan["unrecoverable_events"] == 0 and plan["incomplete_events"] == 0, plan
        rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        assert rebuilt["failed"] == 0, rebuilt
        assert provider._connect().execute("SELECT claim FROM claims WHERE id='c_scoped_replay'").fetchone()[0] == "Original replay value"
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_manifest_and_mcp_cache_match_native_tool_schemas(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    native = module.MemoryWikiProvider().get_tool_schemas()
    root = PLUGIN.parent
    cached = json.loads((root / "mcp-wrapper" / "tool_schemas.json").read_text(encoding="utf-8"))
    assert native == cached
    manifest = (root / "plugin.yaml").read_text(encoding="utf-8")
    listed = [line.strip()[2:] for line in manifest.partition("provides_tools:\n")[2].splitlines()
              if line.startswith("  - ")]
    assert [schema["name"] for schema in native] == listed


def test_scoped_backup_rekeys_chat_hash_after_database_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("session", hermes_home=str(tmp_path), bot_id="bot", agent_context="test")
    try:
        _insert_claim(provider, "c_scoped_rekey", "Before database replacement")
        backup_id = _call(provider, "memory_wiki_scoped_backup")["id"]
        old_hash = provider._scoped_backup_owner()["chat_hash"]
        with provider._connect() as conn:
            conn.execute("UPDATE meta SET value=? WHERE key='database_instance_id'", ("replacement-instance",))
        new_hash = provider._scoped_backup_owner()["chat_hash"]
        assert old_hash != new_hash
        assert _call(provider, "memory_wiki_restore_scoped_backup", backup_id=backup_id)["success"] is True
        row = provider._connect().execute("SELECT origin_chat_hash FROM claims WHERE id='c_scoped_rekey'").fetchone()
        assert row[0] == new_hash
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_scoped_backup_excludes_secrets_quarantine_and_linked_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("session", hermes_home=str(tmp_path), bot_id="bot", agent_context="test")
    try:
        for claim_id in ("c_safe_one", "c_safe_two", "c_secret", "c_quarantine",
                         "c_internal", "c_raw_claim", "c_raw_evidence", "c_raw_metadata",
                         "c_raw_timezone"):
            _insert_claim(provider, claim_id, "Safe text " + claim_id)
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET risk='secret', claim='password=supersecret-risk' WHERE id='c_secret'")
            conn.execute("UPDATE claims SET quarantined_at=123, claim='password=supersecret-quarantine' WHERE id='c_quarantine'")
            conn.execute("UPDATE claims SET secrecy_level='internal', claim='Internal-only sentinel' WHERE id='c_internal'")
            conn.execute("UPDATE claims SET claim='password=supersecret-raw-claim' WHERE id='c_raw_claim'")
            conn.execute("UPDATE claims SET event_timezone='password=supersecret-timezone' WHERE id='c_raw_timezone'")
            conn.execute("UPDATE evidence SET text='password=supersecret-evidence' WHERE claim_id='c_raw_evidence'")
            conn.execute("INSERT INTO code_claim_metadata(claim_id,repository_id,file_path) VALUES(?,?,?)",
                         ("c_raw_metadata", "repo", "token=supersecret-metadata"))
            conn.execute("INSERT INTO contradictions(id,claim_a,claim_b,reason,status,created_at) VALUES(?,?,?,?,?,?)",
                         ("k_secret_reason", "c_safe_one", "c_safe_two", "password=supersecret-reason", "open", 1))
        backup_id = _call(provider, "memory_wiki_scoped_backup", reason="password=supersecret-reason")["id"]
        payload = provider._load_scoped_backup(backup_id)
        assert {row["id"] for row in payload["claims"]} == {"c_safe_one", "c_safe_two"}
        assert {row["claim_id"] for row in payload["evidence"]} == {"c_safe_one", "c_safe_two"}
        assert payload["code_claim_metadata"] == []
        assert payload["contradictions"] == []
        artifact = (provider._scoped_backup_dir() / (backup_id + ".json")).read_text(encoding="utf-8")
        assert "supersecret" not in artifact
        assert "Internal-only sentinel" not in artifact
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_scoped_backup_rejects_linked_artifact_and_key(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("session", hermes_home=str(tmp_path), bot_id="bot", agent_context="test")
    try:
        _insert_claim(provider, "c_link_guard", "Safe link test")
        backup_id = _call(provider, "memory_wiki_scoped_backup")["id"]
        artifact = provider._scoped_backup_dir() / (backup_id + ".json")
        artifact_alias = tmp_path / "artifact-hardlink.json"
        try:
            artifact_alias.hardlink_to(artifact)
        except (OSError, NotImplementedError):
            pass
        else:
            with pytest.raises(ValueError, match="unsafe scoped backup file"):
                provider._load_scoped_backup(backup_id)
            artifact_alias.unlink()
        key = provider.root / ".scoped-backup-key"
        key_alias = tmp_path / "key-hardlink"
        try:
            key_alias.hardlink_to(key)
        except (OSError, NotImplementedError):
            pass
        else:
            with pytest.raises(ValueError, match="unsafe scoped backup file"):
                provider._load_scoped_backup(backup_id)
            key_alias.unlink()
        assert provider._load_scoped_backup(backup_id)["id"] == backup_id
        linked_id = "scopebak_" + "0" * 32
        symlink = provider._scoped_backup_dir() / (linked_id + ".json")
        try:
            symlink.symlink_to(artifact)
        except (OSError, NotImplementedError):
            pass
        else:
            with pytest.raises(ValueError, match="unsafe scoped backup file"):
                provider._load_scoped_backup(linked_id)
        original_backups_dir = provider.backups_dir
        directory_link = tmp_path / "backups-directory-link"
        try:
            directory_link.symlink_to(original_backups_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            provider.backups_dir = directory_link
            with pytest.raises(ValueError, match="unsafe scoped backup directory"):
                provider._scoped_backup_dir()
            provider.backups_dir = original_backups_dir
    finally:
        if provider._conn is not None:
            provider._conn.close()


def test_scoped_restore_reports_derived_render_failure_after_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    module = _module()
    provider = module.MemoryWikiProvider()
    provider.initialize("session", hermes_home=str(tmp_path), bot_id="bot", agent_context="test")
    try:
        _insert_claim(provider, "c_render_deferred", "Original owned value")
        backup_id = _call(provider, "memory_wiki_scoped_backup")["id"]
        with provider._connect() as conn:
            conn.execute("UPDATE claims SET claim='Changed owned value' WHERE id='c_render_deferred'")
        monkeypatch.setattr(provider, "_render_all", lambda: (_ for _ in ()).throw(OSError("render unavailable")))
        result = _call(provider, "memory_wiki_restore_scoped_backup", backup_id=backup_id)
        assert result["success"] is True and result["rendered"] is False
        assert provider._connect().execute("SELECT claim FROM claims WHERE id='c_render_deferred'").fetchone()[0] == "Original owned value"
        plan = provider._rebuild_from_journal(apply=False)
        assert plan["unrecoverable_events"] == 0 and plan["incomplete_events"] == 0, plan
    finally:
        if provider._conn is not None:
            provider._conn.close()
