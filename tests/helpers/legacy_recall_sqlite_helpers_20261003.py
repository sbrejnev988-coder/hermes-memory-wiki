"""Tiny real-SQL fixtures for legacy recall contracts, not SDK/ACL substitutes.

Replay only retrieval/ranking. The immutable native helper owns SQLite/schema;
all host identities, authorization helpers, fingerprints and guards stay real.
No initialize/shutdown, migrations, filesystem databases or live I/O.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location(
    "_legacy_native_sqlite_20261003",
    Path(__file__).with_name("audit_native_helpers_20261003.py"),
)
assert _spec and _spec.loader
native = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(native)
plugin = native.plugin
episodes = native.episodes
events = native.events
observations = native.observations


def replay_backend(backend, retrieval):
    """Replace exactly one retrieval entry point, never final-read helpers."""
    names = [name for name in (
        "query_episodes", "query_events", "query_observations",
    ) if hasattr(retrieval, name)]
    assert len(names) == 1
    adapter = SimpleNamespace(**vars(backend))
    setattr(adapter, names[0], getattr(retrieval, names[0]))
    adapter.calls = retrieval.calls
    for name, value in vars(backend).items():
        if name.startswith("_") and callable(value):
            assert getattr(adapter, name) is value
    return adapter


def insert(provider, table, row):
    """Author synthetic rows in an owned :memory: reference-schema database."""
    assert table in {"claims", "relations", "episodic_turns", "memory_events", "contradictions", "memory_observations"}
    columns = ",".join(row)
    placeholders = ",".join("?" for _ in row)
    with provider._connect() as conn:
        conn.execute(
            f"INSERT INTO {table}({columns}) VALUES({placeholders})",
            tuple(row.values()),
        )


def seed_claim(provider, row):
    values = dict(row)
    visible = values.pop("visible", True)
    values.update({
        "normalized_claim": row["claim"], "topic": "legacy_recall",
        "freshness_at": row["updated_at"], "visibility_scope": "chat",
        "origin_bot_id": provider.bot_id if visible else "foreign-legacy-bot",
        "origin_session_id": provider.session_id,
        "origin_chat_hash": provider._chat_hash(provider.session_id),
    })
    identity = provider._claim_visibility_identity_scope(values)
    values["hash"] = plugin.sha(identity + "\0" + plugin.normalize_claim(row["claim"]).lower())
    insert(provider, "claims", values)
    stored = provider._connect().execute(
        "SELECT * FROM claims WHERE id=?", (row["id"],),
    ).fetchone()
    assert provider._claim_visible(stored) is bool(visible)
    return dict(stored)


def replay_claim_queries(provider, monkeypatch, rows_by_query):
    """Deterministic retrieval seam; final claim reads use actual stored rows."""
    snapshots = {}
    for rows in rows_by_query.values():
        for row in rows:
            if row["id"] not in snapshots:
                snapshots[row["id"]] = seed_claim(provider, row)
    provider.search_calls = []

    def search(query, **kwargs):
        provider.search_calls.append((query, kwargs))
        return [dict(snapshots[row["id"]]) for row in rows_by_query.get(query, [])]

    monkeypatch.setattr(provider, "_search", search)


def seed_relation(provider, row, *, source_claim_id):
    values = dict(row)
    visible = values.pop("visible", True)
    values.update({
        "visibility_scope": "chat",
        "origin_bot_id": provider.bot_id if visible else "foreign-legacy-bot",
        "origin_session_id": provider.session_id,
        "origin_chat_hash": provider._chat_hash(provider.session_id),
        "source_claim_id": source_claim_id, "created_at": 10,
        "hash": plugin.sha("\0".join(str(row[key]) for key in ("id", "subject", "predicate", "object"))),
    })
    insert(provider, "relations", values)
    stored = provider._connect().execute(
        "SELECT * FROM relations WHERE id=?", (row["id"],),
    ).fetchone()
    assert provider._graph_row_visible(stored, conn=provider._connect()) is bool(visible)
    return provider._sanitize_row(stored)


def seed_event(provider, row):
    values = dict(row)
    scope = values.pop("scope", "chat")
    principal, selected_scope, project = events._resolve_scope(provider, scope=scope)
    stamp = values.get("created_at", 100)
    values = {
        "role": "assistant", "event_type": "observation", "modality": "text",
        "turn_id": "legacy-turn-" + row["event_id"],
        "occurred_at": stamp, "observed_at": stamp, "created_at": stamp,
        "expires_at": int(time.time()) + 3600,
        "truncated": 0, "source_length": len(row["content"]),
        "content_hash": plugin.sha(row["content"]), **values,
        "owner_bot_id": principal["bot_id"],
        "owner_chat_hash": principal["chat_hash"],
        "owner_session_hash": principal["session_hash"],
        "visibility_scope": selected_scope, "project_id": project,
    }
    insert(provider, "memory_events", values)
    stored = provider._connect().execute(
        "SELECT * FROM memory_events WHERE event_id=?", (row["event_id"],),
    ).fetchone()
    return {**dict(stored), "scope": selected_scope}


def seed_observation(provider, observation_id, event_ids):
    """Use the actual consolidator/version writer; do not invent lineage."""
    conn = provider._connect()
    first = conn.execute(
        "SELECT * FROM memory_events WHERE event_id=?", (event_ids[0],),
    ).fetchone()
    safe = observations._safe_event(provider, plugin, first)
    assert safe is not None
    principal, scope, project = events._resolve_scope(provider, scope="chat")
    stamp = int(time.time())
    # An owned, unversioned head preserves the legacy fixture's public ID.
    # Native consolidation attaches both real events and writes all immutable
    # versions, digests, support counts and confidence before any read/recall.
    insert(provider, "memory_observations", {
        "observation_id": observation_id, "owner_bot_id": principal["bot_id"],
        "owner_chat_hash": principal["chat_hash"],
        "owner_session_hash": principal["session_hash"],
        "visibility_scope": scope, "project_id": project, "topic": safe["topic"],
        "cluster_normalized": safe["normalized"], "cluster_key": safe["cluster_key"],
        "content": safe["content"], "normalized_content": safe["normalized"],
        "content_hash": safe["content_hash"], "representative_event_id": safe["event_id"],
        "created_at": stamp, "updated_at": stamp, "expires_at": safe["expires_at"],
    })
    consolidated = observations.consolidate_events(
        provider, plugin, scope=scope, limit=len(event_ids),
    )
    assert consolidated["events_linked"] == len(event_ids)
    assert consolidated["versions_created"] == 1
    rows = observations.query_observations(provider, plugin, "", 8, scope=scope)["observations"]
    assert len(rows) == 1 and rows[0]["observation_id"] == observation_id
    assert set(rows[0]["evidence_event_ids"]) == set(event_ids)
    return rows[0]


def seed_episode(provider, row):
    bot_id, chat_hash = episodes._identity(provider)
    values = dict(row)
    visible = values.pop("visible", True)
    insert(provider, "episodic_turns", {
        **values, "owner_bot_id": bot_id if visible else "foreign-legacy-bot",
        "owner_chat_hash": chat_hash,
        "visibility_scope": episodes._scope(), "expires_at": int(time.time()) + 3600,
        "truncated": 0, "source_chars": len(row["content"]),
    })
    # This represents an earlier backend read, including deliberately unsafe
    # retrieval responses used to test the facade's unmodified content guard.
    stored = provider._connect().execute(
        "SELECT * FROM episodic_turns WHERE id=?", (row["id"],),
    ).fetchone()
    return {**dict(stored), "content_hash": plugin.sha(stored["content"])}
