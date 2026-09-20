"""Deterministic, offline Memory Wiki startup and retrieval benchmark.

Run from the repository root: ``python benchmarks/audit_retrieval.py``.
The benchmark uses a temporary Hermes home and never reads the live memory DB.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "__init__.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_audit_benchmark", PLUGIN,
        submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _close(provider: object) -> None:
    connection = getattr(provider, "_conn", None)
    if connection is not None:
        connection.close()
        provider._conn = None


def run(size: int = 1500, repetitions: int = 30) -> dict:
    with tempfile.TemporaryDirectory(prefix="memory-wiki-audit-bench-") as tmp:
        keys = (
            "HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC",
            "MEMORY_WIKI_RERANK_ENABLED", "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE",
        )
        previous = {key: os.environ.get(key) for key in keys}
        os.environ.update({
            "HERMES_HOME": tmp,
            "HERMES_SECURITY_STRICT": "0",
            "MEMORY_WIKI_SEMANTIC": "0",
            "MEMORY_WIKI_RERANK_ENABLED": "0",
            "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0",
        })
        try:
            return _run_isolated(tmp, size, repetitions)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _run_isolated(tmp: str, size: int, repetitions: int) -> dict:
        module = _load_module()
        provider = module.MemoryWikiProvider()
        provider.initialize("audit-session", hermes_home=tmp, project_id="audit")
        ts = module.now()
        rows = [
            (
                f"audit-{index}",
                f"Synthetic archive record {index} stores marker token{index:05d}.",
                "benchmark", "active", 0.9, 0.8, "benchmark", "offline fixture",
                ts, ts, ts, 0, 0, f"audit-hash-{index}", "global", "global", 0.9,
            )
            for index in range(size)
        ]
        with provider._connect() as conn:
            conn.executemany(
                """INSERT INTO claims(
                    id,claim,topic,status,confidence,salience,source,evidence,
                    created_at,updated_at,freshness_at,access_count,last_accessed,hash,
                    scope,visibility_scope,quality
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        start = time.perf_counter()
        provider._rebuild_fts()
        rebuild_ms = (time.perf_counter() - start) * 1000
        _close(provider)

        started = time.perf_counter()
        provider = module.MemoryWikiProvider()
        provider.initialize("audit-session", hermes_home=tmp, project_id="audit")
        first_restart_ms = (time.perf_counter() - started) * 1000
        query_durations = []
        found = 0
        for index in range(repetitions):
            target = (index * 7919) % size
            query = f"token{target:05d}"
            started = time.perf_counter()
            result = provider._search(
                query, limit=5, retrieval_mode="fts", record_retrieval=False,
                apply_rerank=False,
            )
            query_durations.append((time.perf_counter() - started) * 1000)
            found += any(row["id"] == f"audit-{target}" for row in result)
        with closing(sqlite3.connect(provider.db_path)) as conn:
            fts_rows = conn.execute("SELECT count(*) FROM claims_fts").fetchone()[0]
        _close(provider)
        started = time.perf_counter()
        provider = module.MemoryWikiProvider()
        provider.initialize("audit-session", hermes_home=tmp, project_id="audit")
        steady_restart_ms = (time.perf_counter() - started) * 1000
        _close(provider)
        sorted_durations = sorted(query_durations)
        return {
            "fixture_claims": size,
            "repetitions": repetitions,
            "fts_rebuild_ms": round(rebuild_ms, 2),
            "first_restart_ms": round(first_restart_ms, 2),
            "steady_restart_ms": round(steady_restart_ms, 2),
            "recall_at_5": round(found / repetitions, 3),
            "query_p50_ms": round(statistics.median(query_durations), 2),
            "query_p95_ms": round(sorted_durations[max(0, int(repetitions * 0.95) - 1)], 2),
            "fts_rows": fts_rows,
        }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
