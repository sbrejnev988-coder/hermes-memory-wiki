"""Ledger retention remains exact under inserts, deletes, and schema upgrades."""

from __future__ import annotations

import hashlib
import sqlite3
import time

import memory_events


class _Provider:
    def __init__(self, conn: sqlite3.Connection, bot: str,
                 chat_hash: str = "a" * 32, session_id: str = "test"):
        self.conn = conn
        self.bot = bot
        self.chat_hash = chat_hash
        self.session_id = session_id

    def _connect(self) -> sqlite3.Connection:
        return self.conn

    def _scoped_backup_owner(self) -> dict[str, str]:
        return {"bot_id": self.bot, "chat_hash": self.chat_hash,
                "session_id": self.session_id}

    def _meta_text(self, _name: str, _default: str) -> str:
        return "synthetic-database"


def _insert(conn: sqlite3.Connection, bot: str, index: int, content: str,
            *, expired: bool = False, chat_hash: str = "a" * 32,
            session_id: str = "test") -> None:
    now = int(time.time())
    session_hash = hashlib.sha256(
        f"memory-event-session-v1\0synthetic-database\0{bot}\0{session_id}".encode()
    ).hexdigest()[:32]
    conn.execute(
        """INSERT INTO memory_events(
          event_id,owner_bot_id,owner_chat_hash,owner_session_hash,
          visibility_scope,project_id,turn_id,role,event_type,modality,
          content,content_hash,occurred_at,observed_at,provenance_json,
          created_at,expires_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"evt_{bot}_{index}", bot, chat_hash, session_hash, "chat", "", "",
         "user", "dialogue_turn", "text", content,
         hashlib.sha256(content.encode()).hexdigest(), now, now, "{}",
         now - 86400 if expired else now + index,
         now - 1 if expired else now + 86400),
    )


def _usage(conn: sqlite3.Connection, bot: str) -> tuple[int, int]:
    return tuple(conn.execute(
        "SELECT row_count,byte_count FROM memory_event_owner_usage "
        "WHERE owner_bot_id=?", (bot,),
    ).fetchone())


def test_incremental_retention_enforces_row_and_byte_caps_without_cross_owner_deletion(
    monkeypatch,
):
    conn = sqlite3.connect(":memory:")
    memory_events.install_schema(conn)
    try:
        for i in range(8):
            _insert(conn, "alice", i, f"unique memory {i}" + "x" * 2500)
        for i in range(3):
            _insert(conn, "bob", i, f"other memory {i}")
        assert _usage(conn, "alice")[0] == 8
        assert _usage(conn, "bob")[0] == 3

        monkeypatch.setenv("MEMORY_WIKI_EVENT_MAX_ROWS", "6")
        monkeypatch.setenv("MEMORY_WIKI_EVENT_MAX_BYTES", "16384")
        removed = memory_events.prune_events(_Provider(conn, "alice"))
        assert removed == 2
        assert _usage(conn, "alice")[0] == 6
        assert _usage(conn, "alice")[1] <= 16384
        assert _usage(conn, "bob")[0] == 3
        retained = {row[0] for row in conn.execute(
            "SELECT event_id FROM memory_events WHERE owner_bot_id='alice'"
        )}
        assert retained == {f"evt_alice_{i}" for i in range(2, 8)}

        # Retention is idempotent; an ordinary privacy deletion updates the
        # aggregate in the same transaction and leaves FTS in sync.
        assert memory_events.prune_events(_Provider(conn, "alice")) == 0
        _insert(conn, "alice", 8, "new large memory " + "y" * 7000)
        assert memory_events.prune_events(_Provider(conn, "alice")) >= 1
        assert _usage(conn, "alice")[1] <= 16384
        assert _usage(conn, "bob")[0] == 3
        conn.execute("DELETE FROM memory_events WHERE event_id='evt_alice_8'")
        assert _usage(conn, "alice")[0] == conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE owner_bot_id='alice'"
        ).fetchone()[0]
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events_fts WHERE event_id='evt_alice_8'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_usage_is_backfilled_once_and_expired_rows_are_accounted():
    conn = sqlite3.connect(":memory:")
    try:
        memory_events.install_schema(conn)
        _insert(conn, "alice", 0, "old record", expired=True)
        _insert(conn, "alice", 1, "new record")
        expected = _usage(conn, "alice")
        conn.execute("DROP TRIGGER memory_events_usage_ai")
        conn.execute("DROP TRIGGER memory_events_usage_ad")
        conn.execute("DROP TABLE memory_event_owner_usage")
        memory_events.install_schema(conn)
        assert _usage(conn, "alice") == expected
        memory_events.install_schema(conn)
        assert _usage(conn, "alice") == expected
        assert memory_events.prune_events(_Provider(conn, "alice")) == 1
        assert _usage(conn, "alice")[0] == 1
    finally:
        conn.close()


def test_shared_fallback_bot_retention_is_fair_per_chat(monkeypatch):
    conn = sqlite3.connect(":memory:")
    memory_events.install_schema(conn)
    try:
        for index in range(3):
            _insert(conn, "default", index, f"private chat A {index}")
            _insert(conn, "default", index + 10, f"private chat B {index}",
                    chat_hash="c" * 32, session_id="other")
        monkeypatch.setenv("MEMORY_WIKI_EVENT_MAX_ROWS", "2")
        memory_events.prune_events(_Provider(conn, "default"))
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE owner_chat_hash=?",
            ("c" * 32,),
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE owner_chat_hash=?",
            ("a" * 32,),
        ).fetchone()[0] == 2
        memory_events.prune_events(_Provider(conn, "default", "c" * 32, "other"))
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE owner_chat_hash=?",
            ("a" * 32,),
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events WHERE owner_chat_hash=?",
            ("c" * 32,),
        ).fetchone()[0] == 2
        assert _usage(conn, "default")[0] == 4
    finally:
        conn.close()


def test_legacy_fts_is_rebuilt_with_stable_docids_and_survives_vacuum(tmp_path):
    db = tmp_path / "events.sqlite3"
    conn = sqlite3.connect(db)
    try:
        memory_events.install_schema(conn)
        for i in range(8):
            _insert(conn, "alice", i, f"Rare legacy beacon marker{i}.")
        conn.commit()
        conn.execute("DROP TRIGGER memory_events_fts_ai")
        conn.execute("DROP TRIGGER memory_events_fts_ad")
        conn.execute("DROP TABLE memory_events_fts")
        conn.execute("DROP TABLE memory_event_fts_docids")
        conn.execute(
            """CREATE VIRTUAL TABLE memory_events_fts USING fts5(
                event_id UNINDEXED,content,event_type,modality,tokenize='unicode61')"""
        )
        conn.execute(
            "INSERT INTO memory_events_fts(event_id,content,event_type,modality) "
            "SELECT event_id,content,event_type,modality FROM memory_events"
        )
        conn.commit()

        memory_events.install_schema(conn)
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events_fts"
        ).fetchone()[0] == 8
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_event_fts_docids"
        ).fetchone()[0] == 8
        conn.commit()
        before = conn.execute(
            "SELECT docid,event_id FROM memory_event_fts_docids ORDER BY docid"
        ).fetchall()
        conn.execute("VACUUM")
        assert conn.execute(
            "SELECT docid,event_id FROM memory_event_fts_docids ORDER BY docid"
        ).fetchall() == before
        conn.execute("DELETE FROM memory_events WHERE event_id='evt_alice_5'")
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events_fts WHERE event_id='evt_alice_5'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_event_fts_docids"
        ).fetchone()[0] == 7
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_events_fts WHERE memory_events_fts MATCH 'marker7'"
        ).fetchone()[0] == 1
        highest = max(docid for docid, _event_id in before)
        conn.execute("DELETE FROM memory_events WHERE event_id='evt_alice_7'")
        _insert(conn, "alice", 8, "New beacon marker8.")
        fresh = conn.execute(
            "SELECT docid FROM memory_event_fts_docids WHERE event_id='evt_alice_8'"
        ).fetchone()[0]
        assert fresh > highest
    finally:
        conn.close()


def test_non_autoincrement_docid_mapping_migrates_without_duplicate_ids():
    conn = sqlite3.connect(":memory:")
    try:
        memory_events.install_schema(conn)
        _insert(conn, "alice", 1, "Legacy mapping before migration.")
        original = conn.execute(
            "SELECT docid,event_id FROM memory_event_fts_docids"
        ).fetchone()
        conn.execute("DROP TRIGGER memory_events_fts_ai")
        conn.execute("DROP TRIGGER memory_events_fts_ad")
        conn.execute("DROP TABLE memory_event_fts_docids")
        conn.execute(
            "CREATE TABLE memory_event_fts_docids("
            "docid INTEGER PRIMARY KEY,event_id TEXT NOT NULL UNIQUE)"
        )
        conn.execute(
            "INSERT INTO memory_event_fts_docids(docid,event_id) VALUES(?,?)",
            original,
        )
        memory_events.install_schema(conn)
        assert conn.execute(
            "SELECT docid,event_id FROM memory_event_fts_docids"
        ).fetchone() == original
        assert "AUTOINCREMENT" in conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='memory_event_fts_docids'"
        ).fetchone()[0]
        _insert(conn, "alice", 2, "Fresh mapping after migration.")
        assert conn.execute("SELECT COUNT(*) FROM memory_events_fts").fetchone()[0] == 2
    finally:
        conn.close()
