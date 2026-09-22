"""Isolated production-schema SQLite event scale probe (no live profile).

This probes the real event/FTS schema, usage triggers, retention, query API,
cold provider startup, checkpoint and privacy deletion. It bulk-loads benign
synthetic rows to avoid measuring the secret guard or model extraction. It does
not exercise Qdrant, OpenRouter, host first-token latency, or answer quality.
The temporary database is discarded when the probe exits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    from .episodic_fallback_probe import _load_plugin
except ImportError:
    from episodic_fallback_probe import _load_plugin


@contextmanager
def _isolated_settings(home: Path) -> Iterator[None]:
    settings = {
        "HERMES_HOME": str(home),
        "HERMES_SECURITY_STRICT": "0",
        "MEMORY_WIKI_SEMANTIC": "0",
        "MEMORY_WIKI_RERANK_ENABLED": "0",
        "MEMORY_WIKI_EPISODIC_ENABLED": "0",
        "MEMORY_WIKI_EVENT_LEDGER_ENABLED": "1",
        "MEMORY_WIKI_EVENT_MAX_ROWS": "10000000",
        "MEMORY_WIKI_EVENT_MAX_BYTES": "16000000000",
        "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
        "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED": "0",
        "MW_EXTRACTION_ENABLED": "0",
    }
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _percentile(values: list[float], fraction: float) -> float:
    return round(sorted(values)[max(0, int(len(values) * fraction) - 1)], 2)


def _batch(start: int, stop: int, now: int, owner: dict[str, str]):
    for index in range(start, stop):
        content = f"Synthetic periwinkle memory marker{index} has a violet lens."
        yield (
            f"evt_scale_{index:010d}", owner["bot_id"], owner["chat_hash"],
            "a" * 32, "bot", "", "", "user", "dialogue_turn", "text",
            content, hashlib.sha256(content.encode()).hexdigest(), 0,
            len(content), now, now, "{}", now + index // 1000,
            now + 365 * 86400,
        )


INSERT_SQL = """INSERT INTO memory_events(
    event_id,owner_bot_id,owner_chat_hash,owner_session_hash,
    visibility_scope,project_id,turn_id,role,event_type,modality,
    content,content_hash,truncated,source_length,occurred_at,observed_at,
    provenance_json,created_at,expires_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _db_bytes(db: Path) -> dict[str, int]:
    return {
        "database": db.stat().st_size,
        "wal": Path(str(db) + "-wal").stat().st_size
        if Path(str(db) + "-wal").exists() else 0,
    }


def _open(module: Any, home: Path):
    provider = module.MemoryWikiProvider()
    provider.initialize(
        "synthetic-session", hermes_home=str(home), bot_id="synthetic-bot",
        agent_context="trusted-host",
    )
    return provider


def run(*, rows: int = 10_000, batch_size: int = 2_000,
        repetitions: int = 5, directory: Path | None = None,
        progress_every: int = 100_000) -> dict[str, Any]:
    if not 1 <= rows <= 10_000_000:
        raise ValueError("rows must be between 1 and 10,000,000")
    if not 1 <= batch_size <= 20_000:
        raise ValueError("batch_size must be between 1 and 20,000")
    if not 1 <= repetitions <= 50:
        raise ValueError("repetitions must be between 1 and 50")
    if directory is not None and not directory.is_dir():
        raise ValueError("temporary parent directory must already exist")
    with tempfile.TemporaryDirectory(prefix="memory-wiki-scale-", dir=directory) as tmp:
        home = Path(tmp)
        with _isolated_settings(home):
            module = _load_plugin()
            provider = _open(module, home)
            try:
                conn: sqlite3.Connection = provider._connect()
                database = Path(conn.execute("PRAGMA database_list").fetchone()[2])
                owner = provider._scoped_backup_owner()
                stamp = int(time.time())
                started = time.perf_counter()
                last_progress = 0
                for offset in range(0, rows, batch_size):
                    with conn:
                        conn.executemany(
                            INSERT_SQL,
                            _batch(offset, min(offset + batch_size, rows), stamp, owner),
                        )
                    if progress_every and offset + batch_size - last_progress >= progress_every:
                        last_progress = min(offset + batch_size, rows)
                        print(f"inserted {last_progress}/{rows}", file=sys.stderr, flush=True)
                insert_seconds = round(time.perf_counter() - started, 2)
                usage = conn.execute(
                    "SELECT row_count,byte_count FROM memory_event_owner_usage "
                    "WHERE owner_bot_id=?", (owner["bot_id"],)
                ).fetchone()
                if not usage or int(usage[0]) != rows:
                    raise AssertionError("event row accounting disagrees with inserts")
                storage_before = _db_bytes(database)

                queries: dict[str, dict[str, float]] = {}
                for label, search in (
                    ("rare", f"marker{rows // 2}"), ("common", "periwinkle")
                ):
                    durations: list[float] = []
                    for _ in range(repetitions):
                        start = time.perf_counter()
                        result = module._memory_events.query_events(
                            provider, module, search, limit=5, scope="bot"
                        )
                        durations.append((time.perf_counter() - start) * 1000)
                        if label == "rare" and not result["events"]:
                            raise AssertionError("rare event was not recalled")
                    queries[label] = {
                        "p50_ms": _percentile(durations, .5),
                        "p95_ms": _percentile(durations, .95),
                    }

                start = time.perf_counter()
                removed = module._memory_events.prune_events(provider, scope="bot")
                prune_ms = round((time.perf_counter() - start) * 1000, 2)
                if removed:
                    raise AssertionError("in-limit events unexpectedly pruned")

                provider.shutdown()
                start = time.perf_counter()
                provider = _open(module, home)
                cold_start_ms = round((time.perf_counter() - start) * 1000, 2)
                conn = provider._connect()
                integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
                if integrity != "ok":
                    raise AssertionError("SQLite quick_check failed")

                erase_count = min(1000, rows)
                start = time.perf_counter()
                with conn:
                    for offset in range(0, erase_count, 500):
                        ids = [f"evt_scale_{i:010d}" for i in range(
                            offset, min(offset + 500, erase_count)
                        )]
                        conn.execute(
                            "DELETE FROM memory_events WHERE event_id IN (" +
                            ",".join("?" for _ in ids) + ")", ids,
                        )
                erase_ms = round((time.perf_counter() - start) * 1000, 2)
                retained = conn.execute(
                    "SELECT row_count FROM memory_event_owner_usage WHERE owner_bot_id=?",
                    (owner["bot_id"],),
                ).fetchone()[0]
                if retained != rows - erase_count or conn.execute(
                    "SELECT COUNT(*) FROM memory_events_fts"
                ).fetchone()[0] != retained:
                    raise AssertionError("privacy deletion left event/FTS accounting inconsistent")
                start = time.perf_counter()
                checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                checkpoint_ms = round((time.perf_counter() - start) * 1000, 2)
                if checkpoint[0]:
                    raise AssertionError("SQLite checkpoint was busy")
                return {
                    "schema": "production memory_events with FTS and usage triggers",
                    "workload": "synthetic bulk append; real guarded query API",
                    "rows": rows, "batch_size": batch_size,
                    "insert_seconds": insert_seconds,
                    "rows_per_second": round(rows / max(insert_seconds, .001), 2),
                    "stored_content_bytes": int(usage[1]),
                    "storage_before_checkpoint_bytes": storage_before,
                    "query": queries, "in_limit_prune_ms": prune_ms,
                    "cold_start_ms": cold_start_ms, "quick_check": integrity,
                    "privacy_rows_erased": erase_count,
                    "privacy_erase_ms": erase_ms,
                    "wal_checkpoint_ms": checkpoint_ms,
                    "storage_after_checkpoint_bytes": _db_bytes(database),
                    "retained_rows": int(retained),
                }
            finally:
                provider.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=2_000)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--progress-every", type=int, default=100_000)
    args = parser.parse_args()
    print(json.dumps(run(rows=args.rows, batch_size=args.batch_size,
                         repetitions=args.repetitions, directory=args.directory,
                         progress_every=args.progress_every), indent=2))
