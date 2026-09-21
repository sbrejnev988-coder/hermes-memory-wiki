"""Small, content-free daily aggregates for live memory retrieval.

This table is operational telemetry, not memory evidence.  Its dimensions are
fixed in code: callers cannot persist queries, document names, owner IDs,
trace IDs, exception messages, or arbitrary labels through this API.
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any


OPERATIONS = frozenset({"prefetch", "recall"})
OUTCOMES = frozenset({
    "hit", "empty", "timeout_fallback", "error_fallback", "error",
})
BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000,
              10000, 30000, 60000, 300000)
MAX_DURATION_MS = BUCKETS_MS[-1]


def enabled() -> bool:
    """Enable privacy-preserving aggregates by default; opt out explicitly."""
    return os.environ.get("MEMORY_WIKI_ONLINE_METRICS_ENABLED", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def retention_days() -> int:
    try:
        days = int(os.environ.get("MEMORY_WIKI_ONLINE_METRICS_DAYS", "30"))
    except (TypeError, ValueError):
        days = 30
    return max(1, min(days, 90))


def install_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_online_metrics(
            day_utc INTEGER NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('prefetch','recall')),
            outcome TEXT NOT NULL CHECK(outcome IN (
                'hit','empty','timeout_fallback','error_fallback','error'
            )),
            latency_bucket_ms INTEGER NOT NULL CHECK(latency_bucket_ms BETWEEN 0 AND 300000),
            sample_count INTEGER NOT NULL CHECK(sample_count >= 1),
            duration_sum_ms INTEGER NOT NULL CHECK(duration_sum_ms >= 0),
            duration_max_ms INTEGER NOT NULL CHECK(duration_max_ms >= 0),
            PRIMARY KEY (day_utc, operation, outcome, latency_bucket_ms)
        )"""
    )


def _duration(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid metric duration") from exc
    if not math.isfinite(numeric):
        raise ValueError("invalid metric duration")
    return max(0, min(int(round(numeric)), MAX_DURATION_MS))


def _bucket(duration_ms: int) -> int:
    return next(bound for bound in BUCKETS_MS if duration_ms <= bound)


def record(
    conn: sqlite3.Connection,
    operation: str,
    outcome: str,
    duration_ms: Any,
    *,
    timestamp: int | None = None,
) -> None:
    """Record one sample using only validated enum dimensions and integers."""
    if operation not in OPERATIONS or outcome not in OUTCOMES:
        raise ValueError("unknown online metric dimension")
    duration = _duration(duration_ms)
    day = int(time.time() if timestamp is None else timestamp) // 86400
    with conn:
        conn.execute(
            """INSERT INTO memory_online_metrics(
                day_utc,operation,outcome,latency_bucket_ms,sample_count,
                duration_sum_ms,duration_max_ms
            ) VALUES(?,?,?,?,1,?,?)
            ON CONFLICT(day_utc,operation,outcome,latency_bucket_ms) DO UPDATE SET
                sample_count=sample_count+1,
                duration_sum_ms=duration_sum_ms+excluded.duration_sum_ms,
                duration_max_ms=max(duration_max_ms,excluded.duration_max_ms)""",
            (day, operation, outcome, _bucket(duration), duration, duration),
        )
        conn.execute(
            "DELETE FROM memory_online_metrics WHERE day_utc<?",
            (day - retention_days() + 1,),
        )


def record_path(db_path: str | Path, operation: str, outcome: str, duration_ms: Any) -> bool:
    """Best-effort write that never extends the retrieval critical path on lock.

    A dedicated short-lived connection avoids committing a caller's pending
    memory transaction.  An unavailable metrics table or a busy database drops
    this sample rather than changing the recall result.
    """
    if not enabled():
        return False
    path = Path(db_path)
    if not path.is_file():
        return False
    try:
        with closing(sqlite3.connect(str(path), timeout=0.05)) as conn:
            conn.execute("PRAGMA busy_timeout=50")
            record(conn, operation, outcome, duration_ms)
        return True
    except (sqlite3.Error, OSError, ValueError):
        return False


def _percentile_bucket(rows: list[sqlite3.Row], total: int, fraction: float) -> int:
    target = max(1, math.ceil(total * fraction))
    seen = 0
    for row in sorted(rows, key=lambda item: int(item["latency_bucket_ms"])):
        seen += int(row["sample_count"])
        if seen >= target:
            return int(row["latency_bucket_ms"])
    return 0


def snapshot(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
    timestamp: int | None = None,
) -> dict[str, Any]:
    """Return aggregate counts and upper-bound latency percentiles only."""
    window = max(1, min(int(days), retention_days()))
    day = int(time.time() if timestamp is None else timestamp) // 86400
    try:
        raw_rows = conn.execute(
            """SELECT operation,outcome,latency_bucket_ms,
                      sum(sample_count) sample_count,
                      sum(duration_sum_ms) duration_sum_ms,
                      max(duration_max_ms) duration_max_ms
               FROM memory_online_metrics WHERE day_utc>=? AND day_utc<=?
               GROUP BY operation,outcome,latency_bucket_ms""",
            (day - window + 1, day),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        raw_rows = []
    columns = (
        "operation", "outcome", "latency_bucket_ms", "sample_count",
        "duration_sum_ms", "duration_max_ms",
    )
    rows = [dict(zip(columns, row)) for row in raw_rows]
    result: dict[str, Any] = {"window_days": window, "operations": {}}
    for operation in sorted(OPERATIONS):
        selected = [row for row in rows if row["operation"] == operation]
        count = sum(int(row["sample_count"]) for row in selected)
        result["operations"][operation] = {
            "samples": count,
            "outcomes": {
                outcome: sum(int(row["sample_count"]) for row in selected
                             if row["outcome"] == outcome)
                for outcome in sorted(OUTCOMES)
            },
            "latency_p50_upper_ms": _percentile_bucket(selected, count, 0.50),
            "latency_p95_upper_ms": _percentile_bucket(selected, count, 0.95),
            "latency_mean_ms": round(
                sum(int(row["duration_sum_ms"]) for row in selected) / count, 1
            ) if count else 0.0,
        }
    return result
