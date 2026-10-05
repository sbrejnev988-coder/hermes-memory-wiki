"""Small, offline SQLite fixtures; never replace SDK or authorization methods.

The package must already be loaded by the native isolated runner. This is not
an initialization/migration/lifecycle test. Base DDL comes from the checkout's
reference schema; the three non-claim backends install their actual schemas.
Only synthetic host identity and storage are supplied; ACL, guards, capture,
consolidation, search, fingerprints and final response are production code.
"""
from __future__ import annotations

import contextlib
import importlib
import re
import sqlite3
import sys
from pathlib import Path

import memory_wiki as plugin

recall = plugin._recall_orchestrator
events = plugin._memory_events
episodes = plugin._episodic_memory
observations = plugin._memory_observations
decay = sys.modules[plugin.scan_decay.__module__]
guard = sys.modules[plugin.is_social_close.__module__]

QUERY = "Cedar observatory violet calibration"
TEXT = "The Cedar observatory calibration card is violet."
BOT = "audit-native-bot"
SESSION = "audit-native-chat"
DB_ID = "audit-native-database-20261003"

# Deliberately no complete provider initialize/shutdown, filesystem rendering,
# extraction, live secrets, networking, workers or full database migration.
_BASE_TABLES = {
    "meta", "claims", "claims_fts", "claims_simhash", "evidence",
    "entities", "relations", "memory_consumers", "memory_mutations",
    "recall_events", "recall_feedback", "audit_log", "contradictions",
    "topic_aliases", "index_outbox", "source_artifacts",
}


def schema_path() -> Path:
    paths = [Path(path) / "schema.sql" for path in plugin.__path__]
    return next(path for path in paths if path.is_file())


