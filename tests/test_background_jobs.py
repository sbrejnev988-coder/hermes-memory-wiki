"""Durable content-free work, ownership, budgets, and deleted-source behavior."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


jobs = _module("test_memory_wiki_background_jobs", ROOT / "background_jobs.py")


def _store(tmp_path, *, owner="a" * 64, profile="b" * 64):
    path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(path) as conn:
        jobs.install_schema(conn)
    return jobs.JobStore(path, profile, owner)


def _event(index=1):
    return {"event_id": "evt_" + f"{index:032x}"}


def test_payload_is_strictly_content_free(tmp_path):
    store = _store(tmp_path)
    partition = "c" * 64
    for bad in (
        {"event_id": "evt_" + "a" * 32, "transcript": "private text"},
        {"event_id": "sk-test-1234567890123456789"},
        {"event_id": "evt_" + "a" * 32, "high_watermark": "1"},
        {"event_id": "evt_" + "a" * 32, "high_watermark": True},
    ):
        with pytest.raises(ValueError):
            store.enqueue("extract_session_events", bad, partition)
    with pytest.raises(ValueError):
        store.enqueue("run_shell", _event(), partition)
    store.enqueue("extract_session_events", {**_event(), "high_watermark": 9}, partition)
    with sqlite3.connect(store.db_path) as conn:
        serialized = conn.execute("SELECT payload_json FROM memory_jobs").fetchone()[0]
    assert json.loads(serialized) == {**_event(), "high_watermark": 9}
    assert "private text" not in serialized


def test_coalescing_generation_and_fenced_ack(tmp_path):
    store = _store(tmp_path)
    partition, worker = "c" * 64, "d" * 32
    first = store.enqueue("extract_session_events", {**_event(1), "high_watermark": 1}, partition, now=100)
    assert store.enqueue("extract_session_events", {**_event(2), "high_watermark": 2}, partition, now=100) == first
    lease = store.lease(worker, now=100)
    assert lease and json.loads(lease["payload_json"])["high_watermark"] == 2
    assert store.enqueue("extract_session_events", {**_event(3), "high_watermark": 3}, partition, now=101) == first
    assert store.finish(lease, worker, now=101)
    second = store.lease("e" * 32, now=101)
    assert second and second["job_id"] == first
    assert json.loads(second["payload_json"])["high_watermark"] == 3
    assert not store.finish(lease, worker, now=102)
    assert store.finish(second, "e" * 32, now=102)
    assert store.health(now=102)["pending"] == 0


def test_lease_expiry_restart_and_old_lease_fencing(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_LEASE_SECONDS", "30")
    store = _store(tmp_path)
    identifier = store.enqueue("consolidate_observations", _event(), "c" * 64, now=100)
    first = store.lease("d" * 32, now=100)
    assert first and store.lease("e" * 32, now=129) is None
    restarted = jobs.JobStore(store.db_path, store.profile, store.owner)
    second = restarted.lease("e" * 32, now=130)
    assert second and second["job_id"] == identifier and second["attempts"] == 2
    assert not store.finish(first, "d" * 32, now=131)
    assert restarted.finish(second, "e" * 32, now=131)


def test_same_worker_old_lease_cannot_ack_reacquisition(tmp_path):
    store = _store(tmp_path)
    store.enqueue("consolidate_observations", _event(), "c" * 64, now=100)
    worker = "d" * 32
    first = store.lease(worker, now=100)
    second = store.lease(worker, now=220)
    assert first and second and first["lease_owner"] != second["lease_owner"]
    assert not store.finish(first, worker, now=221)
    assert store.finish(second, worker, now=221)


def test_heartbeat_renews_only_current_unexpired_lease(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_LEASE_SECONDS", "30")
    store = _store(tmp_path)
    store.enqueue("consolidate_observations", _event(), "c" * 64, now=100)
    worker = "d" * 32
    first = store.lease(worker, now=100)
    assert first and store.owns(first, worker, now=119)
    assert store.renew(first, worker, now=119)
    assert store.lease("e" * 32, now=131) is None
    assert not store.owns(first, worker, now=150)
    assert not store.renew(first, worker, now=150)
    second = store.lease("e" * 32, now=150)
    assert second and not store.owns(first, worker, now=150)


def test_bounded_retry_and_dead_no_exception_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_RETRY_BASE_SECONDS", "2")
    store = _store(tmp_path)
    store.enqueue("extract_session_events", {**_event(), "high_watermark": 1}, "c" * 64, now=100)
    worker = "d" * 32
    first = store.lease(worker, now=100)
    assert first and store.finish(first, worker, error_code="secret-sk-test-12345678", now=100)
    assert store.lease(worker, now=101) is None
    second = store.lease(worker, now=104)
    assert second and store.finish(second, worker, error_code="network", now=104)
    health = store.health(now=104)
    assert health["dead"] == 1
    with sqlite3.connect(store.db_path) as conn:
        code = conn.execute("SELECT last_error_code FROM memory_jobs").fetchone()[0]
    assert code == "network"


def test_dependency_deferral_preserves_job_without_consuming_attempts(tmp_path):
    store = _store(tmp_path)
    store.enqueue("consolidate_observations", _event(), "c" * 64, now=100)
    worker = "d" * 32
    leased = store.lease(worker, now=100)
    assert leased and leased["attempts"] == 1
    assert store.defer(leased, worker, until=500, now=101)
    assert store.lease(worker, now=499) is None
    again = store.lease(worker, now=500)
    assert again and again["attempts"] == 1


def test_daily_budget_defers_until_utc_day_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_DAILY_JOBS", "1")
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_DAILY_REQUESTS", "1")
    store = _store(tmp_path)
    store.enqueue("extract_session_events", {**_event(1), "high_watermark": 1}, "c" * 64, now=86410)
    store.enqueue("enrich_claim_graph", {"claim_id": "c_abc"}, "d" * 64, now=86410)
    first = store.lease("e" * 32, now=86410)
    assert first and store.finish(first, "e" * 32, now=86411)
    assert store.lease("e" * 32, now=86412) is None
    health = store.health(now=86412)
    assert health["pending"] == 1 and health["requests_today"] == 1
    assert store.lease("e" * 32, now=172799) is None
    assert store.lease("e" * 32, now=172800) is not None


def test_profile_and_bot_partition_isolation(tmp_path):
    first = _store(tmp_path, owner="a" * 64, profile="b" * 64)
    another_bot = jobs.JobStore(first.db_path, first.profile, "c" * 64)
    another_profile = jobs.JobStore(first.db_path, "d" * 64, first.owner)
    first.enqueue("consolidate_observations", _event(), "e" * 64, now=100)
    assert another_bot.lease("f" * 32, now=100) is None
    assert another_profile.lease("f" * 32, now=100) is None
    assert first.lease("f" * 32, now=100)


def _plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "0")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    name = "test_background_plugin_" + str(time.time_ns())
    plugin = _module(name, ROOT / "__init__.py")
    provider = plugin.MemoryWikiProvider()
    provider.initialize("private-session", hermes_home=str(tmp_path), bot_id="bot-background", agent_context="primary")
    # Tests that need a project context set it explicitly. The provider may
    # otherwise infer one from the test runner's repository working directory.
    provider.project_scope = ""
    if provider._background_worker:
        provider._background_worker.stop()
        provider._background_worker = None
    return plugin, provider


def test_session_enqueues_only_retained_event_reference_and_deletion_wins(tmp_path, monkeypatch):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        text = "The observatory in Luma owns the blue telescope."
        provider.sync_turn(text, "Acknowledged.")
        provider.on_session_end([{"role": "user", "content": text}])
        conn = provider._connect()
        records = conn.execute(
            "SELECT job_type,payload_json FROM memory_jobs ORDER BY created_at,job_id"
        ).fetchall()
        assert {r["job_type"] for r in records} == {
            "consolidate_observations", "extract_session_events",
        }
        assert all(text not in r["payload_json"] for r in records)
        monkeypatch.setattr(plugin, "extract_session_claims", lambda *_a, **_kw: pytest.fail("deleted transcript sent to extractor"))
        with conn:
            conn.execute("DELETE FROM memory_events")
        for _ in range(3):
            jobs.run_once(provider, plugin)
        assert conn.execute("SELECT COUNT(*) FROM claims WHERE source='extractor:llm'").fetchone()[0] == 0
    finally:
        provider.shutdown()


def test_worker_rehydrates_event_owner_for_consolidation(tmp_path, monkeypatch):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        provider.sync_turn("The copper telescope belongs to the Aurora exhibit.", "")
        # Job worker has a separate provider connection and uses the retained
        # event's original chat/session partition without raw session IDs.
        assert jobs.run_once(provider, plugin)
        conn = provider._connect()
        assert conn.execute("SELECT COUNT(*) FROM memory_observations").fetchone()[0] >= 1
        source = conn.execute("SELECT owner_session_hash FROM memory_events LIMIT 1").fetchone()[0]
        assert source not in conn.execute("SELECT payload_json FROM memory_jobs LIMIT 1").fetchone()[0]
    finally:
        provider.shutdown()


def test_coalesced_deleted_pointer_uses_retained_partition_event(tmp_path, monkeypatch):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        first = plugin._memory_events.capture_event(
            provider, plugin, "Aurora Observatory has a copper telescope.",
            event_type="dialogue_turn", role="user", session_id=provider.session_id,
        )
        second = plugin._memory_events.capture_event(
            provider, plugin, "Aurora Observatory opens each Monday.",
            event_type="dialogue_turn", role="user", session_id=provider.session_id,
        )
        assert first and second
        assert jobs.enqueue_event(provider, "consolidate_observations", first)
        assert jobs.enqueue_event(provider, "consolidate_observations", second)
        with provider._connect() as conn:
            conn.execute("DELETE FROM memory_events WHERE event_id=?", (second,))
        assert jobs.run_once(provider, plugin)
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM memory_observation_event_decisions WHERE event_id=?",
            (first,),
        ).fetchone()[0] == 1
    finally:
        provider.shutdown()


@pytest.mark.parametrize("erase_during_remote", [False, True])
def test_extraction_callback_is_fenced_by_current_source(tmp_path, monkeypatch, erase_during_remote):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_AUTO_EXTRACT", "1")
    monkeypatch.setenv("MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "1")
    try:
        event_id = plugin._memory_events.capture_event(
            provider, plugin, "The violet telescope is housed at Aurora Observatory.",
            event_type="dialogue_turn", role="user", session_id=provider.session_id,
        )
        assert event_id and jobs.enqueue_event(provider, "extract_session_events", event_id)
        invoked = []

        def fake_extract(exchanges, session_id, *, add_claim_callback, **_kwargs):
            assert exchanges[0]["role"] == "user"
            assert "violet telescope" in exchanges[0]["content"]
            if erase_during_remote:
                with provider._connect() as conn:
                    conn.execute("DELETE FROM memory_events WHERE event_id=?", (event_id,))
            identifier = add_claim_callback(
                "User prefers the violet telescope at Aurora Observatory.",
                topic="preferences", evidence=json.dumps({
                    "schema": "memory-wiki-extraction-evidence-v1",
                    "session_id": session_id, "speaker": "user", "message_index": 0,
                    "evidence_quote": exchanges[0]["content"], "extractor": "extractor:heuristic",
                }),
                source="extractor:heuristic", confidence=.81, salience=.7,
                visibility_scope="chat", event_at=0, event_timezone="UTC",
            )
            invoked.append(identifier)
            return {"persisted_ids": [identifier] if identifier else [], "errors": [], "error": ""}

        monkeypatch.setattr(plugin, "extract_session_claims", fake_extract)
        assert jobs.run_once(provider, plugin)
        assert invoked, "extractor did not receive retained event"
        rows = provider._connect().execute(
            "SELECT id,origin_chat_hash FROM claims WHERE source='extractor:heuristic'"
        ).fetchall()
        if erase_during_remote:
            assert rows == []
        else:
            assert len(rows) == 1 and invoked[0] == rows[0]["id"]
            assert rows[0]["origin_chat_hash"] == provider._chat_hash(provider.session_id)
            assert provider._connect().execute(
                "SELECT COUNT(*) FROM memory_jobs WHERE job_type='enrich_claim_graph'"
            ).fetchone()[0] == 1
    finally:
        provider.shutdown()


def test_weak_background_candidate_never_creates_review_side_effect(tmp_path, monkeypatch):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        event_id = plugin._memory_events.capture_event(
            provider, plugin, "The violet telescope is housed at Aurora Observatory.",
            event_type="dialogue_turn", role="user", session_id=provider.session_id,
        )
        assert event_id and jobs.enqueue_event(provider, "extract_session_events", event_id)

        def weak_candidate(_exchanges, _session_id, *, add_claim_callback, **_kwargs):
            assert add_claim_callback(
                "Aurora Observatory displays a violet telescope.", topic="equipment",
                evidence="Grounded test quote.", source="extractor:heuristic",
                confidence=.81, salience=.7, visibility_scope="chat",
            ) == ""
            return {"persisted_ids": [], "errors": [], "error": ""}

        monkeypatch.setattr(plugin, "extract_session_claims", weak_candidate)
        assert jobs.run_once(provider, plugin)
        assert provider._connect().execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 0
    finally:
        provider.shutdown()


def _second_project_provider(plugin, tmp_path, project_id):
    provider = plugin.MemoryWikiProvider()
    provider.initialize(
        "private-session", hermes_home=str(tmp_path), bot_id="bot-background",
        project_id=project_id, agent_context="primary",
    )
    if provider._background_worker:
        provider._background_worker.stop()
        provider._background_worker = None
    return provider


def test_same_session_two_projects_never_promote_project_events_to_chat(tmp_path, monkeypatch):
    plugin, first = _plugin(tmp_path, monkeypatch)
    first.project_scope = "project-alpha"
    second = _second_project_provider(plugin, tmp_path, "project-beta")
    try:
        alpha = plugin._memory_events.capture_event(
            first, plugin, "Alpha project uses the violet telescope.",
            event_type="dialogue_turn", role="user", scope="project",
            session_id=first.session_id,
        )
        beta = plugin._memory_events.capture_event(
            second, plugin, "Beta project uses the copper telescope.",
            event_type="dialogue_turn", role="user", scope="project",
            session_id=second.session_id,
        )
        assert alpha and beta
        assert jobs.enqueue_event(first, "extract_session_events", alpha)
        monkeypatch.setattr(
            plugin, "extract_session_claims",
            lambda *_args, **_kwargs: pytest.fail("project evidence reached chat extractor"),
        )
        assert jobs.run_once(first, plugin)
        assert first._connect().execute(
            "SELECT COUNT(*) FROM claims WHERE source LIKE 'extractor:%'"
        ).fetchone()[0] == 0
    finally:
        second.shutdown()
        first.shutdown()


def test_chat_extraction_excludes_other_scope_in_same_session(tmp_path, monkeypatch):
    plugin, chat = _plugin(tmp_path, monkeypatch)
    other = _second_project_provider(plugin, tmp_path, "project-beta")
    try:
        chat_event = plugin._memory_events.capture_event(
            chat, plugin, "User prefers the violet telescope in Aurora.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=chat.session_id,
        )
        project_event = plugin._memory_events.capture_event(
            other, plugin, "The private beta design uses a copper telescope.",
            event_type="dialogue_turn", role="user", scope="project",
            session_id=other.session_id,
        )
        assert chat_event and project_event
        assert jobs.enqueue_event(chat, "extract_session_events", chat_event)
        seen = []

        def record(exchanges, **_kwargs):
            seen.extend(str(item["content"]) for item in exchanges)
            return {"persisted_ids": [], "errors": [], "error": ""}

        monkeypatch.setattr(plugin, "extract_session_claims", record)
        assert jobs.run_once(chat, plugin)
        assert len(seen) == 1 and "violet telescope" in seen[0]
        assert "private beta design" not in " ".join(seen)
    finally:
        other.shutdown()
        chat.shutdown()


def test_chat_extraction_rejects_project_context_until_chat_claim_acl_is_fenced(tmp_path, monkeypatch):
    plugin, first = _plugin(tmp_path, monkeypatch)
    first.project_scope = "project-alpha"
    second = _second_project_provider(plugin, tmp_path, "project-beta")
    try:
        alpha = plugin._memory_events.capture_event(
            first, plugin, "Alpha project chat stores the violet telescope.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=first.session_id,
        )
        beta = plugin._memory_events.capture_event(
            second, plugin, "Beta project chat stores the copper telescope.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=second.session_id,
        )
        assert alpha and beta
        assert jobs.enqueue_event(first, "extract_session_events", alpha)
        monkeypatch.setattr(
            plugin, "extract_session_claims",
            lambda *_args, **_kwargs: pytest.fail("project-bound chat evidence reached unfenced chat claim writer"),
        )
        assert jobs.run_once(first, plugin)
        assert first._connect().execute(
            "SELECT COUNT(*) FROM claims WHERE source LIKE 'extractor:%'"
        ).fetchone()[0] == 0
    finally:
        second.shutdown()
        first.shutdown()


@pytest.mark.parametrize("new_scope,new_project", [("bot", ""), ("chat", "project-beta")])
def test_claim_write_fence_rejects_recreated_event_with_changed_acl(
    tmp_path, monkeypatch, new_scope, new_project,
):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        event_id = plugin._memory_events.capture_event(
            provider, plugin, "User prefers the violet telescope in Aurora.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=provider.session_id,
        )
        assert event_id and jobs.enqueue_event(provider, "extract_session_events", event_id)
        persisted = []

        def replace_before_write(exchanges, session_id, *, add_claim_callback, **_kwargs):
            with provider._connect() as conn:
                row = dict(conn.execute(
                    "SELECT * FROM memory_events WHERE event_id=?", (event_id,),
                ).fetchone())
                conn.execute("DELETE FROM memory_events WHERE event_id=?", (event_id,))
                row["visibility_scope"] = new_scope
                row["project_id"] = new_project
                columns = tuple(row)
                conn.execute(
                    "INSERT INTO memory_events(" + ",".join(columns) + ") VALUES(" +
                    ",".join("?" for _ in columns) + ")",
                    tuple(row[column] for column in columns),
                )
            persisted.append(add_claim_callback(
                "User prefers the violet telescope in Aurora.", topic="preferences",
                evidence=json.dumps({
                    "schema": "memory-wiki-extraction-evidence-v1", "session_id": session_id,
                    "speaker": "user", "message_index": 0,
                    "evidence_quote": exchanges[0]["content"],
                    "extractor": "extractor:heuristic",
                }),
                source="extractor:heuristic", confidence=.85, salience=.7,
                visibility_scope="chat",
            ))
            return {"persisted_ids": [], "errors": [], "error": ""}

        monkeypatch.setattr(plugin, "extract_session_claims", replace_before_write)
        assert jobs.run_once(provider, plugin)
        assert persisted == [""]
        assert provider._connect().execute(
            "SELECT COUNT(*) FROM claims WHERE source='extractor:heuristic'"
        ).fetchone()[0] == 0
    finally:
        provider.shutdown()


def test_queued_watermark_survives_vacuum_and_deleted_max_docid(tmp_path, monkeypatch):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        retained = plugin._memory_events.capture_event(
            provider, plugin, "User prefers the retained violet telescope.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=provider.session_id,
        )
        anchor = plugin._memory_events.capture_event(
            provider, plugin, "User prefers the old copper telescope.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=provider.session_id,
        )
        assert retained and anchor
        assert jobs.enqueue_event(provider, "extract_session_events", anchor)
        conn = provider._connect()
        watermark = json.loads(conn.execute(
            "SELECT payload_json FROM memory_jobs WHERE job_type='extract_session_events'"
        ).fetchone()[0])["high_watermark"]
        with conn:
            conn.execute("DELETE FROM memory_events WHERE event_id=?", (anchor,))
        conn.execute("VACUUM")
        newer = plugin._memory_events.capture_event(
            provider, plugin, "User prefers the new gold telescope.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=provider.session_id,
        )
        assert newer
        new_sequence = conn.execute(
            "SELECT docid FROM memory_event_fts_docids WHERE event_id=?", (newer,),
        ).fetchone()[0]
        assert new_sequence > watermark
        seen = []

        def record(exchanges, **_kwargs):
            seen.extend(str(item["content"]) for item in exchanges)
            return {"persisted_ids": [], "errors": [], "error": ""}

        monkeypatch.setattr(plugin, "extract_session_claims", record)
        assert jobs.run_once(provider, plugin)
        assert len(seen) == 1 and "retained violet" in seen[0]
        assert "new gold" not in " ".join(seen)
    finally:
        provider.shutdown()


@pytest.mark.parametrize("background_enabled", [True, False])
def test_logical_restore_rebuilds_only_bounded_id_jobs_from_current_sources(
    tmp_path, monkeypatch, background_enabled,
):
    plugin, provider = _plugin(tmp_path, monkeypatch)
    try:
        deleted = plugin._memory_events.capture_event(
            provider, plugin, "Deleted source must not consume a restored sequence.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=provider.session_id,
        )
        assert deleted
        with provider._connect():
            provider._connect().execute("DELETE FROM memory_events WHERE event_id=?", (deleted,))
        provider.project_scope = "project-alpha"
        alpha = plugin._memory_events.capture_event(
            provider, plugin, "Alpha project uses a violet telescope.",
            event_type="dialogue_turn", role="user", scope="project",
            session_id=provider.session_id,
        )
        provider.project_scope = "project-beta"
        beta = plugin._memory_events.capture_event(
            provider, plugin, "Beta project uses a copper telescope.",
            event_type="dialogue_turn", role="user", scope="project",
            session_id=provider.session_id,
        )
        provider.project_scope = ""
        chat = plugin._memory_events.capture_event(
            provider, plugin, "User prefers the silver telescope.",
            event_type="dialogue_turn", role="user", scope="chat",
            session_id=provider.session_id,
        )
        assert alpha and beta and chat
        assert jobs.enqueue_event(provider, "extract_session_events", chat)
        old_watermark = json.loads(provider._connect().execute(
            "SELECT payload_json FROM memory_jobs WHERE job_type='extract_session_events'"
        ).fetchone()[0])["high_watermark"]
        checkpoint = provider._journal_checkpoint("background-recovery")
        assert "memory_event_fts_docids" not in provider._checkpoint_tables()
        assert "memory_jobs" not in provider._checkpoint_tables()
        monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_RECOVERY_MAX_JOBS", "2")
        if not background_enabled:
            monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
        monkeypatch.setattr(
            plugin, "extract_session_claims",
            lambda *_args, **_kwargs: pytest.fail("remote extraction during restore"),
        )
        rebuilt = provider._rebuild_from_journal(
            apply=True, checkpoint=checkpoint["path"],
        )
        recovery = rebuilt["background_recovery"]
        assert recovery["enabled"] is background_enabled
        assert recovery["scanned"] == (1 if background_enabled else 0)
        conn = provider._connect()
        rows = conn.execute("SELECT job_type,payload_json FROM memory_jobs").fetchall()
        if not background_enabled:
            assert rows == []
            assert recovery["observation_jobs"] == recovery["extraction_jobs"] == 0
            return
        assert len(rows) <= 2
        extraction = [json.loads(row["payload_json"]) for row in rows
                      if row["job_type"] == "extract_session_events"]
        assert len(extraction) == 1
        assert extraction[0]["event_id"] == chat
        new_docid = conn.execute(
            "SELECT docid FROM memory_event_fts_docids WHERE event_id=?", (chat,),
        ).fetchone()[0]
        assert extraction[0]["high_watermark"] == new_docid
        assert new_docid != old_watermark
        assert recovery["extraction_jobs"] == 1
        assert recovery["observation_jobs"] == 1
        assert all(json.loads(row["payload_json"])["event_id"] == chat for row in rows)
        assert all("telescope" not in row["payload_json"] for row in rows)
        assert old_watermark >= 1
    finally:
        provider.shutdown()
