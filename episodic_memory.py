"""Opt-in, host-attested dialogue evidence. Episodes never become trusted claims.

Only MemoryWikiProvider.sync_turn calls capture_turn. Model-facing access is a
bounded read through query_episodes; the caller cannot select an owner or scope.
"""

from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import sys
import time
import re
import unicodedata
import uuid
from typing import Any

try:
    from .recall_planner import expand_memory_queries
except ImportError:  # pragma: no cover - direct module loading in legacy hosts
    from recall_planner import expand_memory_queries


def enabled() -> bool:
    return os.environ.get("MEMORY_WIKI_EPISODIC_ENABLED", "0").lower() in {"1", "true", "yes", "on"}


def _scope() -> str:
    return "bot" if os.environ.get("MEMORY_WIKI_EPISODIC_SCOPE", "chat").lower() == "bot" else "chat"


def _bounded_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        value = default
    return max(minimum, min(value, maximum))


_CAPTURE_MAX_CHARS = 1200
_TRUNCATION_MARKER = "\n… [middle omitted] …\n"


def _balanced_excerpt(value: str, max_chars: int) -> tuple[str, bool, int]:
    """Keep comparable head/tail evidence inside one deterministic bound."""
    text = str(value or "").strip()
    source_chars = len(text)
    cap = max(1, int(max_chars))
    if source_chars <= cap:
        return text, False, source_chars
    if cap <= len(_TRUNCATION_MARKER) + 2:
        # This branch is unreachable for configured capture/recall bounds, but
        # remains balanced for direct callers and future lower limits.
        head_chars = (cap + 1) // 2
        return text[:head_chars] + text[-(cap - head_chars):], True, source_chars
    available = cap - len(_TRUNCATION_MARKER)
    head_chars = (available + 1) // 2
    tail_chars = available - head_chars
    excerpt = (
        text[:head_chars].rstrip()
        + _TRUNCATION_MARKER
        + text[-tail_chars:].lstrip()
    )
    # Whitespace trimming only shortens the result; retain a hard defensive cap.
    if len(excerpt) > cap:
        overflow = len(excerpt) - cap
        excerpt = excerpt[: max(0, head_chars - overflow)] + _TRUNCATION_MARKER + text[-tail_chars:]
    return excerpt, True, source_chars


