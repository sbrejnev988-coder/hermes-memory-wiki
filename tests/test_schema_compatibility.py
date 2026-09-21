"""Database schema checks preserve scoped legacy data and reject downgrades."""

from __future__ import annotations

import importlib.util
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module():
    name = "memory_wiki_schema_contract_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(module, home: Path, session: str = "owner"):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        session, hermes_home=str(home), bot_id="bot-a", agent_context="test",
    )
    return provider


def _legacy_db(home: Path, chat_hash: str, *, scoped: bool = True) -> Path:
    path = home / "memory-wiki" / "memory_wiki.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('database_instance_id','synthetic-db-instance')"
        )
        acl = (
            ",visibility_scope TEXT NOT NULL,origin_bot_id TEXT NOT NULL,"
            "origin_session_id TEXT NOT NULL,origin_chat_hash TEXT NOT NULL,"
            "project_id TEXT NOT NULL,risk TEXT NOT NULL,quarantined_at INTEGER NOT NULL"
        ) if scoped else ""
        conn.execute(
            "CREATE TABLE claims(id TEXT PRIMARY KEY,claim TEXT NOT NULL,"
            "topic TEXT NOT NULL,status TEXT NOT NULL,source TEXT NOT NULL,"
            "evidence TEXT NOT NULL,confidence REAL NOT NULL,salience REAL NOT NULL,"
            "hash TEXT NOT NULL UNIQUE,created_at INTEGER NOT NULL,"
            "updated_at INTEGER NOT NULL,freshness_at INTEGER NOT NULL" + acl + ")"
        )
        values = [
            "legacy-private", "The blue observatory schedules the synthetic launch.",
            "general", "active", "test", "safe fixture", 0.9, 0.8,
            "synthetic-row-hash",
            100000, 100000, 100000,
        ]
        if scoped:
            values.extend(["chat", "bot-a", "owner", chat_hash, "", "low", 0])
        conn.execute(
            "INSERT INTO claims VALUES(" + ",".join("?" for _ in values) + ")", values,
        )
        conn.execute(
            "CREATE TABLE audit_log(id TEXT PRIMARY KEY,op TEXT NOT NULL,"
            "status TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO audit_log VALUES(?,?,?,?,?)",
            ("old-prefetch", "prefetch", "ok", '{"query_hash":"synthetic-fingerprint"}', 100000),
        )
        conn.execute(
            "INSERT INTO audit_log VALUES(?,?,?,?,?)",
            ("other-event", "other", "ok", "safe unrelated detail", 100000),
        )
    return path


def test_legacy_bootstrap_preserves_claim_acl_and_scrubs_old_prefetch(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    chat_hash = hashlib.sha256(b"synthetic-db-instance\0owner").hexdigest()[:32]
    path = _legacy_db(tmp_path, chat_hash)
    provider = _provider(module, tmp_path)
    try:
        conn = provider._connect()
        row = conn.execute("SELECT * FROM claims WHERE id='legacy-private'").fetchone()
        assert row["claim"] == "The blue observatory schedules the synthetic launch."
        assert row["visibility_scope"] == "chat"
        assert row["origin_bot_id"] == "bot-a"
        assert row["origin_chat_hash"] == provider._chat_hash("owner")
        assert provider._claim_visible(row)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
        assert conn.execute("SELECT detail FROM audit_log WHERE id='old-prefetch'").fetchone()[0] == "prefetch metadata redacted"
        assert conn.execute("SELECT detail FROM audit_log WHERE id='other-event'").fetchone()[0] == "safe unrelated detail"
    finally:
        provider._connect().close()
    assert path.is_file()


def test_second_initialize_keeps_ledger_and_private_row(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    first = _provider(module, tmp_path)
    try:
        with first._connect() as conn:
            conn.execute(
                "INSERT INTO claims(id,claim,normalized_claim,topic,status,confidence,salience,"
                "source,evidence,created_at,updated_at,freshness_at,hash,visibility_scope,"
                "origin_bot_id,origin_session_id,origin_chat_hash,quality,risk,quarantined_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("private-iris", "The Iris observatory reserves the synthetic calibration window.",
                 "The Iris observatory reserves the synthetic calibration window.",
                 "general", "active", 0.9, 0.8, "test", "fixture", 100000, 100000,
                 100000, "synthetic-private-hash", "chat", "bot-a", "owner",
                 first._chat_hash("owner"), 0.9, "low", 0),
            )
        before = [tuple(row) for row in first._connect().execute(
            "SELECT version,name,checksum,plugin_version,applied_at FROM schema_migrations"
        )]
        private = first._connect().execute(
            "SELECT id,visibility_scope,origin_chat_hash FROM claims WHERE claim LIKE '%Iris%'"
        ).fetchone()
        assert private is not None
        private = tuple(private)
    finally:
        first._connect().close()
    second = _provider(module, tmp_path, session="other")
    try:
        assert [tuple(row) for row in second._connect().execute(
            "SELECT version,name,checksum,plugin_version,applied_at FROM schema_migrations"
        )] == before
        row = second._connect().execute("SELECT * FROM claims WHERE id=?", (private[0],)).fetchone()
        assert tuple(row[key] for key in ("id", "visibility_scope", "origin_chat_hash")) == private
        assert not second._claim_visible(row)
    finally:
        second._connect().close()


def test_future_schema_is_rejected_before_migration_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    first = _provider(module, tmp_path)
    db = first.db_path
    first._connect().close()
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA user_version=2")
        conn.execute("INSERT INTO meta(key,value) VALUES('future_sentinel','unchanged')")
    second = module.MemoryWikiProvider()
    with pytest.raises(RuntimeError, match="newer"):
        second.initialize("owner", hermes_home=str(tmp_path), bot_id="bot-a")
    if second._conn is not None:
        second._conn.close()
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT value FROM meta WHERE key='future_sentinel'").fetchone()[0] == "unchanged"
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1


def test_tampered_migration_checksum_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    first = _provider(module, tmp_path)
    db = first.db_path
    first._connect().close()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE schema_migrations SET checksum='synthetic-invalid-checksum'")
    second = module.MemoryWikiProvider()
    with pytest.raises(RuntimeError, match="integrity"):
        second.initialize("owner", hermes_home=str(tmp_path), bot_id="bot-a")
    if second._conn is not None:
        second._conn.close()
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT checksum FROM schema_migrations").fetchone()[0] == "synthetic-invalid-checksum"


def test_legacy_populated_claim_without_acl_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    db = _legacy_db(tmp_path, "", scoped=False)
    provider = module.MemoryWikiProvider()
    with pytest.raises(RuntimeError, match="ownership"):
        provider.initialize("owner", hermes_home=str(tmp_path), bot_id="bot-a")
    if provider._conn is not None:
        provider._conn.close()
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone() is None


def test_logical_checkpoint_cannot_overwrite_runtime_schema_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module()
    provider = _provider(module, tmp_path)
    try:
        before = tuple(provider._connect().execute(
            "SELECT version,name,checksum,plugin_version,applied_at FROM schema_migrations"
        ).fetchone())
        provider._apply_checkpoint_payload({"tables": {"schema_migrations": [{
            "version": 2, "name": "unknown", "checksum": "synthetic-incorrect",
            "plugin_version": "999.0", "applied_at": 123,
        }]}})
        after = tuple(provider._connect().execute(
            "SELECT version,name,checksum,plugin_version,applied_at FROM schema_migrations"
        ).fetchone())
        assert after == before
        assert provider._connect().execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    finally:
        provider._connect().close()
