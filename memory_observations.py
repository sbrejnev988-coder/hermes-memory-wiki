"""Evidence-backed living observations derived from the immutable event ledger.

Observations are deterministic materialized views over guard-safe events.  They
never synthesize text: the current content and every immutable version copy the
guarded text of one supporting event.  The event ledger remains the evidence
source of truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import unicodedata
from typing import Any, Iterable

try:
    from . import memory_events as _events
except ImportError:  # pragma: no cover - standalone plugin loading
    import memory_events as _events


_TOKEN_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_SAFE_TOPIC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_SAFE_EVENT_ID_RE = re.compile(r"^evt_[A-Za-z0-9_.:-]{1,120}$")
# This allow-list is intentionally tiny.  Case, Unicode compatibility,
# punctuation, whitespace, and optional English articles are deterministic
# surface equivalences.  Inferring broader paraphrases or supersession from
# free text would require inventing a subject/predicate boundary and can merge
# contradictory facts.  Equivalent evidence instead advances the immutable
# version chain below; explicit structured correction remains the only safe
# basis for claim-level supersession.
_SOFT_TOKENS = frozenset({"a", "an", "the"})
# OCR is derived from an unverified host report. Its surface text may be
# recalled with citations, but paraphrase merging must never strengthen it.
_RAW_EXACT_ONLY_TOPICS = frozenset({"dialogue_turn", "visual_ocr"})
_POLARITY = frozenset({
    "no", "not", "never", "without", "false", "disabled", "off",
    "нет", "не", "никогда", "без", "ложь", "выключен", "отключен",
})


def enabled() -> bool:
    """Derived observation reads and writes follow the host runtime policy."""
    return os.environ.get("MEMORY_WIKI_OBSERVATIONS_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }


class _RetryableEventGuard(RuntimeError):
    """A guard dependency failed; the event must remain eligible for retry."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_REQUIRED_SCHEMA_OBJECTS = {
    "memory_observations": "table",
    "memory_observation_versions": "table",
    "memory_observation_events": "table",
    "memory_observation_version_events": "table",
    "memory_observation_event_decisions": "table",
    "memory_observation_event_retries": "table",
    "memory_observations_fts": "table",
    "idx_memory_observations_owner_topic": "index",
    "idx_memory_observation_versions_observation": "index",
    "idx_memory_observation_events_observation": "index",
    "idx_memory_observation_version_events_event": "index",
    "idx_memory_observation_decisions_observation": "index",
    "idx_memory_observation_retries_due": "index",
    "memory_observations_fts_ai": "trigger",
    "memory_observations_fts_au": "trigger",
    "memory_observations_fts_ad": "trigger",
    "memory_observation_versions_no_update": "trigger",
    "memory_observation_events_no_update": "trigger",
    "memory_observation_version_events_no_update": "trigger",
    "memory_observation_decisions_no_update": "trigger",
    "memory_observations_delete_children": "trigger",
    "memory_observations_event_privacy_delete": "trigger",
}


