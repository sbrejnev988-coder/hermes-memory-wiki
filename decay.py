#!/usr/bin/env python3
"""ACT-R style decay scanner for Hermes Memory Wiki.

Archival itself must be executed by the provider callback so SQLite, FTS,
Qdrant outbox, mutation ledger and audit log remain consistent.
"""
from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULT_DB = Path(__file__).resolve().parent / "memory_wiki.sqlite3"


def _days_since(timestamp: int) -> float:
    return max(0.0, (int(time.time()) - int(timestamp or 0)) / 86400.0)


def _decay_factor(
    days: float,
    confidence: float = 0.7,
    salience: float = 0.7,
    access_count: int = 0,
) -> float:
    quality = max(0.0, confidence) * max(0.0, salience)
    decay_rate = 0.015 / max(0.3, quality)
    access_boost = math.log1p(max(0, access_count)) * 0.05
    return max(0.0, 1.0 - decay_rate * max(0.0, days) + access_boost)


def scan_decay(db_path=None, threshold: float = 0.15) -> List[Dict[str, Any]]:
    threshold = max(0.0, min(1.0, float(threshold)))
    with sqlite3.connect(str(db_path or DEFAULT_DB)) as database:
        database.row_factory = sqlite3.Row
        rows = database.execute(
            """
            SELECT id, topic, confidence, salience, access_count, status,
                   updated_at, freshness_at, pinned
              FROM claims
             WHERE status='active'
            """
        ).fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        days = _days_since(int(row["freshness_at"] or row["updated_at"] or 0))
        factor = _decay_factor(
            days,
            float(row["confidence"] or 0.7),
            float(row["salience"] or 0.7),
            int(row["access_count"] or 0),
        )
        if factor < threshold:
            results.append(dict(row, days=round(days, 1), decay=round(factor, 4)))
    return sorted(results, key=lambda item: item["decay"])


def archive_stale_claims(
    db_path=None,
    threshold: float = 0.05,
    dry_run: bool = True,
    archive_callback: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Select stale claims and delegate archival to the provider transaction."""
    stale = scan_decay(db_path, threshold)
    ids = [
        item["id"]
        for item in stale
        if not int(item.get("pinned") or 0)
        and float(item.get("confidence") or 0.0) < 0.7
    ]
    protected_ids = [item["id"] for item in stale if item["id"] not in set(ids)]
    result: Dict[str, Any] = {
        "stale": len(stale),
        "eligible": len(ids),
        "protected": len(protected_ids),
        "protected_ids": protected_ids[:50],
        "dry_run": bool(dry_run),
        "ids": ids[:50],
    }
    if dry_run or not ids:
        return result
    if archive_callback is None:
        result.update(
            {
                "archived": 0,
                "error": "archive_callback is required to preserve FTS/Qdrant consistency",
            }
        )
        return result
    archived = archive_callback(
        ids,
        reason=f"decay_score_below_{float(threshold):.4f}",
        change_type="decay_archive",
    )
    result["archived"] = int(archived or 0)
    return result


def get_decay_stats(db_path=None) -> Dict[str, Any]:
    with sqlite3.connect(str(db_path or DEFAULT_DB)) as database:
        database.row_factory = sqlite3.Row
        row = database.execute(
            """
            SELECT count(*) AS total,
                   avg(confidence) AS avg_conf,
                   avg(salience) AS avg_sal,
                   avg(access_count) AS avg_access,
                   max(freshness_at) AS newest,
                   min(freshness_at) AS oldest
              FROM claims
             WHERE status='active'
            """
        ).fetchone()
    return dict(row) if row is not None else {}
