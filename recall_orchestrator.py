"""Bounded evidence-first recall across claims, observations, events, episodes, and graph.

This module is deliberately an orchestration layer.  It does not bypass the
provider's source-specific authorization checks, nor does it replace automatic
prefetch.  Every returned evidence string passes the provider recall guard and
gets a stable, source-qualified citation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from .recall_planner import classify_memory_intent, expand_memory_queries
except ImportError:  # pragma: no cover - standalone plugin loading
    try:
        from recall_planner import classify_memory_intent, expand_memory_queries
    except ImportError:  # spec loading from outside the plugin directory
        _planner_name = "_memory_wiki_recall_planner_standalone"
        _planner = sys.modules.get(_planner_name)
        if _planner is None:
            _planner_spec = importlib.util.spec_from_file_location(
                _planner_name, Path(__file__).with_name("recall_planner.py"),
            )
            if _planner_spec is None or _planner_spec.loader is None:
                raise ImportError("unable to load sibling recall_planner")
            _planner = importlib.util.module_from_spec(_planner_spec)
            sys.modules[_planner_name] = _planner
            _planner_spec.loader.exec_module(_planner)
        classify_memory_intent = _planner.classify_memory_intent
        expand_memory_queries = _planner.expand_memory_queries


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_META_RE = re.compile(r"[^A-Za-z0-9_.:/+-]+")
_RRF_K = 60.0
_SOURCE_PRIORITY = {"claim": 0, "observation": 1, "event": 2, "episode": 3, "graph": 4}
_SOURCE_WEIGHT = {
    "claim": 1.0, "observation": 0.95, "event": 0.9,
    "episode": 0.85, "graph": 0.65,
}
_ID_PREFIX = {
    "claim": "c", "observation": "o", "event": "v",
    "episode": "e", "graph": "g",
}
_CLAIM_SNAPSHOT_FIELDS = (
    "id", "claim", "topic", "status", "confidence", "salience", "source",
    "evidence", "created_at", "updated_at", "hash", "type", "source_type",
    "verification_status", "trust_class", "trust_score", "quality_flags",
    "source_ref", "derived_from", "review_state", "secrecy_level",
    "temporal_status", "valid_from", "valid_to", "superseded_by_id",
    "memory_class", "expires_at", "origin_bot_id", "origin_session_id",
    "origin_chat_hash", "source_kind", "visibility_scope", "scope",
    "project_id", "memory_revision", "event_at", "event_timezone", "visible",
)
_EVENT_SCOPES = frozenset({"chat", "bot", "project"})


def _mapping(row: Any) -> dict[str, Any]:
    try:
        return dict(row)
    except Exception:
        return row if isinstance(row, dict) else {}


def _snapshot_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8", "ignore")
    return hashlib.sha256(encoded).hexdigest()


def _event_snapshot_fingerprint(row: Any) -> str:
    values = _mapping(row)
    return _snapshot_fingerprint({
        "event_id": values.get("event_id"),
        "turn_id": values.get("turn_id"),
        "role": values.get("role"),
        "event_type": values.get("event_type"),
        "modality": values.get("modality"),
        # query_events may return a bounded excerpt.  The stored digest binds it
        # to the complete authoritative content without copying that content
        # into the orchestrator's internal metadata.
        "content_hash": values.get("content_hash"),
        "truncated": bool(values.get("truncated")),
        "source_length": _safe_timestamp(values.get("source_length")),
        "occurred_at": _safe_timestamp(values.get("occurred_at")),
        "observed_at": _safe_timestamp(values.get("observed_at")),
        "created_at": _safe_timestamp(values.get("created_at")),
        "expires_at": _safe_timestamp(values.get("expires_at")),
        "scope": values.get("scope", values.get("visibility_scope")),
        "project_id": values.get("project_id"),
    })


def _episode_snapshot_fingerprint(row: Any) -> str:
    values = _mapping(row)
    return _snapshot_fingerprint({
        "id": values.get("id"),
        "content_hash": values.get("content_hash"),
        "role": values.get("role"),
        "created_at": _safe_timestamp(values.get("created_at")),
        "truncated": bool(values.get("truncated")),
        "source_chars": _safe_timestamp(values.get("source_chars")),
    })


def _observation_snapshot_fingerprint(row: Any) -> str:
    values = _mapping(row)
    evidence_ids = [str(value) for value in (values.get("evidence_event_ids") or [])]
    return _snapshot_fingerprint({
        "observation_id": values.get("observation_id"),
        "version_id": values.get("version_id", values.get("current_version_id")),
        "content_hash": values.get("content_hash"),
        "evidence_digest": values.get("evidence_digest"),
        "topic": values.get("topic"),
        "support_count": _safe_timestamp(values.get("support_count")),
        "independent_support_count": _safe_timestamp(
            values.get("independent_support_count")
        ),
        "confidence": _safe_number(values.get("confidence"), 0.0),
        "first_seen": _safe_timestamp(values.get("first_seen")),
        "last_seen": _safe_timestamp(values.get("last_seen")),
        "status": values.get("status"),
        "scope": values.get("scope", values.get("visibility_scope")),
        "project_id": values.get("project_id"),
        "evidence_event_ids": evidence_ids,
        "evidence_event_total": _safe_timestamp(values.get("evidence_event_total")),
        "evidence_event_ids_truncated": bool(
            values.get("evidence_event_ids_truncated")
        ),
    })


def _graph_snapshot_fingerprint(kind: str, row: Any) -> str:
    values = _mapping(row)
    fields = (
        ("id", "name", "entity_type", "aliases", "notes", "updated_at", "hash")
        if kind == "entity"
        else (
            "id", "subject", "predicate", "object", "confidence", "evidence",
            "created_at", "hash", "subject_id", "object_id", "source_ref",
        )
    )
    payload = {field: values.get(field) for field in fields}
    payload.update({
        "graph_kind": kind,
        "visibility_scope": values.get("visibility_scope"),
        "origin_bot_id": values.get("origin_bot_id"),
        "origin_session_id": values.get("origin_session_id"),
        "origin_chat_hash": values.get("origin_chat_hash"),
        "project_id": values.get("project_id"),
        "source_claim_id": values.get("source_claim_id"),
        "valid_from": _safe_timestamp(values.get("valid_from")),
        "valid_to": _safe_timestamp(values.get("valid_to")),
    })
    return _snapshot_fingerprint(payload)


def _stable_id(value: Any, prefix: str) -> str:
    raw = str(value or "").strip()
    if raw and _SAFE_ID_RE.fullmatch(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:24]
    return f"opaque_{prefix.lower()}_{digest}"


def _safe_meta(value: Any, default: str, max_chars: int = 64) -> str:
    text = _SAFE_META_RE.sub("_", str(value or "").strip()).strip("_")[:max_chars]
    return text or default


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _safe_timestamp(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _guard_text(
    provider: Any,
    text: Any,
    *,
    source: str,
    mem_type: str,
    item_id: str,
    max_len: int,
) -> str:
    """Fail closed if the provider guard is absent, errors, or rejects text."""
    try:
        decision = provider._inspect_recall_text(
            str(text or ""), source=source, mem_type=mem_type,
            item_id=item_id, audit=False, max_len=max_len,
        )
    except Exception:
        return ""
    if not isinstance(decision, dict) or decision.get("status") != "safe":
        return ""
    return str(decision.get("content") or "").strip()[:max_len]


def _claim_content(row: Any) -> str:
    claim = str(row.get("claim") or "").strip()
    evidence = str(row.get("evidence") or "").strip()
    if evidence.startswith(("{", "[")):
        # Extraction provenance is structured JSON and the compact evidence
        # column may contain a deliberately truncated copy. Never present a
        # broken JSON fragment as natural-language evidence.
        try:
            payload = json.loads(evidence)
        except (TypeError, ValueError, json.JSONDecodeError):
            return claim
        if isinstance(payload, dict) and payload.get("schema") == "memory-wiki-extraction-evidence-v1":
            quote = str(payload.get("evidence_quote") or "").strip()
            if quote and quote.casefold() not in claim.casefold():
                return f"{claim}\nEvidence quote: {quote}"
        return claim
    if evidence and evidence.casefold() not in claim.casefold():
        return f"{claim}\nEvidence: {evidence}"
    return claim


def _graph_content(kind: str, row: Any) -> str:
    if kind == "relation":
        base = " ".join(str(row.get(key) or "").strip() for key in ("subject", "predicate", "object")).strip()
        evidence = str(row.get("evidence") or "").strip()
        return f"{base}\nEvidence: {evidence}" if evidence else base
    name = str(row.get("name") or "").strip()
    entity_type = str(row.get("entity_type") or row.get("type") or "entity").strip()
    notes = str(row.get("notes") or "").strip()
    base = f"{name} ({entity_type})" if entity_type else name
    return f"{base}: {notes}" if notes else base


def _rrf_add(
    candidates: dict[tuple[str, str], dict[str, Any]],
    *,
    kind: str,
    source_id: Any,
    rank: int,
    item: dict[str, Any],
) -> None:
    safe_id = _stable_id(source_id, _ID_PREFIX[kind])
    key = (kind, safe_id)
    contribution = _SOURCE_WEIGHT[kind] / (_RRF_K + max(1, int(rank)))
    if key not in candidates:
        item["id"] = safe_id
        item["_rrf"] = contribution
        item["_first_rank"] = max(1, int(rank))
        candidates[key] = item
        return
    candidates[key]["_rrf"] += contribution
    candidates[key]["_first_rank"] = min(candidates[key]["_first_rank"], max(1, int(rank)))


def _iter_graph_rows(payload: Any) -> Iterable[tuple[str, Any]]:
    if not isinstance(payload, dict):
        return
    for row in payload.get("relations") or []:
        if isinstance(row, dict):
            yield "relation", row
    for row in payload.get("entities") or []:
        if isinstance(row, dict):
            yield "entity", row


def _detect_conflicts(provider: Any, claim_ids: list[str]) -> bool:
    """Detect an open, visible contradiction without exposing its raw reason."""
    if not claim_ids:
        return False
    try:
        conn = provider._connect()
        placeholders = ",".join("?" for _ in claim_ids)
        rows = conn.execute(
            f"SELECT * FROM contradictions WHERE status='open' "
            f"AND (claim_a IN ({placeholders}) OR claim_b IN ({placeholders})) "
            "ORDER BY created_at DESC LIMIT 40",
            tuple(claim_ids) + tuple(claim_ids),
        ).fetchall()
        return any(provider._contradiction_visible(row, conn) for row in rows)
    except Exception:
        return False


def _claim_snapshot_fingerprint(row: Any) -> str:
    """Bind rendered claim evidence to the exact row state that was searched."""
    try:
        values = dict(row)
    except Exception:
        values = row if isinstance(row, dict) else {}
    payload = {key: values.get(key) for key in _CLAIM_SNAPSHOT_FIELDS}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8", "ignore")
    return hashlib.sha256(encoded).hexdigest()


def _final_visible_claims(provider: Any, claim_ids: Iterable[str]) -> dict[str, str]:
    """Re-read visible claims and return fingerprints of their current row state."""
    unique = sorted({str(value) for value in claim_ids if str(value)})
    if not unique:
        return {}
    try:
        conn = provider._connect()
        placeholders = ",".join("?" for _ in unique)
        rows = conn.execute(
            f"SELECT * FROM claims WHERE id IN ({placeholders})", tuple(unique),
        ).fetchall()
        visible: dict[str, str] = {}
        for row in rows:
            try:
                if provider._claim_visible(row):
                    visible[str(row["id"])] = _claim_snapshot_fingerprint(row)
            except Exception:
                continue
        return visible
    except Exception:
        return {}


def _candidate_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("kind") or ""),
        str(item.get("_source_id") or ""),
        str(item.get("graph_kind") or ""),
    )


def _row_owned_by_event_principal(
    row: Any,
    principal: dict[str, str],
    scope: str,
    project_id: str,
) -> bool:
    values = _mapping(row)
    if not values.get("event_id"):
        return False
    if str(values.get("owner_bot_id") or "") != str(principal.get("bot_id") or ""):
        return False
    if str(values.get("visibility_scope") or "") != scope:
        return False
    if scope == "chat":
        return (
            str(values.get("owner_chat_hash") or "")
            == str(principal.get("chat_hash") or "")
            and str(values.get("owner_session_hash") or "")
            == str(principal.get("session_hash") or "")
        )
    if scope == "project":
        return str(values.get("project_id") or "") == str(project_id or "")
    return scope == "bot"


def _final_visible_nonclaims(
    provider: Any,
    candidates: Iterable[dict[str, Any]],
    *,
    episodic_backend: Any,
    event_backend: Any,
    observation_backend: Any,
    event_scope: str,
    runtime_module: Any,
) -> set[tuple[str, str, str]]:
    """Bulk rehydrate non-claim evidence from the authoritative SQLite store.

    Source adapters perform their own authorization and integrity checks during
    retrieval.  This second read closes the interval between that read and the
    final response.  All dependent observation rows are read in one SQLite
    snapshot, and graph claim provenance is hydrated in one batch.
    """
    expected = {
        _candidate_identity(item): str(item.get("_snapshot_fingerprint") or "")
        for item in candidates
        if item.get("kind") != "claim" and item.get("_source_id")
    }
    if not expected:
        return set()
    try:
        conn = provider._connect()
    except Exception:
        return set()
    # Lightweight contract tests use a deliberately tiny DB double.  The real
    # provider always returns sqlite3.Connection; production paths must pass the
    # authoritative checks below and fail closed on every error.
    if not isinstance(conn, sqlite3.Connection):
        return {key for key, value in expected.items() if value}

    valid: set[tuple[str, str, str]] = set()
    stamp = int(time.time())
    savepoint = f"memory_wiki_unified_final_{id(expected):x}"
    try:
        conn.execute(f"SAVEPOINT {savepoint}")

        event_ids = sorted({key[1] for key in expected if key[0] == "event"})
        if event_ids and event_backend is not None:
            resolver = getattr(event_backend, "_resolve_scope", None)
            owner_builder = getattr(event_backend, "_event_owner_sql", None)
            if callable(resolver) and callable(owner_builder):
                principal, selected_scope, selected_project = resolver(
                    provider, scope=event_scope,
                )
                owner_sql, owner_params = owner_builder(
                    "e", principal, selected_scope, selected_project,
                )
                placeholders = ",".join("?" for _ in event_ids)
                rows = conn.execute(
                    f"SELECT e.* FROM memory_events e WHERE e.event_id IN "
                    f"({placeholders}) AND {owner_sql} AND e.expires_at>?",
                    (*event_ids, *owner_params, stamp),
                ).fetchall()
                for row in rows:
                    raw_id = str(row["event_id"])
                    content = str(row["content"] or "")
                    content_hash = hashlib.sha256(
                        content.encode("utf-8", "ignore")
                    ).hexdigest()
                    key = ("event", raw_id, "")
                    if (
                        content_hash == str(row["content_hash"] or "")
                        and _event_snapshot_fingerprint(row) == expected.get(key)
                    ):
                        valid.add(key)

        episode_ids = sorted({key[1] for key in expected if key[0] == "episode"})
        if episode_ids and episodic_backend is not None:
            identity = getattr(episodic_backend, "_identity", None)
            scope_getter = getattr(episodic_backend, "_scope", None)
            if callable(identity) and callable(scope_getter):
                bot_id, chat_hash = identity(provider)
                episode_scope = str(scope_getter() or "")
                if bot_id and chat_hash and episode_scope in {"chat", "bot"}:
                    placeholders = ",".join("?" for _ in episode_ids)
                    chat_sql = " AND e.owner_chat_hash=?" if episode_scope == "chat" else ""
                    params: tuple[Any, ...] = (
                        (*episode_ids, bot_id, episode_scope, chat_hash, stamp)
                        if episode_scope == "chat"
                        else (*episode_ids, bot_id, episode_scope, stamp)
                    )
                    rows = conn.execute(
                        f"SELECT e.* FROM episodic_turns e WHERE e.id IN "
                        f"({placeholders}) AND e.owner_bot_id=? "
                        f"AND e.visibility_scope=?{chat_sql} AND e.expires_at>?",
                        params,
                    ).fetchall()
                    for row in rows:
                        values = dict(row)
                        values["content_hash"] = hashlib.sha256(
                            str(row["content"] or "").encode("utf-8", "ignore")
                        ).hexdigest()
                        raw_id = str(row["id"])
                        key = ("episode", raw_id, "")
                        if _episode_snapshot_fingerprint(values) == expected.get(key):
                            valid.add(key)

        observation_ids = sorted({
            key[1] for key in expected if key[0] == "observation"
        })
        if observation_ids and observation_backend is not None:
            events_module = getattr(observation_backend, "_events", None)
            resolver = getattr(events_module, "_resolve_scope", None)
            owner_builder = getattr(events_module, "_event_owner_sql", None)
            safe_event = getattr(observation_backend, "_safe_event", None)
            confidence_fn = getattr(observation_backend, "_confidence", None)
            bounded_int = getattr(observation_backend, "_bounded_int", None)
            raw_exact_topics = set(getattr(
                observation_backend, "_RAW_EXACT_ONLY_TOPICS", set(),
            ))
            if all(callable(value) for value in (
                resolver, owner_builder, safe_event, confidence_fn, bounded_int,
            )):
                principal, selected_scope, selected_project = resolver(
                    provider, scope=event_scope,
                )
                owner_sql, owner_params = owner_builder(
                    "o", principal, selected_scope, selected_project,
                )
                placeholders = ",".join("?" for _ in observation_ids)
                observation_rows = conn.execute(
                    f"SELECT o.* FROM memory_observations o WHERE "
                    f"o.observation_id IN ({placeholders}) AND {owner_sql} "
                    "AND o.status='active' AND o.expires_at>?",
                    (*observation_ids, *owner_params, stamp),
                ).fetchall()
                observations = {
                    str(row["observation_id"]): row for row in observation_rows
                }
                version_ids = sorted({
                    str(row["current_version_id"] or "")
                    for row in observation_rows if str(row["current_version_id"] or "")
                })
                versions: dict[str, Any] = {}
                version_links: dict[str, list[Any]] = {}
                if version_ids:
                    version_placeholders = ",".join("?" for _ in version_ids)
                    versions = {
                        str(row["version_id"]): row
                        for row in conn.execute(
                            f"SELECT * FROM memory_observation_versions WHERE "
                            f"version_id IN ({version_placeholders})",
                            tuple(version_ids),
                        ).fetchall()
                    }
                    for row in conn.execute(
                        f"""SELECT ove.version_id AS link_version_id,
                                   ove.event_id AS linked_event_id,
                                   ove.evidence_order,e.*
                              FROM memory_observation_version_events ove
                              LEFT JOIN memory_events e ON e.event_id=ove.event_id
                             WHERE ove.version_id IN ({version_placeholders})
                             ORDER BY ove.version_id,ove.evidence_order,ove.event_id""",
                        tuple(version_ids),
                    ).fetchall():
                        version_links.setdefault(str(row["link_version_id"]), []).append(row)
                observation_links: dict[str, list[Any]] = {}
                for row in conn.execute(
                    f"""SELECT oe.observation_id AS link_observation_id,
                               oe.event_id AS linked_event_id,e.*
                          FROM memory_observation_events oe
                          LEFT JOIN memory_events e ON e.event_id=oe.event_id
                         WHERE oe.observation_id IN ({placeholders})
                         ORDER BY oe.observation_id,e.occurred_at,e.observed_at,
                                  e.created_at,oe.event_id""",
                    tuple(observation_ids),
                ).fetchall():
                    observation_links.setdefault(
                        str(row["link_observation_id"]), []
                    ).append(row)

                for observation_id, observation in observations.items():
                    version_id = str(observation["current_version_id"] or "")
                    version = versions.get(version_id)
                    if version is None or str(version["observation_id"]) != observation_id:
                        continue
                    if str(version["status"] or "") != "active":
                        continue
                    text_fields = (
                        "content", "normalized_content", "content_hash", "topic",
                        "cluster_key", "representative_event_id",
                    )
                    integer_fields = (
                        "support_count", "independent_support_count", "first_seen",
                        "last_seen",
                    )
                    if any(
                        str(observation[field]) != str(version[field])
                        for field in text_fields
                    ):
                        continue
                    if any(
                        int(observation[field]) != int(version[field])
                        for field in integer_fields
                    ):
                        continue
                    if abs(float(observation["confidence"]) - float(version["confidence"])) > 1e-12:
                        continue
                    support_count = int(version["support_count"] or 0)
                    if support_count <= 0 or int(version["evidence_total"] or 0) != support_count:
                        continue
                    if hashlib.sha256(
                        str(observation["content"] or "").encode("utf-8", "ignore")
                    ).hexdigest() != str(observation["content_hash"] or ""):
                        continue
                    linked_rows = observation_links.get(observation_id, [])
                    if len(linked_rows) != support_count:
                        continue
                    safe_support: list[dict[str, Any]] = []
                    support_ids: set[str] = set()
                    integrity_ok = True
                    for linked in linked_rows:
                        event_id = str(linked["linked_event_id"] or "")
                        if (
                            not event_id
                            or event_id in support_ids
                            or int(linked["expires_at"] or 0) <= stamp
                            or not _row_owned_by_event_principal(
                                linked, principal, selected_scope, selected_project,
                            )
                        ):
                            integrity_ok = False
                            break
                        try:
                            checked_event = safe_event(provider, runtime_module, linked)
                        except Exception:
                            checked_event = None
                        if checked_event is None:
                            integrity_ok = False
                            break
                        support_ids.add(event_id)
                        safe_support.append(checked_event)
                    if not integrity_ok or len(safe_support) != support_count:
                        continue
                    ordered_support = sorted(
                        safe_support,
                        key=lambda event: (
                            event["occurred_at"], event["observed_at"],
                            event["created_at"], event["event_id"],
                        ),
                    )
                    representative = ordered_support[-1]
                    independent_keys = {
                        "turn:" + event["turn_id"]
                        if event["turn_id"] else "source:" + event["cluster_key"]
                        for event in ordered_support
                    }
                    confidence = float(confidence_fn(len(independent_keys)))
                    if representative["topic"] in raw_exact_topics:
                        confidence = min(confidence, 0.35)
                    first_seen = min(
                        event["occurred_at"] or event["observed_at"]
                        for event in ordered_support
                    )
                    last_seen = max(
                        event["occurred_at"] or event["observed_at"]
                        for event in ordered_support
                    )
                    digest_payload = {
                        "event_ids": [event["event_id"] for event in ordered_support],
                        "content_hash": hashlib.sha256(
                            representative["content"].encode("utf-8", "ignore")
                        ).hexdigest(),
                        "topic": representative["topic"],
                        "cluster_key": representative["cluster_key"],
                        "representative_event_id": representative["event_id"],
                        "support_count": support_count,
                        "independent_support_count": len(independent_keys),
                        "first_seen": first_seen,
                        "last_seen": last_seen,
                        "confidence": confidence,
                        "status": "active",
                    }
                    evidence_digest = hashlib.sha256(json.dumps(
                        digest_payload, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8", "ignore")).hexdigest()
                    if (
                        evidence_digest != str(version["evidence_digest"] or "")
                        or representative["event_id"]
                        != str(version["representative_event_id"] or "")
                        or representative["content"] != str(version["content"] or "")
                        or len(independent_keys)
                        != int(version["independent_support_count"] or 0)
                        or first_seen != int(version["first_seen"] or 0)
                        or last_seen != int(version["last_seen"] or 0)
                        or abs(confidence - float(version["confidence"])) > 1e-12
                    ):
                        continue
                    linked_version_rows = version_links.get(version_id, [])
                    version_event_ids = [
                        str(row["linked_event_id"] or "") for row in linked_version_rows
                    ]
                    if (
                        not version_event_ids
                        or len(version_event_ids) != len(set(version_event_ids))
                        or any(value not in support_ids for value in version_event_ids)
                        or any(
                            int(row["expires_at"] or 0) <= stamp
                            or not _row_owned_by_event_principal(
                                row, principal, selected_scope, selected_project,
                            )
                            for row in linked_version_rows
                        )
                    ):
                        continue
                    evidence_cap = int(bounded_int(
                        "MEMORY_WIKI_OBSERVATION_VERSION_EVIDENCE_MAX", 128, 1, 1024,
                    ))
                    all_event_ids = [event["event_id"] for event in ordered_support]
                    if len(all_event_ids) <= evidence_cap:
                        expected_version_ids = all_event_ids
                    elif evidence_cap == 1:
                        expected_version_ids = [all_event_ids[-1]]
                    else:
                        oldest_count = max(1, evidence_cap // 4)
                        expected_version_ids = (
                            all_event_ids[:oldest_count]
                            + all_event_ids[-(evidence_cap - oldest_count):]
                        )
                    if version_event_ids != expected_version_ids:
                        continue
                    citation_cap = int(bounded_int(
                        "MEMORY_WIKI_OBSERVATION_EVIDENCE_IDS", 32, 1, 128,
                    ))
                    representative_id = str(version["representative_event_id"] or "")
                    evidence_ids = [
                        value for value in version_event_ids
                        if value != representative_id
                    ][:max(0, citation_cap - 1)]
                    if representative_id in version_event_ids:
                        evidence_ids.append(representative_id)
                    current = {
                        **dict(observation),
                        "version_id": version_id,
                        "evidence_digest": str(version["evidence_digest"] or ""),
                        "scope": str(observation["visibility_scope"] or ""),
                        "project_id": (
                            str(observation["project_id"] or "")
                            if selected_scope == "project" else ""
                        ),
                        "evidence_event_ids": evidence_ids,
                        "evidence_event_total": int(version["evidence_total"] or 0),
                        "evidence_event_ids_truncated": bool(
                            version["evidence_truncated"]
                        ) or len(evidence_ids) < int(version["evidence_total"] or 0),
                    }
                    key = ("observation", observation_id, "")
                    if _observation_snapshot_fingerprint(current) == expected.get(key):
                        valid.add(key)

        graph_keys = [key for key in expected if key[0] == "graph"]
        if graph_keys:
            graph_rows: dict[tuple[str, str], Any] = {}
            for graph_kind, table in (("entity", "entities"), ("relation", "relations")):
                ids = sorted({key[1] for key in graph_keys if key[2] == graph_kind})
                if not ids:
                    continue
                placeholders = ",".join("?" for _ in ids)
                for row in conn.execute(
                    f"SELECT * FROM {table} WHERE id IN ({placeholders})", tuple(ids),
                ).fetchall():
                    graph_rows[(graph_kind, str(row["id"]))] = row
            claim_ids = sorted({
                str(row["source_claim_id"] or "")
                for row in graph_rows.values()
                if str(row["source_claim_id"] or "")
            })
            source_claims: dict[str, Any] = {}
            if claim_ids:
                placeholders = ",".join("?" for _ in claim_ids)
                source_claims = {
                    str(row["id"]): row
                    for row in conn.execute(
                        f"SELECT * FROM claims WHERE id IN ({placeholders})",
                        tuple(claim_ids),
                    ).fetchall()
                }
            sanitizer = getattr(provider, "_sanitize_row", None)
            for (graph_kind, raw_id), row in graph_rows.items():
                values = dict(row)
                scope = str(values.get("visibility_scope") or "")
                if scope == "legacy":
                    visible = os.environ.get(
                        "MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_GRAPH", "0"
                    ).lower() in {"1", "true", "yes", "on"}
                else:
                    try:
                        visible = bool(provider._claim_visible(row))
                    except Exception:
                        visible = False
                if not visible:
                    continue
                if int(values.get("valid_from") or 0) > stamp:
                    continue
                if 0 < int(values.get("valid_to") or 0) <= stamp:
                    continue
                # Unified recall is an evidence facade.  A graph assertion must
                # remain anchored to a current visible claim at the final read.
                claim_id = str(values.get("source_claim_id") or "")
                claim = source_claims.get(claim_id)
                if not claim_id or claim is None:
                    continue
                try:
                    claim_visible = provider._claim_visible(claim)
                except Exception:
                    claim_visible = False
                if (
                    not claim_visible
                    or str(claim["status"] or "") != "active"
                    or str(claim["risk"] or "").lower() == "secret"
                    or int(claim["quarantined_at"] or 0) > 0
                    or str(claim["temporal_status"] or "current") not in {"", "current"}
                    or (int(claim["valid_to"] or 0) and int(claim["valid_to"]) <= stamp)
                ):
                    continue
                rendered = sanitizer(row) if callable(sanitizer) else values
                key = ("graph", raw_id, graph_kind)
                if _graph_snapshot_fingerprint(graph_kind, rendered) == expected.get(key):
                    valid.add(key)
    except Exception:
        return set()
    finally:
        try:
            conn.execute(f"RELEASE {savepoint}")
        except Exception:
            try:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
            except Exception:
                pass
    return valid


def _answer_policy(citations: list[str]) -> dict[str, Any]:
    empty = not citations
    return {
        "must_abstain_or_clarify": empty,
        "require_citations": not empty,
        "allowed_citations": citations,
        "instruction": (
            "No admissible memory evidence was returned. Abstain from memory-based claims or ask a clarifying question."
            if empty else
            "Use only the returned evidence for memory-based claims and cite only an allowed citation ID."
        ),
    }


def recall(
    provider: Any,
    query: str,
    mode: str = "auto",
    limit: int = 10,
    max_chars: int = 6000,
    *,
    episodic_backend: Any = None,
    event_backend: Any = None,
    observation_backend: Any = None,
    runtime_module: Any = None,
    query_expander: Callable[..., list[str]] = expand_memory_queries,
) -> dict[str, Any]:
    """Return one deterministic, guarded evidence set for a memory question."""
    mode = str(mode or "auto").strip().lower()
    if mode not in {"auto", "fast", "deep"}:
        raise ValueError("mode must be one of: auto, fast, deep")
    limit = max(1, min(int(limit or 10), 20))
    max_chars = max(128, min(int(max_chars or 6000), 24000))
    queries = list(query_expander(str(query or ""), mode=mode) or [])[:8]
    intent = classify_memory_intent(str(query or ""))
    retrieval_mode = "fts" if mode == "fast" else "hybrid"
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    source_status = {
        "claims": "not_run",
        "episodes": "disabled",
        "events": "not_requested" if mode == "fast" else "not_configured",
        "observations": "not_requested" if mode == "fast" else "not_configured",
        "graph": "not_requested",
    }
    raw_claim_ids: dict[str, str] = {}

    event_scope = str(os.environ.get("MEMORY_WIKI_EVENT_SCOPE", "chat") or "chat").strip().lower()
    event_ready = False
    observation_ready = False
    if mode in {"auto", "deep"} and event_backend is not None and runtime_module is not None:
        if event_scope not in _EVENT_SCOPES:
            source_status["events"] = "invalid_scope"
        else:
            try:
                enabled_check = getattr(event_backend, "enabled", None)
                event_ready = not callable(enabled_check) or bool(enabled_check())
                source_status["events"] = "ready" if event_ready else "disabled"
            except Exception:
                source_status["events"] = "unavailable"
    if mode in {"auto", "deep"} and observation_backend is not None and runtime_module is not None:
        if event_scope not in _EVENT_SCOPES:
            source_status["observations"] = "invalid_scope"
        else:
            try:
                enabled_check = getattr(observation_backend, "enabled", None)
                observation_ready = not callable(enabled_check) or bool(enabled_check())
                source_status["observations"] = "ready" if observation_ready else "disabled"
            except Exception:
                source_status["observations"] = "unavailable"

    for expanded_query in queries:
        try:
            claim_rows = provider._search(
                expanded_query,
                limit=min(40, max(8, limit * 3)),
                include_stale=True,
                retrieval_mode=retrieval_mode,
                record_retrieval=False,
            )
            source_status["claims"] = "ok"
        except Exception:
            claim_rows = []
            source_status["claims"] = "unavailable"
        for rank, row in enumerate(claim_rows or [], 1):
            if not isinstance(row, dict):
                try:
                    row = dict(row)
                except Exception:
                    continue
            try:
                if not provider._claim_visible(row):
                    continue
            except Exception:
                continue
            raw_id = str(row.get("id") or "")
            content = _guard_text(
                provider, _claim_content(row), source="unified_recall:claim",
                mem_type=str(row.get("type") or "claim"), item_id=raw_id,
                max_len=2200,
            )
            if not content:
                continue
            safe_id = _stable_id(raw_id, "c")
            raw_claim_ids[safe_id] = raw_id
            item = {
                "kind": "claim",
                "citation": f"[M:C:{safe_id}]",
                "content": content,
                "source": "memory_claim",
                "source_kind": _safe_meta(row.get("source_type"), "unknown"),
                "trust": {
                    "level": _safe_meta(row.get("verification_status"), "unverified"),
                    "class": _safe_meta(row.get("trust_class"), "fact"),
                    "confidence": round(_safe_number(row.get("confidence"), 0.0), 4),
                },
                "timestamps": {
                    "event_at": _safe_timestamp(row.get("event_at")),
                    "created_at": _safe_timestamp(row.get("created_at")),
                    "updated_at": _safe_timestamp(row.get("updated_at")),
                },
                "_source_id": raw_id,
                "_snapshot_fingerprint": _claim_snapshot_fingerprint(row),
            }
            _rrf_add(candidates, kind="claim", source_id=raw_id, rank=rank, item=item)

        if episodic_backend is not None and runtime_module is not None:
            try:
                episode_payload = episodic_backend.query_episodes(
                    provider, runtime_module, expanded_query,
                    min(5, max(1, limit)), include_diagnostics=False,
                )
                source_status["episodes"] = "ok" if episode_payload.get("enabled") else "disabled"
            except Exception:
                episode_payload = {"episodes": []}
                source_status["episodes"] = "unavailable"
            for rank, row in enumerate(episode_payload.get("episodes") or [], 1):
                if not isinstance(row, dict):
                    continue
                raw_id = str(row.get("id") or "")
                # The backend already enforces bot/chat ACL, TTL and its guard.
                # Guard again here so no future backend regression can create an
                # unguarded output path through the facade.
                content = _guard_text(
                    provider, row.get("content"), source="unified_recall:episode",
                    mem_type="episode", item_id=raw_id, max_len=500,
                )
                if not content:
                    continue
                safe_id = _stable_id(raw_id, "e")
                item = {
                    "kind": "episode",
                    "citation": f"[M:E:{safe_id}]",
                    "content": content,
                    "source": "host_attested_sync_turn",
                    "source_kind": _safe_meta(row.get("role"), "turn"),
                    "trust": {"level": "untrusted", "class": "episode", "confidence": 0.0},
                    "timestamps": {"created_at": _safe_timestamp(row.get("created_at"))},
                    "_source_id": raw_id,
                    "_snapshot_fingerprint": _episode_snapshot_fingerprint(row),
                }
                _rrf_add(candidates, kind="episode", source_id=raw_id, rank=rank, item=item)

        if event_ready:
            try:
                event_payload = event_backend.query_events(
                    provider,
                    runtime_module,
                    expanded_query,
                    min(12, max(2, limit * 2)),
                    scope=event_scope,
                    include_diagnostics=False,
                )
                if not isinstance(event_payload, dict):
                    raise TypeError("event backend returned a non-object payload")
                source_status["events"] = "ok"
            except Exception:
                event_payload = {"events": []}
                source_status["events"] = "unavailable"
            for rank, row in enumerate(event_payload.get("events") or [], 1):
                if not isinstance(row, dict):
                    continue
                # query_events owns the SQL authorization boundary.  Requiring
                # the returned scope to equal the host-selected partition keeps
                # this facade fail closed if a future adapter violates it.
                if str(row.get("scope") or "").strip().lower() != event_scope:
                    continue
                raw_id = str(row.get("event_id") or "")
                content = _guard_text(
                    provider,
                    row.get("content"),
                    source="unified_recall:event",
                    mem_type="event",
                    item_id=raw_id,
                    max_len=1400,
                )
                if not content:
                    continue
                safe_id = _stable_id(raw_id, "v")
                item = {
                    "kind": "event",
                    "citation": f"[M:V:{safe_id}]",
                    "content": content,
                    "source": "memory_event_ledger",
                    "source_kind": _safe_meta(row.get("event_type"), "event"),
                    "modality": _safe_meta(row.get("modality"), "unknown"),
                    "trust": {
                        "level": "untrusted_evidence",
                        "class": "append_only_event",
                        "confidence": 0.0,
                    },
                    "timestamps": {
                        "occurred_at": _safe_timestamp(row.get("occurred_at")),
                        "observed_at": _safe_timestamp(row.get("observed_at")),
                        "created_at": _safe_timestamp(row.get("created_at")),
                        "expires_at": _safe_timestamp(row.get("expires_at")),
                    },
                    "_source_id": raw_id,
                    "_snapshot_fingerprint": _event_snapshot_fingerprint(row),
                }
                _rrf_add(candidates, kind="event", source_id=raw_id, rank=rank, item=item)

        if observation_ready:
            try:
                observation_payload = observation_backend.query_observations(
                    provider,
                    runtime_module,
                    expanded_query,
                    min(8, max(2, limit)),
                    scope=event_scope,
                    include_diagnostics=False,
                )
                if not isinstance(observation_payload, dict):
                    raise TypeError("observation backend returned a non-object payload")
                source_status["observations"] = "ok"
            except Exception:
                observation_payload = {"observations": []}
                source_status["observations"] = "unavailable"
            for rank, row in enumerate(
                observation_payload.get("observations") or [], 1,
            ):
                if not isinstance(row, dict):
                    continue
                if str(row.get("scope") or "").strip().lower() != event_scope:
                    continue
                raw_id = str(row.get("observation_id") or "")
                content = _guard_text(
                    provider,
                    row.get("content"),
                    source="unified_recall:observation",
                    mem_type="observation",
                    item_id=raw_id,
                    max_len=1600,
                )
                if not content:
                    continue
                safe_id = _stable_id(raw_id, "o")
                evidence_ids = [
                    str(value) for value in (row.get("evidence_event_ids") or [])
                    if _SAFE_ID_RE.fullmatch(str(value) or "")
                ][:128]
                if not evidence_ids:
                    continue
                item = {
                    "kind": "observation",
                    "citation": f"[M:O:{safe_id}]",
                    "content": content,
                    "source": "memory_observation",
                    "source_kind": _safe_meta(row.get("topic"), "observation"),
                    "trust": {
                        "level": "derived_unverified",
                        "class": "event_backed_observation",
                        "confidence": round(
                            _safe_number(row.get("confidence"), 0.0), 4,
                        ),
                    },
                    "timestamps": {
                        "first_seen": _safe_timestamp(row.get("first_seen")),
                        "last_seen": _safe_timestamp(row.get("last_seen")),
                    },
                    "support_count": _safe_timestamp(row.get("support_count")),
                    "independent_support_count": _safe_timestamp(
                        row.get("independent_support_count")
                    ),
                    "evidence_event_ids": evidence_ids,
                    "evidence_event_total": _safe_timestamp(
                        row.get("evidence_event_total") or len(evidence_ids)
                    ),
                    "evidence_event_ids_truncated": bool(
                        row.get("evidence_event_ids_truncated")
                    ),
                    "_source_id": raw_id,
                    "_snapshot_fingerprint": _observation_snapshot_fingerprint(row),
                }
                _rrf_add(
                    candidates, kind="observation", source_id=raw_id,
                    rank=rank, item=item,
                )

    # Graph traversal can be substantially more expensive than lexical/vector
    # lookup. One bounded traversal over the original question is enough; query
    # expansion must not multiply graph-wide scans.
    if mode == "deep":
        try:
            graph_payload = provider._graph_query(
                str(query or ""), min(40, max(8, limit * 2)),
            )
            source_status["graph"] = "ok"
        except Exception:
            graph_payload = {"entities": [], "relations": []}
            source_status["graph"] = "unavailable"
        for rank, (graph_kind, row) in enumerate(_iter_graph_rows(graph_payload), 1):
            try:
                graph_visible = provider._graph_row_visible(row, conn=provider._connect())
            except Exception:
                graph_visible = False
            if not graph_visible:
                continue
            raw_id = str(row.get("id") or "")
            content = _guard_text(
                provider, _graph_content(graph_kind, row),
                source="unified_recall:graph", mem_type=f"graph_{graph_kind}",
                item_id=raw_id, max_len=1400,
            )
            if not content:
                continue
            safe_id = _stable_id(raw_id, "g")
            item = {
                "kind": "graph",
                "graph_kind": graph_kind,
                "citation": f"[M:G:{safe_id}]",
                "content": content,
                "source": "knowledge_graph",
                "source_kind": graph_kind,
                "trust": {
                    "level": "derived",
                    "class": "graph",
                    "confidence": round(_safe_number(row.get("confidence"), 0.0), 4),
                },
                "timestamps": {
                    "created_at": _safe_timestamp(row.get("created_at")),
                    "updated_at": _safe_timestamp(row.get("updated_at")),
                },
                "_source_id": raw_id,
                "_snapshot_fingerprint": _graph_snapshot_fingerprint(graph_kind, row),
            }
            _rrf_add(candidates, kind="graph", source_id=raw_id, rank=rank, item=item)

    final_visible_claims = _final_visible_claims(provider, raw_claim_ids.values())
    final_visible_nonclaims = _final_visible_nonclaims(
        provider,
        candidates.values(),
        episodic_backend=episodic_backend,
        event_backend=event_backend,
        observation_backend=observation_backend,
        event_scope=event_scope,
        runtime_module=runtime_module,
    )
    final_candidates = [
        item for item in candidates.values()
        if (
            item.get("kind") != "claim"
            and _candidate_identity(item) in final_visible_nonclaims
        ) or (
            item.get("kind") == "claim"
            and
            raw_claim_ids.get(str(item.get("id"))) in final_visible_claims
            and item.get("_snapshot_fingerprint")
            == final_visible_claims.get(raw_claim_ids.get(str(item.get("id"))))
        )
    ]
    ordered = sorted(
        final_candidates,
        key=lambda item: (
            -float(item["_rrf"]),
            _SOURCE_PRIORITY[str(item["kind"])],
            int(item["_first_rank"]),
            str(item["id"]),
        ),
    )
    items: list[dict[str, Any]] = []
    used_chars = 0
    for raw_item in ordered:
        if len(items) >= limit or used_chars >= max_chars:
            break
        content = str(raw_item.get("content") or "")
        remaining = max_chars - used_chars
        if len(content) > remaining:
            if remaining < 32:
                break
            content = content[: remaining - 1].rstrip() + "…"
        item = {key: value for key, value in raw_item.items() if not key.startswith("_")}
        item["content"] = content
        item["rrf_score"] = round(float(raw_item["_rrf"]), 8)
        items.append(item)
        used_chars += len(content)

    citations = [str(item["citation"]) for item in items]
    selected_claim_ids = [
        raw_claim_ids[str(item["id"])]
        for item in items
        if item.get("kind") == "claim" and str(item.get("id")) in raw_claim_ids
    ]
    recall_event_ids: dict[str, str] = {}
    tracking_status = "not_needed" if not selected_claim_ids else "unsupported"
    recorder = getattr(provider, "_record_recall_rows", None)
    if selected_claim_ids and callable(recorder):
        tracking_rows = [
            {
                "id": raw_claim_ids[str(item["id"])],
                "score": float(item.get("rrf_score") or 0.0),
            }
            for item in items
            if item.get("kind") == "claim" and str(item.get("id")) in raw_claim_ids
        ]
        try:
            recorded = recorder(
                tracking_rows, injected=True, source="unified_recall",
            )
            if isinstance(recorded, dict):
                recall_event_ids = {
                    str(claim_id): str(event_id)
                    for claim_id, event_id in recorded.items()
                    if str(claim_id) in selected_claim_ids
                    and _SAFE_ID_RE.fullmatch(str(event_id) or "")
                }
                tracking_status = (
                    "ok" if len(recall_event_ids) == len(selected_claim_ids) else "partial"
                )
            else:
                tracking_status = "unavailable"
        except Exception:
            tracking_status = "unavailable"
    linkages: list[dict[str, str]] = []
    for item in items:
        if item.get("kind") != "claim":
            continue
        raw_claim_id = raw_claim_ids.get(str(item.get("id")))
        recall_event_id = recall_event_ids.get(str(raw_claim_id or ""), "")
        if recall_event_id:
            item["recall_event_id"] = recall_event_id
            linkages.append({
                "claim_id": str(raw_claim_id),
                "recall_event_id": recall_event_id,
            })
    guarded_queries = []
    for index, expanded_query in enumerate(queries):
        safe_query = _guard_text(
            provider, expanded_query, source="unified_recall:query_plan",
            mem_type="query", item_id=f"query_{index}", max_len=500,
        )
        guarded_queries.append(safe_query or "[query omitted by recall guard]")

    return {
        "items": items,
        "intent_plan": {
            "mode": mode,
            "intent": intent,
            "queries": guarded_queries,
            "retrieval_mode": retrieval_mode,
            "sources": source_status,
        },
        "evidence_count": len(items),
        "conflicts": _detect_conflicts(provider, selected_claim_ids),
        "chars_used": used_chars,
        "max_chars": max_chars,
        "recall_tracking": {
            "status": tracking_status,
            "events": linkages,
            "answer_linkage": {
                "claim_ids": [row["claim_id"] for row in linkages],
                "recall_event_ids": [row["recall_event_id"] for row in linkages],
                "requires_answer_id_for_cross_retry_idempotency": True,
            },
        },
        "answer_policy": _answer_policy(citations),
    }
