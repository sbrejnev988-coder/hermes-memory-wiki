"""Append-only, scoped event evidence for Memory Wiki.

The ledger stores sanitized observations supplied by trusted provider lifecycle
code.  It is deliberately separate from claims: an event is evidence about what
was observed, not an assertion that Memory Wiki has verified as durable truth.

All owner and visibility predicates are derived from the provider.  Callers may
choose a visibility class, but cannot provide an arbitrary owner identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from typing import Any, Callable, Iterable


_SCOPES = frozenset({"chat", "bot", "project"})
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_SAFE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,191}$")
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_EXCERPT_MARKER = "\n[... {omitted} chars omitted; source_length={source_length} ...]\n"


def enabled() -> bool:
    """Raw event retention is an explicit host policy decision."""
    return os.environ.get("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _bounded_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _safe_label(value: Any, field: str, *, default: str = "") -> str:
    text = str(value or default).strip()
    if not text or not _SAFE_LABEL_RE.fullmatch(text):
        raise ValueError(f"invalid {field}")
    return text


def _safe_optional_target(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if text and not _SAFE_TARGET_RE.fullmatch(text):
        raise ValueError(f"invalid {field}")
    return text


def _balanced_excerpt(
    text: Any,
    limit: int,
    *,
    source_length: int | None = None,
) -> tuple[str, bool]:
    """Return a bounded head+tail excerpt with an explicit omission marker."""
    value = str(text or "")
    cap = max(1, int(limit))
    if len(value) <= cap:
        return value, False
    original_length = max(len(value), int(source_length or 0))
    # The omitted count depends on marker width.  Iterate to a stable marker so
    # the stored metadata is truthful even when the digit count changes.
    marker = _EXCERPT_MARKER.format(
        omitted=max(0, len(value) - cap), source_length=original_length,
    )
    for _ in range(3):
        available = max(0, cap - len(marker))
        omitted = max(0, len(value) - available)
        updated = _EXCERPT_MARKER.format(
            omitted=omitted, source_length=original_length,
        )
        if updated == marker:
            break
        marker = updated
    if len(marker) >= cap:
        # The configured minimum is comfortably larger than the marker in
        # normal operation.  Keep an explicit marker even for direct helper use.
        return marker[:cap], True
    available = cap - len(marker)
    head = (available + 1) // 2
    tail = available - head
    excerpt = value[:head] + marker + (value[-tail:] if tail else "")
    return excerpt, True


def _principal(provider: Any, session_id: str = "") -> dict[str, str]:
    """Return the same database-bound chat identity used by episodic memory.

    Raw session identifiers are never persisted.  ``owner_chat_hash`` remains
    byte-for-byte compatible with :func:`episodic_memory._identity`; the second
    domain-separated hash makes the no-raw-session property explicit in the
    event schema.
    """

    # Background jobs persist only event IDs.  Their private worker instance
    # rehydrates the authoritative owner hashes from a still-retained event;
    # the original raw session identifier was intentionally never stored.
    job_owner = getattr(provider, "_background_job_owner", None)
    if job_owner is not None:
        if str(session_id or provider.session_id) != str(provider.session_id):
            raise ValueError("background event session cannot be changed")
        if not all(str(job_owner.get(key) or "") for key in (
            "bot_id", "chat_hash", "session_hash",
        )):
            raise ValueError("background event owner is incomplete")
        return dict(job_owner)
    owner = provider._scoped_backup_owner()
    bot_id = str(owner.get("bot_id") or "")
    current_session = str(owner.get("session_id") or "")
    selected_session = str(session_id or current_session)
    database_id = str(provider._meta_text("database_instance_id", "uninitialized"))
    if selected_session == current_session:
        chat_hash = str(owner.get("chat_hash") or "")
    else:
        chat_hash = hashlib.sha256(
            f"{database_id}\0{selected_session}".encode("utf-8", "ignore")
        ).hexdigest()[:32]
    session_hash = hashlib.sha256(
        f"memory-event-session-v1\0{database_id}\0{bot_id}\0{selected_session}".encode(
            "utf-8", "ignore"
        )
    ).hexdigest()[:32]
    return {
        "bot_id": bot_id,
        "chat_hash": chat_hash,
        "session_hash": session_hash,
        "project_id": str(owner.get("project_id") or ""),
    }


def _resolve_scope(
    provider: Any,
    *,
    session_id: str = "",
    scope: str = "chat",
    project_id: str = "",
) -> tuple[dict[str, str], str, str]:
    principal = _principal(provider, session_id)
    selected_scope = str(scope or "chat").strip().lower()
    if selected_scope not in _SCOPES:
        raise ValueError("invalid event visibility scope")
    if not principal["bot_id"] or not principal["chat_hash"] or not principal["session_hash"]:
        raise ValueError("event owner identity is unavailable")
    if selected_scope == "bot" and not bool(getattr(provider, "_bot_scope_trusted", False)):
        raise ValueError("bot event scope requires a distinct host bot identity")
    current_project = principal["project_id"]
    requested_project = str(project_id or current_project).strip()
    if project_id and requested_project != current_project:
        raise ValueError("event project must match the provider project")
    if selected_scope == "project" and not requested_project:
        raise ValueError("project event scope requires an active project")
    return principal, selected_scope, requested_project


def _event_owner_sql(
    alias: str,
    principal: dict[str, str],
    scope: str,
    project_id: str,
) -> tuple[str, tuple[Any, ...]]:
    prefix = f"{alias}." if alias else ""
    if scope == "chat":
        return (
            f"{prefix}owner_bot_id=? AND {prefix}owner_chat_hash=? "
            f"AND {prefix}owner_session_hash=? AND {prefix}visibility_scope='chat'",
            (principal["bot_id"], principal["chat_hash"], principal["session_hash"]),
        )
    if scope == "bot":
        return (
            f"{prefix}owner_bot_id=? AND {prefix}visibility_scope='bot'",
            (principal["bot_id"],),
        )
    return (
        f"{prefix}owner_bot_id=? AND {prefix}project_id=? "
        f"AND {prefix}visibility_scope='project'",
        (principal["bot_id"], project_id),
    )


def install_schema(conn: sqlite3.Connection) -> None:
    """Install the durable ledger, derived FTS index, and append-only guards."""

    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_events(
            event_id TEXT PRIMARY KEY,
            owner_bot_id TEXT NOT NULL,
            owner_chat_hash TEXT NOT NULL,
            owner_session_hash TEXT NOT NULL,
            visibility_scope TEXT NOT NULL
                CHECK(visibility_scope IN ('chat','bot','project')),
            project_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL,
            event_type TEXT NOT NULL,
            modality TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            truncated INTEGER NOT NULL DEFAULT 0 CHECK(truncated IN (0,1)),
            source_length INTEGER NOT NULL DEFAULT 0 CHECK(source_length>=0),
            occurred_at INTEGER NOT NULL,
            observed_at INTEGER NOT NULL,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            CHECK(length(content)>0),
            CHECK(length(content_hash)=64),
            CHECK(expires_at>created_at)
        )"""
    )
    actual = {str(row[1]) for row in conn.execute("PRAGMA table_info(memory_events)")}
    # Additive migration keeps old ledgers readable.  Legacy rows retain the
    # defaults and query-time fallback reports their stored content length.
    if "truncated" not in actual:
        conn.execute(
            "ALTER TABLE memory_events ADD COLUMN truncated INTEGER NOT NULL "
            "DEFAULT 0 CHECK(truncated IN (0,1))"
        )
    if "source_length" not in actual:
        conn.execute(
            "ALTER TABLE memory_events ADD COLUMN source_length INTEGER NOT NULL "
            "DEFAULT 0 CHECK(source_length>=0)"
        )
    required = {
        "event_id", "owner_bot_id", "owner_chat_hash", "owner_session_hash",
        "visibility_scope", "project_id", "turn_id", "role", "event_type",
        "modality", "content", "content_hash", "truncated", "source_length",
        "occurred_at", "observed_at", "provenance_json", "created_at", "expires_at",
    }
    actual = {str(row[1]) for row in conn.execute("PRAGMA table_info(memory_events)")}
    missing = required - actual
    if missing:
        raise RuntimeError("incompatible memory_events schema: missing " + ",".join(sorted(missing)))

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_events_owner_time "
        "ON memory_events(owner_bot_id,visibility_scope,owner_chat_hash,"
        "owner_session_hash,project_id,expires_at,occurred_at,event_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_events_owner_type "
        "ON memory_events(owner_bot_id,visibility_scope,event_type,modality,occurred_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_events_turn "
        "ON memory_events(owner_bot_id,turn_id,occurred_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_events_owner_created "
        "ON memory_events(owner_bot_id,created_at,observed_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_events_partition_created "
        "ON memory_events(owner_bot_id,visibility_scope,owner_chat_hash,"
        "owner_session_hash,created_at,observed_at,event_id)"
    )

    usage_exists = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='memory_event_owner_usage'"
    ).fetchone())
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_event_owner_usage(
            owner_bot_id TEXT PRIMARY KEY,
            row_count INTEGER NOT NULL DEFAULT 0 CHECK(row_count>=0),
            byte_count INTEGER NOT NULL DEFAULT 0 CHECK(byte_count>=0)
        )"""
    )
    if not usage_exists:
        # Existing ledgers pay for this aggregate once during upgrade. Subsequent
        # writes/deletes maintain it in the same transaction as their FTS rows.
        conn.execute(
            """INSERT INTO memory_event_owner_usage(owner_bot_id,row_count,byte_count)
               SELECT owner_bot_id,COUNT(*),SUM(
                   LENGTH(CAST(content AS BLOB)) +
                   LENGTH(CAST(provenance_json AS BLOB)))
               FROM memory_events GROUP BY owner_bot_id"""
        )
    conn.execute("DROP TRIGGER IF EXISTS memory_events_usage_ai")
    conn.execute(
        """CREATE TRIGGER memory_events_usage_ai AFTER INSERT ON memory_events
        BEGIN
            INSERT INTO memory_event_owner_usage(owner_bot_id,row_count,byte_count)
            VALUES(NEW.owner_bot_id,1,
                LENGTH(CAST(NEW.content AS BLOB)) +
                LENGTH(CAST(NEW.provenance_json AS BLOB)))
            ON CONFLICT(owner_bot_id) DO UPDATE SET
                row_count=row_count+1,
                byte_count=byte_count+excluded.byte_count;
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_events_usage_ad")
    conn.execute(
        """CREATE TRIGGER memory_events_usage_ad AFTER DELETE ON memory_events
        BEGIN
            UPDATE memory_event_owner_usage SET
                row_count=row_count-1,
                byte_count=byte_count-
                    LENGTH(CAST(OLD.content AS BLOB))-
                    LENGTH(CAST(OLD.provenance_json AS BLOB))
            WHERE owner_bot_id=OLD.owner_bot_id;
        END"""
    )

    partition_usage_exists = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='memory_event_partition_usage'"
    ).fetchone())
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_event_partition_usage(
            owner_bot_id TEXT NOT NULL,
            visibility_scope TEXT NOT NULL,
            owner_chat_hash TEXT NOT NULL,
            owner_session_hash TEXT NOT NULL,
            project_id TEXT NOT NULL,
            row_count INTEGER NOT NULL CHECK(row_count>=0),
            byte_count INTEGER NOT NULL CHECK(byte_count>=0),
            PRIMARY KEY(owner_bot_id,visibility_scope,owner_chat_hash,
                        owner_session_hash,project_id)
        )"""
    )
    if not partition_usage_exists:
        conn.execute(
            """INSERT INTO memory_event_partition_usage
              (owner_bot_id,visibility_scope,owner_chat_hash,owner_session_hash,
               project_id,row_count,byte_count)
               SELECT owner_bot_id,visibility_scope,
                 CASE WHEN visibility_scope='chat' THEN owner_chat_hash ELSE '' END,
                 CASE WHEN visibility_scope='chat' THEN owner_session_hash ELSE '' END,
                 CASE WHEN visibility_scope='project' THEN project_id ELSE '' END,
                 COUNT(*),SUM(LENGTH(CAST(content AS BLOB))+
                              LENGTH(CAST(provenance_json AS BLOB)))
               FROM memory_events GROUP BY owner_bot_id,visibility_scope,
                 CASE WHEN visibility_scope='chat' THEN owner_chat_hash ELSE '' END,
                 CASE WHEN visibility_scope='chat' THEN owner_session_hash ELSE '' END,
                 CASE WHEN visibility_scope='project' THEN project_id ELSE '' END"""
        )
    conn.execute("DROP TRIGGER IF EXISTS memory_events_partition_ai")
    conn.execute(
        """CREATE TRIGGER memory_events_partition_ai AFTER INSERT ON memory_events
        BEGIN
            INSERT INTO memory_event_partition_usage
              (owner_bot_id,visibility_scope,owner_chat_hash,owner_session_hash,
               project_id,row_count,byte_count)
            VALUES(NEW.owner_bot_id,NEW.visibility_scope,
              CASE WHEN NEW.visibility_scope='chat' THEN NEW.owner_chat_hash ELSE '' END,
              CASE WHEN NEW.visibility_scope='chat' THEN NEW.owner_session_hash ELSE '' END,
              CASE WHEN NEW.visibility_scope='project' THEN NEW.project_id ELSE '' END,
              1,LENGTH(CAST(NEW.content AS BLOB))+
                LENGTH(CAST(NEW.provenance_json AS BLOB)))
            ON CONFLICT(owner_bot_id,visibility_scope,owner_chat_hash,
                        owner_session_hash,project_id) DO UPDATE SET
              row_count=row_count+1,byte_count=byte_count+excluded.byte_count;
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_events_partition_ad")
    conn.execute(
        """CREATE TRIGGER memory_events_partition_ad AFTER DELETE ON memory_events
        BEGIN
            UPDATE memory_event_partition_usage SET
              row_count=row_count-1,
              byte_count=byte_count-LENGTH(CAST(OLD.content AS BLOB))-
                         LENGTH(CAST(OLD.provenance_json AS BLOB))
            WHERE owner_bot_id=OLD.owner_bot_id
              AND visibility_scope=OLD.visibility_scope
              AND owner_chat_hash=CASE WHEN OLD.visibility_scope='chat'
                                     THEN OLD.owner_chat_hash ELSE '' END
              AND owner_session_hash=CASE WHEN OLD.visibility_scope='chat'
                                        THEN OLD.owner_session_hash ELSE '' END
              AND project_id=CASE WHEN OLD.visibility_scope='project'
                                  THEN OLD.project_id ELSE '' END;
        END"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_event_evidence(
            link_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL DEFAULT 'supports',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id) ON DELETE CASCADE,
            UNIQUE(event_id,target_type,target_id,relation)
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_event_evidence_event "
        "ON memory_event_evidence(event_id,created_at,link_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_event_evidence_target "
        "ON memory_event_evidence(target_type,target_id,created_at,link_id)"
    )

    # UPDATE is never a legitimate ledger operation.  DELETE remains available
    # for TTL retention and explicit privacy erasure.
    conn.execute("DROP TRIGGER IF EXISTS memory_events_no_update")
    conn.execute(
        """CREATE TRIGGER memory_events_no_update BEFORE UPDATE ON memory_events
        BEGIN SELECT RAISE(ABORT,'memory_events is append-only'); END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_event_evidence_no_update")
    conn.execute(
        """CREATE TRIGGER memory_event_evidence_no_update
        BEFORE UPDATE ON memory_event_evidence
        BEGIN SELECT RAISE(ABORT,'memory_event_evidence is append-only'); END"""
    )
    # Do not depend on a connection's foreign_keys pragma for privacy deletion.
    conn.execute("DROP TRIGGER IF EXISTS memory_events_delete_links")
    conn.execute(
        """CREATE TRIGGER memory_events_delete_links AFTER DELETE ON memory_events
        BEGIN DELETE FROM memory_event_evidence WHERE event_id=OLD.event_id; END"""
    )

    # FTS5's UNINDEXED event_id cannot support deletion by equality without
    # scanning every document. Keep a stable INTEGER PRIMARY KEY docid mapping:
    # unlike the base table's implicit rowid, it survives SQLite VACUUM.
    mapping_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='memory_event_fts_docids'"
    ).fetchone()
    mapping_exists = bool(mapping_sql)
    if mapping_exists and "AUTOINCREMENT" not in str(mapping_sql[0]).upper():
        # Early numeric mappings may reuse a deleted highest ID. Durable job
        # watermarks require IDs never to be reused even after privacy erasure.
        conn.execute(
            """CREATE TABLE memory_event_fts_docids_new(
                docid INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE
            )"""
        )
        conn.execute(
            "INSERT INTO memory_event_fts_docids_new(docid,event_id) "
            "SELECT docid,event_id FROM memory_event_fts_docids"
        )
        conn.execute("DROP TABLE memory_event_fts_docids")
        conn.execute("ALTER TABLE memory_event_fts_docids_new RENAME TO memory_event_fts_docids")
        mapping_exists = False
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_event_fts_docids(
            docid INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE
        )"""
    )
    if not mapping_exists:
        conn.execute(
            "INSERT OR IGNORE INTO memory_event_fts_docids(event_id) "
            "SELECT event_id FROM memory_events ORDER BY rowid"
        )
    fts_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_events_fts'"
    ).fetchone()
    fts_exists = bool(fts_sql)
    if fts_exists:
        fts_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(memory_events_fts)")
        }
        if (fts_columns != {"event_id", "content", "event_type", "modality"}
                or "detail=full" not in str(fts_sql[0]).replace(" ", "").lower()):
            # FTS is derived state.  Dropping an incompatible index cannot lose
            # ledger data. The marker forces a one-time rebuild of legacy
            # implicit-rowid indexes when docid mapping is first introduced.
            conn.execute("DROP TRIGGER IF EXISTS memory_events_fts_ai")
            conn.execute("DROP TRIGGER IF EXISTS memory_events_fts_ad")
            conn.execute("DROP TABLE memory_events_fts")
            fts_exists = False
    conn.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts USING fts5(
            event_id UNINDEXED,content,event_type,modality,
            tokenize='unicode61',detail=full)"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_events_fts_ai")
    conn.execute(
        """CREATE TRIGGER memory_events_fts_ai AFTER INSERT ON memory_events BEGIN
            INSERT INTO memory_event_fts_docids(event_id) VALUES(NEW.event_id);
            INSERT INTO memory_events_fts(rowid,event_id,content,event_type,modality)
            VALUES((SELECT docid FROM memory_event_fts_docids
                    WHERE event_id=NEW.event_id),
                   NEW.event_id,NEW.content,NEW.event_type,NEW.modality);
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_events_fts_ad")
    conn.execute(
        """CREATE TRIGGER memory_events_fts_ad AFTER DELETE ON memory_events BEGIN
            DELETE FROM memory_events_fts WHERE rowid=(
                SELECT docid FROM memory_event_fts_docids WHERE event_id=OLD.event_id
            );
            DELETE FROM memory_event_fts_docids WHERE event_id=OLD.event_id;
        END"""
    )
    base_count = int(conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0])
    fts_count = int(conn.execute("SELECT COUNT(*) FROM memory_events_fts").fetchone()[0])
    if not fts_exists or not mapping_exists or base_count != fts_count:
        rebuild_fts(conn)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts_vocab "
        "USING fts5vocab(memory_events_fts,'row')"
    )


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Transactionally rebuild only derived FTS rows from the immutable ledger."""

    savepoint = "memory_events_fts_rebuild"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        conn.execute("DELETE FROM memory_events_fts")
        conn.execute(
            "DELETE FROM memory_event_fts_docids WHERE event_id NOT IN "
            "(SELECT event_id FROM memory_events)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO memory_event_fts_docids(event_id) "
            "SELECT event_id FROM memory_events"
        )
        conn.execute(
            "INSERT INTO memory_events_fts(rowid,event_id,content,event_type,modality) "
            "SELECT d.docid,e.event_id,e.content,e.event_type,e.modality "
            "FROM memory_events e JOIN memory_event_fts_docids d "
            "ON d.event_id=e.event_id"
        )
        base_count = int(conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0])
        fts_count = int(conn.execute("SELECT COUNT(*) FROM memory_events_fts").fetchone()[0])
        if base_count != fts_count:
            raise RuntimeError("memory event FTS rebuild count mismatch")
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")


def _canonical_provenance(provider: Any, module: Any, provenance: Any) -> str | None:
    if provenance in (None, ""):
        return "{}"
    if not isinstance(provenance, (dict, list)):
        return None
    try:
        raw = json.dumps(
            provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    limit = _bounded_env("MEMORY_WIKI_EVENT_PROVENANCE_BYTES", 4096, 128, 16384)
    if len(raw.encode("utf-8", "ignore")) > limit:
        return None
    scrubbed = module.scrub_memory_artifacts(raw)
    if module.secret_scan(scrubbed).get("raw_secret"):
        return None
    redacted = module.redact_secrets(scrubbed)
    checked = provider._inspect_recall_text(
        redacted,
        source="host:event_ledger:provenance",
        mem_type="event_provenance",
        audit=False,
        max_len=limit,
    )
    if checked.get("status") != "safe":
        return None
    sanitized = str(checked.get("content") or "").strip()
    try:
        parsed = json.loads(sanitized)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, (dict, list)):
        return None
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prune_events(provider: Any, *, conn: sqlite3.Connection | None = None,
                 scope: str = "chat", project_id: str = "",
                 session_id: str = "") -> int:
    """Bound one authorized visibility partition without evicting peer chats."""

    principal, selected_scope, selected_project = _resolve_scope(
        provider, session_id=session_id, scope=scope, project_id=project_id,
    )
    owner_sql, owner_params = _event_owner_sql(
        "", principal, selected_scope, selected_project,
    )
    partition_key = (
        principal["bot_id"], selected_scope,
        principal["chat_hash"] if selected_scope == "chat" else "",
        principal["session_hash"] if selected_scope == "chat" else "",
        selected_project if selected_scope == "project" else "",
    )
    database = conn or provider._connect()
    def usage() -> tuple[int, int]:
        row = database.execute(
            "SELECT row_count,byte_count FROM memory_event_partition_usage "
            "WHERE owner_bot_id=? AND visibility_scope=? AND owner_chat_hash=? "
            "AND owner_session_hash=? AND project_id=?", partition_key,
        ).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    before, _ = usage()
    stamp = int(time.time())
    database.execute(
        f"DELETE FROM memory_events WHERE {owner_sql} AND expires_at<=?",
        (*owner_params, stamp),
    )
    max_rows = _bounded_env("MEMORY_WIKI_EVENT_MAX_ROWS", 20000, 1, 10_000_000)
    max_bytes = _bounded_env(
        "MEMORY_WIKI_EVENT_MAX_BYTES", 32_000_000, 16_384, 16_000_000_000
    )
    rows, retained_bytes = usage()
    if rows > max_rows:
        database.execute(
            f"""DELETE FROM memory_events WHERE event_id IN (
               SELECT event_id FROM memory_events WHERE {owner_sql}
               ORDER BY created_at,observed_at,rowid LIMIT ?)""",
            (*owner_params, rows - max_rows),
        )
        rows, retained_bytes = usage()
    # Fetch only as many oldest rows as are needed to satisfy the byte cap.
    # No full-partition window scan runs on every capture at 1M+ rows.
    while retained_bytes > max_bytes and rows:
        oldest = database.execute(
            f"""SELECT event_id,
                  LENGTH(CAST(content AS BLOB)) +
                  LENGTH(CAST(provenance_json AS BLOB)) AS size_bytes
               FROM memory_events WHERE {owner_sql}
               ORDER BY created_at,observed_at,rowid LIMIT 2048""",
            owner_params,
        ).fetchall()
        if not oldest:
            raise RuntimeError("memory event usage aggregate is inconsistent")
        selected: list[str] = []
        reclaimed = 0
        for event in oldest:
            selected.append(str(event[0]))
            reclaimed += int(event[1])
            if retained_bytes - reclaimed <= max_bytes:
                break
        database.execute(
            "DELETE FROM memory_events WHERE event_id IN (" +
            ",".join("?" for _ in selected) + ")",
            selected,
        )
        rows, retained_bytes = usage()
    after = rows
    if conn is None:
        database.commit()
    return max(0, before - after)


def erase_memory_mutation_events(
    provider: Any,
    module: Any,
    *,
    claim_ids: Iterable[str] = (),
    exact_contents: Iterable[str] = (),
    conn: sqlite3.Connection | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Erase matching provider-visible event evidence for a host removal.

    A host ``remove`` must not leave the removed text recallable through the
    event or observation layers. Dialogue, mutation and visual-derived events
    inside the caller's exact chat or authorized shared partitions are scanned.
    Linked events are erased by claim ID; unlinked content is erased when its
    normalized text equals or contains the removed sentence.

    The caller may pass an existing transaction.  Deleting a source event then
    activates the observation privacy trigger, which removes the complete
    derived observation and its immutable version history.
    """

    principal = _principal(provider, session_id)
    if not principal["bot_id"] or not principal["chat_hash"] or not principal["session_hash"]:
        raise ValueError("event owner identity is unavailable")
    database = conn or provider._connect()

    owner_clauses: list[str] = []
    owner_params: list[Any] = []
    chat_sql, chat_params = _event_owner_sql("e", principal, "chat", "")
    owner_clauses.append(f"({chat_sql})")
    owner_params.extend(chat_params)
    # The fallback ``default`` bot can represent several agents and is not a
    # safe cross-chat identity, matching the normal bot-scope query policy.
    if bool(getattr(provider, "_bot_scope_trusted", False)):
        bot_sql, bot_params = _event_owner_sql("e", principal, "bot", "")
        owner_clauses.append(f"({bot_sql})")
        owner_params.extend(bot_params)
    if principal["project_id"]:
        project_sql, project_params = _event_owner_sql(
            "e", principal, "project", principal["project_id"],
        )
        owner_clauses.append(f"({project_sql})")
        owner_params.extend(project_params)

    safe_claim_ids = sorted({
        value for value in (
            _safe_optional_target(item, "claim_id") for item in claim_ids
        ) if value
    })
    normalize = getattr(module, "normalize_claim", None)
    if not callable(normalize):
        raise RuntimeError("claim normalizer is unavailable")
    normalized_targets = {
        str(normalize(value) or "").casefold()
        for value in exact_contents
        if str(value or "").strip()
    }
    normalized_targets.discard("")

    linked_sql = "0 AS linked"
    # SQL placeholders in the SELECT expression precede the owner predicates.
    query_params: list[Any] = []
    if safe_claim_ids:
        placeholders = ",".join("?" for _ in safe_claim_ids)
        linked_sql = (
            "EXISTS(SELECT 1 FROM memory_event_evidence l "
            "WHERE l.event_id=e.event_id AND l.target_type='claim' "
            f"AND l.target_id IN ({placeholders})) AS linked"
        )
        query_params.extend(safe_claim_ids)
    query_params.extend(owner_params)
    rows = database.execute(
        f"""SELECT e.event_id,e.content,{linked_sql}
              FROM memory_events e
             WHERE ({' OR '.join(owner_clauses)})
             ORDER BY e.event_id""",
        tuple(query_params),
    ).fetchall()

    event_ids: list[str] = []
    linked_ids: set[str] = set()
    content_ids: set[str] = set()
    for row in rows:
        event_id = str(row["event_id"])
        linked = bool(int(row["linked"] or 0))
        source_text = str(normalize(str(row["content"] or "")) or "").casefold()
        # Exact token boundaries also apply to short phrases.  A length gate
        # let a host remove "I use Vim" while retaining an unlinked event
        # saying "I use Vim for coding" (and its derived observation).
        content_match = any(
            source_text == target or bool(re.search(
                r"(?<!\w)" + re.escape(target) + r"(?!\w)", source_text,
            ))
            for target in normalized_targets
        )
        if linked or content_match:
            event_ids.append(event_id)
            if linked:
                linked_ids.add(event_id)
            if content_match:
                content_ids.add(event_id)

    observation_ids: set[str] = set()
    if event_ids and database.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='memory_observation_events'"
    ).fetchone():
        for offset in range(0, len(event_ids), 400):
            chunk = event_ids[offset:offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            observation_ids.update(
                str(row[0]) for row in database.execute(
                    "SELECT DISTINCT observation_id FROM memory_observation_events "
                    f"WHERE event_id IN ({placeholders})",
                    tuple(chunk),
                ).fetchall()
            )

    deleted = 0
    for offset in range(0, len(event_ids), 400):
        chunk = event_ids[offset:offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        cursor = database.execute(
            f"DELETE FROM memory_events WHERE event_id IN ({placeholders})",
            tuple(chunk),
        )
        deleted += max(0, int(cursor.rowcount))
    if conn is None:
        database.commit()
    return {
        "deleted": deleted,
        "event_ids": event_ids,
        "linked_deleted": len(linked_ids),
        "exact_content_deleted": len(content_ids),
        "observations_deleted": len(observation_ids),
    }


def capture_event(
    provider: Any,
    module: Any,
    content: str,
    *,
    role: str = "observer",
    event_type: str = "observation",
    modality: str = "text",
    turn_id: str = "",
    occurred_at: int | None = None,
    observed_at: int | None = None,
    provenance: dict[str, Any] | list[Any] | None = None,
    session_id: str = "",
    scope: str = "chat",
    project_id: str = "",
    ttl_days: int | None = None,
    _after_insert: Callable[[sqlite3.Connection, str], None] | None = None,
) -> str | None:
    """Append a sanitized event and return its opaque ID.

    ``None`` means the input failed secret, injection, identity, or size checks.
    Programmer errors in labels and scope raise ``ValueError`` so integrations
    cannot silently write data into an unintended partition.
    """

    if not enabled():
        return None

    selected_role = _safe_label(role, "event role", default="observer")
    selected_type = _safe_label(event_type, "event type", default="observation")
    selected_modality = _safe_label(modality, "event modality", default="text")
    selected_turn = _safe_optional_target(turn_id, "event turn_id")
    principal, selected_scope, selected_project = _resolve_scope(
        provider,
        session_id=session_id,
        scope=scope,
        project_id=project_id,
    )

    raw = module.scrub_memory_artifacts(str(content or ""))
    # Scan the complete source before any excerpting.  A secret in the omitted
    # middle must reject the event rather than disappear behind the size cap.
    if not raw.strip() or module.secret_scan(raw).get("raw_secret"):
        return None
    redacted = module.redact_secrets(raw).strip()
    if not redacted:
        return None
    source_length = len(redacted)
    max_content = _bounded_env("MEMORY_WIKI_EVENT_MAX_CONTENT", 4000, 128, 16000)
    # Let the injection guard inspect the full redacted source.  Bounding is a
    # storage concern applied only after the guard has accepted the event.
    checked = provider._inspect_recall_text(
        redacted,
        source="host:event_ledger",
        mem_type="event",
        audit=False,
        max_len=max(max_content, source_length),
    )
    if checked.get("status") != "safe":
        return None
    guarded_content = str(checked.get("content") or "").strip()
    if not guarded_content or module.secret_scan(guarded_content).get("raw_secret"):
        return None
    safe_content, truncated = _balanced_excerpt(
        guarded_content, max_content, source_length=source_length,
    )
    if not safe_content or module.secret_scan(safe_content).get("raw_secret"):
        return None
    provenance_json = _canonical_provenance(provider, module, provenance)
    if provenance_json is None:
        return None

    created = int(time.time())
    observed = max(0, int(observed_at if observed_at is not None else created))
    occurred = max(0, int(occurred_at if occurred_at is not None else observed))
    if ttl_days is None:
        ttl = _bounded_env("MEMORY_WIKI_EVENT_TTL_DAYS", 90, 1, 3650)
    else:
        ttl = max(1, min(int(ttl_days), 3650))
    event_id = "evt_" + uuid.uuid4().hex
    digest = hashlib.sha256(safe_content.encode("utf-8", "ignore")).hexdigest()
    conn = provider._connect()
    with conn:
        conn.execute(
            """INSERT INTO memory_events(
                event_id,owner_bot_id,owner_chat_hash,owner_session_hash,
                visibility_scope,project_id,turn_id,role,event_type,modality,
                content,content_hash,truncated,source_length,occurred_at,observed_at,
                provenance_json,created_at,expires_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                principal["bot_id"],
                principal["chat_hash"],
                principal["session_hash"],
                selected_scope,
                selected_project,
                selected_turn,
                selected_role,
                selected_type,
                selected_modality,
                safe_content,
                digest,
                int(truncated),
                source_length,
                occurred,
                observed,
                provenance_json,
                created,
                created + ttl * 86400,
            ),
        )
        if _after_insert is not None:
            # A derived source registry must commit or roll back with the
            # underlying event; never leave an untracked OCR excerpt on crash.
            _after_insert(conn, event_id)
        prune_events(provider, conn=conn, scope=selected_scope,
                     project_id=selected_project, session_id=session_id)
    return event_id


def _fts_expression(module: Any, query: str, mode: str) -> str:
    safe_builder = getattr(module, "safe_fts_query", None)
    if callable(safe_builder):
        return str(safe_builder(str(query or "")[:500], mode=mode) or "")
    tokens = _TOKEN_RE.findall(str(query or "").lower())[:12]
    operator = " AND " if mode == "and" else " OR "
    return operator.join('"' + token.replace('"', '""') + '"' for token in tokens)


def _common_recent_candidates(
    conn: sqlite3.Connection,
    query: str,
    where_sql: str,
    filter_params: list[Any],
    candidate_limit: int,
) -> list[Any]:
    """Bound a single very common term by a recent exact-token window.

    Ranking millions of FTS postings for a broad term takes seconds and adds
    little evidence discrimination. This path reads at most the last 100k
    inserted rows and stops at ``candidate_limit`` exact word matches. A rare
    query, sparse scope, or insufficient window falls through to FTS ranking.
    """

    tokens = _TOKEN_RE.findall(query.casefold())
    if len(tokens) != 1 or len(query) > 96:
        return []
    token = tokens[0]
    if not token or len(token) < 3:
        return []
    try:
        vocab = conn.execute(
            "SELECT doc FROM memory_events_fts_vocab WHERE term=?", (token,)
        ).fetchone()
    except sqlite3.Error:
        return []
    if not vocab or int(vocab[0]) <= 10_000:
        return []
    maximum = conn.execute("SELECT MAX(rowid) FROM memory_events").fetchone()[0]
    if maximum is None:
        return []
    rows = conn.execute(
        f"""SELECT e.*,NULL AS fts_rank FROM memory_events e NOT INDEXED
            WHERE e.rowid>=? AND {where_sql}
            ORDER BY e.rowid DESC LIMIT 4000""",
        (max(1, int(maximum) - 100_000), *filter_params),
    ).fetchall()
    matches = [row for row in rows if token in _TOKEN_RE.findall(
        str(row["content"]).casefold()
    )]
    return matches[:candidate_limit] if len(matches) >= candidate_limit else []


def _event_links(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not event_ids:
        return {}
    placeholders = ",".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""SELECT event_id,target_type,target_id,relation,created_at
            FROM memory_event_evidence WHERE event_id IN ({placeholders})
            ORDER BY created_at,link_id""",
        tuple(event_ids),
    ).fetchall()
    output: dict[str, list[dict[str, Any]]] = {event_id: [] for event_id in event_ids}
    for row in rows:
        target_type = str(row["target_type"])
        target_id = str(row["target_id"])
        relation = str(row["relation"])
        # Link rows normally enter through ``link_evidence``.  Keep a direct
        # database insertion from turning metadata into prompt-like text.
        if (
            not _SAFE_LABEL_RE.fullmatch(target_type)
            or not _SAFE_TARGET_RE.fullmatch(target_id)
            or not _SAFE_LABEL_RE.fullmatch(relation)
        ):
            continue
        output.setdefault(str(row["event_id"]), []).append(
            {
                "target_type": target_type,
                "target_id": target_id,
                "relation": relation,
                "created_at": int(row["created_at"]),
            }
        )
    return output


def _read_provenance(provider: Any, module: Any, raw: Any, event_id: str) -> Any:
    text = str(raw or "{}")
    if module.secret_scan(text).get("raw_secret"):
        return {}
    checked = provider._inspect_recall_text(
        text,
        source="event_ledger:provenance",
        mem_type="event_provenance",
        item_id=event_id,
        audit=False,
        max_len=_bounded_env("MEMORY_WIKI_EVENT_PROVENANCE_BYTES", 4096, 128, 16384),
    )
    if checked.get("status") != "safe":
        return {}
    try:
        parsed = json.loads(str(checked.get("content") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, (dict, list)) else {}


def query_events(
    provider: Any,
    module: Any,
    query: str = "",
    limit: int = 8,
    *,
    scope: str = "chat",
    project_id: str = "",
    session_id: str = "",
    event_types: Iterable[str] | None = None,
    modalities: Iterable[str] | None = None,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Query one exact event partition, applying owner predicates before LIMIT."""

    started = time.perf_counter()
    principal, selected_scope, selected_project = _resolve_scope(
        provider,
        session_id=session_id,
        scope=scope,
        project_id=project_id,
    )
    requested_limit = max(1, min(int(limit), 50))
    owner_sql, owner_params = _event_owner_sql(
        "e", principal, selected_scope, selected_project
    )
    type_values = [event_types] if isinstance(event_types, str) else (event_types or [])
    media_values = [modalities] if isinstance(modalities, str) else (modalities or [])
    types = sorted({_safe_label(item, "event type filter") for item in type_values})
    media = sorted({_safe_label(item, "event modality filter") for item in media_values})
    filters = [owner_sql, "e.expires_at>?"]
    filter_params: list[Any] = [*owner_params, int(time.time())]
    if types:
        filters.append("e.event_type IN (" + ",".join("?" for _ in types) + ")")
        filter_params.extend(types)
    if media:
        filters.append("e.modality IN (" + ",".join("?" for _ in media) + ")")
        filter_params.extend(media)
    where_sql = " AND ".join(filters)

    conn = provider._connect()
    candidates: list[Any] = []
    seen: set[str] = set()
    expression_query = str(query or "").strip()
    if expression_query:
        candidate_limit = min(400, max(40, requested_limit * 8))
        candidates = _common_recent_candidates(
            conn, expression_query, where_sql, filter_params, candidate_limit,
        )
        seen.update(str(row["event_id"]) for row in candidates)
        for mode in (() if candidates else ("and", "or")):
            expression = _fts_expression(module, expression_query, mode)
            if not expression:
                continue
            rows = conn.execute(
                f"""SELECT e.*,bm25(memory_events_fts) AS fts_rank
                    FROM memory_events_fts
                    JOIN memory_event_fts_docids d
                      ON d.docid=memory_events_fts.rowid
                    JOIN memory_events e ON e.event_id=d.event_id
                    WHERE memory_events_fts MATCH ? AND {where_sql}
                    ORDER BY fts_rank,e.occurred_at DESC,e.event_id
                    LIMIT ?""",
                (expression, *filter_params, candidate_limit),
            ).fetchall()
            for row in rows:
                event_id = str(row["event_id"])
                if event_id not in seen:
                    seen.add(event_id)
                    candidates.append(row)
            # Validate after retrieval.  Raw AND hits can fill the requested
            # limit while every one of them later fails the content hash,
            # secret, or recall guard checks.  Collect the bounded OR fallback
            # as well so a rejected AND row cannot starve safe results.
    else:
        candidates = conn.execute(
            f"""SELECT e.*,NULL AS fts_rank FROM memory_events e
                WHERE {where_sql}
                ORDER BY e.occurred_at DESC,e.event_id LIMIT ?""",
            (*filter_params, min(400, max(40, requested_limit * 8))),
        ).fetchall()

    events: list[dict[str, Any]] = []
    rejected_secret = 0
    rejected_guard = 0
    rejected_hash = 0
    for row in candidates:
        stored_content = str(row["content"])
        if hashlib.sha256(stored_content.encode("utf-8", "ignore")).hexdigest() != str(
            row["content_hash"]
        ):
            rejected_hash += 1
            continue
        if module.secret_scan(stored_content).get("raw_secret"):
            rejected_secret += 1
            continue
        try:
            recorded_source_length = max(0, int(row["source_length"] or 0))
        except (TypeError, ValueError, OverflowError):
            recorded_source_length = 0
        source_length = max(len(stored_content), recorded_source_length)
        try:
            stored_truncated = bool(int(row["truncated"] or 0))
        except (TypeError, ValueError, OverflowError):
            stored_truncated = source_length > len(stored_content)
        # New rows are already bounded, but balance an oversized legacy/imported
        # row before the guard rather than front-cutting it.  For ordinary rows
        # max_len covers the complete stored excerpt, including its tail.
        guard_cap = _bounded_env(
            "MEMORY_WIKI_EVENT_MAX_CONTENT", 4000, 128, 16000,
        )
        guard_content, guard_input_truncated = _balanced_excerpt(
            stored_content, guard_cap, source_length=source_length,
        )
        checked = provider._inspect_recall_text(
            guard_content,
            source="event_ledger:untrusted",
            mem_type="event",
            item_id=str(row["event_id"]),
            audit=False,
            max_len=max(guard_cap, len(guard_content)),
        )
        if checked.get("status") != "safe":
            rejected_guard += 1
            continue
        guarded_content = str(checked.get("content") or "").strip()
        if not guarded_content:
            rejected_guard += 1
            continue
        recall_cap = _bounded_env(
            "MEMORY_WIKI_EVENT_RECALL_CONTENT", 1200, 128, 4000,
        )
        safe_content, recall_truncated = _balanced_excerpt(
            guarded_content, recall_cap, source_length=source_length,
        )
        if not safe_content or module.secret_scan(safe_content).get("raw_secret"):
            rejected_guard += 1
            continue
        provenance = _read_provenance(
            provider, module, row["provenance_json"], str(row["event_id"])
        )
        events.append(
            {
                "event_id": str(row["event_id"]),
                "turn_id": str(row["turn_id"]),
                "role": str(row["role"]),
                "event_type": str(row["event_type"]),
                "modality": str(row["modality"]),
                "content": safe_content,
                "content_hash": str(row["content_hash"]),
                "truncated": bool(
                    stored_truncated or guard_input_truncated or recall_truncated
                ),
                "source_length": source_length,
                "occurred_at": int(row["occurred_at"]),
                "observed_at": int(row["observed_at"]),
                "created_at": int(row["created_at"]),
                "expires_at": int(row["expires_at"]),
                "scope": str(row["visibility_scope"]),
                "project_id": str(row["project_id"]),
                "provenance": provenance,
                "trust_level": "untrusted_evidence",
            }
        )
        if len(events) >= requested_limit:
            break
    links = _event_links(conn, [event["event_id"] for event in events])
    for event in events:
        event["evidence_links"] = links.get(event["event_id"], [])
    result: dict[str, Any] = {
        "scope": selected_scope,
        "project_id": selected_project if selected_scope == "project" else "",
        "events": events,
    }
    if include_diagnostics:
        result["diagnostics"] = {
            "candidates": len(candidates),
            "secret_rejected": rejected_secret,
            "guard_rejected": rejected_guard,
            "hash_rejected": rejected_hash,
            "search_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    return result


def link_evidence(
    provider: Any,
    event_id: str,
    target_type: str,
    target_id: str,
    *,
    relation: str = "supports",
) -> str:
    """Append a generic event-to-memory evidence edge.

    The target deliberately has no polymorphic foreign key.  The event side is
    authenticated against the provider's currently accessible chat, bot, or
    project partitions before the link is inserted.
    """

    selected_event = _safe_optional_target(event_id, "event_id")
    if not selected_event:
        raise ValueError("invalid event_id")
    selected_type = _safe_label(target_type, "evidence target_type")
    selected_target = _safe_optional_target(target_id, "evidence target_id")
    if not selected_target:
        raise ValueError("invalid evidence target_id")
    selected_relation = _safe_label(relation, "evidence relation", default="supports")
    principal = _principal(provider)
    if not principal["bot_id"]:
        raise ValueError("event owner identity is unavailable")
    project_clause = ""
    project_params: tuple[Any, ...] = ()
    if principal["project_id"]:
        project_clause = (
            " OR (visibility_scope='project' AND owner_bot_id=? AND project_id=?)"
        )
        project_params = (principal["bot_id"], principal["project_id"])
    conn = provider._connect()
    row = conn.execute(
        """SELECT event_id FROM memory_events WHERE event_id=? AND expires_at>?
           AND (
             (visibility_scope='chat' AND owner_bot_id=? AND owner_chat_hash=?
              AND owner_session_hash=?)
             OR (visibility_scope='bot' AND owner_bot_id=?)"""
        + project_clause
        + ")",
        (
            selected_event,
            int(time.time()),
            principal["bot_id"],
            principal["chat_hash"],
            principal["session_hash"],
            principal["bot_id"],
            *project_params,
        ),
    ).fetchone()
    if row is None:
        raise PermissionError("event is not accessible to this provider")
    stamp = int(time.time())
    link_id = "evl_" + uuid.uuid4().hex
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO memory_event_evidence(
                link_id,event_id,target_type,target_id,relation,created_at
            ) VALUES(?,?,?,?,?,?)""",
            (
                link_id,
                selected_event,
                selected_type,
                selected_target,
                selected_relation,
                stamp,
            ),
        )
        existing = conn.execute(
            """SELECT link_id FROM memory_event_evidence
               WHERE event_id=? AND target_type=? AND target_id=? AND relation=?""",
            (selected_event, selected_type, selected_target, selected_relation),
        ).fetchone()
    if existing is None:
        raise RuntimeError("event evidence link was not persisted")
    return str(existing["link_id"] if isinstance(existing, sqlite3.Row) else existing[0])