def _require_schema(conn: sqlite3.Connection) -> None:
    """Fail closed when startup migration has not installed observation schema.

    Runtime reads and writes must not execute DDL or rebuild FTS.  This single
    catalog read is deliberately cheap; incompatible columns still fail closed
    when the prepared runtime statement is compiled.
    """
    names = tuple(_REQUIRED_SCHEMA_OBJECTS)
    placeholders = ",".join("?" for _ in names)
    try:
        rows = conn.execute(
            f"SELECT name,type FROM sqlite_master WHERE name IN ({placeholders})",
            names,
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError("memory observation schema readiness check failed") from exc
    actual = {str(row[0]): str(row[1]) for row in rows}
    missing = sorted(
        name for name, object_type in _REQUIRED_SCHEMA_OBJECTS.items()
        if actual.get(name) != object_type
    )
    if missing:
        raise RuntimeError(
            "memory observation schema is not installed; run provider migration: "
            + ",".join(missing)
        )


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return max(minimum, min(value, maximum))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()


def _normalize_content(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(_TOKEN_RE.findall(text))[:4000]


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(str(value or "").casefold()))


def _anchor_tokens(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        token for token in values
        if any(char.isdigit() for char in token) or token in _POLARITY
    )


def _cluster_key(value: str) -> str:
    return " ".join(
        token for token in _TOKEN_RE.findall(str(value or ""))
        if token not in _SOFT_TOKENS
    )


def _similarity(first: str, second: str) -> float:
    if first == second and first:
        return 1.0
    left = _tokens(first)
    right = _tokens(second)
    if len(left) < 3 or len(right) < 3:
        return 0.0
    if _anchor_tokens(left) != _anchor_tokens(right):
        return 0.0
    # High token overlap alone can merge a changed value in a long sentence.
    # Only article-level differences are safe to ignore without an extractor;
    # preserve word order so "dog bites man" never joins "man bites dog".
    if not (left ^ right).issubset(_SOFT_TOKENS):
        return 0.0
    left_sequence = tuple(
        token for token in _TOKEN_RE.findall(first) if token not in _SOFT_TOKENS
    )
    right_sequence = tuple(
        token for token in _TOKEN_RE.findall(second) if token not in _SOFT_TOKENS
    )
    if left_sequence != right_sequence:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _topic(row: Any) -> str:
    value = str(row["event_type"] or "observation").strip().lower()
    return value if _SAFE_TOPIC_RE.fullmatch(value) else ""


def _partition_identity(
    principal: dict[str, str], scope: str, project_id: str,
) -> str:
    if scope == "chat":
        return "\0".join((scope, principal["bot_id"], principal["chat_hash"], principal["session_hash"]))
    if scope == "bot":
        return "\0".join((scope, principal["bot_id"]))
    return "\0".join((scope, principal["bot_id"], project_id))


def _confidence(independent_support: int) -> float:
    if independent_support <= 0:
        return 0.0
    # Event observations remain unverified even with repetition.  Correlated
    # events from one turn count once, and the curve cannot exceed 0.85.
    return round(min(0.85, 0.35 + 0.15 * math.log2(independent_support)), 4)


def install_schema(conn: sqlite3.Connection) -> None:
    """Migration hook: install observations, immutable history, links, and FTS."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_observations(
            observation_id TEXT PRIMARY KEY,
            owner_bot_id TEXT NOT NULL,
            owner_chat_hash TEXT NOT NULL,
            owner_session_hash TEXT NOT NULL,
            visibility_scope TEXT NOT NULL
                CHECK(visibility_scope IN ('chat','bot','project')),
            project_id TEXT NOT NULL DEFAULT '',
            topic TEXT NOT NULL,
            cluster_normalized TEXT NOT NULL,
            cluster_key TEXT NOT NULL,
            content TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            representative_event_id TEXT NOT NULL,
            current_version_id TEXT NOT NULL DEFAULT '',
            support_count INTEGER NOT NULL DEFAULT 0 CHECK(support_count>=0),
            independent_support_count INTEGER NOT NULL DEFAULT 0
                CHECK(independent_support_count>=0),
            first_seen INTEGER NOT NULL DEFAULT 0,
            last_seen INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0 CHECK(confidence>=0 AND confidence<=1),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','superseded')),
            superseded_by TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            CHECK(length(content)>0),
            CHECK(length(content_hash)=64)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_observation_versions(
            version_id TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            version_no INTEGER NOT NULL CHECK(version_no>0),
            content TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            topic TEXT NOT NULL,
            cluster_key TEXT NOT NULL,
            representative_event_id TEXT NOT NULL,
            support_count INTEGER NOT NULL CHECK(support_count>0),
            independent_support_count INTEGER NOT NULL
                CHECK(independent_support_count>0),
            first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            confidence REAL NOT NULL CHECK(confidence>=0 AND confidence<=1),
            status TEXT NOT NULL CHECK(status IN ('active','superseded')),
            evidence_digest TEXT NOT NULL,
            evidence_total INTEGER NOT NULL CHECK(evidence_total>0),
            evidence_truncated INTEGER NOT NULL DEFAULT 0
                CHECK(evidence_truncated IN (0,1)),
            created_at INTEGER NOT NULL,
            FOREIGN KEY(observation_id) REFERENCES memory_observations(observation_id)
                ON DELETE CASCADE,
            UNIQUE(observation_id,version_no),
            UNIQUE(observation_id,evidence_digest),
            CHECK(length(content)>0),
            CHECK(length(content_hash)=64),
            CHECK(length(evidence_digest)=64)
        )"""
    )
    # One event supports exactly one observation.  The version digest commits
    # the full ordered evidence set; the version link table keeps a bounded,
    # deterministic oldest/recent sample for citation and inspection.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_observation_events(
            event_id TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            linked_at INTEGER NOT NULL,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id) ON DELETE CASCADE,
            FOREIGN KEY(observation_id) REFERENCES memory_observations(observation_id)
                ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_observation_version_events(
            version_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            evidence_order INTEGER NOT NULL CHECK(evidence_order>=0),
            PRIMARY KEY(version_id,event_id),
            FOREIGN KEY(version_id) REFERENCES memory_observation_versions(version_id)
                ON DELETE CASCADE,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_observation_event_decisions(
            event_id TEXT PRIMARY KEY,
            outcome TEXT NOT NULL CHECK(outcome IN ('linked','rejected')),
            observation_id TEXT NOT NULL DEFAULT '',
            decided_at INTEGER NOT NULL,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_observation_event_retries(
            event_id TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL CHECK(attempts>0),
            retry_after INTEGER NOT NULL,
            last_reason TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id) ON DELETE CASCADE
        )"""
    )

    expected = {
        "memory_observations": {
            "observation_id", "owner_bot_id", "owner_chat_hash", "owner_session_hash",
            "visibility_scope", "project_id", "topic", "cluster_normalized",
            "cluster_key", "content", "normalized_content", "content_hash",
            "representative_event_id", "current_version_id",
            "support_count", "independent_support_count", "first_seen", "last_seen",
            "confidence", "status", "superseded_by", "created_at", "updated_at",
            "expires_at",
        },
        "memory_observation_versions": {
            "version_id", "observation_id", "version_no", "content",
            "normalized_content", "content_hash", "topic", "support_count",
            "independent_support_count", "first_seen", "last_seen", "confidence",
            "status", "evidence_digest", "evidence_total", "evidence_truncated",
            "cluster_key", "representative_event_id", "created_at",
        },
        "memory_observation_events": {"event_id", "observation_id", "linked_at"},
        "memory_observation_version_events": {
            "version_id", "event_id", "evidence_order",
        },
        "memory_observation_event_decisions": {
            "event_id", "outcome", "observation_id", "decided_at",
        },
        "memory_observation_event_retries": {
            "event_id", "attempts", "retry_after", "last_reason", "updated_at",
        },
    }
    for table, required in expected.items():
        actual = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = required - actual
        if missing:
            raise RuntimeError(
                f"incompatible {table} schema: missing " + ",".join(sorted(missing))
            )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_observations_owner_topic "
        "ON memory_observations(owner_bot_id,visibility_scope,owner_chat_hash,"
        "owner_session_hash,project_id,status,topic,cluster_key,last_seen,observation_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_observation_versions_observation "
        "ON memory_observation_versions(observation_id,version_no,version_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_observation_events_observation "
        "ON memory_observation_events(observation_id,event_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_observation_version_events_event "
        "ON memory_observation_version_events(event_id,version_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_observation_decisions_observation "
        "ON memory_observation_event_decisions(observation_id,event_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_observation_retries_due "
        "ON memory_observation_event_retries(retry_after,event_id)"
    )

    fts_exists = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='memory_observations_fts'"
    ).fetchone())
    if fts_exists:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(memory_observations_fts)")
        }
        if columns != {"observation_id", "content", "topic"}:
            for trigger in (
                "memory_observations_fts_ai", "memory_observations_fts_au",
                "memory_observations_fts_ad",
            ):
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            conn.execute("DROP TABLE memory_observations_fts")
            fts_exists = False
    conn.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS memory_observations_fts USING fts5(
            observation_id UNINDEXED,content,topic,tokenize='unicode61')"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observations_fts_ai")
    conn.execute(
        """CREATE TRIGGER memory_observations_fts_ai
        AFTER INSERT ON memory_observations BEGIN
          INSERT INTO memory_observations_fts(observation_id,content,topic)
          VALUES(NEW.observation_id,NEW.content,NEW.topic);
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observations_fts_au")
    conn.execute(
        """CREATE TRIGGER memory_observations_fts_au
        AFTER UPDATE OF content,topic,status ON memory_observations BEGIN
          DELETE FROM memory_observations_fts WHERE observation_id=OLD.observation_id;
          INSERT INTO memory_observations_fts(observation_id,content,topic)
          VALUES(NEW.observation_id,NEW.content,NEW.topic);
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observations_fts_ad")
    conn.execute(
        """CREATE TRIGGER memory_observations_fts_ad
        AFTER DELETE ON memory_observations BEGIN
          DELETE FROM memory_observations_fts WHERE observation_id=OLD.observation_id;
        END"""
    )

    # Version and evidence snapshots cannot be rewritten.  DELETE remains
    # available only so expiry and explicit privacy erasure can remove content.
    conn.execute("DROP TRIGGER IF EXISTS memory_observation_versions_no_update")
    conn.execute(
        """CREATE TRIGGER memory_observation_versions_no_update
        BEFORE UPDATE ON memory_observation_versions BEGIN
          SELECT RAISE(ABORT,'memory observation versions are immutable');
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observation_events_no_update")
    conn.execute(
        """CREATE TRIGGER memory_observation_events_no_update
        BEFORE UPDATE ON memory_observation_events BEGIN
          SELECT RAISE(ABORT,'memory observation event links are immutable');
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observation_version_events_no_update")
    conn.execute(
        """CREATE TRIGGER memory_observation_version_events_no_update
        BEFORE UPDATE ON memory_observation_version_events BEGIN
          SELECT RAISE(ABORT,'memory observation version links are immutable');
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observation_decisions_no_update")
    conn.execute(
        """CREATE TRIGGER memory_observation_decisions_no_update
        BEFORE UPDATE ON memory_observation_event_decisions BEGIN
          SELECT RAISE(ABORT,'memory observation decisions are immutable');
        END"""
    )

    # Foreign keys can be disabled by a host connection.  These triggers make
    # privacy deletion independent of that pragma.  Deleting any source event
    # removes the complete derived observation and all content-bearing history;
    # remaining events can form a fresh observation on the next consolidation.
    conn.execute("DROP TRIGGER IF EXISTS memory_observations_delete_children")
    conn.execute(
        """CREATE TRIGGER memory_observations_delete_children
        BEFORE DELETE ON memory_observations BEGIN
          DELETE FROM memory_observation_version_events WHERE version_id IN (
            SELECT version_id FROM memory_observation_versions
            WHERE observation_id=OLD.observation_id
          );
          DELETE FROM memory_observation_versions
            WHERE observation_id=OLD.observation_id;
          DELETE FROM memory_observation_events
            WHERE observation_id=OLD.observation_id;
          DELETE FROM memory_observations_fts
            WHERE observation_id=OLD.observation_id;
        END"""
    )
    conn.execute("DROP TRIGGER IF EXISTS memory_observations_event_privacy_delete")
    conn.execute(
        """CREATE TRIGGER memory_observations_event_privacy_delete
        BEFORE DELETE ON memory_events BEGIN
          DELETE FROM memory_observation_event_decisions WHERE event_id IN (
            SELECT sibling.event_id FROM memory_observation_events sibling
            WHERE sibling.observation_id IN (
              SELECT observation_id FROM memory_observation_events
              WHERE event_id=OLD.event_id
            )
          );
          DELETE FROM memory_observations WHERE observation_id IN (
            SELECT observation_id FROM memory_observation_events
            WHERE event_id=OLD.event_id
          );
          DELETE FROM memory_observation_events WHERE event_id=OLD.event_id;
          DELETE FROM memory_observation_version_events WHERE event_id=OLD.event_id;
           DELETE FROM memory_observation_event_decisions WHERE event_id=OLD.event_id;
           DELETE FROM memory_observation_event_retries WHERE event_id=OLD.event_id;
        END"""
    )

    base_count = int(conn.execute(
        "SELECT COUNT(*) FROM memory_observations"
    ).fetchone()[0])
    fts_count = int(conn.execute("SELECT COUNT(*) FROM memory_observations_fts").fetchone()[0])
    if not fts_exists or base_count != fts_count:
        rebuild_fts(conn)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the derived observation FTS index transactionally."""
    savepoint = "memory_observations_fts_rebuild"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        conn.execute("DELETE FROM memory_observations_fts")
        conn.execute(
            """INSERT INTO memory_observations_fts(observation_id,content,topic)
               SELECT observation_id,content,topic FROM memory_observations"""
        )
        base_count = int(conn.execute(
            "SELECT COUNT(*) FROM memory_observations"
        ).fetchone()[0])
        fts_count = int(conn.execute(
            "SELECT COUNT(*) FROM memory_observations_fts"
        ).fetchone()[0])
        if base_count != fts_count:
            raise RuntimeError("memory observation FTS rebuild count mismatch")
    except Exception:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")
        raise
    conn.execute(f"RELEASE {savepoint}")


def _safe_event(provider: Any, module: Any, row: Any) -> dict[str, Any] | None:
    try:
        event_id = str(row["event_id"] or "")
        content = str(row["content"] or "")
    except Exception:
        return None
    if not _SAFE_EVENT_ID_RE.fullmatch(event_id):
        return None
    if _sha(content) != str(row["content_hash"] or ""):
        return None
    try:
        if module.secret_scan(content).get("raw_secret"):
            return None
    except Exception as exc:
        raise _RetryableEventGuard("secret_scan_unavailable") from exc
    try:
        checked = provider._inspect_recall_text(
            content,
            source="observation:event_evidence",
            mem_type="event",
            item_id=event_id,
            audit=False,
            max_len=_bounded_int(
                "MEMORY_WIKI_OBSERVATION_EVENT_CONTENT", 1600, 128, 4000
            ),
        )
    except Exception as exc:
        raise _RetryableEventGuard("recall_guard_unavailable") from exc
    if not isinstance(checked, dict):
        raise _RetryableEventGuard("recall_guard_invalid_result")
    status = str(checked.get("status") or "")
    if status != "safe":
        if "runtime_failure" in status or not status:
            raise _RetryableEventGuard("recall_guard_runtime_failure")
        return None
    safe_content = str(checked.get("content") or "").strip()
    try:
        if module.secret_scan(safe_content).get("raw_secret"):
            return None
    except Exception as exc:
        raise _RetryableEventGuard("secret_scan_unavailable") from exc
    normalized = _normalize_content(safe_content)
    topic = _topic(row)
    if not safe_content or not normalized or not topic:
        return None
    exact_only = topic in _RAW_EXACT_ONLY_TOPICS
    return {
        "event_id": event_id,
        "content": safe_content,
        "normalized": normalized,
        "cluster_key": normalized if exact_only else _cluster_key(normalized),
        "exact_only": exact_only,
        "topic": topic,
        "turn_id": str(row["turn_id"] or ""),
        "role": str(row["role"] or "observer"),
        "content_hash": _sha(safe_content),
        "occurred_at": max(0, int(row["occurred_at"] or 0)),
        "observed_at": max(0, int(row["observed_at"] or 0)),
        "created_at": max(0, int(row["created_at"] or 0)),
        "expires_at": max(0, int(row["expires_at"] or 0)),
    }


def _defer_event(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    stamp: int,
    reason: str,
) -> int:
    """Persist bounded retry state without turning an outage into rejection."""
    previous = conn.execute(
        "SELECT attempts FROM memory_observation_event_retries WHERE event_id=?",
        (event_id,),
    ).fetchone()
    attempts = min(31, int(previous[0] if previous is not None else 0) + 1)
    base = _bounded_int("MEMORY_WIKI_OBSERVATION_RETRY_BASE_SECONDS", 1, 1, 300)
    maximum = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_RETRY_MAX_SECONDS", 3600, base, 86400,
    )
    delay = min(maximum, base * (2 ** min(attempts - 1, 16)))
    retry_after = stamp + delay
    conn.execute(
        """INSERT INTO memory_observation_event_retries(
               event_id,attempts,retry_after,last_reason,updated_at
           ) VALUES(?,?,?,?,?)
           ON CONFLICT(event_id) DO UPDATE SET
             attempts=excluded.attempts,retry_after=excluded.retry_after,
             last_reason=excluded.last_reason,updated_at=excluded.updated_at""",
        (event_id, attempts, retry_after, str(reason)[:64], stamp),
    )
    return retry_after


def _invalidate_linked_observation(
    conn: sqlite3.Connection,
    observation_id: str,
) -> str:
    """Remove a derived history whose linked source is now permanently unsafe.

    A prior successful guard decision is not permanent: policy can tighten after
    a transient outage.  Keeping any version that counted the newly rejected
    source would retain stale confidence and evidence.  Delete the whole derived
    history and release sibling decisions, matching source privacy deletion;
    still-live siblings can form a clean observation on the next consolidation.
    """
    observation_id = str(observation_id or "")
    if not observation_id:
        return ""
    conn.execute(
        "DELETE FROM memory_observation_event_decisions WHERE observation_id=?",
        (observation_id,),
    )
    conn.execute(
        "DELETE FROM memory_observations WHERE observation_id=?",
        (observation_id,),
    )
    return observation_id


def _best_observation(
    observations: list[dict[str, Any]], topic: str, normalized: str, threshold: float,
) -> dict[str, Any] | None:
    choices = []
    for observation in observations:
        if observation["status"] != "active" or observation["topic"] != topic:
            continue
        if topic in _RAW_EXACT_ONLY_TOPICS:
            similarity = 1.0 if normalized in {
                str(observation["cluster_normalized"]),
                str(observation["normalized_content"]),
            } else 0.0
        else:
            similarity = max(
                _similarity(normalized, observation["cluster_normalized"]),
                _similarity(normalized, observation["normalized_content"]),
            )
        if similarity >= threshold:
            choices.append((similarity, observation["observation_id"], observation))
    if not choices:
        return None
    choices.sort(key=lambda item: (-item[0], item[1]))
    return choices[0][2]


def _support_rows(
    conn: sqlite3.Connection,
    observation_id: str,
    owner_sql: str,
    owner_params: tuple[Any, ...],
    stamp: int,
) -> list[Any]:
    cap = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_MAX_SUPPORT_EVENTS", 20000, 1, 20000
    )
    return conn.execute(
        f"""SELECT * FROM (
              SELECT e.* FROM memory_observation_events oe
              JOIN memory_events e ON e.event_id=oe.event_id
              WHERE oe.observation_id=? AND {owner_sql} AND e.expires_at>?
              ORDER BY e.occurred_at DESC,e.observed_at DESC,
                       e.created_at DESC,e.event_id DESC LIMIT ?
            ) ORDER BY occurred_at,observed_at,created_at,event_id""",
        (observation_id, *owner_params, stamp, cap),
    ).fetchall()


def _write_version(
    conn: sqlite3.Connection,
    observation: Any,
    events: list[dict[str, Any]],
    *,
    stamp: int,
) -> bool:
    if not events:
        conn.execute(
            "DELETE FROM memory_observations WHERE observation_id=?",
            (str(observation["observation_id"]),),
        )
        return False
    ordered = sorted(
        events,
        key=lambda event: (
            event["occurred_at"], event["observed_at"],
            event["created_at"], event["event_id"],
        ),
    )
    representative = ordered[-1]
    event_ids = [event["event_id"] for event in ordered]
    independent_keys = {
        "turn:" + event["turn_id"]
        if event["turn_id"]
        # Wording and speaker-role variation are not independent sources.
        # Without a turn or verified provenance identity, the whole cluster
        # counts once; otherwise one echoed statement could inflate trust.
        else "source:" + event["cluster_key"]
        for event in ordered
    }
    support_count = len(event_ids)
    independent_count = len(independent_keys)
    first_seen = min(event["occurred_at"] or event["observed_at"] for event in ordered)
    last_seen = max(event["occurred_at"] or event["observed_at"] for event in ordered)
    confidence = _confidence(independent_count)
    if representative["topic"] in _RAW_EXACT_ONLY_TOPICS:
        confidence = min(confidence, 0.35)
    ttl_days = _bounded_int("MEMORY_WIKI_OBSERVATION_TTL_DAYS", 365, 1, 3650)
    # A materialized observation is valid only while every item counted in its
    # support/confidence remains live.  Expire at the earliest source boundary;
    # maintenance can then rebuild from the still-live siblings.
    expires_at = min(min(event["expires_at"] for event in ordered), stamp + ttl_days * 86400)
    digest_payload = {
        "event_ids": event_ids,
        "content_hash": _sha(representative["content"]),
        "topic": representative["topic"],
        "cluster_key": representative["cluster_key"],
        "representative_event_id": representative["event_id"],
        "support_count": support_count,
        "independent_support_count": independent_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "confidence": confidence,
        "status": "active",
    }
    evidence_digest = _sha(json.dumps(
        digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ))
    observation_id = str(observation["observation_id"])
    existing = conn.execute(
        """SELECT version_id FROM memory_observation_versions
           WHERE observation_id=? AND evidence_digest=?""",
        (observation_id, evidence_digest),
    ).fetchone()
    if existing is not None:
        return False
    version_no = int(conn.execute(
        "SELECT COALESCE(MAX(version_no),0)+1 FROM memory_observation_versions "
        "WHERE observation_id=?", (observation_id,),
    ).fetchone()[0])
    version_id = "obv_" + _sha(observation_id + "\0" + evidence_digest)[:24]
    conn.execute(
        """INSERT INTO memory_observation_versions(
            version_id,observation_id,version_no,content,normalized_content,
            content_hash,topic,cluster_key,representative_event_id,support_count,
            independent_support_count,first_seen,last_seen,confidence,status,
            evidence_digest,evidence_total,evidence_truncated,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            version_id, observation_id, version_no, representative["content"],
            representative["normalized"], _sha(representative["content"]),
            representative["topic"], representative["cluster_key"],
            representative["event_id"], support_count, independent_count,
            first_seen, last_seen, confidence, "active", evidence_digest,
            support_count, int(support_count > _bounded_int(
                "MEMORY_WIKI_OBSERVATION_VERSION_EVIDENCE_MAX", 128, 1, 1024
            )), stamp,
        ),
    )
    evidence_cap = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_VERSION_EVIDENCE_MAX", 128, 1, 1024
    )
    if len(event_ids) <= evidence_cap:
        version_event_ids = event_ids
    elif evidence_cap == 1:
        version_event_ids = [event_ids[-1]]
    else:
        oldest_count = max(1, evidence_cap // 4)
        recent_count = evidence_cap - oldest_count
        version_event_ids = event_ids[:oldest_count] + event_ids[-recent_count:]
    conn.executemany(
        """INSERT INTO memory_observation_version_events(
            version_id,event_id,evidence_order
        ) VALUES(?,?,?)""",
        [
            (version_id, event_id, index)
            for index, event_id in enumerate(version_event_ids)
        ],
    )
    conn.execute(
        """UPDATE memory_observations SET
            content=?,normalized_content=?,content_hash=?,cluster_key=?,
            representative_event_id=?,current_version_id=?,support_count=?,
            independent_support_count=?,first_seen=?,last_seen=?,confidence=?,
            status='active',superseded_by='',updated_at=?,expires_at=?
           WHERE observation_id=?""",
        (
            representative["content"], representative["normalized"],
            _sha(representative["content"]), representative["cluster_key"],
            representative["event_id"], version_id, support_count,
            independent_count, first_seen, last_seen, confidence, stamp,
            expires_at, observation_id,
        ),
    )
    version_cap = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_VERSIONS_PER_RECORD", 64, 1, 512
    )
    expired_versions = [
        str(row["version_id"])
        for row in conn.execute(
            """SELECT version_id FROM memory_observation_versions
               WHERE observation_id=? ORDER BY version_no DESC,version_id DESC
               LIMIT -1 OFFSET ?""",
            (observation_id, version_cap),
        ).fetchall()
    ]
    if expired_versions:
        placeholders = ",".join("?" for _ in expired_versions)
        conn.execute(
            f"DELETE FROM memory_observation_version_events "
            f"WHERE version_id IN ({placeholders})",
            tuple(expired_versions),
        )
        conn.execute(
            f"DELETE FROM memory_observation_versions "
            f"WHERE version_id IN ({placeholders})",
            tuple(expired_versions),
        )
    return True


def consolidate_events(
    provider: Any,
    module: Any,
    *,
    scope: str = "chat",
    project_id: str = "",
    session_id: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    """Incrementally cluster unlinked events and append immutable versions."""
    principal, selected_scope, selected_project = _events._resolve_scope(
        provider, session_id=session_id, scope=scope, project_id=project_id,
    )
    conn = provider._connect()
    _require_schema(conn)
    pre_pruned = prune_observations(
        provider, conn=conn, scope=selected_scope, project_id=selected_project,
        session_id=session_id,
    )
    batch = max(1, min(
        int(limit) if limit is not None else _bounded_int(
            "MEMORY_WIKI_OBSERVATION_BATCH_EVENTS", 1000, 1, 10000
        ),
        10000,
    ))
    threshold = _bounded_float(
        "MEMORY_WIKI_OBSERVATION_SIMILARITY", 0.82, 0.60, 1.0
    )
    event_owner_sql, event_owner_params = _events._event_owner_sql(
        "e", principal, selected_scope, selected_project,
    )
    observation_owner_sql, observation_owner_params = _events._event_owner_sql(
        "o", principal, selected_scope, selected_project,
    )
    stamp = int(time.time())
    rows = conn.execute(
        f"""SELECT e.* FROM memory_events e
            LEFT JOIN memory_observation_event_decisions d ON d.event_id=e.event_id
            LEFT JOIN memory_observation_event_retries r ON r.event_id=e.event_id
            WHERE {event_owner_sql} AND e.expires_at>?
              AND (d.event_id IS NULL OR (r.event_id IS NOT NULL AND r.retry_after<=?))
              AND (r.event_id IS NULL OR r.retry_after<=?)
            ORDER BY e.created_at,e.observed_at,e.event_id LIMIT ?""",
        (*event_owner_params, stamp, stamp, stamp, batch),
    ).fetchall()
    max_existing = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_MATCH_ROWS", 10000, 1, 50000
    )
    existing_rows = conn.execute(
        f"""SELECT * FROM memory_observations o
            WHERE {observation_owner_sql} AND o.status='active' AND o.expires_at>?
            ORDER BY o.created_at,o.observation_id LIMIT ?""",
        (*observation_owner_params, stamp, max_existing),
    ).fetchall()
    observations = [dict(row) for row in existing_rows]
    affected: set[str] = set()
    accepted = 0
    rejected = 0
    deferred = 0
    next_retry_at = 0
    created = 0
    invalidated = 0
    partition = _partition_identity(principal, selected_scope, selected_project)
    with conn:
        for raw in rows:
            raw_event_id = str(raw["event_id"])
            existing_link = conn.execute(
                f"""SELECT oe.observation_id
                    FROM memory_observation_events oe
                    JOIN memory_observations o
                      ON o.observation_id=oe.observation_id
                    WHERE oe.event_id=? AND {observation_owner_sql} LIMIT 1""",
                (raw_event_id, *observation_owner_params),
            ).fetchone()
            try:
                event = _safe_event(provider, module, raw)
            except _RetryableEventGuard as exc:
                deferred += 1
                due = _defer_event(
                    conn, str(raw["event_id"]), stamp=stamp, reason=exc.reason,
                )
                next_retry_at = due if not next_retry_at else min(next_retry_at, due)
                continue
            if event is None:
                rejected += 1
                invalidated_observation_id = ""
                if existing_link is not None:
                    invalidated_observation_id = _invalidate_linked_observation(
                        conn, str(existing_link["observation_id"]),
                    )
                if invalidated_observation_id:
                    invalidated += 1
                    affected.discard(invalidated_observation_id)
                    observations[:] = [
                        item for item in observations
                        if str(item["observation_id"]) != invalidated_observation_id
                    ]
                conn.execute(
                    """INSERT OR IGNORE INTO memory_observation_event_decisions(
                        event_id,outcome,observation_id,decided_at
                    ) VALUES(?,'rejected','',?)""",
                    (raw_event_id, stamp),
                )
                conn.execute(
                    "DELETE FROM memory_observation_event_retries WHERE event_id=?",
                    (raw_event_id,),
                )
                continue
            # Exact canonical matches use an indexed owner-filtered lookup over
            # the whole partition.  The bounded in-memory list is only for the
            # conservative similarity fallback, so its row budget cannot split
            # an already known exact cluster.
            exact = conn.execute(
                f"""SELECT * FROM memory_observations o
                    WHERE {observation_owner_sql} AND o.status='active'
                      AND o.topic=? AND o.cluster_key=? AND o.expires_at>?
                    ORDER BY o.created_at,o.observation_id LIMIT 1""",
                (
                    *observation_owner_params, event["topic"],
                    event["cluster_key"], stamp,
                ),
            ).fetchone()
            if existing_link is not None:
                linked = conn.execute(
                    "SELECT * FROM memory_observations WHERE observation_id=?",
                    (str(existing_link["observation_id"]),),
                ).fetchone()
                observation = dict(linked) if linked is not None else None
            else:
                observation = dict(exact) if exact is not None else _best_observation(
                    observations, event["topic"], event["normalized"], threshold,
                )
            if observation is None:
                observation_id = "obs_" + _sha(
                    partition + "\0" + event["event_id"]
                )[:24]
                conn.execute(
                    """INSERT OR IGNORE INTO memory_observations(
                        observation_id,owner_bot_id,owner_chat_hash,
                        owner_session_hash,visibility_scope,project_id,topic,
                        cluster_normalized,cluster_key,content,normalized_content,
                        content_hash,representative_event_id,
                        created_at,updated_at,expires_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        observation_id, principal["bot_id"], principal["chat_hash"],
                        principal["session_hash"], selected_scope, selected_project,
                        event["topic"], event["normalized"], event["cluster_key"],
                        event["content"], event["normalized"],
                        _sha(event["content"]), event["event_id"], stamp, stamp,
                        event["expires_at"],
                    ),
                )
                stored = conn.execute(
                    "SELECT * FROM memory_observations WHERE observation_id=?",
                    (observation_id,),
                ).fetchone()
                if stored is None:
                    rejected += 1
                    continue
                observation = dict(stored)
                observations.append(observation)
                created += 1
            cursor = conn.execute(
                """INSERT OR IGNORE INTO memory_observation_events(
                    event_id,observation_id,linked_at
                ) VALUES(?,?,?)""",
                (event["event_id"], observation["observation_id"], stamp),
            )
            if cursor.rowcount:
                accepted += 1
                affected.add(str(observation["observation_id"]))
            elif existing_link is not None:
                affected.add(str(observation["observation_id"]))
            conn.execute(
                """INSERT OR IGNORE INTO memory_observation_event_decisions(
                    event_id,outcome,observation_id,decided_at
                ) VALUES(?,'linked',?,?)""",
                (
                    event["event_id"], str(observation["observation_id"]), stamp,
                ),
            )
            conn.execute(
                "DELETE FROM memory_observation_event_retries WHERE event_id=?",
                (event["event_id"],),
            )

        versions_created = 0
        deleted_empty = 0
        for observation_id in sorted(affected):
            observation = conn.execute(
                "SELECT * FROM memory_observations WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
            if observation is None:
                continue
            raw_support = _support_rows(
                conn, observation_id, event_owner_sql, event_owner_params, stamp,
            )
            safe_support: list[dict[str, Any]] = []
            support_deferred = False
            for support_row in raw_support:
                try:
                    safe = _safe_event(provider, module, support_row)
                except _RetryableEventGuard as exc:
                    support_deferred = True
                    due = _defer_event(
                        conn, str(support_row["event_id"]), stamp=stamp,
                        reason=exc.reason,
                    )
                    next_retry_at = due if not next_retry_at else min(next_retry_at, due)
                    continue
                if safe is not None:
                    safe_support.append(safe)
            if support_deferred:
                continue
            if not safe_support:
                conn.execute(
                    "DELETE FROM memory_observations WHERE observation_id=?",
                    (observation_id,),
                )
                deleted_empty += 1
                continue
            versions_created += int(_write_version(
                conn, observation, safe_support, stamp=stamp,
            ))
        pruned = pre_pruned + prune_observations(
            provider, conn=conn, scope=selected_scope,
            project_id=selected_project, session_id=session_id,
        )
    return {
        "scope": selected_scope,
        "project_id": selected_project if selected_scope == "project" else "",
        "events_scanned": len(rows),
        "events_linked": accepted,
        "events_rejected": rejected,
        "events_deferred": deferred,
        "next_retry_at": next_retry_at,
        "observations_created": created,
        "observations_invalidated": invalidated,
        "versions_created": versions_created,
        "empty_deleted": deleted_empty,
        "pruned": pruned,
        "similarity_threshold": threshold,
    }


def _evidence_ids(
    conn: sqlite3.Connection,
    version_id: str,
    representative_event_id: str,
    principal: dict[str, str],
    scope: str,
    project_id: str,
    stamp: int,
) -> list[str]:
    owner_sql, owner_params = _events._event_owner_sql(
        "e", principal, scope, project_id,
    )
    cap = _bounded_int("MEMORY_WIKI_OBSERVATION_EVIDENCE_IDS", 32, 1, 128)
    keep_oldest = max(0, cap - 1)
    values = [
        str(row["event_id"])
        for row in conn.execute(
            f"""SELECT ove.event_id FROM memory_observation_version_events ove
                JOIN memory_events e ON e.event_id=ove.event_id
                WHERE ove.version_id=? AND ove.event_id<>?
                  AND {owner_sql} AND e.expires_at>?
                ORDER BY ove.evidence_order,ove.event_id LIMIT ?""",
            (
                version_id, representative_event_id, *owner_params, stamp,
                keep_oldest,
            ),
        ).fetchall()
    ]
    representative = conn.execute(
        f"""SELECT ove.event_id FROM memory_observation_version_events ove
            JOIN memory_events e ON e.event_id=ove.event_id
            WHERE ove.version_id=? AND ove.event_id=?
              AND {owner_sql} AND e.expires_at>? LIMIT 1""",
        (version_id, representative_event_id, *owner_params, stamp),
    ).fetchone()
    if representative is not None:
        values.append(str(representative["event_id"]))
    return [value for value in values if _SAFE_EVENT_ID_RE.fullmatch(value)]


def _validated_current_version(
    conn: sqlite3.Connection,
    provider: Any,
    module: Any,
    row: Any,
    principal: dict[str, str],
    scope: str,
    project_id: str,
    stamp: int,
) -> Any | None:
    """Bind a materialization to its version and re-guard every counted source.

    Guard decisions are policy snapshots, not permanent attestations.  The
    current policy must accept every event counted in support/confidence before
    a query can expose the observation or any evidence ID.
    """
    observation_id = str(row["observation_id"] or "")
    version_id = str(row["current_version_id"] or "")
    version = conn.execute(
        """SELECT * FROM memory_observation_versions
           WHERE version_id=? AND observation_id=? LIMIT 1""",
        (version_id, observation_id),
    ).fetchone()
    if version is None:
        return None

    text_fields = (
        "content", "normalized_content", "content_hash", "topic",
        "cluster_key", "representative_event_id",
    )
    integer_fields = (
        "support_count", "independent_support_count", "first_seen", "last_seen",
    )
    if any(str(row[field]) != str(version[field]) for field in text_fields):
        return None
    if any(int(row[field]) != int(version[field]) for field in integer_fields):
        return None
    if not math.isclose(
        float(row["confidence"]), float(version["confidence"]),
        rel_tol=0.0, abs_tol=1e-12,
    ):
        return None
    if int(version["evidence_total"]) != int(version["support_count"]):
        return None

    event_owner_sql, event_owner_params = _events._event_owner_sql(
        "e", principal, scope, project_id,
    )
    expected_support = int(version["support_count"])
    # The consolidation path has a hard 20k support ceiling.  Count before the
    # bounded read so injected extra links cannot hide behind LIMIT.
    total_links = int(conn.execute(
        "SELECT COUNT(*) FROM memory_observation_events WHERE observation_id=?",
        (observation_id,),
    ).fetchone()[0])
    live_owned_links = int(conn.execute(
        f"""SELECT COUNT(*) FROM memory_observation_events oe
            JOIN memory_events e ON e.event_id=oe.event_id
            WHERE oe.observation_id=? AND {event_owner_sql} AND e.expires_at>?""",
        (observation_id, *event_owner_params, stamp),
    ).fetchone()[0])
    if total_links != expected_support or live_owned_links != expected_support:
        return None

    raw_support = _support_rows(
        conn, observation_id, event_owner_sql, event_owner_params, stamp,
    )
    if len(raw_support) != expected_support:
        return None

    safe_support: list[dict[str, Any]] = []
    for raw_event in raw_support:
        event_id = str(raw_event["event_id"])
        try:
            safe_event = _safe_event(provider, module, raw_event)
        except _RetryableEventGuard as exc:
            # Fail closed now and schedule the already-linked event for a later
            # maintenance recheck.  Its immutable linked decision deliberately
            # remains intact until policy/runtime can make a permanent choice.
            with conn:
                _defer_event(conn, event_id, stamp=stamp, reason=exc.reason)
            return None
        if safe_event is None:
            # A permanent policy rejection invalidates every version that
            # counted this event.  Release sibling decisions so maintenance can
            # rebuild from only the remaining live, currently safe evidence.
            with conn:
                _invalidate_linked_observation(conn, observation_id)
                conn.execute(
                    """INSERT OR IGNORE INTO memory_observation_event_decisions(
                        event_id,outcome,observation_id,decided_at
                    ) VALUES(?,'rejected','',?)""",
                    (event_id, stamp),
                )
                conn.execute(
                    "DELETE FROM memory_observation_event_retries WHERE event_id=?",
                    (event_id,),
                )
            return None
        safe_support.append(safe_event)

    ordered = sorted(
        safe_support,
        key=lambda event: (
            event["occurred_at"], event["observed_at"],
            event["created_at"], event["event_id"],
        ),
    )
    if not ordered:
        return None
    representative = ordered[-1]
    event_ids = [event["event_id"] for event in ordered]
    independent_keys = {
        "turn:" + event["turn_id"]
        if event["turn_id"] else "source:" + event["cluster_key"]
        for event in ordered
    }
    first_seen = min(event["occurred_at"] or event["observed_at"] for event in ordered)
    last_seen = max(event["occurred_at"] or event["observed_at"] for event in ordered)
    confidence = _confidence(len(independent_keys))
    if representative["topic"] in _RAW_EXACT_ONLY_TOPICS:
        confidence = min(confidence, 0.35)
    digest_payload = {
        "event_ids": event_ids,
        "content_hash": _sha(representative["content"]),
        "topic": representative["topic"],
        "cluster_key": representative["cluster_key"],
        "representative_event_id": representative["event_id"],
        "support_count": len(event_ids),
        "independent_support_count": len(independent_keys),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "confidence": confidence,
        "status": "active",
    }
    evidence_digest = _sha(json.dumps(
        digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ))
    expected = {
        "content": representative["content"],
        "normalized_content": representative["normalized"],
        "content_hash": _sha(representative["content"]),
        "topic": representative["topic"],
        "cluster_key": representative["cluster_key"],
        "representative_event_id": representative["event_id"],
        "support_count": len(event_ids),
        "independent_support_count": len(independent_keys),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "evidence_digest": evidence_digest,
    }
    for field, expected_value in expected.items():
        actual = version[field]
        if isinstance(expected_value, int):
            if int(actual) != expected_value:
                return None
        elif str(actual) != str(expected_value):
            return None
    if not math.isclose(
        float(version["confidence"]), float(confidence),
        rel_tol=0.0, abs_tol=1e-12,
    ):
        return None
    return version


def query_observations(
    provider: Any,
    module: Any,
    query: str = "",
    limit: int = 8,
    *,
    scope: str = "chat",
    project_id: str = "",
    session_id: str = "",
    include_superseded: bool = False,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Query one exact owner partition, applying SQL ownership before LIMIT."""
    started = time.perf_counter()
    if not enabled():
        result: dict[str, Any] = {"enabled": False, "observations": []}
        if include_diagnostics:
            result["diagnostics"] = {
                "candidates": 0,
                "guard_rejected": 0,
                "hash_rejected": 0,
                "integrity_rejected": 0,
                "missing_evidence": 0,
                "search_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        return result
    principal, selected_scope, selected_project = _events._resolve_scope(
        provider, session_id=session_id, scope=scope, project_id=project_id,
    )
    conn = provider._connect()
    _require_schema(conn)
    requested_limit = max(1, min(int(limit), 50))
    owner_sql, owner_params = _events._event_owner_sql(
        "o", principal, selected_scope, selected_project,
    )
    stamp = int(time.time())
    status_sql = "o.status IN ('active','superseded')" if include_superseded else "o.status='active'"
    candidates: list[Any] = []
    seen: set[str] = set()
    expression_query = str(query or "").strip()
    candidate_limit = min(400, max(40, requested_limit * 8))
    if expression_query:
        for mode in ("and", "or"):
            expression = _events._fts_expression(module, expression_query, mode)
            if not expression:
                continue
            rows = conn.execute(
                f"""SELECT o.*,bm25(memory_observations_fts) AS fts_rank
                    FROM memory_observations_fts
                    JOIN memory_observations o
                      ON o.observation_id=memory_observations_fts.observation_id
                    WHERE memory_observations_fts MATCH ? AND {owner_sql}
                      AND {status_sql} AND o.expires_at>?
                    ORDER BY fts_rank,o.last_seen DESC,o.observation_id LIMIT ?""",
                (expression, *owner_params, stamp, candidate_limit),
            ).fetchall()
            for row in rows:
                observation_id = str(row["observation_id"])
                if observation_id not in seen:
                    seen.add(observation_id)
                    candidates.append(row)
            # Validate after retrieval.  Even when raw AND hits fill the user
            # limit, all of them may fail hash/guard/evidence checks; collect the
            # bounded OR fallback now so safe rows can backfill the result.
    else:
        candidates = conn.execute(
            f"""SELECT o.*,NULL AS fts_rank FROM memory_observations o
                WHERE {owner_sql} AND {status_sql} AND o.expires_at>?
                ORDER BY o.last_seen DESC,o.observation_id LIMIT ?""",
            (*owner_params, stamp, candidate_limit),
        ).fetchall()

    output: list[dict[str, Any]] = []
    guard_rejected = 0
    hash_rejected = 0
    integrity_rejected = 0
    missing_evidence = 0
    for row in candidates:
        content = str(row["content"] or "")
        if _sha(content) != str(row["content_hash"] or ""):
            hash_rejected += 1
            continue
        try:
            if module.secret_scan(content).get("raw_secret"):
                guard_rejected += 1
                continue
            checked = provider._inspect_recall_text(
                content,
                source="observation:derived_event_evidence",
                mem_type="observation",
                item_id=str(row["observation_id"]),
                audit=False,
                max_len=_bounded_int(
                    "MEMORY_WIKI_OBSERVATION_RECALL_CONTENT", 1600, 128, 4000
                ),
            )
        except Exception:
            guard_rejected += 1
            continue
        if checked.get("status") != "safe":
            guard_rejected += 1
            continue
        safe_content = str(checked.get("content") or "").strip()
        if not safe_content:
            guard_rejected += 1
            continue
        try:
            if module.secret_scan(safe_content).get("raw_secret"):
                guard_rejected += 1
                continue
        except Exception:
            guard_rejected += 1
            continue
        version = _validated_current_version(
            conn, provider, module, row, principal, selected_scope,
            selected_project, stamp,
        )
        if version is None:
            integrity_rejected += 1
            continue
        evidence_ids = _evidence_ids(
            conn, str(row["current_version_id"]),
            str(version["representative_event_id"]), principal,
            selected_scope, selected_project, stamp,
        )
        if not evidence_ids:
            missing_evidence += 1
            continue
        output.append({
            "observation_id": str(row["observation_id"]),
            "version_id": str(row["current_version_id"]),
            "content": safe_content,
            "content_hash": str(row["content_hash"]),
            "evidence_digest": str(version["evidence_digest"]),
            "topic": str(row["topic"]),
            "support_count": int(row["support_count"]),
            "independent_support_count": int(row["independent_support_count"]),
            "confidence": float(row["confidence"]),
            "first_seen": int(row["first_seen"]),
            "last_seen": int(row["last_seen"]),
            "status": str(row["status"]),
            "scope": str(row["visibility_scope"]),
            "project_id": str(row["project_id"]) if selected_scope == "project" else "",
            "evidence_event_ids": evidence_ids,
            "evidence_event_total": int(version["evidence_total"]),
            "evidence_event_ids_truncated": bool(version["evidence_truncated"])
            or len(evidence_ids) < int(version["evidence_total"]),
            "trust_level": "derived_unverified",
            "source": "memory_event_consolidation",
            "merge_policy": (
                "exact_only_low_confidence"
                if str(row["topic"]) in _RAW_EXACT_ONLY_TOPICS
                else "deterministic_surface_equivalence"
            ),
        })
        if len(output) >= requested_limit:
            break
    result: dict[str, Any] = {
        "enabled": True,
        "scope": selected_scope,
        "project_id": selected_project if selected_scope == "project" else "",
        "observations": output,
    }
    if include_diagnostics:
        result["diagnostics"] = {
            "candidates": len(candidates),
            "guard_rejected": guard_rejected,
            "hash_rejected": hash_rejected,
            "integrity_rejected": integrity_rejected,
            "missing_evidence": missing_evidence,
            "search_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    return result


def delete_observations(
    provider: Any,
    *,
    scope: str = "chat",
    project_id: str = "",
    session_id: str = "",
) -> int:
    """Delete every observation in one exact provider-owned partition."""
    principal, selected_scope, selected_project = _events._resolve_scope(
        provider, session_id=session_id, scope=scope, project_id=project_id,
    )
    conn = provider._connect()
    _require_schema(conn)
    owner_sql, owner_params = _events._event_owner_sql(
        "memory_observations", principal, selected_scope, selected_project,
    )
    with conn:
        cursor = conn.execute(
            f"DELETE FROM memory_observations WHERE {owner_sql}", owner_params,
        )
    return max(0, int(cursor.rowcount))


def prune_observations(
    provider: Any,
    *,
    conn: sqlite3.Connection | None = None,
    scope: str = "chat",
    project_id: str = "",
    session_id: str = "",
) -> int:
    """Apply retention within one visibility partition, preserving peer chats."""
    principal, selected_scope, selected_project = _events._resolve_scope(
        provider, scope=scope, project_id=project_id, session_id=session_id,
    )
    owner_sql, owner_params = _events._event_owner_sql(
        "", principal, selected_scope, selected_project,
    )
    database = conn or provider._connect()
    _require_schema(database)
    before = int(database.execute(
        f"SELECT COUNT(*) FROM memory_observations WHERE {owner_sql}", owner_params,
    ).fetchone()[0])
    stamp = int(time.time())
    expired_ids = [
        str(row["observation_id"])
        for row in database.execute(
            f"""SELECT observation_id FROM memory_observations
               WHERE {owner_sql} AND expires_at<=?""",
            (*owner_params, stamp),
        ).fetchall()
    ]
    if expired_ids:
        # Release the decisions for every sibling before removing the stale
        # materialization. SQLite builds can cap bound variables at 999;
        # large simultaneous expiry must not abort retention maintenance.
        for offset in range(0, len(expired_ids), 400):
            batch = expired_ids[offset:offset + 400]
            placeholders = ",".join("?" for _ in batch)
            database.execute(
                f"DELETE FROM memory_observation_event_decisions "
                f"WHERE observation_id IN ({placeholders})",
                tuple(batch),
            )
            database.execute(
                f"DELETE FROM memory_observations "
                f"WHERE observation_id IN ({placeholders})",
                tuple(batch),
            )
    max_rows = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_MAX_ROWS", 10000, 1, 100000
    )
    max_bytes = _bounded_int(
        "MEMORY_WIKI_OBSERVATION_MAX_BYTES", 16_000_000, 16384, 128_000_000
    )
    database.execute(
        f"""DELETE FROM memory_observations WHERE observation_id IN (
            SELECT observation_id FROM (
                SELECT observation_id,
                  ROW_NUMBER() OVER (
                    ORDER BY last_seen DESC,updated_at DESC,rowid DESC
                  ) AS n,
                  SUM(LENGTH(CAST(content AS BLOB))) OVER (
                    ORDER BY last_seen DESC,updated_at DESC,rowid DESC
                  ) AS bytes
                FROM memory_observations WHERE {owner_sql}
            ) WHERE n>? OR bytes>?
        )""",
        (*owner_params, max_rows, max_bytes),
    )
    after = int(database.execute(
        f"SELECT COUNT(*) FROM memory_observations WHERE {owner_sql}", owner_params,
    ).fetchone()[0])
    if conn is None:
        database.commit()
    return max(0, before - after)