def configure_offline(monkeypatch) -> None:
    # These are process-local test policies, NOT a change to the user's profile.
    settings = {
        "MEMORY_WIKI_EVENT_LEDGER_ENABLED": "1",
        "MEMORY_WIKI_OBSERVATIONS_ENABLED": "1",
        "MEMORY_WIKI_EVENT_SCOPE": "chat",
        "MEMORY_WIKI_EPISODIC_ENABLED": "1",
        "MEMORY_WIKI_EPISODIC_SCOPE": "chat",
        "MEMORY_WIKI_EPISODIC_SEMANTIC": "0",
        "MEMORY_WIKI_EPISODIC_PREFETCH": "0",
        "MEMORY_WIKI_SEMANTIC": "0",
        "MEMORY_WIKI_RERANK_ENABLED": "0",
        "MEMORY_WIKI_BACKGROUND_JOBS_ENABLED": "0",
        "MEMORY_WIKI_GRAPH_AUTO_EXTRACT": "0",
        "MEMORY_WIKI_REVISION_DELTA_LIMIT": "0",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    assert not plugin.SEMANTIC_ENABLED, "Load the package in an offline native runner"


class NativeConnection(sqlite3.Connection):
    """A genuine supported sqlite3.Connection subclass, not an SQL double."""


@contextlib.contextmanager
def native_provider(*, factory=sqlite3.Connection, channels=True):
    import __main__
    missing = object()
    previous = getattr(__main__, "_memory_wiki_instance", missing)
    provider = plugin.MemoryWikiProvider()
    conn = sqlite3.connect(":memory:", check_same_thread=False, factory=factory)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    provider._conn = conn
    provider.session_id = SESSION
    provider.bot_id = BOT
    provider._bot_scope_trusted = True
    provider.project_scope = "audit-native-project"
    provider.default_visibility = "chat"
    provider.database_instance_id = DB_ID
    try:
        found = set()
        for section in re.split(r"(?m)^-- ", schema_path().read_text(encoding="utf-8")):
            header, _, ddl = section.partition("\n")
            name = header.removeprefix("table: ")
            if header.startswith("table: ") and name in _BASE_TABLES:
                conn.executescript(ddl)
                found.add(name)
        assert found == _BASE_TABLES, "Fixture schema prerequisites changed"
        with conn:
            conn.executemany("INSERT INTO meta(key,value) VALUES(?,?)", [
                ("database_instance_id", DB_ID), ("claims_fts_format", "v3"),
                ("memory_revision", "0"),
            ])
        provider.origin_chat_hash = provider._chat_hash(SESSION)
        if channels:
            events.install_schema(conn)
            episodes.install_schema(conn)
            observations.install_schema(conn)
            conn.commit()
        yield provider
    finally:
        # Own the in-memory resource explicitly; no shutdown/render/lifecycle.
        conn.close()
        provider._conn = None
        if getattr(__main__, "_memory_wiki_instance", missing) is provider:
            if previous is missing:
                del __main__._memory_wiki_instance
            else:
                __main__._memory_wiki_instance = previous


def seed_claim(provider) -> str:
    conn = provider._connect()  # The real provider returns our native connection.
    claim_id = "claim_audit_native_calibration"
    stamp = plugin.now()
    with conn:
        conn.execute("""INSERT INTO claims(
            id,claim,normalized_claim,topic,status,confidence,salience,
            source,evidence,created_at,updated_at,freshness_at,hash,quality,
            visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,
            project_id,scope,trust_class,trust_score)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                claim_id, TEXT, TEXT, "observatory", "active", .8, .8,
                "host:synthetic-audit", "", stamp, stamp, stamp,
                plugin.sha(TEXT), .95, "chat", BOT, SESSION,
                provider._chat_hash(SESSION), "", "global", "fact", .8,
            ))
        conn.execute("""INSERT INTO claims_fts(
            id,claim,normalized,topic,evidence,search_text) VALUES(?,?,?,?,?,?)""", (
                claim_id, "", "", "", "",
                plugin.claim_search_text(TEXT, TEXT, "observatory", ""),
            ))
    row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    assert provider._claim_visible(row)
    assert provider._ensure_fts_current() == "current"
    return claim_id


def seed_nonclaims(provider) -> dict[str, str]:
    claim_id = seed_claim(provider)
    event_ids = [events.capture_event(
        provider, plugin, TEXT, turn_id=f"audit-turn-{index}",
        occurred_at=100 + index, observed_at=100 + index,
        role="observer", event_type="observation", scope="chat",
    ) for index in (1, 2)]
    assert all(event_ids), "Real guarded event capture must succeed"
    episode_id = episodes.capture_turn(
        provider, plugin, "user", TEXT, turn_id="audit-episode-turn",
    )
    assert episode_id, "Real guarded episodic capture must succeed"
    consolidated = observations.consolidate_events(provider, plugin, scope="chat")
    assert consolidated["versions_created"] >= 1
    rows = observations.query_observations(
        provider, plugin, QUERY, scope="chat",
    )["observations"]
    assert len(rows) == 1
    assert rows[0]["support_count"] == rows[0]["independent_support_count"] == 2
    assert set(rows[0]["evidence_event_ids"]) == set(event_ids)
    graph = provider._add_relation({
        "subject": "Cedar observatory", "predicate": "uses_provider",
        "object": "violet calibration card", "evidence": TEXT,
        "confidence": .8, "source_claim_id": claim_id,
    })
    graph_row = provider._connect().execute(
        "SELECT * FROM relations WHERE id=?", (graph["id"],),
    ).fetchone()
    assert provider._graph_row_visible(graph_row, conn=provider._connect())
    return {
        "claim": claim_id, "event": event_ids[0], "support_event": event_ids[1],
        "episode": episode_id, "observation": rows[0]["observation_id"],
        "graph": graph["id"],
    }


def recall_all(provider):
    return recall.recall(
        provider, QUERY, mode="deep", limit=20,
        episodic_backend=episodes, event_backend=events,
        observation_backend=observations, runtime_module=plugin,
    )


def assert_visible(response, ids) -> None:
    keys = {(item["kind"], item["id"]) for item in response["items"]}
    assert {(kind, ids[kind]) for kind in (
        "claim", "event", "episode", "observation", "graph",
    )} <= keys, (keys, response["intent_plan"]["sources"])
    assert response["evidence_count"] == len(response["items"])
    assert response["answer_policy"]["must_abstain_or_clarify"] is False
    assert response["answer_policy"]["allowed_citations"] == [
        item["citation"] for item in response["items"]
    ]
    assert all(not any(key.startswith("_") for key in item)
               for item in response["items"])
    assert response["intent_plan"]["sources"] == {
        "claims": "ok", "episodes": "ok", "events": "ok",
        "observations": "ok", "graph": "ok",
    }
