"""Compatibility ledger around the provider's historical idempotent DDL.

The existing provider migration creates and repairs its tables in place. This
module checks database ownership/version *before* that code runs, then records
the successfully installed schema after it finishes. Future migrations must
append a numbered, checksummed record rather than silently reinterpreting an
older database.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time


DB_SCHEMA_VERSION = 1
DB_SCHEMA_COMPAT_MIN = 1
_BOOTSTRAP_NAME = "bootstrap_scoped_memory_wiki_v1"
_BOOTSTRAP_CHECKSUM = hashlib.sha256(
    b"memory-wiki/schema/v1:scoped-provider-ddl:prefetch-query-hash-scrub"
).hexdigest()
_LEDGER_COLUMNS = frozenset({
    "version", "name", "checksum", "plugin_version", "applied_at",
})
_CLAIM_BASE_COLUMNS = frozenset({
    "id", "claim", "topic", "status", "source", "evidence",
    "confidence", "salience", "hash",
    "created_at", "updated_at", "freshness_at",
})
_CLAIM_ACL_COLUMNS = frozenset({
    "visibility_scope", "origin_bot_id", "origin_session_id",
    "origin_chat_hash", "project_id", "risk", "quarantined_at",
})


class IncompatibleSchemaError(RuntimeError):
    """The database must not be changed or queried by this plugin version."""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    # All table identifiers here are module-owned constants, never input.
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def assert_schema_compatible(conn: sqlite3.Connection) -> bool:
    """Return True for a versionless legacy DB; reject unknown versions/shape.

This is read-only. In particular it runs before the provider's CREATE TABLE,
ALTER TABLE, and data repair statements, so a future database is untouched.
"""
    pragma_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if pragma_version > DB_SCHEMA_VERSION:
        raise IncompatibleSchemaError("Memory Wiki database schema is newer than this runtime")
    tables = _tables(conn)
    if "schema_migrations" in tables:
        if not _LEDGER_COLUMNS.issubset(_columns(conn, "schema_migrations")):
            raise IncompatibleSchemaError("Memory Wiki schema ledger has an unsupported shape")
        rows = conn.execute(
            "SELECT version,name,checksum,plugin_version,applied_at "
            "FROM schema_migrations ORDER BY version"
        ).fetchall()
        if not rows:
            raise IncompatibleSchemaError("Memory Wiki schema ledger is incomplete")
        versions = [int(row[0]) for row in rows]
        if versions[-1] > DB_SCHEMA_VERSION:
            raise IncompatibleSchemaError("Memory Wiki database schema is newer than this runtime")
        if versions[0] < DB_SCHEMA_COMPAT_MIN:
            raise IncompatibleSchemaError("Memory Wiki database schema is older than this runtime")
        if versions != [DB_SCHEMA_VERSION] or pragma_version != DB_SCHEMA_VERSION:
            raise IncompatibleSchemaError("Memory Wiki schema ledger and database version disagree")
        row = rows[0]
        if (str(row[1]), str(row[2])) != (_BOOTSTRAP_NAME, _BOOTSTRAP_CHECKSUM):
            raise IncompatibleSchemaError("Memory Wiki schema ledger integrity check failed")
        if not str(row[3]).strip() or int(row[4]) <= 0:
            raise IncompatibleSchemaError("Memory Wiki schema ledger is incomplete")
        if not {"meta", "claims"}.issubset(tables):
            raise IncompatibleSchemaError("Memory Wiki versioned database is missing core tables")
        if not _CLAIM_ACL_COLUMNS.issubset(_columns(conn, "claims")):
            raise IncompatibleSchemaError("Memory Wiki versioned database is missing ACL columns")
        return False

    if pragma_version != 0:
        raise IncompatibleSchemaError("Unversioned Memory Wiki database has an unknown schema version")
    if not tables:
        return True
    if not {"meta", "claims"}.issubset(tables):
        raise IncompatibleSchemaError("Unversioned database has an unrecognized Memory Wiki shape")
    if not {"key", "value"}.issubset(_columns(conn, "meta")):
        raise IncompatibleSchemaError("Unversioned Memory Wiki metadata has an unknown shape")
    columns = _columns(conn, "claims")
    if not _CLAIM_BASE_COLUMNS.issubset(columns):
        raise IncompatibleSchemaError("Unversioned Memory Wiki claims have an unknown shape")
    if (not _CLAIM_ACL_COLUMNS.issubset(columns)
            and conn.execute("SELECT 1 FROM claims LIMIT 1").fetchone() is not None):
        # Populated legacy rows without ownership cannot be defaulted to
        # global visibility. A manual, provenance-aware import is required.
        raise IncompatibleSchemaError("Legacy claim ownership cannot be established")
    return True


def record_schema_version(conn: sqlite3.Connection, plugin_version: str) -> None:
    """Mark the completed schema, including one-time privacy repair."""
    if not assert_schema_compatible(conn):
        return
    if not str(plugin_version).strip():
        raise ValueError("plugin_version must be nonempty")
    # The provider has completed its schema installation before this point.
    # The scrub and ledger marker commit together even if CREATE TABLE would
    # otherwise run in SQLite autocommit mode. A concurrent bootstrap that
    # won the race is checked rather than overwritten.
    conn.execute("SAVEPOINT mw_schema_marker")
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY CHECK(version >= 1),
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            plugin_version TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        )""")
        if conn.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone():
            assert_schema_compatible(conn)
        else:
            conn.execute(
                "UPDATE audit_log SET detail='prefetch metadata redacted' "
                "WHERE op='prefetch' AND detail LIKE '%\"query_hash\"%'"
            )
            conn.execute(
                "INSERT INTO schema_migrations(version,name,checksum,plugin_version,applied_at) "
                "VALUES(?,?,?,?,?)",
                (DB_SCHEMA_VERSION, _BOOTSTRAP_NAME, _BOOTSTRAP_CHECKSUM,
                 str(plugin_version), int(time.time())),
            )
            conn.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION}")
        conn.execute("RELEASE SAVEPOINT mw_schema_marker")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT mw_schema_marker")
        conn.execute("RELEASE SAVEPOINT mw_schema_marker")
        raise
