"""Removing a memory also erases matching owned raw episode evidence."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module():
    name = "memory_wiki_episode_erase_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(module, home, bot, chat):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        chat, hermes_home=str(home), bot_id=bot, agent_context="primary",
    )
    provider._ingest_text = lambda *args, **kwargs: None
    return provider


def test_phrase_erasure_is_exactly_chat_and_trusted_bot_scoped(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "chat")
    module = _module()
    own = _provider(module, tmp_path, "alice", "chat-a")
    peer = _provider(module, tmp_path, "alice", "chat-b")
    other = _provider(module, tmp_path, "bob", "chat-a")
    try:
        phrase = "Orion sensor indicator is blue"
        own_id = module._episodic_memory.capture_turn(
            own, module, "user", f"Remember: {phrase}.",
        )
        peer_id = module._episodic_memory.capture_turn(
            peer, module, "user", f"Remember: {phrase}.",
        )
        other_id = module._episodic_memory.capture_turn(
            other, module, "user", f"Remember: {phrase}.",
        )
        monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "bot")
        bot_id = module._episodic_memory.capture_turn(
            own, module, "user", f"Shared note: {phrase}.",
        )
        assert all((own_id, peer_id, other_id, bot_id))
        result = module._episodic_memory.erase_matching_episodes(
            own, module, [phrase],
        )
        assert result["deleted"] == 2
        assert set(result["episode_ids"]) == {own_id, bot_id}
        rows = own._connect().execute(
            "SELECT id FROM episodic_turns ORDER BY id"
        ).fetchall()
        assert {row[0] for row in rows} == {peer_id, other_id}
        fts_rows = own._connect().execute(
            "SELECT id FROM episodic_turns_fts ORDER BY id"
        ).fetchall()
        assert {row[0] for row in fts_rows} == {peer_id, other_id}
    finally:
        for provider in (own, peer, other):
            provider.shutdown()


def test_phrase_boundaries_avoid_unrelated_longer_words(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    module = _module()
    own = _provider(module, tmp_path, "alice", "chat-a")
    try:
        exact = module._episodic_memory.capture_turn(
            own, module, "user", "We use C++ on the Atlas project.",
        )
        other = module._episodic_memory.capture_turn(
            own, module, "user", "The catalogue has blue covers.",
        )
        assert exact and other
        result = module._episodic_memory.erase_matching_episodes(
            own, module, "C++",
        )
        assert result["episode_ids"] == [exact]
        assert own._connect().execute(
            "SELECT id FROM episodic_turns"
        ).fetchall()[0][0] == other
        assert module._episodic_memory.erase_matching_episodes(
            own, module, "cat",
        )["deleted"] == 0
    finally:
        own.shutdown()


def test_erasure_joins_caller_transaction_and_queues_historical_vector_delete(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    module = _module()
    own = _provider(module, tmp_path, "alice", "chat-a")
    try:
        episode_id = module._episodic_memory.capture_turn(
            own, module, "user", "Orion sensor indicator is blue.",
        )
        assert episode_id
        conn = own._connect()
        with conn:
            conn.execute(
                """INSERT INTO episodic_vector_targets(
                    episode_id,endpoint,collection,vector_target_hash,
                    manifest_hash,status,indexed_at,updated_at)
                    VALUES(?,?,?,?,?,'active',1,1)""",
                (
                    episode_id, "http://127.0.0.1:6333",
                    "memory_wiki_episodes_old", "a" * 64, "b" * 64,
                ),
            )
        with conn:
            result = module._episodic_memory.erase_matching_episodes(
                own, module, ["Orion sensor indicator is blue."], conn=conn,
            )
            assert result["deleted"] == 1
            assert result["vector_deletes_queued"] is True
        rows = conn.execute(
            "SELECT payload_json FROM index_outbox "
            "WHERE object_type='episode' AND object_id=? AND operation='delete'",
            (episode_id,),
        ).fetchall()
        assert any(
            json.loads(str(row[0]))["collection"] == "memory_wiki_episodes_old"
            for row in rows
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns WHERE id=?", (episode_id,),
        ).fetchone()[0] == 0
    finally:
        own.shutdown()


def test_caller_rollback_restores_episode_and_fts(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    module = _module()
    own = _provider(module, tmp_path, "alice", "chat-a")
    try:
        episode_id = module._episodic_memory.capture_turn(
            own, module, "user", "Orion sensor indicator is blue.",
        )
        assert episode_id
        conn = own._connect()
        with pytest.raises(RuntimeError, match="simulated claim rollback"):
            with conn:
                result = module._episodic_memory.erase_matching_episodes(
                    own, module, "Orion sensor indicator is blue", conn=conn,
                )
                assert result["deleted"] == 1
                raise RuntimeError("simulated claim rollback")
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns WHERE id=?", (episode_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM episodic_turns_fts WHERE id=?", (episode_id,),
        ).fetchone()[0] == 1
    finally:
        own.shutdown()
