"""Host removals remain private when an old backup or checkpoint is restored."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


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


def _provider(module, home: Path, chat: str):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        chat, hermes_home=str(home), bot_id="trusted-private-bot",
        visibility_scope="chat", agent_context="primary",
    )
    provider._ingest_text = lambda *args, **kwargs: None
    return provider


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_SCOPE", "chat")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "chat")
    return tmp_path


def test_old_zip_replay_erases_only_owner_and_keeps_ledger_content_free(environment):
    module = _module("memory_wiki_privacy_zip_replay")
    owner = _provider(module, environment, "owner-chat")
    peer = _provider(module, environment, "peer-chat")
    phrase = "The indigo workshop stores its copper checklist beside desk eleven."
    try:
        owner.sync_turn("Remember: " + phrase, "")
        peer.sync_turn("Remember: " + phrase, "")
        own_id = owner.on_memory_write("add", "operations", phrase, {})["claim_ids"][0]
        peer_id = peer.on_memory_write("add", "operations", phrase, {})["claim_ids"][0]
        archive = owner._backup("pre-removal")["path"]
        removed = owner.on_memory_write("remove", "operations", phrase, {})
        assert removed["events_deleted"] and removed["episodes_deleted"]
        ledger = owner._privacy_erasure.log_path.read_text(encoding="utf-8")
        assert phrase not in ledger
        assert own_id not in ledger
        assert peer_id not in ledger

        peer.shutdown()
        owner._restore(archive)
        peer = _provider(module, environment, "peer-chat")
        conn = owner._connect()
        assert conn.execute("SELECT status FROM claims WHERE id=?", (own_id,)).fetchone()[0] == "retired"
        assert conn.execute("SELECT status FROM claims WHERE id=?", (peer_id,)).fetchone()[0] == "active"
        assert module._memory_events.query_events(owner, module, "indigo copper checklist", scope="chat")["events"] == []
        assert module._episodic_memory.query_episodes(owner, module, "indigo copper checklist")["episodes"] == []
        assert module._memory_events.query_events(peer, module, "indigo copper checklist", scope="chat")["events"]
    finally:
        owner.shutdown()
        peer.shutdown()


def test_intent_fsynced_before_failed_commit_replays_at_startup(environment, monkeypatch):
    module = _module("memory_wiki_privacy_crash_replay")
    owner = _provider(module, environment, "owner-chat")
    phrase = "The violet workshop keeps its signed schedule inside drawer five."
    own_id = owner.on_memory_write("add", "operations", phrase, {})["claim_ids"][0]
    original_append = owner._privacy_erasure.append

    def crash_after_append(*args, **kwargs):
        original_append(*args, **kwargs)
        raise RuntimeError("simulated crash before SQLite commit")

    monkeypatch.setattr(owner._privacy_erasure, "append", crash_after_append)
    with pytest.raises(RuntimeError, match="simulated crash"):
        owner.on_memory_write("remove", "operations", phrase, {})
    assert owner._connect().execute("SELECT status FROM claims WHERE id=?", (own_id,)).fetchone()[0] == "active"
    owner.shutdown()

    restarted = _provider(module, environment, "owner-chat")
    try:
        assert restarted._connect().execute("SELECT status FROM claims WHERE id=?", (own_id,)).fetchone()[0] == "retired"
        assert module._memory_events.query_events(restarted, module, "violet signed schedule", scope="chat")["events"] == []
    finally:
        restarted.shutdown()


def test_old_logical_checkpoint_replay_does_not_resurrect_claim(environment):
    module = _module("memory_wiki_privacy_checkpoint_replay")
    owner = _provider(module, environment, "owner-chat")
    phrase = "The coral workshop keeps its approved checklist next to shelf eight."
    try:
        own_id = owner.on_memory_write("add", "operations", phrase, {})["claim_ids"][0]
        checkpoint = owner._journal_checkpoint("before-private-removal")
        owner.on_memory_write("remove", "operations", phrase, {})
        result = owner._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
        assert result["apply"]
        assert owner._connect().execute("SELECT status FROM claims WHERE id=?", (own_id,)).fetchone()[0] == "retired"
    finally:
        owner.shutdown()


def test_old_archive_rows_pruned_before_remove_are_erased_by_text_fingerprint(environment):
    module = _module("memory_wiki_privacy_pruned_archive")
    owner = _provider(module, environment, "owner-chat")
    phrase = "The silver workshop keeps its blue binder beside cabinet six."
    try:
        owner.sync_turn("Remember: " + phrase, "")
        claim_id = owner.on_memory_write("add", "operations", phrase, {})["claim_ids"][0]
        archive = owner._backup("before-retention-prune")["path"]
        conn = owner._connect()
        with conn:
            conn.execute("DELETE FROM memory_events WHERE owner_chat_hash=?", (owner._chat_hash(owner.session_id),))
            conn.execute("DELETE FROM episodic_turns WHERE owner_chat_hash=?", (owner._chat_hash(owner.session_id),))
        removed = owner.on_memory_write("remove", "operations", phrase, {})
        assert removed["claim_ids"] == [claim_id]
        assert removed["event_ids"] == []
        assert removed["episodes_deleted"] == 0
        owner._restore(archive)
        assert module._memory_events.query_events(owner, module, "silver blue binder", scope="chat")["events"] == []
        assert module._episodic_memory.query_episodes(owner, module, "silver blue binder")["episodes"] == []
    finally:
        owner.shutdown()


def test_old_linked_event_without_matching_text_is_erased(environment):
    module = _module("memory_wiki_privacy_linked_archive")
    owner = _provider(module, environment, "owner-chat")
    phrase = "The saffron workshop stores signed reports in room nine."
    try:
        claim_id = owner.on_memory_write("add", "operations", phrase, {})["claim_ids"][0]
        event_id = module._memory_events.capture_event(
            owner, module, "An unrelated source note with a separate wording.",
            role="host", event_type="memory_mutation", scope="chat",
        )
        assert event_id
        module._memory_events.link_evidence(owner, event_id, "claim", claim_id)
        archive = owner._backup("before-linked-retention-prune")["path"]
        conn = owner._connect()
        with conn:
            conn.execute("DELETE FROM memory_events WHERE event_id=?", (event_id,))
        owner.on_memory_write("remove", "operations", phrase, {})
        owner._restore(archive)
        assert owner._connect().execute(
            "SELECT 1 FROM memory_events WHERE event_id=?", (event_id,),
        ).fetchone() is None
    finally:
        owner.shutdown()


def test_ledger_integrity_failure_blocks_provider_start(environment):
    module = _module("memory_wiki_privacy_tamper")
    owner = _provider(module, environment, "owner-chat")
    phrase = "The teal workshop posts the daily checklist near gate three."
    owner.on_memory_write("remove", "operations", phrase, {})
    ledger = owner._privacy_erasure.log_path
    owner.shutdown()
    with open(ledger, "ab") as out:
        out.write(b"{}\n")
    with pytest.raises(RuntimeError, match="privacy erasure ledger integrity failed"):
        _provider(module, environment, "owner-chat")
