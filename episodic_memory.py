"""Opt-in, host-attested dialogue evidence. Episodes never become trusted claims.

Only MemoryWikiProvider.sync_turn calls capture_turn. Model-facing access is a
bounded read through query_episodes; the caller cannot select an owner or scope.
"""

from __future__ import annotations

import os
import hashlib
import sqlite3
import time
import uuid
from typing import Any


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


def install_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS episodic_turns(
        id TEXT PRIMARY KEY, content TEXT NOT NULL, role TEXT NOT NULL
            CHECK(role IN ('user','assistant')),
        owner_bot_id TEXT NOT NULL, owner_chat_hash TEXT NOT NULL,
        visibility_scope TEXT NOT NULL CHECK(visibility_scope IN ('chat','bot')),
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_owner_expiry ON episodic_turns(owner_bot_id,visibility_scope,owner_chat_hash,expires_at,created_at)")
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodic_turns_fts'").fetchone()
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS episodic_turns_fts USING fts5(id UNINDEXED,content,tokenize='unicode61')")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS episodic_turns_ai AFTER INSERT ON episodic_turns BEGIN
        INSERT INTO episodic_turns_fts(id,content) VALUES(new.id,new.content); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS episodic_turns_ad AFTER DELETE ON episodic_turns BEGIN
        DELETE FROM episodic_turns_fts WHERE id=old.id; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS episodic_turns_au AFTER UPDATE OF content ON episodic_turns BEGIN
        DELETE FROM episodic_turns_fts WHERE id=old.id;
        INSERT INTO episodic_turns_fts(id,content) VALUES(new.id,new.content); END""")
    if not exists:
        conn.execute("INSERT INTO episodic_turns_fts(id,content) SELECT id,content FROM episodic_turns")


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild only the derived index after a checkpoint or FTS corruption."""
    with conn:
        conn.execute("DELETE FROM episodic_turns_fts")
        conn.execute("INSERT INTO episodic_turns_fts(id,content) SELECT id,content FROM episodic_turns")


def _identity(provider: Any, session_id: str = "") -> tuple[str, str]:
    owner = provider._scoped_backup_owner()  # Fresh DB identity after restore.
    if session_id and session_id != owner["session_id"]:
        database_id = provider._meta_text("database_instance_id", "uninitialized")
        chat_hash = hashlib.sha256(f"{database_id}\0{session_id}".encode("utf-8", "ignore")).hexdigest()[:32]
    else:
        chat_hash = str(owner["chat_hash"])
    return str(owner["bot_id"]), chat_hash


def capture_turn(provider: Any, module: Any, role: str, text: str, *, session_id: str = "") -> str | None:
    """Capture a bounded excerpt from trusted provider lifecycle input only."""
    if not enabled() or role not in {"user", "assistant"}:
        return None
    # Reject the entire turn on a detected secret rather than persisting a
    # redaction marker next to potentially revealing surrounding text.
    raw = module.scrub_memory_artifacts(str(text or ""))
    if not raw.strip() or module.secret_scan(raw).get("raw_secret"):
        return None
    redacted = module.redact_secrets(raw).strip()
    checked = provider._inspect_recall_text(
        redacted, source="host:sync_turn", mem_type="episode", audit=False, max_len=1200,
    )
    if checked.get("status") != "safe":
        return None
    content = str(checked.get("content") or "").strip()[:1200]
    if not content or module.secret_scan(content).get("raw_secret"):
        return None
    bot, chat = _identity(provider, session_id)
    if not bot or not chat:
        return None
    scope = _scope()
    if scope == "bot" and bot == "default":
        # The fallback identity can represent several agents in one home.
        # Explicit bot-wide sharing requires a distinct host bot identity.
        return None
    stamp = int(time.time())
    ttl = _bounded_env("MEMORY_WIKI_EPISODIC_TTL_DAYS", 30, 1, 365) * 86400
    row_id = "ep_" + uuid.uuid4().hex
    conn = provider._connect()
    with conn:
        conn.execute("""INSERT INTO episodic_turns
            (id,content,role,owner_bot_id,owner_chat_hash,visibility_scope,created_at,expires_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (row_id, content, role, bot, chat, scope, stamp, stamp + ttl))
        # Prune only this bot. An unrelated bot cannot influence another
        # principal's retention or infer its row count through quota effects.
        conn.execute("DELETE FROM episodic_turns WHERE owner_bot_id=? AND expires_at<=?", (bot, stamp))
        max_rows = _bounded_env("MEMORY_WIKI_EPISODIC_MAX_ROWS", 5000, 1, 20000)
        max_bytes = _bounded_env("MEMORY_WIKI_EPISODIC_MAX_BYTES", 8_000_000, 4800, 32_000_000)
        # One windowed prune avoids O(old row count) round trips when a host
        # sharply lowers an existing quota. Newest rows win deterministically.
        conn.execute("""DELETE FROM episodic_turns WHERE id IN (
            SELECT id FROM (
                SELECT id,
                  ROW_NUMBER() OVER (ORDER BY created_at DESC,rowid DESC) AS n,
                  SUM(LENGTH(CAST(content AS BLOB))) OVER (ORDER BY created_at DESC,rowid DESC) AS bytes
                FROM episodic_turns WHERE owner_bot_id=?
            ) WHERE n>? OR bytes>?
        )""", (bot, max_rows, max_bytes))
    return row_id


def delete_episodes(provider: Any, scope: str = "all") -> int:
    """Host-only privacy operation; ``all`` erases every episode for this bot."""
    bot, chat = _identity(provider)
    if not bot or not chat:
        return 0
    if scope not in {"all", "chat", "bot"}:
        raise ValueError("invalid episode deletion scope")
    clause = "" if scope == "all" else "AND visibility_scope=?"
    params: tuple[Any, ...] = (bot,) if scope == "all" else (bot, scope)
    if scope == "chat":
        clause += " AND owner_chat_hash=?"
        params += (chat,)
    with provider._connect() as conn:
        cur = conn.execute(
            f"DELETE FROM episodic_turns WHERE owner_bot_id=? {clause}", params,
        )
    return int(cur.rowcount)


def query_episodes(provider: Any, module: Any, query: str, limit: int = 2,
                   *, include_diagnostics: bool = False, session_id: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    stats = {"candidates": 0, "secret_rejected": 0, "guard_rejected": 0,
             "budget_rejected": 0, "search_ms": 0.0}

    def result(*, is_enabled: bool, scope: str = "", episodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
    if not bot or not chat or (scope == "bot" and bot == "default"):
        return result(is_enabled=True, scope=scope)
    limit = max(1, min(int(limit), 5))
    conn = provider._connect()
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    budget = 800
    owner_clause = "AND e.owner_chat_hash=?" if scope == "chat" else ""
    owner_params: tuple[Any, ...] = (bot, scope, chat) if scope == "chat" else (bot, scope)
    stamp = int(time.time())
    for mode in ("and", "or"):
        expression = module.safe_fts_query(str(query or "")[:300], mode=mode)
        if not expression:
            continue
        try:
            rows = conn.execute(f"""SELECT e.id,e.content,e.role,e.created_at,
                bm25(episodic_turns_fts) AS rank
                FROM episodic_turns_fts JOIN episodic_turns e ON e.id=episodic_turns_fts.id
                WHERE episodic_turns_fts MATCH ? AND e.owner_bot_id=?
                  AND e.visibility_scope=? {owner_clause} AND e.expires_at>?
                ORDER BY rank,e.created_at DESC LIMIT 40""",
                (expression, *owner_params, stamp),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for row in rows:
            row_id = str(row["id"])
            if row_id in seen:
                continue
            seen.add(row_id)
            stats["candidates"] += 1
            if module.secret_scan(row["content"]).get("raw_secret"):
                stats["secret_rejected"] += 1
                continue
            checked = provider._inspect_recall_text(
                row["content"], source="episodic:untrusted", mem_type="episode",
                item_id=row_id, audit=False, max_len=350,
            )
            if checked.get("status") != "safe":
                stats["guard_rejected"] += 1
                continue
            content = str(checked.get("content") or "").strip()[:350]
            if not content or len(content) > budget:
                stats["budget_rejected"] += 1
                continue
            output.append({"id": row_id, "role": row["role"], "content": content,
                           "created_at": row["created_at"], "trust_level": "untrusted",
                           "source": "host_attested_sync_turn"})
            budget -= len(content)
            if len(output) >= limit:
                return result(is_enabled=True, scope=scope, episodes=output)
    return result(is_enabled=True, scope=scope, episodes=output)
