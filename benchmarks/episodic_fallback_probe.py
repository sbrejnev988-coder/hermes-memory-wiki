"""Paired, isolated LongMemEval probe for a scoped raw-episode fallback.

This is benchmark code only. It captures host-supplied dialogue turns in a
temporary, owner-scoped FTS table, runs the actual `_ingest_text` claim path,
and compares top-K claims with guarded episode supplements. It does not add a
production tool, persist transcripts, use Qdrant, or generate answers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import statistics
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    from . import longmemeval_adapter as official
except ImportError:
    import longmemeval_adapter as official


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ORACLE_SHA256 = "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c"
_BENCH_ENV = {
    "HERMES_SECURITY_STRICT": "0",  # Local guard only; not a production safety verdict.
    "MEMORY_WIKI_SEMANTIC": "0", "MEMORY_WIKI_RERANK_ENABLED": "0",
    "MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE": "0", "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED": "0",
}


def _load_plugin() -> Any:
    name = "memory_wiki_episode_probe_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py",
                                                   submodule_search_locations=[str(ROOT)])
    if spec is None or spec.loader is None:
        raise RuntimeError("Memory Wiki module cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@contextmanager
def _isolated_home(home: str) -> Iterator[None]:
    settings = {"HERMES_HOME": home, **_BENCH_ENV}
    prior = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _select_cases(cases: list[dict[str, Any]], per_type: int) -> list[dict[str, Any]]:
    if per_type < 1:
        raise ValueError("per_type must be positive")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        if any(turn.get("has_answer") is True for session in case["haystack_sessions"] for turn in session):
            grouped[str(case["question_type"])].append(case)
    selected = [case for question_type in sorted(grouped) for case in grouped[question_type][:per_type]]
    return selected


class EpisodeStore:
    """Temporary owner-bound index; deliberately separate from durable claims."""

    def __init__(self, provider: Any, module: Any, *, ttl_days: int = 90,
                 max_rows: int = 5_000, max_bytes: int = 8_000_000) -> None:
        self.provider = provider
        self.module = module
        self.ttl_seconds = max(1, min(ttl_days, 365)) * 86400
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.stats = {"write_secret_rejects": 0, "write_guard_rejects": 0,
                      "write_empty_rejects": 0, "evicted_rows": 0}
        conn = provider._connect()
        with conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS benchmark_episodes(
                id TEXT PRIMARY KEY, content TEXT NOT NULL, role TEXT NOT NULL,
                source_session_id TEXT NOT NULL, source_turn INTEGER NOT NULL,
                owner_bot_id TEXT NOT NULL, owner_chat_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)""")
            conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS benchmark_episodes_fts
                USING fts5(id UNINDEXED, content, tokenize='unicode61')""")

    def _owner(self) -> tuple[str, str]:
        owner = self.provider._scoped_backup_owner()
        return owner["bot_id"], owner["chat_hash"]

    def add_turn(self, session_id: str, turn_index: int, role: str, text: str) -> str | None:
        # The benchmark calls this directly from a host-provided turn, never
        # from model tool arguments. Production needs the same attestation.
        if role not in {"user", "assistant"}:
            self.stats["write_empty_rejects"] += 1
            return None
        raw = self.module.scrub_memory_artifacts(str(text or ""))
        if self.module.secret_scan(raw).get("raw_secret"):
            self.stats["write_secret_rejects"] += 1
            return None
        cleaned = self.module.redact_secrets(raw).strip()
        if not cleaned:
            self.stats["write_empty_rejects"] += 1
            return None
        checked = self.provider._inspect_recall_text(
            cleaned, source="benchmark:host_turn", mem_type="episode", audit=False, max_len=1200,
        )
        if checked.get("status") != "safe":
            self.stats["write_guard_rejects"] += 1
            return None
        content = str(checked.get("content") or "")[:1200]
        if not content:
            self.stats["write_guard_rejects"] += 1
            return None
        owner_bot, owner_chat = self._owner()
        episode_id = "be_" + hashlib.sha256(
            f"{owner_chat}\0{session_id}\0{turn_index}\0{role}".encode()
        ).hexdigest()[:24]
        stamp = int(time.time())
        conn = self.provider._connect()
        with conn:
            inserted = conn.execute("""INSERT OR IGNORE INTO benchmark_episodes
                (id,content,role,source_session_id,source_turn,owner_bot_id,
                 owner_chat_hash,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (episode_id, content, role, session_id, turn_index, owner_bot,
                 owner_chat, stamp, stamp + self.ttl_seconds))
            if inserted.rowcount:
                conn.execute("INSERT INTO benchmark_episodes_fts(id,content) VALUES(?,?)",
                             (episode_id, content))
            self._trim(conn, owner_bot, owner_chat, stamp)
        return episode_id

    def _trim(self, conn: sqlite3.Connection, owner_bot: str, owner_chat: str, stamp: int) -> None:
        expired = conn.execute("""SELECT id FROM benchmark_episodes
            WHERE owner_bot_id=? AND owner_chat_hash=? AND expires_at<=?""",
            (owner_bot, owner_chat, stamp)).fetchall()
        for row in expired:
            self._delete(conn, str(row["id"]))
        while True:
            row = conn.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(content)),0) AS bytes
                FROM benchmark_episodes WHERE owner_bot_id=? AND owner_chat_hash=?""",
                (owner_bot, owner_chat)).fetchone()
            if row["n"] <= self.max_rows and row["bytes"] <= self.max_bytes:
                break
            oldest = conn.execute("""SELECT id FROM benchmark_episodes
                WHERE owner_bot_id=? AND owner_chat_hash=? ORDER BY created_at,id LIMIT 1""",
                (owner_bot, owner_chat)).fetchone()
            if oldest is None:
                break
            self._delete(conn, str(oldest["id"]))
            self.stats["evicted_rows"] += 1

    @staticmethod
    def _delete(conn: sqlite3.Connection, episode_id: str) -> None:
        conn.execute("DELETE FROM benchmark_episodes_fts WHERE id=?", (episode_id,))
        conn.execute("DELETE FROM benchmark_episodes WHERE id=?", (episode_id,))

    def search(self, query: str, *, slots: int = 2, max_chars: int = 800) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        started = time.perf_counter()
        owner_bot, owner_chat = self._owner()
        conn = self.provider._connect()
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        stats = {"candidates": 0, "guard_rejects": 0, "secret_rejects": 0,
                 "assistant_excerpts": 0, "prompt_chars": 0, "search_ms": 0.0}
        for mode in ("and", "or"):
            fts_query = self.module.safe_fts_query(query, mode=mode)
            if not fts_query:
                continue
            try:
                rows = conn.execute("""SELECT e.*, bm25(benchmark_episodes_fts) AS rank
                    FROM benchmark_episodes_fts JOIN benchmark_episodes e
                      ON e.id=benchmark_episodes_fts.id
                    WHERE benchmark_episodes_fts MATCH ? AND e.owner_bot_id=?
                      AND e.owner_chat_hash=? AND e.expires_at>?
                    ORDER BY rank LIMIT 50""",
                    (fts_query, owner_bot, owner_chat, int(time.time()))).fetchall()
            except sqlite3.OperationalError:
                continue
            for row in rows:
                episode_id = str(row["id"])
                if episode_id in seen:
                    continue
                seen.add(episode_id)
                stats["candidates"] += 1
                # Defense in depth after SQL ACL, before model-facing text.
                if row["owner_bot_id"] != owner_bot or row["owner_chat_hash"] != owner_chat:
                    continue
                if self.module.secret_scan(row["content"]).get("raw_secret"):
                    stats["secret_rejects"] += 1
                    continue
                checked = self.provider._inspect_recall_text(
                    row["content"], source="benchmark:episode_recall", mem_type="episode",
                    item_id=episode_id, audit=False, max_len=350,
                )
                if checked.get("status") != "safe":
                    stats["guard_rejects"] += 1
                    continue
                content = str(checked.get("content") or "")[:350]
                if not content or len(content) + stats["prompt_chars"] > max_chars:
                    continue
                output.append({"id": episode_id, "session_id": row["source_session_id"],
                               "turn_index": int(row["source_turn"]), "role": row["role"],
                               "chars": len(content)})
                stats["prompt_chars"] += len(content)
                if row["role"] == "assistant":
                    stats["assistant_excerpts"] += 1
                if len(output) >= slots:
                    break
            if len(output) >= slots:
                break
        stats["search_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return output, stats


def _score_case(provider: Any, module: Any, case: dict[str, Any], top_k: int,
                episode_slots: int) -> dict[str, Any]:
    store = EpisodeStore(provider, module)
    claim_sources: dict[str, set[tuple[str, int]]] = defaultdict(set)
    episode_sources: dict[str, tuple[str, int]] = {}
    gold_turns: set[tuple[str, int]] = set()
    accepted = queued = ingest_errors = 0
    current: tuple[str, int] | None = None
    original_add = provider._add_claim

    def capture_claim(*args: Any, **kwargs: Any) -> Any:
        nonlocal accepted, queued
        result = original_add(*args, **kwargs)
        if current is not None and isinstance(result, str):
            if result.startswith("c_"):
                claim_sources[result].add(current)
                accepted += 1
            elif result.startswith("rq_"):
                queued += 1
        return result

    provider._add_claim = capture_claim
    try:
        for session_id, turn_index, turn, _ in official.chronological_turns(case):
            if turn.get("has_answer") is True:
                gold_turns.add((session_id, turn_index))
            role = str(turn["role"])
            episode_id = store.add_turn(session_id, turn_index, role, turn["content"])
            if episode_id:
                episode_sources[episode_id] = (session_id, turn_index)
            current = (session_id, turn_index)
            try:
                provider._ingest_text(turn["content"], source=f"turn:{role}:{session_id}", max_claims=8 if role == "user" else 2)
            except Exception:
                ingest_errors += 1
            finally:
                current = None
    finally:
        provider._add_claim = original_add
    baseline_rows = provider._search(case["question"], limit=top_k, retrieval_mode="fts",
                                     record_retrieval=False, apply_rerank=False)
    claim_turns = [claim_sources.get(str(row["id"]), set()) for row in baseline_rows]
    episodes, episode_stats = store.search(case["question"], slots=episode_slots)
    episode_turns = [episode_sources.get(row["id"]) for row in episodes]
    episode_turn_set = {turn for turn in episode_turns if turn is not None}
    def retrieved_claims(rows: list[set[tuple[str, int]]]) -> set[tuple[str, int]]:
        return set().union(*rows) if rows else set()
    baseline = retrieved_claims(claim_turns)
    supplement = baseline | episode_turn_set
    fixed = retrieved_claims(claim_turns[:max(0, top_k - episode_slots)]) | episode_turn_set
    return {
        "question_id": case["question_id"], "question_type": case["question_type"],
        "gold_turns": len(gold_turns), "gold_episode_coverage": len(gold_turns & set(episode_sources.values())),
        "gold_claim_coverage": len(gold_turns & retrieved_claims(list(claim_sources.values()))),
        "accepted_claim_writes": accepted, "queued_claim_writes": queued,
        "ingest_errors": ingest_errors,
        "baseline_any": bool(gold_turns & baseline) if gold_turns else None,
        "baseline_all": gold_turns <= baseline if gold_turns else None,
        "supplement_any": bool(gold_turns & supplement) if gold_turns else None,
        "supplement_all": gold_turns <= supplement if gold_turns else None,
        "fixed_any": bool(gold_turns & fixed) if gold_turns else None,
        "fixed_all": gold_turns <= fixed if gold_turns else None,
        "baseline_hits": len(gold_turns & baseline),
        "supplement_hits": len(gold_turns & supplement),
        "fixed_hits": len(gold_turns & fixed),
        "episodes_returned": len(episodes), "episode_stats": episode_stats,
        "episode_write_stats": dict(store.stats),
    }


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row[field] is not None]
    return round(statistics.mean(values), 4) if values else None


def run(dataset: Path, *, per_type: int = 5, top_k: int = 5, episode_slots: int = 2) -> dict[str, Any]:
    if not 1 <= top_k <= 50 or not 1 <= episode_slots <= min(5, top_k):
        raise ValueError("invalid retrieval budget")
    cases, total = official.load_cases(dataset, 500)
    selected = _select_cases(cases, per_type)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="memory-wiki-episode-probe-") as tmp:
        with _isolated_home(tmp):
            module = _load_plugin()
            try:
                for index, case in enumerate(selected):
                    provider = module.MemoryWikiProvider()
                    try:
                        provider.initialize(f"episode-probe-{index}", hermes_home=str(Path(tmp) / f"case-{index}"),
                                            bot_id="episode-probe", project_id=f"case-{index}")
                        results.append(_score_case(provider, module, case, top_k, episode_slots))
                    finally:
                        if provider._conn is not None:
                            provider._conn.close()
                            provider._conn = None
            finally:
                sys.modules.pop(module.__name__, None)
    scored = [row for row in results if row["gold_turns"]]
    return {
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "official_oracle_sha256_match": hashlib.sha256(dataset.read_bytes()).hexdigest() == OFFICIAL_ORACLE_SHA256,
        "dataset_questions": total, "sampled_questions": len(selected),
        "selection": f"first {per_type} answer-labeled questions per question_type",
        "ingestion": "production-like _ingest_text plus temporary host-supplied raw episodes",
        "scope": "exact bot and chat hash; no cross-scope fallback",
        "guard_mode": "non-strict local guard in isolated benchmark; not a production security verdict",
        "retrieval_mode": "fts", "top_k": top_k, "episode_slots": episode_slots,
        "baseline_any": _mean(scored, "baseline_any"), "baseline_all": _mean(scored, "baseline_all"),
        "supplement_any": _mean(scored, "supplement_any"), "supplement_all": _mean(scored, "supplement_all"),
        "fixed_any": _mean(scored, "fixed_any"), "fixed_all": _mean(scored, "fixed_all"),
        "gold_turns": sum(row["gold_turns"] for row in scored),
        "gold_episode_coverage": sum(row["gold_episode_coverage"] for row in scored),
        "gold_claim_coverage": sum(row["gold_claim_coverage"] for row in scored),
        "assistant_excerpts": sum(row["episode_stats"]["assistant_excerpts"] for row in results),
        "guard_rejects": sum(row["episode_stats"]["guard_rejects"] for row in results),
        "write_secret_rejects": sum(row["episode_write_stats"]["write_secret_rejects"] for row in results),
        "ingest_errors": sum(row["ingest_errors"] for row in results),
        "prompt_chars": sum(row["episode_stats"]["prompt_chars"] for row in results),
        "episode_search_p50_ms": round(statistics.median(row["episode_stats"]["search_ms"] for row in results), 2) if results else None,
        "episode_search_p95_ms": sorted(row["episode_stats"]["search_ms"] for row in results)[max(0, int(len(results)*.95)-1)] if results else None,
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Locally downloaded official LongMemEval oracle JSON")
    parser.add_argument("--per-type", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--episode-slots", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, per_type=args.per_type, top_k=args.top_k,
                         episode_slots=args.episode_slots), ensure_ascii=False, indent=2))
