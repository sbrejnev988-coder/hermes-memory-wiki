"""F05/F06 regressions on the real package and native Hermes SDK.

Run through the owner-approved run_isolated.py --package harness. Cached
retrieval responses below model the earlier adapter read, never authorization:
the actual recall() and final SQLite checks are not replaced or AST-extracted.
All SQLite connections are tiny, in-memory, and fixture-owned; no lifecycle
initialization, live memory, external extraction, or transport is exercised.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent.memory_provider import MemoryProvider
import memory_wiki as plugin


recall_module = plugin._recall_orchestrator


@pytest.fixture
def provider(monkeypatch, tmp_path, request):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MEMORY_WIKI_EVENT_SCOPE", "chat")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_SCOPE", "chat")
    monkeypatch.setenv("MEMORY_WIKI_EVENT_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_EPISODIC_QUERY_MODE", "fast")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATION_EVIDENCE_IDS", "32")
    monkeypatch.setenv("MEMORY_WIKI_OBSERVATION_VERSION_EVIDENCE_MAX", "128")
    main = sys.modules["__main__"]
    monkeypatch.setattr(
        main, "_memory_wiki_instance",
        getattr(main, "_memory_wiki_instance", None), raising=False,
    )
    instance = plugin.MemoryWikiProvider()
    connection = sqlite3.connect(
        ":memory:", factory=getattr(request, "param", sqlite3.Connection),
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
    connection.execute(
        "INSERT INTO meta VALUES('database_instance_id','recall-audit-fixture')"
    )
    instance._conn = connection
    instance.bot_id = "recall-audit-bot"
    instance.session_id = "recall-audit-chat"
    instance.project_scope = "recall-audit-project"
    instance.database_instance_id = "recall-audit-fixture"
    instance._bot_scope_trusted = True
    monkeypatch.setattr(instance, "_search", lambda *_a, **_k: [])
    try:
        yield instance
    finally:
        connection.close()
        instance._conn = None


def _cached_adapters(episodes, events, observations):
    """Only replay retrieval; retain the real final-read adapter helpers."""
    episode_adapter = SimpleNamespace(**vars(plugin._episodic_memory))
    event_adapter = SimpleNamespace(**vars(plugin._memory_events))
    observation_adapter = SimpleNamespace(**vars(plugin._memory_observations))
    episode_adapter.query_episodes = lambda *_a, **_k: {
        "enabled": True, "episodes": episodes,
    }
    event_adapter.enabled = lambda: True
    event_adapter.query_events = lambda *_a, **_k: {"events": events}
    observation_adapter.enabled = lambda: True
    observation_adapter.query_observations = lambda *_a, **_k: {
        "observations": observations,
    }
    return episode_adapter, event_adapter, observation_adapter


def _recall(provider, adapters):
    episodes, events, observations = adapters
    return recall_module.recall(
        provider, "telescope", mode="deep", limit=20,
        episodic_backend=episodes, event_backend=events,
        observation_backend=observations, runtime_module=plugin,
        query_expander=lambda *_a, **_k: ["telescope"],
    )


class _ExecuteOnly:
    def execute(self, *_a, **_k):
        raise AssertionError("unsupported connection must not execute SQL")


class _SQLiteWrapper:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)


@pytest.mark.parametrize("connection_kind", ["none", "object", "execute_only", "wrapper"])
def test_unsupported_connection_leaves_no_nonclaim_snapshot(
    provider, monkeypatch, connection_kind,
):
    text = "Cached telescope evidence marker."
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    episodes = [{
        "id": "ep_cached_marker", "content": text, "role": "user",
        "created_at": 100, "content_hash": digest,
    }]
    events = [{
        "event_id": "evt_cached_marker", "content": text, "scope": "chat",
        "role": "user", "event_type": "observation", "modality": "text",
        "content_hash": digest, "created_at": 101, "expires_at": 9999999999,
    }]
    observations = [{
        "observation_id": "obs_cached_marker", "content": text,
        "topic": "observation", "scope": "chat", "content_hash": digest,
        "evidence_event_ids": ["evt_support_marker"], "support_count": 1,
        "evidence_event_total": 1, "version_id": "ov_cached_marker",
        "evidence_digest": digest,
    }]
    graph = {"entities": [{
        "id": "ent_cached_marker", "name": "Cached telescope", "notes": text,
        "visibility_scope": "global", "source_claim_id": "",
    }], "relations": []}
    monkeypatch.setattr(provider, "_graph_query", lambda *_a, **_k: graph)
    connection = {
        "none": None, "object": object(), "execute_only": _ExecuteOnly(),
        "wrapper": _SQLiteWrapper(provider._conn),
    }[connection_kind]
    monkeypatch.setattr(provider, "_connect", lambda: connection)

    result = _recall(provider, _cached_adapters(episodes, events, observations))

    assert result["intent_plan"]["sources"] == {
        "claims": "ok", "episodes": "ok", "events": "ok",
        "observations": "ok", "graph": "ok",
    }
    assert result["items"] == []
    assert result["evidence_count"] == 0
    assert result["chars_used"] == 0
    assert result["answer_policy"]["allowed_citations"] == []
    assert result["recall_tracking"]["events"] == []
    assert result["recall_tracking"]["answer_linkage"]["claim_ids"] == []
    assert result["recall_tracking"]["answer_linkage"]["recall_event_ids"] == []
    encoded = json.dumps(result, sort_keys=True)
    assert "_snapshot_fingerprint" not in encoded
    assert "_source_id" not in encoded
    assert "cached_marker" not in encoded
    assert "evt_support_marker" not in encoded
    assert text not in encoded


class _IntRaises:
    def __init__(self, error):
        self.error = error

    def __int__(self):
        raise self.error


@pytest.mark.parametrize("value", [
    pytest.param(float("inf"), id="positive_infinity"),
    pytest.param(float("-inf"), id="negative_infinity"),
    pytest.param(_IntRaises(OverflowError("synthetic conversion overflow")), id="int_overflow"),
])
def test_timestamp_overflow_falls_back(value):
    assert recall_module._safe_timestamp(value) == 0


class _SQLiteSubclass(sqlite3.Connection):
    pass


def _insert(connection, table, row):
    columns = ",".join(row)
    placeholders = ",".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO {table}({columns}) VALUES({placeholders})", tuple(row.values()),
    )


@pytest.fixture
def source_snapshot(provider):
    """Real source schemas/adapters, two events, one version, two graph rows.

    The unrelated claim/graph write lifecycle is deliberately not initialized;
    its tiny tables contain just the columns read by native ACL/graph recall.
    """
    connection = provider._connect()
    plugin._memory_events.install_schema(connection)
    plugin._episodic_memory.install_schema(connection)
    plugin._memory_observations.install_schema(connection)
    connection.executescript("""
        CREATE TABLE claims(
            id TEXT PRIMARY KEY,claim TEXT,evidence TEXT,visibility_scope TEXT,
            origin_bot_id TEXT,origin_session_id TEXT,origin_chat_hash TEXT,
            project_id TEXT,status TEXT,risk TEXT,quarantined_at INTEGER,
            temporal_status TEXT,valid_from INTEGER,valid_to INTEGER,
            created_at INTEGER,updated_at INTEGER
        );
        CREATE TABLE entities(
            id TEXT PRIMARY KEY,name TEXT,entity_type TEXT,aliases TEXT,notes TEXT,
            updated_at INTEGER,hash TEXT,visibility_scope TEXT,origin_bot_id TEXT,
            origin_session_id TEXT,origin_chat_hash TEXT,project_id TEXT,
            source_claim_id TEXT,valid_from INTEGER,valid_to INTEGER
        );
        CREATE TABLE relations(
            id TEXT PRIMARY KEY,subject TEXT,predicate TEXT,object TEXT,
            confidence REAL,evidence TEXT,created_at INTEGER,hash TEXT,
            subject_id TEXT,object_id TEXT,source_ref TEXT,visibility_scope TEXT,
            origin_bot_id TEXT,origin_session_id TEXT,origin_chat_hash TEXT,
            project_id TEXT,source_claim_id TEXT,valid_from INTEGER,valid_to INTEGER
        );
    """)
    principal, _, project = plugin._memory_events._resolve_scope(provider, scope="chat")
    stamp = int(time.time())
    text = "Synthetic telescope lens is violet."
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for index, event_id in enumerate(("evt_telescope_one", "evt_telescope_two")):
        _insert(connection, "memory_events", {
            "event_id": event_id, "owner_bot_id": principal["bot_id"],
            "owner_chat_hash": principal["chat_hash"],
            "owner_session_hash": principal["session_hash"],
            "visibility_scope": "chat", "project_id": project,
            "turn_id": f"telescope-turn-{index}", "role": "assistant",
            "event_type": "observation", "modality": "text", "content": text,
            "content_hash": digest, "source_length": len(text),
            "occurred_at": stamp - 10 + index, "observed_at": stamp - 10 + index,
            "created_at": stamp - 10 + index, "expires_at": stamp + 3600,
        })
    consolidated = plugin._memory_observations.consolidate_events(
        provider, plugin, scope="chat", limit=2,
    )
    assert consolidated["events_linked"] == 2
    assert consolidated["versions_created"] == 1
    episode_text = "Synthetic telescope arrived yesterday."
    _insert(connection, "episodic_turns", {
        "id": "ep_telescope", "content": episode_text, "role": "user",
        "owner_bot_id": principal["bot_id"],
        "owner_chat_hash": principal["chat_hash"], "visibility_scope": "chat",
        "created_at": stamp - 20, "expires_at": stamp + 3600,
        "source_chars": len(episode_text),
    })
    owner = {
        "visibility_scope": "chat", "origin_bot_id": provider.bot_id,
        "origin_session_id": provider.session_id,
        "origin_chat_hash": principal["chat_hash"], "project_id": project,
    }
    _insert(connection, "claims", {
        "id": "cl_telescope_anchor", "claim": "Telescope uses a violet lens.",
        "evidence": "", **owner, "status": "active", "risk": "low",
        "quarantined_at": 0, "temporal_status": "current",
        "valid_from": 0, "valid_to": 0, "created_at": stamp - 30,
        "updated_at": stamp - 30,
    })
    graph_owner = {
        **owner, "source_claim_id": "cl_telescope_anchor",
        "valid_from": 0, "valid_to": 0, "hash": digest,
    }
    _insert(connection, "entities", {
        "id": "ent_telescope", "name": "Telescope", "entity_type": "instrument",
        "aliases": "[]", "notes": "The synthetic telescope is calibrated.",
        "updated_at": stamp - 15, **graph_owner,
    })
    _insert(connection, "relations", {
        "id": "rel_telescope", "subject": "Telescope", "predicate": "uses",
        "object": "Violet lens", "confidence": 0.7,
        "evidence": "Synthetic calibration report.", "created_at": stamp - 15,
        "subject_id": "ent_telescope", "object_id": "", "source_ref": "",
        **graph_owner,
    })
    connection.commit()
    episodes = plugin._episodic_memory.query_episodes(provider, plugin, "telescope", 5)["episodes"]
    events = plugin._memory_events.query_events(provider, plugin, "telescope", 12)["events"]
    observations = plugin._memory_observations.query_observations(
        provider, plugin, "telescope", 8,
    )["observations"]
    graph = provider._graph_query("telescope", 20)
    assert len(episodes) == 1
    assert len(events) == 2
    assert len(observations) == 1
    assert len(graph["entities"]) == len(graph["relations"]) == 1
    return {"episodes": episodes, "events": events, "observations": observations, "graph": graph}


def test_real_package_native_sdk_loaded(provider):
    assert isinstance(provider, MemoryProvider)
    assert plugin.MemoryProvider is MemoryProvider
    assert MemoryProvider.__module__ == "agent.memory_provider"
    assert Path(plugin.__file__).name == "__init__.py"
    assert Path(recall_module.__file__).resolve() == (
        Path(__file__).resolve().parents[1] / "recall_orchestrator.py"
    )
    assert plugin._memory_events.__name__ == "memory_wiki.memory_events"
    assert provider._connect() is provider._conn
    assert isinstance(provider._connect(), sqlite3.Connection)


@pytest.mark.parametrize("provider", [sqlite3.Connection, _SQLiteSubclass], indirect=True)
def test_real_sqlite_revalidates_all_channels_without_closing_provider(
    provider, source_snapshot,
):
    connection = provider._connect()
    statements = []
    connection.set_trace_callback(statements.append)
    try:
        result = _recall(provider, (
            plugin._episodic_memory, plugin._memory_events,
            plugin._memory_observations,
        ))
    finally:
        connection.set_trace_callback(None)
    expected = {
        "evt_telescope_one", "evt_telescope_two", "ep_telescope",
        "ent_telescope", "rel_telescope",
        source_snapshot["observations"][0]["observation_id"],
    }
    assert {item["id"] for item in result["items"]} == expected
    assert {item["kind"] for item in result["items"]} == {
        "event", "episode", "observation", "graph",
    }
    assert result["evidence_count"] == len(expected)
    assert result["chars_used"] == sum(len(item["content"]) for item in result["items"])
    assert result["answer_policy"]["allowed_citations"] == [
        item["citation"] for item in result["items"]
    ]
    assert all(not key.startswith("_") for item in result["items"] for key in item)
    final_start = next(index for index, sql in enumerate(statements) if sql.startswith("SAVEPOINT memory_wiki_unified_final_"))
    final_sql = statements[final_start:]
    for table in (
        "memory_events", "episodic_turns", "memory_observations",
        "memory_observation_versions", "memory_observation_events",
        "memory_observation_version_events", "entities", "relations", "claims",
    ):
        assert any(f"FROM {table}" in sql or f"JOIN {table}" in sql for sql in final_sql), table
    assert any(sql.startswith("RELEASE memory_wiki_unified_final_") for sql in final_sql)
    assert not connection.in_transaction
    assert connection.execute("SELECT 1").fetchone()[0] == 1


def _candidates(snapshot):
    candidates = []
    for rows, kind, id_field, fingerprint in (
        (snapshot["events"], "event", "event_id", recall_module._event_snapshot_fingerprint),
        (snapshot["episodes"], "episode", "id", recall_module._episode_snapshot_fingerprint),
        (snapshot["observations"], "observation", "observation_id", recall_module._observation_snapshot_fingerprint),
    ):
        for row in rows:
            candidates.append({
                "kind": kind, "_source_id": row[id_field],
                "_snapshot_fingerprint": fingerprint(row),
            })
    for graph_kind, key in (("entity", "entities"), ("relation", "relations")):
        for row in snapshot["graph"][key]:
            candidates.append({
                "kind": "graph", "graph_kind": graph_kind, "_source_id": row["id"],
                "_snapshot_fingerprint": recall_module._graph_snapshot_fingerprint(graph_kind, row),
            })
    return candidates


def _final(provider, candidates, *, event_scope="chat"):
    return recall_module._final_visible_nonclaims(
        provider, candidates, episodic_backend=plugin._episodic_memory,
        event_backend=plugin._memory_events,
        observation_backend=plugin._memory_observations,
        event_scope=event_scope, runtime_module=plugin,
    )


@pytest.mark.parametrize("identity_field", ["bot_id", "session_id"])
def test_final_read_rechecks_current_host_principal(
    provider, source_snapshot, monkeypatch, identity_field,
):
    candidates = _candidates(source_snapshot)
    assert _final(provider, candidates) == {
        recall_module._candidate_identity(item) for item in candidates
    }
    monkeypatch.setattr(provider, identity_field, "foreign-owner")
    assert _final(provider, candidates) == set()
    assert provider._connect().execute("SELECT 1").fetchone()[0] == 1


@pytest.mark.parametrize("scope", ["chat", "bot", "project"])
def test_event_sql_ownership_is_applied_before_accepting_fingerprint(
    provider, source_snapshot, scope,
):
    connection = provider._connect()
    template = dict(connection.execute(
        "SELECT * FROM memory_events WHERE event_id='evt_telescope_one'"
    ).fetchone())
    rows = []
    for suffix in ("allowed", "foreign_bot", "foreign_partition"):
        row = {**template, "event_id": "evt_acl_" + suffix, "visibility_scope": scope}
        if suffix == "foreign_bot":
            row["owner_bot_id"] = "foreign-bot"
        if suffix == "foreign_partition":
            if scope == "project":
                row["project_id"] = "foreign-project"
            elif scope == "chat":
                row["owner_session_hash"] = "foreign-session-hash"
            else:
                row["visibility_scope"] = "chat"
        _insert(connection, "memory_events", row)
        rows.append(row)
    connection.commit()
    candidates = [{
        "kind": "event", "_source_id": row["event_id"],
        "_snapshot_fingerprint": recall_module._event_snapshot_fingerprint(row),
    } for row in rows]
    assert _final(provider, candidates, event_scope=scope) == {
        ("event", "evt_acl_allowed", ""),
    }


@pytest.mark.parametrize("mutation", [
    "missing_version", "missing_support_link", "missing_version_link",
    "wrong_support_count", "source_hash_mismatch", "source_acl_changed",
])
def test_observation_lineage_is_rehydrated_not_trusted_from_cache(
    provider, source_snapshot, mutation,
):
    candidates = [item for item in _candidates(source_snapshot) if item["kind"] == "observation"]
    expected = {recall_module._candidate_identity(item) for item in candidates}
    assert _final(provider, candidates) == expected
    connection = provider._connect()
    observation_id = source_snapshot["observations"][0]["observation_id"]
    if mutation == "missing_version":
        connection.execute("UPDATE memory_observations SET current_version_id='missing-version'")
    elif mutation == "missing_support_link":
        connection.execute("DELETE FROM memory_observation_events WHERE event_id='evt_telescope_one'")
    elif mutation == "missing_version_link":
        connection.execute("DELETE FROM memory_observation_version_events WHERE event_id='evt_telescope_one'")
    elif mutation == "wrong_support_count":
        connection.execute("UPDATE memory_observations SET support_count=3")
    else:
        # Corrupt only this synthetic authority to model a tampered/restored
        # source. The production append-only writer and live policy are untouched.
        connection.execute("DROP TRIGGER memory_events_no_update")
        if mutation == "source_hash_mismatch":
            connection.execute("UPDATE memory_events SET content='Changed synthetic content.' WHERE event_id='evt_telescope_one'")
        else:
            connection.execute("UPDATE memory_events SET owner_session_hash='foreign-session-hash' WHERE event_id='evt_telescope_one'")
    connection.commit()
    assert connection.execute(
        "SELECT 1 FROM memory_observations WHERE observation_id=?", (observation_id,),
    ).fetchone() is not None
    assert _final(provider, candidates) == set()
    assert connection.execute("SELECT 1").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", [
    "deleted", "foreign_owner", "retired", "secret", "quarantined",
    "superseded", "expired",
])
def test_graph_requires_current_admissible_source_claim(
    provider, source_snapshot, mutation,
):
    candidates = [item for item in _candidates(source_snapshot) if item["kind"] == "graph"]
    assert _final(provider, candidates) == {
        recall_module._candidate_identity(item) for item in candidates
    }
    connection = provider._connect()
    statements = {
        "deleted": "DELETE FROM claims",
        "foreign_owner": "UPDATE claims SET origin_bot_id='foreign-bot'",
        "retired": "UPDATE claims SET status='retired'",
        "secret": "UPDATE claims SET risk='secret'",
        "quarantined": "UPDATE claims SET quarantined_at=1",
        "superseded": "UPDATE claims SET temporal_status='superseded'",
        "expired": "UPDATE claims SET valid_to=1",
    }
    connection.execute(statements[mutation])
    connection.commit()
    assert _final(provider, candidates) == set()
    assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 1


@pytest.mark.parametrize("channel", ["event", "episode", "observation", "entity", "relation"])
def test_changed_source_is_dropped_while_other_snapshots_survive(
    provider, source_snapshot, channel,
):
    candidates = _candidates(source_snapshot)
    before = _final(provider, candidates)
    assert len(before) == len(candidates)
    connection = provider._connect()
    statements = {
        "event": "UPDATE memory_events SET content_hash='" + "0" * 64 + "' WHERE event_id='evt_telescope_one'",
        "episode": "UPDATE episodic_turns SET content='Changed synthetic episode.'",
        "observation": "UPDATE memory_observations SET content='Changed synthetic observation.'",
        "entity": "UPDATE entities SET notes='Changed synthetic entity.'",
        "relation": "UPDATE relations SET evidence='Changed synthetic relation.'",
    }
    if channel == "event":
        connection.execute("DROP TRIGGER memory_events_no_update")
    connection.execute(statements[channel])
    connection.commit()
    after = _final(provider, candidates)
    affected = {
        "event": {("event", "evt_telescope_one", ""), ("observation", source_snapshot["observations"][0]["observation_id"], "")},
        "episode": {("episode", "ep_telescope", "")},
        "observation": {("observation", source_snapshot["observations"][0]["observation_id"], "")},
        "entity": {("graph", "ent_telescope", "entity")},
        "relation": {("graph", "rel_telescope", "relation")},
    }[channel]
    assert after == before - affected
    assert connection.execute("SELECT 1").fetchone()[0] == 1


@pytest.mark.parametrize("channel", ["event", "episode", "observation", "entity", "relation", "anchor"])
def test_deletion_after_retrieval_cannot_leave_citations_or_support_metadata(
    provider, source_snapshot, monkeypatch, channel,
):
    connection = provider._connect()
    ids = {
        "event": "evt_telescope_one", "episode": "ep_telescope",
        "observation": source_snapshot["observations"][0]["observation_id"],
        "entity": "ent_telescope", "relation": "rel_telescope",
        "anchor": "cl_telescope_anchor",
    }
    table, id_field = {
        "event": ("memory_events", "event_id"), "episode": ("episodic_turns", "id"),
        "observation": ("memory_observations", "observation_id"),
        "entity": ("entities", "id"), "relation": ("relations", "id"),
        "anchor": ("claims", "id"),
    }[channel]
    baseline = _recall(provider, (
        plugin._episodic_memory, plugin._memory_events, plugin._memory_observations,
    ))
    assert baseline["evidence_count"] == 6
    original_guard = provider._inspect_recall_text
    deleted = False

    def deleting_guard(text, **kwargs):
        nonlocal deleted
        checked = original_guard(text, **kwargs)
        if kwargs.get("source") == "unified_recall:graph" and kwargs.get("item_id") == "ent_telescope":
            connection.execute(f"DELETE FROM {table} WHERE {id_field}=?", (ids[channel],))
            connection.commit()
            deleted = True
        return checked

    monkeypatch.setattr(provider, "_inspect_recall_text", deleting_guard)
    result = _recall(provider, (
        plugin._episodic_memory, plugin._memory_events, plugin._memory_observations,
    ))
    assert deleted
    assert connection.execute(f"SELECT 1 FROM {table} WHERE {id_field}=?", (ids[channel],)).fetchone() is None
    assert result["items"]
    encoded = json.dumps(result, sort_keys=True)
    assert ids[channel] not in encoded
    if channel == "anchor":
        assert all(item["kind"] != "graph" for item in result["items"])
    if channel == "event":
        assert all(item["kind"] != "observation" for item in result["items"])
    assert "_snapshot_fingerprint" not in encoded
    assert "_source_id" not in encoded
    assert result["evidence_count"] == len(result["items"])
    assert result["chars_used"] == sum(len(item["content"]) for item in result["items"])
    assert result["answer_policy"]["allowed_citations"] == [item["citation"] for item in result["items"]]
    assert connection.execute("SELECT 1").fetchone()[0] == 1


def test_sqlite_read_error_discards_partial_final_snapshot(provider, source_snapshot):
    connection = provider._connect()
    candidates = _candidates(source_snapshot)
    assert len(_final(provider, candidates)) == len(candidates)

    def deny_version_links(action, table, _column, _database, _trigger):
        if action == sqlite3.SQLITE_READ and table == "memory_observation_version_events":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(deny_version_links)
    try:
        assert _final(provider, candidates) == set()
    finally:
        connection.set_authorizer(None)
    assert not connection.in_transaction
    assert connection.execute("SELECT 1").fetchone()[0] == 1


def test_closed_sqlite_connection_is_not_authoritative(provider, source_snapshot):
    candidates = _candidates(source_snapshot)
    assert len(_final(provider, candidates)) == len(candidates)
    provider._connect().close()
    assert _final(provider, candidates) == set()


def test_connection_failure_exposes_no_nonclaim_snapshot(provider, source_snapshot, monkeypatch):
    candidates = _candidates(source_snapshot)

    def unavailable():
        raise RuntimeError("synthetic private database failure")

    monkeypatch.setattr(provider, "_connect", unavailable)
    assert _final(provider, candidates) == set()


def test_empty_nonclaims_do_not_open_connection(provider, monkeypatch):
    def unexpected():
        raise AssertionError("empty candidates must not connect")

    monkeypatch.setattr(provider, "_connect", unexpected)
    assert _final(provider, []) == set()


@pytest.mark.parametrize("value, expected", [
    (None, 0), ("", 0), (0, 0), (False, 0), (True, 1), (-7, 0),
    (-7.9, 0), (7.9, 7), ("7", 7), (" 7 ", 7), ("not-a-date", 0),
    ("7.9", 0), (float("nan"), 0), (object(), 0), (10 ** 100, 10 ** 100),
    (_IntRaises(TypeError("bad conversion")), 0),
    (_IntRaises(ValueError("bad conversion")), 0),
])
def test_timestamp_existing_conversion_contract(value, expected):
    actual = recall_module._safe_timestamp(value)
    assert actual == expected
    assert type(actual) is int


@pytest.mark.parametrize("error", [
    RuntimeError("not a conversion error"), OSError("not a conversion error"),
    AssertionError("not a conversion error"), KeyboardInterrupt(), SystemExit(2),
])
def test_timestamp_unrelated_errors_propagate(error):
    with pytest.raises(type(error)) as caught:
        recall_module._safe_timestamp(_IntRaises(error))
    assert caught.value is error


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
@pytest.mark.parametrize("fingerprint, field", [
    (recall_module._event_snapshot_fingerprint, "occurred_at"),
    (recall_module._episode_snapshot_fingerprint, "created_at"),
    (recall_module._observation_snapshot_fingerprint, "last_seen"),
    (lambda row: recall_module._graph_snapshot_fingerprint("relation", row), "valid_from"),
])
def test_real_source_fingerprint_callers_use_timestamp_fallback(fingerprint, field, value):
    assert fingerprint({field: value}) == fingerprint({field: 0})


def test_recall_timestamp_metadata_survives_sqlite_infinities(
    provider, source_snapshot, monkeypatch,
):
    connection = provider._connect()
    connection.execute(
        "UPDATE claims SET created_at=?,updated_at=?", (float("inf"), float("-inf")),
    )
    connection.commit()
    monkeypatch.setattr(provider, "_search", lambda *_a, **_k: [
        dict(connection.execute("SELECT * FROM claims").fetchone()),
    ])
    result = recall_module.recall(
        provider, "telescope", mode="fast", query_expander=lambda *_a, **_k: ["telescope"],
    )
    assert [item["id"] for item in result["items"]] == ["cl_telescope_anchor"]
    assert result["items"][0]["timestamps"] == {"event_at": 0, "created_at": 0, "updated_at": 0}
    assert result["evidence_count"] == 1
    assert connection.execute("SELECT 1").fetchone()[0] == 1
