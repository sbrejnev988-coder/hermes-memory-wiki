"""Episode FTS deletes use durable numeric docids across migration and VACUUM."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _memory():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "episodic_memory_docid_test", ROOT / "episodic_memory.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _insert(conn, episode_id, text):
    conn.execute(
        """INSERT INTO episodic_turns(
            id,content,role,owner_bot_id,owner_chat_hash,visibility_scope,
            created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)""",
        (episode_id, text, "user", "bot-1", "chat-1", "chat", 1, 9999999999),
    )


def test_legacy_fts_migrates_and_update_delete_use_stable_docids(tmp_path):
    memory = _memory()
    conn = sqlite3.connect(tmp_path / "episodes.sqlite3")
    try:
        memory.install_schema(conn)
        for trigger in (
            "episodic_turns_ai", "episodic_turns_ad", "episodic_turns_au",
        ):
            conn.execute(f"DROP TRIGGER {trigger}")
        conn.execute("DROP TABLE episodic_turns_fts")
        conn.execute("DROP TABLE episodic_fts_docids")
        conn.execute(
            "CREATE VIRTUAL TABLE episodic_turns_fts "
            "USING fts5(id UNINDEXED,content,tokenize='unicode61')"
        )
        conn.execute("""CREATE TRIGGER episodic_turns_ai
            AFTER INSERT ON episodic_turns BEGIN
              INSERT INTO episodic_turns_fts(id,content)
              VALUES(NEW.id,NEW.content); END""")
        conn.execute("""CREATE TRIGGER episodic_turns_ad
            AFTER DELETE ON episodic_turns BEGIN
              DELETE FROM episodic_turns_fts WHERE id=OLD.id; END""")
        _insert(conn, "ep_first", "Orion relay is green")
        _insert(conn, "ep_second", "Vega relay is blue")
        conn.commit()

        memory.install_schema(conn)
        mapped = conn.execute(
            """SELECT e.id,d.docid,f.id,f.content
               FROM episodic_turns e
               JOIN episodic_fts_docids d ON d.episode_id=e.id
               JOIN episodic_turns_fts f ON f.rowid=d.docid
               ORDER BY e.id"""
        ).fetchall()
        assert mapped == [
            ("ep_first", mapped[0][1], "ep_first", "Orion relay is green"),
            ("ep_second", mapped[1][1], "ep_second", "Vega relay is blue"),
        ]
        before = conn.execute(
            "SELECT docid FROM episodic_fts_docids WHERE episode_id='ep_first'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE episodic_turns SET content='Orion relay is amber' "
            "WHERE id='ep_first'"
        )
        assert conn.execute(
            "SELECT docid FROM episodic_fts_docids WHERE episode_id='ep_first'"
        ).fetchone()[0] == before
        assert conn.execute(
            "SELECT id FROM episodic_turns_fts WHERE episodic_turns_fts MATCH 'amber'"
        ).fetchall() == [("ep_first",)]
        assert conn.execute(
            "SELECT id FROM episodic_turns_fts WHERE episodic_turns_fts MATCH 'green'"
        ).fetchall() == []
        conn.execute("UPDATE episodic_turns SET id='ep_renamed' WHERE id='ep_first'")
        assert conn.execute(
            "SELECT id FROM episodic_turns_fts WHERE episodic_turns_fts MATCH 'amber'"
        ).fetchall() == [("ep_renamed",)]
        conn.commit()
        stable = conn.execute(
            "SELECT docid FROM episodic_fts_docids WHERE episode_id='ep_renamed'"
        ).fetchone()[0]
        conn.execute("VACUUM")
        assert conn.execute(
            "SELECT docid FROM episodic_fts_docids WHERE episode_id='ep_renamed'"
        ).fetchone()[0] == stable
        conn.execute("DELETE FROM episodic_turns WHERE id='ep_renamed'")
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns_fts WHERE rowid=?", (stable,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_fts_docids WHERE episode_id='ep_renamed'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT id FROM episodic_turns_fts WHERE episodic_turns_fts MATCH 'Vega'"
        ).fetchall() == [("ep_second",)]
    finally:
        conn.close()


def test_rebuild_repairs_missing_and_orphaned_derived_rows(tmp_path):
    memory = _memory()
    conn = sqlite3.connect(tmp_path / "episodes.sqlite3")
    try:
        memory.install_schema(conn)
        _insert(conn, "ep_one", "Orion port is open")
        _insert(conn, "ep_two", "Vega port is closed")
        conn.execute("DELETE FROM episodic_turns_fts WHERE id='ep_one'")
        conn.execute(
            "INSERT INTO episodic_fts_docids(episode_id) VALUES('ep_orphan')"
        )
        memory.install_schema(conn)
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns_fts"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_fts_docids"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT id FROM episodic_turns_fts WHERE episodic_turns_fts MATCH 'Orion'"
        ).fetchall() == [("ep_one",)]
    finally:
        conn.close()


def test_delete_fails_closed_when_docid_mapping_is_missing(tmp_path):
    memory = _memory()
    conn = sqlite3.connect(tmp_path / "episodes.sqlite3")
    try:
        memory.install_schema(conn)
        _insert(conn, "ep_one", "Orion port is open")
        conn.execute(
            "DELETE FROM episodic_fts_docids WHERE episode_id='ep_one'"
        )
        with pytest.raises(sqlite3.IntegrityError, match="docid missing"):
            conn.execute("DELETE FROM episodic_turns WHERE id='ep_one'")
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns WHERE id='ep_one'"
        ).fetchone()[0] == 1
        memory.install_schema(conn)
        conn.execute("DELETE FROM episodic_turns WHERE id='ep_one'")
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns_fts"
        ).fetchone()[0] == 0
    finally:
        conn.close()
