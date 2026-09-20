"""Full paired LongMemEval evidence-retrieval probe against production episodes.

Runs the actual claim ingestion, episode capture, and model-facing episode tool
in one fresh temporary database per question. It does not generate answers or
call OpenRouter/Qdrant. The fixed-budget comparison is five claims against
three claims plus two guarded episode excerpts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:
    from . import episodic_fallback_probe as prototype
except ImportError:
    import episodic_fallback_probe as prototype


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, min(len(values) - 1, int(len(values) * fraction) - 1))], 2)


@contextmanager
def _feature_env(strict_guard: bool):
    updates = {"MEMORY_WIKI_EPISODIC_ENABLED": "1", "MEMORY_WIKI_EPISODIC_SCOPE": "bot"}
    if strict_guard:
        updates["HERMES_SECURITY_STRICT"] = "1"
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _score(provider: Any, module: Any, case: dict[str, Any], top_k: int,
           episode_slots: int) -> dict[str, Any]:
    gold: set[tuple[str, int]] = set()
    claim_sources: dict[str, set[tuple[str, int]]] = defaultdict(set)
    episode_sources: dict[str, tuple[str, int]] = {}
    turns = accepted = queued = ingest_errors = 0
    secret_rejects = write_guard_rejects = read_guard_rejects = 0
    current: tuple[str, int] | None = None
    original_add = provider._add_claim
    original_inspect = provider._inspect_recall_text
    original_capture = module._episodic_memory.capture_turn

    def trace_add(*args: Any, **kwargs: Any) -> Any:
        nonlocal accepted, queued
        result = original_add(*args, **kwargs)
        if current is not None and isinstance(result, str):
            if result.startswith("c_"):
                claim_sources[result].add(current)
                accepted += 1
            elif result.startswith("rq_"):
                queued += 1
        return result

    def trace_guard(text: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal write_guard_rejects, read_guard_rejects
        result = original_inspect(text, **kwargs)
        if result.get("status") != "safe":
            source = kwargs.get("source", "")
            if source == "host:sync_turn":
                write_guard_rejects += 1
            elif source == "episodic:untrusted":
                read_guard_rejects += 1
        return result

    def trace_capture(capture_provider: Any, capture_module: Any, role: str,
                      content: str, *, session_id: str = "") -> str | None:
        result = original_capture(capture_provider, capture_module, role, content,
                                  session_id=session_id)
        if result and current is not None:
            episode_sources[result] = current
        return result

    provider._add_claim = trace_add
    provider._inspect_recall_text = trace_guard
    module._episodic_memory.capture_turn = trace_capture
    try:
        for session_id, index, turn, _ in prototype.official.chronological_turns(case):
            turns += 1
            current = (session_id, index)
            if turn.get("has_answer") is True:
                gold.add(current)
            role = str(turn["role"])
            content = turn["content"]
            if module.secret_scan(module.scrub_memory_artifacts(content)).get("raw_secret"):
                secret_rejects += 1
            try:
                provider.sync_turn(content if role == "user" else "",
                                   content if role == "assistant" else "",
                                   session_id=session_id)
            except Exception:
                ingest_errors += 1
            finally:
                current = None
    finally:
        provider._add_claim = original_add
        module._episodic_memory.capture_turn = original_capture
    claim_start = time.perf_counter()
    rows = provider._search(case["question"], limit=top_k, retrieval_mode="fts",
                            record_retrieval=False, apply_rerank=False)
    claim_ms = (time.perf_counter() - claim_start) * 1000
    tool_start = time.perf_counter()
    response = json.loads(provider.handle_tool_call(
        "memory_wiki_query_episodes", {"query": case["question"], "limit": episode_slots},
    ))
    episode_ms = (time.perf_counter() - tool_start) * 1000
    if not response.get("success") or not response.get("enabled"):
        raise RuntimeError(f"episode tool unavailable for {case['question_id']}")
    episode_rows = response.get("episodes", [])
    if len(episode_rows) > episode_slots or sum(len(r.get("content", "")) for r in episode_rows) > 800:
        raise AssertionError("production episode tool exceeded retrieval budget")
    for row in episode_rows:
        if row.get("trust_level") != "untrusted":
            raise AssertionError("episode lost its untrusted label")
    claim_turns = [claim_sources.get(str(row["id"]), set()) for row in rows]
    baseline = set().union(*claim_turns) if claim_turns else set()
    fixed_claims = set().union(*claim_turns[:top_k - episode_slots]) if claim_turns else set()
    episode_turns = {episode_sources[r["id"]] for r in episode_rows if r["id"] in episode_sources}
    fixed = fixed_claims | episode_turns
    supplement = baseline | episode_turns
    all_claim_turns = set().union(*claim_sources.values()) if claim_sources else set()
    return {
        "question_id": case["question_id"], "category": case["question_type"],
        "turns": turns, "gold_turns": len(gold),
        "gold_capture": len(gold & set(episode_sources.values())),
        "gold_claim_capture": len(gold & all_claim_turns),
        "episode_capture": len(episode_sources), "capture_rejects": turns - len(episode_sources),
        "secret_rejects": secret_rejects, "write_guard_rejects": write_guard_rejects,
        "read_guard_rejects": read_guard_rejects, "ingest_errors": ingest_errors,
        "accepted_claim_writes": accepted, "queued_claim_writes": queued,
        "baseline_hits": len(gold & baseline), "fixed_hits": len(gold & fixed),
        "supplement_hits": len(gold & supplement),
        "baseline_any": bool(gold & baseline), "fixed_any": bool(gold & fixed),
        "supplement_any": bool(gold & supplement),
        "baseline_all": gold <= baseline, "fixed_all": gold <= fixed,
        "supplement_all": gold <= supplement,
        "episodes_returned": len(episode_rows),
        "assistant_excerpts": sum(r["role"] == "assistant" for r in episode_rows),
        "prompt_chars": sum(len(r["content"]) for r in episode_rows),
        "claim_ms": round(claim_ms, 2), "episode_tool_ms": round(episode_ms, 2),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"questions": 0, "evidence_scored_questions": 0}
    scored = [r for r in rows if r["gold_turns"]]
    n = len(scored)
    gold = sum(r["gold_turns"] for r in scored)
    counts = ("turns", "gold_turns", "gold_capture", "gold_claim_capture",
              "episode_capture", "capture_rejects", "secret_rejects",
              "write_guard_rejects", "read_guard_rejects", "ingest_errors",
              "accepted_claim_writes", "queued_claim_writes", "baseline_hits",
              "fixed_hits", "supplement_hits", "episodes_returned",
              "assistant_excerpts", "prompt_chars")
    out: dict[str, Any] = {"questions": len(rows), "evidence_scored_questions": n}
    out.update({key: sum(r[key] for r in rows) for key in counts})
    for key in ("baseline_any", "fixed_any", "supplement_any",
                "baseline_all", "fixed_all", "supplement_all"):
        out[key] = round(sum(bool(r[key]) for r in scored) / n, 4) if n else None
    for key in ("baseline_hits", "fixed_hits", "supplement_hits"):
        out[key + "_per_gold"] = round(out[key] / gold, 4) if gold else None
    for key in ("claim_ms", "episode_tool_ms"):
        values = [r[key] for r in rows]
        out[key + "_p50"] = _percentile(values, .5)
        out[key + "_p95"] = _percentile(values, .95)
    return out


def run(dataset: Path, *, top_k: int = 5, episode_slots: int = 2,
        limit: int = 500, progress_every: int = 25) -> dict[str, Any]:
    if not 1 <= episode_slots < top_k <= 50:
        raise ValueError("invalid fixed retrieval budget")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
    cases, total = prototype.official.load_cases(dataset, 500)
    cases = cases[:limit]
    guard_available = importlib.util.find_spec("hermes_trust_core") is not None
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="memory-wiki-full-episode-") as temp:
        with prototype._isolated_home(temp):
            with _feature_env(guard_available):
                module = prototype._load_plugin()
                try:
                    for index, case in enumerate(cases):
                        provider = module.MemoryWikiProvider()
                        try:
                            provider.initialize(
                                f"benchmark-chat-{index}", hermes_home=str(Path(temp) / f"case-{index}"),
                                bot_id=f"benchmark-bot-{index}", project_id=f"case-{index}",
                            )
                            rows.append(_score(provider, module, case, top_k, episode_slots))
                        finally:
                            if provider._conn is not None:
                                provider._conn.close()
                                provider._conn = None
                        if progress_every and (index + 1) % progress_every == 0:
                            print(f"scored {index + 1}/{len(cases)}", file=sys.stderr, flush=True)
                finally:
                    sys.modules.pop(module.__name__, None)
    categories = sorted({r["category"] for r in rows})
    return {
        "dataset_sha256": sha,
        "official_oracle_sha256_match": sha == prototype.OFFICIAL_ORACLE_SHA256,
        "dataset_questions": total, "evaluated_questions": len(rows),
        "evidence_scored_questions": sum(bool(r["gold_turns"]) for r in rows),
        "comparison": "five FTS claims versus three FTS claims plus two production query_episodes excerpts",
        "episode_scope": "explicit bot; one isolated bot and database per question",
        "guard_mode": "strict shared guard" if guard_available else "non-strict local guard; shared core unavailable",
        "retrieval_mode": "offline FTS; no OpenRouter/Qdrant or answer generation",
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "overall": _aggregate(rows),
        "by_category": {name: _aggregate([r for r in rows if r["category"] == name]) for name in categories},
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--episode-slots", type=int, default=2)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, top_k=args.top_k, episode_slots=args.episode_slots,
                         limit=args.limit, progress_every=args.progress_every),
                     ensure_ascii=False, indent=2))
