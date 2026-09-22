"""Paired, stratified LongMemEval oracle retrieval probe.

Runs identical public cases through isolated FTS-only and live hybrid profiles.
Only question IDs and retrieval metrics are saved; no conversation text or keys.
The underlying adapter creates random physical Qdrant collections and verifies
their removal. This is evidence retrieval, not official answer QA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path

import longmemeval_adapter as base


def select_cases(dataset: Path, *, per_type: int, seed: int) -> tuple[list[dict], dict]:
    cases, total = base.load_cases(dataset, 10**9)
    groups: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        groups[case["question_type"]].append(case)
    rng = random.Random(seed)
    selected = []
    for kind in sorted(groups):
        if len(groups[kind]) < per_type:
            raise ValueError(f"Too few questions for {kind}")
        selected.extend(rng.sample(groups[kind], per_type))
    selected.sort(key=lambda case: case["question_id"])
    return selected, {"dataset_questions": total, "type_counts": {k: len(v) for k, v in sorted(groups.items())}}


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 2)


def summary(rows: list[dict], mode: str) -> dict:
    own = [row[mode] for row in rows if isinstance(row.get(mode), dict)]
    evidence = [row for row in own if row.get("evidence_scored")]
    times = [float(row["search_ms"]) for row in own if isinstance(row.get("search_ms"), (int, float))]
    return {
        "completed": len(own), "errors": sum(mode + "_error" in row for row in rows),
        "evidence_scored": len(evidence),
        "session_recall_all_at_5": base._mean(evidence, "session_recall_all"),
        "session_recall_any_at_5": base._mean(evidence, "session_recall_any"),
        "session_mrr_at_5": base._mean(evidence, "reciprocal_rank"),
        "turn_recall_all_at_5": base._mean(evidence, "turn_recall_all"),
        "search_p50_ms": percentile(times, .5), "search_p95_ms": percentile(times, .95),
        "accepted_turns": sum(row.get("accepted_turns", 0) for row in own),
        "queued_turns": sum(row.get("queued_turns", 0) for row in own),
        "skipped_turns": sum(row.get("skipped_turns", 0) for row in own),
        "embedding_operations": sum(row.get("embedding_operations", 0) for row in own),
        "embedding_input_chars": sum(row.get("embedding_input_chars", 0) for row in own),
    }


def compact(row: dict) -> dict:
    return {key: row.get(key) for key in (
        "question_id", "question_type", "evidence_scored", "session_recall_all",
        "session_recall_any", "reciprocal_rank", "turn_recall_all", "search_ms",
        "accepted_turns", "queued_turns", "skipped_turns", "ingest_error_counts",
        "embedding_operations", "embedding_input_chars", "semantic_reindex",
        "isolated_collection", "isolated_collection_removed",
    ) if key in row}


def run(dataset: Path, env_file: Path, output: Path, *, per_type: int = 5, seed: int = 20260920) -> dict:
    selected, counts = select_cases(dataset, per_type=per_type, seed=seed)
    env = base._env_file_values(env_file)
    if (env.get("MEMORY_WIKI_EMBED_PROVIDER") != "openrouter"
            or not (env.get("MEMORY_WIKI_EMBED_API_KEY") or env.get("OPENROUTER_API_KEY"))
            or not env.get("MEMORY_WIKI_QDRANT_URL")):
        raise ValueError("Explicit env file must configure OpenRouter embeddings and Qdrant")
    run_token = uuid.uuid4().hex[:16]
    rows = []
    report = {
        "method": "5 seeded questions per official question type; identical raw-turn claim ingestion; FTS-only and live OpenRouter+Qdrant hybrid in separate temporary homes; top-k=5",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "seed": seed, "per_type": per_type, "selected": len(selected), **counts,
        "question_ids": [case["question_id"] for case in selected],
        "rows": rows,
        "limitations": [
            "Measures evidence retrieval, not official answer QA.",
            "Whole raw turns pass through claim quality policy; queued turns are not indexed.",
            "OpenRouter embedding responses do not expose per-call tokens or cost through this plugin; character counts are measured inputs, not tokens.",
            "Separate temporary profiles permit state isolation; accepted/queued turn counts should be compared per case for parity.",
        ],
    }

    def save() -> None:
        report["fts"] = summary(rows, "fts")
        report["hybrid"] = summary(rows, "hybrid")
        paired = [row for row in rows if "fts" in row and "hybrid" in row]
        report["paired_count"] = len(paired)
        report["ingestion_parity_count"] = sum(
            row["fts"]["accepted_turns"] == row["hybrid"]["accepted_turns"]
            and row["fts"]["queued_turns"] == row["hybrid"]["queued_turns"]
            for row in paired
        )
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="memory-wiki-paired-lme-") as tmp:
        with base._isolated_environment(tmp):
            module = base._load_plugin()
            try:
                for index, case in enumerate(selected):
                    row = {"question_id": case["question_id"], "question_type": case["question_type"]}
                    provider = None
                    try:
                        provider = module.MemoryWikiProvider()
                        provider.initialize(
                            f"paired-lme-{index}", hermes_home=str(Path(tmp) / f"fts-{index:04d}"),
                            project_id=f"paired-lme-{index}", bot_id="longmemeval-benchmark",
                        )
                        row["fts"] = compact(base._evaluate_case(provider, case, 5, None, retrieval_mode="fts"))
                    except Exception as exc:
                        row["fts_error"] = type(exc).__name__
                    finally:
                        if provider is not None:
                            connection = getattr(provider, "_conn", None)
                            if connection is not None:
                                connection.close()
                                provider._conn = None
                    try:
                        hybrid = base._run_semantic_case(case, index, 5, None, tmp=tmp, env_values=env, run_token=run_token)
                        row["hybrid"] = compact(hybrid)
                    except Exception as exc:
                        row["hybrid_error"] = type(exc).__name__
                    rows.append(row)
                    save()
                    print(f"{index + 1}/{len(selected)} {case['question_id']}: FTS={'fts' in row} hybrid={'hybrid' in row}", flush=True)
            finally:
                sys.modules.pop(module.__name__, None)
        # Read-only ownership check: any collection with our random run token
        # indicates cleanup failed. Never touch active collection aliases.
        with base._isolated_environment(tmp, {**env, "MEMORY_WIKI_SEMANTIC": "1",
                                               "MEMORY_WIKI_QDRANT_ALIAS_MODE": "physical"}):
            check_module = base._load_plugin()
            try:
                names = base._qdrant_collection_names(check_module)
                leftovers = sorted(name for name in names if name.startswith(f"memory_wiki_lme_{run_token}_"))
            finally:
                sys.modules.pop(check_module.__name__, None)
        report["temporary_qdrant_collections_remaining"] = leftovers
        save()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-type", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()
    if args.per_type < 1 or args.output.resolve() in (args.dataset.resolve(), args.env_file.resolve()):
        parser.error("Invalid --per-type or output path")
    result = run(args.dataset, args.env_file, args.output, per_type=args.per_type, seed=args.seed)
    print(json.dumps({k: result[k] for k in ("paired_count", "ingestion_parity_count", "fts", "hybrid", "temporary_qdrant_collections_remaining")}, indent=2))


if __name__ == "__main__":
    main()
