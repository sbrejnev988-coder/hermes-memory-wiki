"""Host-supplied OCR evidence for screenshots and images.

This module never opens an image, stores pixels, or calls a vision service. A
trusted Hermes host can supply text it already derived from an image. The text
remains unverified event evidence; a digest identifies its source for deletion.
The API is deliberately absent from model-callable tools.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

try:
    from . import memory_events as _events
except ImportError:  # pragma: no cover - standalone plugin loading
    import memory_events as _events


_DIGEST = re.compile(r"^[a-fA-F0-9]{64}$")
_ENGINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_MEDIA = frozenset({"image/png", "image/jpeg", "image/webp", "image/tiff", "image/bmp"})


def enabled() -> bool:
    """Accept derived visual text only when the host explicitly opts in."""
    import os

    return os.environ.get("MEMORY_WIKI_VISUAL_EVIDENCE_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def install_schema(conn: sqlite3.Connection) -> None:
    """Index source digests without persisting an asset path or image bytes."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS visual_evidence_sources(
            event_id TEXT PRIMARY KEY,
            asset_sha256 TEXT NOT NULL CHECK(length(asset_sha256)=64),
            media_type TEXT NOT NULL,
            ocr_engine TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES memory_events(event_id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visual_evidence_source "
        "ON visual_evidence_sources(asset_sha256,event_id)"
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS visual_evidence_sources_no_update
        BEFORE UPDATE ON visual_evidence_sources BEGIN
          SELECT RAISE(ABORT,'visual_evidence_sources is append-only');
        END"""
    )
    # The event ledger also has a delete trigger for SQLite configurations in
    # which foreign-key enforcement was disabled by an older host.
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS visual_evidence_event_delete
        AFTER DELETE ON memory_events BEGIN
          DELETE FROM visual_evidence_sources WHERE event_id=OLD.event_id;
        END"""
    )


def _digest(value: str) -> str:
    selected = str(value or "").strip().lower()
    if not _DIGEST.fullmatch(selected):
        raise ValueError("asset_sha256 must be a SHA-256 hex digest")
    return selected


def _bump_recall_partition(
    provider: Any, conn: sqlite3.Connection, principal: dict[str, str],
    scope: str, project_id: str,
) -> None:
    conn.execute(
        "UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) "
        "WHERE key='cache_state_revision'"
    )
    if scope == "chat":
        partition = provider._cache_component_partition(
            "chat", origin_bot_id=principal["bot_id"],
            origin_chat_hash=principal["chat_hash"],
        )
    elif scope == "bot":
        partition = provider._cache_component_partition(
            "bot", origin_bot_id=principal["bot_id"],
        )
    else:
        partition = provider._cache_component_partition(
            "project", project_id=project_id,
        )
    provider._bump_cache_component_revision(conn, partition)


def capture_host_ocr(
    provider: Any,
    module: Any,
    text: str,
    *,
    asset_sha256: str,
    media_type: str,
    ocr_engine: str,
    scope: str = "chat",
    occurred_at: int | None = None,
    ttl_days: int | None = None,
) -> str | None:
    """Store OCR text as untrusted evidence, never as a verified claim.

    ``asset_sha256`` is supplied by the host and is source identity, not proof
    that this process inspected the pixels. The complete OCR text passes the
    event ledger's secret scan and prompt-injection guard before truncation.
    ``None`` means disabled or rejected by those guards.
    """
    if not enabled() or not _events.enabled():
        return None
    digest = _digest(asset_sha256)
    selected_media = str(media_type or "").strip().lower()
    if selected_media not in _MEDIA:
        raise ValueError("unsupported image media_type")
    selected_engine = str(ocr_engine or "").strip()
    if not _ENGINE.fullmatch(selected_engine):
        raise ValueError("invalid ocr_engine label")
    if module.secret_scan(selected_engine).get("raw_secret"):
        raise ValueError("ocr_engine label contains secret-like material")
    if not isinstance(text, str):
        raise TypeError("OCR evidence must be text")
    if not text.strip():
        return None
    # Resolve scope before capture to fail early on a missing project or
    # ambiguous fallback bot. Owners are always derived from provider state.
    principal, selected_scope, project_id = _events._resolve_scope(
        provider, scope=scope,
    )
    def register_source(conn: sqlite3.Connection, event_id: str) -> None:
        # The event ledger invokes this inside the same write transaction.
        # A crash or callback failure can therefore never leave OCR text
        # recallable without its deletion key.
        conn.execute(
            "INSERT INTO visual_evidence_sources"
            "(event_id,asset_sha256,media_type,ocr_engine) VALUES(?,?,?,?)",
            (event_id, digest, selected_media, selected_engine),
        )
        _bump_recall_partition(
            provider, conn, principal, selected_scope, project_id,
        )

    event_id = _events.capture_event(
        provider,
        module,
        text,
        role="host_ocr",
        event_type="visual_ocr",
        modality="image_ocr_text",
        scope=scope,
        occurred_at=occurred_at,
        ttl_days=ttl_days,
        provenance={
            "derivation": "host_supplied_ocr_text",
            "verification": "unverified_host_report",
            # A short reference is sufficient in model-facing provenance.
            # The full integrity digest stays in the host-only source index.
            "asset_ref": digest[:16],
            "media_type": selected_media,
            "ocr_engine": selected_engine,
            "image_bytes_retained": False,
        },
        _after_insert=register_source,
    )
    if not event_id:
        return None
    # Per-owner retention may evict an oversized event during capture. In
    # that case the source registry has already been removed by its trigger.
    retained = provider._connect().execute(
        "SELECT 1 FROM visual_evidence_sources WHERE event_id=?", (event_id,),
    ).fetchone()
    return event_id if retained else None


def delete_host_ocr_source(
    provider: Any,
    *,
    asset_sha256: str,
    scope: str = "chat",
) -> dict[str, int]:
    """Erase all OCR evidence for one source in exactly one owned partition.

    Deleting the source events also removes FTS entries and any derived
    observation versions through the existing event privacy triggers.
    """
    digest = _digest(asset_sha256)
    principal, selected_scope, project_id = _events._resolve_scope(
        provider, scope=scope,
    )
    owner_sql, owner_params = _events._event_owner_sql(
        "e", principal, selected_scope, project_id,
    )
    conn = provider._connect()
    with conn:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"""SELECT e.event_id FROM visual_evidence_sources v
                JOIN memory_events e ON e.event_id=v.event_id
                WHERE v.asset_sha256=? AND e.event_type='visual_ocr'
                  AND e.modality='image_ocr_text' AND {owner_sql}
                ORDER BY e.event_id""",
            (digest, *owner_params),
        ).fetchall()
        event_ids = [str(row[0]) for row in rows]
        observation_ids: set[str] = set()
        for offset in range(0, len(event_ids), 400):
            chunk = event_ids[offset:offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            observation_ids.update(str(row[0]) for row in conn.execute(
                "SELECT DISTINCT observation_id "
                "FROM memory_observation_events WHERE event_id IN ("
                + placeholders + ")",
                tuple(chunk),
            ).fetchall())
            conn.execute(
                "DELETE FROM memory_events WHERE event_id IN ("
                + placeholders + ")",
                tuple(chunk),
            )
        if event_ids:
            # Invalidate the same visibility partition used by normal event
            # removal; otherwise a cached recall could outlive the deletion.
            _bump_recall_partition(
                provider, conn, principal, selected_scope, project_id,
            )
    return {
        "events_deleted": len(event_ids),
        "observations_deleted": len(observation_ids),
    }
