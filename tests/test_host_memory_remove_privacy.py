"""Host removal retires exact visible claims and erases derived recall evidence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _provider(module, home: Path, bot: str, chat: str):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        chat,
        hermes_home=str(home),
        bot_id=bot,
        visibility_scope="chat",
        agent_context="test",
    )
    provider._ingest_text = lambda *args, **kwargs: None
    return provider


def test_add_remove_is_acl_scoped_privacy_erasure(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_SCOPE", "chat")
    module = _module("memory_wiki_host_remove_privacy_test")
    owner = _provider(module, tmp_path, "owner-bot", "owner-chat")
    foreign = _provider(module, tmp_path, "foreign-bot", "foreign-chat")
    statement = (
        "The Cobalt observatory keeps its signed amber checklist beside "
        "console seven every Friday."
    )
    try:
        owner_add = owner.on_memory_write("add", "operations", statement, {"adapter": "test"})
        foreign_add = foreign.on_memory_write("add", "operations", statement, {"adapter": "test"})
        owner_id = owner_add["claim_ids"][0]
        foreign_id = foreign_add["claim_ids"][0]
        assert owner_id != foreign_id

        conn = owner._connect()
        owner_event = conn.execute(
            """SELECT e.event_id FROM memory_events e
               JOIN memory_event_evidence l ON l.event_id=e.event_id
               WHERE l.target_type='claim' AND l.target_id=?""",
            (owner_id,),
        ).fetchone()
        assert owner_event is not None
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_observation_events WHERE event_id=?",
            (owner_event["event_id"],),
        ).fetchone()[0] == 1

        # Exercise the real status trigger without starting a remote worker.
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('semantic_enabled','1')"
            )
        removed = owner.on_memory_write("remove", "operations", statement, {})

        assert removed["count"] == 1
        assert removed["claim_ids"] == [owner_id]
        assert removed["events_deleted"] == 1
        assert removed["observations_deleted"] == 1
        assert conn.execute(
            "SELECT status FROM claims WHERE id=?", (owner_id,),
        ).fetchone()[0] == "retired"
        assert conn.execute(
            "SELECT status FROM claims WHERE id=?", (foreign_id,),
        ).fetchone()[0] == "active"

        assert owner._search(statement, record_retrieval=False) == []
        assert foreign._search(statement, record_retrieval=False)[0]["id"] == foreign_id
        assert module._memory_events.query_events(
            owner, module, "Cobalt amber checklist", scope="chat",
        )["events"] == []
        assert module._memory_observations.query_observations(
            owner, module, "Cobalt amber checklist", scope="chat",
        )["observations"] == []
        assert module._memory_events.query_events(
            foreign, module, "Cobalt amber checklist", scope="chat",
        )["events"]
        assert module._memory_observations.query_observations(
            foreign, module, "Cobalt amber checklist", scope="chat",
        )["observations"]

        # The status transition atomically removed FTS state and queued the
        # semantic deletion.  A remove event containing the body was not added.
        assert conn.execute(
            "SELECT COUNT(*) FROM claims_fts WHERE id=?", (owner_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            """SELECT COUNT(*) FROM index_outbox
               WHERE object_type='claim' AND object_id=?
                 AND operation='delete' AND status='pending'""",
            (owner_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT COUNT(*) FROM memory_events
               WHERE event_type='memory_mutation' AND provenance_json LIKE '%remove%'"""
        ).fetchone()[0] == 0
    finally:
        owner.shutdown()
        foreign.shutdown()


def test_remove_erases_matching_dialogue_episode_event_and_observation(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_SCOPE", "chat")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "chat")
    module = _module("memory_wiki_remove_dialogue_sources")
    owner = _provider(module, tmp_path, "owner-bot", "owner-chat")
    peer = _provider(module, tmp_path, "owner-bot", "peer-chat")
    owner.agent_context = peer.agent_context = "primary"
    statement = "The amber observatory keeps its signed checklist beside console seven."
    try:
        owner.sync_turn("Remember: " + statement, "")
        peer.sync_turn("Remember: " + statement, "")
        added = owner.on_memory_write("add", "operations", statement, {})
        assert added["claim_ids"]
        assert module._episodic_memory.query_episodes(
            owner, module, "amber observatory checklist"
        )["episodes"]
        assert module._memory_events.query_events(
            owner, module, "amber observatory checklist", scope="chat"
        )["events"]
        removed = owner.on_memory_write("remove", "operations", statement, {})
        assert removed["episodes_deleted"] >= 1
        assert removed["events_deleted"] >= 1
        assert module._episodic_memory.query_episodes(
            owner, module, "amber observatory checklist"
        )["episodes"] == []
        assert module._memory_events.query_events(
            owner, module, "amber observatory checklist", scope="chat"
        )["events"] == []
        assert module._memory_observations.query_observations(
            owner, module, "amber observatory checklist", scope="chat"
        )["observations"] == []
        assert module._episodic_memory.query_episodes(
            peer, module, "amber observatory checklist"
        )["episodes"]
    finally:
        owner.shutdown()
        peer.shutdown()


def test_short_phrase_removal_erases_containing_event_only_in_owner_chat(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_SCOPE", "chat")
    module = _module("memory_wiki_short_remove_event")
    owner = _provider(module, tmp_path, "same-platform", "one-chat")
    peer = _provider(module, tmp_path, "same-platform", "other-chat")
    owner.agent_context = peer.agent_context = "primary"
    try:
        owner.sync_turn("I use Vim for coding.", "")
        peer.sync_turn("I use Vim for coding.", "")
        owner.on_memory_write("add", "preference", "I use Vim", {})
        assert module._memory_events.query_events(
            owner, module, "Vim coding", scope="chat"
        )["events"]
        outcome = owner.on_memory_write("remove", "preference", "I use Vim", {})
        assert outcome["events_deleted"] >= 1
        assert module._memory_events.query_events(
            owner, module, "Vim coding", scope="chat"
        )["events"] == []
        assert module._memory_events.query_events(
            peer, module, "Vim coding", scope="chat"
        )["events"]
    finally:
        owner.shutdown()
        peer.shutdown()
