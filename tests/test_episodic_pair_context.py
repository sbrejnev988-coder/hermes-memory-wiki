"""Paired episodic context recovers answers without widening its trust boundary."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_episodic_pair_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "chat")


def _provider(module, home, bot="alice", chat="chat-a"):
    provider = module.MemoryWikiProvider()
    provider.initialize(chat, hermes_home=str(home), bot_id=bot, agent_context="primary")
    provider._ingest_text = lambda *_a, **_k: None
    return provider


def test_query_match_recovers_answer_from_same_turn(tmp_path, monkeypatch):
    _environment(tmp_path, monkeypatch)
    module = _module()
    provider = _provider(module, tmp_path)
    try:
        provider.sync_turn(
            "What did Elena choose for the winter launch?",
            "The selected codename is Silver Heron.",
        )
        rows = provider._connect().execute(
            "SELECT role,turn_id FROM episodic_turns ORDER BY rowid",
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["turn_id"] and rows[0]["turn_id"] == rows[1]["turn_id"]

        payload = module._episodic_memory.query_episodes(
            provider, module, "Elena winter launch", limit=2,
            include_diagnostics=True,
        )
        assert [row["role"] for row in payload["episodes"]] == ["user", "assistant"]
        assert "Silver Heron" in payload["episodes"][1]["content"]
        assert payload["diagnostics"]["paired_returned"] == 1
        assert len(module._episodic_memory.query_episodes(
            provider, module, "Elena winter launch", limit=1,
        )["episodes"]) == 1
    finally:
        provider.shutdown()


def test_pair_expansion_keeps_exact_source_chat(tmp_path, monkeypatch):
    _environment(tmp_path, monkeypatch)
    module = _module()
    chat_a = _provider(module, tmp_path, chat="chat-a")
    chat_b = _provider(module, tmp_path, chat="chat-b")
    try:
        chat_a.sync_turn(
            "Where is the Atlas cedar parcel?",
            "It is in the north archive drawer.",
        )
        chat_b.sync_turn(
            "Unrelated foreign prompt.",
            "Foreign answer must never cross the chat boundary.",
        )
        conn = chat_a._connect()
        source_turn = conn.execute(
            "SELECT turn_id FROM episodic_turns WHERE content LIKE 'Where is the Atlas%'",
        ).fetchone()[0]
        # Simulate a collision/corrupt adapter assignment in another chat.
        with conn:
            conn.execute(
                "UPDATE episodic_turns SET turn_id=? WHERE content LIKE 'Foreign answer%'",
                (source_turn,),
            )
        result = module._episodic_memory.query_episodes(
            chat_a, module, "Atlas cedar parcel", limit=5,
        )
        rendered = "\n".join(row["content"] for row in result["episodes"])
        assert "north archive drawer" in rendered
        assert "Foreign answer" not in rendered
        with conn:
            conn.execute(
                "UPDATE episodic_turns SET expires_at=1 WHERE content LIKE 'It is in the north%'",
            )
        expired = module._episodic_memory.query_episodes(
            chat_a, module, "Atlas cedar parcel", limit=5,
        )
        expired_text = "\n".join(row["content"] for row in expired["episodes"])
        assert "north archive drawer" not in expired_text
        assert "Foreign answer" not in expired_text
    finally:
        chat_a.shutdown()
        chat_b.shutdown()


def test_pair_expansion_reuses_secret_guard_and_shared_budget(tmp_path, monkeypatch):
    _environment(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_QUERY_MAX_CHARS", "800")
    module = _module()
    provider = _provider(module, tmp_path)
    try:
        provider.sync_turn(
            "budgetprobe " + "alpha " * 48,
            "Answer " + "beta " * 55,
        )
        conn = provider._connect()
        original = conn.execute(
            "SELECT * FROM episodic_turns WHERE role='assistant'",
        ).fetchone()
        with conn:
            conn.execute(
                """INSERT INTO episodic_turns
                   (id,content,role,turn_id,owner_bot_id,owner_chat_hash,
                    visibility_scope,created_at,expires_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    "ep_budget_extra", "Extra " + "gamma " * 55, "assistant",
                    original["turn_id"], original["owner_bot_id"],
                    original["owner_chat_hash"], original["visibility_scope"],
                    original["created_at"], original["expires_at"],
                ),
            )
        budgeted = module._episodic_memory.query_episodes(
            provider, module, "budgetprobe", limit=5,
            include_diagnostics=True,
        )
        assert sum(len(row["content"]) for row in budgeted["episodes"]) <= 800
        assert budgeted["diagnostics"]["budget_rejected"] >= 1

        provider.sync_turn(
            "secretpair quartz beacon request",
            "This safe placeholder will be corrupted below.",
        )
        with conn:
            conn.execute(
                """UPDATE episodic_turns
                   SET content='api_key=sk-test-123456789012345678901234'
                   WHERE content LIKE 'This safe placeholder%'""",
            )
        guarded = module._episodic_memory.query_episodes(
            provider, module, "secretpair quartz beacon", limit=2,
            include_diagnostics=True,
        )
        rendered = "\n".join(row["content"] for row in guarded["episodes"])
        assert "sk-test" not in rendered
        assert guarded["diagnostics"]["secret_rejected"] >= 1
    finally:
        provider.shutdown()