def install_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS episodic_turns(
        id TEXT PRIMARY KEY, content TEXT NOT NULL, role TEXT NOT NULL
            CHECK(role IN ('user','assistant')),
        turn_id TEXT NOT NULL DEFAULT '',
        owner_bot_id TEXT NOT NULL, owner_chat_hash TEXT NOT NULL,
        visibility_scope TEXT NOT NULL CHECK(visibility_scope IN ('chat','bot')),
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        truncated INTEGER NOT NULL DEFAULT 0 CHECK(truncated IN (0,1)),
        source_chars INTEGER NOT NULL DEFAULT 0 CHECK(source_chars>=0),
        vector_manifest_hash TEXT NOT NULL DEFAULT '',
        vector_target_hash TEXT NOT NULL DEFAULT '',
        vector_collection TEXT NOT NULL DEFAULT '',
        vector_endpoint TEXT NOT NULL DEFAULT '')""")
    # Forward-compatible migration for databases created before paired turn
    # context existed.  Legacy rows keep an empty identifier and therefore
    # retain their exact single-row retrieval behaviour.
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(episodic_turns)").fetchall()}
    if "turn_id" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN turn_id TEXT NOT NULL DEFAULT ''")
    if "vector_manifest_hash" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN vector_manifest_hash TEXT NOT NULL DEFAULT ''")
    if "vector_target_hash" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN vector_target_hash TEXT NOT NULL DEFAULT ''")
    if "vector_collection" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN vector_collection TEXT NOT NULL DEFAULT ''")
    if "vector_endpoint" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN vector_endpoint TEXT NOT NULL DEFAULT ''")
    if "truncated" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0")
    if "source_chars" not in columns:
        conn.execute("ALTER TABLE episodic_turns ADD COLUMN source_chars INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "UPDATE episodic_turns SET source_chars=LENGTH(content) WHERE source_chars<=0"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_owner_expiry ON episodic_turns(owner_bot_id,visibility_scope,owner_chat_hash,expires_at,created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_turn_pair ON episodic_turns(owner_bot_id,visibility_scope,owner_chat_hash,turn_id,expires_at,created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS episodic_vector_targets(
        episode_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        collection TEXT NOT NULL,
        vector_target_hash TEXT NOT NULL,
        manifest_hash TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active','delete_pending','deleted')),
        indexed_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY(episode_id,endpoint,collection,vector_target_hash))""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_episode_vector_targets_episode "
        "ON episodic_vector_targets(episode_id,status,updated_at)"
    )
    # Rebuild target history after a logical checkpoint restore.  New writes
    # persist both columns; databases from before this migration safely leave
    # them empty and will establish history on their next semantic backfill.
    conn.execute("""INSERT OR IGNORE INTO episodic_vector_targets(
            episode_id,endpoint,collection,vector_target_hash,manifest_hash,
            status,indexed_at,updated_at)
        SELECT id,vector_endpoint,vector_collection,vector_target_hash,
               vector_manifest_hash,'active',created_at,created_at
          FROM episodic_turns
         WHERE vector_endpoint<>'' AND vector_collection<>''
           AND vector_target_hash<>''""")
    # FTS5's UNINDEXED id requires a full table scan for DELETE WHERE id=?.
    # Keep an INTEGER PRIMARY KEY docid that survives VACUUM; the base table's
    # implicit rowid is not a durable surrogate for this purpose.
    mapping_exists = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='episodic_fts_docids'"
    ).fetchone())
    for trigger in ("episodic_turns_ai", "episodic_turns_ad", "episodic_turns_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS episodic_fts_docids(
            docid INTEGER PRIMARY KEY,
            episode_id TEXT NOT NULL UNIQUE
        )"""
    )
    if not mapping_exists:
        conn.execute(
            "INSERT INTO episodic_fts_docids(episode_id) "
            "SELECT id FROM episodic_turns ORDER BY rowid"
        )
    fts_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='episodic_turns_fts'"
    ).fetchone()
    fts_exists = bool(fts_sql)
    if fts_exists:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(episodic_turns_fts)")
        }
        if columns != {"id", "content"} or "fts5" not in str(fts_sql[0]).lower():
            # FTS is derived state. The canonical episode rows remain intact.
            conn.execute("DROP TABLE episodic_turns_fts")
            fts_exists = False
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS episodic_turns_fts "
        "USING fts5(id UNINDEXED,content,tokenize='unicode61')"
    )
    conn.execute(
        """CREATE TRIGGER episodic_turns_ai AFTER INSERT ON episodic_turns BEGIN
            INSERT INTO episodic_fts_docids(episode_id) VALUES(NEW.id);
            INSERT INTO episodic_turns_fts(rowid,id,content)
            VALUES((SELECT docid FROM episodic_fts_docids
                    WHERE episode_id=NEW.id),NEW.id,NEW.content);
        END"""
    )
    conn.execute(
        """CREATE TRIGGER episodic_turns_ad AFTER DELETE ON episodic_turns BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM episodic_fts_docids WHERE episode_id=OLD.id
            ) THEN RAISE(ABORT,'episode FTS docid missing') END;
            DELETE FROM episodic_turns_fts WHERE rowid=(
                SELECT docid FROM episodic_fts_docids WHERE episode_id=OLD.id
            );
            DELETE FROM episodic_fts_docids WHERE episode_id=OLD.id;
        END"""
    )
    conn.execute(
        """CREATE TRIGGER episodic_turns_au
        AFTER UPDATE OF id,content ON episodic_turns BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM episodic_fts_docids WHERE episode_id=OLD.id
            ) THEN RAISE(ABORT,'episode FTS docid missing') END;
            DELETE FROM episodic_turns_fts WHERE rowid=(
                SELECT docid FROM episodic_fts_docids WHERE episode_id=OLD.id
            );
            INSERT OR IGNORE INTO episodic_fts_docids(episode_id) VALUES(NEW.id);
            DELETE FROM episodic_fts_docids
              WHERE episode_id=OLD.id AND OLD.id<>NEW.id;
            INSERT INTO episodic_turns_fts(rowid,id,content)
            VALUES((SELECT docid FROM episodic_fts_docids
                    WHERE episode_id=NEW.id),NEW.id,NEW.content);
        END"""
    )
    base_count = int(conn.execute("SELECT COUNT(*) FROM episodic_turns").fetchone()[0])
    mapping_count = int(conn.execute("SELECT COUNT(*) FROM episodic_fts_docids").fetchone()[0])
    fts_count = int(conn.execute("SELECT COUNT(*) FROM episodic_turns_fts").fetchone()[0])
    # Counts alone cannot detect an orphaned/wrong docid. These indexed joins
    # also repair a legacy index whose implicit rowids were reordered by VACUUM.
    mapping_mismatch = bool(conn.execute(
        """SELECT 1 FROM episodic_turns e
           LEFT JOIN episodic_fts_docids d ON d.episode_id=e.id
           WHERE d.docid IS NULL LIMIT 1"""
    ).fetchone()) or bool(conn.execute(
        """SELECT 1 FROM episodic_fts_docids d
           LEFT JOIN episodic_turns e ON e.id=d.episode_id
           WHERE e.id IS NULL LIMIT 1"""
    ).fetchone())
    fts_mismatch = bool(conn.execute(
        """SELECT 1 FROM episodic_fts_docids d
           LEFT JOIN episodic_turns_fts f ON f.rowid=d.docid
           WHERE f.id IS NULL OR f.id<>d.episode_id LIMIT 1"""
    ).fetchone())
    if (not mapping_exists or not fts_exists or base_count != mapping_count
            or base_count != fts_count or mapping_mismatch or fts_mismatch):
        rebuild_fts(conn)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild only the derived index after a checkpoint or FTS corruption."""
    savepoint = "episodic_fts_rebuild"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        conn.execute("DELETE FROM episodic_turns_fts")
        conn.execute(
            "DELETE FROM episodic_fts_docids WHERE episode_id NOT IN "
            "(SELECT id FROM episodic_turns)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO episodic_fts_docids(episode_id) "
            "SELECT id FROM episodic_turns"
        )
        conn.execute(
            "INSERT INTO episodic_turns_fts(rowid,id,content) "
            "SELECT d.docid,e.id,e.content FROM episodic_turns e "
            "JOIN episodic_fts_docids d ON d.episode_id=e.id"
        )
        base_count = int(conn.execute("SELECT COUNT(*) FROM episodic_turns").fetchone()[0])
        fts_count = int(conn.execute("SELECT COUNT(*) FROM episodic_turns_fts").fetchone()[0])
        if base_count != fts_count:
            raise RuntimeError("episodic FTS rebuild count mismatch")
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")


def _identity(provider: Any, session_id: str = "") -> tuple[str, str]:
    owner = provider._scoped_backup_owner()  # Fresh DB identity after restore.
    if session_id and session_id != owner["session_id"]:
        database_id = provider._meta_text("database_instance_id", "uninitialized")
        chat_hash = hashlib.sha256(f"{database_id}\0{session_id}".encode("utf-8", "ignore")).hexdigest()[:32]
    else:
        chat_hash = str(owner["chat_hash"])
    return str(owner["bot_id"]), chat_hash


def _provider_module(provider: Any, module: Any | None = None) -> Any | None:
    if module is not None:
        return module
    return sys.modules.get(getattr(provider.__class__, "__module__", ""))


def _semantic_enabled(module: Any | None) -> bool:
    try:
        return bool(module and module._episodic_semantic_enabled())
    except Exception:
        return False


def _semantic_was_enabled(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='episodic_semantic_ever_enabled'"
        ).fetchone()
        return bool(row and str(row[0]) == "1")
    except sqlite3.DatabaseError:
        return False


def _episode_has_vector_history(conn: sqlite3.Connection, row_id: str) -> bool:
    """Catch old indexed rows even if their feature marker was lost."""
    try:
        if conn.execute(
            "SELECT 1 FROM episodic_vector_targets WHERE episode_id=? LIMIT 1",
            (row_id,),
        ).fetchone():
            return True
        return bool(conn.execute(
            """SELECT 1 FROM index_outbox WHERE object_type='episode'
               AND object_id=? AND operation IN ('upsert','embed_and_upsert')
               LIMIT 1""",
            (row_id,),
        ).fetchone())
    except sqlite3.DatabaseError:
        return False


def _recorded_episode_targets(
    module: Any, conn: sqlite3.Connection, row_id: str,
) -> list[dict[str, str]]:
    """Return every durable or in-flight vector location for one episode."""
    manifest = module._embedding_manifest()
    current_collection = module._episodic_collection_name(manifest)
    current_endpoint = module._normalized_qdrant_endpoint()
    current_target = module._episodic_vector_target_hash(
        manifest, collection=current_collection,
    )
    targets: dict[tuple[str, str], dict[str, str]] = {
        (current_endpoint, current_collection): {
            "endpoint": current_endpoint,
            "collection": current_collection,
            "vector_target_hash": current_target,
            "manifest_hash": module._manifest_hash(manifest),
        }
    }
    try:
        history = conn.execute(
            """SELECT endpoint,collection,vector_target_hash,manifest_hash
                 FROM episodic_vector_targets WHERE episode_id=?""",
            (str(row_id),),
        ).fetchall()
        for row in history:
            endpoint = str(row[0] or "").strip()
            collection = str(row[1] or "").strip()
            if endpoint and collection:
                targets[(endpoint, collection)] = {
                    "endpoint": endpoint,
                    "collection": collection,
                    "vector_target_hash": str(row[2] or ""),
                    "manifest_hash": str(row[3] or ""),
                }
    except sqlite3.DatabaseError:
        pass
    # A processing embed may not have reached target history yet.  Preserve its
    # retained location before privacy deletion removes pending embed jobs.
    try:
        pending = conn.execute(
            """SELECT payload_json FROM index_outbox
                WHERE object_type='episode' AND object_id=?
                  AND operation IN ('upsert','embed_and_upsert')""",
            (str(row_id),),
        ).fetchall()
        for row in pending:
            try:
                payload = json.loads(str(row[0] or "{}"))
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            endpoint = str(
                payload.get("endpoint") or current_endpoint
            ).strip()
            collection = str(payload.get("collection") or "").strip()
            if endpoint and collection:
                targets[(endpoint, collection)] = {
                    "endpoint": endpoint,
                    "collection": collection,
                    "vector_target_hash": str(payload.get("vector_target_hash") or ""),
                    "manifest_hash": str(payload.get("manifest_hash") or ""),
                }
    except sqlite3.DatabaseError:
        pass
    return list(targets.values())


def _enqueue_episode_delete(module: Any | None, conn: sqlite3.Connection, row_id: str) -> bool:
    if module is None:
        return False
    queued = False
    for target in _recorded_episode_targets(module, conn, str(row_id)):
        module._outbox_enqueue(
            "delete", "episode", str(row_id),
            {**target, "reason": "episode_removed"},
            conn=conn,
        )
        queued = True
    return queued


def _wake_semantic_worker(provider: Any, module: Any | None) -> None:
    if module is None:
        return
    try:
        module._start_outbox_worker(str(provider.db_path))
        module._wake_outbox_worker(str(provider.db_path))
    except Exception:
        # The durable outbox row is sufficient; the normal worker poll will
        # retry after transient initialization or wake failures.
        pass


def enqueue_semantic_backfill(provider: Any, module: Any) -> int:
    """Queue owner-scoped rows missing from the active vector target.

    The function performs no network work and is idempotent because outbox
    enqueue coalesces pending jobs for the same episode. Rows are marked only
    after Qdrant confirms the upsert.
    """
    if not enabled() or not _semantic_enabled(module):
        return 0
    bot, _chat = _identity(provider)
    if not bot:
        return 0
    stamp = int(time.time())
    manifest_hash = module._manifest_hash(module._embedding_manifest())
    target_hash = module._episodic_vector_target_hash()
    cap = _bounded_env("MEMORY_WIKI_EPISODIC_SEMANTIC_BACKFILL_ROWS", 5000, 1, 20000)
    conn = provider._connect()
    rows = conn.execute("""SELECT id,content,role,turn_id,owner_bot_id,
            owner_chat_hash,visibility_scope,created_at,expires_at
        FROM episodic_turns
        WHERE owner_bot_id=? AND expires_at>?
          AND (vector_manifest_hash<>? OR vector_target_hash<>?)
        ORDER BY created_at DESC,id LIMIT ?""",
        (bot, stamp, manifest_hash, target_hash, cap),
    ).fetchall()
    queued = 0
    with conn:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('episodic_semantic_ever_enabled','1') "
            "ON CONFLICT(key) DO UPDATE SET value='1'"
        )
        for row in rows:
            content = str(row["content"] or "").strip()
            if not content or module.secret_scan(content).get("raw_secret"):
                continue
            checked = provider._inspect_recall_text(
                content, source="episodic:semantic-backfill", mem_type="episode",
                item_id=str(row["id"]), audit=False, max_len=_CAPTURE_MAX_CHARS,
            )
            if checked.get("status") != "safe":
                continue
            document = str(checked.get("content") or "").strip()
            if not document or module.secret_scan(document).get("raw_secret"):
                continue
            module._outbox_enqueue("embed_and_upsert", "episode", str(row["id"]), {
                "text": document,
                "collection": module._episodic_collection_name(),
                "endpoint": module._normalized_qdrant_endpoint(),
                "manifest_hash": manifest_hash,
                "vector_target_hash": target_hash,
                "role": str(row["role"]),
                "turn_id": str(row["turn_id"] or ""),
                "owner_bot_id": str(row["owner_bot_id"]),
                "owner_chat_hash": str(row["owner_chat_hash"]),
                "visibility_scope": str(row["visibility_scope"]),
                "created_at": int(row["created_at"]),
                "expires_at": int(row["expires_at"]),
            }, conn=conn)
            queued += 1
    if queued:
        _wake_semantic_worker(provider, module)
    return queued


def capture_turn(provider: Any, module: Any, role: str, text: str, *, session_id: str = "",
                 turn_id: str = "") -> str | None:
    """Capture a bounded excerpt from trusted provider lifecycle input only."""
    if not enabled() or role not in {"user", "assistant"}:
        return None
    # Reject the entire turn on a detected secret rather than persisting a
    # redaction marker next to potentially revealing surrounding text.
    raw = module.scrub_memory_artifacts(str(text or ""))
    if not raw.strip() or module.secret_scan(raw).get("raw_secret"):
        return None
    redacted = module.redact_secrets(raw).strip()
    excerpt, was_truncated, source_chars = _balanced_excerpt(
        redacted, _CAPTURE_MAX_CHARS,
    )
    checked = provider._inspect_recall_text(
        excerpt, source="host:sync_turn", mem_type="episode", audit=False,
        max_len=_CAPTURE_MAX_CHARS,
    )
    if checked.get("status") != "safe":
        return None
    content = str(checked.get("content") or "").strip()
    if not content or module.secret_scan(content).get("raw_secret"):
        return None
    bot, chat = _identity(provider, session_id)
    if not bot or not chat:
        return None
    scope = _scope()
    if scope == "bot" and not bool(getattr(provider, "_bot_scope_trusted", False)):
        # A platform fallback can represent several users in one profile.
        return None
    stamp = int(time.time())
    ttl = _bounded_env("MEMORY_WIKI_EPISODIC_TTL_DAYS", 30, 1, 365) * 86400
    row_id = "ep_" + uuid.uuid4().hex
    # This value originates in the host lifecycle, never in a model-facing
    # tool call.  Keep a narrow alphabet and bound anyway so the database
    # cannot accumulate attacker-controlled grouping keys through an adapter.
    group_id = str(turn_id or "").strip()
    if (len(group_id) > 96
            or any(not (ch.isascii() and (ch.isalnum() or ch in "_-")) for ch in group_id)):
        group_id = ""
    conn = provider._connect()
    semantic = _semantic_enabled(module)
    queued = False
    with conn:
        conn.execute("""INSERT INTO episodic_turns
            (id,content,role,turn_id,owner_bot_id,owner_chat_hash,visibility_scope,
             created_at,expires_at,truncated,source_chars)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id, content, role, group_id, bot, chat, scope, stamp,
                stamp + ttl, int(was_truncated), source_chars,
            ))
        # Expiry is absolute; quotas below are isolated by visibility partition.
        expired_ids = [str(row[0]) for row in conn.execute(
            "SELECT id FROM episodic_turns WHERE owner_bot_id=? AND expires_at<=?",
            (bot, stamp),
        ).fetchall()]
        conn.execute("DELETE FROM episodic_turns WHERE owner_bot_id=? AND expires_at<=?", (bot, stamp))
        max_rows = _bounded_env("MEMORY_WIKI_EPISODIC_MAX_ROWS", 5000, 1, 20000)
        max_bytes = _bounded_env("MEMORY_WIKI_EPISODIC_MAX_BYTES", 8_000_000, 4800, 32_000_000)
        owner_where = "owner_bot_id=? AND visibility_scope=?"
        owner_params: tuple[Any, ...] = (bot, scope)
        if scope == "chat":
            owner_where += " AND owner_chat_hash=?"
            owner_params += (chat,)
        # One windowed prune avoids O(old row count) round trips when a host
        # sharply lowers an existing quota. Newest rows win deterministically.
        overflow_ids = [str(row[0]) for row in conn.execute(f"""SELECT id FROM (
                SELECT id,
                  ROW_NUMBER() OVER (ORDER BY created_at DESC,rowid DESC) AS n,
                  SUM(LENGTH(CAST(content AS BLOB))) OVER (ORDER BY created_at DESC,rowid DESC) AS bytes
                FROM episodic_turns WHERE {owner_where}
            ) WHERE n>? OR bytes>?""", (*owner_params, max_rows, max_bytes)).fetchall()]
        conn.execute(f"""DELETE FROM episodic_turns WHERE id IN (
            SELECT id FROM (
                SELECT id,
                  ROW_NUMBER() OVER (ORDER BY created_at DESC,rowid DESC) AS n,
                  SUM(LENGTH(CAST(content AS BLOB))) OVER (ORDER BY created_at DESC,rowid DESC) AS bytes
                FROM episodic_turns WHERE {owner_where}
            ) WHERE n>? OR bytes>?
        )""", (*owner_params, max_rows, max_bytes))
        if semantic:
            manifest_hash = module._manifest_hash(module._embedding_manifest())
            target_hash = module._episodic_vector_target_hash()
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('episodic_semantic_ever_enabled','1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
            module._outbox_enqueue("embed_and_upsert", "episode", row_id, {
                "text": content,
                "collection": module._episodic_collection_name(),
                "endpoint": module._normalized_qdrant_endpoint(),
                "manifest_hash": manifest_hash,
                "vector_target_hash": target_hash,
                "role": role,
                "turn_id": group_id,
                "owner_bot_id": bot,
                "owner_chat_hash": chat,
                "visibility_scope": scope,
                "created_at": stamp,
                "expires_at": stamp + ttl,
            }, conn=conn)
            queued = True
        if semantic or _semantic_was_enabled(conn):
            for deleted_id in dict.fromkeys(expired_ids + overflow_ids):
                queued = _enqueue_episode_delete(module, conn, deleted_id) or queued
    if queued:
        _wake_semantic_worker(provider, module)
    return row_id


def delete_episodes(provider: Any, scope: str = "chat", module: Any | None = None) -> int:
    """Host-only privacy operation; broad deletion requires trusted bot identity."""
    module = _provider_module(provider, module)
    bot, chat = _identity(provider)
    if not bot or not chat:
        return 0
    if scope not in {"all", "chat", "bot"}:
        raise ValueError("invalid episode deletion scope")
    if scope != "chat" and not bool(getattr(provider, "_bot_scope_trusted", False)):
        raise PermissionError("trusted bot identity required for broad episode deletion")
    clause = "" if scope == "all" else "AND visibility_scope=?"
    params: tuple[Any, ...] = (bot,) if scope == "all" else (bot, scope)
    if scope == "chat":
        clause += " AND owner_chat_hash=?"
        params += (chat,)
    queued = False
    with provider._connect() as conn:
        removed_ids = [str(row[0]) for row in conn.execute(
            f"SELECT id FROM episodic_turns WHERE owner_bot_id=? {clause}", params,
        ).fetchall()]
        cur = conn.execute(
            f"DELETE FROM episodic_turns WHERE owner_bot_id=? {clause}", params,
        )
        if _semantic_enabled(module) or _semantic_was_enabled(conn):
            for row_id in removed_ids:
                queued = _enqueue_episode_delete(module, conn, row_id) or queued
    if queued:
        _wake_semantic_worker(provider, module)
    return int(cur.rowcount)


def _removal_surface(value: Any) -> str:
    """Losslessly normalize case, Unicode width, and whitespace for erasure."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = " ".join(normalized.split())
    normalized = normalized.strip(" \t\r\n\"'“”‘’.,;:!?؛،")
    return normalized


def _contains_removal_phrase(content: str, target: str) -> bool:
    if not target:
        return False
    normalized_content = _removal_surface(content)
    if normalized_content == target:
        return True
    # A word boundary prevents a short removal from matching an unrelated
    # longer token ("cat" must not remove "catalogue"). Punctuation inside
    # the target remains significant, so "C++" does not become the word "c".
    return bool(re.search(r"(?<!\w)" + re.escape(target) + r"(?!\w)", normalized_content))


def erase_matching_episodes(
    provider: Any,
    module: Any,
    exact_contents: Any,
    *,
    conn: sqlite3.Connection | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Erase owned raw episodes containing a removed memory's exact phrase.

    The caller may share its claim-removal transaction. Only the exact current
    chat and, if Hermes supplied a distinct trusted bot identity, that bot's
    explicitly shared rows are considered. No raw episode content is returned.
    """
    values = [exact_contents] if isinstance(exact_contents, str) else (exact_contents or ())
    targets = sorted({
        surface for surface in (_removal_surface(value) for value in values)
        if surface
    })
    if not targets:
        return {"deleted": 0, "episode_ids": [], "vector_deletes_queued": False}
    bot, chat = _identity(provider, session_id)
    if not bot or not chat:
        return {"deleted": 0, "episode_ids": [], "vector_deletes_queued": False}
    trusted_bot = bool(getattr(provider, "_bot_scope_trusted", False))
    owner_predicate = "(owner_bot_id=? AND visibility_scope='chat' AND owner_chat_hash=?)"
    owner_args: list[Any] = [bot, chat]
    if trusted_bot:
        owner_predicate += " OR (owner_bot_id=? AND visibility_scope='bot')"
        owner_args.append(bot)
    database = conn or provider._connect()

    def erase() -> dict[str, Any]:
        rows = database.execute(
            "SELECT id,content,visibility_scope FROM episodic_turns WHERE "
            + owner_predicate + " ORDER BY id",
            tuple(owner_args),
        ).fetchall()
        selected = [
            (str(row[0]), str(row[2])) for row in rows
            if any(_contains_removal_phrase(str(row[1]), target) for target in targets)
        ]
        if not selected:
            return {"deleted": 0, "episode_ids": [], "vector_deletes_queued": False}
        queued = False
        for offset in range(0, len(selected), 400):
            chunk = selected[offset:offset + 400]
            ids = [row_id for row_id, _scope in chunk]
            placeholders = ",".join("?" for _ in ids)
            database.execute(
                "DELETE FROM episodic_turns WHERE id IN (" + placeholders + ")",
                tuple(ids),
            )
            if module is not None:
                active_or_prior = _semantic_enabled(module) or _semantic_was_enabled(database)
                for row_id in ids:
                    if active_or_prior or _episode_has_vector_history(database, row_id):
                        queued = _enqueue_episode_delete(module, database, row_id) or queued
        # Invalidate only affected visibility partitions after source erasure.
        scopes = {scope for _row_id, scope in selected}
        database.execute(
            "UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) "
            "WHERE key='cache_state_revision'"
        )
        if "chat" in scopes:
            provider._bump_cache_component_revision(
                database,
                provider._cache_component_partition(
                    "chat", origin_bot_id=bot, origin_chat_hash=chat,
                ),
            )
        if "bot" in scopes:
            provider._bump_cache_component_revision(
                database,
                provider._cache_component_partition(
                    "bot", origin_bot_id=bot,
                ),
            )
        return {
            "deleted": len(selected),
            "episode_ids": [row_id for row_id, _scope in selected],
            "vector_deletes_queued": queued,
        }

    if conn is None:
        with database:
            if not database.in_transaction:
                database.execute("BEGIN IMMEDIATE")
            result = erase()
        if result["vector_deletes_queued"]:
            _wake_semantic_worker(provider, module)
        return result
    return erase()


def query_episodes(provider: Any, module: Any, query: str, limit: int = 2,
                   *, include_diagnostics: bool = False, session_id: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    stats: dict[str, Any] = {
        "candidates": 0, "lexical_candidates": 0, "semantic_candidates": 0,
        "paired_candidates": 0, "paired_returned": 0,
        "secret_rejected": 0, "guard_rejected": 0,
        "budget_rejected": 0, "query_variants": 0,
        "semantic_used": False, "semantic_error": "", "search_ms": 0.0,
    }

    def result(*, is_enabled: bool, scope: str = "",
               episodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"enabled": is_enabled, "episodes": episodes or []}
        if scope:
            payload["scope"] = scope
        if include_diagnostics:
            stats["search_ms"] = round((time.perf_counter() - started) * 1000, 2)
            payload["diagnostics"] = stats
        return payload

    if not enabled():
        return result(is_enabled=False)
    bot, chat = _identity(provider, session_id)
    scope = _scope()
    if not bot or not chat or (scope == "bot" and not bool(
            getattr(provider, "_bot_scope_trusted", False))):
        return result(is_enabled=True, scope=scope)
    result_cap = _bounded_env("MEMORY_WIKI_EPISODIC_QUERY_MAX_RESULTS", 8, 1, 20)
    limit = max(1, min(int(limit), result_cap))
    conn = provider._connect()
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    budget = _bounded_env("MEMORY_WIKI_EPISODIC_QUERY_MAX_CHARS", 2400, 350, 12000)
    recall_cap = _bounded_env(
        "MEMORY_WIKI_EPISODIC_RECALL_MAX_CHARS", 350, 128, _CAPTURE_MAX_CHARS,
    )
    owner_clause = "AND e.owner_chat_hash=?" if scope == "chat" else ""
    owner_params: tuple[Any, ...] = (bot, scope, chat) if scope == "chat" else (bot, scope)
    stamp = int(time.time())

    # Expired SQLite rows can leave stale vectors after a quiet period. Remove
    # them transactionally and enqueue the matching point deletes. A stale
    # vector can still never pass the authoritative hydration query below.
    queued_delete = False
    with conn:
        expired_ids = [str(row[0]) for row in conn.execute(
            "SELECT id FROM episodic_turns WHERE owner_bot_id=? AND expires_at<=?",
            (bot, stamp),
        ).fetchall()]
        if expired_ids:
            conn.executemany("DELETE FROM episodic_turns WHERE id=?", ((value,) for value in expired_ids))
            if _semantic_enabled(module) or _semantic_was_enabled(conn):
                for row_id in expired_ids:
                    queued_delete = _enqueue_episode_delete(module, conn, row_id) or queued_delete
    if queued_delete:
        _wake_semantic_worker(provider, module)

    def append_checked(row: sqlite3.Row, *, paired: bool = False) -> bool:
        """Append one row after applying the complete episode read boundary."""
        nonlocal budget
        row_id = str(row["id"])
        if row_id in seen:
            return False
        seen.add(row_id)
        stats["candidates"] += 1
        if paired:
            stats["paired_candidates"] += 1
        stored_content = str(row["content"] or "")
        if module.secret_scan(stored_content).get("raw_secret"):
            stats["secret_rejected"] += 1
            return False
        recall_excerpt, recall_truncated, _stored_chars = _balanced_excerpt(
            stored_content, recall_cap,
        )
        checked = provider._inspect_recall_text(
            recall_excerpt, source="episodic:untrusted", mem_type="episode",
            item_id=row_id, audit=False, max_len=recall_cap,
        )
        if checked.get("status") != "safe":
            stats["guard_rejected"] += 1
            return False
        content = str(checked.get("content") or "").strip()
        guard_truncated = False
        if len(content) > recall_cap:
            content, guard_truncated, _ = _balanced_excerpt(content, recall_cap)
        if not content or len(content) > budget:
            stats["budget_rejected"] += 1
            return False
        row_keys = set(row.keys())
        original_chars = int(row["source_chars"] or 0) if "source_chars" in row_keys else 0
        original_chars = max(original_chars, len(stored_content))
        capture_truncated = bool(row["truncated"]) if "truncated" in row_keys else False
        output.append({
            "id": row_id, "role": row["role"], "content": content,
            "content_hash": hashlib.sha256(
                stored_content.encode("utf-8", "ignore")
            ).hexdigest(),
            "created_at": row["created_at"], "trust_level": "untrusted",
            "source": "host_attested_sync_turn",
            "truncated": bool(capture_truncated or recall_truncated or guard_truncated),
            "source_chars": original_chars,
        })
        budget -= len(content)
        if paired:
            stats["paired_returned"] += 1
        return True

    # Collect lexical ranks first rather than rendering immediately. This lets
    # semantic and lexical evidence participate in one deterministic RRF list.
    lexical_rank: dict[str, int] = {}
    planner_mode = os.environ.get("MEMORY_WIKI_EPISODIC_QUERY_MODE", "auto").strip().lower()
    if planner_mode not in {"fast", "auto", "deep"}:
        planner_mode = "auto"
    variants = expand_memory_queries(str(query or "")[:500], mode=planner_mode)
    stats["query_variants"] = len(variants)
    for variant in variants:
        for mode in ("and", "or"):
            expression = module.safe_fts_query(variant[:300], mode=mode)
            if not expression:
                continue
            try:
                rows = conn.execute(f"""SELECT e.id,
                    bm25(episodic_turns_fts) AS rank
                    FROM episodic_turns_fts JOIN episodic_turns e ON e.id=episodic_turns_fts.id
                    WHERE episodic_turns_fts MATCH ? AND e.owner_bot_id=?
                      AND e.visibility_scope=? {owner_clause} AND e.expires_at>?
                    ORDER BY rank,e.created_at DESC,e.id LIMIT 40""",
                    (expression, *owner_params, stamp),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            for row in rows:
                row_id = str(row["id"])
                if row_id not in lexical_rank:
                    lexical_rank[row_id] = len(lexical_rank) + 1
    stats["lexical_candidates"] = len(lexical_rank)

    semantic_rank: dict[str, int] = {}
    raw_query = str(query or "").strip()[:500]
    if raw_query and _semantic_enabled(module):
        try:
            if module._episodic_semantic_available():
                vector = module._embed_query(raw_query)
                if vector:
                    query_filter = module._qdrant_episode_filter(
                        bot_id=bot, chat_hash=chat, visibility_scope=scope,
                        expires_after=stamp,
                    )
                    matches = module._qdrant_episode_search(
                        vector, max(40, min(100, limit * 12)),
                        query_filter=query_filter,
                    )
                    for episode_id, _score in matches:
                        value = str(episode_id)
                        if value not in semantic_rank:
                            semantic_rank[value] = len(semantic_rank) + 1
                    stats["semantic_used"] = True
            else:
                stats["semantic_error"] = "unavailable"
        except Exception as exc:
            # Optional network retrieval never suppresses the local FTS path.
            stats["semantic_error"] = type(exc).__name__[:80]
    stats["semantic_candidates"] = len(semantic_rank)

    candidate_ids = list(dict.fromkeys([*lexical_rank, *semantic_rank]))
    hydrated: dict[str, sqlite3.Row] = {}
    for offset in range(0, len(candidate_ids), 200):
        chunk = candidate_ids[offset:offset + 200]
        placeholders = ",".join("?" for _ in chunk)
        if not placeholders:
            continue
        rows = conn.execute(f"""SELECT e.id,e.content,e.role,e.turn_id,
                e.owner_chat_hash,e.created_at,e.truncated,e.source_chars
            FROM episodic_turns e
            WHERE e.id IN ({placeholders}) AND e.owner_bot_id=?
              AND e.visibility_scope=? {owner_clause} AND e.expires_at>?""",
            (*chunk, *owner_params, stamp),
        ).fetchall()
        for row in rows:
            hydrated[str(row["id"])] = row

    # Rank-only fusion is stable across BM25/cosine score scales. A row present
    # in both lists gets both contributions; ties prefer recent evidence and a
    # final stable ID order.
    fused: dict[str, float] = {}
    for row_id, rank in lexical_rank.items():
        if row_id in hydrated:
            fused[row_id] = fused.get(row_id, 0.0) + 1.0 / (60 + rank)
    for row_id, rank in semantic_rank.items():
        if row_id in hydrated:
            fused[row_id] = fused.get(row_id, 0.0) + 1.0 / (60 + rank)
    ordered = sorted(
        hydrated.values(),
        key=lambda row: (
            -fused.get(str(row["id"]), 0.0),
            -int(row["created_at"] or 0),
            str(row["id"]),
        ),
    )

    for row in ordered:
        if str(row["id"]) in seen:
            continue
        group_id = str(row["turn_id"] or "")
        if group_id:
            # Pair expansion never broadens authorization. Even bot-scoped
            # retrieval fetches the counterpart from the exact source chat.
            group_rows = conn.execute("""SELECT id,content,role,turn_id,
                owner_chat_hash,created_at,truncated,source_chars
                FROM episodic_turns
                WHERE turn_id=? AND owner_bot_id=?
                  AND visibility_scope=? AND owner_chat_hash=? AND expires_at>?
                ORDER BY CASE role WHEN 'user' THEN 0 ELSE 1 END,created_at,id LIMIT 4""",
                (group_id, bot, scope, row["owner_chat_hash"], stamp),
            ).fetchall()
            # Render a complete exchange in conversational order even when
            # only the assistant message matched. If the caller left too
            # little capacity, preserve the actual hit rather than returning
            # only its nonmatching counterpart.
            if len(group_rows) > 1 and len(output) + len(group_rows) <= limit:
                matched_id = str(row["id"])
                for group_row in group_rows:
                    append_checked(group_row, paired=str(group_row["id"]) != matched_id)
                    if len(output) >= limit:
                        return result(is_enabled=True, scope=scope, episodes=output)
                continue
        if append_checked(row) and len(output) >= limit:
            return result(is_enabled=True, scope=scope, episodes=output)
    return result(is_enabled=True, scope=scope, episodes=output)
