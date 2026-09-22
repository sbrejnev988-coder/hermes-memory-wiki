"""Simultaneous observation expiry stays under SQLite parameter limits."""

from __future__ import annotations

import hashlib
import sqlite3
import time

import memory_events
import memory_observations


class _Provider:
    def __init__(self, conn):
        self.conn = conn

    def _connect(self):
        return self.conn

    def _scoped_backup_owner(self):
        return {"bot_id": "bulk-bot", "chat_hash": "a" * 32, "session_id": "chat"}

    def _meta_text(self, _name, _default):
        return "bulk-expiry-test"


def test_more_than_one_thousand_expired_observations_are_removed_in_chunks():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        memory_events.install_schema(conn)
        memory_observations.install_schema(conn)
        stamp = int(time.time())
        session_hash = hashlib.sha256(
            b"memory-event-session-v1\0bulk-expiry-test\0bulk-bot\0chat"
        ).hexdigest()[:32]
        with conn:
            conn.executemany(
                """INSERT INTO memory_observations(
                    observation_id,owner_bot_id,owner_chat_hash,owner_session_hash,
                    visibility_scope,project_id,topic,cluster_normalized,cluster_key,
                    content,normalized_content,content_hash,representative_event_id,
                    created_at,updated_at,expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ((
                    f"obs_{i}", "bulk-bot", "a" * 32, session_hash, "chat", "",
                    "test", f"synthetic_{i}", f"cluster_{i}",
                    "Synthetic expired observation.", "synthetic expired observation",
                    hashlib.sha256(b"Synthetic expired observation.").hexdigest(),
                    f"evt_{i}", stamp - 100, stamp - 100, stamp - 1,
                ) for i in range(1201))
            )
        assert memory_observations.prune_observations(_Provider(conn)) == 1201
        assert conn.execute("SELECT COUNT(*) FROM memory_observations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM memory_observations_fts").fetchone()[0] == 0
    finally:
        conn.close()
