"""Observation recall revalidates every event counted by the current version."""

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


def test_non_representative_policy_rejection_rebuilds_without_unsafe_support(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1")
    module = _module("memory_wiki_observation_reguard_test")
    observations = module._memory_observations
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "chat-a", hermes_home=str(tmp_path), bot_id="alice", agent_context="test",
    )
    text = "The Meridian telescope calibration card is violet."
    try:
        first = module._memory_events.capture_event(
            provider, module, text, turn_id="turn-1", occurred_at=100,
            observed_at=100, event_type="observation", scope="chat",
        )
        second = module._memory_events.capture_event(
            provider, module, text, turn_id="turn-2", occurred_at=200,
            observed_at=200, event_type="observation", scope="chat",
        )
        assert first and second
        observations.consolidate_events(provider, module, scope="chat")
        initial = observations.query_observations(
            provider, module, "Meridian telescope violet", scope="chat",
        )["observations"]
        assert len(initial) == 1
        assert initial[0]["support_count"] == 2
        assert initial[0]["observation_id"]
        assert initial[0]["evidence_event_ids"] == [first, second]

        original_guard = provider._inspect_recall_text

        def tightened_guard(content, *, item_id="", **kwargs):
            if item_id == first:
                return {
                    "status": "quarantined", "content": "",
                    "trust_level": "quarantined", "injection_signals": ["new-policy"],
                }
            return original_guard(content, item_id=item_id, **kwargs)

        provider._inspect_recall_text = tightened_guard
        # The representative is the later event.  Rejecting only the older,
        # non-representative source must still fail the whole stale version.
        assert observations.query_observations(
            provider, module, "Meridian telescope violet", scope="chat",
        )["observations"] == []
        decision = provider._connect().execute(
            "SELECT outcome FROM memory_observation_event_decisions WHERE event_id=?",
            (first,),
        ).fetchone()
        assert decision and decision["outcome"] == "rejected"
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM memory_observations"
        ).fetchone()[0] == 0

        rebuilt = observations.consolidate_events(provider, module, scope="chat")
        assert rebuilt["versions_created"] == 1
        recalled = observations.query_observations(
            provider, module, "Meridian telescope violet", scope="chat",
        )["observations"]
        assert len(recalled) == 1
        assert recalled[0]["support_count"] == 1
        assert recalled[0]["independent_support_count"] == 1
        assert recalled[0]["confidence"] == 0.35
        assert recalled[0]["evidence_event_ids"] == [second]
        assert first not in recalled[0]["evidence_event_ids"]
    finally:
        provider.shutdown()


def test_transient_non_representative_guard_failure_is_fail_closed_and_retried(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATION_RETRY_BASE_SECONDS", "1")
    module = _module("memory_wiki_observation_reguard_transient_test")
    observations = module._memory_observations
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "chat-a", hermes_home=str(tmp_path), bot_id="alice", agent_context="test",
    )
    text = "The transient Meridian telescope calibration card is indigo."
    try:
        first = module._memory_events.capture_event(
            provider, module, text, turn_id="turn-1", occurred_at=100,
            observed_at=100, event_type="observation", scope="chat",
        )
        second = module._memory_events.capture_event(
            provider, module, text, turn_id="turn-2", occurred_at=200,
            observed_at=200, event_type="observation", scope="chat",
        )
        assert first and second
        observations.consolidate_events(provider, module, scope="chat")
        original_guard = provider._inspect_recall_text

        def unavailable_guard(content, *, item_id="", **kwargs):
            if item_id == first:
                raise RuntimeError("temporary guard outage")
            return original_guard(content, item_id=item_id, **kwargs)

        provider._inspect_recall_text = unavailable_guard
        assert observations.query_observations(
            provider, module, "Meridian telescope indigo", scope="chat",
        )["observations"] == []
        retry = provider._connect().execute(
            "SELECT attempts,last_reason FROM memory_observation_event_retries WHERE event_id=?",
            (first,),
        ).fetchone()
        assert retry and retry["attempts"] == 1
        # Transient failure does not destroy the linked version; it remains
        # hidden until the scheduled maintenance recheck succeeds.
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM memory_observations"
        ).fetchone()[0] == 1
    finally:
        provider.shutdown()
