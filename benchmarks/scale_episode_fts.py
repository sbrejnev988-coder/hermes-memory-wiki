"""Isolated episode FTS deletion probe with synthetic text only.

This exercises the production episodic schema and triggers in a disposable
SQLite database. It does not open a Hermes profile or contact Qdrant/OpenRouter.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _memory():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "episodic_memory_scale_probe", ROOT / "episodic_memory.py",
    )
    if not spec or not spec.loader:
        raise RuntimeError("episodic module unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile) - 1))
    return round(ordered[index], 3)


def run(rows: int = 100_000, deletes: int = 2_000) -> dict[str, object]:
    if not 1 <= rows <= 1_000_000:
        raise ValueError("rows must be between 1 and 1,000,000")
    if not 1 <= deletes <= rows:
        raise ValueError("deletes must be between 1 and rows")
    memory = _memory()
    with tempfile.TemporaryDirectory(prefix="memory-wiki-episode-scale-") as tmp:
        db_path = Path(tmp) / "episodes.sqlite3"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            memory.install_schema(conn)
            inserted_at = time.perf_counter()
            sql = """INSERT INTO episodic_turns(
                id,content,role,owner_bot_id,owner_chat_hash,visibility_scope,
                created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)"""
            for offset in range(0, rows, 5_000):
                with conn:
                    conn.executemany(sql, (
                        (
                            f"ep_scale_{index:010d}",
                            f"Synthetic violet relay marker{index} is available.",
                            "user", "scale-bot", "scale-chat", "chat",
                            1, 9_999_999_999,
                        ) for index in range(offset, min(rows, offset + 5_000))
                    ))
            insert_seconds = round(time.perf_counter() - inserted_at, 3)
            starting_docid = conn.execute(
                "SELECT docid FROM episodic_fts_docids "
                "WHERE episode_id='ep_scale_0000000000'"
            ).fetchone()[0]
            started = time.perf_counter()
            memory.install_schema(conn)
            schema_check_ms = round((time.perf_counter() - started) * 1000, 3)
            timings: list[float] = []
            with conn:
                for index in range(deletes):
                    started = time.perf_counter()
                    conn.execute(
                        "DELETE FROM episodic_turns WHERE id=?",
                        (f"ep_scale_{index:010d}",),
                    )
                    timings.append((time.perf_counter() - started) * 1000)
            remaining = rows - deletes
            base_count = int(conn.execute(
                "SELECT COUNT(*) FROM episodic_turns"
            ).fetchone()[0])
            mapping_count = int(conn.execute(
                "SELECT COUNT(*) FROM episodic_fts_docids"
            ).fetchone()[0])
            fts_count = int(conn.execute(
                "SELECT COUNT(*) FROM episodic_turns_fts"
            ).fetchone()[0])
            if (base_count, mapping_count, fts_count) != (remaining,) * 3:
                raise AssertionError("episode/FTS/docid counts diverged")
            surviving_id = f"ep_scale_{deletes:010d}"
            before_vacuum = conn.execute(
                "SELECT docid FROM episodic_fts_docids WHERE episode_id=?",
                (surviving_id,),
            ).fetchone()[0]
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
            after_vacuum = conn.execute(
                "SELECT docid FROM episodic_fts_docids WHERE episode_id=?",
                (surviving_id,),
            ).fetchone()[0]
            if before_vacuum != after_vacuum:
                raise AssertionError("episode docid changed after VACUUM")
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise AssertionError("SQLite quick_check failed")
            return {
                "rows": rows,
                "deletes": deletes,
                "insert_seconds": insert_seconds,
                "schema_check_ms": schema_check_ms,
                "delete_total_ms": round(sum(timings), 3),
                "delete_p50_ms": _percentile(timings, .5),
                "delete_p95_ms": _percentile(timings, .95),
                "delete_mean_ms": round(statistics.fmean(timings), 3),
                "remaining": remaining,
                "docid_stable_after_vacuum": before_vacuum == after_vacuum,
                "sample_initial_docid": int(starting_docid),
                "quick_check": "ok",
                "data_scope": "synthetic_disposable_sqlite",
            }
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--deletes", type=int, default=2_000)
    args = parser.parse_args()
    print(json.dumps(run(args.rows, args.deletes), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