def test_assistant_only_match_renders_pair_in_conversation_order(tmp_path, monkeypatch):
    _environment(tmp_path, monkeypatch)
    module = _module()
    provider = _provider(module, tmp_path, bot="bot-a", chat="chat-a")
    try:
        assistant = (
            "The telescope has routine catalog notes. "
            + ("ordinary filler " * 180)
            + "The final location is beside the zaffre-only astrolabe marker."
        )
        provider.sync_turn(
            "Where did we store the ordinary telescope?",
            assistant,
        )
        payload = module._episodic_memory.query_episodes(
            provider, module, "zaffre-only astrolabe marker", limit=2,
            include_diagnostics=True,
        )
        assert [item["role"] for item in payload["episodes"]] == ["user", "assistant"]
        assert "zaffre-only astrolabe marker" in payload["episodes"][1]["content"]
        assert payload["episodes"][1]["truncated"] is True
        assert payload["episodes"][1]["source_chars"] == len(assistant)
        assert payload["diagnostics"]["paired_returned"] == 1
    finally:
        provider.shutdown()


def test_schema_migration_preserves_legacy_rows_without_pairing(tmp_path, monkeypatch):
    _environment(tmp_path, monkeypatch)
    module = _module()
    path = tmp_path / "legacy-episodes.sqlite3"
    conn = sqlite3.connect(path)
    try:
        conn.execute("""CREATE TABLE episodic_turns(
            id TEXT PRIMARY KEY, content TEXT NOT NULL, role TEXT NOT NULL,
            owner_bot_id TEXT NOT NULL, owner_chat_hash TEXT NOT NULL,
            visibility_scope TEXT NOT NULL, created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL)""")
        stamp = int(time.time())
        conn.execute(
            "INSERT INTO episodic_turns VALUES(?,?,?,?,?,?,?,?)",
            ("ep_legacy", "Legacy amber compass.", "user", "alice", "chat-hash",
             "chat", stamp, stamp + 3600),
        )
        module._episodic_memory.install_schema(conn)
        module._episodic_memory.install_schema(conn)  # Migration is idempotent.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(episodic_turns)")}
        assert "turn_id" in columns
        assert "truncated" in columns
        assert "source_chars" in columns
        assert conn.execute(
            "SELECT turn_id FROM episodic_turns WHERE id='ep_legacy'",
        ).fetchone()[0] == ""
        truncation = conn.execute(
            "SELECT truncated,source_chars FROM episodic_turns WHERE id='ep_legacy'",
        ).fetchone()
        assert truncation == (0, len("Legacy amber compass."))
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns_fts WHERE id='ep_legacy'",
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_episodic_turn_pair'",
        ).fetchone()
    finally:
        conn.close()
